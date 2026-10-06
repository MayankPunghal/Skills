"""Real SQL parsing for the toolkit: `.sql` scripts and SQL embedded in C# string literals, no regular expressions.

    python <skill>/scripts/sql_parse.py --check                 # which engine is available (exit 1: none)
    python <skill>/scripts/sql_parse.py --build                 # build the ScriptDom helper now (needs the .NET SDK + nuget.org once)
    python <skill>/scripts/sql_parse.py --root DIR [--code] [--transpile] [--out facts.json]

Engines, best first:
  scriptdom  Microsoft.SqlServer.TransactSql.ScriptDom (the parser behind SSDT / sqlpackage) through the small helper in
             scripts/sqlscan, built once into a per-user cache. Full T-SQL: procedures, functions, triggers, types, cursors,
             TRY/CATCH, MERGE, OUTPUT, temp tables, dynamic SQL. Gives objects, columns, keys, reads / writes / calls
             and a construct census (what a PostgreSQL port has to handle).
  sqlglot    pure-Python parser (pip). Fallback when no .NET SDK is installed, and the PostgreSQL transpile preview
             (--transpile). Good for DML / DDL; procedural T-SQL bodies are reported as unparsed, never guessed.
SQL in C# (--code): a C# lexer (not a regex) finds string literals (regular, verbatim, interpolated, raw), joins
"a" + "b" concatenations, turns interpolation / format holes and concatenated expressions into @p placeholders
(flagged dynamic), and keeps only literals that start with a SQL keyword, parse without errors and either use a
data-access API nearby or write the keyword in one case (so UI text such as "Select an item" is not taken for SQL).

Python API (import from other scripts, migration-assessment included):
  engine()                         "scriptdom" | "sqlglot" | None
  parse(items)                     items: [{"id", "text"}] -> results in the sqlscan schema (see sqlscan/Program.cs)
  scan_files(root, skip_dirs)      every .sql file under root -> results (id = path relative to root)
  csharp_sql(text)                 SQL candidates in one C# file: [{line, end_line, text, dynamic, holes, context}]
  scan_code(root, skip_dirs)       SQL embedded in .cs files, parsed -> results (id = "path:line")
  transpile_pg(sql)                (postgres_text, ok, message) via sqlglot
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import run, tool_exe, utf8_stdout  # noqa: E402

HELPER_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sqlscan")
SKIP_DIRS = {"bin", "obj", "packages", ".vs", "node_modules", ".git", "dist", "build", "vendor", "graphify-out"}
HOLE = "\x01"                      # a run-time value or name spliced into the SQL text (interpolation, format item, + expr)
CHUNK = 1500                       # items per helper call (keeps stdin / stdout sizes sane)
MIN_DOTNET = 8
SQL_START = {"SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "EXEC", "EXECUTE", "WITH", "CREATE", "ALTER", "DROP", "TRUNCATE",
             "DECLARE", "SET", "IF", "BEGIN", "BULK", "USE", "GRANT", "SP_EXECUTESQL"}
DATA_API = {"SqlCommand", "CommandText", "ExecuteReader", "ExecuteReaderAsync", "ExecuteNonQuery", "ExecuteNonQueryAsync",
            "ExecuteScalar", "ExecuteScalarAsync", "Query", "QueryAsync", "QueryFirst", "QueryFirstAsync", "QueryFirstOrDefault",
            "QueryFirstOrDefaultAsync", "QuerySingle", "QuerySingleAsync", "QuerySingleOrDefault", "QuerySingleOrDefaultAsync",
            "QueryMultiple", "QueryMultipleAsync", "Execute", "ExecuteAsync", "FromSqlRaw", "FromSqlInterpolated", "FromSql",
            "ExecuteSqlRaw", "ExecuteSqlRawAsync", "ExecuteSqlInterpolated", "ExecuteSqlInterpolatedAsync", "ExecuteSql",
            "ExecuteSqlAsync", "SqlQuery", "SqlQueryRaw", "ExecuteSqlCommand", "ExecuteSqlCommandAsync", "ExecuteStoreQuery",
            "ExecuteStoreCommand", "CreateSQLQuery", "CreateSqlQuery", "ExecuteQuery", "ExecuteCommand", "DbCommand",
            "OleDbCommand", "OdbcCommand", "SqlDataAdapter", "DataAdapter", "CreateCommand", "SqlBulkCopy", "Database",
            "DbContext", "IDbConnection", "SqlConnection", "DbConnection", "CreateQuery"}
HQL_ONLY = {"CreateQuery"}          # NHibernate HQL / JPQL-style APIs: object queries, not SQL
SQL_ALSO = {"CreateSQLQuery", "CreateSqlQuery", "SqlCommand", "CommandText", "FromSqlRaw", "ExecuteSqlRaw", "Query", "QueryAsync",
            "Execute", "ExecuteAsync", "ExecuteReader", "ExecuteScalar", "ExecuteNonQuery"}


# ---------------------------------------------------------------- engines

def dotnet_major():
    exe = tool_exe("dotnet")
    if not exe:
        return 0
    code, out = run([exe, "--list-sdks"])
    majors = [int(l.split(".")[0]) for l in out.splitlines() if code == 0 and l[:1].isdigit()]
    return max(majors, default=0)


def _src_hash():
    h = hashlib.sha1()
    for f in ("Program.cs", "SqlScan.csproj"):
        with open(os.path.join(HELPER_SRC, f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:12]


def cache_dir():
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base or os.path.expanduser("~"), "codebase-documenter", "sqlscan", _src_hash())


def helper_dll():
    p = os.path.join(cache_dir(), "bin", "sqlscan.dll")
    return p if os.path.exists(p) else None


def build(verbose=False):
    """Build the ScriptDom helper into the per-user cache (copy of the sources, so the skill folder stays clean)."""
    if helper_dll():
        return helper_dll()
    exe = tool_exe("dotnet")
    if not exe or dotnet_major() < MIN_DOTNET:
        if verbose:
            print(f"sql_parse: .NET SDK {MIN_DOTNET}+ not found; ScriptDom engine unavailable (run install_prerequisites.py)")
        return None
    root = cache_dir()
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)
    for f in ("Program.cs", "SqlScan.csproj"):
        shutil.copy2(os.path.join(HELPER_SRC, f), os.path.join(src, f))
    if verbose:
        print(f"sql_parse: building the ScriptDom helper into {root} (first use only; restores one NuGet package) ...", flush=True)
    code, out = run([exe, "build", os.path.join(src, "SqlScan.csproj"), "-c", "Release", "-o", os.path.join(root, "bin"),
                     "--nologo", "-v", "minimal"], timeout=900, env={"DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"})
    if code or not helper_dll():
        print(f"sql_parse: helper build failed ({code}):\n{out[-1500:]}")
        return None
    parent = os.path.dirname(root)
    for old in os.listdir(parent):  # builds of earlier helper versions
        if old != os.path.basename(root):
            shutil.rmtree(os.path.join(parent, old), ignore_errors=True)
    if verbose:
        print("sql_parse: helper built.")
    return helper_dll()


def has_sqlglot():
    try:
        import sqlglot  # noqa: F401
        return True
    except ImportError:
        return False


def engine(build_if_needed=True):
    if helper_dll() or (build_if_needed and build()):
        return "scriptdom"
    return "sqlglot" if has_sqlglot() else None


# ---------------------------------------------------------------- parsing

def parse(items, prefer=None):
    """items [{"id", "text"}] -> results in the sqlscan schema. prefer="sqlglot" forces the fallback."""
    eng = prefer or engine()
    if eng == "scriptdom":
        out = []
        for i in range(0, len(items), CHUNK):
            out += _scriptdom(items[i:i + CHUNK])
        return out
    if eng == "sqlglot":
        return [_sqlglot_scan(it) for it in items]
    raise RuntimeError("no SQL parser available: run install_prerequisites.py (.NET SDK 8+ or pip sqlglot)")


def _scriptdom(items):
    import subprocess
    p = subprocess.run([tool_exe("dotnet"), helper_dll()], input=json.dumps(items), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1800)
    if p.returncode:
        raise RuntimeError(f"sqlscan failed ({p.returncode}): {p.stderr[-800:]}")
    return json.loads(p.stdout)


def _batches(text):
    """Split a script on GO separator lines (T-SQL client convention; not part of the language)."""
    cur, start, out = [], 1, []
    for n, line in enumerate(text.splitlines(), 1):
        w = line.strip().split()
        if w and w[0].upper() == "GO" and (len(w) == 1 or (len(w) == 2 and w[1].isdigit())):
            out.append((start, "\n".join(cur)))
            cur, start = [], n + 1
        else:
            cur.append(line)
    out.append((start, "\n".join(cur)))
    return [(s, b) for s, b in out if b.strip()]


def _sqlglot_scan(it):
    """Best-effort facts with sqlglot, in the sqlscan schema. Unparsed batches are reported as errors, never guessed."""
    import sqlglot
    from sqlglot import exp
    res = {"id": it.get("id"), "parser": "sqlglot " + getattr(sqlglot, "__version__", "?"), "errors": [], "objects": [],
           "script": {"reads": [], "writes": [], "calls": [], "functions": [], "temp_tables": [], "result_sets": 0,
                      "return_value": False, "dynamic_sql": False, "constructs": {}, "statements": []}}
    kinds = {"TABLE": "TABLE", "VIEW": "VIEW", "PROCEDURE": "PROCEDURE", "FUNCTION": "FUNCTION", "INDEX": "INDEX",
             "TRIGGER": "TRIGGER", "SEQUENCE": "SEQUENCE", "TYPE": "TYPE", "SCHEMA": "SCHEMA"}

    def tname(t):
        return ".".join(p for p in (t.catalog, t.db, t.name) if p)

    def facts(tree, bucket):
        targets = set()
        for node in tree.walk():
            node = node[0] if isinstance(node, tuple) else node
            if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
                t = node.this if isinstance(node.this, exp.Table) else node.find(exp.Table)
                if t is not None:
                    op = type(node).__name__.lower()
                    bucket["writes"].append({"name": tname(t), "op": op})
                    targets.add(id(t))
        for t in tree.find_all(exp.Table):
            if id(t) in targets or not t.name:
                continue
            n = tname(t)
            if n.startswith("#"):
                bucket["temp_tables"].append(n)
            elif n not in bucket["reads"]:
                bucket["reads"].append(n)
        if isinstance(tree, exp.Select):
            bucket["result_sets"] += 1
        for f in tree.find_all(exp.Anonymous):
            bucket["constructs"]["fn: " + str(f.this).upper()] = bucket["constructs"].get("fn: " + str(f.this).upper(), 0) + 1

    for start, batch in _batches(it.get("text") or ""):
        try:
            trees = sqlglot.parse(batch, read="tsql")
        except Exception as ex:  # noqa: BLE001 - sqlglot raises several error types
            res["errors"].append({"line": start, "col": 0, "message": f"sqlglot: {str(ex).splitlines()[0][:200]}"})
            continue
        for tree in trees:
            if tree is None:
                continue
            res["script"]["statements"].append(type(tree).__name__)
            if isinstance(tree, exp.Command):  # sqlglot keeps what it cannot model as raw text: say so
                res["errors"].append({"line": start, "col": 0, "message": f"sqlglot: unparsed {str(tree.this).upper()} statement"})
                continue
            if isinstance(tree, exp.Create):
                k = kinds.get(str(tree.args.get("kind") or "").upper())
                t = tree.find(exp.Table)
                o = {"kind": k or str(tree.args.get("kind")), "name": tname(t) if t is not None else "", "verb": "CREATE",
                     "line": start, "reads": [], "writes": [], "calls": [], "functions": [], "temp_tables": [],
                     "result_sets": 0, "return_value": False, "dynamic_sql": False, "constructs": {}}
                if k == "TABLE" and isinstance(tree.this, exp.Schema):
                    o["columns"] = [{"name": c.name, "type": c.args["kind"].sql("tsql") if c.args.get("kind") else None}
                                    for c in tree.this.expressions if isinstance(c, exp.ColumnDef)]
                body = tree.expression
                if body is not None:
                    facts(body, o)
                res["objects"].append(o)
            else:
                facts(tree, res["script"])
    return res


def transpile_pg(sql):
    """PostgreSQL rendering of T-SQL (preview only: review every line). (text, ok, message)."""
    if not has_sqlglot():
        return "", False, "sqlglot not installed"
    import sqlglot
    try:
        out = sqlglot.transpile(sql, read="tsql", write="postgres", unsupported_level=sqlglot.ErrorLevel.RAISE)
        return ";\n".join(out), True, ""
    except Exception as ex:  # noqa: BLE001
        return "", False, str(ex).splitlines()[0][:300]


# ---------------------------------------------------------------- files

def read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if len(raw) > 3 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        return raw.decode("utf-16-le")
    return raw.decode("utf-8-sig", errors="replace")


def walk(root, exts, skip_dirs=None):
    skip = {x.lower() for x in (set(skip_dirs or ()) | SKIP_DIRS)}
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x.lower() not in skip and not x.startswith("."))
        for f in sorted(files):
            if f.lower().endswith(exts):
                yield os.path.join(d, f)


def scan_files(root, skip_dirs=None, prefer=None):
    """Every .sql file under root. A file with a syntax error is re-parsed batch by batch (GO-separated), so one bad
    batch loses only itself; its errors stay on the result with file line numbers."""
    items = [{"id": os.path.relpath(p, root).replace("\\", "/"), "text": read_text(p)} for p in walk(root, (".sql",), skip_dirs)]
    if not items:
        return []
    res = parse(items, prefer)
    texts = {it["id"]: it["text"] for it in items}
    bad = [r for r in res if r.get("errors") and len(_batches(texts[r["id"]])) > 1]
    if bad:
        parts, where = [], {}
        for r in bad:
            for k, (start, b) in enumerate(_batches(texts[r["id"]])):
                pid = f"{r['id']}#{k}"
                parts.append({"id": pid, "text": b})
                where[pid] = (r["id"], start - 1)
        merged = {r["id"]: dict(r, objects=[], errors=[], batch_reparsed=True) for r in bad}
        scripts = {r["id"]: [] for r in bad}
        for p in parse(parts, prefer):
            fid, off = where[p["id"]]
            m = merged[fid]
            for o in p.get("objects", []):
                for key in ("line", "end_line"):
                    if isinstance(o.get(key), int):
                        o[key] += off
                o["construct_lines"] = {k: v + off for k, v in (o.get("construct_lines") or {}).items()}
                m["objects"].append(o)
            m["errors"] += [dict(e, line=e["line"] + off) for e in p.get("errors", [])]
            scripts[fid].append(p.get("script") or {})
        for fid, m in merged.items():
            m["script"] = _merge_scripts(scripts[fid])
        res = [merged.get(r["id"], r) for r in res]
    return res


def _merge_scripts(scripts):
    out = {}
    for s in scripts:
        for k, v in s.items():
            if isinstance(v, list):
                out.setdefault(k, [])
                out[k] += [x for x in v if x not in out[k]] if k != "statements" else v
            elif isinstance(v, dict):
                d = out.setdefault(k, {})
                for kk, vv in v.items():
                    d[kk] = d.get(kk, 0) + vv
            elif isinstance(v, bool):
                out[k] = out.get(k, False) or v
            elif isinstance(v, int):
                out[k] = out.get(k, 0) + v
            else:
                out.setdefault(k, v)
    return out


# ---------------------------------------------------------------- C# lexer

def _read_string(s, i):
    """Lex one C# string literal starting at s[i] (prefix included). Returns (end, value, holes) or None if s[i] starts none.
    value has interpolation holes and format items replaced by @p; holes counts them."""
    n = len(s)
    j, dollars, verbatim = i, 0, False
    while j < n and s[j] in "$@":
        if s[j] == "$":
            dollars += 1
        else:
            verbatim = True
        j += 1
    if j >= n or s[j] != '"' or j - i > 4:
        return None
    if s.startswith('"""', j):  # raw string literal (C# 11): """ ... """ with as many quotes as it opened with
        q = j
        while q < n and s[q] == '"':
            q += 1
        quotes = q - j
        close = s.find('"' * quotes, q)
        if close < 0:
            return n, s[q:], 0
        body = s[q:close]
        lines = body.split("\n")
        if len(lines) > 1 and not lines[0].strip():
            lines = lines[1:]
        if len(lines) > 1 and not lines[-1].strip():
            lines = lines[:-1]
        body = "\n".join(lines)
        value, holes = (_fill_holes(body, dollars, raw=True) if dollars else (body, 0))
        return close + quotes, value, holes
    k = j + 1
    out, holes = [], 0
    while k < n:
        c = s[k]
        if c == '"':
            if verbatim and k + 1 < n and s[k + 1] == '"':
                out.append('"')
                k += 2
                continue
            k += 1
            break
        if c == "\\" and not verbatim:
            nxt = s[k + 1] if k + 1 < n else ""
            out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'", "0": " "}.get(nxt, " "))
            k += 2
            continue
        if c == "\n" and not verbatim:
            break
        if dollars and c == "{":
            if k + 1 < n and s[k + 1] == "{":
                out.append("{")
                k += 2
                continue
            k = _skip_hole(s, k + 1)
            out.append(HOLE)
            holes += 1
            continue
        if dollars and c == "}" and k + 1 < n and s[k + 1] == "}":
            out.append("}")
            k += 2
            continue
        out.append(c)
        k += 1
    value = "".join(out)
    if not dollars:
        value, fh = _format_items(value)
        holes += fh
    return k, value, holes


def _skip_hole(s, k):
    """Index just after the } that closes an interpolation hole opened before s[k] (nested braces / strings / chars)."""
    depth, n = 1, len(s)
    while k < n and depth:
        c = s[k]
        if c in "$@\"":
            r = _read_string(s, k)
            if r:
                k = r[0]
                continue
        if c == "'":
            k = _skip_char(s, k)
            continue
        depth += 1 if c == "{" else -1 if c == "}" else 0
        k += 1
    return k


def _fill_holes(body, dollars, raw):
    """Raw interpolated strings: holes open with `dollars` braces."""
    opn, out, k, holes, n = "{" * dollars, [], 0, 0, len(body)
    while k < n:
        if body.startswith(opn, k) and not body.startswith(opn + "{", k):
            k = _skip_hole(body, k + dollars)
            out.append(HOLE)
            holes += 1
            continue
        out.append(body[k])
        k += 1
    return "".join(out), holes


def _format_items(v):
    """string.Format items {0} / {1,10:N2} -> @p (they are always values or names spliced in at run time)."""
    out, k, holes, n = [], 0, 0, len(v)
    while k < n:
        if v[k] == "{" and k + 1 < n and v[k + 1].isdigit():
            e = v.find("}", k)
            inner = v[k + 1:e] if e > 0 else ""
            if e > 0 and inner.split(",")[0].split(":")[0].strip().isdigit():
                out.append(HOLE)
                holes += 1
                k = e + 1
                continue
        out.append(v[k])
        k += 1
    return "".join(out), holes


def _skip_char(s, k):
    n = len(s)
    j = k + 1
    while j < n and s[j] != "'" and s[j] != "\n":
        j += 2 if s[j] == "\\" else 1
    return j + 1


def _tokens(s):
    """Coarse C# token stream: ('str', value, line, end_line, holes), ('id', name, line), ('op', ch, line)."""
    toks, i, n, line = [], 0, len(s), 1
    while i < n:
        c = s[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in " \t\r\f\v":
            i += 1
        elif c == "/" and s.startswith("//", i):
            e = s.find("\n", i)
            i = n if e < 0 else e
        elif c == "/" and s.startswith("/*", i):
            e = s.find("*/", i + 2)
            e = n if e < 0 else e + 2
            line += s.count("\n", i, e)
            i = e
        elif c in "$@\"":
            r = _read_string(s, i)
            if r:
                e, value, holes = r
                end_line = line + s.count("\n", i, e)
                toks.append(("str", value, line, end_line, holes))
                line, i = end_line, e
            elif c == "@":  # verbatim identifier @class
                j = i + 1
                while j < n and (s[j].isalnum() or s[j] == "_"):
                    j += 1
                toks.append(("id", s[i + 1:j], line))
                i = j
            else:
                toks.append(("op", c, line))
                i += 1
        elif c == "'":
            i = _skip_char(s, i)
        elif c.isalpha() or c == "_":
            j = i + 1
            while j < n and (s[j].isalnum() or s[j] == "_"):
                j += 1
            toks.append(("id", s[i:j], line))
            i = j
        elif c == "#" and not s[s.rfind("\n", 0, i) + 1:i].strip():
            e = s.find("\n", i)  # preprocessor directive
            i = n if e < 0 else e
        else:
            toks.append(("op", c, line))
            i += 1
    return toks


def csharp_literals(text):
    """Every complete C# string literal (no run-time holes): [(line, value)]. Used to find database object NAMES passed
    to the data-access layer (CommandType.StoredProcedure, TVP type names, EF mappings), which are not SQL statements."""
    return [(t[2], t[1]) for t in _tokens(text) if t[0] == "str" and not t[4] and 2 < len(t[1]) < 130]


def csharp_sql(text):
    """SQL candidates in one C# source: string literals (concatenations joined) whose first word is a SQL keyword.
    context = data-access identifiers seen within the surrounding statement window (empty: probably not SQL)."""
    toks = _tokens(text)
    out, i, n = [], 0, len(toks)
    stop = {";", ",", ")", "}", "]", "=", "?", ":"}
    while i < n:
        t = toks[i]
        if t[0] != "str":
            i += 1
            continue
        parts, holes, dynamic, line, end_line = [t[1]], t[4], t[4] > 0, t[2], t[3]
        j = i + 1
        while j < n and toks[j][:2] == ("op", "+"):
            j += 1
            if j < n and toks[j][0] == "str":
                parts.append(toks[j][1])
                holes += toks[j][4]
                dynamic = dynamic or toks[j][4] > 0
                end_line = toks[j][3]
                j += 1
                continue
            depth = 0  # a non-literal operand: skip to the next + / end of expression at this depth
            while j < n:
                k, v = toks[j][0], toks[j][1]
                if k == "op" and v in "([{":
                    depth += 1
                elif k == "op" and v in ")]}":
                    if depth == 0:
                        break
                    depth -= 1
                elif k == "op" and depth == 0 and (v == "+" or v in stop):
                    break
                j += 1
            parts.append(" " + HOLE + " ")
            holes += 1
            dynamic = True
        sql = "".join(parts)
        i = j
        words = sql.replace("(", " ").replace(";", " ").split()
        if not words or words[0].upper() not in SQL_START or len(sql) < 8:
            continue
        lo = max(0, i - 120)
        ctx = sorted({toks[k][1] for k in range(lo, min(n, j + 40)) if toks[k][0] == "id" and toks[k][1] in DATA_API})
        out.append({"line": line, "end_line": end_line, "text": sql, "dynamic": dynamic, "holes": holes, "context": ctx,
                    "keyword_case": "upper" if words[0].isupper() else "lower" if words[0].islower() else "mixed"})
    return out


def scan_code(root, skip_dirs=None, prefer=None, exts=(".cs",)):
    """Parse SQL embedded in C#. Returns (accepted results, stats). Each result carries `file`, `line`, `dynamic`,
    `context` besides the sqlscan fields; rejected candidates are counted in stats, never reported as SQL."""
    cands, stats = [], {"files": 0, "candidates": 0, "accepted": 0, "parse_errors": 0, "no_context": 0}
    for p in walk(root, exts, skip_dirs):
        r = os.path.relpath(p, root).replace("\\", "/")
        if r.lower().endswith((".designer.cs", ".g.cs", ".generated.cs")):
            continue
        txt = read_text(p)
        stats["files"] += 1
        low = txt.lower()
        if not any(k in low for k in ("select", "insert", "update", "delete", "exec", "merge", "create ", "truncate")):
            continue
        for c in csharp_sql(txt):
            cands.append(dict(c, id=f"{r}:{c['line']}", file=r))
    stats["candidates"] = len(cands)
    if not cands:
        return [], stats
    by_id = {c["id"]: c for c in cands}
    best, pending = {}, list(cands)
    for k, variant in enumerate(VARIANTS):  # cheapest reading first; retry only what failed
        if not pending:
            break
        results = parse([{"id": c["id"], "text": variant(c["text"])} for c in pending], prefer)
        failed = []
        for res in results:
            c = by_id.get(res.get("id"))
            if not c or res.get("fatal"):
                continue
            ok = not res.get("errors") and (res.get("script", {}).get("statements") or res.get("objects"))
            if ok:
                best[c["id"]] = (res, variant(c["text"]), k)
            else:
                failed.append(c)
        pending = [c for c in failed if c["holes"] or k == 0]
    accepted = []
    for c in cands:
        if c["id"] not in best:
            stats["parse_errors"] += 1
            continue
        if not c["context"] and c["keyword_case"] == "mixed":
            stats["no_context"] += 1
            continue
        if set(c["context"]) & HQL_ONLY and not set(c["context"]) & SQL_ALSO:
            stats["hql"] = stats.get("hql", 0) + 1
            continue
        res, sql, k = best[c["id"]]
        accepted.append(dict(res, file=c["file"], line=c["line"], end_line=c["end_line"], dynamic=c["dynamic"],
                             holes=c["holes"], context=c["context"], sql=sql, reading=VARIANT_NAMES[k]))
    stats["accepted"] = len(accepted)
    return accepted, stats


def _fix_params(sql):
    """Client-side parameter styles ScriptDom does not know: :name (NHibernate, Oracle-style) and Dapper's IN @list."""
    out, i, n, quote = [], 0, len(sql), False
    while i < n:
        c = sql[i]
        if c == "'":
            quote = not quote
        if not quote and c == ":" and i + 1 < n and (sql[i + 1].isalpha() or sql[i + 1] == "_") and (i == 0 or sql[i - 1] in " \t\r\n(,=<>"):
            out.append("@")
            i += 1
            continue
        out.append(c)
        i += 1
    words = "".join(out).split(" ")
    for k in range(len(words) - 1):
        if words[k].upper() == "IN" and words[k + 1].startswith("@"):
            w = words[k + 1]
            j = 1
            while j < len(w) and (w[j].isalnum() or w[j] == "_"):
                j += 1
            words[k + 1] = "(" + w[:j] + ")" + w[j:]
    return " ".join(words)


def _contextual_holes(sql):
    """Each hole read by the word before it: a predicate after WHERE / AND / ON, a name after FROM / JOIN / INTO,
    nothing when it stands alone between statements (a spliced-in SQL constant), otherwise a value."""
    parts = sql.split(HOLE)
    out = [parts[0]]
    for k in range(1, len(parts)):
        before, after = "".join(out).rstrip(), parts[k].lstrip()
        prev = (before.replace("(", " ").split() or [""])[-1].upper()
        if (not before or before.endswith(";")) and (not after or after.startswith(";")):
            fill = ""
        elif prev in ("WHERE", "AND", "OR", "ON", "HAVING", "NOT", "WHEN"):
            fill = "1 = 1"
        elif prev in ("FROM", "JOIN", "INTO", "UPDATE", "TABLE", "EXEC", "EXECUTE", "BY", "MERGE", "USING"):
            fill = "dyn_p"
        else:
            fill = "@p"
        out.append(" " + fill + " " + parts[k])
    return "".join(out)


# readings of a literal, tried in order: holes as values, as names (dynamic column / table), as nothing (optional clause)
VARIANTS = [lambda s: s.replace(HOLE, "@p"),
            lambda s: _fix_params(s.replace(HOLE, "@p")),
            lambda s: _fix_params(s.replace(HOLE, "dyn_p")),
            lambda s: _fix_params(s.replace(HOLE, "")),
            lambda s: _fix_params(_contextual_holes(s))]
VARIANT_NAMES = ["as written", "parameter style normalised", "dynamic name", "dynamic clause", "contextual holes"]


# ---------------------------------------------------------------- CLI

def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report the available engine; exit 1 if none")
    ap.add_argument("--build", action="store_true", help="build the ScriptDom helper now")
    ap.add_argument("--root", help="folder to scan (.sql files; with --code also SQL in C#)")
    ap.add_argument("--code", action="store_true", help="also parse SQL embedded in C# string literals")
    ap.add_argument("--engine", choices=["scriptdom", "sqlglot"], help="force an engine")
    ap.add_argument("--transpile", action="store_true", help="add a PostgreSQL preview (sqlglot) per object / script")
    ap.add_argument("--out", help="write JSON here (default: summary to stdout only)")
    a = ap.parse_args()
    if a.check or a.build:
        dm = dotnet_major()
        print(f".NET SDK: {dm or 'not found'}" + (f" (need {MIN_DOTNET}+)" if dm and dm < MIN_DOTNET else ""))
        print(f"sqlglot: {'installed' if has_sqlglot() else 'not installed'}")
        dll = build(verbose=True) if a.build else helper_dll()
        print(f"ScriptDom helper: {dll or 'not built yet (built on first use, or run --build)'}")
        eng = "scriptdom" if dll else ("scriptdom (after build)" if dm >= MIN_DOTNET else "sqlglot" if has_sqlglot() else None)
        print(f"ENGINE: {eng or 'NONE: run install_prerequisites.py'}")
        sys.exit(0 if eng else 1)
    if not a.root:
        ap.error("--root, --check or --build is required")
    import time
    t = time.time()
    eng = a.engine or engine()
    files = scan_files(a.root, prefer=eng)
    code, stats = scan_code(a.root, prefer=eng) if a.code else ([], {})
    if a.transpile:
        texts = {}
        for r in files:
            texts[r["id"]] = read_text(os.path.join(a.root, r["id"]))
        for r in files:
            pg, ok, msg = transpile_pg(texts[r["id"]])
            r["postgres_preview"] = {"ok": ok, "text": pg if ok else "", "message": msg}
        for r in code:
            pg, ok, msg = transpile_pg(r["sql"])
            r["postgres_preview"] = {"ok": ok, "text": pg if ok else "", "message": msg}
    objs = sum(len(r.get("objects", [])) for r in files)
    errs = sum(1 for r in files if r.get("errors"))
    print(f"sql_parse [{eng}]: {len(files)} .sql files, {objs} objects, {errs} files with parse errors"
          + (f"; C#: {stats['files']} files, {stats['candidates']} SQL-looking literals, {stats['accepted']} parsed as SQL "
             f"({stats['parse_errors']} did not parse, {stats['no_context']} rejected as UI text)" if a.code else "")
          + f" in {time.time() - t:.1f}s")
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"engine": eng, "files": files, "code": code, "code_stats": stats}, fh, ensure_ascii=False, indent=1)
        print(f"written {a.out}")


if __name__ == "__main__":
    main()
