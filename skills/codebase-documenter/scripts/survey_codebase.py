"""Deterministic inventory of the source tree: what is there, which stacks, which projects, where the config lives.

    python <skill>/scripts/survey_codebase.py [--max-depth 3] [--refresh-areas]
    python <skill>/scripts/survey_codebase.py --pre      # before the graph build: vendored folders and largest folders only

Writes docs/_notes/00-survey.md and docs/_notes/areas.json (candidate research areas merged from top folders, ASP.NET MVC
controller features and, when present, graph communities). An existing areas.json is kept (it is usually edited by hand):
the new candidates go to areas.suggested.json instead, and --refresh-areas replaces areas.json (the old one is kept as
areas.json.bak). Vendored code (vendor_files.py, including graph.vendor_dirs) is never counted or proposed as an area.
Prints a short summary. No LLM work: the agent reads the result instead of walking the tree itself.
"""
import argparse
import fnmatch
import json
import os
import re
import shutil
from collections import Counter, defaultdict

from _common import load_config, tick, utf8_stdout, write
from vendor_files import configured_dirs, context, docs_kit_dirs, is_vendored

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
ADAPTER_HINTS = {".NET project (C#)": "generic-di (DI, messages, pipeline, events, jobs: the calls graphify cannot see), generic-api, "
                                      "generic-views",
                 "SQL Server database project (SSDT)": "generic-sql (or aspnet-mvc-ssdt when the web project is ASP.NET MVC)"}
ENGINE_MARKERS = [("SQL Server", ("System.Data.SqlClient", "Microsoft.Data.SqlClient", "EntityFramework.SqlServer",
                                  "Microsoft.EntityFrameworkCore.SqlServer")),
                  ("PostgreSQL", ("Npgsql",)), ("MySQL", ("MySql.Data", "MySqlConnector", "Pomelo.EntityFrameworkCore.MySql")),
                  ("Oracle", ("Oracle.ManagedDataAccess", "Oracle.DataAccess")), ("SQLite", ("System.Data.SQLite", "Microsoft.Data.Sqlite")),
                  ("MongoDB", ("MongoDB.Driver",)), ("Redis", ("StackExchange.Redis",)), ("Entity Framework 6", ('"EntityFramework"', "EntityFramework.6", 'Include="EntityFramework')),
                  ("EF Core", ("Microsoft.EntityFrameworkCore",)), ("Dapper", ('"Dapper"', 'Include="Dapper')),
                  ("ASP.NET MVC 5", ("Microsoft.AspNet.Mvc", "System.Web.Mvc")), ("ASP.NET Web API 2", ("Microsoft.AspNet.WebApi",)),
                  ("SignalR", ("Microsoft.AspNet.SignalR", "Microsoft.AspNetCore.SignalR"))]
MANIFEST = re.compile(r"(?i)\.(cs|vb|fs)proj$|^packages\.config$|^(web|app)\.config$|^appsettings.*\.json$|^Directory\.Packages\.props$")
# cross-cutting files that form the foundation area (start-up, hosting, filters, authorisation, configuration)
FOUNDATION_DIR = re.compile(r"(?i)^(?:.*/)?(?:App_Start|Filters|Authorization|Authorisation|Middleware|Middlewares|Infrastructure|Startup|Configuration)/")
FOUNDATION = re.compile(r"(?i)(?:^|/)(?:App_Start|Filters|Authorization|Authorisation|Middleware|Middlewares|Infrastructure|Startup|Configuration)/"
                        r"|(?:^|/)(?:Global\.asax\.(?:cs|vb)|Startup(?:\.\w+)?\.(?:cs|vb)|Program\.(?:cs|vb)|"
                        r"\w*(?:Filter|Attribute|Middleware)\.(?:cs|vb))$")
BIG_CONTROLLER = 3000  # lines: research it as several areas (by action group)
MVC_FEATURE_DIRS = ("Views/{stem}", "Scripts/{stem}*", "Scripts/{stem}/", "Models/{stem}*", "ViewModels/{stem}*", "Content/{stem}*")


def count_lines(p):
    try:
        return sum(1 for _ in open(p, encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def sql_definitions(paths):
    """(CREATE PROCEDURE / FUNCTION / VIEW / TRIGGER statements, CREATE TABLE statements) in .sql files, by keyword pairs
    (a count for the adapter hint, not a parse; generic-sql parses them properly)."""
    routines = tables = 0
    for p in paths:
        try:
            words = open(p, encoding="utf-8", errors="ignore").read().lower().split()
        except OSError:
            continue
        for k, w in enumerate(words):
            if w != "create":
                continue
            j = k + 3 if words[k + 1:k + 3] == ["or", "alter"] else k + 1  # CREATE OR ALTER PROCEDURE
            obj = words[j] if j < len(words) else ""
            if obj in ("procedure", "proc", "function", "view", "trigger"):
                routines += 1
            elif obj == "table":
                tables += 1
    return routines, tables


def mvc_areas(src, files_by_dir, line_of, vendored):
    """One candidate area per ASP.NET MVC controller (a feature): the controller plus Views/<stem>, Scripts/<stem>*,
    Models/<stem>*, ViewModels/<stem>*, Content/<stem>* of the same project (or MVC area). Returns (areas, claimed files)."""
    areas, claimed = [], set()
    for d, files in sorted(files_by_dir.items()):
        if not re.search(r"(^|/)Controllers$", d, re.I):
            continue
        base = d.rsplit("/", 1)[0] if "/" in d else ""
        for f in sorted(files):
            m = re.match(r"(\w+)Controller\.(cs|vb)$", f)
            if not m or m.group(1) in ("Base", "Api"):
                continue
            stem = m.group(1)
            ctl = f"{d}/{f}"
            members = [ctl]
            for pat in MVC_FEATURE_DIRS:
                full = ((base + "/") if base else "") + pat.format(stem=stem)
                for dd, ff in files_by_dir.items():
                    for x in ff:
                        rel = f"{dd}/{x}".lstrip("/")
                        if rel in vendored or rel in members:
                            continue
                        if full.endswith("/") and (rel.startswith(full) or dd == full.rstrip("/")):
                            members.append(rel)
                        elif not full.endswith("/") and (fnmatch.fnmatch(rel, full + ".*") or fnmatch.fnmatch(rel, full)
                                                         or fnmatch.fnmatch(rel, full + "/*") or rel.startswith(full.rstrip("*") + "/")):
                            members.append(rel)
            n = sum(line_of.get(x, 0) for x in members)
            paths = [ctl] + sorted({(((base + "/") if base else "") + pat.format(stem=stem)).rstrip("/")
                                    for pat in MVC_FEATURE_DIRS
                                    if any(x != ctl and fnmatch.fnmatch(x, ((base + "/") if base else "") + pat.format(stem=stem).rstrip("/") + "*")
                                           for x in members)})
            area = {"id": None, "title": re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem), "paths": paths, "code_lines": n,
                    "communities": [], "kind": "feature (MVC controller)"}
            if line_of.get(ctl, 0) > BIG_CONTROLLER:
                area["note"] = (f"the controller alone has {line_of[ctl]:,} lines: research it as several areas by action group "
                                "(split this entry once the groups are known)")
            areas.append(area)
            claimed.update(members)
    return areas, claimed


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-depth", type=int, default=3)
    ap.add_argument("--pre", action="store_true", help="before the graph: vendored and largest folders only, writes nothing")
    ap.add_argument("--refresh-areas", action="store_true", help="replace areas.json (old one kept as areas.json.bak)")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    src = cfg["source_root"]
    if not os.path.isdir(src):
        raise SystemExit(f"source root not found: {src}")
    exts, lines_by_ext, stacks, configs = Counter(), Counter(), defaultdict(list), []
    engines = defaultdict(list)
    dir_files, dir_lines = Counter(), Counter()
    vend_files = vend_lines = 0
    vend_by_dir, all_by_dir = Counter(), Counter()
    pkgs, vdirs = context(src, SKIP)
    largest, sql_files = [], []
    files_by_dir, line_of, vendored = defaultdict(list), {}, set()
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
        reld = os.path.relpath(d, src).replace("\\", "/")
        top = "/".join(reld.split("/")[:2]) if reld != "." else "."
        top3 = "/".join(reld.split("/")[:3]) if reld != "." else "."
        for f in files:
            p = os.path.join(d, f)
            e = os.path.splitext(f)[1].lower() or f
            relp = os.path.relpath(p, src).replace("\\", "/")
            files_by_dir["" if reld == "." else reld].append(f)
            exts[e] += 1
            dir_files[top] += 1
            if e == ".sql":
                sql_files.append(p)
            for pat, label in STACK_MARKERS:
                if re.search(pat, f, re.I):
                    stacks[label].append(relp)
            if CONFIG_PAT.search(f):
                configs.append(relp)
            if MANIFEST.search(f):  # databases and main frameworks from package references and provider names
                try:
                    mt = open(p, encoding="utf-8", errors="ignore").read()
                except OSError:
                    mt = ""
                for label, marks in ENGINE_MARKERS:
                    if any(mk in mt for mk in marks):
                        engines[label].append(relp)
            if e in LANG and not GENERATED.search(f) and is_vendored(p, relp, pkgs, vdirs):
                n = count_lines(p)
                vend_lines += n
                vend_files += 1
                vend_by_dir[top3] += n
                all_by_dir[top3] += n
                vendored.add(relp)
            elif e in LANG and not GENERATED.search(f):
                n = count_lines(p)
                lines_by_ext[e] += n
                dir_lines[top] += n
                all_by_dir[top3] += n
                line_of[relp] = n
                largest.append((n, relp))
    conf = configured_dirs()
    kits = [k for k in docs_kit_dirs(src, SKIP) if k not in conf]
    vendor_lines = ["## Vendored code (not counted, not graphed)", "",
                    f"{vend_files:,} files, {vend_lines:,} lines of copied third-party libraries and documentation output "
                    f"({len(conf)} configured folder(s) in graph.vendor_dirs, {len(kits)} documentation folder(s) of this skill, "
                    f"{len(vdirs) - len(conf) - len(kits)} library folder(s) detected).", ""]
    if vdirs:
        vendor_lines += ["| Folder | Source |", "| --- | --- |"] + [
            f"| `{x}` | {'graph.vendor_dirs' if x in conf else 'documentation workspace or installed docs kit' if x in kits else 'detected (versioned name + licence banner)'} |"
            for x in vdirs]
    suspects = [(d, n) for d, n in all_by_dir.most_common(40) if n and vend_by_dir.get(d, 0) < n * 0.5
                and re.search(r"(?i)(^|/)(scripts|content|js|lib|libs|assets|plugins|static)(/|$)", d) and n > 5000]
    if suspects:
        vendor_lines += ["", "Large script / asset folders still counted as code (check whether they are copied libraries; if so add them "
                         "to `graph.vendor_dirs` before building the graph):", ""] + [f"- `{d}`: {n:,} lines" for d, n in suspects[:10]]
    if a.pre:
        print("\n".join(vendor_lines))
        print("\n## Largest folders (all code, vendored included)\n")
        for d, n in all_by_dir.most_common(15):
            v = vend_by_dir.get(d, 0)
            print(f"- `{d}`: {n:,} lines" + (f" ({v:,} vendored)" if v else ""))
        print(f"\npre-survey: {sum(lines_by_ext.values()):,} code lines to graph, {vend_lines:,} vendored lines left out. "
              "Add any copied library folder above to graph.vendor_dirs in codebase-docs.json, then build the graph.")
        return
    largest.sort(reverse=True)
    comm = []
    cj = os.path.join(cfg["docs_dir"], "_notes", "graph-communities.json")
    if os.path.exists(cj):
        comm = json.load(open(cj, encoding="utf-8"))
    out = ["# 00 — Source survey", "", f"Source root: `{src}`. Generated by `survey_codebase.py`; counts exclude {', '.join(sorted(SKIP))}.", "",
           "## Stacks detected", "", "| Stack | Evidence (first files) | Count |", "| --- | --- | ---: |"]
    for label, ps in sorted(stacks.items(), key=lambda kv: -len(kv[1])):
        out.append(f"| {label} | {', '.join('`' + x + '`' for x in ps[:3])} | {len(ps)} |")
    for label, ps in engines.items():
        out.append(f"| {label} (package / provider reference) | {', '.join('`' + x + '`' for x in ps[:3])} | {len(ps)} |")
    out += [""] + vendor_lines
    out += ["", "## Files by type", "", "| Extension | Files | Lines (code) |", "| --- | ---: | ---: |"]
    for e, n in exts.most_common(25):
        out.append(f"| `{e}` | {n:,} | {lines_by_ext.get(e, 0):,} |")
    out += ["", "## Folders (two levels)", "", "| Folder | Files | Code lines |", "| --- | ---: | ---: |"]
    for d, n in dir_files.most_common(60):
        out.append(f"| `{d}` | {n:,} | {dir_lines.get(d, 0):,} |")
    out += ["", "## Largest code files (read these in full during research)", ""] + [f"- `{p}` — {n:,} lines" for n, p in largest[:30]]
    out += ["", "## Configuration files (key names only in the docs — never values)", ""] + [f"- `{c}`" for c in sorted(configs)[:80]]
    from safe_grep import secret_locations  # locations only: the values are never read into the notes
    secrets = [s for s in secret_locations(src) if s[0] not in vendored]
    if secrets:
        out += ["", "## Secret-looking values in the source (locations only)", "",
                "Each is a SEC finding candidate: credentials in source control or config, live or commented out. Values are "
                "not shown; open the file only if needed, and never copy the value. Search with `safe_grep.py`, not plain grep.", "",
                "| Location | Looks like |", "| --- | --- |"] + [f"| `{f}:{ln}` | {', '.join(k)} |" for f, ln, k in secrets[:60]]
        if len(secrets) > 60:
            out.append(f"| … | {len(secrets) - 60} more (`safe_grep.py --secrets`) |")
    langs = Counter()
    for e, n in lines_by_ext.items():
        langs[LANG.get(e, e)] += n
    out[out.index("## Stacks detected") + 1:out.index("## Stacks detected") + 1] = [
        "", "Languages by code lines: " + ", ".join(f"{k} {v:,}" for k, v in langs.most_common(8)), ""]
    # adapter hints: only what the evidence supports
    hints = sorted({ADAPTER_HINTS[s] for s in stacks if s in ADAPTER_HINTS})
    out += ["", "## Suggested adapters", "", "- generic-graph, generic-areas (always)"] + [f"- {h}" for h in hints]
    n_routines, n_tables = sql_definitions(sql_files)
    if "SQL Server database project (SSDT)" in stacks and any(s in stacks for s in ("ASP.NET (System.Web)",)):
        out.append("- aspnet-mvc-ssdt is an option (ASP.NET MVC web project + SSDT database project both present)")
    if n_routines or n_tables:
        out.append(f"- generic-sql ({len(sql_files)} .sql files define {n_tables} tables and {n_routines} routines)")
    from code_routines import find as code_routines
    cr = code_routines(src) if any(s in stacks for s in (".NET project (C#)", ".NET project (VB)")) else {"routines": {}}
    undefined = bool(cr["routines"]) and not n_routines
    if undefined:
        out.append(f"- generic-sql ({len(cr['routines'])} stored procedures named in code, none defined in the repository: "
                   "code-only database reference)")
    elif sql_files and not (n_routines or n_tables):
        out.append(f"- not generic-sql for DDL: the {len(sql_files)} .sql file(s) define no table or routine (scripts, grants, data)")
    if cr["routines"]:
        out += ["", "## Database code without database scripts" if not n_routines else "## Stored procedures called from code", "",
                f"{len(cr['routines'])} stored procedure name(s) are passed to the database from the code "
                + (f"and **none is defined in the repository**. The data model has to be documented from the code (call sites, "
                   "parameters, result mapping), not from DDL: keep generic-sql in the adapters, it lists them as code-only "
                   "procedures (db-code-routines.md), and ask the client for a schema export." if undefined else
                   f"(compare with the {n_routines} routines defined in .sql files; generic-sql marks the ones without a definition).")
                + (" Helper methods that run them: " + ", ".join(f"`{h}`" for h in sorted(cr.get("helpers", {}))) + "." if cr.get("helpers") else "")]
    # research areas: MVC controller features first, then top folders by code volume (vendored code never counts)
    areas = []
    feature, claimed = mvc_areas(src, files_by_dir, line_of, vendored)

    def comm_of(files):  # graph communities whose busiest files include these (paths relative to source root or workspace)
        want = {f.replace("\\", "/").lstrip("./") for f in files}
        def rank(c):  # position of the first matching file in the community's busiest-first list; -1 when none
            return next((i for i, g in enumerate(c.get("files", [])) if any(g.replace("\\", "/").lstrip("./").endswith(w) for w in want)), -1)
        hits = [(rank(c), -c.get("size", 0), c["name"]) for c in comm]
        return [name for r, _, name in sorted(h for h in hits if h[0] >= 0)][:5]
    for x in feature:
        x["communities"] = comm_of(x["paths"][:1])  # the controller is the feature's core
    # foundation: start-up, filters, authorisation, configuration and other cross-cutting files every feature relies on
    found = sorted(f for f in line_of if f not in claimed and FOUNDATION.search(f))
    if found:
        fpaths = sorted({(m.group(0).rstrip("/") if (m := FOUNDATION_DIR.search(f)) else f) for f in found})
        areas.append({"id": None, "title": "Foundation", "paths": fpaths, "code_lines": sum(line_of[f] for f in found),
                      "communities": comm_of(found), "kind": "foundation (cross-cutting)",
                      "note": "start-up and hosting, filters and authorisation, configuration readers, base classes: read first"})
        claimed = claimed | set(found)
    claimed_lines = Counter()
    for relp in claimed:  # keyed like dir_lines: the file's folder, two levels deep
        parts = relp.split("/")[:-1]
        claimed_lines["/".join(parts[:2]) if parts else "."] += line_of.get(relp, 0)
    total_lines = sum(dir_lines.values())
    floor = 200 if total_lines > 20000 else 0  # small codebases: every folder with code is an area
    areas += [x for x in feature if x["code_lines"] > (floor // 4)]
    for d, n in dir_lines.most_common(40):
        rest = n - claimed_lines.get(d, 0)
        if rest <= floor or rest <= 0:
            continue
        if d == ".":  # files directly in the source root: solution-level scripts, build and deployment files
            areas.append({"id": None, "title": "Root Files", "paths": ["."], "code_lines": rest, "communities": [],
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
        area = {"id": None, "title": name.replace("_", " ").title() if name.islower() else name.replace("_", " "),
                "paths": [d], "code_lines": rest, "communities": cs}
        if claimed_lines.get(d):
            area["kind"] = "shared (rest of a folder)"
            area["note"] = (f"the folder minus the files already in the feature and foundation areas "
                            f"({sum(1 for x in feature if x['paths'][0].startswith(d + '/'))} controller features): shared helpers, base classes, data access")
        areas.append(area)
    for i, ar in enumerate(areas):
        ar["id"] = f"{10 + i * 5}-{re.sub(r'[^a-z0-9]+', '-', ar['title'].lower()).strip('-')}"
    write(os.path.join(cfg["docs_dir"], "_notes", "00-survey.md"), "\n".join(out) + "\n")
    summary = [k for k in ("ASP.NET MVC 5", "ASP.NET Web API 2", "SignalR", "Entity Framework 6", "EF Core", "Dapper") if k in engines]
    summary += [k for k in ("SQL Server", "PostgreSQL", "MySQL", "Oracle", "SQLite", "MongoDB", "Redis") if k in engines]
    write(os.path.join(cfg["docs_dir"], "_notes", "survey.json"), json.dumps({  # machine-readable: make_agent_skill's Stack line
        "stacks": {k: len(v) for k, v in stacks.items()}, "languages": dict(langs.most_common(10)), "stack_summary": summary,
        "vendored_files": vend_files, "code_lines": sum(lines_by_ext.values()),
        "procedures_named_in_code": len(cr["routines"]), "sql_routines_defined": n_routines, "sql_tables_defined": n_tables},
        indent=1, ensure_ascii=False))
    ap_ = os.path.join(cfg["docs_dir"], "_notes", "areas.json")
    sug = os.path.join(cfg["docs_dir"], "_notes", "areas.suggested.json")
    if a.refresh_areas and os.path.exists(ap_):
        shutil.copy2(ap_, ap_ + ".bak")
    if a.refresh_areas or not os.path.exists(ap_):
        write(ap_, json.dumps(areas, indent=1, ensure_ascii=False))
        if os.path.exists(sug):
            os.remove(sug)
        print(f"areas.json: {len(areas)} candidate research areas ({len(feature)} MVC controller features) "
              "(edit freely: merge, split, rename, reorder)" + (" — previous file kept as areas.json.bak" if a.refresh_areas else ""))
    else:
        write(sug, json.dumps(areas, indent=1, ensure_ascii=False))
        print(f"areas.json kept (already exists); {len(areas)} fresh candidates written to areas.suggested.json "
              "(compare, or rerun with --refresh-areas to replace areas.json)")
    print(f"survey: {sum(exts.values()):,} files, {sum(lines_by_ext.values()):,} code lines; languages: "
          f"{', '.join(k for k, _ in langs.most_common(4))}; stacks: {', '.join(list(stacks)[:8]) or '-'}"
          + (f"; vendored: {vend_files:,} files left out" if vend_files else "")
          + (f"; {len(secrets)} secret-looking value(s) (locations in the survey)" if secrets else ""))
    print(f"wrote {cfg['docs_dir']}/_notes/00-survey.md")
    tick(cfg, "survey (")


if __name__ == "__main__":
    main()
