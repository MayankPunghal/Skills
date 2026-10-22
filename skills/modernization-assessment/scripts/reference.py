"""The context pack: everything a new session needs to pick the assessment up, in one folder of the output.

    py -X utf8 reference.py                                  # (re)build assessment/reference/
    py -X utf8 reference.py --note "Title" --file answer.md  # save a chat answer as a note, then rebuild
    py -X utf8 reference.py --note "Title" < answer.md       # the same from stdin

Writes assessment/reference/:
  README.md / .html   start here: scope, repository copies (branch, commit), headline numbers, where every output is, the
                      code graph and how to query it, what lives outside assessment/ and why, tool versions, notes, logs
  notes/              answers given in chat (dated .md + .html), so a later session has them without the transcript
  logs/               copies of the run issues log and the workspace-root logs
  inputs/             assessment.json and the AWS Transform scanner settings, secret values masked

Nothing outside assessment/ is moved or deleted: large or shared things (repository copies, build copies, tool caches) are
listed with their path. Run it after the report steps and whenever a note is added; context.py says when it is stale.
"""
import argparse
import datetime
import glob
import json
import os
import platform
import re
import shutil
import sys

from _common import CONFIG_NAME, ISSUES_LOG, OUT, load_config, load_state, mask, read_json, run, slug, tool_exe, utf8_stdout
from _mdhtml import write_pair

REF = os.path.join(OUT, "reference")
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_KEY = re.compile(r"(?i)pass|pwd|secret|token|apikey|api_key|accesskey|credential|privatekey|clientkey|sharedkey")
FOLDERS = [  # assessment/<folder>: what it holds
    ("report", "The deliverables: full report, summary, tracker workbook, execution plan, CSV/JSON exports"),
    ("effort", "Phased estimate per repository: estimate inputs (answers and scenarios), facts, AWS managed-service swaps"),
    ("atf", "AWS Transform codebase scanner: RadNet and RaSQL results, readable HTML reports, scanner caches and logs"),
    ("graphs", "Code graph per repository (graphify-out/graph.json), cluster analysis, wiring findings"),
    ("findings", "Every finding per repository with file:line evidence"),
    ("scan", "Raw scan results per repository: packages, DLLs, APIs, config keys"),
    ("linux", "Linux readiness per repository (JSON, Markdown, HTML)"),
    ("infra", "Server dependencies, endpoints, hosting evidence, network access"),
    ("inventory", "Solutions, projects, frameworks and packages per repository"),
    ("solutions", "Solution index and per-solution details"),
    ("narrative", "The hand-written report sections (with {{v:...}} value tags)"),
    ("reviews", "Finding verdicts recorded during review"),
    ("config", "Configuration map per repository (keys only, never values)"),
    ("build", "Build check results; build/index.json names the folder the build copies went to"),
    ("documents", "Lift-and-shift document and workbook (that track only)"),
    ("cache", "Package lookup cache (safe to delete)"),
    ("reference", "This context pack"),
]


def skill_version():
    m = re.search(r"(?m)^\s+version:\s*(\S+)", open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8").read())
    return m.group(1) if m else "?"


def git(path, *args):
    code, out = run(["git", "-C", path] + list(args))
    return out.strip().splitlines()[-1] if code == 0 and out.strip() else ""


def size(p):
    try:
        n = os.path.getsize(p) if os.path.isfile(p) else sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs)
    except OSError:
        return "-"
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


def link(path):
    return f"[{os.path.basename(path)}]({os.path.relpath(path, REF).replace(os.sep, '/')})"


def masked_json(obj):
    if isinstance(obj, dict):
        return {k: ("***" if SECRET_KEY.search(k) and isinstance(v, str) and v else masked_json(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [masked_json(v) for v in obj]
    return obj


def copy_inputs(root, cfg):
    d = os.path.join(REF, "inputs")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, CONFIG_NAME), "w", encoding="utf-8") as fh:
        json.dump(masked_json(cfg), fh, indent=1)
    out = [os.path.join(d, CONFIG_NAME)]
    sdir = cfg.get("atf_scanner_dir") or os.environ.get("ATF_SCANNER_DIR") or ""
    for name in ("scanner-config.yaml", "apps-config.yaml"):
        p = os.path.join(sdir, name)
        if sdir and os.path.isfile(p):
            q = os.path.join(d, "atf-" + name)
            with open(q, "w", encoding="utf-8") as fh:
                fh.writelines(mask(l) + "\n" for l in open(p, encoding="utf-8", errors="ignore"))
            out.append(q)
    return out


def copy_logs(root):
    d = os.path.join(REF, "logs")
    os.makedirs(d, exist_ok=True)
    out = []
    issues = os.path.join(root, ISSUES_LOG)
    if os.path.isfile(issues):
        write_pair(os.path.join(d, ISSUES_LOG), open(issues, encoding="utf-8").read())
        out.append(os.path.join(d, ISSUES_LOG))
    for p in glob.glob(os.path.join(root, "*.log")):
        shutil.copy2(p, d)
        out.append(os.path.join(d, os.path.basename(p)))
    return out


def add_note(title, text):
    d = os.path.join(REF, "notes")
    os.makedirs(d, exist_ok=True)
    day = datetime.date.today().isoformat()
    p = os.path.join(d, f"{day}-{slug(title)[:60]}.md")
    body = text.strip()
    if not body.startswith("# "):
        body = f"# {title}\n\n{body}"
    write_pair(p, f"{body}\n\n_Saved {day}._\n", title)
    print(f"note: {os.path.relpath(p)}")


def notes():
    rows = []
    for p in sorted(glob.glob(os.path.join(REF, "notes", "*.md"))):
        m = re.search(r"(?m)^#\s+(.+)$", open(p, encoding="utf-8").read())
        rows.append((os.path.basename(p)[:10], m.group(1).strip() if m else os.path.basename(p), p))
    return rows


def headline(st):
    lines = []
    ph = read_json(os.path.join(OUT, "effort", "estimate-phases.json"), {}) or {}
    for repo, x in sorted((ph.get("repos") or {}).items()):
        lo, hi = (x.get("total") or [0, 0])[:2]
        dd = x.get("dev_days") or ["?", "?"]
        lines.append(f"- **{repo}**: {lo}–{hi} h phased estimate ({dd[0]}–{dd[1]} dev-days of {x.get('hours_per_day', '?')} h)")
        for s in x.get("scenarios") or []:
            if isinstance(s, dict) and s.get("total"):
                lines.append(f"  - scenario *{s.get('name')}*: {s['total'][0]}–{s['total'][1]} h")
    t = (read_json(os.path.join(OUT, "estimate.json"), {}) or {}).get("totals") or {}
    if t.get("likely_hours"):
        lines.append(f"- Parametric cross-check: likely {t['likely_hours']} h (range {t.get('range_method', '')} {t.get('total_hours')})"
                     + (f"; AWS managed-service swaps {t['aws_swap_hours'][0]}–{t['aws_swap_hours'][1]} h" if t.get("aws_swap_hours") else ""))
    cls = read_json(os.path.join(OUT, "classification.json"), {}) or {}
    for a in (cls.get("applications") or [])[:20]:
        lines.append(f"- {a.get('name') or a.get('id')} ({a.get('repo')}, {a.get('type')}, {'/'.join(a.get('target_frameworks') or [])}): "
                     f"**{a.get('r7') or '?'}** -> {a.get('target') or '?'}")
    return lines or ["- No estimate yet."]


def build(root, cfg, st):
    utc = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    inputs, logs = copy_inputs(root, cfg), copy_logs(root)
    repos = {r: v for r, v in (st.get("repos") or {}).items() if v.get("scope") != "out"}
    md = [f"# Context pack: {cfg.get('client') or 'assessment'}", "",
          f"Built {utc} by modernization-assessment {skill_version()}. Open this first in a new session: it says what was assessed, "
          "where every output is and what lives outside this folder. Then run `context.py` from the workspace for the next step.", "",
          "## Resume", "",
          f"- Workspace: `{root}`",
          f"- Resume: `cd` to the workspace, then `python <skill>/scripts/context.py` (prints the state and `NEXT`)",
          f"- Assessment type: {cfg.get('assessment_type') or 'not chosen'} · target .NET {cfg.get('target_dotnet') or '?'} · target OS {cfg.get('target_os') or '?'}",
          f"- Settings: {link(inputs[0])} (secret values masked)", "",
          "## Headline", ""] + headline(st) + ["",
          "## Repositories (read-only copies the scripts read)", "",
          "| Repository | Copy | Branch | Commit | Steps done |", "|---|---|---|---|---|"]
    for r, v in sorted(repos.items()):
        p = v.get("root_path") or ""
        br, sha = (git(p, "rev-parse", "--abbrev-ref", "HEAD"), git(p, "rev-parse", "--short", "HEAD")) if os.path.isdir(p) else ("", "")
        md.append(f"| {r} | `{p}` | {br or '-'} | {sha or '-'} | {', '.join(k for k, s in v.items() if s == 'done')} |")
    md += ["", "## Deliverables", ""]
    for pat in ("report/*.html", "report/*.xlsx", "atf/*-report.html", "effort/*/estimate.html", "effort/*/effort-inputs.html",
                "effort/*/aws-native.html", "linux/*/linux-readiness.html", "report/open-questions.csv"):
        md += [f"- {link(p)}" for p in sorted(glob.glob(os.path.join(OUT, pat)))]
    md += ["", "## Where everything is (assessment/)", "", "| Folder | Holds | Files | Size |", "|---|---|---|---|"]
    for f, what in FOLDERS:
        p = os.path.join(OUT, f)
        if os.path.isdir(p):
            md.append(f"| `{f}/` | {what} | {sum(len(fs) for _, _, fs in os.walk(p))} | {size(p)} |")
    md += ["", "Top-level files: `state.json` (steps done), `estimate.json` (parametric estimate), `classification.json` (7 Rs), "
           "`decisions.json` (7R decisions taken), `execution-plan.json`.", "", "## Code graph", ""]
    gx = tool_exe("graphify") or "graphify"
    for r in sorted(repos):
        gj = os.path.join(OUT, "graphs", r, "graphify-out", "graph.json")
        if not os.path.isfile(gj):
            md.append(f"- {r}: no graph yet (`map_graphs.py --repo {r}`)")
            continue
        gd = os.path.dirname(gj)
        extra = [link(p) for p in sorted(glob.glob(os.path.join(gd, "*.html")) + glob.glob(os.path.join(gd, "wiki", "index.*")) + glob.glob(os.path.join(gd, "wiki-html", "index.html")))]
        ex = os.path.join(OUT, "graphs", r, "explorer.html")
        md += [f"- **{r}**: {link(gj)} ({size(gj)}), {link(os.path.join(gd, 'GRAPH_REPORT.md'))}"
               + (f", {', '.join(extra)}" if extra else f" · no wiki or call-flow pages: `map_graphs.py --repo {r} --exports` makes them"),
               (f"  - Explorer (blast radius, depends on, paths, hubs; offline): {link(ex)}" if os.path.isfile(ex) else f"  - No explorer yet: `graph_ui.py --repo {r}`"),
               f"  - Query: `\"{gx}\" query \"<question>\" --graph {os.path.relpath(gj, root).replace(os.sep, '/')} --budget 800`"]
    md += ["", "Ask the graph from a browser: `py -X utf8 <skill>/scripts/graph_ui.py --serve` in the workspace, then open http://127.0.0.1:8765/ "
           "(the explorers plus graphify query / explain / path / affected; local only).", "",
           "Migration order, per-project 7R, difficulty and blast radius: `report/projects.json`; sign-in and access per application: `report/auth.json`."]
    md += ["", "## Outside assessment/ (listed, not copied)", "", "| What | Where | Size | Why it is not here |", "|---|---|---|---|"]
    for r, v in sorted(repos.items()):
        if v.get("root_path"):
            md.append(f"| Repository copy: {r} | `{v['root_path']}` | {size(v['root_path'])} | The code itself; the graph's `.graphify_root` points here |")
    bi = read_json(os.path.join(OUT, "build", "index.json"), {}) or {}
    if not bi.get("work_dir"):
        try:
            from build_check import work_base  # where build_check.py puts its copies (a short folder when the workspace path is long)
            bi["work_dir"] = work_base(root) if os.path.isdir(work_base(root)) else ""
        except Exception:
            pass
    if bi.get("work_dir") and os.path.abspath(bi["work_dir"]) != os.path.abspath(os.path.join(OUT, "build", "work")):
        md.append(f"| Build copies | `{bi['work_dir']}` | {size(bi['work_dir'])} | Short path: MSBuild fails on long Windows paths. Results are in `build/index.json`; delete when done |")
    sdir = cfg.get("atf_scanner_dir") or os.environ.get("ATF_SCANNER_DIR") or ""
    if sdir:
        md.append(f"| AWS Transform scanner | `{sdir}` | {size(sdir)} | Third-party tool; its results, caches and logs are copied to `atf/`, its settings to `reference/inputs/` |")
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    for p, why in ((os.path.join(local, "lift-and-shift-assessment"), "Shared tool cache (NuGet, .NET Framework reference packs) for every assessment"),
                   (os.path.join(os.path.expanduser("~"), ".cache", "codebase-documenter"), "Shared cache: tool-update check, Mermaid script")):
        if os.path.isdir(p):
            md.append(f"| Tool cache | `{p}` | {size(p)} | {why} |")
    md.append("| Temporary files | system temp folder | - | None kept: the Word helpers delete their scripts and PDFs |")
    md += ["", "## Notes (answers given in chat)", ""]
    nl = notes()
    md += [f"- {d}: [{t}]({os.path.relpath(p, REF).replace(os.sep, '/')})" for d, t, p in nl] or [
        "- None yet. Save an answer with `reference.py --note \"<title>\" --file <answer.md>`."]
    md += ["", "## Logs", ""] + [f"- {link(p)}" for p in logs]
    md += [f"- {link(p)}" for p in sorted(glob.glob(os.path.join(OUT, "*.log")) + glob.glob(os.path.join(OUT, "atf", "*.log")))]
    sdks = run(["dotnet", "--list-sdks"])
    gv = run([gx, "--version"]) if tool_exe("graphify") else (1, "")
    gver = re.sub(r"(?i)^graphify\s+", "", gv[1].strip().splitlines()[-1]) if gv[0] == 0 and gv[1].strip() else "not found"
    psd = os.path.join(sdir, "CodebaseScanner.psd1") if sdir else ""
    av = re.search(r"ModuleVersion\s*=\s*'([^']+)'", open(psd, encoding="utf-8", errors="ignore").read()) if psd and os.path.isfile(psd) else None
    md += ["", "## Tools", "", f"- modernization-assessment {skill_version()} (`{SKILL_DIR}`)",
           f"- Python {platform.python_version()} · graphify {gver}"
           f" · .NET SDKs {', '.join(s.split(' ')[0] for s in sdks[1].strip().splitlines()) if sdks[0] == 0 else 'none'}"
           + (f" · AWS Transform scanner {av.group(1)}" if av else ""), ""]
    hp = write_pair(os.path.join(REF, "README.md"), "\n".join(md) + "\n", f"Context pack: {cfg.get('client') or 'assessment'}")
    print(f"reference: {os.path.relpath(hp)} ({len(nl)} notes, {len(logs)} logs, {len(inputs)} inputs)")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--note", help="title of a chat answer to save under reference/notes/")
    ap.add_argument("--file", help="Markdown file with the note (default: stdin)")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    if a.note:
        add_note(a.note, open(a.file, encoding="utf-8").read() if a.file else sys.stdin.read())
    build(root, cfg, load_state(root))


if __name__ == "__main__":
    main()
