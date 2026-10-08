"""Intake questionnaire: everything the assessment needs that the code cannot show. Nothing is assumed; the tools refuse to run on a gap.

    python <skill>/scripts/intake.py --pending [--stage S]        the questions that apply now and are unanswered (ask these)
    python <skill>/scripts/intake.py --questions [--stage S]      the whole questionnaire (data/intake.json) as JSON
    python <skill>/scripts/intake.py --answers FILE|JSON          record the answers (JSON keyed by question id)
    python <skill>/scripts/intake.py --check                      exit code 1 while a question that applies is unanswered
    python <skill>/scripts/intake.py --solution ID --environments "dev, prod" [--ci yes|no|unknown] [--note TEXT]
                                                                  the environments (and CI status) of one solution
    python <skill>/scripts/intake.py --confirm-environments       the user confirmed the environment lists (needed to finalise)
    python <skill>/scripts/intake.py --finalize "<who said so>"   the user said the document is final (until then everything is DRAFT)
    python <skill>/scripts/intake.py                              show the recorded answers

Guardrail: scan_repo.py, solutions.py, build_check.py, config_template.py, estimate_hours.py and build_doc.py call require() and stop while
a question that applies is unanswered. Questions have a stage: before_scan (asked right after discovery), after_scan (only when the scan
found the thing the question is about), after_build (after the static build check). The agent records only what the user said; 'unknown'
is accepted only when the user says it, and then stays UNKNOWN in the document. Nothing is final until the user says so.
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

from _common import CONFIG_NAME, OUT, data, load_config, load_state, read_json, save_config, utf8_stdout

WORK_ITEMS = ("build_artifacts", "cicd_secrets", "retarget", "validation_cutover")
STAGES = ("before_scan", "after_scan", "after_build")


def questions(stage=None):
    return [q for q in data("intake.json")["questions"] if not stage or q["stage"] == stage]


def split_envs(text):
    if isinstance(text, list):
        text = ",".join(text)
    return [x.strip() for x in re.split(r"[;,/+]|\band\b", str(text or "")) if x.strip() and x.strip().lower() not in ("unknown", "none")]


def asked(q, ans):
    """A question is asked when every `when` condition holds; a list means any of them, and a multi answer matches when it contains the value."""
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


def pending(cfg, root, stages=None):
    """Questions that apply and have no answer yet, in questionnaire order (restricted to the stages whose data exists)."""
    ans = cfg.get("intake") or {}
    st = load_state(root)
    sig = signals(root)
    out = []
    for q in questions():
        if stages and q["stage"] not in stages:
            continue
        if not data_ready(q["stage"], st) or not applies(q, ans, sig) or answered(ans, q["id"]):
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
    by_id = {q["id"]: q for q in questions()}
    for k, v in ans.items():
        q = by_id.get(k)
        if not q:
            errs.append(f"unknown question id: {k}")
            continue
        if v in (None, "", []):
            errs.append(f"{k}: empty answer; record only what the user said")
            continue
        if q.get("options") and v != "unknown":
            allowed = [o["value"] for o in q["options"]]
            for x in (v if isinstance(v, list) else [v]):
                if x not in allowed:
                    errs.append(f"{k}: '{x}' is not one of {', '.join(allowed)}")
    return errs


def apply(cfg, ans):
    """Answers -> assessment.json. Returns the changes, for the summary."""
    changes = []
    items = ans.get("work_items")
    if isinstance(items, str):
        ans["work_items"] = [x.strip() for x in items.split(",") if x.strip()]
    prev = cfg.get("intake") or {}
    new = {**prev, **ans}
    for key, field in (("prepared_by", "prepared_by"), ("engagement_title", "engagement")):
        if ans.get(key) and cfg.get(field) != ans[key]:
            cfg[field] = ans[key]
            changes.append(f"{field} = {ans[key]!r}")
    if ans.get("current_hosting") and ans["current_hosting"] not in ("unknown", "other"):
        cfg["current_hosting"] = ans["current_hosting"]
    if "environments" in ans and split_envs(new.get("environments")) != split_envs(prev.get("environments")):
        new["environments_confirmed"] = False
    if new != prev:
        changes.append("intake answers recorded")
    cfg["intake"] = new
    return changes


def solution_settings(cfg, sid):
    return ((cfg.get("intake") or {}).get("solutions") or {}).get(sid) or {}


def environments_of(cfg, sid):
    """(list of environments, confirmed?). A solution's own list, else the default list, else [] (UNKNOWN: 1 per deployable is assumed)."""
    it = cfg.get("intake") or {}
    own = solution_settings(cfg, sid).get("environments")
    envs = own if own else split_envs(it.get("environments"))
    return envs, bool(it.get("environments_confirmed")) and bool(envs)


def selected(cfg):
    return [x for x in ((cfg.get("intake") or {}).get("work_items") or []) if x in WORK_ITEMS]


def unknowns(cfg):
    """Questions the user answered 'unknown': they stay UNKNOWN in the document."""
    ans = cfg.get("intake") or {}
    return [q for q in questions() if ans.get(q["id"]) == "unknown"]


def summary(cfg, root=None):
    ans = cfg.get("intake") or {}
    if not ans:
        return "INTAKE: not started: run intake.py --pending and ask the questions (multiple-choice tool), then intake.py --answers '<json>'"
    out = []
    if root:
        gaps = pending(cfg, root)
        total = sum(1 for q in questions() if asked(q, ans))
        out.append(f"INTAKE: {len(gaps)} question(s) pending" + (f" ({', '.join(q['id'] for q in gaps[:6])}{'...' if len(gaps) > 6 else ''})" if gaps else ": every question that applies is answered")
                   + f"; {len(unknowns(cfg))} answered 'unknown'")
    items = selected(cfg)
    out.append("WORK ITEMS: " + (", ".join(items) if items else "none selected (the estimate would be empty)"))
    envs = split_envs(ans.get("environments"))
    out.append("ENVIRONMENTS: " + (", ".join(envs) if envs else "UNKNOWN: 1 per deployable is assumed") + (" (confirmed)" if ans.get("environments_confirmed") and envs else " (NOT confirmed)"))
    out.append(f"DEVOPS: mechanism {ans.get('devops_mechanism', 'not answered')}")
    sols = ans.get("solutions") or {}
    if sols:
        out.append("SOLUTIONS WITH THEIR OWN SETTINGS: " + ", ".join(f"{k} ({', '.join(v.get('environments') or ['no environments'])})" for k, v in sols.items()))
    out.append("STATUS: " + (f"FINAL (confirmed by {ans['final']['by']} on {ans['final']['date']})" if ans.get("final") else "DRAFT: nothing is final until the user says so; every hour can be revised"))
    return "\n".join(out)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", action="store_true", help="print the questionnaire as JSON")
    ap.add_argument("--pending", action="store_true", help="the questions to ask now")
    ap.add_argument("--check", action="store_true", help="exit 1 while a question that applies is unanswered")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--answers", help="answers as a JSON file path or a JSON string")
    ap.add_argument("--solution", help="solution id (see solutions.py) to set environments for")
    ap.add_argument("--environments", help="comma-separated environments of that solution, e.g. 'dev, prod'")
    ap.add_argument("--ci", choices=["yes", "no", "unknown"], help="does the solution have a CI pipeline today")
    ap.add_argument("--note", help="free note for that solution")
    ap.add_argument("--confirm-environments", action="store_true", help="the user confirmed the environment lists")
    ap.add_argument("--finalize", metavar="WHO", help="the user said the documents are final (name or role of who said so)")
    ap.add_argument("--reopen", action="store_true", help="the user wants to revise a finalised document")
    a = ap.parse_args()
    if a.questions:
        print(json.dumps(questions(a.stage), indent=1, ensure_ascii=False))
        return
    root, cfg = load_config()
    os.chdir(root)
    it = cfg.setdefault("intake", {})
    msg = []
    if a.answers:
        raw = open(a.answers, encoding="utf-8").read() if os.path.exists(a.answers) else a.answers
        ans = json.loads(raw)
        errs = validate(ans)
        if errs:
            sys.exit("intake answers rejected:\n  " + "\n  ".join(errs))
        msg += apply(cfg, ans)
        it = cfg["intake"]
    if a.solution:
        s = it.setdefault("solutions", {}).setdefault(a.solution, {})
        if a.environments is not None:
            s["environments"] = split_envs(a.environments)
            it["environments_confirmed"] = False  # a changed list must be confirmed again
            msg.append(f"{a.solution}: environments {s['environments'] or 'UNKNOWN'} (confirm again)")
        if a.ci:
            s["ci"] = a.ci
        if a.note:
            s["note"] = a.note
    if a.confirm_environments:
        it["environments_confirmed"] = True
        msg.append("environments confirmed")
    if a.finalize:
        gaps = pending(cfg, root)
        if gaps:
            sys.exit(f"cannot finalise: {len(gaps)} intake question(s) are unanswered ({', '.join(q['id'] for q in gaps[:6])})")
        if not it.get("environments_confirmed"):
            sys.exit("cannot finalise: the environments are not confirmed (intake.py --confirm-environments after the user confirmed them)")
        it["final"] = {"by": a.finalize, "date": datetime.date.today().isoformat()}
        msg.append("marked FINAL")
    if a.reopen:
        it.pop("final", None)
        msg.append("reopened: back to DRAFT")
    if msg:
        save_config(root, cfg)
        print(f"saved to {CONFIG_NAME}: " + "; ".join(msg))
    if a.pending or a.check:
        gaps = pending(cfg, root, [a.stage] if a.stage else None)
        sig = signals(root)
        print(f"{len(gaps)} question(s) to ask now" + (f" (stage {a.stage})" if a.stage else ""))
        for q in gaps:
            ev = evidence(q, sig)
            print(f"  [{q['stage']}] {q['id']}: {q['ask']}" + (f"  (found: {ev})" if ev else "") + (f"  options: {', '.join(o['value'] for o in q['options'])}" if q.get("options") else "  (free text)"))
        later = [q for q in questions() if q["stage"] != "before_scan" and not data_ready(q["stage"], load_state(root))]
        if later:
            print(f"  {len(later)} more question(s) may follow after the scan and the build check; they depend on what is found.")
        if a.check and gaps:
            sys.exit(1)
        return
    print(summary(cfg, root))


if __name__ == "__main__":
    main()
