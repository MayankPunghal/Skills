"""Database object inventory and SQL-dialect footprint (input to the PostgreSQL / dual-database scenarios).

Called by scan_repo.py; results go to assessment/scan/<repo>.json -> "db_inventory". SQL is PARSED, not pattern-matched:
codebase-documenter's sql_parse.py runs Microsoft's T-SQL parser (ScriptDom, needs the .NET SDK) or sqlglot as fallback.
  objects     every CREATE / ALTER of TABLE, VIEW, PROCEDURE, FUNCTION, TRIGGER, TYPE, SEQUENCE, SYNONYM, INDEX in .sql
              files: file:line, length, parameters, tables read / written, procedures called, functions used, temp
              tables, dynamic SQL, and the construct census with each construct's PostgreSQL conversion level
  code_sql    SQL embedded in C# string literals (concatenations joined, interpolation holes marked dynamic), parsed the
              same way: tables read / written, procedures called, constructs, conversion levels
  conversion  construct occurrences by level (auto / rewrite / redesign, data/pg_conversion.json) and every "redesign"
              item (no PostgreSQL equivalent) with its location and the replacement approach
  code        data-access API footprint in C# / VB (SqlClient, Dapper, EF6, stored-procedure call styles) plus the parsed
              embedded-SQL counts the estimate prices
  parse_errors  syntax errors the parser reported (the object is still inventoried from the batches that parsed)
"""
import json
import os
import re
import sys
from collections import Counter

from _common import SOURCE_DIR_SKIP, documenter_dir, read_text

def _pg_table():
    """SQL Server -> PostgreSQL conversion knowledge, shared with codebase-documenter (one copy: its scripts/data)."""
    for d in (documenter_dir(), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        p = os.path.join(d or "", "scripts", "data", "pg_conversion.json")
        if d and os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
    return {"constructs": {}, "functions": {}, "globals": {}, "data_types": {}, "prefix_defaults": {},
            "default": {"level": "rewrite", "pg": "review for PostgreSQL", "hours": [0.05, 0.2]}}


PG = _pg_table()
ROUTINES = ("PROCEDURE", "FUNCTION", "TRIGGER", "VIEW")
# C# / VB data-access APIs (application code, not SQL): what changes when the provider becomes Npgsql
CODE = {
    "stored_procedure_calls": r"CommandType\.StoredProcedure|\.ExecuteSqlCommand(Async)?\s*\(|\bDatabase\.SqlQuery\s*<|\.SqlQuery\s*<|\.FromSql(Raw|Interpolated)?\s*\(|\bExecuteFunction\s*\(",
    "sqlclient_usage": r"\bnew\s+Sql(Connection|Command|DataAdapter|Parameter)\b|\bSqlDbType\.",
    "dapper_calls": r"\.(Query|QueryFirst|QueryFirstOrDefault|QuerySingle|QueryMultiple|Execute|ExecuteScalar)(Async)?\s*(<[^>]+>)?\s*\(\s*(@?\"|sql\b|query\b)",
    "ef6_contexts": r":\s*(System\.Data\.Entity\.)?DbContext\b|:\s*ObjectContext\b",
}
CODE_RX = {k: re.compile(v, re.I) for k, v in CODE.items()}


def sql_parser():
    """codebase-documenter's sql_parse module, or None (prerequisites missing)."""
    d = documenter_dir()
    if not d:
        return None
    sp = os.path.join(d, "scripts")
    if sp not in sys.path:
        sys.path.insert(0, sp)
    try:
        import sql_parse
        return sql_parse
    except ImportError:
        return None


def conversion(label):
    """PostgreSQL conversion entry for a parser construct label: {level, pg, hours}."""
    if label in PG["constructs"]:
        return PG["constructs"][label]
    for prefix, table in (("fn: ", "functions"), ("global: ", "globals"), ("data type: ", "data_types")):
        if label.startswith(prefix):
            key = label[len(prefix):]
            return PG[table].get(key) or PG[table].get(key.upper()) or PG["prefix_defaults"].get(prefix) or PG["default"]
    return PG["default"]


def _slim(o, file):
    keep = ("kind", "name", "verb", "line", "end_line", "params", "returns", "on_object", "trigger_type", "trigger_events",
            "reads", "writes", "calls", "functions", "temp_tables", "result_sets", "return_value", "dynamic_sql", "clr", "temporal",
            "memory_optimized", "graph", "foreign_keys", "primary_key")
    out = {k: o[k] for k in keep if o.get(k) not in (None, [], {}, False, "")}
    out["file"] = file
    out["lines"] = o.get("lines") or 1
    if o.get("columns"):
        out["columns"] = len(o["columns"])
        out["column_types"] = sorted({(c.get("type") or "").split("(")[0].strip().lower() for c in o["columns"] if c.get("type")})
    out["constructs"] = dict(o.get("constructs") or {})
    return out


def inventory(root, skip_dirs=()):
    skip = sorted(SOURCE_DIR_SKIP | {s.lower() for s in skip_dirs})
    sp = sql_parser()
    eng = sp.engine() if sp else None
    res = {"engine": eng, "objects": [], "code_sql": [], "parse_errors": [], "kinds": {}, "routine_sizes": {}, "constructs": {},
           "code_constructs": {}, "conversion": {}, "redesign_items": [], "sql_lines": 0, "code": {}, "code_files": {},
           "edmx_function_imports": 0, "code_sql_stats": {}}
    if not eng:
        res["note"] = ("SQL not analysed: no SQL parser available (codebase-documenter missing, or neither the .NET SDK 8+ nor "
                       "sqlglot is installed). Run codebase-documenter install_prerequisites.py and rescan.")
        print("WARN db inventory: " + res["note"])
    else:
        for r in sp.scan_files(root, skip):
            if r.get("fatal"):
                res["parse_errors"].append({"file": r["id"], "line": 0, "message": r["fatal"]})
                continue
            res["parse_errors"] += [{"file": r["id"], "line": e["line"], "message": e["message"]} for e in r.get("errors", [])[:5]]
            for o in r.get("objects", []):
                if o.get("name", "").split(".")[-1].startswith(("#", "@")):
                    continue
                res["objects"].append(_slim(o, r["id"]))
        # ALTER TABLE ... ADD (keys, columns) belongs to the table it changes: one object, constructs merged
        tables = {o["name"].lower(): o for o in res["objects"] if o["kind"] == "TABLE" and str(o.get("verb", "")).lower().startswith("create")}
        kept = []
        for o in res["objects"]:
            t = tables.get(o["name"].lower()) if o["kind"] == "TABLE" and str(o.get("verb", "")).lower() == "alter" else None
            if t is not None:
                for k, v in o["constructs"].items():
                    t["constructs"][k] = t["constructs"].get(k, 0) + v
                t["foreign_keys"] = (t.get("foreign_keys") or []) + (o.get("foreign_keys") or [])
                continue
            kept.append(o)
        res["objects"] = kept
        code_sql, stats = sp.scan_code(root, skip)
        res["code_sql_stats"] = stats
        for s in code_sql:
            sc = s.get("script") or {}
            cons = dict(sc.get("constructs") or {})
            for o in s.get("objects", []):  # DDL in code (EF migrations, installers): count its constructs too
                for k, v in (o.get("constructs") or {}).items():
                    cons[k] = cons.get(k, 0) + v
            res["code_sql"].append({"file": s["file"], "line": s["line"], "reads": sc.get("reads", []), "writes": sc.get("writes", []),
                                    "calls": sc.get("calls", []), "functions": sc.get("functions", []), "dynamic": s.get("dynamic", False),
                                    "dynamic_sql": sc.get("dynamic_sql", False), "statements": sc.get("statements", []),
                                    "objects": [{"kind": o.get("kind"), "name": o.get("name")} for o in s.get("objects", [])],
                                    "constructs": cons, "context": s.get("context", [])})
    # object NAMES passed as whole C# string literals (CommandType.StoredProcedure, TVP type names, name constants)
    res["name_sites"] = []
    if eng and res["objects"]:
        full = {o["name"].lower(): o for o in res["objects"]}
        shorts = {}
        for o in res["objects"]:
            shorts.setdefault(o["name"].split(".")[-1].lower(), []).append(o)
        for path in sp.walk(root, (".cs",), skip):
            rp = os.path.relpath(path, root).replace("\\", "/")
            for line, value in sp.csharp_literals(read_text(path)):
                v = value.strip().replace("[", "").replace("]", "")
                if not v or " " in v:
                    continue
                o = full.get(v.lower()) or full.get("dbo." + v.lower())
                if not o and "." not in v and len(shorts.get(v.lower(), [])) == 1:
                    o = shorts[v.lower()][0]
                if o and (o["kind"] != "TABLE" or "." in v):  # a bare word such as "Orders" is too often UI text
                    res["name_sites"].append({"file": rp, "line": line, "object": o["name"]})
    # data-access API usage in application code
    code, code_files = Counter(), Counter()
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x.lower() not in skip and not x.startswith(".")]
        for fn in files:
            p = os.path.join(d, fn)
            low = fn.lower()
            try:
                if low.endswith((".cs", ".vb")) and os.path.getsize(p) < 2_000_000:
                    text = read_text(p)
                    for k, rx in CODE_RX.items():
                        n = len(rx.findall(text))
                        if n:
                            code[k] += n
                            code_files[k] += 1
                elif low.endswith(".edmx"):
                    res["edmx_function_imports"] += read_text(p).count("<FunctionImport")
            except OSError:
                continue
    # conversion levels: database objects and embedded SQL
    levels, levels_code, cons_total, cons_code = Counter(), Counter(), Counter(), Counter()
    for where, items in (("database", res["objects"]), ("code", res["code_sql"])):
        for o in items:
            (cons_total if where == "database" else cons_code).update(o["constructs"])
            lv = Counter()
            for k, n in o["constructs"].items():
                c = conversion(k)
                lv[c["level"]] += n
                if c["level"] == "redesign":
                    res["redesign_items"].append({"where": where, "object": o.get("name", ""), "kind": o.get("kind", "embedded SQL"),
                                                  "file": o["file"], "line": o.get("line", 0), "construct": k, "count": n, "pg": c["pg"]})
            o["conversion"] = dict(lv)
            (levels if where == "database" else levels_code).update(lv)
    code["inline_sql_strings"] = len(res["code_sql"])
    code["tsql_in_strings"] = sum(1 for s in res["code_sql"] if s["conversion"].get("rewrite") or s["conversion"].get("redesign"))
    code["dynamic_sql_in_code"] = sum(1 for s in res["code_sql"] if s["dynamic"] or s["dynamic_sql"])
    code_files["inline_sql_strings"] = len({s["file"] for s in res["code_sql"]})
    res["kinds"] = dict(Counter(o["kind"] for o in res["objects"]))
    res["routine_sizes"] = dict(Counter("small" if o["lines"] <= 50 else ("medium" if o["lines"] <= 200 else "large")
                                        for o in res["objects"] if o["kind"] in ROUTINES))
    res["constructs"] = dict(cons_total)
    res["code_constructs"] = dict(cons_code)
    res["conversion"] = {"database": dict(levels), "code": dict(levels_code)}
    res["sql_lines"] = sum(o["lines"] for o in res["objects"])
    res["code"] = {k: v for k, v in code.items() if v}
    res["code_files"] = dict(code_files)
    return res
