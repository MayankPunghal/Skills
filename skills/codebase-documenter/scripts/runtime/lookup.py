"""Find anything in the documentation by name and print where it is documented AND where it lives in the code.

Usage (run from the folder Claude Code / your editor is opened in, so printed paths are clickable):
  python docs/_tools/lookup.py Order_Calculate_Totals            # exact / partial name, any kind
  python docs/_tools/lookup.py Order --kind table                # restrict kind (table, routine, controller, action,
                                                                 #   class, method, project, package, endpoint, ui-trigger, entry-point, db-access, error, runbook, view, enum, seed, claim, role, script, report, page, section)
  python docs/_tools/lookup.py "send to billing" --list          # list name / summary matches only, no bodies (several
                                                                 #   words without --list or --fuzzy rank by keywords)
  python docs/_tools/lookup.py BillingService --find invoice_id        # lines in the source file matching text
  python docs/_tools/lookup.py Order --fuzzy                     # an exact name shows only itself; --fuzzy adds partial
                                                                 #   and summary matches
  python docs/_tools/lookup.py SEC-02                            # finding ids (SEC-, DEF-, TD-) and narrative rows
  python docs/_tools/lookup.py --search "where are coupons validated"   # a question in words: ranked docs + code items

--search ranks the retrieval cards (docs/agent/cards.jsonl: every documented item and every narrative section) by
keyword relevance (BM25 over names, identifier words and text) and prints the best matches with their doc and source
locations; a name that matches nothing falls back to it. Use it when you know the topic but not the name.

Each match prints:
  doc:  <path>:<line>     where it is documented
  src:  <path>:<line>     the source file and the line where it is declared (when the source code is present)
then the doc entry, then the code: the whole declaration for classes, methods, procedures, tables ... (attributes and doc
comments included, at most --code-lines, default 40) or, for call sites, errors and settings, each cited source line; the
first --code-matches (3) matches only, none with --no-code or --list. A "note:" line flags a source file changed after the
docs were built. The first match also gets its connections (callers, callees, tables read and written, code that uses
it, entry points ... from its card), the related items with their source locations, and the findings that name it
(--no-related turns this off).
Paths are relative to the current folder, with forward slashes, so they open as links.
The source root is --src, DOCS_SOURCE_ROOT, codebase-docs.json source_root, or found automatically (a folder containing the
source_markers listed in codebase-docs.json).
Built for coding agents: output is plain text, bounded in size.
"""
import argparse
import json
import math
import os
import re
from collections import Counter

# Paths resolve from this script's own location (<root>/docs/_tools/lookup.py), so it works from any working directory
# and wherever the docs were unpacked (repo root, repo-kit/, a docs-only workspace ...).
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX = os.path.join(BASE, "docs", "agent", "entities.jsonl")
CARDS = os.path.join(BASE, "docs", "agent", "cards.jsonl")
EXTS = (r"\.(?:cs|vb|sql|cshtml|razor|js|mjs|cjs|jsx|ts|tsx|vue|svelte|py|java|kt|kts|scala|go|rb|php|rs|swift|"
        r"c|cc|cpp|h|hpp|m|rdl|rdlc|config|asmx|aspx|json|xml|ya?ml|toml|graphql|proto)")
SRC_EXT = r"[\w./ -]+" + EXTS   # inside backticks, where a path may hold spaces
BARE_EXT = r"[\w./-]+" + EXTS   # in running text, where a space ends the path
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
    if ent.get("line") is not None and ent["line"] < len(lines):  # table rows (findings, narrative rows) carry their line
        return ent["line"]
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


LOC_TICK = re.compile(r"`(" + SRC_EXT + r"):(\d+)`")              # `src/X.cs:73` in reference pages
LOC_BARE = re.compile(r"(?<![\w/.-])(" + BARE_EXT + r"):(\d+)\b")  # src/X.cs:73 in index summaries and cards
DECLARED = ("table", "routine", "class", "controller", "function", "method", "enum", "action", "endpoint", "view", "script")


def locations(text):
    """Every distinct `path:line` in a doc entry, in order."""
    out = []
    for m in list(LOC_TICK.finditer(text)) or list(LOC_BARE.finditer(text)):
        loc = (m.group(1).strip(), int(m.group(2)))
        if loc not in out:
            out.append(loc)
    return out


LANG = {".cs": "csharp", ".vb": "vbnet", ".sql": "sql", ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
        ".jsx": "jsx", ".java": "java", ".kt": "kotlin", ".go": "go", ".rs": "rust", ".php": "php", ".rb": "ruby", ".cshtml": "cshtml",
        ".razor": "razor", ".aspx": "aspx", ".json": "json", ".xml": "xml", ".config": "xml", ".yml": "yaml", ".yaml": "yaml"}
BRACES = (".cs", ".java", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".kt", ".kts", ".scala", ".rs", ".swift", ".php",
          ".c", ".cc", ".cpp", ".h", ".hpp", ".m")
VB_END = re.compile(r"^\s*End\s+(Sub|Function|Class|Module|Property|Structure|Interface|Enum|Namespace)\b", re.I)


def block_end(src_lines, start, ext):
    """0-based last line of the declaration starting at 0-based line `start`: the matching brace (C-like), GO or the next
    CREATE (SQL), End Sub/Function/Class (VB), the dedent (Python); a short window for anything else."""
    n = len(src_lines)
    if ext == ".sql":
        for j in range(start + 1, n):
            if re.match(r"\s*GO\s*(--.*)?$", src_lines[j], re.I):
                return j - 1
            if re.match(r"(?:CREATE|ALTER)\s+(?:OR\s+ALTER\s+)?(?:PROC|FUNCTION|VIEW|TABLE\s+[^#\s]|TRIGGER|TYPE)", src_lines[j], re.I):
                # the next object in a script without GO; an indented CREATE TABLE #temp inside the body is not one
                return j - 1
        return n - 1
    if ext == ".vb":
        for j in range(start + 1, n):
            if VB_END.match(src_lines[j]):
                return j
        return min(n - 1, start + 15)
    if ext == ".py":
        ind = len(src_lines[start]) - len(src_lines[start].lstrip())
        last = start
        for j in range(start + 1, n):
            s = src_lines[j]
            if s.strip() and len(s) - len(s.lstrip()) <= ind and not s.lstrip().startswith((")", "]")):
                break
            if s.strip():
                last = j
        return last
    if ext not in BRACES:
        return min(n - 1, start + 15)
    depth, opened, block_c, quote = 0, False, False, None
    for j in range(start, n):
        s, k = src_lines[j], 0
        if quote in ('"', "'"):  # ordinary strings end with their line; verbatim, raw and template strings do not
            quote = None
        while k < len(s):
            ch = s[k]
            if block_c:
                if s.startswith("*/", k):
                    block_c, k = False, k + 1
            elif quote and len(quote) >= 3:  # C# raw string literal: ends at the same run of quotes
                if s.startswith(quote, k):
                    quote, k = None, k + len(quote) - 1
            elif quote:
                if ch == "\\" and quote != '@"':
                    k += 1
                elif quote == '@"' and s.startswith('""', k):
                    k += 1
                elif ch == quote[-1]:
                    quote = None
            elif s.startswith("//", k):
                break
            elif s.startswith("/*", k):
                block_c, k = True, k + 1
            elif s.startswith('@"', k) or s.startswith('$@"', k) or s.startswith('@$"', k):
                quote, k = '@"', k + (1 if s[k] == "@" and s[k + 1] == '"' else 2)
            elif s.startswith('"""', k):
                run_len = len(s[k:]) - len(s[k:].lstrip('"'))
                quote, k = '"' * run_len, k + run_len - 1
            elif ch in "\"'`":
                quote = ch
            elif ch == "{":
                depth, opened = depth + 1, True
            elif ch == "}":
                depth -= 1
                if opened and depth == 0:
                    return j
            elif ch == ";" and not opened and depth == 0:  # expression-bodied member or a declaration without a body
                return j
            k += 1
    return min(n - 1, start + 15)


def snippet(src_lines, line, ext, max_lines):
    """(first, last, text) of the declaration at 1-based `line`, with the attributes / doc comments right above it."""
    start = max(0, min(line, len(src_lines)) - 1)
    first = start
    marks = ("[", "///", "@", "<Attribute") + (("--",) if ext == ".sql" else ())  # attributes, doc comments, decorators
    while first > 0 and first > start - 8 and src_lines[first - 1].lstrip().startswith(marks):
        first -= 1
    last = block_end(src_lines, start, ext)
    shown = src_lines[first:min(last, first + max_lines - 1) + 1]
    return first + 1, last + 1, "\n".join(shown)


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


_cards = None


def cards():
    """Retrieval cards by id (empty when the docs predate gen_rag_cards.py)."""
    global _cards
    if _cards is None:
        _cards = {}
        if os.path.exists(CARDS):
            for line in open(CARDS, encoding="utf-8"):
                c = json.loads(line)
                _cards[c["id"]] = c
    return _cards


STOP = set("a an and are as at be by can do does for from how i in is it its of on or the to what when where which who "
           "why with this that these those there get set use used using code app".split())


def words(text):
    """Search terms: identifiers split at case changes, underscores and dots; lower case; one common suffix dropped, so
    "validated coupons" meets ValidateCoupon."""
    out = []
    for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", text):
        w = w.lower()
        if len(w) < 2 or w in STOP:
            continue
        for suf in ("ing", "ed", "es", "e", "s"):
            if w.endswith(suf) and len(w) - len(suf) >= 3 and not w.endswith("ss"):
                w = w[:-len(suf)]
                break
        out.append(w)
    return out


def search(query, limit):
    """Cards ranked by BM25 over title (x3), identifier keys (x2) and text."""
    q = set(words(query))
    cs = list(cards().values())
    if not q or not cs:
        return []
    docs = [Counter(words(c["title"]) * 3 + words(" ".join(c.get("keys") or [])) * 2 + words(c.get("text") or ""))
            for c in cs]
    avg = sum(sum(d.values()) for d in docs) / len(docs)
    df = Counter(w for d in docs for w in q if w in d)
    scored = []
    for c, d in zip(cs, docs):
        n = sum(d.values())
        s = sum(math.log(1 + (len(cs) - df[w] + 0.5) / (df[w] + 0.5)) * d[w] * 2.2 / (d[w] + 1.2 * (0.25 + 0.75 * n / avg))
                for w in q if w in d)
        if s:
            scored.append((s * (0.5 + 0.5 * sum(w in d for w in q) / len(q)), c))  # favour cards holding more of the words
    return [c for _, c in sorted(scored, key=lambda t: -t[0])[:limit]]


def slug(heading):
    return re.sub(r"\s+", "-", re.sub(r"[^\w\- ]", "", heading).strip().lower())


def doc_loc(doc):
    """Clickable docs path:line for a card's "page.md#anchor"."""
    page, _, anchor = doc.partition("#")
    path = os.path.join(BASE, "docs", page)
    lines = read_lines(path) or []
    for i, line in enumerate(lines):
        if anchor and (f'id="{anchor}"' in line or (line.startswith("#") and slug(line.lstrip("#")) == anchor)):
            return f"{rel(path)}:{i + 1}"
    return f"{rel(path)}:1"


def src_loc(loc, src_root):
    """`path:line` under the source root as a clickable path, unchanged when the code is not here."""
    m = re.fullmatch(r"(.+):(\d+)", loc or "")
    if not m or not src_root or not os.path.exists(os.path.join(src_root, m.group(1))):
        return loc or ""
    return f"{rel(os.path.join(src_root, m.group(1)))}:{m.group(2)}"


def linkify(text, src_root):
    """Every bare path:line in card text, made clickable under the source root."""
    return LOC_BARE.sub(lambda m: src_loc(f"{m.group(1)}:{m.group(2)}", src_root), text)


def print_search(query, limit, src_root):
    found = search(query, limit)
    if not found:
        print("no match (no card shares a word with the query)")
        return
    print(f'search "{query}": best {len(found)} of {len(cards())} cards by keyword relevance; check each with lookup.py <name>\n')
    for k, c in enumerate(found, 1):
        lines = [l for l in (c.get("text") or "").splitlines()[1:] if l.strip() and not l.startswith("Defined in")]
        print(f"{k}. [{c['kind']}] {c['title']}")
        print(f"   doc: {doc_loc(c['doc'])}" + (f"   src: {src_loc(c['source'], src_root)}" if c.get("source") else ""))
        if lines:
            print("   " + linkify(lines[0], src_root)[:220])


CONTEXT_SKIP = ("Defined in", "Declaration:", "Parameters:", "Returns:", "Columns:")  # already in the entry or the code


def related(e, src_root):
    """Connections of an entry from its card, the related cards with their source, and the findings naming it."""
    out = []
    c = cards().get(e.get("anchor") or "")
    if c:
        lines = [l for l in c["text"].splitlines()[1:] if l.strip() and not l.startswith(CONTEXT_SKIP)]
        if lines:
            out.append("connections:")
            out += [f"   {linkify(l, src_root)[:600]}" for l in lines[:15]]
        rel_cards = [cards()[r] for r in c.get("related") or [] if r in cards()]
        if rel_cards:
            out.append("related:")
            out += [f"   [{r['kind']}] {r['title']}  " + (src_loc(r["source"], src_root) or doc_loc(r["doc"])) for r in rel_cards[:10]]
            if len(rel_cards) > 10:
                out.append(f"   ... {len(rel_cards) - 10} more")
    short = e["name"].split(".")[-1].split(" ")[0]
    if len(short) >= 4 and e["kind"] not in ("finding", "page", "section"):
        rx = re.compile(r"(?<![\w.])" + re.escape(short) + r"(?!\w)", re.I)
        hits = [f for f in ENTS if f["kind"] == "finding" and rx.search(f["summary"])]
        if hits:
            out.append("findings that name it:")
            for f in hits[:5]:
                lines = read_lines(os.path.join(BASE, f["file"])) or []
                at = anchor_line(f, lines)
                out.append(f"   {f['name'][:110]}  ({rel(os.path.join(BASE, f['file']))}:{(at or 0) + 1})")
    return out


ENTS = []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--search", metavar="WORDS", help="rank docs and code items by keyword relevance to a question")
    ap.add_argument("--no-related", action="store_true", help="skip the first match's connections, related items and findings")
    ap.add_argument("--kind")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--find", help="print lines of each match's source file containing this text (case-insensitive)")
    ap.add_argument("--src", help="source root (the folder containing the code; see source_markers in codebase-docs.json)")
    ap.add_argument("--fuzzy", action="store_true", help="also show partial and summary matches when an exact name matches")
    ap.add_argument("--no-code", action="store_true", help="do not print the code of the declaration / the cited source lines")
    ap.add_argument("--code-lines", type=int, default=40, help="most lines of code printed per match (default 40)")
    ap.add_argument("--code-matches", type=int, default=3, help="matches that get their code printed (default the first 3)")
    a = ap.parse_args()
    import sys
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    if not a.query and not a.search:
        ap.error("give a name, or --search \"words\"")
    if a.search:
        src_root = find_source_root(a.src)
        print(f"source root: {rel(src_root) if src_root else 'NOT FOUND (set DOCS_SOURCE_ROOT or --src)'}")
        print_search(a.search, a.limit, src_root)
        return
    q = a.query.lower()
    ents = [json.loads(l) for l in open(INDEX, encoding="utf-8")]
    ENTS[:] = ents
    if a.kind:
        ents = [e for e in ents if e["kind"] == a.kind]
    exact = [e for e in ents if e["name"].lower() == q]
    part = [e for e in ents if q in e["name"].lower() and e not in exact]
    text = [e for e in ents if q in e["summary"].lower() and e not in exact and e not in part]
    # an exact name answers the question: partial / summary matches ("ManageController" -> 10 others) only with --fuzzy
    hits = exact if exact and not a.fuzzy else exact + part + text
    src_root = find_source_root(a.src)
    if not exact and " " in q.strip() and not a.fuzzy and not a.list and not a.kind:
        # several words and no item of that name: a topic. Ranked cards answer it better than every page that contains
        # the phrase (whole sections); --fuzzy or --list keeps the substring matches
        print(f"no item is named '{a.query}'; ranking by keywords (--fuzzy for substring matches):")
        print_search(a.query, a.limit, src_root)
        return
    if not hits:  # a topic rather than a name: the closest items by keywords
        print(f"no name matches '{a.query}'" + (f" (kind {a.kind})" if a.kind else "") + "; closest by keywords:")
        print_search(a.query, min(a.limit, 5), src_root)
        return
    print(f"{len(hits)} match(es); showing {min(len(hits), a.limit)}")
    print(f"source root: {rel(src_root) if src_root else 'NOT FOUND (set DOCS_SOURCE_ROOT or --src) - code paths are relative to the repository root'}\n")
    built = os.path.getmtime(INDEX)
    for n_hit, e in enumerate(hits[:a.limit]):
        doc = os.path.join(BASE, e["file"])
        lines = read_lines(doc) or []
        i = anchor_line(e, lines)
        b = body(e, lines, i)
        print(f"== {e['kind']}: {e['name']}")
        print(f"   doc: {rel(doc)}:{(i or 0) + 1}")
        locs = [] if e["kind"] in ("page", "section", "seed-row", "claim", "role", "report") else locations(b) or locations(e["summary"])
        # the entry's own `path:line` is the declaration; the old guess (first / last path in the text) is the fallback
        sp, at = (locs[0] if locs and e["kind"] in DECLARED else (source_path(e, lines, i, b), None))
        code = []  # printed after the doc text: the declaration, or each cited source line
        if sp:
            full = os.path.join(src_root, sp) if src_root else None
            src_lines = read_lines(full) if full else None
            if src_lines is not None:
                at = at if at and at <= len(src_lines) else decl_line(e, src_lines)
                print(f"   src: {rel(full)}:{at}")
                if os.path.getmtime(full) > built + 1:
                    print("   note: this source file changed after the docs were built; where they disagree, the code is right")
                if not a.no_code and not a.list and n_hit < a.code_matches and e["kind"] in DECLARED:
                    ext = os.path.splitext(full)[1].lower()
                    first, last, txt = snippet(src_lines, at, ext, a.code_lines)
                    shown_last = min(last, first + a.code_lines - 1)
                    code = [f"code ({rel(full)}:{first}-{shown_last}):", "```" + LANG.get(ext, ""), txt, "```"]
                    if last > shown_last:
                        code.append(f"... {last - shown_last} more lines to {rel(full)}:{last} (--code-lines {last - first + 1} shows all)")
                if a.find:
                    f = a.find.lower()
                    found = [(j + 1, l.strip()) for j, l in enumerate(src_lines) if f in l.lower()]
                    for j, l in found[:30]:
                        print(f"        {rel(full)}:{j}  {l[:160]}")
                    if not found:
                        print(f"        (no line contains '{a.find}')")
            else:
                print(f"   src: {sp}  (file not found under the source root)")
                if a.find:
                    print("        (source not available: --find skipped)")
        elif a.find:
            print("        (no source file for this entry: --find skipped)")
        if (not code and e["kind"] not in DECLARED and src_root and locs and not a.no_code and not a.list
                and n_hit < a.code_matches):  # call sites, errors, settings read in code: quote each cited line
            for p, ln in locs[:8]:
                sl = read_lines(os.path.join(src_root, p))
                if sl and 0 < ln <= len(sl):
                    code.append(f"   {rel(os.path.join(src_root, p))}:{ln}  {sl[ln - 1].strip()[:200]}")
            if code:
                code.insert(0, "code at the cited lines:" + (f" (first 8 of {len(locs)})" if len(locs) > 8 else ""))
        if not a.list:
            print(b)
            if code:
                print("\n".join(code))
            if n_hit == 0 and not a.no_related:
                ctx = related(e, src_root)
                if ctx:
                    print("\n".join(ctx))
            print()
    if len(hits) > a.limit:
        print(f"... {len(hits) - a.limit} more (use --limit or --kind)")
    others = len(part) + len(text)
    if exact and not a.fuzzy and others:
        print(f"({others} partial / summary match(es) not shown: add --fuzzy)")


if __name__ == "__main__":
    main()
