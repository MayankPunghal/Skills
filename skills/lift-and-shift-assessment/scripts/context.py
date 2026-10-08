"""Print where the assessment stands and the next command. Run once per session, first (cheap, deterministic).

    python <skill>/scripts/context.py
"""
import glob
import os
import sys

from _common import CONFIG_NAME, ISSUES_LOG, OUT, issues_log, load_config, load_state, read_json, run, utf8_stdout
import intake as I


def newer(a, b):
    """True when assessment/<a> exists and was written after assessment/<b>."""
    pa, pb = os.path.join(OUT, a), os.path.join(OUT, b)
    return os.path.exists(pa) and os.path.exists(pb) and os.path.getmtime(pa) > os.path.getmtime(pb)


def main():
    utf8_stdout()
    if sys.version_info < (3, 10):
        print("PREREQUISITES: missing python 3.10+")
    root, cfg = load_config(required=False)
    if not root:
        print(f"STATE: no {CONFIG_NAME} here or above: new assessment.\nNEXT: setup_assessment.py --client \"<name>\" --roots <folders>")
        return
    os.chdir(root)
    st = load_state(root)
    steps = st.get("steps", {})
    out_of_scope = sorted(r for r in st["repos"] if st["repos"][r].get("scope") == "out")
    repos = sorted(r for r in st["repos"] if r not in out_of_scope)
    print(f"WORKSPACE: {root}\nCLIENT: {cfg.get('client') or '?'} · roots: {', '.join(cfg.get('estate_roots') or []) or 'none'}")
    print(f"REPOS: {len(repos)} in scope (.NET) · scanned {sum(1 for r in repos if st['repos'][r].get('scan') == 'done')} · "
          f"infrastructure mapped {sum(1 for r in repos if st['repos'][r].get('infra') == 'done')}"
          + (f" · {len(out_of_scope)} out of scope (no .NET project)" if out_of_scope else ""))
    print(I.summary(cfg, root))
    idx = read_json(os.path.join(OUT, "solutions", "index.json"))
    if idx:
        ws = sum(len(s["workloads"]) for s in idx["solutions"])
        print(f"SOLUTIONS: {len(idx['solutions'])} · projects {sum(len(s['projects']) for s in idx['solutions'])} · deployables {sum(len(s['deployables']) for s in idx['solutions'])} · workloads (deployable x environment) {ws}")
    bc = read_json(os.path.join(OUT, "build", "index.json"))
    if bc:
        print("BUILD: " + ", ".join(f"{s['id']} static {s['static']['status']}, real build {s['real']['status']}" for s in bc["solutions"]))
    est = read_json(os.path.join(OUT, "estimate.json"))
    if est:
        t = est["total"]
        print(f"ESTIMATE (dev hours, AI-assisted, planning grade): {t['low']}-{t['high']} h incl. {est['contingency_pct']}% buffer ({est['days_low']}-{est['days_high']} dev days) · {est['status']}")
    docs = glob.glob(os.path.join(OUT, "documents", "*.docx"))
    print(f"DOCUMENTS: {len(docs)} built" if docs else "DOCUMENTS: not built")
    n, still = issues_log(root, cfg.get("client") or "")
    print(f"SKILL ISSUES: {n} logged ({still} open) in {ISSUES_LOG}. Log every script failure, misleading output, false gate, unclear step or workaround there as it happens.")
    sel = I.selected(cfg)
    if not repos and not steps.get("discover"):
        nxt = "discover_estate.py"
    elif not cfg.get("intake") or I.pending(cfg, root):
        gaps = I.pending(cfg, root)
        nxt = (f"intake: {len(gaps)} question(s) pending ({gaps[0]['stage']} first). Ask them with the multiple-choice tool (intake.py --pending lists them), record only the user's "
               "answers with intake.py --answers '<json>'. Nothing is assumed: the tools refuse to run while a question that applies is unanswered.")
    elif not sel:
        nxt = "intake: no work item selected; ask the questionnaire again (intake.py --questions)"
    elif any(st["repos"][r].get("scan") != "done" for r in repos):
        nxt = "scan_repo.py --all [--offline]"
    elif any(st["repos"][r].get("infra") != "done" for r in repos):
        nxt = "map_infra.py --all"
    elif steps.get("solutions") != "done":
        nxt = "solutions.py   (solution-wise inventory, deployables and workloads)"
    elif steps.get("third_party") != "done":
        nxt = "third_party.py   (licensed packages, integrations, server-to-server calls)"
    elif "build_artifacts" in sel and steps.get("build_static") != "done":
        nxt = "build_check.py   (static readiness; then build_check.py --run after the user approves the downloads; the build must pass before artifacts)"
    elif "cicd_secrets" in sel and steps.get("configtpl") != "done":
        nxt = "config_template.py   (tokenised config files and CI variables: CI/CD + Secrets Manager is selected)"
    elif not est or newer("solutions/index.json", "estimate.json") or newer("solutions/third_party.json", "estimate.json") or newer("build/index.json", "estimate.json"):
        nxt = "estimate_hours.py   (the estimate is missing or older than the data it counts)"
    elif not docs or newer("estimate.json", "documents/built.json"):
        nxt = "build_doc.py   (the single .docx for the whole project + the small workbook), then verify_doc.py"
    else:
        nxt = ("build_doc.py after any change, then verify_doc.py; upload the .docx to Drive; before finalising ask the user to confirm the environments "
               "(intake.py --confirm-environments) and only finalise when the user says so (intake.py --finalize)")
    print(f"NEXT: {nxt}")


if __name__ == "__main__":
    main()
