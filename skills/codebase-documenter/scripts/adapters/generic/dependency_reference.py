"""Project and package dependencies from build manifests (no build, no network).

Writes docs/reference/dependencies.md:
  - project graph (Mermaid), layers in dependency order (layer 0 depends on no other project) and cycles
  - every project (anchor prj-…): manifest, framework / runtime, output, depends on, used by, packages
  - every third-party package (anchor pkg-…): versions in use (version drift flagged) and the projects using it
and docs/agent/dependencies.json with the same data for tools.

.NET packages are enriched OFFLINE from the NuGet package folders already on this machine (NUGET_PACKAGES, ~/.nuget/packages,
a solution-level packages/ folder): licence (from the .nuspec), the frameworks the package builds for, and whether the
version in use only runs on Windows (native binaries only for win-* or only net*-windows builds). A package that was
never restored here shows "not in local cache"; nothing is fetched from the network.

Manifests read: .NET *.csproj / *.vbproj / *.fsproj (ProjectReference, PackageReference, packages.config, central
versions from Directory.Packages.props), package.json (npm / yarn / pnpm workspaces), pyproject.toml and
requirements*.txt, pom.xml, build.gradle(.kts), go.mod, Cargo.toml. Options (adapter_options.generic-deps):
skip_regex, include_dev (default true: dev / test dependencies are listed and marked "dev").
"""
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

try:
    import tomllib
except ImportError:  # Python 3.10
    tomllib = None

CFG = json.load(open("codebase-docs.json", encoding="utf-8"))
DOCS = CFG.get("docs_dir", "docs")
OUT = os.path.join(DOCS, "reference")
ROOT = os.environ.get("DOCS_SOURCE_ROOT") or CFG.get("source_root", ".")
OPT = CFG.get("adapter_options", {}).get("generic-deps", {})
SKIP = re.compile(OPT.get("skip_regex", r"(^|/)(\.git|bin|obj|node_modules|dist|build|out|target|vendor|packages|\.venv|venv|__pycache__)(/|$)"), re.I)
INCLUDE_DEV = OPT.get("include_dev", True)
MAX_DIAGRAM = OPT.get("max_diagram_projects", 80)
BACK = "[↑ Back to index](#index)"


def slug(*parts):
    return re.sub(r"[^a-z0-9]+", "-", "-".join(str(p) for p in parts).lower()).strip("-")


def rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def text(p):
    try:
        return open(p, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return ""


def local(tag):
    return tag.rsplit("}", 1)[-1]


def xml(p):
    try:
        return ET.fromstring(text(p).encode("utf-8"))
    except ET.ParseError:
        return None


def toml(p):
    t = text(p)
    if tomllib:
        try:
            return tomllib.loads(t)
        except Exception:
            return {}
    # minimal fallback: [project] name / dependencies = [ ... ]
    name = re.search(r'(?m)^name\s*=\s*"([^"]+)"', t)
    deps = re.search(r"(?ms)^dependencies\s*=\s*\[(.*?)\]", t)
    return {"project": {"name": name.group(1) if name else "", "dependencies": re.findall(r'"([^"]+)"', deps.group(1)) if deps else []}}


def project(path, name, kind):
    return {"name": name, "file": rel(path), "kind": kind, "framework": "", "output": "", "refs": set(), "ref_names": set(),
            "packages": {}}


def add_pkg(p, name, version="", dev=False):
    if name and (INCLUDE_DEV or not dev):
        p["packages"][name] = {"version": (version or "").strip(), "dev": dev}


def central_versions(path, cache={}):
    """Directory.Packages.props (NuGet central package management) nearest above the project."""
    d = os.path.dirname(os.path.abspath(path))
    while True:
        if d not in cache:
            f = os.path.join(d, "Directory.Packages.props")
            vers = {}
            if os.path.exists(f):
                r = xml(f)
                for e in (r.iter() if r is not None else []):
                    if local(e.tag) == "PackageVersion" and e.get("Include"):
                        vers[e.get("Include")] = e.get("Version", "")
            cache[d] = vers or None
        if cache[d] is not None:
            return cache[d]
        up = os.path.dirname(d)
        if up == d or not up.startswith(os.path.abspath(ROOT)):
            return {}
        d = up


def parse_dotnet(path):
    p = project(path, os.path.splitext(os.path.basename(path))[0], ".NET")
    r = xml(path)
    if r is None:
        return p
    tfm, out = [], ""
    cpm = None
    for e in r.iter():
        t, inc = local(e.tag), e.get("Include") or e.get("Update") or ""
        if t in ("TargetFramework", "TargetFrameworks", "TargetFrameworkVersion") and e.text:
            tfm += [x.strip() for x in e.text.split(";") if x.strip() and "$(" not in x]
        elif t == "OutputType" and e.text:
            out = e.text.strip()
        elif t == "ProjectReference" and inc:
            p["refs"].add(os.path.normpath(os.path.join(os.path.dirname(path), inc.replace("\\", os.sep))))
        elif t == "PackageReference" and e.get("Include"):
            ver = e.get("Version") or next((c.text for c in e if local(c.tag) == "Version" and c.text), "")
            if not ver:
                cpm = central_versions(path) if cpm is None else cpm
                ver = cpm.get(inc, "")
            dev = (e.get("PrivateAssets") or "").lower() == "all"
            add_pkg(p, inc, ver, dev)
    pc = os.path.join(os.path.dirname(path), "packages.config")
    if os.path.exists(pc):
        r2 = xml(pc)
        for e in (r2.iter() if r2 is not None else []):
            if local(e.tag) == "package" and e.get("id"):
                add_pkg(p, e.get("id"), e.get("version", ""), e.get("developmentDependency") == "true")
    p["framework"] = ";".join(sorted(set(tfm)))
    p["output"] = out or "Library"
    return p


def parse_npm(path):
    try:
        d = json.loads(text(path) or "{}")
    except ValueError:
        d = {}
    p = project(path, d.get("name") or os.path.basename(os.path.dirname(path)) or "root", "npm")
    p["framework"] = ("node " + d["engines"]["node"]) if isinstance(d.get("engines"), dict) and d["engines"].get("node") else ""
    p["output"] = "private" if d.get("private") else ("library" if d.get("main") or d.get("exports") else "")
    for sec, dev in (("dependencies", False), ("peerDependencies", False), ("optionalDependencies", False), ("devDependencies", True)):
        for n, v in (d.get(sec) or {}).items():
            if str(v).startswith(("workspace:", "file:", "link:")):
                p["ref_names"].add(n)
            else:
                add_pkg(p, n, str(v), dev)
                p["ref_names"].add(n)  # resolved to a project later if a workspace package has this name
    return p


REQ = re.compile(r"^\s*([A-Za-z0-9_.\-\[\]]+)\s*([<>=!~^].*)?$")


def parse_python(path):
    folder = os.path.dirname(path)
    if path.endswith(".toml"):
        d = toml(path)
        proj = d.get("project") or {}
        poetry = (d.get("tool") or {}).get("poetry") or {}
        p = project(path, proj.get("name") or poetry.get("name") or os.path.basename(folder), "Python")
        p["framework"] = ("python " + proj["requires-python"]) if proj.get("requires-python") else ""
        for dep in proj.get("dependencies") or []:
            m = REQ.match(re.split(r";", dep)[0])
            if m:
                add_pkg(p, re.sub(r"\[.*\]", "", m.group(1)), (m.group(2) or "").strip())
        for grp, deps in (proj.get("optional-dependencies") or {}).items():
            for dep in deps:
                m = REQ.match(re.split(r";", dep)[0])
                if m:
                    add_pkg(p, re.sub(r"\[.*\]", "", m.group(1)), (m.group(2) or "").strip(), dev=True)
        for n, v in (poetry.get("dependencies") or {}).items():
            if n.lower() == "python":
                p["framework"] = f"python {v}"
            elif isinstance(v, dict) and v.get("path"):
                p["refs"].add(os.path.normpath(os.path.join(folder, v["path"])))
            else:
                add_pkg(p, n, v if isinstance(v, str) else (v.get("version", "") if isinstance(v, dict) else ""))
        return p
    p = project(path, os.path.basename(folder) or "root", "Python")
    for line in text(path).splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        m = REQ.match(line.split(";")[0])
        if m:
            add_pkg(p, re.sub(r"\[.*\]", "", m.group(1)), (m.group(2) or "").strip(), dev="dev" in os.path.basename(path) or "test" in os.path.basename(path))
    return p


def parse_maven(path):
    r = xml(path)
    p = project(path, os.path.basename(os.path.dirname(path)), "Maven")
    if r is None:
        return p

    def child(e, name):
        return next((c.text.strip() for c in e if local(c.tag) == name and c.text), "")
    p["name"] = child(r, "artifactId") or p["name"]
    p["group"] = child(r, "groupId") or next((child(c, "groupId") for c in r if local(c.tag) == "parent"), "")
    p["output"] = child(r, "packaging") or "jar"
    props = {local(c.tag): (c.text or "").strip() for e in r if local(e.tag) == "properties" for c in e}
    p["framework"] = ("java " + (props.get("maven.compiler.release") or props.get("java.version") or props.get("maven.compiler.source") or "")).strip()
    if p["framework"] == "java":
        p["framework"] = ""
    for e in r.iter():
        if local(e.tag) == "dependency":
            g, a, v = child(e, "groupId"), child(e, "artifactId"), child(e, "version")
            v = re.sub(r"\$\{([^}]+)\}", lambda m: props.get(m.group(1), m.group(0)), v)
            add_pkg(p, f"{g}:{a}", v, child(e, "scope") == "test")
            p["ref_names"].add(a)
        elif local(e.tag) == "module" and e.text:
            pass  # aggregation only; dependency direction comes from <dependency>
    return p


def parse_gradle(path):
    t = text(path)
    folder = os.path.dirname(path)
    p = project(path, os.path.basename(folder), "Gradle")
    for m in re.finditer(r"(\w+)\s*\(?\s*project\(\s*['\"]:?([^'\"]+)['\"]\s*\)", t):
        p["ref_names"].add(m.group(2).split(":")[-1])
    for m in re.finditer(r"(\w+)\s*\(?\s*['\"]([\w.\-]+):([\w.\-]+):([^'\"]+)['\"]", t):
        add_pkg(p, f"{m.group(2)}:{m.group(3)}", m.group(4), m.group(1).lower().startswith("test"))
    return p


def parse_go(path):
    t = text(path)
    m = re.search(r"(?m)^module\s+(\S+)", t)
    p = project(path, (m.group(1) if m else os.path.basename(os.path.dirname(path))), "Go")
    gv = re.search(r"(?m)^go\s+(\S+)", t)
    p["framework"] = f"go {gv.group(1)}" if gv else ""
    body = "\n".join(re.findall(r"(?ms)^require\s*\((.*?)\)", t)) + "\n" + "\n".join(re.findall(r"(?m)^require\s+([^(\n].*)$", t))
    for line in body.splitlines():
        parts = line.split("//")[0].split()
        if len(parts) >= 2:
            add_pkg(p, parts[0], parts[1], "// indirect" in line)
    for line in re.findall(r"(?m)^\s*(?:replace\s+)?(\S+)(?:\s+\S+)?\s*=>\s*(\.{1,2}/\S+)", t):
        p["refs"].add(os.path.normpath(os.path.join(os.path.dirname(path), line[1])))
        p["packages"].pop(line[0], None)
    return p


def parse_cargo(path):
    d = toml(path)
    p = project(path, (d.get("package") or {}).get("name") or os.path.basename(os.path.dirname(path)), "Cargo")
    for sec, dev in (("dependencies", False), ("dev-dependencies", True), ("build-dependencies", True)):
        for n, v in (d.get(sec) or {}).items():
            if isinstance(v, dict) and v.get("path"):
                p["refs"].add(os.path.normpath(os.path.join(os.path.dirname(path), v["path"])))
            else:
                add_pkg(p, n, v if isinstance(v, str) else (v.get("version", "") if isinstance(v, dict) else ""), dev)
    return p


PARSERS = [(re.compile(r"\.(csproj|vbproj|fsproj)$", re.I), parse_dotnet), (re.compile(r"^package\.json$"), parse_npm),
           (re.compile(r"^pyproject\.toml$"), parse_python), (re.compile(r"^requirements[\w.\-]*\.txt$", re.I), parse_python),
           (re.compile(r"^pom\.xml$"), parse_maven), (re.compile(r"^build\.gradle(\.kts)?$"), parse_gradle),
           (re.compile(r"^go\.mod$"), parse_go), (re.compile(r"^Cargo\.toml$"), parse_cargo)]


def nuget_dirs():
    dirs = [os.environ.get("NUGET_PACKAGES") or "", os.path.join(os.path.expanduser("~"), ".nuget", "packages")]
    for d, sub, _ in os.walk(ROOT):
        r = rel(d)
        if "packages" in sub and r.count("/") < 3:
            dirs.append(os.path.join(d, "packages"))
        sub[:] = [x for x in sub if not SKIP.search((r + "/" + x).lstrip("./"))] if r.count("/") < 3 else []
    return [d for d in dict.fromkeys(dirs) if d and os.path.isdir(d)]


def nuget_info(name, version, dirs, cache={}):
    """Licence, target frameworks and Windows-only flag of a restored package version (None when not restored here)."""
    v = (version or "").strip("[]() ").split(",")[0].strip()
    key = (name.lower(), v.lower())
    if key in cache:
        return cache[key]
    cands = []
    for d in dirs:
        cands += [os.path.join(d, name.lower(), v.lower()), os.path.join(d, f"{name}.{v}")]
    folder = next((c for c in cands if v and os.path.isdir(c)), None)
    info = None
    if folder:
        spec = next((os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".nuspec")), None)
        lic = ""
        if spec:
            r = xml(spec)
            for e in (r.iter() if r is not None else []):
                t = local(e.tag)
                if t == "license" and e.text:
                    lic = e.text.strip() if (e.get("type") or "expression") == "expression" else f"file {e.text.strip()}"
                elif t == "licenseUrl" and e.text and not lic:
                    lic = e.text.strip()
        libs = sorted(x.lower() for x in os.listdir(os.path.join(folder, "lib"))) if os.path.isdir(os.path.join(folder, "lib")) else []
        rt = os.path.join(folder, "runtimes")
        rids = sorted(x for x in os.listdir(rt) if os.path.isdir(os.path.join(rt, x, "native"))) if os.path.isdir(rt) else []
        win_native = bool(rids) and all(x.lower().startswith("win") for x in rids)
        win_lib = bool(libs) and all("-windows" in x or x.startswith(("net4", "net3", "net2")) for x in libs) and any("-windows" in x for x in libs)
        net_fx_only = bool(libs) and all(x.startswith(("net4", "net3", "net2")) for x in libs)
        info = {"licence": lic, "frameworks": libs, "native_rids": rids, "windows_only": win_native or win_lib,
                "why": ("native binaries only for " + ", ".join(rids)) if win_native else ("builds only for " + ", ".join(libs)) if win_lib
                else ("builds only for .NET Framework (" + ", ".join(libs) + ")") if net_fx_only else "",
                "netfx_only": net_fx_only}
    cache[key] = info
    return info


def discover():
    projects = []
    for d, dirs, files in os.walk(ROOT):
        r = rel(d)
        dirs[:] = [x for x in dirs if not SKIP.search((r + "/" + x).lstrip("./"))]
        has_pyproject = "pyproject.toml" in files
        for f in sorted(files):
            if has_pyproject and f.lower().startswith("requirements"):
                continue  # pyproject is the project; requirements files there are lock-like duplicates
            for rx, fn in PARSERS:
                if rx.search(f):
                    projects.append(fn(os.path.join(d, f)))
                    break
    return projects


def layers(ids, deps):
    level, cycles, state = {}, [], {}

    def visit(i, stack):
        if i in level:
            return level[i]
        if state.get(i) == "busy":
            cyc = stack[stack.index(i):] + [i]
            if sorted(cyc[:-1]) not in [sorted(c[:-1]) for c in cycles]:
                cycles.append(cyc)
            return 0
        state[i] = "busy"
        lv = 1 + max((visit(j, stack + [i]) for j in deps[i]), default=-1)
        state[i] = "done"
        level[i] = lv
        return lv
    for i in ids:
        visit(i, [])
    return level, cycles


def main():
    projects = discover()
    if not projects:
        print("dependencies: no manifests found")
        return
    by_path = {os.path.normpath(os.path.join(ROOT, p["file"])): k for k, p in enumerate(projects)}
    by_dir = defaultdict(list)
    for k, p in enumerate(projects):
        by_dir[os.path.normpath(os.path.dirname(os.path.join(ROOT, p["file"])))].append(k)
    by_name = defaultdict(list)
    for k, p in enumerate(projects):
        by_name[p["name"].lower()].append(k)
    deps, users = defaultdict(set), defaultdict(set)
    for k, p in enumerate(projects):
        for ref in p["refs"]:
            ref = os.path.normpath(ref)
            for t in ([by_path[ref]] if ref in by_path else by_dir.get(ref, [])):
                if t != k:
                    deps[k].add(t)
        for n in p["ref_names"]:
            for t in by_name.get(n.lower(), []):
                if t != k and projects[t]["kind"] == p["kind"]:
                    deps[k].add(t)
                    p["packages"].pop(n, None)
                    for key in [x for x in p["packages"] if x.endswith(":" + n)]:
                        p["packages"].pop(key, None)  # Maven / Gradle group:artifact of a sibling module
    for k, ts in deps.items():
        for t in ts:
            users[t].add(k)
    names = [p["name"] for p in projects]
    dup = {n for n in names if names.count(n) > 1}
    label = [p["name"] + (f" ({os.path.dirname(p['file']) or '.'})" if p["name"] in dup else "") for p in projects]
    aid = [slug("prj", label[k]) for k in range(len(projects))]
    level, cycles = layers(range(len(projects)), deps)

    pkgs = defaultdict(dict)  # name -> {project index: (version, dev)}
    for k, p in enumerate(projects):
        for n, v in p["packages"].items():
            pkgs[n][k] = (v["version"], v["dev"])
    ndirs = nuget_dirs() if any(p["kind"] == ".NET" and p["packages"] for p in projects) else []
    meta = {}  # name -> {version: nuget_info}
    for n, used in pkgs.items():
        if any(projects[k]["kind"] == ".NET" for k in used):
            meta[n] = {ver: nuget_info(n, ver, ndirs) for ver in sorted({v for v, _ in used.values() if v})}
    for k, p in enumerate(projects):
        for n, v in p["packages"].items():
            i = (meta.get(n) or {}).get(v["version"])
            if i:
                v.update({"licence": i["licence"], "windows_only": i["windows_only"]})

    def pinfo(n):
        infos = [i for i in (meta.get(n) or {}).values() if i]
        if n not in meta:
            return "", ""
        if not infos:
            return "not in local cache", ""
        lic = ", ".join(sorted({i["licence"] for i in infos if i["licence"]})) or "not declared"
        plat = "; ".join(sorted({("**Windows-only**: " + i["why"]) if i["windows_only"] else i["why"] for i in infos if i["why"]})) or \
            ", ".join(sorted({f for i in infos for f in i["frameworks"]})) or "—"
        return lic, plat

    def plink(k):
        return f"[{label[k]}](#{aid[k]})"

    order = sorted(range(len(projects)), key=lambda k: (level.get(k, 0), label[k].lower()))
    out = ["# Dependencies", "",
           f"Projects and third-party packages read from the build manifests ({len(projects)} projects, {len(pkgs)} packages). "
           "Layer 0 projects depend on no other project, so they can be built, changed or ported first; each layer only "
           "depends on lower layers. Versions are as declared (ranges are not resolved).", "", '<a id="index"></a>', "",
           "- [Project graph](#project-graph) · [Layers](#layers) · [Projects](#projects) · [Packages](#packages)", ""]
    out += ['<a id="project-graph"></a>', "", "## Project graph", "", BACK, ""]
    linked = [k for k in order if deps[k] or users[k]]
    if linked and len(linked) <= MAX_DIAGRAM:
        out += ["Arrows point from a project to the project it depends on.", "", "```mermaid", "graph LR"]
        out += [f'  p{k}["{label[k]}"]' for k in linked]
        out += [f"  p{k} --> p{t}" for k in linked for t in sorted(deps[k])]
        out += ["```", ""]
    else:
        out += [("No project references between projects." if not linked else
                 f"{len(linked)} connected projects: too many for one diagram; see the layers and tables below."), ""]
    out += ['<a id="layers"></a>', "", "## Layers", "", BACK, "", "| Layer | Projects |", "| ---: | --- |"]
    for lv in sorted(set(level.values())):
        out.append(f"| {lv} | {', '.join(plink(k) for k in order if level.get(k) == lv)} |")
    if cycles:
        out += ["", "Cycles (these projects reference each other; break the cycle before splitting or porting them):", ""]
        out += ["- " + " → ".join(label[k] for k in c) for c in cycles]
    out += ["", '<a id="projects"></a>', "", "## Projects", "", BACK, "",
            "| Project | Kind | Framework / runtime | Output | Depends on | Used by | Packages |", "| --- | --- | --- | --- | --- | --- | ---: |"]
    for k in order:
        p = projects[k]
        out.append(f"| {plink(k)} | {p['kind']} | {p['framework'] or '—'} | {p['output'] or '—'} | "
                   f"{', '.join(plink(t) for t in sorted(deps[k], key=lambda t: label[t])) or '—'} | "
                   f"{', '.join(plink(t) for t in sorted(users[k], key=lambda t: label[t])) or '—'} | {len(p['packages'])} |")
    for k in order:
        p = projects[k]
        out += ["", f'<a id="{aid[k]}"></a>', "", f"### {label[k]}", "", f"File: `{p['file']}` · {BACK}", ""]
        out.append(f"- Kind: {p['kind']}" + (f" · framework / runtime: {p['framework']}" if p["framework"] else "")
                   + (f" · output: {p['output']}" if p["output"] else "") + f" · layer {level.get(k, 0)}")
        out.append("- Depends on: " + (", ".join(plink(t) for t in sorted(deps[k], key=lambda t: label[t])) or "—"))
        out.append("- Used by: " + (", ".join(plink(t) for t in sorted(users[k], key=lambda t: label[t])) or "—"))
        if p["packages"]:
            out.append("- Packages: " + ", ".join(
                f"[{n}](#{slug('pkg', n)}) {v['version']}".rstrip() + (" (dev)" if v["dev"] else "")
                for n, v in sorted(p["packages"].items(), key=lambda kv: kv[0].lower())))
    out += ["", '<a id="packages"></a>', "", "## Packages", "", BACK, "",
            "A package with more than one declared version is marked ⚠ (version drift: align before upgrading or porting)."
            + (" Licence and platform of .NET packages come from the NuGet packages restored on this machine (no network): "
               "**Windows-only** means the version in use ships native binaries only for Windows or builds only for net*-windows; "
               "a package that builds only for .NET Framework needs a newer version or a replacement to run on modern .NET."
               if meta else ""), "",
            "| Package | Versions | Licence | Platform | Used by |" if meta else "| Package | Versions | Used by |",
            "| --- | --- | --- | --- | --- |" if meta else "| --- | --- | --- |"]
    drift = 0
    winonly = []
    for n in sorted(pkgs, key=str.lower):
        vers = sorted({v for v, _ in pkgs[n].values() if v})
        drift += len(vers) > 1
        lic, plat = pinfo(n)
        winonly += [n] if "Windows-only" in plat else []
        out.append(f'| <a id="{slug("pkg", n)}"></a>**{n}** | {", ".join(vers) or "—"}{" ⚠" if len(vers) > 1 else ""} | '
                   + (f"{lic or '—'} | {plat or '—'} | " if meta else "")
                   + ", ".join(plink(k) + (f" {v}" if len(vers) > 1 else "") + (" (dev)" if dev else "")
                               for k, (v, dev) in sorted(pkgs[n].items(), key=lambda kv: label[kv[0]])) + " |")
    if winonly:
        out += ["", f"Windows-only packages ({len(winonly)}): " + ", ".join(f"[{n}](#{slug('pkg', n)})" for n in winonly)
                + ". The projects using them cannot run on Linux until the package is replaced or upgraded to a cross-platform version."
                + (" Code-level Linux issues: [platform portability](platform-portability.md)." if "generic-portability" in CFG.get("adapters", []) else "")]
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "dependencies.md"), "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    agent = os.path.join(DOCS, "agent")
    os.makedirs(agent, exist_ok=True)
    data = {"projects": [{"name": label[k], "anchor": aid[k], "file": projects[k]["file"], "kind": projects[k]["kind"],
                          "framework": projects[k]["framework"], "output": projects[k]["output"], "layer": level.get(k, 0),
                          "depends_on": sorted(label[t] for t in deps[k]), "used_by": sorted(label[t] for t in users[k]),
                          "packages": projects[k]["packages"]} for k in order],
            "cycles": [[label[k] for k in c] for c in cycles],
            "package_info": {n: {v: i for v, i in vs.items() if i} for n, vs in meta.items() if any(vs.values())}}
    open(os.path.join(agent, "dependencies.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(data, ensure_ascii=False, indent=1))
    stat("dependencies", projects=len(projects), packages=len(pkgs), project_references=sum(len(v) for v in deps.values()), version_drift=drift, cycles=len(cycles))
    print(f"dependencies: {len(projects)} projects, {sum(len(v) for v in deps.values())} project references, "
          f"{len(pkgs)} packages ({drift} with version drift), {len(cycles)} cycles"
          + (f"; local NuGet info for {sum(1 for vs in meta.values() if any(vs.values()))}/{len(meta)} .NET packages, {len(winonly)} Windows-only" if meta else ""))


if __name__ == "__main__":
    main()
