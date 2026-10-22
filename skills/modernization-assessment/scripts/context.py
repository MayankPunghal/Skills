"""Print where the assessment stands and the next command. Run once per session, first (cheap, deterministic).

    python <skill>/scripts/context.py
"""
import glob
import os
import re
import sys
from collections import Counter

from _common import ASSESSMENT_TYPES, CONFIG_NAME, ISSUES_LOG, OUT, documenter_dir, issues_log, load_config, load_state, read_json, run, slug, utf8_stdout
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
    out_of_scope = sorted(r for r in st["repos"] if st["repos"][r].get("scope") == "out")
    repos = sorted(r for r in st["repos"] if r not in out_of_scope)
    steps = Counter()
    for r in repos:
        for k, v in st["repos"][r].items():
            if v == "done":
                steps[k] += 1
    print(f"WORKSPACE: {root}\nCLIENT: {cfg.get('client') or '?'} · target {cfg.get('target_dotnet')} · roots: {', '.join(cfg.get('estate_roots') or []) or 'none'}")
    print(f"ASSESSMENT TYPE: {ASSESSMENT_TYPES.get(cfg.get('assessment_type'), 'not chosen yet (intake questionnaire pending)')}")
    print(f"REPOS: {len(repos)} in scope (.NET) · scanned {steps['scan']} · graphed {steps['graph']} · server dependencies mapped {steps['infra']}"
          + (f" · {len(out_of_scope)} out of scope (no .NET project, listed in the inventory workbook)" if out_of_scope else ""))
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
    if est and est.get("basis") == "hours":  # lift-and-shift track: hours calculator
        t = est["totals"]
        print(f"ESTIMATE (hours calculator): {t['total_hours'][0]:g}-{t['total_hours'][1]:g} developer hours incl. {t['contingency_pct']}% buffer "
              f"({t['total_days'][0]:g}-{t['total_days'][1]:g} dev days); {t['sample_basis_hours'][0]:g}-{t['sample_basis_hours'][1]:g} h calibrated to the sample, "
              f"{t['inferred_hours'][0]:g}-{t['inferred_hours'][1]:g} h inferred" + ("; environments UNKNOWN" if t.get("environments_assumed") else ""))
    elif est:
        t = est["totals"]
        print(f"ESTIMATE: {t['total_days'][0]}-{t['total_days'][1]} person-days (likely {t['likely_days']}), ~{t['duration_weeks']} weeks")
    todo = [os.path.basename(p)[:-3] for p in glob.glob(os.path.join(OUT, "narrative", "*.md")) if re.search(r"(?m)^(?:PENDING|TODO):", open(p, encoding="utf-8").read())]
    print(f"NARRATIVES: {'all written' if not todo else 'to write: ' + ', '.join(sorted(todo))}")
    reports = glob.glob(os.path.join(OUT, "report", "*.md"))
    print(f"REPORT: {os.path.relpath(reports[0]) if reports else 'not built'}")
    pending_discover = not repos
    pending_scan = [r for r in repos if st["repos"][r].get("scan") != "done"]
    pending_graph = [r for r in repos if st["repos"][r].get("graph") != "done"]
    pending_infra = [r for r in repos if st["repos"][r].get("infra") != "done"]
    sample = (cfg.get("intake") or {}).get("code_access") == "sample"
    lift = cfg.get("assessment_type") == "lift-and-shift"

    def newer(a, b):  # a (under assessment/) changed after b was written, or b is missing
        pa, pb = os.path.join(OUT, a), os.path.join(OUT, b)
        return not os.path.exists(pb) or (os.path.exists(pa) and os.path.getmtime(pa) > os.path.getmtime(pb))

    atf_dir = cfg.get("atf_scanner_dir") or os.environ.get("ATF_SCANNER_DIR")
    atf_todo = [r for r in repos if not os.path.exists(os.path.join(OUT, "atf", r, "atf.json"))] if atf_dir and not lift else []
    phased = read_json(os.path.join(OUT, "effort", "estimate-phases.json"), {}) or {}
    phases_todo = [r for r in repos if r not in (phased.get("repos") or {})] if not lift else []
    summaries = glob.glob(os.path.join(OUT, "report", "*-Modernization-Summary.md"))
    stem = os.path.join(OUT, "documents", slug(cfg.get("client") or "client"))
    extras = [(stem + "-open-questions.md", "build_open_questions.py   (full and short question lists and the client email, .md + .html)"),
              (stem + "-effort-estimate-explained.md", "build_estimate_explainer.py   (every hour explained, .md + .html)")]
    docs = read_json(os.path.join(OUT, "documents", "built.json"))
    mapping = glob.glob(os.path.join(OUT, "documents", "*-Application-Server-Mapping.xlsx"))
    if not cfg.get("assessment_type") and not repos:  # workspaces started before the intake keep their scenario.hosting
        nxt = ("intake questionnaire: ask the questions from intake.py --questions in plain words, then intake.py --answers '<json>' "
               "(references/intake.md); the answers choose the assessment type")
    elif pending_discover:
        nxt = "discover_estate.py"
    elif atf_todo and pending_scan:
        nxt = f"atf_scan.py   (AWS Transform codebase scanner, RadNet then RaSQL: {len(atf_todo)} repositories without atf.json; references/atf-and-phased-estimate.md)"
    elif pending_scan:
        nxt = f"scan_repo.py --all   ({len(pending_scan)} repositories not scanned)"
    elif pending_infra:
        nxt = (f"map_infra.py --all [--servers <the client's server list .xlsx>]   ({len(pending_infra)} repositories without server dependencies and hosting evidence); "
               "then update_inventory_xlsx.py --xlsx <repository inventory workbook> to write the findings back")
    elif pending_graph:
        nxt = f"map_graphs.py --all   ({len(pending_graph)} repositories without a code graph)"
    elif unreviewed or needs:
        nxt = "review findings (references/review-findings.md): record verdicts in assessment/reviews/<repo>.json"
    elif not cls:
        nxt = "classify_apps.py"
    elif len(dec) < apps:
        nxt = f"review 7R decisions ({apps - len(dec)} pending): write assessment/decisions.json, then classify_apps.py"
    elif cfg.get("assessment_type") == "lift-and-shift" and (cfg.get("intake") or {}).get("work_items") is None:
        nxt = "intake: the hours calculator questions (work_items, retarget_to, estimate_basis, environments, ...) are unanswered: intake.py --questions, ask, intake.py --answers"
    elif not est or (os.path.getmtime(os.path.join(OUT, "estimate.json")) < os.path.getmtime(os.path.join(OUT, "classification.json"))):
        nxt = ("estimate_effort.py   (lift-and-shift track: runs solutions.py, third_party.py and the hours calculator itself; build_check.py shows whether each solution builds on a clean agent)"
               if cfg.get("assessment_type") == "lift-and-shift" else "estimate_effort.py")
    elif sample and (not os.path.exists(os.path.join(OUT, "extrapolation.json"))
                     or os.path.getmtime(os.path.join(OUT, "extrapolation.json")) < os.path.getmtime(os.path.join(OUT, "estimate.json"))):
        nxt = "extrapolate_estate.py (only a sample of the estate is assessed: estimate the rest from it)"
    elif phases_todo:
        nxt = (f"effort_facts.py, then estimate_phases.py   ({len(phases_todo)} repositories without a phased estimate; "
               "answer the UNKNOWN inputs in assessment/effort/<repo>/estimate-inputs.json and re-run)")
    elif lift and (not docs or newer("estimate.json", "documents/built.json")):
        nxt = "build_doc.py   (the single .docx for the whole project + the small workbook), then verify_doc.py"
    elif lift and not mapping and not os.path.exists(os.path.join(OUT, "infra", "mapping-check.json")):
        nxt = "build_mapping_sheet.py   (the application-to-server sheet for the client to fill in; never pre-fill servers)"
    elif lift and any(not os.path.exists(f) or newer("documents/built.json", os.path.relpath(f, OUT)) for f, _ in extras):
        nxt = next(cmd for f, cmd in extras if not os.path.exists(f) or newer("documents/built.json", os.path.relpath(f, OUT)))
    elif todo:
        nxt = f"write narratives: {', '.join(sorted(todo))} (references/write-report.md)"
    elif not reports:
        nxt = "build_report.py"
    elif not glob.glob(os.path.join(OUT, "report", "*.html")):
        nxt = "build_html_report.py, then verify_report.py"
    elif not lift and (not summaries or newer("effort/estimate-phases.json", os.path.relpath(summaries[0], OUT))):
        nxt = "build_summary.py   (the one short report: answer first, then only what needs action)"
    elif lift:
        nxt = ("build_doc.py after any change, then verify_doc.py; before finalising ask the user to confirm the environments "
               "(intake.py --confirm-environments) and only finalise when the user says so (intake.py --finalize). Call answers: intake.py --client-update / --decision / "
               "--release-step. Mapping workbook back: check_mapping.py --workbook <file>")
    else:
        nxt = "build_report.py and build_html_report.py after any change, then verify_report.py"
    ref = os.path.join(OUT, "reference", "README.md")
    if os.path.exists(ref):
        stale = any(os.path.getmtime(p) > os.path.getmtime(ref) for p in glob.glob(os.path.join(OUT, "report", "*.md")) + [os.path.join(root, ISSUES_LOG)] if os.path.exists(p))
        print(f"CONTEXT PACK: {ref} (start here: scope, outputs, notes from earlier sessions){' - stale, re-run reference.py' if stale else ''}")
    elif reports:
        print("CONTEXT PACK: none yet - run reference.py (assessment/reference/: where everything is, for the next session)")
    n, still = issues_log(root, cfg.get("client") or "")
    print(f"SKILL ISSUES: {n} logged ({still} open) in {ISSUES_LOG}. Log every script failure, misleading output, false gate, "
          "unclear step or workaround there as it happens (symptom, cause, workaround, suggested fix).")
    print(f"NEXT: {nxt}")


if __name__ == "__main__":
    main()
