"""Intake questionnaire: decides the assessment type from the client's answers, so nobody passes flags.

    python <skill>/scripts/intake.py --questions          print the questions (data/intake.json) for the agent to ask
    python <skill>/scripts/intake.py --answers FILE|JSON   record the answers and apply them to assessment.json
    python <skill>/scripts/intake.py                       show the recorded answers and what they set
    python <skill>/scripts/intake.py --solution ID --environments "dev, prod"   one solution's own environment list
    python <skill>/scripts/intake.py --confirm-environments                     the user confirmed the environment lists

Answers are a JSON object keyed by question id, e.g.
    {"goal": "lift-and-shift", "os_today": "both", "platform": "Proxmox, vendor-managed", "db_engine": "keep",
     "db_hosting": "ec2", "aws_native": "later", "code_access": "sample", "estate_total": 85,
     "estate_list": "docs/estate.csv", "compliance": "", "team": "3 engineers from 2026-11-02"}
Option answers must be one of the listed values; free-text answers are stored as given. A question the user could not
answer is stored as "unknown" and becomes an open question in the report: nothing is filled in by guessing.

Lift-and-shift track (goal = lift-and-shift): ten more questions feed the hours calculator (estimate_hours.py): scope_confirm,
scope_exclusions, work_items, retarget_to, regression_tests, estimate_basis, environments, environments_differ, pipeline_scope,
pipeline_solutions. require_hours() stops solutions.py / estimate_hours.py / build_check.py while one of them that applies has no answer:
"unknown" is accepted only when the user says it, and then the figure stays UNKNOWN / assumed in the report.
"""
import argparse
import json
import os
import re
import sys

from _common import ASSESSMENT_TYPES, CONFIG_NAME, data, load_config, save_config, utf8_stdout

WORK_ITEMS = ("build_artifacts", "cicd_secrets", "retarget", "validation_cutover")  # keys of data/hours.json "items"
HOURS_QUESTIONS = ("scope_confirm", "scope_exclusions", "work_items", "retarget_to", "regression_tests", "estimate_basis", "environments",
                   "environments_differ", "pipeline_scope", "pipeline_solutions")
HOSTING = {"lift-and-shift": "lift-and-shift", "modernize": "modernize", "compare": "modernize"}
DATABASE = {"keep": "none", "postgresql": "postgresql", "dual": "dual", "later": "none", "unknown": "none"}


def questions():
    return data("intake.json")["questions"]


def split_envs(text):
    if isinstance(text, list):
        text = ",".join(text)
    return [x.strip() for x in re.split(r"[;,/+]|\band\b", str(text or "")) if x.strip() and x.strip().lower() not in ("unknown", "none")]


def asked(q, ans):
    """A question is asked when every `when` condition holds; a list value means any of them, and a multi answer matches when it contains the value."""
    for k, v in (q.get("when") or {}).items():
        have = ans.get(k)
        have = have if isinstance(have, list) else [have]
        if not any(x in have for x in (v if isinstance(v, list) else [v])):
            return False
    if q["id"] == "environments_differ" and not split_envs(ans.get("environments")):
        return False  # no environment list: nothing to differ
    return True


def validate(ans):
    errs = []
    for q in questions():
        if not asked(q, ans):
            continue
        v = ans.get(q["id"])
        if q.get("options") and v not in (None, "", "unknown"):
            allowed = [o["value"] for o in q["options"]]
            for x in (v if isinstance(v, list) else [v]):
                if x not in allowed:
                    errs.append(f"{q['id']}: '{x}' is not one of {', '.join(allowed)}")
    unknown = set(ans) - {q["id"] for q in questions()}
    if unknown:
        errs.append("unknown question ids: " + ", ".join(sorted(unknown)))
    return errs


def apply(cfg, ans):
    """Answers -> assessment.json fields. Returns the list of changes, for the summary."""
    changes = []

    def put(path, value):
        cur = cfg
        keys = path.split(".")
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        if cur.get(keys[-1]) != value:
            cur[keys[-1]] = value
            changes.append(f"{path} = {value!r}")

    if isinstance(ans.get("work_items"), str):  # "a, b" -> ["a", "b"]
        ans["work_items"] = [x.strip() for x in ans["work_items"].split(",") if x.strip()]
    prev = cfg.get("intake") or {}
    for keep in ("solutions", "environments_confirmed"):  # set by --solution / --confirm-environments, not by the questionnaire
        if keep in prev and keep not in ans:
            ans[keep] = prev[keep]
    if "environments" in ans and split_envs(ans["environments"]) != split_envs(prev.get("environments")):
        ans["environments_confirmed"] = False  # a changed list must be confirmed again
    goal = ans.get("goal") or "unknown"
    if goal in HOSTING:
        put("assessment_type", goal)
        put("scenario.hosting", HOSTING[goal])
    if ans.get("db_engine"):
        put("scenario.database", DATABASE.get(ans["db_engine"], "none"))
    if ans.get("db_hosting"):
        put("scenario.db_hosting", ans["db_hosting"])
    if ans.get("platform"):
        put("current_hosting", str(ans["platform"]).strip())
    if ans.get("compliance"):
        put("compliance", [x.strip() for x in re.split(r"[;,]", str(ans["compliance"])) if x.strip()])
    team = str(ans.get("team") or "")
    m = re.search(r"\b(\d{1,3})\s*(engineers?|devs?|developers?|people)\b", team, re.I)
    if m:
        put("scenario.engineers", int(m.group(1)))
    m = re.search(r"\b(20\d\d-\d\d-\d\d)\b", team)
    if m:
        put("scenario.start_date", m.group(1))
    total = ans.get("estate_total")
    if total not in (None, "", "unknown"):
        try:
            ans["estate_total"] = int(str(total).strip())
        except ValueError:
            pass
    put("intake", ans)
    return changes


def unanswered(cfg):
    """Required questions with no answer or "unknown" (the report lists them as open questions)."""
    ans = cfg.get("intake") or {}
    if not ans:
        return []
    return [q for q in questions() if asked(q, ans) and ans.get(q["id"]) in (None, "", "unknown") and "optional" not in q["ask"]]


def selected(cfg):
    """The work items of the hours calculator that the intake selected (lift-and-shift track)."""
    return [x for x in ((cfg.get("intake") or {}).get("work_items") or []) if x in WORK_ITEMS]


def solution_settings(cfg, sid):
    return ((cfg.get("intake") or {}).get("solutions") or {}).get(sid) or {}


def environments_of(cfg, sid):
    """(list of environments, confirmed?) of a solution: its own list, else the default list, else [] (UNKNOWN: 1 per solution is assumed)."""
    it = cfg.get("intake") or {}
    own = solution_settings(cfg, sid).get("environments")
    envs = own if own else split_envs(it.get("environments"))
    return envs, bool(it.get("environments_confirmed")) and bool(envs)


def hours_gaps(cfg):
    """Hours-calculator questions that apply and have no answer at all. 'unknown' is an answer (the user said it); a blank is not."""
    ans = cfg.get("intake") or {}
    return [q for q in questions() if q["id"] in HOURS_QUESTIONS and asked(q, ans) and ans.get(q["id"]) in (None, "", [])]


def require_hours(cfg, who):
    """Gate of the lift-and-shift hours calculator: stop while one of its questions is unanswered. Nothing is assumed."""
    gaps = hours_gaps(cfg)
    if gaps:
        sys.exit(f"{who}: {len(gaps)} intake question(s) for the hours calculator are unanswered; nothing is assumed. Ask the user (intake.py --questions) "
                 "and record the answers with intake.py --answers; 'unknown' only if the user says it:\n  "
                 + "\n  ".join(f"{q['id']}: {q['ask'][:110]}" for q in gaps))


def summary(cfg):
    ans = cfg.get("intake") or {}
    t = cfg.get("assessment_type")
    out = [f"ASSESSMENT TYPE: {ASSESSMENT_TYPES.get(t, 'not set: run the intake questionnaire')}"]
    if t:
        sc = cfg.get("scenario", {})
        out.append(f"SCENARIO: hosting {sc.get('hosting')} · database code {sc.get('database')} · database hosting {sc.get('db_hosting', 'not set')}")
        out.append("REPORT: " + {"lift-and-shift": "lift-and-shift report (landing on AWS: network, DNS, mail, file shares, identity, jobs); "
                                                   "Linux and .NET modernization findings summarised as future work",
                                 "modernize": "migration and modernization report",
                                 "compare": "migration and modernization report, lift-and-shift costed beside it"}[t])
        nat = ans.get("aws_native", "no")
        out.append("AWS MANAGED SERVICES: " + {"no": "not in scope", "later": "listed as future options, outside the estimate",
                                               "now": "in scope: their code changes are added to the estimate"}.get(nat, nat))
        if t == "lift-and-shift":
            items = selected(cfg)
            out.append("EFFORT MODEL: hours calculator (estimate_hours.py): developer hours, AI-assisted, 8 h/day, 20% buffer; work items: "
                       + (", ".join(items) if items else "none selected yet (intake: work_items)"))
            envs = split_envs(ans.get("environments"))
            out.append("ENVIRONMENTS: " + (", ".join(envs) if envs else "UNKNOWN: 1 per solution is assumed")
                       + (" (confirmed)" if ans.get("environments_confirmed") and envs else " (NOT confirmed)"))
            gaps = hours_gaps(cfg)
            if gaps:
                out.append("HOURS QUESTIONS NOT ANSWERED: " + ", ".join(q["id"] for q in gaps))
        if ans.get("code_access") == "sample":
            out.append(f"ESTATE: sample access; whole estate {ans.get('estate_total', 'unknown')} repositories; list: {ans.get('estate_list') or 'none given'}"
                       " -> run extrapolate_estate.py after estimate_effort.py")
        missing = [q["id"] for q in unanswered(cfg)]
        if missing:
            out.append("UNANSWERED (open questions in the report): " + ", ".join(missing))
    return "\n".join(out)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", action="store_true", help="print the questionnaire as JSON")
    ap.add_argument("--answers", help="answers as a JSON file path or a JSON string")
    ap.add_argument("--solution", help="solution id (see solutions.py) to set environments for")
    ap.add_argument("--environments", help="comma-separated environments of that solution, e.g. 'dev, prod'")
    ap.add_argument("--confirm-environments", action="store_true", help="the user confirmed the environment lists")
    a = ap.parse_args()
    if a.questions:
        print(json.dumps(questions(), indent=1, ensure_ascii=False))
        return
    root, cfg = load_config()
    if a.answers:
        raw = open(a.answers, encoding="utf-8").read() if os.path.exists(a.answers) else a.answers
        ans = json.loads(raw)
        errs = validate(ans)
        if errs:
            sys.exit("intake answers rejected:\n  " + "\n  ".join(errs))
        changes = apply(cfg, ans)
        save_config(root, cfg)
        print(f"saved to {CONFIG_NAME}: " + ("; ".join(c for c in changes if not c.startswith("intake =")) or "no change"))
    if a.solution or a.confirm_environments:
        it = cfg.setdefault("intake", {})
        msg = []
        if a.solution and a.environments is not None:
            it.setdefault("solutions", {}).setdefault(a.solution, {})["environments"] = split_envs(a.environments)
            it["environments_confirmed"] = False  # a changed list must be confirmed again
            msg.append(f"{a.solution}: environments {split_envs(a.environments) or 'UNKNOWN'} (confirm again)")
        if a.confirm_environments:
            it["environments_confirmed"] = True
            msg.append("environments confirmed")
        save_config(root, cfg)
        print(f"saved to {CONFIG_NAME}: " + "; ".join(msg))
    print(summary(cfg))


if __name__ == "__main__":
    main()
