"""Assessment scope: which projects are .NET (assessed) and which are not (out of scope), plus how the .NET code is coupled to them.

The skill assesses .NET code only. Python, Node.js, Java and other projects found in the same repositories are listed as
out of scope (never edited, moved or scanned). A front-end folder inside a .NET web project is not ignored blindly: when the
.NET build or run time needs it (MSBuild runs npm, gulp writes into the project, Vite builds into wwwroot, a gulp task calls
dotnet publish, C# starts node), moving the .NET code without it breaks the .NET code too. `coupling()` finds that evidence.

Used by discover_estate.py (writes it into the inventory) and scan_repo.py (skips the out-of-scope folders, raises findings).
"""
import json
import os
import re

from _common import read_text, rel

MANIFESTS = {"package.json": "Node.js", "requirements.txt": "Python", "pyproject.toml": "Python", "setup.py": "Python", "pipfile": "Python",
             "pom.xml": "Java", "build.gradle": "Java", "build.gradle.kts": "Java", "go.mod": "Go", "gemfile": "Ruby",
             "composer.json": "PHP", "cargo.toml": "Rust"}
CONFIG_FILES = re.compile(r"(?i)^(vite\.config\.\w+|angular\.json|\.angular-cli\.json|webpack[\w.-]*\.js|gulpfile[\w.-]*\.js|gulp\.config\.js|"
                          r"tsconfig[\w.-]*\.json|package\.json|rollup\.config\.\w+|next\.config\.\w+|vue\.config\.js)$")
NODE_TOKEN = re.compile(r"(?i)(?<![\w.-])(npm|npx|yarn|pnpm|gulp|webpack|node(?:\.exe)?|ts-node|ng build)(?![\w-])")
BUILD_LINE = re.compile(r"(?i)<Exec\b|<Target\b|\bCommand=|<Import\b|<PackageReference\b|<SpaRoot|<SpaProxy|<Content\b|<None\b|<TypeScript")
RUNTIME_PKG = re.compile(r"(?i)(Microsoft\.AspNetCore\.NodeServices|Microsoft\.AspNetCore\.SpaServices|Jering\.Javascript\.NodeJS|NodeJs\.?Interop|Microsoft\.TypeScript\.MSBuild)")
OUT_PATTERNS = [
    re.compile(r"""\boutDir\s*[:=]\s*["']([^"']+)["']"""),
    re.compile(r""""?outputPath"?\s*:\s*"([^"]+)\""""),
    re.compile(r"""\bpath\s*:\s*(?:path\.(?:resolve|join)\([^)]*?,\s*)?["']([^"']+)["']"""),
    re.compile(r"""\bdest(?:ination)?\s*[:=(]\s*["']([^"']+)["']"""),
    re.compile(r"""\b(?:buildLocation|outputDir|distDir|publicPath)\s*[:=]\s*["']([^"']+)["']"""),
    re.compile(r"""\.pipe\(\s*gulp\.dest\(\s*["']([^"']+)["']"""),
    re.compile(r"""\boutput\s*:\s*["']([^"']*\.\.[^"']*)["']"""),
]
PARENT_STRING = re.compile(r"""["']((?:\.\.[/\\])+[^"'\s]*)["']""")  # "../SwiftUI/deploymentPackage/": a path that leaves the Node folder
NAMED_OUT = re.compile(r"\b(?:outDir|outputPath|buildLocation|outputDir|distDir)\b")
DOTNET_DRIVE =re.compile(r"(?i)\b(dotnet\s+(publish|build|msbuild)|gulp-dotnet-cli|msbuild(\.exe)?|nuget\s+(restore|pack))\b|require\(['\"]gulp-dotnet-cli['\"]\)")
RUNTIME_USE = re.compile(r"""(?i)(Process\.Start|ProcessStartInfo)\s*\(.{0,80}["'](node|node\.exe|npm|npm\.cmd|npx|ts-node)["']|\bINodeServices\b|\bNodeJSService\b|Jering\.Javascript""")
CI_FILES = re.compile(r"(?i)^(\.gitlab-ci\.ya?ml|jenkinsfile.*|azure-pipelines.*\.ya?ml|buildspec.*\.ya?ml|dockerfile.*|.*\.pubxml)$")
SKIP = {"node_modules", "bin", "obj", ".git", "packages", "dist", "bower_components", ".vs"}
OUTPUT_HINT = re.compile(r"(?i)(wwwroot|content|scripts|app_themes|themes|views|templates|static|public|deploymentpackage|publish|assets|css)")


def _walk(root, skip, depth=None):
    base = os.path.normpath(root)
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x.lower() not in skip and not x.startswith(".")]
        if depth is not None and os.path.relpath(d, base).count(os.sep) + (0 if d == base else 1) > depth:
            dirs[:] = []
        yield d, files


def _is_npm_manifest(path):
    try:
        obj = json.loads(read_text(path))
    except ValueError:
        return False
    return isinstance(obj, dict) and any(k in obj for k in ("name", "version", "dependencies", "devDependencies", "scripts", "main", "private", "workspaces"))


def find_non_dotnet(repo_root, skip, project_dirs):
    """Non-.NET project manifests, one entry per (folder, ecosystem). project_dirs: [(abs dir, project path)] for the .NET projects."""
    found = {}
    for d, files in _walk(repo_root, skip):
        for fn in files:
            eco = MANIFESTS.get(fn.lower())
            if not eco:
                continue
            if eco == "Node.js" and not _is_npm_manifest(os.path.join(d, fn)):
                continue  # a data file that happens to be called package.json (a request payload, not an npm project)
            key = (os.path.normpath(d), eco)
            e = found.setdefault(key, {"path": rel(d, repo_root) or ".", "ecosystem": eco, "manifests": []})
            e["manifests"].append(fn)
    out = []
    pdirs = sorted(project_dirs, key=lambda x: -len(x[0]))
    for (d, eco), e in sorted(found.items()):
        owner = next((p for pd, p in pdirs if d == pd or d.startswith(pd + os.sep)), None)
        e["abs"] = d
        e["embedded_in"] = owner  # inside a .NET project folder: the project's own front end / tooling
        e["name"] = os.path.basename(d) or os.path.basename(repo_root)
        out.append(e)
    return out


def _lines(path, limit=3_000_000):
    try:
        if os.path.getsize(path) > limit:
            return []
        return read_text(path).splitlines()
    except OSError:
        return []


def _resolve(base_dir, val):
    if re.match(r"^[a-zA-Z]:|^/|^\\\\|^[a-z]+://|\$|\{", val) or val in (".", "./", "/"):
        return None
    return os.path.normpath(os.path.join(base_dir, val.replace("\\", "/")))


def coupling(repo_root, np, dotnet_projects, skip=SKIP):
    """How the .NET code depends on the non-.NET project `np` (an entry from find_non_dotnet). Evidence only, no guesses."""
    signals = []

    def add(kind, file, line, text):
        if len(signals) < 40:
            signals.append({"kind": kind, "file": rel(file, repo_root) if os.path.isabs(file) else file, "line": line, "text": text.strip()[:160]})

    ndir = np["abs"]
    pdirs = [(os.path.normpath(os.path.dirname(os.path.join(repo_root, p["path"]))), p) for p in dotnet_projects]
    # 1. .NET project files that run or include the Node project
    ts_items, ts_first = 0, None
    for pd, p in pdirs:
        pf = os.path.join(repo_root, p["path"])
        proj_rel_to_node = os.path.relpath(ndir, pd).replace("\\", "/") if os.path.splitdrive(pd)[0] == os.path.splitdrive(ndir)[0] else ""
        owns = ndir == pd or ndir.startswith(pd + os.sep)  # the Node project sits inside this .NET project's folder
        for i, line in enumerate(_lines(pf), 1):
            if owns and re.search(r"<TypeScriptCompile\b", line):
                ts_items += 1
                ts_first = ts_first or (pf, i, line)
                continue
            if not owns and not (proj_rel_to_node and proj_rel_to_node.lower() + "/" in line.replace("\\", "/").lower() and "Include=" in line):
                continue  # a project elsewhere in the repository: not evidence about this Node project
            if (RUNTIME_PKG.search(line) and "PackageReference" in line) or re.search(r"<SpaRoot|<SpaProxy", line):
                add("spa-or-node-package", pf, i, line)
            elif BUILD_LINE.search(line) and NODE_TOKEN.search(line) and re.search(r"<Exec\b|Command=|<Target\b", line):
                add("msbuild-runs-node", pf, i, line)
            elif re.search(r"Microsoft\.TypeScript\.(Default\.props|targets)", line):
                add("typescript-in-msbuild", pf, i, line)
            elif re.search(r"<(Content|None)\s+Include=\"[^\"]*(gulpfile|webpack|package\.json)", line, re.I):
                add("project-lists-node-files", pf, i, line)
            elif proj_rel_to_node and proj_rel_to_node not in (".", "") and not proj_rel_to_node.startswith("..") and \
                    proj_rel_to_node.lower() + "/" in line.replace("\\", "/").lower() and "Include=" in line:
                add("project-includes-node-folder", pf, i, line)
    if ts_items and ts_first:
        add("typescript-in-msbuild", ts_first[0], ts_first[1], f"{ts_items} TypeScriptCompile items compiled by the .NET project (needs the TypeScript MSBuild targets)")
    # 2. where the Node build writes its output, and 3. whether it drives dotnet
    emits, separate = [], []

    def classify_target(path, i, line, tgt, named):
        if re.search(r"(?i)imgPath|url\(|targetPath|\.\./images", line) or os.path.normpath(repo_root).startswith(os.path.normpath(tgt)):
            return  # CSS image references and parent folders of the repository are not build outputs
        outside = os.path.relpath(tgt, repo_root).startswith("..")
        inside_proj = next((p["path"] for pd, p in pdirs if tgt == pd or tgt.startswith(pd + os.sep)), None)
        if outside or inside_proj:
            emits.append((path, i, tgt, outside, inside_proj))
        elif named:
            separate.append((path, i, tgt))

    for d, files in _walk(ndir, skip, depth=1):
        for fn in files:
            if not CONFIG_FILES.match(fn):
                continue
            path = os.path.join(d, fn)
            for i, line in enumerate(_lines(path), 1):
                if re.match(r"^\s*(//|\*|/\*)", line):
                    continue
                if DOTNET_DRIVE.search(line):
                    add("drives-dotnet-build", path, i, line)
                if not re.match(r"(?i)^(tsconfig|package\.json)", fn) and "require(" not in line and not re.search(r"\.(json|js|ts)[\"']", line):
                    for m in PARENT_STRING.finditer(line):
                        tgt = _resolve(d, m.group(1))
                        if tgt:
                            classify_target(path, i, line, tgt, False)
                for rx in OUT_PATTERNS:
                    for m in rx.finditer(line):
                        tgt = _resolve(d, m.group(1))
                        if tgt:
                            classify_target(path, i, line, tgt, bool(NAMED_OUT.search(line)))
    seen, per_proj = set(), {}
    for path, i, tgt, outside, inside_proj in emits:
        if tgt in seen:
            continue
        seen.add(tgt)
        if outside:
            add("emits-outside-repo", path, i, f"writes to {os.path.relpath(tgt, repo_root).replace(chr(92), '/')} (a folder outside this repository: needs the sibling repository checked out next to it)")
        elif inside_proj:
            per_proj.setdefault(inside_proj, []).append((path, i, tgt))
    for proj, items in per_proj.items():
        path, i, tgt = items[0]
        has_files = os.path.isdir(tgt) and any(f for _, _, f in os.walk(tgt))
        more = f" (+{len(items) - 1} more target folders in it)" if len(items) > 1 else ""
        add("emits-into-dotnet", path, i, f"writes to {rel(tgt, repo_root)} inside .NET project {proj}{more}; built output {'is committed' if has_files else 'is NOT in the repository (built on the build machine)'}")
    if separate and not seen:
        path, i, tgt = separate[0]
        add("emits-separate", path, i, f"builds into {rel(tgt, repo_root)}, a folder that no .NET project in this repository includes (deployed on its own)")
    # 4. build scripts and pipelines
    for d, files in _walk(ndir, skip, depth=1):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in (".cmd", ".bat", ".ps1", ".sh"):
                for i, line in enumerate(_lines(os.path.join(d, fn)), 1):
                    if NODE_TOKEN.search(line) and not re.match(r"^\s*(rem|::|#)", line, re.I):
                        add("manual-build-script", os.path.join(d, fn), i, line)
                        break
    ci_hits = 0
    for d, files in _walk(repo_root, skip, depth=4):
        for fn in files:
            if CI_FILES.match(fn):
                for i, line in enumerate(_lines(os.path.join(d, fn)), 1):
                    if NODE_TOKEN.search(line):
                        add("pipeline-builds-node", os.path.join(d, fn), i, line)
                        ci_hits += 1
                        break
    # 5. run time: C# starts node
    for d, files in _walk(repo_root, skip):
        for fn in files:
            if fn.lower().endswith(".cs"):
                p = os.path.join(d, fn)
                try:
                    if os.path.getsize(p) > 1_500_000:
                        continue
                    text = read_text(p)
                except OSError:
                    continue
                if "node" in text.lower() or "npm" in text.lower() or "Jering" in text:
                    for i, line in enumerate(text.splitlines(), 1):
                        if RUNTIME_USE.search(line):
                            add("runtime-node", p, i, line)
                            break
    kinds = {s["kind"] for s in signals}
    if "runtime-node" in kinds or "spa-or-node-package" in kinds:
        level = "runtime"
    elif "drives-dotnet-build" in kinds:
        level = "build-drives-dotnet"
    elif kinds & {"emits-into-dotnet", "emits-outside-repo", "msbuild-runs-node", "typescript-in-msbuild", "project-lists-node-files", "project-includes-node-folder"}:
        level = "build-time"
    elif "emits-separate" in kinds:
        level = "independent"
    else:
        level = "none-found"
    return {"level": level, "signals": signals, "pipeline_in_repo_builds_it": bool(ci_hits)}


LEVEL_TEXT = {
    "runtime": "the .NET application starts or hosts Node at run time",
    "build-drives-dotnet": "a Node build (gulp/npm) drives the .NET build or publish",
    "build-time": "the .NET build or its published output needs the Node build (assets or TypeScript)",
    "independent": "builds a separate deployable; no .NET project in the repository includes or serves its output (confirm how it is deployed)",
    "none-found": "no link from the .NET code to it was found",
}


def assess_scope(repo_root, skip, dotnet_projects):
    """Scope section of the inventory: out-of-scope projects with their coupling to the .NET code."""
    pdirs = [(os.path.normpath(os.path.dirname(os.path.join(repo_root, p["path"]))), p["path"]) for p in dotnet_projects]
    items = find_non_dotnet(repo_root, skip, pdirs)
    out = []
    for e in items:
        c = coupling(repo_root, e, dotnet_projects, skip) if (e["ecosystem"] == "Node.js" or e["embedded_in"]) else {"level": "none-found", "signals": [], "pipeline_in_repo_builds_it": False}
        own = any(pd == e["abs"] or pd.startswith(e["abs"] + os.sep) for pd, _ in pdirs)  # the folder holds .NET project files: never skipped
        out.append({"path": e["path"], "name": e["name"], "skippable": not own and e["path"] != ".", "ecosystem": e["ecosystem"], "manifests": sorted(e["manifests"]),
                    "relation": "embedded in .NET project " + e["embedded_in"] if e["embedded_in"] else "standalone folder",
                    "embedded_in": e["embedded_in"], "scope": "out of scope (not .NET)", "coupling": c["level"],
                    "coupling_meaning": LEVEL_TEXT[c["level"]], "signals": c["signals"], "pipeline_in_repo_builds_it": c["pipeline_in_repo_builds_it"]})
    return out


def skip_dirs(items):
    """Folders (relative, forward slashes) the scan skips: out-of-scope project folders that hold no .NET project files, however they are coupled."""
    return sorted({i["path"] for i in items if i.get("skippable")})
