"""Shared helpers for the source-scanning adapters (api, errors, tests, build): config, file walk, method lookup."""
import bisect
import json
import os
import re
from collections import defaultdict

CFG = json.load(open("codebase-docs.json", encoding="utf-8"))
DOCS = CFG.get("docs_dir", "docs")
OUT = os.path.join(DOCS, "reference")
ROOT = os.environ.get("DOCS_SOURCE_ROOT") or CFG.get("source_root", ".")
SKIP = re.compile(r"(^|/)(\.git|\.vs|\.idea|bin|obj|node_modules|dist|build|out|target|vendor|packages|\.venv|venv|__pycache__|"
                  r"wwwroot/lib|coverage)(/|$)|\.min\.js$|\.designer\.cs$|\.g\.cs$", re.I)
CODE_EXT = {".cs", ".vb", ".fs", ".java", ".kt", ".scala", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".py", ".go", ".rb",
            ".php", ".rs", ".swift", ".sql"}
BACK = "[↑ Back to index](#index)"


def options(name):
    return CFG.get("adapter_options", {}).get(name, {})


def slug(*parts):
    return re.sub(r"[^a-z0-9]+", "-", "-".join(str(p) for p in parts).lower()).strip("-")


def esc(s):
    """Table-cell escape for text inside `code spans` (Markdown already escapes HTML there)."""
    return str(s).replace("|", "\\|").replace("\n", " ")


def esc_text(s):
    """Table-cell escape for prose (routes, messages, labels): `<int:id>` or `Task<T>` would otherwise be read as HTML."""
    return esc(str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def read(p):
    try:
        return open(p, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return ""


_KITS = []


def kit_dirs():
    """This skill's own output inside the source tree (the workspace, an installed docs kit): never scanned as project code."""
    if not _KITS:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        try:
            import vendor_files
            _KITS.append({d.lower() for d in vendor_files.docs_kit_dirs(ROOT)})
        except Exception:  # never fail an adapter over this
            _KITS.append(set())
    return _KITS[0]


def walk(exts=CODE_EXT, names=None, skip=None):
    """(relative path, absolute path) of source files with the given extensions (or exact / regex file names)."""
    skip = skip or SKIP
    kits = kit_dirs()
    for d, dirs, files in os.walk(ROOT):
        r = rel(d)
        r = "" if r == "." else r
        dirs[:] = [x for x in dirs if not skip.search(f"{r}/{x}".lstrip("/") + "/")
                   and f"{r}/{x}".lstrip("/").lower() not in kits]
        for f in sorted(files):
            p = f"{r}/{f}".lstrip("/")
            if skip.search(p):
                continue
            if (exts and os.path.splitext(f)[1].lower() in exts) or (names and names.search(f)):
                yield p, os.path.join(d, f)


def line_at(text, pos):
    return text.count("\n", 0, pos) + 1


def project_of(path, _cache={}):
    """Nearest folder holding a project manifest (same rule as the method map), else the top folder."""
    rx = re.compile(r"\.(csproj|vbproj|fsproj)$|^(package\.json|pyproject\.toml|setup\.py|pom\.xml|build\.gradle(\.kts)?|go\.mod|Cargo\.toml|composer\.json)$", re.I)
    probe = os.path.dirname(path)
    while True:
        if probe not in _cache:
            try:
                _cache[probe] = any(rx.search(f) for f in os.listdir(os.path.join(ROOT, probe) if probe else ROOT))
            except OSError:
                _cache[probe] = False
        if _cache[probe]:
            return probe or "."
        if not probe:
            return path.split("/")[0] if "/" in path else "."
        probe = os.path.dirname(probe)


class Methods:
    """docs/agent/methods.json (from the method map) indexed by file, to name the method enclosing a line."""

    def __init__(self):
        p = os.path.join(DOCS, "agent", "methods.json")
        self.data = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
        self.by_file = defaultdict(list)
        for a, m in self.data.items():
            if m.get("line"):
                self.by_file[m["file"]].append((m["line"], a))
        for v in self.by_file.values():
            v.sort()

    def enclosing(self, path, line):
        """Anchor of the last method declared at or above `line` in `path` (None if none)."""
        v = self.by_file.get(path)
        if not v:
            return None
        k = bisect.bisect_right(v, (line, "\uffff")) - 1
        return v[k][1] if k >= 0 else None

    def next_after(self, path, line, within=8):
        """Anchor of the first method declared within `within` lines below `line` (attribute / decorator targets)."""
        for ln, a in self.by_file.get(path, []):
            if line <= ln <= line + within:
                return a
        return None

    def link(self, a, page_prefix=""):
        if not a or a not in self.data:
            return ""
        m = self.data[a]
        return f"[{esc(m['name'])}]({page_prefix}{m.get('page', 'methods.md')}#{a})"


def cut(s, n):
    """Truncate code text to n characters with "…", and never leave an unclosed "<": MkDocs runs an HTML parser over the
    whole Markdown page, and a dangling `List<Order` or `<asp:TextBox Rows="1"` opens a tag that swallows every
    <a id> after it on the page (thousands of "does not contain an anchor" warnings)."""
    s = str(s)
    if len(s) > n:
        s = s[:n].rstrip() + "…"
    if s.rfind("<") > s.rfind(">"):
        s += " …>"
    return s


GLOBAL_FILTER = re.compile(r"(?:GlobalFilters\.Filters|\bfilters|config\.Filters|options\.Filters|o\.Filters|opts\.Filters)\s*\.\s*Add"
                           r"(?:<\s*(\w+)\s*>\s*\(|\(\s*new\s+([\w.]+))")


def global_filters():
    """[(filter class, file, line)] registered for every MVC / Web API action (GlobalFilters, FilterConfig, AddMvc options)
    plus "RequireAuthorization" when controllers are mapped with it (ASP.NET Core). They never apply to Web Forms pages."""
    out = []
    for rp, full in walk(exts={".cs", ".vb"}):
        t = read(full)
        if "Filters" not in t and "RequireAuthorization" not in t:
            continue
        for m in GLOBAL_FILTER.finditer(t):
            out.append(((m.group(1) or m.group(2)).split(".")[-1], rp, line_at(t, m.start())))
        for m in re.finditer(r"Map(?:Default)?Controller(?:Route)?s?\s*\([^;]*?\)\s*\.\s*RequireAuthorization\(", t):
            out.append(("RequireAuthorization", rp, line_at(t, m.start())))
    return out


_VENDORED = []


def vendored():
    """Relative paths of copied third-party files (scripts/vendor_files.py: configured graph.vendor_dirs, detected library
    folders, banners). URLs, environment reads and calls inside them belong to the library, not to the application."""
    if not _VENDORED:
        # each adapter is its own process: share one scan per build through docs/agent/vendored.json, reused while it is
        # newer than codebase-docs.json and less than an hour old (a build runs all adapters within minutes)
        import sys
        import time
        cache = os.path.join(DOCS, "agent", "vendored.json")
        try:
            age = time.time() - os.path.getmtime(cache)
            if age < 3600 and os.path.getmtime(cache) > os.path.getmtime("codebase-docs.json"):
                c = json.load(open(cache, encoding="utf-8"))
                if c.get("root") == os.path.abspath(ROOT):
                    _VENDORED.append(set(c["files"]))
                    return _VENDORED[0]
        except (OSError, ValueError, KeyError):
            pass
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        try:
            import vendor_files
            _VENDORED.append(set(vendor_files.scan(ROOT)))
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            json.dump({"root": os.path.abspath(ROOT), "files": sorted(_VENDORED[0])}, open(cache, "w", encoding="utf-8"))
        except Exception as e:  # never fail an adapter over this: say so and treat nothing as vendored
            print(f"note: vendor file detection unavailable ({e}); third-party files are scanned too")
            _VENDORED.append(set())
    return _VENDORED[0]


def write_page(name, lines):
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
