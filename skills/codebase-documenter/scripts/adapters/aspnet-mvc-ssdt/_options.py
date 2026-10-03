"""Options for the ASP.NET MVC + SQL Server (SSDT) adapter, read from codebase-docs.json.

Every option is auto-detected from the source tree when it is not set, so the adapter works on any
ASP.NET MVC (+ SSDT) solution without configuration. Set an option only to override detection:

  "adapter_options": {"aspnet-mvc-ssdt": {
     "web_project": "MyApp",                                  # main MVC project folder (relative to source root)
     "databases": [                                           # SSDT projects -> reference pages
        {"name": "Main", "path": "MyDb/MyDb", "tables_page": "db-tables.md", "routines_page": "db-routines.md"},
        {"name": "Reporting", "path": "ReportDb/ReportDb", "tables_page": "reportdb-tables.md", "routines_page": "reportdb-routines.md"}],
     "edmx": "MyApp/Models/Model.edmx",                       # EF function-import alias map (optional)
     "seeds_dir": "MyDb/MyDb/Scripts/PostDeployment/DataSeeds",
     "inventory_projects": ["MyApp", "MyApi"],                # projects scanned for views / components / models
     "scripts_dir": "MyApp/Scripts", "bundle_config": "MyApp/App_Start/BundleConfig.cs",
     "custom_js": ["app.js", "site.js"],                      # hand-written scripts (default: every non-vendor script)
     "ssrs_dir": "Reports"}}                                  # folder with .rdl files (optional)

Detection: web project = the project folder with Controllers/ and Web.config (or Global.asax); databases = every
*.sqlproj folder; edmx = first *.edmx in the web project; seeds = a DataSeeds / PostDeployment folder in the first
database; inventory = every top-level folder holding a *.csproj (test / spec projects skipped); SSRS = the folder holding the most *.rdl files.
"""
import fnmatch
import json
import os
import re

CFG = json.load(open("codebase-docs.json", encoding="utf-8")) if os.path.exists("codebase-docs.json") else {}
OPT = CFG.get("adapter_options", {}).get("aspnet-mvc-ssdt", {})
ROOT = os.environ.get("DOCS_SOURCE_ROOT") or CFG.get("source_root") or "."
DOCS = CFG.get("docs_dir", "docs")
PRODUCT = CFG.get("code_name") or CFG.get("product") or "the application"
SKIP = {"bin", "obj", "packages", "node_modules", ".git", ".vs", "TestResults"}
VENDOR_JS = re.compile(r"^(jquery|bootstrap|modernizr|respond|MicrosoftAjax|MicrosoftMvc|json2|datetimepicker|dataTables\.|"
                       r"_references|knockout|moment|select2|chosen|signalr|popper|angular|react|vue|lodash|underscore)", re.I)


def _rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def _find(pattern):
    """Files matching a glob pattern anywhere under ROOT (build / package folders skipped), sorted."""
    out = []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(x for x in dirs if x not in SKIP)
        out += [os.path.join(d, f) for f in fnmatch.filter(files, pattern)]
    return sorted(out)


def _web_project():
    for proj in _find("*.csproj"):
        d = os.path.dirname(proj)
        if os.path.isdir(os.path.join(d, "Controllers")) and (os.path.exists(os.path.join(d, "Web.config")) or os.path.exists(os.path.join(d, "Global.asax"))):
            return _rel(d)
    return CFG.get("code_name") or "."


def _databases():
    dbs = []
    for i, proj in enumerate(_find("*.sqlproj")):
        name = os.path.splitext(os.path.basename(proj))[0]
        prefix = "db" if i == 0 else re.sub(r"[^a-z0-9]+", "", name.lower()) or f"db{i + 1}"
        dbs.append({"name": name, "path": _rel(os.path.dirname(proj)), "tables_page": f"{prefix}-tables.md", "routines_page": f"{prefix}-routines.md"})
    return dbs


def _seeds_dir():
    if not DATABASES:
        return None
    base = os.path.join(ROOT, DATABASES[0]["path"])
    for name in ("DataSeeds", "Seeds", "SeedData", "PostDeployment"):
        hits = [d for d, _, _ in os.walk(base) if os.path.basename(d).lower() == name.lower()]
        if hits:
            return _rel(sorted(hits, key=len)[0])
    return None


def _ssrs_dir():
    rdl = _find("*.rdl")
    return _rel(os.path.commonpath([os.path.dirname(p) for p in rdl])) if rdl else None


WEB_PROJECT = OPT.get("web_project") or _web_project()
DATABASES = OPT.get("databases") or _databases()
EDMX = OPT.get("edmx") or next((_rel(p) for p in _find("*.edmx") if _rel(p).startswith(WEB_PROJECT.rstrip("/") + "/") or WEB_PROJECT == "."), "")
SEEDS_DIR = OPT.get("seeds_dir") or _seeds_dir()
INVENTORY_PROJECTS = tuple(OPT.get("inventory_projects") or sorted({_rel(os.path.dirname(p)).split("/")[0] for p in _find("*.csproj")
                                                                    if not re.search(r"(?i)tests?$|specs?$|test_|_test", _rel(os.path.dirname(p)).split("/")[0])}))
SCRIPTS_DIR = OPT.get("scripts_dir", f"{WEB_PROJECT}/Scripts")
BUNDLE_CONFIG = OPT.get("bundle_config", f"{WEB_PROJECT}/App_Start/BundleConfig.cs")
CUSTOM_JS = tuple(OPT.get("custom_js") or ())
SSRS_DIR = OPT.get("ssrs_dir") or _ssrs_dir()


def is_custom_js(path):
    """True for a hand-written script: listed in custom_js, or (no list given) not a vendor library / minified file."""
    if CUSTOM_JS:
        return any(k in path for k in CUSTOM_JS)
    f = os.path.basename(path)
    return not f.endswith(".min.js") and not VENDOR_JS.match(f)
