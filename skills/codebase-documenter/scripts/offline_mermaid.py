"""Offline Mermaid for the documentation site.

Material for MkDocs loads mermaid.min.js from unpkg.com when a page shows a diagram, so a site opened without internet
shows the diagrams as plain text. A local copy listed under extra_javascript in mkdocs.yml is used instead (Material
takes an already-defined `mermaid` global and fetches nothing).

    python offline_mermaid.py --status              # pages with diagrams, local copy present?, cached copy present?
    python offline_mermaid.py --from <file.js>      # use a mermaid.min.js you already have (node_modules/mermaid/dist/...)
    python offline_mermaid.py --install             # copy from the cache, else DOWNLOAD (about 3 MB, MIT licence)

--install downloads only when no cached copy exists: ask the user first (the skill never downloads without approval).
The copy is cached in ~/.cache/codebase-documenter/ so later workspaces need no download. Run from the workspace root.
"""
import argparse
import glob
import os
import re
import shutil
import sys
import urllib.request

from _common import load_config, utf8_stdout

URL = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"  # the npm package, served by jsDelivr
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "codebase-documenter", "mermaid.min.js")
REL = "assets/javascripts/mermaid.min.js"  # relative to docs_dir, as mkdocs.yml lists it


def diagram_pages(docs):
    return [p for p in glob.glob(os.path.join(docs, "**", "*.md"), recursive=True)
            if f"{os.sep}_tools{os.sep}" not in p and "```mermaid" in open(p, encoding="utf-8", errors="ignore").read()]


def listed(yml_text):
    return bool(re.search(r"(?m)^\s*-\s*['\"]?" + re.escape(REL) + r"['\"]?\s*$", yml_text))


def status(docs):
    """(pages with diagrams, local copy listed and present)."""
    yml = open("mkdocs.yml", encoding="utf-8").read() if os.path.exists("mkdocs.yml") else ""
    return diagram_pages(docs), listed(yml) and os.path.exists(os.path.join(docs, REL))


def add_to_mkdocs():
    text = open("mkdocs.yml", encoding="utf-8").read()
    if listed(text):
        return False
    m = re.search(r"(?m)^extra_javascript:[ \t]*\r?\n", text)
    if m:
        text = text[:m.end()] + f"  - {REL}\n" + text[m.end():]
    else:
        nav = text.find("# >>> nav")
        block = f"extra_javascript:\n  - {REL}\n\n"
        text = text[:nav] + block + text[nav:] if nav >= 0 else text.rstrip("\n") + "\n\n" + block
    open("mkdocs.yml", "w", encoding="utf-8", newline="\n").write(text)
    return True


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--install", action="store_true", help="copy from the cache, else download (ask the user first)")
    g.add_argument("--from", dest="src", help="path to an existing mermaid.min.js")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    docs = cfg["docs_dir"]
    pages, local = status(docs)
    if a.status:
        print(f"pages with diagrams: {len(pages)} · local Mermaid: {'yes' if local else 'no'} · cached copy: "
              f"{'yes' if os.path.exists(CACHE) else 'no'} ({CACHE})")
        if pages and not local:
            print("NEXT: the site needs internet for its diagrams; run --from <mermaid.min.js> or, after the user approves "
                  "the ~3 MB download, --install")
        return
    dest = os.path.join(docs, REL)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if a.src:
        shutil.copy2(a.src, dest)
        how = f"copied from {a.src}"
    elif os.path.exists(CACHE):
        shutil.copy2(CACHE, dest)
        how = "copied from the cache"
    else:
        print(f"downloading {URL} ...", flush=True)
        try:
            data = urllib.request.urlopen(URL, timeout=60).read()
        except OSError as e:
            sys.exit(f"download failed ({e}); copy a mermaid.min.js by hand and use --from")
        # an error or captive-portal page must never reach the cache: every later workspace would copy it
        if data.lstrip()[:1] == b"<" or b"mermaid" not in data[:20000] or len(data) < 500_000:
            sys.exit("the download does not look like mermaid.min.js; nothing written")
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        open(CACHE, "wb").write(data)
        shutil.copy2(CACHE, dest)
        how = f"downloaded ({len(data) // 1024} KB, cached for later workspaces)"
    changed = add_to_mkdocs()
    print(f"offline Mermaid: {dest} {how}; mkdocs.yml extra_javascript {'updated' if changed else 'already lists it'}. "
          "Rebuild the site (build_site.py).")


if __name__ == "__main__":
    main()
