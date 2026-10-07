"""Third-party front-end libraries copied into a repository (jQuery, Bootstrap, Modernizr, WebForms scripts, chart kits ...).

They are not the project's code: counting them inflates code volume, and graphing them buries the real communities and hubs
under thousands of library functions. Shared by survey_codebase.py, code_graph.py (graphify --exclude), network_endpoints.py
and the migration-assessment map_graphs.py. Standard library only.

Four sources, all additive:
  - configured folders: "graph": {"vendor_dirs": ["Scripts/highmapsv10.1", "Content/kendo"]} in codebase-docs.json
    (paths relative to the source root; a whole folder, recursively, or one file);
  - this skill's own output inside the source tree: the workspace (`.codebase-docs`) and an installed docs kit (docs_kit_dirs);
  - detected library folders: a folder whose name carries a version (highmapsv10.1, jquery-ui-1.12.1, summernote-0.8)
    holding at least one file with a library banner: everything under it is vendored, banner or not;
  - single files: vendor folders (wwwroot/lib, bower_components ...), files named after a declared client package,
    IntelliSense copies, and files whose first lines carry a library banner.

    python <skill>/scripts/vendor_files.py <source root>      # list the vendored folders and files found
"""
import json
import os
import re
import sys

SKIP = {".git", "node_modules", "bin", "obj", "packages", ".vs", "dist", "build", "target", "__pycache__", ".venv", "venv",
        ".idea", "graphify-out", "site", "publish", ".next", ".nuxt", "vendor", "coverage"}
VENDOR_DIR = re.compile(r"(?i)(^|/)(wwwroot/lib|bower_components|jspm_packages|third[-_]?party|externals?)(/|$)")
ASSET_EXT = (".js", ".css", ".scss", ".less")
ASSET_PARENTS = ("scripts", "content", "wwwroot", "lib", "js", "css")
BANNER = re.compile(r"(?i)\bv?\d+\.\d+\.\d+\b.{0,80}\b(license|\(c\)|copyright)", re.S)
# an open-source licence header: a copyright line plus a licence grant (a company's own "All rights reserved" header has no grant)
COPYRIGHT = re.compile(r"(?i)copyright|\(c\)\s*\d{4}")
GRANT = re.compile(r"(?i)licen[cs]ed under|released under|\bMIT\b|\bGPL\b|apache licen[cs]e|\bBSD\b|mit-license|opensource\.org")
STEM_CUT = re.compile(r"[-.](?:\d|min\b|slim\b|bundle\b)")
VERSIONED_DIR = re.compile(r"(?i)(?:^|[-_.v])v?\d+(?:\.\d+)+(?:[-_.]?\w+)?$|[a-z]v\d+(?:\.\d+)*$")
# well-known libraries often copied in without a version or a licence banner (file stem, exact match after STEM_CUT)
KNOWN_LIBS = {
    "moment", "moment-with-locales", "moment-timezone", "moment-timezone-with-data", "modernizr", "respond", "knockout",
    "knockout.mapping", "pdfmake", "vfs_fonts", "jszip", "parsley", "switchery", "footable", "bootbox", "metismenu",
    "sb-admin", "jquery", "jquery-ui", "jquery.validate", "jquery.validate.unobtrusive", "jquery.unobtrusive-ajax",
    "bootstrap", "bootstrap-datepicker", "bootstrap-select", "popper", "lodash", "underscore", "handlebars", "mustache",
    "select2", "toastr", "sweetalert", "sweetalert2", "numeral", "summernote", "dropzone", "fullcalendar", "html2canvas",
    "jspdf", "raphael", "nprogress", "datatables", "jquery.datatables", "jquery.signalr", "highcharts", "highstock",
    "chartjs-plugin-datalabels", "clipboard", "spin", "ladda", "pace", "jquery.slimscroll", "jquery.sparkline"}
MAX_ARG_CHARS = 24000  # Windows caps a command line at 32,767 characters; leave room for the rest of the graphify call


def configured_dirs(cfg_path="codebase-docs.json"):
    """graph.vendor_dirs from the workspace config (relative to the source root, forward slashes, no leading / trailing /)."""
    try:
        cfg = json.load(open(cfg_path, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [d.replace("\\", "/").strip("/") for d in (cfg.get("graph") or {}).get("vendor_dirs") or [] if str(d).strip("/\\")]


def client_packages(src, skip=SKIP):
    """Package ids that deliver script / style files into the repository (NuGet content packages, libman, bower, npm)."""
    ids = set()
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in skip and not x.startswith(".")]
        for f in files:
            low = f.lower()
            if low not in ("packages.config", "libman.json", "bower.json", "package.json"):
                continue
            try:
                t = open(os.path.join(d, f), encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            if low == "packages.config":
                found = re.findall(r'<package\s+id="([^"]+)"', t)
            else:
                found = re.findall(r'"library"\s*:\s*"([^"@]+)', t) + re.findall(r'"([@\w./-]+)"\s*:\s*"[\^~>=<]*\d', t)
            ids.update(i.lower().split("/")[-1].removesuffix(".js") for i in found if len(i) >= 4)
    return ids


def has_banner(path):
    try:
        head = open(path, encoding="utf-8", errors="ignore").read(600)
    except OSError:
        return False
    return ("/*!" in head or "@license" in head or "NUGET: BEGIN LICENSE TEXT" in head
            or head.lstrip("﻿").startswith("//CdnPath=") or bool(BANNER.search(head))
            or bool(COPYRIGHT.search(head) and GRANT.search(head)))


def under(rel, dirs):
    low = rel.lower()
    return any(low == d.lower() or low.startswith(d.lower() + "/") for d in dirs)


def is_vendored(path, rel, pkgs, dirs=()):
    """A configured or detected library folder (dirs); a vendor folder; a file named after a declared client-side package
    (jquery-3.4.1.js from the jQuery NuGet package); a folder named after one (Scripts/WebForms from
    Microsoft.AspNet.ScriptManager.WebForms); a Visual Studio IntelliSense copy; or a .js / .css file whose first lines carry
    a library banner (/*! name vX | licence */, @license, NuGet's licence block, //CdnPath=)."""
    rel = rel.replace("\\", "/")
    if VENDOR_DIR.search(rel) or (dirs and under(rel, dirs)):
        return True
    low = rel.lower().rsplit("/", 1)[-1]
    if not low.endswith(ASSET_EXT):
        return False
    if low.endswith((".intellisense.js", "-vsdoc.js")):
        return True
    stem = STEM_CUT.split(low.rsplit(".", 1)[0])[0]
    if stem in KNOWN_LIBS:
        return True
    if len(stem) >= 4 and any(stem == pk or stem.startswith(pk + ".") or pk.startswith(stem + ".") for pk in pkgs):
        return True
    parts = rel.lower().split("/")
    if len(parts) >= 3 and parts[-3] in ASSET_PARENTS and any(len(pk.split(".")[-1]) >= 5 and parts[-2] == pk.split(".")[-1] for pk in pkgs):
        return True
    return has_banner(path)


def library_dirs(src, skip=SKIP, pkgs=()):
    """Folders that hold a copied library: (1) the name carries a version and some file below has a library banner; or
    (2) a folder directly inside a script / style folder (Scripts/jqplot, Content/summernote) where at least half of the
    script / style files below (and at least 3) are vendored on their own: the banner-less plugins beside them are too."""
    found = []
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in skip and not x.startswith(".")]
        rel = os.path.relpath(d, src).replace("\\", "/")
        if rel == "." or under(rel, found):
            continue
        parts = rel.lower().split("/")
        versioned = bool(VERSIONED_DIR.search(parts[-1]))
        in_assets = len(parts) >= 2 and parts[-2] in ASSET_PARENTS
        if not (versioned or in_assets):
            continue
        assets = vend = 0
        for d2, dirs2, files2 in os.walk(d):
            dirs2[:] = [x for x in dirs2 if x not in skip and not x.startswith(".")]
            for f in files2:
                if not f.lower().endswith(ASSET_EXT):
                    continue
                assets += 1
                p = os.path.join(d2, f)
                if is_vendored(p, os.path.relpath(p, src).replace("\\", "/"), pkgs):
                    vend += 1
                    if versioned:
                        break
            if versioned and vend:
                break
        if (versioned and vend) or (in_assets and vend >= 3 and vend * 2 >= assets):
            found.append(rel)
    return found


KIT_MARKERS = ("agent/entities.jsonl", "_tools/lookup.py")


def docs_kit_dirs(src, skip=SKIP):
    """Folders under src that hold this skill's own output, never the project's code: the documentation workspace when it sits
    inside the source tree (`<repo>/.codebase-docs` with source_root ".."), any other folder holding a codebase-docs.json, and
    an installed docs kit (a folder with agent/entities.jsonl and _tools/lookup.py, e.g. `<repo>/docs` after a mode A install).
    Their scripts (lookup.py, build_docs.py ...) and site assets would otherwise be graphed and documented as the project's."""
    src_abs, out = os.path.abspath(src), []
    if os.path.exists("codebase-docs.json"):  # the current workspace
        r = os.path.relpath(os.path.abspath("."), src_abs).replace("\\", "/")
        if r != "." and not r.startswith(".."):
            out.append(r)
    for d, dirs, files in os.walk(src):
        rel = os.path.relpath(d, src).replace("\\", "/")
        if rel != "." and (under(rel, out) or "codebase-docs.json" in files
                           or all(os.path.exists(os.path.join(d, m)) for m in KIT_MARKERS)):
            if not under(rel, out):
                out.append(rel)
            dirs[:] = []
            continue
        # dot folders are not walked, but a workspace such as .codebase-docs is still recognised
        for x in dirs:
            if x.startswith(".") and x not in skip and os.path.exists(os.path.join(d, x, "codebase-docs.json")):
                r = f"{rel}/{x}" if rel != "." else x
                if not under(r, out):
                    out.append(r)
        dirs[:] = [x for x in dirs if x not in skip and not x.startswith(".")]
    return out


def excluded_dirs(src, skip=SKIP):
    """graph.vendor_dirs plus the skill's own output folders (docs_kit_dirs): whole folders that are never the project's code."""
    conf = configured_dirs()
    return conf + [k for k in docs_kit_dirs(src, skip) if not under(k, conf)]


def context(src, skip=SKIP):
    """(declared client packages, configured + docs-kit + detected library folders) for is_vendored()."""
    conf = excluded_dirs(src, skip)
    pkgs = client_packages(src, skip)
    return pkgs, conf + [d for d in library_dirs(src, skip, pkgs) if not under(d, conf)]


def scan(src, skip=SKIP, ctx=None):
    """Relative paths (forward slashes) of every vendored file under src."""
    pkgs, dirs = ctx or context(src, skip)
    out = []
    for d, dirs_, files in os.walk(src):
        dirs_[:] = [x for x in dirs_ if x not in skip and not x.startswith(".")]
        for f in files:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, src).replace("\\", "/")
            if is_vendored(p, rel, pkgs, dirs):
                out.append(rel)
    return sorted(out)


def graphify_excludes(src, skip=SKIP, max_chars=MAX_ARG_CHARS, report=None):
    """gitignore-style patterns (anchored at src) for graphify extract --exclude, in this order: configured folders
    (/dir/), then the highest folders whose script / style files are all vendored (/dir/**/*.js ...), then single files,
    largest first. Never truncates silently: when the patterns would not fit on one command line, the rest is dropped
    with a WARNING (and listed in `report`, a dict, when given) so the user can add those folders to graph.vendor_dirs."""
    pkgs, dirs = context(src, skip)
    conf = excluded_dirs(src, skip)
    files = scan(src, skip, (pkgs, dirs))
    if not files and not conf:
        return []
    vend = set(files)
    total, vcount, exts = {}, {}, {}
    for d, dirs_, fs in os.walk(src):
        dirs_[:] = [x for x in dirs_ if x not in skip and not x.startswith(".")]
        rel = os.path.relpath(d, src).replace("\\", "/")
        rel = "" if rel == "." else rel
        for f in fs:
            if not f.lower().endswith(ASSET_EXT):
                continue
            fr = f"{rel}/{f}".lstrip("/")
            parts = rel.split("/") if rel else []
            for k in range(1, len(parts) + 1):  # count the file for every ancestor folder
                a = "/".join(parts[:k])
                total[a] = total.get(a, 0) + 1
                exts.setdefault(a, set()).add(os.path.splitext(f)[1].lower())
                if fr in vend:
                    vcount[a] = vcount.get(a, 0) + 1
    pats = [f"/{d}/" if os.path.isdir(os.path.join(src, d)) else f"/{d}" for d in conf]
    whole = sorted(a for a, n in total.items() if n and vcount.get(a, 0) == n and not under(a, conf))
    top = []
    for a in whole:  # keep the highest fully vendored folders only
        if not under(a, top):
            top.append(a)
    for a in top:
        pats += [f"/{a}/**/*{e}" for e in sorted(exts[a])]
    rest = [f for f in files if not under(f, conf) and not under(f, top) and f.lower().endswith(ASSET_EXT)]
    rest.sort(key=lambda f: -(os.path.getsize(os.path.join(src, f)) if os.path.exists(os.path.join(src, f)) else 0))
    pats += ["/" + f for f in rest]
    kept, size = [], 0
    for p in pats:
        size += len(p) + 12  # "--exclude" plus quoting
        if size > max_chars:
            break
        kept.append(p)
    if report is not None:
        own = configured_dirs()
        report.update({"configured": own, "kits": [d for d in conf if d not in own], "folders": top, "files": len(rest), "patterns": len(pats), "dropped": pats[len(kept):]})
    if len(kept) < len(pats):
        print(f"WARNING: {len(pats) - len(kept)} of {len(pats)} vendor exclude patterns do not fit on the graphify command line "
              f"and are NOT excluded (first: {pats[len(kept)]}). Add their folders to graph.vendor_dirs in codebase-docs.json.",
              file=sys.stderr)
    return kept


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    rep = {}
    pats = graphify_excludes(root, report=rep)
    fl = scan(root)
    for x in rep.get("configured", []):
        print(f"configured folder  {x}")
    for x in rep.get("kits", []):
        print(f"docs output folder {x}")
    for x in rep.get("folders", []):
        print(f"library folder     {x}")
    print(f"{len(fl)} vendored files; {len(pats)} graphify exclude patterns"
          + (f" ({len(rep['dropped'])} dropped: too long for one command line)" if rep.get("dropped") else ""), file=sys.stderr)
