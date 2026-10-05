"""Discover and inventory every repository, solution and project in the client estate (deterministic).

    python <skill>/scripts/discover_estate.py [--repo NAME] [--force]

For each repository under the configured estate roots writes assessment/inventory/<repo>.json:
  solutions (.sln/.slnx), projects (SDK-style or legacy, target frameworks, output type, project type, packages,
  project references, assembly references, lines of code per language), Web Site projects (no project file),
  applications (deployable projects + their transitive references), shared libraries (referenced by more than one
  application: hybrid / .NET Standard 2.0 candidates), artefacts (configs, SQL, SSIS/SSRS/SSAS, scripts, CI, Docker),
  and git activity (commits, authors, hot files) for merge-risk planning.
Then writes assessment/inventory/estate.json (all repositories, totals). Re-runnable; skips repositories already
inventoried unless --force.
"""
import argparse
import datetime
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from _common import (OUT, SOURCE_DIR_SKIP, load_config, load_state, mark, mark_step, read_json, read_text, rel, run,
                     slug, utf8_stdout, write_json)
from _complexity import file_metrics, project_metrics

CODE_EXT = {".cs": "C#", ".vb": "VB.NET", ".fs": "F#"}
MARKUP_EXT = {".aspx", ".ascx", ".master", ".asax", ".ashx", ".asmx", ".svc", ".cshtml", ".vbhtml", ".razor", ".xaml"}
PROJ_EXT = {".csproj", ".vbproj", ".fsproj", ".sqlproj"}
GUIDS = {
    "349c5851-65df-11da-9384-00065b846f21": "web-application", "e3e379df-f4c6-4180-9b81-6769533abe47": "mvc4",
    "e53f8fea-eae0-44a6-8774-ffd645390401": "mvc3", "f85e285d-a4e0-4152-9332-ab1d724d3325": "mvc2",
    "3d9ad99f-2412-4246-b90b-4eaa41c64699": "wcf", "60dc8134-eba5-43b8-bcc9-bb4bc16c2548": "wpf",
    "3ac096d0-a1c2-e12c-1390-a8335801fdab": "test", "a1591282-1198-4647-a2b1-27e5ff5f6f3b": "silverlight",
    "786c830f-07a1-408b-bd7f-6ee04809d6db": "pcl", "e24c65dc-7377-472b-9aba-bc803b73c61a": "website",
}
TEST_PKGS = re.compile(r"(?i)^(MSTest\.TestFramework|NUnit|xunit|Microsoft\.NET\.Test\.Sdk|Microsoft\.VisualStudio\.QualityTools\.UnitTestFramework|SpecFlow|Reqnroll|NSubstitute|Moq)$")
TFM_SUPPORT = [  # (regex, label, end of support, status)
    (r"^v?(2\.0|3\.0|3\.5)$|^net(20|30|35)$", ".NET Framework 2.0-3.5", "3.5 SP1: 2029-01-09; earlier ended", "legacy"),
    (r"^v?(4\.0|4\.5|4\.5\.1|4\.5\.2|4\.6|4\.6\.1)$|^net(40|45|451|452|46|461)$", ".NET Framework 4.0-4.6.1", "ended (2016 / 2022-04-26)", "out-of-support"),
    (r"^v?4\.6\.2$|^net462$", ".NET Framework 4.6.2", "2027-01-12", "ending-soon"),
    (r"^v?4\.(7|7\.1|7\.2|8|8\.1)$|^net(47|471|472|48|481)$", ".NET Framework 4.7-4.8.1", "follows the Windows OS lifecycle", "supported-windows-only"),
    (r"^netcoreapp[123]\.\d$|^net5\.0|^net6\.0|^net7\.0", ".NET Core / .NET 5-7", "ended", "out-of-support"),
    (r"^net8\.0|^net9\.0", ".NET 8 / 9", "2026-11-10", "ending-soon"),
    (r"^net10\.0", ".NET 10 (LTS)", "2028-11-14", "supported"),
    (r"^net1[1-9]\.0", ".NET 11+", "check policy", "supported"),
    (r"^netstandard", ".NET Standard", "not a runtime (supported by consumers)", "supported"),
]


def tfm_info(tfm):
    t = (tfm or "").lower().split("-")[0]
    for rx, label, eos, status in TFM_SUPPORT:
        if re.search(rx, t):
            return {"tfm": tfm, "label": label, "end_of_support": eos, "status": status}
    return {"tfm": tfm, "label": tfm or "unknown", "end_of_support": "unknown", "status": "unknown"}


def family(tfms):
    fams = set()
    for t in tfms:
        t = t.lower()
        if t.startswith("netstandard"):
            fams.add("netstandard")
        elif re.match(r"^v?\d", t) or re.match(r"^net[1-4]\d*$", t):
            fams.add("netfx")
        elif t:
            fams.add("netcore")
    return "+".join(sorted(fams)) or "unknown"


def local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_project(path, repo_root):
    """Read a project file (legacy or SDK-style) without MSBuild."""
    p = {"path": rel(path, repo_root), "name": os.path.splitext(os.path.basename(path))[0], "ext": os.path.splitext(path)[1].lower()}
    try:
        root = ET.fromstring(read_text(path).encode("utf-8"))
    except ET.ParseError as ex:
        p["error"] = f"unparseable project file: {ex}"
        return p
    sdk = root.get("Sdk") or ""
    if not sdk:
        imp = [e.get("Project", "") for e in root.iter() if local(e.tag) == "Import" and e.get("Sdk")]
        sdk = root.find("./Sdk").get("Name") if root.find("./Sdk") is not None else (imp[0] if imp else "")
    p["sdk_style"] = bool(sdk) or any(local(e.tag) == "Sdk" for e in root)
    p["sdk"] = sdk
    props = defaultdict(list)
    for e in root.iter():
        t = local(e.tag)
        if t in ("TargetFramework", "TargetFrameworks", "TargetFrameworkVersion", "OutputType", "ProjectTypeGuids", "AssemblyName",
                 "RootNamespace", "UseWPF", "UseWindowsForms", "UseWinUI", "OutputPath", "TargetFrameworkProfile", "Nullable", "LangVersion",
                 "IsPackable", "AspNetCoreHostingModel", "RuntimeIdentifier", "RuntimeIdentifiers", "SelfContained", "PublishProfile"):
            if e.text and e.text.strip():
                props[t].append(e.text.strip())
    tfms = []
    for v in props.get("TargetFramework", []) + props.get("TargetFrameworks", []):
        tfms += [x.strip() for x in v.split(";") if x.strip() and "$(" not in x]
    if not tfms and props.get("TargetFrameworkVersion"):
        tfms = [props["TargetFrameworkVersion"][0]]
    p["target_frameworks"] = sorted(set(tfms))
    p["framework_family"] = family(p["target_frameworks"])
    p["output_type"] = (props.get("OutputType") or ["Library"])[0]
    p["assembly_name"] = (props.get("AssemblyName") or [p["name"]])[0]
    guids = ";".join(props.get("ProjectTypeGuids", [])).lower()
    p["type_guids"] = sorted({GUIDS.get(g.strip("{} "), g.strip("{} ")) for g in guids.split(";") if g.strip()})
    p["use_wpf"] = any(v.lower() == "true" for v in props.get("UseWPF", []))
    p["use_winforms"] = any(v.lower() == "true" for v in props.get("UseWindowsForms", []))
    p["references"], p["packages"], p["project_references"], p["com_references"] = [], [], [], []
    for e in root.iter():
        t = local(e.tag)
        inc = e.get("Include") or ""
        if t == "Reference" and inc:
            p["references"].append(inc.split(",")[0].strip())
        elif t == "PackageReference" and inc:
            ver = e.get("Version") or next((c.text for c in e if local(c.tag) == "Version" and c.text), "") or ""
            p["packages"].append({"id": inc, "version": ver.strip(), "source": "PackageReference", "file": p["path"]})
        elif t == "ProjectReference" and inc:
            target = os.path.normpath(os.path.join(os.path.dirname(path), inc.replace("\\", os.sep)))
            p["project_references"].append(rel(target, repo_root))
        elif t == "COMReference" and inc:
            p["com_references"].append(inc)
    pc = os.path.join(os.path.dirname(path), "packages.config")
    p["packages_config"] = os.path.exists(pc)
    if p["packages_config"]:
        try:
            for e in ET.fromstring(read_text(pc).encode("utf-8")).iter():
                if local(e.tag) == "package" and e.get("id"):
                    p["packages"].append({"id": e.get("id"), "version": e.get("version", ""), "source": "packages.config",
                                          "file": rel(pc, repo_root), "targetFramework": e.get("targetFramework", "")})
        except ET.ParseError:
            p["packages_config_error"] = True
    p["tfm_support"] = [tfm_info(t) for t in p["target_frameworks"]]
    return p


def walk_files(root, skip):
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x.lower() not in skip and not x.startswith("."))
        for f in files:
            yield os.path.join(d, f)


GENERATED_NAME = re.compile(r"(?i)(\.designer\.(cs|vb)|\.g\.(i\.)?cs|^Reference\.(cs|vb)|^AssemblyInfo\.(cs|vb)|\.AssemblyAttributes\.cs|^TemporaryGeneratedFile)")
GENERATED_HEAD = re.compile(r"<auto-generated|This code was generated by a tool|generated from a template", re.I)


def count_lines(path):
    try:
        return sum(1 for line in read_text(path).splitlines() if line.strip())
    except OSError:
        return 0


def classify(p, files_by_ext, code_hits):
    """Project type from SDK, GUIDs, references, packages and files."""
    if p["ext"] == ".sqlproj":
        return "database"
    refs = {r.lower() for r in p.get("references", [])}
    pk = {x["id"].lower() for x in p.get("packages", [])}
    guids = set(p.get("type_guids", []))
    if "test" in guids or any(TEST_PKGS.match(x["id"]) for x in p.get("packages", [])) or "microsoft.visualstudio.qualitytools.unittestframework" in refs:
        return "test"
    fam = p.get("framework_family", "")
    sdk = (p.get("sdk") or "").lower()
    if sdk.endswith("sdk.web") or sdk.endswith("sdk.razor") or sdk.endswith("sdk.blazorwebassembly"):
        return "aspnet-core"  # also ASP.NET Core 2.x on .NET Framework (a half-way port)
    if sdk.endswith("sdk.worker"):
        return "netcore-other"
    if "netcore" in fam and "netfx" not in fam:
        if p.get("use_wpf"):
            return "wpf"
        if p.get("use_winforms"):
            return "winforms"
        if sdk.endswith(".web") or sdk.endswith("web"):
            return "aspnet-core"
        return "netcore-other"
    if fam == "netstandard":
        return "class-library"
    aspx = files_by_ext.get(".aspx", 0) + files_by_ext.get(".master", 0)
    razor = files_by_ext.get(".cshtml", 0) + files_by_ext.get(".vbhtml", 0)
    mvc = "system.web.mvc" in refs or "microsoft.aspnet.mvc" in pk
    webapi = "system.web.http" in refs or "microsoft.aspnet.webapi.core" in pk or "microsoft.aspnet.webapi" in pk
    if aspx and not mvc:
        return "aspnet-webforms"
    if mvc:
        return "aspnet-webforms" if aspx > razor else "aspnet-mvc"  # an MVC app with a few .aspx pages stays MVC (findings list the pages)
    if webapi:
        return "aspnet-webapi"
    if files_by_ext.get(".svc") or "wcf" in guids:
        return "wcf-service"
    if "web-application" in guids or files_by_ext.get(".asmx") or files_by_ext.get(".ashx"):
        return "aspnet-webapi"
    if "wpf" in guids or "presentationframework" in refs or p.get("use_wpf"):
        return "wpf"
    if code_hits.get("servicebase") and p.get("output_type", "").lower() in ("exe", "winexe"):
        return "windows-service"
    if "system.windows.forms" in refs and p.get("output_type", "").lower() in ("winexe", "exe"):
        return "winforms"
    if p.get("output_type", "").lower() in ("exe", "winexe"):
        return "console"
    return "class-library"


DEPLOYABLE = {"aspnet-mvc", "aspnet-webapi", "aspnet-webforms", "wcf-service", "windows-service", "console", "winforms", "wpf",
              "aspnet-core", "website", "database"}


def parse_solutions(repo_root, skip):
    sols = []
    for f in walk_files(repo_root, skip):
        low = f.lower()
        if low.endswith(".sln"):
            projs = re.findall(r'Project\("\{([^}]+)\}"\)\s*=\s*"([^"]+)",\s*"([^"]+)"', read_text(f))
            entries = [{"name": n, "path": rel(os.path.normpath(os.path.join(os.path.dirname(f), pth.replace("\\", os.sep))), repo_root)}
                       for g, n, pth in projs if os.path.splitext(pth)[1].lower() in PROJ_EXT or g.upper() == "E24C65DC-7377-472B-9ABA-BC803B73C61A"]
            sols.append({"path": rel(f, repo_root), "projects": entries})
        elif low.endswith(".slnx"):
            try:
                root = ET.fromstring(read_text(f).encode("utf-8"))
                entries = [{"name": os.path.splitext(os.path.basename(e.get("Path", "")))[0],
                            "path": rel(os.path.normpath(os.path.join(os.path.dirname(f), e.get("Path", "").replace("\\", os.sep))), repo_root)}
                           for e in root.iter() if local(e.tag) == "Project" and e.get("Path")]
                sols.append({"path": rel(f, repo_root), "projects": entries})
            except ET.ParseError:
                sols.append({"path": rel(f, repo_root), "projects": [], "error": "unparseable"})
    return sols


def git_activity(repo_root, days):
    if not os.path.exists(os.path.join(repo_root, ".git")):
        return {"git": False}
    since = f"--since={days}.days"
    code, out = run(["git", "-C", repo_root, "log", since, "--format=@@%H|%ae|%ad", "--date=short", "--name-only", "--no-merges"], timeout=300)
    if code:
        return {"git": True, "error": out[-300:]}
    commits, authors, files, dates = 0, set(), Counter(), []
    for block in out.split("@@")[1:]:
        lines = [x for x in block.splitlines() if x.strip()]
        if not lines:
            continue
        h, author, date = (lines[0].split("|") + ["", ""])[:3]
        commits += 1
        authors.add(author)
        dates.append(date)
        files.update(lines[1:])
    _, branch = run(["git", "-C", repo_root, "rev-parse", "--abbrev-ref", "HEAD"])
    _, shallow = run(["git", "-C", repo_root, "rev-parse", "--is-shallow-repository"])
    _, last = run(["git", "-C", repo_root, "log", "-1", "--format=%ad", "--date=short"])
    _, branches = run(["git", "-C", repo_root, "branch", "-a", "--format=%(refname:short)"])
    weeks = max(days / 7.0, 1)
    return {"git": True, "window_days": days, "commits": commits, "commits_per_week": round(commits / weeks, 2),
            "authors": len(authors), "hot_files": files.most_common(15), "branch": branch.strip(),
            "branches": len([b for b in branches.splitlines() if b.strip()]), "last_commit": last.strip(),
            "shallow": shallow.strip() == "true", "first_in_window": min(dates) if dates else None}


ARTEFACTS = {
    "config": re.compile(r"(?i)^(web|app)(\.[\w-]+)?\.config$|^appsettings(\.[\w-]+)?\.json$|^[\w.-]+\.exe\.config$"),
    "sql": re.compile(r"(?i)\.sql$"), "ssis": re.compile(r"(?i)\.(dtsx|ispac|dtproj)$"), "ssrs": re.compile(r"(?i)\.(rdl|rds|rsd|rptproj)$"),
    "ssas": re.compile(r"(?i)\.(bim|cube|dwproj|asdatabase)$"), "crystal": re.compile(r"(?i)\.rpt$"), "rdlc": re.compile(r"(?i)\.rdlc$"),
    "script": re.compile(r"(?i)\.(ps1|psm1|bat|cmd|vbs)$"), "docker": re.compile(r"(?i)^(dockerfile(\.[\w-]+)?|docker-compose[\w.-]*\.ya?ml)$"),
    "ci": re.compile(r"(?i)^(azure-pipelines[\w.-]*\.ya?ml|jenkinsfile|\.gitlab-ci\.yml|buildspec[\w.-]*\.ya?ml|appveyor\.yml|bitbucket-pipelines\.yml|\.travis\.yml)$"),
    "nuget_config": re.compile(r"(?i)^nuget\.config$"), "publish_profile": re.compile(r"(?i)\.pubxml$"), "edmx": re.compile(r"(?i)\.edmx$"),
    "js_lib": re.compile(r"(?i)\.js$"), "package_json": re.compile(r"(?i)^(package|bower)\.json$"),
}


def inventory_repo(name, repo_root, cfg):
    skip = SOURCE_DIR_SKIP | {s.lower() for s in cfg.get("exclude_dirs", [])}
    proj_files, all_files = [], []
    for f in walk_files(repo_root, skip):
        all_files.append(f)
        if os.path.splitext(f)[1].lower() in PROJ_EXT:
            proj_files.append(f)
    projects = [parse_project(f, repo_root) for f in sorted(proj_files)]
    pdirs = sorted(((os.path.normpath(os.path.dirname(os.path.join(repo_root, p["path"]))), p) for p in projects), key=lambda x: -len(x[0]))

    def owner(path):
        path = os.path.normpath(path)
        for d, p in pdirs:
            if path.startswith(d + os.sep):
                return p
        return None

    per_proj = defaultdict(lambda: {"ext": Counter(), "loc": Counter(), "files": 0, "servicebase": False})
    artefacts = defaultdict(list)
    loose = defaultdict(lambda: {"ext": Counter(), "loc": Counter(), "files": 0})
    for f in all_files:
        ext = os.path.splitext(f)[1].lower()
        base = os.path.basename(f)
        for kind, rx in ARTEFACTS.items():
            if rx.search(base) and not (kind == "js_lib" and not re.search(r"(?i)[\\/](scripts|js|lib|content)[\\/]", f)):
                artefacts[kind].append(rel(f, repo_root))
        o = owner(f)
        bucket = per_proj[o["path"]] if o else loose[rel(os.path.dirname(f), repo_root).split("/")[0]]
        if ext in CODE_EXT or ext in MARKUP_EXT or ext in (".js", ".ts", ".sql", ".config", ".css"):
            bucket["ext"][ext] += 1
            bucket["files"] += 1
            if os.path.getsize(f) < 3_000_000 and not base.endswith(".min.js"):
                n = count_lines(f)
                lang = CODE_EXT.get(ext) or ("markup" if ext in MARKUP_EXT else ext.lstrip("."))
                if ext in CODE_EXT and (GENERATED_NAME.search(base) or GENERATED_HEAD.search(read_text(f)[:1500])):
                    lang = "generated"  # designer / T4 / service-reference code: regenerated, not ported by hand
                bucket["loc"][lang] += n
                if ext in (".cs", ".vb") and lang != "generated" and o is not None:
                    bucket.setdefault("cx_files", []).append(file_metrics(read_text(f), vb=(ext == ".vb")))
                if ext in (".cs", ".vb") and o is not None and not per_proj[o["path"]]["servicebase"] and n:
                    if re.search(r"(:\s*ServiceBase\b|Inherits\s+(System\.ServiceProcess\.)?ServiceBase\b)", read_text(f)):
                        per_proj[o["path"]]["servicebase"] = True
    for p in projects:
        b = per_proj[p["path"]]
        p["files_by_ext"] = dict(b["ext"])
        p["loc"] = dict(b["loc"])
        p["loc_code"] = sum(v for k, v in b["loc"].items() if k in ("C#", "VB.NET", "F#", "markup"))
        p["loc_handwritten"] = sum(v for k, v in b["loc"].items() if k in ("C#", "VB.NET", "F#"))
        p["loc_markup"] = b["loc"].get("markup", 0)
        p["loc_generated"] = b["loc"].get("generated", 0)
        p["complexity"] = project_metrics(b.get("cx_files", []))
        p["languages"] = sorted(k for k in b["loc"] if k in ("C#", "VB.NET", "F#"))
        p["type"] = classify(p, b["ext"], {"servicebase": b["servicebase"]})
        p["deployable"] = p["type"] in DEPLOYABLE
    # Web Site projects: folders with web.config + pages but no project file owning them
    websites = []
    for f in all_files:
        if os.path.basename(f).lower() == "web.config" and owner(f) is None:
            d = os.path.dirname(f)
            pages = [x for x in os.listdir(d) if os.path.splitext(x)[1].lower() in (".aspx", ".asmx", ".svc", ".cshtml")]
            if pages or os.path.isdir(os.path.join(d, "App_Code")):
                websites.append({"path": rel(d, repo_root), "name": os.path.basename(d), "type": "website", "deployable": True,
                                 "pages": len(pages), "app_code": os.path.isdir(os.path.join(d, "App_Code"))})
    by_path = {p["path"]: p for p in projects}
    for p in projects:  # reverse references
        p["referenced_by"] = sorted(q["path"] for q in projects if p["path"] in q.get("project_references", []))

    def closure(path, seen=None):
        seen = seen if seen is not None else set()
        for r in by_path.get(path, {}).get("project_references", []):
            if r not in seen:
                seen.add(r)
                closure(r, seen)
        return seen

    apps = []
    for p in projects:
        if p["deployable"] and p["type"] != "database":
            deps = sorted(closure(p["path"]))
            loc = p["loc_code"] + sum(by_path[d]["loc_code"] for d in deps if d in by_path)
            apps.append({"id": slug(f"{name}-{os.path.splitext(p['path'])[0]}"), "name": p["name"], "entry": p["path"], "type": p["type"],
                         "framework_family": p["framework_family"], "target_frameworks": p["target_frameworks"], "projects": [p["path"]] + deps, "loc": loc})
    for w in websites:
        apps.append({"id": slug(f"{name}-{w['path']}-site"), "name": w["name"], "entry": w["path"], "type": "website",
                     "framework_family": "netfx", "target_frameworks": [], "projects": [], "loc": 0})
    usage = Counter(d for a in apps for d in a["projects"][1:])
    shared = [{"path": d, "name": by_path[d]["name"], "used_by": sorted(a["name"] for a in apps if d in a["projects"][1:]),
               "framework_family": by_path[d]["framework_family"], "target_frameworks": by_path[d]["target_frameworks"]}
              for d, n in usage.items() if n > 1 and d in by_path]
    sols = parse_solutions(repo_root, skip)
    in_sln = {e["path"] for s in sols for e in s["projects"]}
    totals = {"projects": len(projects), "solutions": len(sols), "applications": len(apps), "loc": sum(p["loc_code"] for p in projects),
              "loc_by_language": dict(sum((Counter(p["loc"]) for p in projects), Counter())),
              "types": dict(Counter(p["type"] for p in projects)), "families": dict(Counter(p["framework_family"] for p in projects)),
              "legacy_project_files": sum(1 for p in projects if not p.get("sdk_style") and p["ext"] != ".sqlproj"),
              "packages_config": sum(1 for p in projects if p.get("packages_config")), "files": len(all_files)}
    return {"repo": name, "root": repo_root, "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "solutions": sols, "projects": projects, "projects_not_in_solution": sorted(set(by_path) - in_sln),
            "websites": websites, "applications": apps, "shared_libraries": shared,
            "artefacts": {k: sorted(v) for k, v in artefacts.items()}, "loose_files": {k: dict(v["loc"]) for k, v in loose.items() if v["files"]},
            "git": git_activity(repo_root, int(cfg.get("git_activity_days", 180))), "totals": totals}


def find_repos(roots, cfg):
    """A repository = a folder with .git; when a root has no .git below it, the root itself is one repository."""
    repos = {}
    skip = SOURCE_DIR_SKIP | {s.lower() for s in cfg.get("exclude_dirs", [])}
    for r in roots:
        r = os.path.abspath(r)
        if not os.path.isdir(r):
            print(f"WARN estate root not found: {r}")
            continue
        found = []
        for d, dirs, files in os.walk(r):
            if ".git" in dirs or ".git" in files:
                found.append(d)
                dirs[:] = []
                continue
            dirs[:] = [x for x in dirs if x.lower() not in skip and not x.startswith(".")]
        if not found:
            found = [r]
        for d in found:
            name = slug(os.path.basename(d))
            while name in repos and repos[name] != d:
                name += "-2"
            repos[name] = d
    return {k: v for k, v in repos.items() if k not in set(cfg.get("skip_repos", []))}


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="only this repository (name as listed in estate.json)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    if not cfg["estate_roots"]:
        sys.exit("estate_roots is empty in assessment.json")
    repos = find_repos(cfg["estate_roots"], cfg)
    st = load_state(root)
    done = 0
    for name, path in sorted(repos.items()):
        if a.repo and name != a.repo:
            continue
        out = os.path.join(OUT, "inventory", f"{name}.json")
        if os.path.exists(out) and not a.force and st["repos"].get(name, {}).get("discover") == "done":
            continue
        inv = inventory_repo(name, path, cfg)
        write_json(out, inv)
        mark(root, name, "discover", root_path=path)
        t = inv["totals"]
        print(f"{name}: {t['solutions']} solutions, {t['projects']} projects, {t['applications']} applications, {t['loc']:,} lines; types {t['types']}")
        done += 1
    estate = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "roots": cfg["estate_roots"], "repos": []}
    for name, path in sorted(repos.items()):
        inv = read_json(os.path.join(OUT, "inventory", f"{name}.json"))
        if inv:
            estate["repos"].append({"repo": name, "root": path, **inv["totals"], "git": {k: inv["git"].get(k) for k in ("commits", "commits_per_week", "authors", "last_commit", "branch", "shallow")}})
    estate["totals"] = {k: sum(r.get(k, 0) for r in estate["repos"]) for k in ("projects", "solutions", "applications", "loc", "files")}
    write_json(os.path.join(OUT, "inventory", "estate.json"), estate)
    mark_step(root, "discover")
    print(f"estate: {len(estate['repos'])} repositories, {estate['totals']['applications']} applications, {estate['totals']['loc']:,} lines "
          f"({done} inventoried now) -> {OUT}/inventory/")


if __name__ == "__main__":
    main()
