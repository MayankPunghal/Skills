"""Offline Mermaid for the documentation site.

Material for MkDocs loads mermaid.min.js from unpkg.com when a page shows a diagram, so a site opened without internet
shows the diagrams as plain text. A local copy listed under extra_javascript in mkdocs.yml is used instead (Material
takes an already-defined `mermaid` global and fetches nothing).

The copy is a prerequisite: install_prerequisites.py downloads it once (about 3 MB, MIT licence) into
~/.cache/codebase-documenter/, and every build_site.py run copies it into docs/assets/javascripts/ and lists it in
mkdocs.yml (reader_guide.py), so no workspace needs a download of its own.

    python offline_mermaid.py --status              # pages with diagrams, local copy present?, cached copy present?
    python offline_mermaid.py --from <file.js>      # use a mermaid.min.js you already have (node_modules/mermaid/dist/...)
    python offline_mermaid.py --install             # copy from the cache, else download into the cache first
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys
import urllib.request

def tested_version():
    """The Mermaid release this skill was tested with (scripts/data/tool_versions.json)."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tool_versions.json")
    return json.load(open(p, encoding="utf-8"))["tools"]["mermaid"]["tested"]


URL = f"https://cdn.jsdelivr.net/npm/mermaid@{tested_version()}/dist/mermaid.min.js"  # the npm package, served by jsDelivr
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "codebase-documenter", "mermaid.min.js")
REL = "assets/javascripts/mermaid.min.js"  # relative to docs_dir, as mkdocs.yml lists it


def cached_version():
    """Version of the cached copy (its embedded version string), or None."""
    if not os.path.exists(CACHE):
        return None
    found = re.findall(r'version:"(\d+\.\d+\.\d+)"', open(CACHE, encoding="utf-8", errors="ignore").read())
    real = [v for v in found if v != "0.0.0"]
    return real[0] if real else None


def fetch_to_cache():
    """Download the tested mermaid.min.js into the cache, replacing any other version. (ok, message); an error or
    captive-portal page is never cached, since every later workspace would copy it."""
    try:
        data = urllib.request.urlopen(URL, timeout=60).read()
    except OSError as e:
        return False, f"download failed ({e}); copy a mermaid.min.js by hand and run offline_mermaid.py --from <file>"
    if data.lstrip()[:1] == b"<" or b"mermaid" not in data[:20000] or len(data) < 500_000:
        return False, "the download does not look like mermaid.min.js; nothing cached"
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    open(CACHE, "wb").write(data)
    return True, f"cached {len(data) // 1024} KB at {CACHE}"


def diagram_pages(docs):
    return [p for p in glob.glob(os.path.join(docs, "**", "*.md"), recursive=True)
            if f"{os.sep}_tools{os.sep}" not in p and "```mermaid" in open(p, encoding="utf-8", errors="ignore").read()]


def listed(yml_text):
    return bool(re.search(r"(?m)^\s*-\s*['\"]?" + re.escape(REL) + r"['\"]?\s*$", yml_text))


def status(docs, yml="mkdocs.yml"):
    """(pages with diagrams, local copy listed and present)."""
    text = open(yml, encoding="utf-8").read() if os.path.exists(yml) else ""
    return diagram_pages(docs), listed(text) and os.path.exists(os.path.join(docs, REL))


def add_to_mkdocs(yml="mkdocs.yml"):
    text = open(yml, encoding="utf-8").read()
    if listed(text):
        return False
    m = re.search(r"(?m)^extra_javascript:[ \t]*\r?\n", text)
    if m:
        text = text[:m.end()] + f"  - {REL}\n" + text[m.end():]
    else:
        nav = text.find("# >>> nav")
        block = f"extra_javascript:\n  - {REL}\n\n"
        text = text[:nav] + block + text[nav:] if nav >= 0 else text.rstrip("\n") + "\n\n" + block
    open(yml, "w", encoding="utf-8", newline="\n").write(text)
    return True


def ensure(docs, yml="mkdocs.yml", src=None):
    """Copy the cached (or given) mermaid.min.js into the docs and list it in mkdocs.yml. Called on every build; a
    no-op returning False when there is no copy (verify_docs.py then notes that diagrams need internet)."""
    src = src or CACHE
    if not os.path.exists(src) or not os.path.exists(yml):
        return False
    dest = os.path.join(docs, REL)
    if not os.path.exists(dest) or os.path.getsize(dest) != os.path.getsize(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
    add_to_mkdocs(yml)
    return True


def main():
    from _common import load_config, utf8_stdout
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--install", action="store_true", help="copy from the cache, else download into the cache first")
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
            print("NEXT: run install_prerequisites.py (caches Mermaid once), or offline_mermaid.py --from <mermaid.min.js>")
        return
    if a.src:
        ok = ensure(docs, src=a.src)
        how = f"copied from {a.src}"
    else:
        how = "copied from the cache"
        if not os.path.exists(CACHE):
            print(f"downloading {URL} ...", flush=True)
            fetched, msg = fetch_to_cache()
            if not fetched:
                sys.exit(msg)
            how = msg
        ok = ensure(docs)
    print(f"offline Mermaid: {'ready' if ok else 'not set up (no mkdocs.yml?)'} ({how}). Rebuild the site (build_site.py).")


if __name__ == "__main__":
    main()
