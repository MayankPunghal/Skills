"""Print where the assessment stands and the next command. Run once per session, first (cheap, deterministic).

    python <skill>/scripts/context.py
"""
import glob
import os
import re
import sys
from collections import Counter

from _common import CONFIG_NAME, ISSUES_LOG, OUT, documenter_dir, issues_log, load_config, load_state, read_json, run, utf8_stdout
import _findings as F


def prereqs():
    miss = [] if sys.version_info >= (3, 10) else ["python 3.10+"]
    if run(["graphify", "--help"])[0]:
        miss.append("graphify")
    if not documenter_dir():
        miss.append("codebase-documenter skill (sibling install)")
    else:
        sys.path.insert(0, os.path.join(documenter_dir(), "scripts"))
        try:
            import sql_parse
            if not sql_parse.has_sqlglot():
                miss.append("sqlglot")
            if sql_parse.dotnet_major() < sql_parse.MIN_DOTNET:
                miss.append(".NET SDK 8+ (T-SQL parser)")
        except ImportError:
            miss.append("codebase-documenter sql_parse.py (update the codebase-documenter skill)")
    dotnet = run(["dotnet", "--list-sdks"])
    return miss, (dotnet[1].strip().splitlines() if dotnet[0] == 0 else [])


def main():
    utf8_stdout()
    miss, sdks = prereqs()
    if miss:
        print("PREREQUISITES: missing " + ", ".join(miss) + "  (see references/setup.md)")
    if documenter_dir():
        try:
            import tool_updates  # codebase-documenter's: the cached result of the last `npx ... update` check
            upd = tool_updates.cached_summary()
            if upd:
                print(upd)
        except ImportError:
            pass
    print("DOTNET SDKS: " + (", ".join(s.split(" ")[0] for s in sdks) if sdks else "none (Linux build validation will be skipped or use a container)"))
    root, cfg = load_config(required=False)
    if not root:
        print(f"STATE: no {CONFIG_NAME} here or above: new assessment.\nNEXT: setup_assessment.py --client \"<name>\" --roots <folders>")
        return
    os.chdir(root)
    st = load_state(root)
    repos = sorted(st["repos"])
    steps = Counter()
    for r in repos:
        for k, v in st["repos"][r].items():
            if v == "done":
                steps[k] += 1
    print(f"WORKSPACE: {root}\nCLIENT: {cfg.get('client') or '?'} · target {cfg.get('target_dotnet')} · roots: {', '.join(cfg.get('estate_roots') or []) or 'none'}")
    print(f"REPOS: {len(repos)} discovered · scanned {steps['scan']} · graphed {steps['graph']}")
    fs, unreviewed, needs = [], 0, 0
    for r in repos:
        inv = F.load_inventory(root, r)
        if inv and os.path.exists(os.path.join(OUT, "findings", f"{r}.json")):
            ff = F.load(root, r)
            fs += ff
            unreviewed += sum(1 for f in ff if f["severity"] in ("Blocker", "High") and f.get("confidence") != "Confirmed" and not f.get("review"))
            needs += sum(1 for f in ff if f.get("confidence") == "Needs verification" and f["severity"] in ("Blocker", "High", "Medium") and not f.get("review"))
    sev = Counter(f["severity"] for f in fs)
    print("FINDINGS: " + (", ".join(f"{k} {sev[k]}" for k in ("Blocker", "High", "Medium", "Low", "Info") if sev[k]) or "none yet") +
          f" · Blocker/High not yet reviewed: {unreviewed} · Medium+ needing verification: {needs}")
    cls = read_json(os.path.join(OUT, "classification.json"))
    dec = read_json(os.path.join(OUT, "decisions.json"), {}) or {}
    apps = len(cls["applications"]) if cls else 0
    print(f"APPLICATIONS: {apps} classified · reviewed decisions: {len(dec)}")
    est = read_json(os.path.join(OUT, "estimate.json"))
    if est:
        t = est["totals"]
        print(f"ESTIMATE: {t['total_days'][0]}-{t['total_days'][1]} person-days (likely {t['likely_days']}), ~{t['duration_weeks']} weeks")
    todo = [os.path.basename(p)[:-3] for p in glob.glob(os.path.join(OUT, "narrative", "*.md")) if re.search(r"(?m)^(?:PENDING|TODO):", open(p, encoding="utf-8").read())]
    print(f"NARRATIVES: {'all written' if not todo else 'to write: ' + ', '.join(sorted(todo))}")
    reports = glob.glob(os.path.join(OUT, "report", "*.md"))
    print(f"REPORT: {os.path.relpath(reports[0]) if reports else 'not built'}")
    pending_discover = not repos
    pending_scan = [r for r in repos if st["repos"][r].get("scan") != "done"]
    pending_graph = [r for r in repos if st["repos"][r].get("graph") != "done"]
    if pending_discover:
        nxt = "discover_estate.py"
    elif pending_scan:
        nxt = f"scan_repo.py --all   ({len(pending_scan)} repositories not scanned)"
    elif pending_graph:
        nxt = f"map_graphs.py --all   ({len(pending_graph)} repositories without a code graph)"
    elif unreviewed or needs:
        nxt = "review findings (references/review-findings.md): record verdicts in assessment/reviews/<repo>.json"
    elif not cls:
        nxt = "classify_apps.py"
    elif len(dec) < apps:
        nxt = f"review 7R decisions ({apps - len(dec)} pending): write assessment/decisions.json, then classify_apps.py"
    elif not est or (os.path.getmtime(os.path.join(OUT, "estimate.json")) < os.path.getmtime(os.path.join(OUT, "classification.json"))):
        nxt = "estimate_effort.py"
    elif todo:
        nxt = f"write narratives: {', '.join(sorted(todo))} (references/write-report.md)"
    elif not reports:
        nxt = "build_report.py"
    elif not glob.glob(os.path.join(OUT, "report", "*.html")):
        nxt = "build_html_report.py, then verify_report.py"
    else:
        nxt = "build_report.py and build_html_report.py after any change, then verify_report.py"
    n, still = issues_log(root, cfg.get("client") or "")
    print(f"SKILL ISSUES: {n} logged ({still} open) in {ISSUES_LOG}. Log every script failure, misleading output, false gate, "
          "unclear step or workaround there as it happens (symptom, cause, workaround, suggested fix).")
    print(f"NEXT: {nxt}")


if __name__ == "__main__":
    main()
