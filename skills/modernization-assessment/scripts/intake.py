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

Recording what the user and the client say (both tracks; from lift-and-shift-assessment 1.1.0):

    python <skill>/scripts/intake.py --pending [--stage S]        the questions that apply now and are unanswered (ask these)
    python <skill>/scripts/intake.py --check                      exit code 1 while a question that applies is unanswered
    python <skill>/scripts/intake.py --solution ID [--environments "dev, prod"] [--ci yes|no|unknown] [--note TEXT]
    python <skill>/scripts/intake.py --finalize "<who said so>"   the user said the document is final (until then everything is DRAFT); --reopen
    python <skill>/scripts/intake.py --client-update "TOPIC" "ANSWER" "EFFECT ON THIS PLAN"
                                                                  what the client said on a call (document 1.1 and sheet ClientAnswers);
                                                                  the same topic again replaces its row; --remove-client-update TOPIC drops it
    python <skill>/scripts/intake.py --release-step "STEP" "WHAT HAPPENS"
                                                                  how releases are built and deployed today, one step per call, in order
                                                                  (section 7 and sheet ReleaseToday); --clear-release-steps starts again
    python <skill>/scripts/intake.py --branch-note REPO "WHY THIS BRANCH"
                                                                  why a branch was chosen for a repository (sheet Branches)
    python <skill>/scripts/intake.py --open-question "QUESTION" "WHY IT MATTERS" "WHO ANSWERS" [--status open|waiting|closed]
                                                                  an extra item for build_open_questions.py
    python <skill>/scripts/intake.py --decision "TEXT" [--source "client call, <date>"]
                                                                  a key decision, logged in assessment/documents/decision-log.md

Lift-and-shift guardrail: scan_repo.py, solutions.py, build_check.py, config_template.py, estimate_hours.py and build_doc.py call require()
and stop while a question that applies is unanswered. Questions have a stage: before_scan (asked right after discovery; the default),
after_scan (only when the scan found the thing the question is about: when_found), after_build (after the static build check).
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

from _common import ASSESSMENT_TYPES, CONFIG_NAME, OUT, data, load_config, load_state, read_json, save_config, utf8_stdout

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


def signals(root):
    """What the scan, the third-party step and the build check found: rule ids and named signals. Evidence for the when_found questions."""
    out = {}

    def add(k, n=1):
        out[k] = out.get(k, 0) + n

    for f in glob.glob(os.path.join(root, OUT, "findings", "*.json")):
        for x in read_json(f, []) or []:
            add(x["rule"].split(":")[0])
    for f in glob.glob(os.path.join(root, OUT, "scan", "*.json")):
        sc = read_json(f, {}) or {}
        if (sc.get("network") or {}).get("inbound"):
            add("inbound-public", len(sc["network"]["inbound"]))
        if sc.get("scheduled_jobs"):
            add("scheduled-jobs", len(sc["scheduled_jobs"]))
    tp = read_json(os.path.join(root, OUT, "solutions", "third_party.json"), {}) or {}
    for s in tp.get("solutions", []):
        for i in s["licensed_and_integrations"]:
            if i["kind"] == "licensed component":
                add("licensed-components")
            if i["rekey"]:
                add("rekey-integrations")
    idx = read_json(os.path.join(root, OUT, "solutions", "index.json"), {}) or {}
    if idx.get("loose_projects"):
        add("loose-projects", len(idx["loose_projects"]))
    bc = read_json(os.path.join(root, OUT, "build", "index.json"), {}) or {}
    for s in bc.get("solutions", []):
        if s["static"]["status"] == "BLOCKED":
            add("build-blocked")
    return out


def evidence(q, sig):
    return ", ".join(f"{k} x{sig[k]}" for k in q.get("when_found", []) if k in sig)


def applies(q, ans, sig):
    if not asked(q, ans):
        return False
    wf = q.get("when_found")
    return not wf or any(k in sig for k in wf)


def answered(ans, qid):
    v = ans.get(qid)
    return v not in (None, "", [])


def data_ready(stage, st):
    """Whether the data a stage's questions depend on exists yet (the when_found questions need the scan, and so on)."""
    repos = [r for r, v in st["repos"].items() if v.get("scope") != "out"]
    steps = st.get("steps", {})
    if stage == "before_scan":
        return True
    scanned = bool(repos) and all(st["repos"][r].get("scan") == "done" and st["repos"][r].get("infra") == "done" for r in repos)
    if stage == "after_scan":
        return scanned and steps.get("solutions") == "done" and steps.get("third_party") == "done"
    return scanned and steps.get("build_static") == "done"


def pending(cfg, root=None, stages=None):
    """Questions that apply and have no answer yet, in questionnaire order. With the workspace root: only the stages whose data exists, and
    the when_found questions only when the scan found their signal. Without it: every question whose `when` holds. 'unknown' is an answer."""
    ans = cfg.get("intake") or {}
    if not root:
        return [q for q in questions() if asked(q, ans) and not answered(ans, q["id"])]
    st = load_state(root)
    sig = signals(root)
    out = []
    for q in questions():
        stage = q.get("stage", "before_scan")
        if stages and stage not in stages:
            continue
        if not data_ready(stage, st) or not applies(q, ans, sig) or answered(ans, q["id"]):
            continue
        out.append(q)
    return out


def require(cfg, root, stages, who):
    """Gate: stop the calling tool while a question of these stages is unanswered or the data its questions need does not exist yet."""
    st = load_state(root)
    not_ready = [s for s in stages if not data_ready(s, st)]
    if not_ready:
        sys.exit(f"{who}: the intake cannot be completed yet ({', '.join(not_ready)} questions need data that does not exist yet). Run the earlier steps first (context.py shows the next one).")
    gaps = pending(cfg, root, stages)
    if gaps:
        sys.exit(f"{who}: {len(gaps)} intake question(s) are unanswered; nothing is assumed. Ask them (intake.py --pending) and record the user's answers:\n  "
                 + "\n  ".join(f"{q['id']}: {q['ask'][:110]}" for q in gaps[:12]) + ("\n  ..." if len(gaps) > 12 else ""))


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
    for keep in ("solutions", "environments_confirmed", "final"):  # set by --solution / --confirm-environments / --finalize, not by the questionnaire
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
    out.append("STATUS: " + (f"FINAL (confirmed by {ans['final']['by']} on {ans['final']['date']})" if ans.get("final") else "DRAFT: nothing is final until the user says so; every figure can be revised"))
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
    if cfg.get("assessment_type") == "lift-and-shift":
        out.append(f"DEVOPS: mechanism {ans.get('devops_mechanism', 'not answered')}")
        sols = ans.get("solutions") or {}
        if sols:
            out.append("SOLUTIONS WITH THEIR OWN SETTINGS: " + ", ".join(f"{k} ({', '.join(v.get('environments') or ['no environments'])})" for k, v in sols.items()))
        if ans.get("client_updates") or ans.get("release_process"):
            out.append(f"RECORDED: {len(ans.get('client_updates') or [])} client update(s), {len(ans.get('release_process') or [])} release step(s)")
    return "\n".join(out)


DECISION_LOG = os.path.join(OUT, "documents", "decision-log.md")


def log_decision(root, text, source=None):
    """Append a numbered, dated row to the decision log (a Markdown table the user can share). Entries are never rewritten."""
    path = os.path.join(root, DECISION_LOG)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# Decision log\n\nKey decisions for this assessment, newest last. Each one is applied to the document on the next build.\n\n"
                     "| # | Date | Decision | Source |\n|---|---|---|---|\n")
    n = sum(1 for line in open(path, encoding="utf-8") if re.match(r"^\|\s*\d+\s*\|", line)) + 1
    cell = lambda s: (s or "").replace("|", "/").replace("\n", " ").strip()
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(f"| {n} | {datetime.date.today().isoformat()} | {cell(text)} | {cell(source) or 'the user'} |\n")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", action="store_true", help="print the questionnaire as JSON")
    ap.add_argument("--answers", help="answers as a JSON file path or a JSON string")
    ap.add_argument("--solution", help="solution id (see solutions.py) to set environments for")
    ap.add_argument("--environments", help="comma-separated environments of that solution, e.g. 'dev, prod'")
    ap.add_argument("--confirm-environments", action="store_true", help="the user confirmed the environment lists")
    ap.add_argument("--pending", action="store_true", help="the questions that apply now and are unanswered (ask these)")
    ap.add_argument("--check", action="store_true", help="exit 1 while a question that applies is unanswered")
    ap.add_argument("--stage", choices=["before_scan", "after_scan", "after_build"], help="with --pending / --check: only this stage")
    ap.add_argument("--ci", choices=["yes", "no", "unknown"], help="with --solution: does the solution have a CI pipeline today")
    ap.add_argument("--note", help="with --solution: free note for that solution")
    ap.add_argument("--finalize", metavar="WHO", help="the user said the document is final (name or role of who said so)")
    ap.add_argument("--reopen", action="store_true", help="the user wants to revise a finalised document")
    ap.add_argument("--client-update", nargs=3, metavar=("TOPIC", "ANSWER", "EFFECT"), help="what the client said on a call and what it changes")
    ap.add_argument("--remove-client-update", metavar="TOPIC")
    ap.add_argument("--release-step", nargs=2, metavar=("STEP", "WHAT"), help="one step of today's release process, in order")
    ap.add_argument("--clear-release-steps", action="store_true")
    ap.add_argument("--branch-note", nargs=2, metavar=("REPO", "WHY"), help="why this branch was chosen for the repository (folder name)")
    ap.add_argument("--open-question", nargs=3, metavar=("QUESTION", "WHY", "WHO"), help="an extra open question for build_open_questions.py")
    ap.add_argument("--status", choices=["open", "waiting", "closed"], default="open", help="status of --open-question")
    ap.add_argument("--decision", help="a key decision to log (assessment/documents/decision-log.md)")
    ap.add_argument("--source", help="where the decision came from (e.g. 'client call, 2026-10-19')")
    a = ap.parse_args()
    if a.questions:
        print(json.dumps(questions(), indent=1, ensure_ascii=False))
        return
    root, cfg = load_config()
    if a.pending or a.check:
        gaps = pending(cfg, root, [a.stage] if a.stage else None)
        if a.pending:
            print("\n".join(f"{q['id']}: {q['ask']}" for q in gaps) or "every question that applies is answered")
        if a.check and gaps:
            sys.exit(f"{len(gaps)} intake question(s) unanswered")
        return
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
        if a.solution and (a.ci or a.note is not None):
            sol = it.setdefault("solutions", {}).setdefault(a.solution, {})
            if a.ci:
                sol["ci"] = a.ci
            if a.note is not None:
                sol["note"] = a.note
            msg.append(f"{a.solution}: " + ", ".join(x for x in (f"CI {a.ci}" if a.ci else "", "note saved" if a.note is not None else "") if x))
        if a.confirm_environments:
            it["environments_confirmed"] = True
            msg.append("environments confirmed")
        save_config(root, cfg)
        print(f"saved to {CONFIG_NAME}: " + "; ".join(msg))
    if a.finalize:
        it = cfg.setdefault("intake", {})
        gaps = pending(cfg, root)
        if gaps:
            sys.exit(f"cannot finalise: {len(gaps)} intake question(s) are unanswered ({', '.join(q['id'] for q in gaps[:6])})")
        if cfg.get("assessment_type") == "lift-and-shift" and not it.get("environments_confirmed"):
            sys.exit("cannot finalise: the environments are not confirmed (intake.py --confirm-environments after the user confirmed them)")
    msg = []
    it = cfg.setdefault("intake", {})
    if a.client_update:
        topic, answer, effect = (x.strip() for x in a.client_update)
        rows = [r for r in it.get("client_updates") or [] if r[0].strip().lower() != topic.lower()]
        it["client_updates"] = rows + [[topic, answer, effect]]
        msg.append(f"client update '{topic}' recorded ({len(it['client_updates'])} in all)")
    if a.remove_client_update:
        before = len(it.get("client_updates") or [])
        it["client_updates"] = [r for r in it.get("client_updates") or [] if r[0].strip().lower() != a.remove_client_update.strip().lower()]
        msg.append(f"client update '{a.remove_client_update}' removed" if len(it["client_updates"]) < before else f"no client update named '{a.remove_client_update}'")
    if a.clear_release_steps:
        it["release_process"] = []
        msg.append("release steps cleared")
    if a.release_step:
        it.setdefault("release_process", []).append([x.strip() for x in a.release_step])
        msg.append(f"release step {len(it['release_process'])} recorded")
    if a.branch_note:
        cfg.setdefault("branch_notes", {})[a.branch_note[0].strip().lower()] = a.branch_note[1].strip()
        msg.append(f"branch note for {a.branch_note[0].strip().lower()} recorded")
    if a.open_question:
        q, why, who = (x.strip() for x in a.open_question)
        rows = [e for e in cfg.get("open_questions_extra") or [] if e.get("question", "").strip().lower() != q.lower()]
        cfg["open_questions_extra"] = rows + [{"question": q, "why": why, "who": who, "status": a.status}]
        msg.append(f"open question recorded ({a.status})")
    if a.decision:
        log_decision(root, a.decision, a.source)
        msg.append("decision logged in assessment/documents/decision-log.md")
    if msg:
        save_config(root, cfg)
        print(f"saved to {CONFIG_NAME}: " + "; ".join(msg))
    if a.finalize or a.reopen:
        it = cfg.setdefault("intake", {})
        if a.finalize:
            it["final"] = {"by": a.finalize, "date": datetime.date.today().isoformat()}
        else:
            it.pop("final", None)
        save_config(root, cfg)
        print(f"saved to {CONFIG_NAME}: " + ("finalised by " + a.finalize if a.finalize else "reopened: DRAFT again"))
    print(summary(cfg))


if __name__ == "__main__":
    main()
