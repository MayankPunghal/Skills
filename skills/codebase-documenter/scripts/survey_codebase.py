"""Deterministic inventory of the source tree: what is there, which stacks, which projects, where the config lives.

    python <skill>/scripts/survey_codebase.py [--max-depth 3]

Writes docs/_notes/00-survey.md and docs/_notes/areas.json (candidate research areas merged from top folders and,
when present, graph communities). Prints a short summary. No LLM work: the agent reads the result instead of
walking the tree itself.
"""
import argparse
import json
import os
import re
from collections import Counter, defaultdict

from _common import load_config, tick, utf8_stdout, write
from vendor_files import client_packages, is_vendored

SKIP = {".git", "node_modules", "bin", "obj", "packages", ".vs", "dist", "build", "target", "__pycache__", ".venv", "venv",
        ".idea", "graphify-out", "site", "publish", ".next", ".nuxt", "vendor", "coverage"}
STACK_MARKERS = [
    (r"\.sln$", ".NET solution"), (r"\.csproj$", ".NET project (C#)"), (r"\.vbproj$", ".NET project (VB)"),
    (r"\.sqlproj$", "SQL Server database project (SSDT)"), (r"\.dtproj$", "SSIS project"), (r"\.rptproj$", "SSRS report project"),
    (r"^package\.json$", "Node.js / JavaScript"), (r"^tsconfig\.json$", "TypeScript"), (r"^angular\.json$", "Angular"),
    (r"^next\.config\.(js|mjs|ts)$", "Next.js"), (r"^vite\.config\.(js|ts|mjs)$", "Vite"),
    (r"^pom\.xml$", "Java (Maven)"), (r"^build\.gradle(\.kts)?$", "Java/Kotlin (Gradle)"),
    (r"^pyproject\.toml$", "Python (pyproject)"), (r"^requirements.*\.txt$", "Python (requirements)"), (r"^manage\.py$", "Django"),
    (r"^go\.mod$", "Go"), (r"^Cargo\.toml$", "Rust"), (r"^Gemfile$", "Ruby"), (r"^composer\.json$", "PHP (Composer)"),
    (r"^Dockerfile$", "Docker"), (r"^docker-compose.*\.ya?ml$", "Docker Compose"), (r"\.tf$", "Terraform"),
    (r"^web\.config$", "IIS / ASP.NET config"), (r"^appsettings.*\.json$", ".NET Core config"), (r"\.edmx$", "Entity Framework (EDMX)"),
    (r"^Global\.asax$", "ASP.NET (System.Web)"), (r"^Startup\.cs$", "ASP.NET / OWIN startup"), (r"^Program\.cs$", ".NET entry point"),
    (r"\.rdl$", "SSRS report"), (r"\.dtsx$", "SSIS package"), (r"^openapi.*\.(ya?ml|json)$", "OpenAPI spec"), (r"\.proto$", "gRPC / protobuf"),
]
CONFIG_PAT = re.compile(r"(?i)(web|app)\.config$|appsettings.*\.json$|\.env(\..+)?$|settings\.py$|application\.(ya?ml|properties)$|config\.(ya?ml|json|toml)$")
LANG = {".cs": "C#", ".vb": "VB.NET", ".java": "Java", ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
        ".jsx": "JavaScript", ".go": "Go", ".rb": "Ruby", ".php": "PHP", ".sql": "SQL", ".cshtml": "Razor", ".razor": "Razor",
        ".kt": "Kotlin", ".rs": "Rust", ".scala": "Scala", ".swift": "Swift", ".vue": "Vue", ".svelte": "Svelte",
        ".fs": "F#", ".vbhtml": "Razor", ".aspx": "Web Forms markup", ".ascx": "Web Forms markup", ".master": "Web Forms markup",
        ".asmx": "ASP.NET service", ".ashx": "ASP.NET service", ".svc": "WCF service", ".asax": "ASP.NET service", ".xaml": "XAML",
        ".tt": "T4 template", ".proto": "Protobuf", ".ps1": "Scripts", ".psm1": "Scripts", ".bat": "Scripts", ".cmd": "Scripts",
        ".sh": "Scripts", ".vbs": "Scripts", ".config": "Config", ".yml": "Config / pipelines", ".yaml": "Config / pipelines",
        ".tf": "Infrastructure as code", ".bicep": "Infrastructure as code", ".rdl": "SSRS report", ".dtsx": "SSIS package",
        ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "CSS", ".less": "CSS"}
# minified / generated assets are not code to read or document
GENERIC_DIR = {"src", "source", "sources", "app", "apps", "code", "lib", "libs", "main", "projects", "solution", "web"}


GENERATED = re.compile(r"(?i)\.min\.(js|css)$|\.designer\.cs$|\.g\.cs$|\.g\.i\.cs$|assemblyinfo\.cs$|\.bundle\.js$")
ADAPTER_HINTS = {".NET project (C#)": "aspnet-mvc-ssdt (if ASP.NET MVC + SSDT) else generic-graph; always generic-di "
                                      "(DI, messages, pipeline, events, jobs: the calls graphify cannot see)",
                 "SQL Server database project (SSDT)": "generic-sql (or aspnet-mvc-ssdt)"}


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-depth", type=int, default=3)
    ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    src = cfg["source_root"]
    if not os.path.isdir(src):
        raise SystemExit(f"source root not found: {src}")
    exts, lines_by_ext, stacks, configs = Counter(), Counter(), defaultdict(list), []
    dir_files, dir_lines = Counter(), Counter()
    vend_files = vend_lines = 0
    pkgs = client_packages(src, SKIP)
    largest = []
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
        reld = os.path.relpath(d, src).replace("\\", "/")
        top = "/".join(reld.split("/")[:2]) if reld != "." else "."
        for f in files:
            p = os.path.join(d, f)
            e = os.path.splitext(f)[1].lower() or f
            exts[e] += 1
            dir_files[top] += 1
            for pat, label in STACK_MARKERS:
                if re.search(pat, f, re.I):
                    stacks[label].append(os.path.relpath(p, src).replace("\\", "/"))
            if CONFIG_PAT.search(f):
                configs.append(os.path.relpath(p, src).replace("\\", "/"))
            relp = os.path.relpath(p, src).replace("\\", "/")
            if e in LANG and not GENERATED.search(f) and is_vendored(p, relp, pkgs):
                try:
                    vend_lines += sum(1 for _ in open(p, encoding="utf-8", errors="ignore"))
                except OSError:
                    pass
                vend_files += 1
            elif e in LANG and not GENERATED.search(f):
                try:
                    n = sum(1 for _ in open(p, encoding="utf-8", errors="ignore"))
                except OSError:
                    n = 0
                lines_by_ext[e] += n
                dir_lines[top] += n
                largest.append((n, os.path.relpath(p, src).replace("\\", "/")))
    largest.sort(reverse=True)
    comm = []
    cj = os.path.join(cfg["docs_dir"], "_notes", "graph-communities.json")
    if os.path.exists(cj):
        comm = json.load(open(cj, encoding="utf-8"))
    out = ["# 00 — Source survey", "", f"Source root: `{src}`. Generated by `survey_codebase.py`; counts exclude {', '.join(sorted(SKIP))}.", "",
           "## Stacks detected", "", "| Stack | Evidence (first files) | Count |", "| --- | --- | ---: |"]
    for label, ps in sorted(stacks.items(), key=lambda kv: -len(kv[1])):
        out.append(f"| {label} | {', '.join('`' + x + '`' for x in ps[:3])} | {len(ps)} |")
    if vend_files:
        out += ["", f"Third-party front-end libraries copied into the repository (vendor folders, files named after a declared client-side "
                    f"package, or files with a library banner) are not "
                    f"counted as code: {vend_files:,} files, {vend_lines:,} lines."]
    out += ["", "## Files by type", "", "| Extension | Files | Lines (code) |", "| --- | ---: | ---: |"]
    for e, n in exts.most_common(25):
        out.append(f"| `{e}` | {n:,} | {lines_by_ext.get(e, 0):,} |")
    out += ["", "## Folders (two levels)", "", "| Folder | Files | Code lines |", "| --- | ---: | ---: |"]
    for d, n in dir_files.most_common(60):
        out.append(f"| `{d}` | {n:,} | {dir_lines.get(d, 0):,} |")
    out += ["", "## Largest code files (read these in full during research)", ""] + [f"- `{p}` — {n:,} lines" for n, p in largest[:30]]
    out += ["", "## Configuration files (key names only in the docs — never values)", ""] + [f"- `{c}`" for c in sorted(configs)[:80]]
    langs = Counter()
    for e, n in lines_by_ext.items():
        langs[LANG.get(e, e)] += n
    out[out.index("## Stacks detected") + 1:out.index("## Stacks detected") + 1] = [
        "", "Languages by code lines: " + ", ".join(f"{k} {v:,}" for k, v in langs.most_common(8)), ""]
    hints = sorted({ADAPTER_HINTS[s] for s in stacks if s in ADAPTER_HINTS})
    out += ["", "## Suggested adapters", "", "- generic-graph, generic-areas (always)"] + [f"- {h}" for h in hints]
    if any(s.startswith("SQL") for s in stacks) or exts.get(".sql"):
        out.append("- generic-sql (SQL files present)")
    # research areas: top folders by code volume, enriched with graph communities that live mostly in them
    areas = []
    total_lines = sum(dir_lines.values())
    floor = 200 if total_lines > 20000 else 0  # small codebases: every folder with code is an area
    for d, n in dir_lines.most_common(40):
        if n <= floor:
            continue
        if d == ".":  # files directly in the source root: solution-level scripts, build and deployment files
            areas.append({"id": None, "title": "Root Files", "paths": ["."], "code_lines": n, "communities": [],
                          "note": "files directly in the source root only (not subfolders): build, deployment and solution-level files"})
            continue
        pre_full = f"{src}/{d}".replace("\\", "/").lstrip("./")
        pre_rel = d.replace("\\", "/")

        def inside(f):  # graph paths are relative to the source root or to the workspace, depending on how it was built
            f = f.replace("\\", "/").lstrip("./")
            return f == pre_rel or f.startswith(pre_rel + "/") or f.startswith(pre_full)
        cs = [c["name"] for c in comm if any(inside(f) for f in c.get("folders", []))][:5]
        parts = d.split("/")
        name = parts[-1] if parts[-1].lower() not in GENERIC_DIR or len(parts) == 1 else f"{parts[-2]} {parts[-1]}"
        areas.append({"id": None, "title": name.replace("_", " ").title() if name.islower() else name.replace("_", " "),
                      "paths": [d], "code_lines": n, "communities": cs})
    for i, ar in enumerate(areas):
        ar["id"] = f"{10 + i * 5}-{re.sub(r'[^a-z0-9]+', '-', ar['title'].lower()).strip('-')}"
    write(os.path.join(cfg["docs_dir"], "_notes", "00-survey.md"), "\n".join(out) + "\n")
    ap_ = os.path.join(cfg["docs_dir"], "_notes", "areas.json")
    if not os.path.exists(ap_):
        write(ap_, json.dumps(areas, indent=1, ensure_ascii=False))
        print(f"areas.json: {len(areas)} candidate research areas (edit freely: merge, split, rename, reorder)")
    else:
        print("areas.json kept (already exists)")
    print(f"survey: {sum(exts.values()):,} files, {sum(lines_by_ext.values()):,} code lines; languages: "
          f"{', '.join(k for k, _ in langs.most_common(4))}; stacks: {', '.join(list(stacks)[:8]) or '-'}")
    print(f"wrote {cfg['docs_dir']}/_notes/00-survey.md")
    tick(cfg, "survey (")


if __name__ == "__main__":
    main()
