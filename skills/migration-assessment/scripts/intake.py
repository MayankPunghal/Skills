"""Intake questionnaire: decides the assessment type from the client's answers, so nobody passes flags.

    python <skill>/scripts/intake.py --questions          print the questions (data/intake.json) for the agent to ask
    python <skill>/scripts/intake.py --answers FILE|JSON   record the answers and apply them to assessment.json
    python <skill>/scripts/intake.py                       show the recorded answers and what they set

Answers are a JSON object keyed by question id, e.g.
    {"goal": "lift-and-shift", "os_today": "both", "platform": "Proxmox, vendor-managed", "db_engine": "keep",
     "db_hosting": "ec2", "aws_native": "later", "code_access": "sample", "estate_total": 85,
     "estate_list": "docs/estate.csv", "compliance": "", "team": "3 engineers from 2026-11-02"}
Option answers must be one of the listed values; free-text answers are stored as given. A question the user could not
answer is stored as "unknown" and becomes an open question in the report: nothing is filled in by guessing.
"""
import argparse
import json
import os
import re
import sys

from _common import ASSESSMENT_TYPES, CONFIG_NAME, data, load_config, save_config, utf8_stdout

HOSTING = {"lift-and-shift": "lift-and-shift", "modernize": "modernize", "compare": "modernize"}
DATABASE = {"keep": "none", "postgresql": "postgresql", "dual": "dual", "later": "none", "unknown": "none"}


def questions():
    return data("intake.json")["questions"]


def asked(q, ans):
    return all(ans.get(k) == v for k, v in (q.get("when") or {}).items())


def validate(ans):
    errs = []
    for q in questions():
        if not asked(q, ans):
            continue
        v = ans.get(q["id"])
        if q.get("options") and v not in (None, "", "unknown") and v not in [o["value"] for o in q["options"]]:
            errs.append(f"{q['id']}: '{v}' is not one of {', '.join(o['value'] for o in q['options'])}")
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
    print(summary(cfg))


if __name__ == "__main__":
    main()
