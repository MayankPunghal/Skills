"""Where a finding comes from: repository, project, file and line, for the workbook sheets.

Everything is read from the repository checkout named in the inventory (read only) and from the scan and config outputs.
Functions return "file:line" strings (file relative to the repository root, forward slashes). A place is never guessed:
when a needle is not found the result is empty."""
import os
import re

from _common import skip_dir, OUT, SOURCE_DIR_SKIP, read_json

TEXT_EXT = (".config", ".json", ".cs", ".vb", ".xml", ".settings", ".ini", ".cshtml", ".aspx", ".asmx", ".ashx", ".asax", ".svc", ".csproj", ".vbproj", ".props", ".targets", ".yml", ".yaml", ".txt")
MAX_BYTES = 1_000_000
_cache = {"repo": None, "lines": {}}
_inv, _conf = {}, {}


def root_of(repo):
    if repo not in _inv:
        _inv[repo] = (read_json(os.path.join(OUT, "inventory", repo + ".json"), {}) or {}).get("root") or ""
    return _inv[repo]


def conf_rows(repo):
    if repo not in _conf:
        _conf[repo] = (read_json(os.path.join(OUT, "config", repo + ".json"), {}) or {}).get("rows") or []
    return _conf[repo]


def _norm(p):
    return (p or "").replace("\\", "/")


def lines_of(repo, rel):
    """Lines of one file of the repository (cached for the repository being worked on)."""
    if _cache["repo"] != repo:
        _cache.update(repo=repo, lines={})
    rel = _norm(rel)
    if rel not in _cache["lines"]:
        path = os.path.join(root_of(repo), rel)
        try:
            ok = os.path.isfile(path) and os.path.getsize(path) <= MAX_BYTES
            _cache["lines"][rel] = open(path, encoding="utf-8-sig", errors="replace").read().split("\n") if ok else []
        except OSError:
            _cache["lines"][rel] = []
    return _cache["lines"][rel]


def line_in(repo, rel, needle):
    """First line of the file that holds the needle (case-insensitive): returns 'file:line' or ''."""
    n = needle.lower()
    for i, l in enumerate(lines_of(repo, rel), 1):
        if n in l.lower():
            return f"{_norm(rel)}:{i}"
    return ""


def project_dir(p):
    return _norm(os.path.dirname(_norm(p["path"])))


def project_of(sol, rel):
    """Project of the solution that holds the file (the deepest project folder that contains it)."""
    rel = _norm(rel).lower()
    best = None
    for p in sol["projects"]:
        d = project_dir(p).lower()
        if (rel.startswith(d + "/") if d else True) and (best is None or len(d) > len(project_dir(best))):
            best = p
    return best["name"] if best else ""


def walk_files(repo, folders):
    """Text files below the project folders (relative paths), skipping build output and packages."""
    root = root_of(repo)
    seen = set()
    for f in folders:
        base = os.path.join(root, f) if f else root
        for d, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if not skip_dir(d, x, SOURCE_DIR_SKIP)]
            for name in files:
                if name.lower().endswith(TEXT_EXT):
                    rel = _norm(os.path.relpath(os.path.join(d, name), root))
                    if rel not in seen:
                        seen.add(rel)
                        yield rel


def find_in_projects(sol, needle, limit=3):
    """[(project name, 'file:line')] for the first file of each project of the solution that holds the needle."""
    repo = sol["repo"]
    found = []
    for p in sol["projects"]:
        for rel in walk_files(repo, [project_dir(p)]):
            w = line_in(repo, rel, needle)
            if w:
                found.append((p["name"], w))
                break
        if len(found) >= limit:
            break
    return found


def package_where(sol, pkg_id, project_names=None):
    """[(project, 'file:line', version)] of the project file or packages.config that references the package."""
    repo = sol["repo"]
    out = []
    for p in sol["projects"]:
        if project_names is not None and not ({p["name"].lower(), os.path.basename(p["path"]).lower(), _norm(p["path"]).lower()} & project_names):
            continue
        d = project_dir(p)
        for rel in (_norm(p["path"]), (d + "/" if d else "") + "packages.config"):
            hit = None
            for i, l in enumerate(lines_of(repo, rel), 1):
                if re.search(r'(?:Include|id)\s*=\s*"%s"' % re.escape(pkg_id), l, re.I):
                    v = re.search(r'[Vv]ersion\s*=\s*"([^"]+)"', l) or re.search(r"<Version>([^<]+)</Version>", "".join(lines_of(repo, rel)[i:i + 3]))
                    hit = (p["name"], f"{rel}:{i}", v.group(1) if v else "")
                    break
            if hit:
                out.append(hit)
                break
    return out


def config_where(repo, target, projects=None):
    """['file:line'] of the config rows whose target (host or address) is the given one, for the given projects when named."""
    t = (target or "").lower()
    ps = {x.lower() for x in projects} if projects else None
    return list(dict.fromkeys(f"{_norm(r['file'])}:{r['line']}" for r in conf_rows(repo)
                              if (r.get("target") or "").lower() == t and r.get("line") and (ps is None or (r.get("project") or "").lower() in ps)))


def evidence_file(text):
    """The file named in a third-party evidence part such as 'call to host in Project/File.cs'."""
    m = re.match(r"call to \S+ in (.+)$", text.strip())
    return _norm(m.group(1)) if m else ""


def cap(items, n=4):
    """Lines for one cell: the first n distinct items, then a count of the rest."""
    items = list(dict.fromkeys(i for i in items if i))
    return "\n".join(items[:n]) + (f"\n(+{len(items) - n} more)" if len(items) > n else "")


def drop_empty(rows, keep=()):
    """Remove the columns whose every data row is empty (header names in keep stay). Rows[0] is the header."""
    if len(rows) < 2:
        return rows
    used = [i for i, h in enumerate(rows[0]) if h in keep or any(str(r[i]).strip() not in ("", "None") for r in rows[1:] if i < len(r) and r[i] is not None)]
    return [[r[i] if i < len(r) else "" for i in used] for r in rows]


ENV_VAR = re.compile(r'GetEnvironmentVariable\(\s*"([A-Za-z0-9_.]+)"')


def env_var_places(sol):
    """{variable name: [(project, 'file:line')]} for GetEnvironmentVariable("NAME") calls in the solution's projects."""
    repo = sol["repo"]
    out = {}
    for p in sol["projects"]:
        for rel in walk_files(repo, [project_dir(p)]):
            if not rel.lower().endswith((".cs", ".vb", ".cshtml", ".aspx", ".ashx", ".asmx", ".asax", ".svc")):
                continue
            for i, l in enumerate(lines_of(repo, rel), 1):
                for m in ENV_VAR.finditer(l):
                    out.setdefault(m.group(1), []).append((p["name"], f"{rel}:{i}"))
    return out


def config_lines(repo, rel):
    """['file:line'] of the config rows in a file (the hard-coded addresses, paths and credentials the scan found there)."""
    return list(dict.fromkeys(f"{_norm(r['file'])}:{r['line']}" for r in conf_rows(repo) if _norm(r["file"]) == _norm(rel) and r.get("line")))
