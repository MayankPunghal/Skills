"""Database object inventory and SQL-dialect footprint (input to the PostgreSQL / dual-database scenarios).

Called by scan_repo.py; results go to assessment/scan/<repo>.json -> "db_inventory":
  objects   every CREATE [OR ALTER] TABLE / VIEW / PROCEDURE / FUNCTION / TRIGGER / TYPE / SEQUENCE / SYNONYM in .sql files,
            with file:line, length in lines and the T-SQL constructs that need rework for PostgreSQL
  code      data-access footprint in C#/VB: stored-procedure call sites, inline SQL strings, T-SQL-specific syntax in
            those strings, SqlClient usage, EF6 / EDMX / EF Core usage, Dapper
"""
import os
import re
from collections import Counter

from _common import SOURCE_DIR_SKIP, read_text, rel

CREATE = re.compile(r"(?im)^\s*CREATE\s+(?:OR\s+ALTER\s+)?(TABLE|VIEW|PROCEDURE|PROC|FUNCTION|TRIGGER|TYPE|SEQUENCE|SYNONYM)\s+((?:\[?[\w$#@]+\]?\.)?\[?[\w$#@]+\]?)")
CONSTRUCTS = {
    "cursor": r"\bDECLARE\s+\w+\s+CURSOR\b|\bFETCH\s+NEXT\b",
    "temp table": r"#[A-Za-z_]\w*",
    "table variable": r"\bDECLARE\s+@\w+\s+TABLE\b",
    "dynamic SQL": r"\bsp_executesql\b|\bEXEC(UTE)?\s*\(\s*@",
    "TRY/CATCH": r"\bBEGIN\s+TRY\b",
    "MERGE": r"(?m)^\s*MERGE\b",
    "OUTPUT clause": r"\bOUTPUT\s+(INSERTED|DELETED)\.",
    "APPLY": r"\b(CROSS|OUTER)\s+APPLY\b",
    "PIVOT": r"\b(UN)?PIVOT\s*\(",
    "XML": r"\bFOR\s+XML\b|\bOPENXML\b|\.nodes\s*\(|\bxml\b",
    "identity functions": r"@@IDENTITY|\bSCOPE_IDENTITY\s*\(|\bIDENT_CURRENT\b",
    "TOP": r"\bTOP\s*\(?\s*\d+|\bTOP\s*\(\s*@",
    "table hints": r"\bWITH\s*\(\s*NOLOCK\b|\(\s*NOLOCK\s*\)",
    "RAISERROR/THROW": r"\bRAISERROR\b|\bTHROW\b",
    "string/date functions": r"\b(ISNULL|CHARINDEX|DATEADD|DATEDIFF|GETDATE|CONVERT|LEN|STUFF|PATINDEX|NEWID)\s*\(",
    "transactions": r"\bBEGIN\s+TRAN(SACTION)?\b",
}
CONSTRUCT_RX = {k: re.compile(v, re.I) for k, v in CONSTRUCTS.items()}
CODE = {
    "stored_procedure_calls": r"CommandType\.StoredProcedure|\.ExecuteSqlCommand(Async)?\s*\(|\bDatabase\.SqlQuery\s*<|\.SqlQuery\s*<|\.FromSql(Raw|Interpolated)?\s*\(|\bExecuteFunction\s*\(",
    "inline_sql_strings": r"\"\s*(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|EXEC|EXECUTE|WITH)\s",
    "tsql_in_strings": r"\"[^\"]*(\bTOP\s+\d|GETDATE\(\)|ISNULL\(|NOLOCK|@@IDENTITY|SCOPE_IDENTITY|\bNEWID\(\))[^\"]*\"",
    "sqlclient_usage": r"\bnew\s+Sql(Connection|Command|DataAdapter|Parameter)\b|\bSqlDbType\.",
    "dapper_calls": r"\.(Query|QueryFirst|QueryFirstOrDefault|QuerySingle|QueryMultiple|Execute|ExecuteScalar)(Async)?\s*(<[^>]+>)?\s*\(\s*(@?\"|sql\b|query\b)",
    "ef6_contexts": r":\s*(System\.Data\.Entity\.)?DbContext\b|:\s*ObjectContext\b",
}
CODE_RX = {k: re.compile(v, re.I) for k, v in CODE.items()}


def inventory(root, skip_dirs=()):
    skip = SOURCE_DIR_SKIP | {s.lower() for s in skip_dirs}
    objects, code = [], Counter()
    code_files = Counter()
    edmx_imports = 0
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x.lower() not in skip and not x.startswith(".")]
        for fn in files:
            p = os.path.join(d, fn)
            low = fn.lower()
            try:
                if low.endswith(".sql") and os.path.getsize(p) < 3_000_000:
                    text = read_text(p)
                    lines = text.splitlines()
                    starts = [(m.start(), m) for m in CREATE.finditer(text)]
                    for i, (pos, m) in enumerate(starts):
                        name = m.group(2).replace("[", "").replace("]", "")
                        if name.split(".")[-1].startswith(("#", "@")):
                            continue
                        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
                        body = text[pos:end]
                        go = re.search(r"(?im)^\s*GO\s*$", body)
                        if go:
                            body = body[:go.start()]
                        kind = {"PROC": "PROCEDURE"}.get(m.group(1).upper(), m.group(1).upper())
                        cons = {k: len(rx.findall(body)) for k, rx in CONSTRUCT_RX.items()}
                        objects.append({"kind": kind, "name": name, "file": rel(p, root), "line": text.count("\n", 0, pos) + 1,
                                        "lines": body.count("\n") + 1, "constructs": {k: v for k, v in cons.items() if v}})
                elif low.endswith((".cs", ".vb")) and os.path.getsize(p) < 2_000_000:
                    text = read_text(p)
                    for k, rx in CODE_RX.items():
                        n = len(rx.findall(text))
                        if n:
                            code[k] += n
                            code_files[k] += 1
                elif low.endswith(".edmx"):
                    edmx_imports += len(re.findall(r"<FunctionImport\b", read_text(p)))
            except OSError:
                continue
    kinds = Counter(o["kind"] for o in objects)
    cons_total = Counter()
    for o in objects:
        cons_total.update(o["constructs"])
    sizes = Counter("small" if o["lines"] <= 50 else ("medium" if o["lines"] <= 200 else "large") for o in objects if o["kind"] in ("PROCEDURE", "FUNCTION", "TRIGGER", "VIEW"))
    return {"objects": objects, "kinds": dict(kinds), "routine_sizes": dict(sizes), "constructs": dict(cons_total),
            "sql_lines": sum(o["lines"] for o in objects), "code": dict(code), "code_files": dict(code_files), "edmx_function_imports": edmx_imports}
