"""Find anything in the documentation by name and print where it is documented AND where it lives in the code.

Usage (run from the folder Claude Code / your editor is opened in, so printed paths are clickable):
  python docs/_tools/lookup.py Order_Calculate_Totals            # exact / partial name, any kind
  python docs/_tools/lookup.py Order --kind table                # restrict kind (table, routine, controller, action,
                                                                 #   class, method, project, package, endpoint, ui-trigger, entry-point, db-access, error, runbook, view, enum, seed, claim, role, script, report, page, section)
  python docs/_tools/lookup.py "send to billing" --list          # list matches only, no bodies
  python docs/_tools/lookup.py BillingService --find invoice_id        # lines in the source file matching text

Each match prints:
  doc:  <path>:<line>     where it is documented
  src:  <path>:<line>     the source file and the line where it is declared (when the source code is present)
Paths are relative to the current folder, with forward slashes, so they open as links.
The source root is --src, DOCS_SOURCE_ROOT, codebase-docs.json source_root, or found automatically (a folder containing the
source_markers listed in codebase-docs.json).
Built for coding agents: output is plain text, bounded in size.
"""
import argparse
import json
import os
import re

# Paths resolve from this script's own location (<root>/docs/_tools/lookup.py), so it works from any working directory
# and wherever the docs were unpacked (repo root, repo-kit/, a docs-only workspace ...).
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX = os.path.join(BASE, "docs", "agent", "entities.jsonl")
SRC_EXT = (r"[\w./ -]+\.(?:cs|vb|sql|cshtml|razor|js|mjs|cjs|jsx|ts|tsx|vue|svelte|py|java|kt|kts|scala|go|rb|php|rs|swift|"
           r"c|cc|cpp|h|hpp|m|rdl|rdlc|config|asmx|aspx|json|xml|ya?ml|toml|graphql|proto)")
_lines_cache = {}


def rel(path):
    try:
        r = os.path.relpath(path)
        path = os.path.abspath(path) if r.startswith("..") else r  # outside the current folder: absolute is clearer
    except ValueError:  # other drive on Windows
        pass
    return path.replace("\\", "/")


def read_lines(path):
    if path not in _lines_cache:
        try:
            _lines_cache[path] = open(path, encoding="utf-8-sig", errors="replace").read().splitlines()
        except OSError:
            _lines_cache[path] = None
    return _lines_cache[path]


CFG_FILE = os.path.join(BASE, "codebase-docs.json")
CFG = json.load(open(CFG_FILE, encoding="utf-8")) if os.path.exists(CFG_FILE) else {}
MARKERS = CFG.get("source_markers") or []


def is_source_root(d):
    if MARKERS:
        return any(os.path.exists(os.path.join(d, m)) for m in MARKERS)
    return False


def find_source_root(explicit):
    for c in (explicit, os.environ.get("DOCS_SOURCE_ROOT")):  # explicit choices win, markers or not
        if c and os.path.isdir(c):
            return os.path.abspath(c)
    if not MARKERS:  # no markers configured: trust codebase-docs.json source_root (relative to the docs root)
        c = os.path.join(BASE, CFG.get("source_root", "."))
        return os.path.abspath(c) if CFG and os.path.isdir(c) else None
    cands = [explicit, os.environ.get("DOCS_SOURCE_ROOT"), BASE, os.path.dirname(BASE),
             os.path.join(BASE, CFG.get("source_root", ".")), os.path.join(os.path.dirname(BASE), CFG.get("source_root", ".")),
             os.getcwd()]
    for c in cands:
        if c and is_source_root(os.path.abspath(c)):
            return os.path.abspath(c)
    # ponytail: shallow search only (2 levels under the docs root's parent); pass --src for other layouts
    parent = os.path.dirname(BASE)
    for d1 in sorted(os.listdir(parent)):
        p1 = os.path.join(parent, d1)
        if not os.path.isdir(p1) or d1.startswith("."):
            continue
        if is_source_root(p1):
            return p1
        try:
            for d2 in sorted(os.listdir(p1)):
                p2 = os.path.join(p1, d2)
                if os.path.isdir(p2) and is_source_root(p2):
                    return p2
        except OSError:
            pass
    return None


def anchor_line(ent, lines):
    """0-based line of the entry in its doc file, or None."""
    if ent["anchor"]:
        tag = f'<a id="{ent["anchor"]}"></a>'
        for i, l in enumerate(lines):
            if tag in l:
                return i
    if ent["kind"] == "section":
        for i, l in enumerate(lines):
            if re.match(r"#{2,3}\s+", l) and ent["name"] in re.sub(r"[*`]", "", l):
                return i
    return None if ent["anchor"] or ent["kind"] == "section" else 0


def body(ent, lines, i, max_lines=60):
    if ent["kind"] == "seed-row":  # one row of a seed table: the summary holds all its columns
        return ent["summary"]
    if i is None:
        return ent["summary"]
    if not ent["anchor"] and ent["kind"] != "section":
        return "\n".join(lines[:max_lines])
    if lines[i].startswith("|"):  # table row entry: the row itself is the entry
        return lines[i]
    out, headed = ([lines[i]], True) if ent["kind"] == "section" and not ent["anchor"] else ([], False)
    for m in lines[i + 1:]:
        if re.match(r'<a id="(?!index)', m) or (headed and re.match(r"#{1,2} ", m)):
            break
        headed = headed or m.startswith("#")
        out.append(m)
    return "\n".join(out[:max_lines]).strip()


def source_path(ent, lines, i, text):
    """Source file (relative to the source root) of an entry, taken from its doc text."""
    if ent["kind"] in ("page", "section", "seed-row", "claim", "role", "report"):
        return None
    m = re.findall(r"`(" + SRC_EXT + r")`", text)
    if m:
        return m[-1] if ent["kind"] == "routine" else m[0]  # routine rows end with the .sql path
    if i is not None:  # e.g. an action row: the controller's "File:" line sits above it
        for l in reversed(lines[:i]):
            m = re.search(r"(?:File|Source):\s*`(" + SRC_EXT + r")`", l) or re.match(r"#+ .*?`(" + SRC_EXT + r")`", l)
            if m:
                return m.group(1)
    return None


def decl_line(ent, src_lines):
    """1-based line where the entry is declared in its source file."""
    n = re.escape(ent["name"].split(".")[-1].split(" ")[0])
    k = ent["kind"]
    if k in ("table", "routine"):
        pat = r"CREATE\s+(?:OR\s+ALTER\s+)?(?:PROC(?:EDURE)?|FUNCTION|VIEW|TABLE|TRIGGER|TYPE)\s+[\[\w\].]*?\[?" + n + r"\]?\b"
    elif k in ("class", "controller"):
        pat = r"\b(?:class|interface|struct|record|trait|type|module|object)\s+" + n + r"\b"
    elif k in ("function", "endpoint", "method"):  # Python, JS/TS, Go, Rust, Kotlin, Ruby, C-like methods
        pat = (r"(?:\bdef\s+|\bfunction\s*\*?\s*|\bfunc\s+(?:\([^)]*\)\s*)?|\bfn\s+|\bfun\s+|"
               r"\b(?:const|let|var)\s+(?=" + n + r"\s*=)|"
               r"\b(?!(?:return|await|new|throw|yield|else|case|in|of|is|as)\b)[\w<>,\[\]?]+\s+)" + n + r"\s*[(=<]")
    elif k == "enum":
        pat = r"\benum\s+" + n + r"\b"
    elif k == "action":
        pat = r"\bpublic\b[^=;]*\b" + n + r"\s*\("
    elif k == "script":
        return 1
    else:
        pat = r"\b" + n + r"\b"
    rx = re.compile(pat, re.I if k in ("table", "routine") else 0)
    nth = 1
    m = re.search(r"-(\d+)$", ent["anchor"] or "")
    if k == "action" and m:  # overloads get anchors ...-2, -3
        nth = int(m.group(1))
    seen = 0
    for j, l in enumerate(src_lines):
        if rx.search(l):
            seen += 1
            if seen == nth:
                return j + 1
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--kind")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--find", help="print lines of each match's source file containing this text (case-insensitive)")
    ap.add_argument("--src", help="source root (the folder containing the code; see source_markers in codebase-docs.json)")
    a = ap.parse_args()
    import sys
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    q = a.query.lower()
    ents = [json.loads(l) for l in open(INDEX, encoding="utf-8")]
    if a.kind:
        ents = [e for e in ents if e["kind"] == a.kind]
    exact = [e for e in ents if e["name"].lower() == q]
    part = [e for e in ents if q in e["name"].lower() and e not in exact]
    text = [e for e in ents if q in e["summary"].lower() and e not in exact and e not in part]
    hits = exact + part + text
    if not hits:
        print("no match"); return
    src_root = find_source_root(a.src)
    print(f"{len(hits)} match(es); showing {min(len(hits), a.limit)}")
    print(f"source root: {rel(src_root) if src_root else 'NOT FOUND (set DOCS_SOURCE_ROOT or --src) - code paths are relative to the repository root'}\n")
    for e in hits[:a.limit]:
        doc = os.path.join(BASE, e["file"])
        lines = read_lines(doc) or []
        i = anchor_line(e, lines)
        b = body(e, lines, i)
        print(f"== {e['kind']}: {e['name']}")
        print(f"   doc: {rel(doc)}:{(i or 0) + 1}")
        sp = source_path(e, lines, i, b)
        if sp:
            full = os.path.join(src_root, sp) if src_root else None
            src_lines = read_lines(full) if full else None
            if src_lines is not None:
                print(f"   src: {rel(full)}:{decl_line(e, src_lines)}")
                if a.find:
                    f = a.find.lower()
                    found = [(j + 1, l.strip()) for j, l in enumerate(src_lines) if f in l.lower()]
                    for j, l in found[:30]:
                        print(f"        {rel(full)}:{j}  {l[:160]}")
                    if not found:
                        print(f"        (no line contains '{a.find}')")
            else:
                print(f"   src: {sp}  (file not found under the source root)")
        if not a.list:
            print(b); print()
    if len(hits) > a.limit:
        print(f"... {len(hits) - a.limit} more (use --limit or --kind)")


if __name__ == "__main__":
    main()
