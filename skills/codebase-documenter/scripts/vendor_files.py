"""Third-party front-end libraries copied into a repository (jQuery, Bootstrap, Modernizr, WebForms scripts, chart kits ...).

They are not the project's code: counting them inflates code volume, and graphing them buries the real communities and hubs
under thousands of library functions. Shared by survey_codebase.py, code_graph.py (graphify --exclude), network_endpoints.py
and the migration-assessment map_graphs.py. Standard library only.

Three sources, all additive:
  - configured folders: "graph": {"vendor_dirs": ["Scripts/highmapsv10.1", "Content/kendo"]} in codebase-docs.json
    (paths relative to the source root; a whole folder, recursively, or one file);
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
BANNER = re.compile(r"(?i)\bv?\d+\.\d+\.\d+\b.{0,80}\b(license|\(c\)|copyright)")
STEM_CUT = re.compile(r"[-.](?:\d|min\b|slim\b|bundle\b)")
VERSIONED_DIR = re.compile(r"(?i)(?:^|[-_.v])v?\d+(?:\.\d+)+(?:[-_.]?\w+)?$|[a-z]v\d+(?:\.\d+)*$")
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
            or head.lstrip("﻿").startswith("//CdnPath=") or bool(BANNER.search(head)))


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
    if len(stem) >= 4 and any(stem == pk or stem.startswith(pk + ".") or pk.startswith(stem + ".") for pk in pkgs):
        return True
    parts = rel.lower().split("/")
    if len(parts) >= 3 and parts[-3] in ASSET_PARENTS and any(len(pk.split(".")[-1]) >= 5 and parts[-2] == pk.split(".")[-1] for pk in pkgs):
        return True
    return has_banner(path)


def library_dirs(src, skip=SKIP):
    """Folders that hold a copied library: the name carries a version and some file below has a library banner."""
    found = []
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in skip and not x.startswith(".")]
        rel = os.path.relpath(d, src).replace("\\", "/")
        if rel == "." or not VERSIONED_DIR.search(rel.rsplit("/", 1)[-1]) or under(rel, found):
            continue
        for d2, dirs2, files2 in os.walk(d):
            dirs2[:] = [x for x in dirs2 if x not in skip and not x.startswith(".")]
            if any(f.lower().endswith(ASSET_EXT) and has_banner(os.path.join(d2, f)) for f in files2):
                found.append(rel)
                break
    return found


def context(src, skip=SKIP):
    """(declared client packages, configured + detected library folders) for is_vendored()."""
    conf = configured_dirs()
    return client_packages(src, skip), conf + [d for d in library_dirs(src, skip) if not under(d, conf)]


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
    conf = configured_dirs()
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
        report.update({"configured": conf, "folders": top, "files": len(rest), "patterns": len(pats), "dropped": pats[len(kept):]})
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
    for x in rep.get("folders", []):
        print(f"library folder     {x}")
    print(f"{len(fl)} vendored files; {len(pats)} graphify exclude patterns"
          + (f" ({len(rep['dropped'])} dropped: too long for one command line)" if rep.get("dropped") else ""), file=sys.stderr)
