"""Third-party front-end libraries copied into a repository (jQuery, Bootstrap, Modernizr, WebForms scripts ...).

They are not the project's code: counting them inflates code volume, and graphing them buries the real communities and hubs
under thousands of library functions. Shared by survey_codebase.py, code_graph.py (graphify --exclude) and the
migration-assessment map_graphs.py. Standard library only.

    python <skill>/scripts/vendor_files.py <source root>      # list the vendored files found
"""
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


def is_vendored(path, rel, pkgs):
    """A vendor folder; a file named after a declared client-side package (jquery-3.4.1.js from the jQuery NuGet package);
    a folder named after one (Scripts/WebForms from Microsoft.AspNet.ScriptManager.WebForms); a Visual Studio IntelliSense
    copy; or a .js / .css file whose first lines carry a library banner (/*! name vX | licence */, @license, NuGet's
    licence block, //CdnPath=)."""
    rel = rel.replace("\\", "/")
    if VENDOR_DIR.search(rel):
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
    try:
        head = open(path, encoding="utf-8", errors="ignore").read(600)
    except OSError:
        return False
    return ("/*!" in head or "@license" in head or "NUGET: BEGIN LICENSE TEXT" in head
            or head.lstrip("﻿").startswith("//CdnPath=") or bool(BANNER.search(head)))


def scan(src, skip=SKIP):
    """Relative paths (forward slashes) of every vendored file under src."""
    pkgs = client_packages(src, skip)
    out = []
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in skip and not x.startswith(".")]
        for f in files:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, src).replace("\\", "/")
            if is_vendored(p, rel, pkgs):
                out.append(rel)
    return sorted(out)


def graphify_excludes(src, skip=SKIP, max_patterns=400):
    """gitignore-style patterns (anchored at src) for graphify extract --exclude: a whole folder when every script / style
    file in it is vendored, otherwise the files one by one."""
    files = scan(src, skip)
    if not files:
        return []
    vend = set(files)
    by_dir = {}
    for f in files:
        by_dir.setdefault(f.rsplit("/", 1)[0] if "/" in f else "", []).append(f)
    pats = []
    for d, fs in sorted(by_dir.items()):
        full = os.path.join(src, d)
        assets = [x for x in os.listdir(full) if x.lower().endswith(ASSET_EXT)] if os.path.isdir(full) else []
        if d and assets and all((d + "/" + x) in vend for x in assets):
            pats += [f"/{d}/*{e}" for e in ASSET_EXT if any(x.lower().endswith(e) for x in assets)]
        else:
            pats += ["/" + f for f in fs]
    return pats[:max_patterns]


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    fl = scan(root)
    for x in fl:
        print(x)
    print(f"{len(fl)} vendored files; {len(graphify_excludes(root))} graphify exclude patterns", file=sys.stderr)
