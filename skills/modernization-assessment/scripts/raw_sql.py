"""Raw SQL and database-object usage for one repository: the application side of SQL Server -> PostgreSQL.

    py -X utf8 raw_sql.py --root <repo> --out <output dir> [--name myrepo]

Writes <out>/sql-inventory.json and <out>/sql-inventory.csv. Covers what modernization-assessment's _dbinventory.py does not:

  procedures  every stored-procedure call site in C# / VB, with the procedure NAME even when no .sql file defines it
              (literal, constant or variable), the call API (ExecuteReader / NonQuery / Scalar / XmlReader / DataSet /
              Dapper / EF), parameter names, OUTPUT / ReturnValue / table-valued (Structured) parameters, NextResult()
              multi-result handling and the columns the caller reads back by name
  statements  raw SQL text anywhere, not only C# literals that start with a SQL keyword:
              C# literals and "a" + b + "c" chains (holes marked dynamic), string.Format / interpolation,
              StringBuilder.Append runs and s += "..." runs (joined back into one statement), VB literals with & / +,
              SqlDataSource Select/Insert/Update/DeleteCommand in .aspx / .ascx / .master, SQL in .config / .xml /
              .json / .resx values, and .sql files. Every candidate is parsed with Microsoft's T-SQL parser
              (ScriptDom, via codebase-documenter's sql_parse.py); ones that do not parse are KEPT as fragments for
              review, never dropped.
  constructs  the T-SQL constructs each statement uses, with the PostgreSQL conversion level (auto / rewrite /
              redesign) from codebase-documenter's data/pg_conversion.json, plus a regex pass for fragments
  database    connection strings (provider and database names only, no hosts or credentials), databases named in
              three-part names, dynamic database names spliced into SQL, and SQL-Server-specific API use
              (SqlException.Number, SqlDbType, SqlBulkCopy, SqlDependency, SqlFileStream, transactions)
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def _documenter_scripts():
    """codebase-documenter's scripts folder: env var, sibling skill, a tools/skills copy, or the personal install."""
    home = os.path.expanduser("~")
    for d in (os.environ.get("CODEBASE_DOCUMENTER_DIR"), os.path.join(HERE, "..", "..", "codebase-documenter"),
              os.path.join(HERE, "..", "skills", "codebase-documenter"), os.path.join(home, ".claude", "skills", "codebase-documenter"),
              os.path.join(home, ".agents", "skills", "codebase-documenter")):
        if d and os.path.exists(os.path.join(d, "scripts", "sql_parse.py")):
            return os.path.normpath(os.path.join(d, "scripts"))
    raise SystemExit("raw_sql.py needs the codebase-documenter skill (its scripts/sql_parse.py): install it or set CODEBASE_DOCUMENTER_DIR")


DOC = _documenter_scripts()
if DOC not in sys.path:
    sys.path.insert(0, DOC)
import sql_parse as sp  # noqa: E402

PG = json.load(open(os.path.join(DOC, "data", "pg_conversion.json"), encoding="utf-8"))
SKIP_DIRS = {"bin", "obj", ".vs", ".git", "node_modules", "graphify-out", "testresults", "bower_components"}
HOLE = sp.HOLE
CODE_EXT = (".cs",)
VB_EXT = (".vb",)
MARKUP_EXT = (".aspx", ".ascx", ".master", ".cshtml", ".vbhtml", ".razor")
DATA_EXT = (".config", ".xml", ".json", ".resx", ".settings")
SKIP_FILES = (".csproj", ".vbproj", ".designer.cs", ".g.cs", ".generated.cs", ".edmx.diagram")
SKIP_NAMES = {"packages.config", "reference.cs", "reference.vb"}  # generated service-reference proxies

# SQL shape anywhere in a text (case-insensitive). A literal is a candidate when it matches one of these.
STMT_START = re.compile(r"^\s*\(?\s*(select|insert|update|delete|merge|exec|execute|with|truncate|declare|create|alter|drop|"
                        r"if\s+(not\s+)?exists|begin\s+tran|set\s+(nocount|transaction|ansi|quoted|xact|rowcount|dateformat)|"
                        r"sp_executesql|bulk\s+insert|use\s+\[?\w)\b", re.I)
STMT_ANY = [re.compile(p, re.I) for p in (
    r"\bselect\b[\s\S]{1,2000}?\bfrom\s+[\[\w#@]", r"\binsert\s+into\s+[\[\w#@]", r"\bupdate\s+[\[\w#@][\w\]\.]*\s+set\b",
    r"\bdelete\s+from\s+[\[\w#@]", r"\bexec(ute)?\s+(\[?dbo\]?\.)?\[?(sp_|usp_|\w+(get|set|save|update|insert|delete|search|check|list)\b)",
    r"\btruncate\s+table\b", r"\bmerge\s+(into\s+)?[\[\w\.\]]+\s+(as\s+\w+\s+)?using\b")]
FRAGMENT = re.compile(r"^\s*(from|where|and|or|order\s+by|group\s+by|having|inner\s+join|left\s+(outer\s+)?join|right\s+(outer\s+)?join|"
                      r"cross\s+(join|apply)|outer\s+apply|join|on|values|set|union(\s+all)?|top\s+\d|case\s+when|output\s+inserted)\b", re.I)
UI_TEXT = re.compile(r"^\s*(select|update|delete)\s+(a|an|the|your|one|all|this|from\s+the|at\s+least)\b", re.I)

DATA_API = set(sp.DATA_API) | {"ExecuteXmlReader", "ExecuteXMLReader", "ExecuteDataset", "ExecuteDataSet", "ExecuteDataTable",
                               "Fill", "SqlDataAdapter", "SqlCommand", "CommandText", "SelectCommand", "OleDbCommand", "OdbcCommand"}
CALL_API = ["ExecuteXmlReader", "ExecuteXMLReader", "ExecuteReaderAsync", "ExecuteReader", "ExecuteNonQueryAsync", "ExecuteNonQuery",
            "ExecuteScalarAsync", "ExecuteScalar", "ExecuteDataset", "ExecuteDataSet", "ExecuteDataTable", "Fill", "QueryMultipleAsync",
            "QueryMultiple", "QueryFirstOrDefaultAsync", "QueryFirstOrDefault", "QuerySingleOrDefault", "QueryAsync", "Query",
            "ExecuteAsync", "Execute", "SqlDataAdapter", "SqlCommand", "CommandText", "ExecuteSqlCommand", "SqlQuery", "FromSqlRaw"]
NAME_RX = re.compile(r"^\[?[A-Za-z_#][\w#]*\]?(\.\[?[A-Za-z_][\w]*\]?){0,3}$")

# Regex census for text that did not parse (fragments) and for flags the parser does not label. label -> pg_conversion key
TSQL_RX = {
    "TOP": r"\btop\s*\(?\s*(\d+|@)", "NOLOCK": r"\bnolock\b|\bwith\s*\(\s*(rowlock|updlock|holdlock|readpast|tablock)",
    "fn: ISNULL": r"\bisnull\s*\(", "fn: GETDATE": r"\bgetdate\s*\(\s*\)", "fn: GETUTCDATE": r"\bgetutcdate\s*\(",
    "fn: CONVERT": r"\bconvert\s*\(", "fn: DATEADD": r"\bdateadd\s*\(", "fn: DATEDIFF": r"\bdatediff\s*\(",
    "fn: LEN": r"\blen\s*\(", "fn: CHARINDEX": r"\bcharindex\s*\(", "fn: NEWID": r"\bnewid\s*\(", "fn: IIF": r"\biif\s*\(",
    "fn: STUFF": r"\bstuff\s*\(", "fn: SCOPE_IDENTITY": r"\bscope_identity\s*\(", "global: @@IDENTITY": r"@@identity",
    "global: @@ROWCOUNT": r"@@rowcount", "FOR XML": r"\bfor\s+xml\b", "FOR JSON": r"\bfor\s+json\b", "MERGE": r"\bmerge\s+",
    "OUTPUT clause": r"\boutput\s+(inserted|deleted)\.", "CROSS APPLY": r"\b(cross|outer)\s+apply\b", "PIVOT": r"\b(un)?pivot\s*\(",
    "bracket identifiers": r"\[[A-Za-z_][\w ]*\]", "cross-database": r"\b\w+\.\w*\.\w+\b(?=[^']*$)|\.dbo\.",
    "string concatenation +": r"'\s*\+|\+\s*'", "temp table": r"#\w+", "sp_executesql": r"\bsp_executesql\b",
}
TSQL_RX = {k: re.compile(v, re.I) for k, v in TSQL_RX.items()}
# SQL-Server-specific ADO.NET / EF usage in application code (behaviour shim, provider swap)
API_RX = {
    "System.Data.SqlClient using": r"^\s*using\s+System\.Data\.SqlClient\s*;|Imports\s+System\.Data\.SqlClient",
    "Microsoft.Data.SqlClient using": r"^\s*using\s+Microsoft\.Data\.SqlClient\s*;",
    "Sql* types (new SqlConnection/Command/Parameter/DataAdapter)": r"\bnew\s+Sql(Connection|Command|Parameter|DataAdapter|CommandBuilder)\b",
    "SqlDataReader": r"\bSqlDataReader\b", "SqlDbType": r"\bSqlDbType\.\w+", "SqlDbType.Structured (TVP)": r"\bSqlDbType\.Structured\b",
    "SqlException": r"\bSqlException\b", "SqlException.Number (error-number logic)": r"\.Number\s*(==|!=|switch|\bis\b)|case\s+(2627|2601|1205|547|-2)\b",
    "SqlBulkCopy": r"\bSqlBulkCopy\b", "SqlDependency": r"\bSqlDependency\b", "SqlFileStream": r"\bSqlFileStream\b",
    "SqlTransaction / BeginTransaction": r"\bSqlTransaction\b|\.BeginTransaction\s*\(", "TransactionScope": r"\bTransactionScope\b",
    "ExecuteXmlReader (FOR XML)": r"\bExecuteXmlReader\s*\(|\bExecuteXMLReader\s*\(", "NextResult (multi-result)": r"\.NextResult(Async)?\s*\(",
    "Dapper": r"\busing\s+Dapper\s*;", "Entity Framework 6": r"\bSystem\.Data\.Entity\b|:\s*DbContext\b", "EF Core": r"\bMicrosoft\.EntityFrameworkCore\b",
    "OleDb / Odbc": r"\b(OleDb|Odbc)(Connection|Command)\b", "SqlConnectionStringBuilder": r"\bSqlConnectionStringBuilder\b",
    "SqlCommandBuilder.DeriveParameters": r"\bDeriveParameters\s*\(", "CommandTimeout": r"\.CommandTimeout\s*=",
}
API_RX = {k: re.compile(v, re.I | re.M) for k, v in API_RX.items()}
CONN_RX = re.compile(r"(?i)(?:initial\s+catalog|database)\s*=\s*([^;\"'<>]+)")
PROVIDER_RX = re.compile(r'providerName\s*=\s*"([^"]+)"', re.I)
CONNSTR_RX = re.compile(r"(?i)<add\b[^>]*\bconnectionString\s*=|(?:data\s+source|server)\s*=[^;\"']+;[^\"']*(?:initial\s+catalog|database)\s*=")


def conversion(label):
    if label in PG["constructs"]:
        return PG["constructs"][label]
    for prefix, table in (("fn: ", "functions"), ("global: ", "globals"), ("data type: ", "data_types")):
        if label.startswith(prefix):
            key = label[len(prefix):]
            return PG[table].get(key) or PG[table].get(key.upper()) or PG["prefix_defaults"].get(prefix) or PG["default"]
    return PG["default"]


def read(p):
    return sp.read_text(p)


def nuget_folder(path):
    """A restored NuGet packages folder (packages/<Id>.<version>/*.nupkg), not source code that happens to be named Packages."""
    try:
        if os.path.exists(os.path.join(path, "repositories.config")):
            return True
        for sub in os.listdir(path)[:8]:
            q = os.path.join(path, sub)
            if os.path.isdir(q) and any(f.lower().endswith(".nupkg") for f in os.listdir(q)):
                return True
    except OSError:
        pass
    return False


def walk(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIRS and not x.startswith(".")
                   and not (x.lower() == "packages" and nuget_folder(os.path.join(d, x)))]
        for f in files:
            yield os.path.join(d, f)


def rel(root, p):
    return os.path.relpath(p, root).replace("\\", "/")


STRUCTURE = {  # a statement-start keyword only counts when the statement has the shape that keyword needs
    "select": r"^\s*\(?\s*select\s+(@@?\w+|\d+|N?'|\w+\s*\(|top\b|distinct\b|\*)|\bfrom\s+[\[\w#@{]",
    "insert": r"\binsert\s+(into\s+)?[\[\w#@.\]{}\x01]+\s*(\(|values\b|select\b|exec\b|default\s+values|output\b)|\binsert\s+into\b",
    "update": r"\bupdate\s+[\[\w#@.\]{}\x01]+\s+set\b",
    "delete": r"\bdelete\s+(top\s*\(\d+\)\s*)?(from\s+)?[\[\w#@.\]{}\x01]+\s*(where\b|from\b|output\b|$|;)",
    "merge": r"\bmerge\b[\s\S]+\busing\b", "with": r"^\s*with\s+[\w\[\]]+(\s*\([^)]*\))?\s+as\s*\(",
    "create": r"^\s*create\s+(or\s+alter\s+)?(unique\s+|clustered\s+|nonclustered\s+)*(table|proc|procedure|view|index|function|trigger|type|schema|database|sequence|synonym)\b",
    "alter": r"^\s*alter\s+(table|proc|procedure|view|index|function|trigger|database)\b",
    "drop": r"^\s*drop\s+(table|proc|procedure|view|index|function|trigger|type)\b",
    "exec": r"^\s*exec(ute)?\s+(@\w+\s*=\s*)?[\[\w.#\]\x01]*([_.]|[a-z][A-Z])[\w.\]]*(\s|$|;)|^\s*exec(ute)?\s+[\[\w.]+\s+@|^\s*exec(ute)?\s*\(\s*@",
    "truncate": r"^\s*truncate\s+table\b", "declare": r"^\s*declare\s+@", "set": r"^\s*set\s+(nocount|transaction|ansi|quoted|xact|rowcount|dateformat|@)",
    "if": r"^\s*if\s+(not\s+)?exists\s*\(\s*select\b", "begin": r"^\s*begin\s+tran", "sp_executesql": r"sp_executesql",
    "bulk": r"^\s*bulk\s+insert\b", "use": r"^\s*use\s+\[?\w+\]?\s*;?\s*$",
}
STRUCTURE = {k: re.compile(v, re.I) for k, v in STRUCTURE.items()}


def is_sql(text, context=False, joined=False):
    """'statement' | 'fragment' | None for one candidate text."""
    t = text.replace(HOLE, " @p ").strip()
    if len(t) < 6 or len(t.split()) < 2 or UI_TEXT.match(t) and not context:
        return None
    m = STMT_START.match(t)
    if m:
        kw = m.group(1).split()[0].lower().rstrip("(")
        kw = "exec" if kw == "execute" else kw
        rx = STRUCTURE.get(kw)
        if rx is None or rx.search(t):
            return "statement"
    elif any(rx.search(t) for rx in STMT_ANY):
        return "statement"
    if (context or joined) and FRAGMENT.match(t) and len(t.split()) >= 2 and re.search(r"[=<>]|\bin\s*\(|\bjoin\b|\bby\b|\bis\s+(not\s+)?null\b", t, re.I):
        return "fragment"
    return None


# ---------------------------------------------------------------- C#
def cs_chains(toks):
    """Every string-literal expression: "a" + x + "b" joined (non-literal operands become holes)."""
    out, i, n = [], 0, len(toks)
    stop = {";", ",", ")", "}", "]", "=", "?", ":"}
    while i < n:
        t = toks[i]
        if t[0] != "str":
            i += 1
            continue
        parts, holes, line, end_line, start = [t[1]], t[4], t[2], t[3], i
        j = i + 1
        while j < n and toks[j][:2] == ("op", "+") and not (j + 1 < n and toks[j + 1][:2] == ("op", "=")):
            j += 1
            if j < n and toks[j][0] == "str":
                parts.append(toks[j][1]); holes += toks[j][4]; end_line = toks[j][3]; j += 1
                continue
            depth = 0
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
            parts.append(" " + HOLE + " "); holes += 1
        text = re.sub(r"\{\d+(:[^}]*)?\}", HOLE, "".join(parts))  # string.Format items
        out.append({"line": line, "end_line": end_line, "text": text, "holes": holes + text.count(HOLE) - "".join(parts).count(HOLE),
                    "start": start, "end": j})
        i = j
    return out


def context_ids(toks, a, b):
    return sorted({toks[k][1] for k in range(max(0, a - 80), min(len(toks), b + 30)) if toks[k][0] == "id" and toks[k][1] in DATA_API})


def builder_runs(toks, chains):
    """sb.Append("..") / sb.AppendLine / sb.AppendFormat runs and s += ".." runs on one variable, joined in order."""
    by_start = {c["start"]: c for c in chains}
    pieces = defaultdict(list)  # var -> [(line, chain)]
    n = len(toks)
    for k in range(n - 3):
        t = toks[k]
        if t[0] != "id":
            continue
        # X.Append( "..."
        if toks[k + 1][:2] == ("op", ".") and toks[k + 2][0] == "id" and toks[k + 2][1] in ("Append", "AppendLine", "AppendFormat", "Insert") \
                and k + 4 < n and toks[k + 3][:2] == ("op", "("):
            c = by_start.get(k + 4)
            if c:
                pieces[t[1]].append(c)
        # X += "..."   /   X = "..." (start of a run)
        elif toks[k + 1][:2] == ("op", "+") and toks[k + 2][:2] == ("op", "=") and k + 3 < n:
            c = by_start.get(k + 3)
            if c:
                pieces[t[1]].append(c)
        elif toks[k + 1][:2] == ("op", "=") and toks[k + 2][0] == "str" and (k == 0 or toks[k - 1][1] not in ("=", "!", "<", ">")):
            c = by_start.get(k + 2)
            if c:
                pieces[t[1]].append(dict(c, reset=True))
    runs = []
    for var, cs in pieces.items():
        cs.sort(key=lambda c: c["start"])
        cur = []
        for c in cs:
            if cur and (c.get("reset") or c["line"] - cur[-1]["end_line"] > 15):
                runs.append((var, cur)); cur = []
            cur.append(c)
        if cur:
            runs.append((var, cur))
    return [(v, r) for v, r in runs if len(r) > 1]


NOT_METHOD = {"if", "for", "foreach", "while", "switch", "catch", "using", "lock", "fixed", "return", "new", "nameof", "typeof",
              "sizeof", "default", "when", "base", "this", "checked", "unchecked", "await", "throw", "in", "is", "as", "else"}
PARAM_API = {"SqlParameter", "AddWithValue", "Add", "GetOrdinal", "GetString", "GetInt32", "GetValue", "Parameters", "Field",
             "Contains", "Equals", "Format", "Replace", "Split", "Join", "Concat", "Log", "Info", "Error", "Debug", "Warn", "WriteLine"}
EXEC_LIKE = re.compile(r"exec|query|fill|proc|sproc|reader|scalar|nonquery|dataset|datatable|storedprocedure|runsp|callsp", re.I)
WRAPPER_NAME = re.compile(r"StoredProc|Sproc|ExecProc|ExecuteProc|RunProc|CallProc|ExecSP|ExecuteSP|RunSP|CallSP", re.I)
NOT_A_NAME = {"CommandType", "CommandBehavior", "conn", "connection", "cmd", "command", "sqlConnection", "con", "cn", "transaction",
              "tran", "trans", "parameters", "sqlParameters", "spParameters", "parms", "param", "args", "null", "true", "false"}


def args_of(toks, open_idx):
    """Top-level argument token slices of the call whose '(' is at open_idx, and the index of its ')'."""
    out, cur, d, i = [], [], 0, open_idx + 1
    while i < len(toks):
        t = toks[i]
        if t[0] == "op" and t[1] in "([{":
            d += 1
        elif t[0] == "op" and t[1] in ")]}":
            if d == 0:
                if cur:
                    out.append(cur)
                return out, i
            d -= 1
        if t[0] == "op" and t[1] == "," and d == 0:
            out.append(cur)
            cur = []
        else:
            cur.append(t)
        i += 1
    return out, i


def method_spans(toks):
    """(name, '{' index, '}' index, [parameter names]) for every method / constructor / local function body."""
    spans, stack = [], []
    for i, t in enumerate(toks):
        if t[0] != "op" or t[1] not in "{}":
            continue
        if t[1] == "}":
            if stack:
                st = stack.pop()
                if st[1]:
                    spans.append((st[1], st[0], i, st[2]))
            continue
        name, params = None, []
        j = i - 1
        if j >= 0 and toks[j][:2] == ("op", ")"):
            d, k = 0, j
            while k >= 0:
                if toks[k][:2] == ("op", ")"):
                    d += 1
                elif toks[k][:2] == ("op", "("):
                    d -= 1
                    if d == 0:
                        break
                k -= 1
            if k > 1 and toks[k - 1][0] == "id" and toks[k - 1][1] not in NOT_METHOD and (toks[k - 2][0] == "id" or toks[k - 2][1] in (">", "]", "?")):
                name = toks[k - 1][1]
                for arg in args_of(toks, k)[0]:
                    cut = next((n for n, x in enumerate(arg) if x[:2] == ("op", "=")), len(arg))
                    ids = [x[1] for x in arg[:cut] if x[0] == "id"]
                    if ids:
                        params.append(ids[-1])
        stack.append((i, name, params))
    return spans


def enclosing(spans, k):
    best = None
    for s in spans:
        if s[1] < k < s[2] and (best is None or s[1] > best[1]):
            best = s
    return best


def name_from(tok, consts):
    """(name, how) for one argument token: literal, constant, or variable."""
    if tok[0] == "str" and not tok[4] and NAME_RX.match(tok[1] or "-"):
        return tok[1], "literal"
    if tok[0] == "id" and tok[1] not in NOT_A_NAME:
        if tok[1] in consts:
            return consts[tok[1]], "constant " + tok[1]
        return "(variable " + tok[1] + ")", "variable"
    return None, None


def name_from_arg(arg, consts):
    """(name, how) for one whole argument: a literal / constant, a Class.Constant, or a concatenation such as
    Catalog + ".dbo.Proc" (the run-time part shown as {db})."""
    if len(arg) == 1:
        return name_from(arg[0], consts)
    if len(arg) == 3 and arg[1][1] == "." and arg[2][0] == "id" and arg[2][1] in consts:
        return consts[arg[2][1]], "constant " + arg[0][1] + "." + arg[2][1]
    strs = [t for t in arg if t[0] == "str"]
    if strs and any(t[1] == "+" for t in arg if t[0] == "op"):
        parts, prev_str = [], False
        for t in arg:
            if t[0] == "str":
                parts.append(t[1]); prev_str = True
            elif t[0] == "op" and t[1] == "+":
                prev_str = False
            elif not prev_str and (not parts or parts[-1] != "{db}"):
                parts.append("{db}")
        nm = "".join(parts)
        if NAME_RX.match(nm.replace("{db}", "x")) and "{db}" in nm:
            return nm, "run-time database name"
    return None, None


def file_consts(toks):
    consts = {}
    for k in range(len(toks) - 3):
        if toks[k][0] == "id" and toks[k + 1][:2] == ("op", "=") and toks[k + 2][0] == "str" and not toks[k + 2][4] \
                and NAME_RX.match(toks[k + 2][1] or "-") and toks[k + 3][1] in (";", ","):
            consts.setdefault(toks[k][1], toks[k + 2][1])
    return consts


def call_owner(toks, m, lo):
    """Method name and argument index of the call that directly contains token m (None if not inside a call)."""
    d, j, idx = 0, m - 1, 0
    while j >= lo:
        t = toks[j]
        if t[0] == "op" and t[1] in ")]}":
            d += 1
        elif t[0] == "op" and t[1] in "([{":
            if d == 0:
                if t[1] == "(" and j > 0 and toks[j - 1][0] == "id":
                    return toks[j - 1][1], idx, j
                if t[1] == "(" and j > 1 and toks[j - 1][1] == ">":  # Name<T>(
                    g, q = 0, j - 1
                    while q > 0 and q > j - 40:
                        g += 1 if toks[q][1] == ">" else -1 if toks[q][1] == "<" else 0
                        if g == 0:
                            break
                        q -= 1
                    if q > 0 and toks[q - 1][0] == "id":
                        return toks[q - 1][1], idx, j
                return None, idx, j
            d -= 1
        elif t[0] == "op" and t[1] == "," and d == 0:
            idx += 1
        j -= 1
    return None, idx, j


def proc_sites_cs(toks, file, consts, spans):
    """Direct stored-procedure call sites (CommandType.StoredProcedure / commandType: ...). A site whose name is a
    parameter of the enclosing method marks that method as a WRAPPER, resolved at its own call sites in pass 2."""
    sites, wrappers = [], {}
    for k in range(len(toks) - 2):
        if not (toks[k][1] == "CommandType" and toks[k + 1][1] == "." and toks[k + 2][1] == "StoredProcedure"):
            continue
        line = toks[k][2]
        a, depth = k, 0  # statement start: previous ';' or the enclosing block '{' (object initialisers crossed)
        while a > 0 and k - a < 400:
            v = toks[a - 1][1] if toks[a - 1][0] == "op" else ""
            if v in (")", "}", "]"):
                depth += 1
            elif v in ("(", "{", "["):
                if depth == 0 and v == "{" and not (a > 1 and toks[a - 2][0] == "id" and toks[a - 3][1] == "new"):
                    break
                depth = max(0, depth - 1)
            elif v == ";" and depth == 0:
                break
            a -= 1
        b = k
        while b < len(toks) - 1 and b - k < 60 and toks[b][1] != ";":
            b += 1
        name, how, api = None, None, None
        for m in range(a, b + 1):  # a literal / constant passed to an execute-like call or the SqlCommand constructor
            t = toks[m]
            if t[0] == "id" and not (t[1] in consts or toks[m + 1][1] in (",", ")")):
                continue
            if t[0] not in ("str", "id") or (t[0] == "id" and toks[m - 1][1] == "."):
                continue
            owner, idx, _ = call_owner(toks, m, a)
            if not owner or owner in PARAM_API:
                continue
            if (owner in CALL_API or EXEC_LIKE.search(owner)) and (t[0] == "str" or idx == 0):
                nm, hw = name_from(t, consts)
                if nm:
                    name, how, api = nm, hw, owner
                    break
        if not name:  # cmd.CommandText = x  /  new SqlCommand(x, ...) in the statements just above
            for j in range(k - 1, max(1, k - 400), -1):
                if toks[j][1] == "CommandText" and j + 2 < len(toks) and toks[j + 1][1] == "=":
                    name, how = name_from(toks[j + 2], consts)
                    how = "CommandText " + (how or "")
                    break
                if toks[j][1] in ("SqlCommand", "SqlDataAdapter") and toks[j + 1][1] == "(" and toks[j - 1][1] == "new":
                    name, how = name_from(toks[j + 2], consts)
                    how = "new " + toks[j][1] + " " + (how or "")
                    break
        if not api:
            api = next((t[1] for t in reversed(toks[a:b + 1]) if t[0] == "id" and t[1] in CALL_API), None) or \
                  next((t[1] for t in toks[b:b + 200] if t[0] == "id" and t[1] in CALL_API), "?")
        site = {"file": file, "line": line, "name": name or "(unresolved)", "how": (how or "unresolved").strip(), "api": api, "tok": k}
        if name and name.startswith("(variable "):
            var = name[10:-1]
            enc = enclosing(spans, k)
            if enc and var in enc[3]:
                wrappers.setdefault(enc[0], {"param": enc[3].index(var), "file": file, "line": toks[enc[1]][2], "api": api})
                site["wrapper_definition"] = enc[0]
        sites.append(site)
    return sites, wrappers


def wrapper_sites_cs(toks, file, consts, wrappers):
    """Pass 2: calls to wrapper methods; the procedure name is the argument in the wrapper's name parameter."""
    out = []
    for k in range(1, len(toks) - 1):
        t = toks[k]
        if t[0] != "id" or toks[k + 1][:2] != ("op", "("):
            continue
        w = wrappers.get(t[1])
        if w is None and WRAPPER_NAME.search(t[1]):
            w = {"param": 0, "heuristic": True}
        if w is None:
            continue
        prev = toks[k - 1]
        if prev[0] == "id" and prev[1] not in NOT_METHOD:  # a declaration "Task<X> Name(" / "void Name(", not a call
            continue
        if prev[1] == ">" and toks[k - 2][0] == "id":  # Task<DataTable> Name(
            continue
        args, _ = args_of(toks, k + 1)
        if len(args) <= w["param"] or not args[w["param"]]:
            continue
        arg = args[w["param"]]
        nm, hw = name_from_arg(arg, consts)
        if nm is None and w.get("heuristic"):  # wrapper defined outside this repo: the first name-like argument
            for other in args:
                nm, hw = name_from_arg(other, consts)
                if nm and not nm.startswith("("):
                    break
                nm, hw = None, None
        if nm is None:
            nm, hw = "(expression)", "expression"
        out.append({"file": file, "line": t[2], "name": nm, "how": "wrapper " + t[1] + " / " + hw, "api": t[1], "tok": k})
    return out


def site_details(lines, sites):
    """Parameters / OUTPUT / TVP / multi-result / columns read, between the previous call site and the next one."""
    sites.sort(key=lambda s: s["line"])
    for i, s in enumerate(sites):
        lo = max(sites[i - 1]["line"] if i else 0, s["line"] - 45)
        hi = min(sites[i + 1]["line"] if i + 1 < len(sites) else len(lines), s["line"] + 80)
        before = "\n".join(lines[lo:s["line"]])
        after = "\n".join(lines[s["line"]:hi])
        s["params"] = sorted(set(re.findall(r"\"(@\w+)\"", before + "\n" + lines[s["line"] - 1])))
        s["output_params"] = len(re.findall(r"ParameterDirection\.(Output|InputOutput)", before))
        s["return_value"] = bool(re.search(r"ParameterDirection\.ReturnValue", before))
        s["tvp"] = bool(re.search(r"SqlDbType\.Structured", before))
        s["sqldbtypes"] = sorted(set(re.findall(r"SqlDbType\.(\w+)", before)))
        s["next_result"] = len(re.findall(r"\.NextResult(Async)?\s*\(", after)) + len(re.findall(r"\.Tables\s*\[\s*[1-9]", after))
        s["columns_read"] = sorted(set(re.findall(r"\w+\s*\[\s*\"(\w+)\"\s*\]", after)) | set(re.findall(r"GetOrdinal\s*\(\s*\"(\w+)\"", after)))[:80]
        s["xml_reader"] = "xml" in s["api"].lower()
        s.pop("tok", None)
    return sites


def scan_cs(path, file):
    text = read(path)
    toks = sp._tokens(text)
    chains = cs_chains(toks)
    cands = []
    used = set()
    for var, run in builder_runs(toks, chains):
        joined = " ".join(c["text"] for c in run)
        ctx = context_ids(toks, run[0]["start"], run[-1]["end"])
        kind = is_sql(joined, bool(ctx), joined=True)
        if kind:
            cands.append({"file": file, "line": run[0]["line"], "end_line": run[-1]["end_line"], "text": joined,
                          "holes": sum(c["holes"] for c in run), "source": "cs-builder:" + var, "kind": kind, "context": ctx})
            used.update(c["start"] for c in run)
    for c in chains:
        if c["start"] in used:
            continue
        ctx = context_ids(toks, c["start"], c["end"])
        kind = is_sql(c["text"], bool(ctx))
        if kind:
            src = "cs-format" if re.search(r"\{\d", "".join(t[1] for t in toks[c["start"]:c["end"]] if t[0] == "str")) else \
                  "cs-concat" if c["holes"] else "cs-literal"
            cands.append({"file": file, "line": c["line"], "end_line": c["end_line"], "text": c["text"], "holes": c["holes"],
                          "source": src, "kind": kind, "context": ctx})
    return cands, toks, text


# ---------------------------------------------------------------- VB, markup, data files
VB_STR = re.compile(r'"((?:[^"]|"")*)"')


def scan_vb(path, file):
    text = read(path)
    cands, procs = [], []
    logical, start = [], 1
    for no, ln in enumerate(text.splitlines(), 1):
        code = re.sub(r"'(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$).*$", "", ln)  # strip comment outside strings
        if not logical:
            start = no
        logical.append(code.rstrip())
        if code.rstrip().endswith(" _") or code.rstrip().endswith("&") or code.rstrip().endswith("+"):
            continue
        stmt = " ".join(x.rstrip(" _") for x in logical)
        logical = []
        lits = VB_STR.findall(stmt)
        if not lits:
            continue
        joined = re.sub(r'"(?:[^"]|"")*"', lambda m: m.group(0)[1:-1].replace('""', '"'), stmt)
        body = HOLE.join(x.replace('""', '"') for x in lits) if len(lits) > 1 else lits[0].replace('""', '"')
        ctx = [w for w in DATA_API if w in stmt]
        kind = is_sql(body, bool(ctx))
        if kind:
            cands.append({"file": file, "line": start, "end_line": no, "text": body, "holes": len(lits) - 1,
                          "source": "vb", "kind": kind, "context": ctx})
        if "StoredProcedure" in stmt:
            nm = next((x for x in lits if NAME_RX.match(x)), None)
            procs.append({"file": file, "line": start, "name": nm or "(unresolved)", "how": "literal" if nm else "unresolved",
                          "api": next((a for a in CALL_API if a in stmt), "?"), "params": [], "output_params": 0,
                          "return_value": False, "tvp": False, "sqldbtypes": [], "next_result": 0, "columns_read": [],
                          "xml_reader": "ExecuteXmlReader" in stmt})
        del joined
    return cands, procs, text


MARKUP_CMD = re.compile(r'\b(Select|Insert|Update|Delete)Command\s*=\s*"([^"]*)"', re.I)
MARKUP_TYPE = re.compile(r'\b(Select|Insert|Update|Delete)CommandType\s*=\s*"StoredProcedure"', re.I)
QUOTED = re.compile(r'"([^"\r\n]{6,4000})"|>([^<]{6,4000})<')


def scan_markup(path, file):
    text = read(path)
    cands, procs = [], []
    for m in MARKUP_CMD.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        tag_end = text.find(">", m.end())
        tag = text[text.rfind("<", 0, m.start()):tag_end if tag_end > 0 else m.end()]
        if MARKUP_TYPE.search(tag) and NAME_RX.match(m.group(2).strip()):
            procs.append({"file": file, "line": line, "name": m.group(2).strip(), "how": "SqlDataSource " + m.group(1) + "Command",
                          "api": "SqlDataSource", "params": sorted(set(re.findall(r'Name="(\w+)"', text[m.end():m.end() + 3000])))[:30],
                          "output_params": 0, "return_value": False, "tvp": False, "sqldbtypes": [], "next_result": 0, "columns_read": [],
                          "xml_reader": False})
        elif m.group(2).strip():
            cands.append({"file": file, "line": line, "end_line": line, "text": m.group(2), "holes": 0,
                          "source": "markup:" + m.group(1) + "Command", "kind": is_sql(m.group(2), True) or "fragment", "context": ["SqlDataSource"]})
    # server-side code blocks <% %> and <script runat=server>: treat as C#
    for blk in re.finditer(r"<%(?![@#:=$-])([\s\S]*?)%>|<script[^>]*runat\s*=\s*\"server\"[^>]*>([\s\S]*?)</script>", text, re.I):
        code = blk.group(1) or blk.group(2) or ""
        if not re.search(r"select|insert|update|delete|exec", code, re.I):
            continue
        base = text.count("\n", 0, blk.start())
        toks = sp._tokens(code)
        for c in cs_chains(toks):
            ctx = context_ids(toks, c["start"], c["end"])
            kind = is_sql(c["text"], bool(ctx))
            if kind:
                cands.append({"file": file, "line": base + c["line"], "end_line": base + c["end_line"], "text": c["text"],
                              "holes": c["holes"], "source": "markup:server-code", "kind": kind, "context": ctx})
    return cands, procs, text


def scan_data(path, file):
    text = read(path)
    cands = []
    for m in QUOTED.finditer(text):
        v = (m.group(1) or m.group(2) or "").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"')
        if is_sql(v, False) == "statement" and (STMT_START.match(v) or re.search(r"\bfrom\b|\binto\b", v, re.I)):
            line = text.count("\n", 0, m.start()) + 1
            cands.append({"file": file, "line": line, "end_line": line, "text": v, "holes": 0, "source": "data:" + os.path.splitext(file)[1],
                          "kind": "statement", "context": []})
    return cands, [], text


# ---------------------------------------------------------------- parse + classify
def parse_all(cands):
    variants = sp.VARIANTS[:4]
    best, pending = {}, list(range(len(cands)))
    for k, variant in enumerate(variants):
        if not pending:
            break
        res = sp.parse([{"id": str(i), "text": variant(cands[i]["text"])} for i in pending])
        failed = []
        for r in res:
            i = int(r.get("id", -1))
            ok = not r.get("errors") and not r.get("fatal") and ((r.get("script") or {}).get("statements") or r.get("objects"))
            if ok:
                best[i] = (r, k)
            else:
                failed.append(i)
                cands[i].setdefault("parse_error", (r.get("errors") or [{}])[0].get("message", r.get("fatal", "")))
        pending = [i for i in failed if cands[i]["holes"]]
    for i, c in enumerate(cands):
        if i in best:
            r, k = best[i]
            sc = r.get("script") or {}
            cons = Counter(sc.get("constructs") or {})
            for o in r.get("objects", []):
                cons.update(o.get("constructs") or {})
            ph = lambda x: re.sub(r"\bdyn_p\b|@p\b", "{?}", x)  # parser placeholders for run-time parts
            nm = lambda xs: sorted({ph(x if isinstance(x, str) else (x.get("name") or "")) for x in xs or []} - {""})
            sc = dict(sc, reads=nm(sc.get("reads")), writes=nm(sc.get("writes")), calls=nm(sc.get("calls")),
                      functions=nm(sc.get("functions")), temp_tables=nm(sc.get("temp_tables")),
                      statements=[x if isinstance(x, str) else (x.get("kind") or x.get("type") or str(x)) for x in sc.get("statements") or []])
            c.update(parsed=True, reading=sp.VARIANT_NAMES[k], statements=sc.get("statements", []) + [o.get("verb", "") + " " + o.get("kind", "") for o in r.get("objects", [])],
                     reads=sc.get("reads", []), writes=sc.get("writes", []), calls=sc.get("calls", []),
                     functions=sc.get("functions", []), temp_tables=sc.get("temp_tables", []), dynamic_sql=sc.get("dynamic_sql", False),
                     result_sets=sc.get("result_sets", 0), constructs=dict(cons))
            c["kind"] = "statement"
            c.pop("parse_error", None)
        else:
            t = c["text"].replace(HOLE, " @p ")
            c.update(parsed=False, statements=[], reads=[], writes=[], calls=[], functions=[], temp_tables=[], dynamic_sql=False,
                     result_sets=0, constructs={k: len(rx.findall(t)) for k, rx in TSQL_RX.items() if rx.search(t)})
            if c["kind"] == "statement":
                c["kind"] = "statement (did not parse)"
        # flags the parser does not label
        t = c["text"]
        extra = {}
        if re.search(HOLE + r"\s*\.\s*(dbo|\[dbo\])\s*\.", t, re.I) or re.search(r"\.\s*dbo\s*\.", t, re.I) and HOLE in t[:t.lower().find(".dbo.") + 1]:
            extra["dynamic database name"] = 1
        if re.search(r"\[[A-Za-z_]\w*\]", t):
            extra["bracket identifiers"] = len(re.findall(r"\[[A-Za-z_]\w*\]", t))
        if c["holes"] and re.search(r"'\s*" + HOLE + r"\s*'|=\s*" + HOLE, t):
            extra["value concatenated into SQL (injection risk, rewrite as parameter)"] = 1
        for k2, v in extra.items():
            c["constructs"][k2] = c["constructs"].get(k2, 0) + v
        lv = Counter()
        red = []
        for lab, n in c["constructs"].items():
            conv = conversion(lab)
            lv[conv["level"]] += n
            if conv["level"] == "redesign":
                red.append({"construct": lab, "pg": conv.get("pg", "")})
        c["conversion"] = dict(lv)
        c["redesign"] = red
        c["dynamic"] = c["holes"] > 0
    return cands


def inventory(root, name=None):
    """Every stored-procedure call site and raw SQL statement in one repository (the dict written to sql-inventory.json)."""
    root = os.path.abspath(root)
    name = name or os.path.basename(root.rstrip("\\/")).lower()
    cands, procs, api, files_seen = [], [], Counter(), Counter()
    api_files = defaultdict(set)
    conn = {"connection_strings": 0, "providers": Counter(), "databases": Counter(), "files": set()}
    sql_files = []
    cs_files = {}  # file -> (toks, consts, lines) for pass 2
    wrappers = {}
    for p in walk(root):
        f = rel(root, p)
        low = f.lower()
        if low.endswith(SKIP_FILES) or os.path.basename(low) in SKIP_NAMES or os.path.getsize(p) > 3_000_000:
            continue
        ext = os.path.splitext(low)[1]
        try:
            if ext in CODE_EXT:
                c, toks, text = scan_cs(p, f)
                consts = file_consts(toks)
                pr = []
                if "StoredProcedure" in text:
                    pr, w = proc_sites_cs(toks, f, consts, method_spans(toks))
                    wrappers.update(w)
                cs_files[f] = (toks, consts, text.splitlines(), pr)
                pr = []
            elif ext in VB_EXT:
                c, pr, text = scan_vb(p, f)
            elif ext in MARKUP_EXT:
                c, pr, text = scan_markup(p, f)
            elif ext in DATA_EXT:
                c, pr, text = scan_data(p, f)
            elif ext == ".sql":
                text = read(p)
                sql_files.append({"file": f, "lines": text.count("\n") + 1})
                c, pr = [], []
            else:
                continue
        except (OSError, UnicodeError) as e:
            print("skip", f, e, file=sys.stderr)
            continue
        files_seen[ext] += 1
        cands += c
        procs += pr
        if ext in CODE_EXT + VB_EXT + MARKUP_EXT:
            for k, rx in API_RX.items():
                n = len(rx.findall(text))
                if n:
                    api[k] += n
                    api_files[k].add(f)
        if ext in DATA_EXT + CODE_EXT and CONNSTR_RX.search(text):
            conn["files"].add(f)
            conn["connection_strings"] += len(re.findall(r"(?i)\bconnectionString\s*=\s*\"", text)) if ext == ".config" else len(CONN_RX.findall(text))
            conn["providers"].update(PROVIDER_RX.findall(text))
            conn["databases"].update(x.strip() for x in CONN_RX.findall(text) if x.strip() and "{" not in x)
    # pass 2: wrapper calls; constants shared across files (class constants used from another file)
    all_consts = {}
    for toks, consts, _, _ in cs_files.values():
        for k, v in consts.items():
            all_consts.setdefault(k, v)
    spans_of = {}
    for _round in range(4):
        before = len(wrappers)
        for f, (toks, consts, lines, direct) in cs_files.items():
            ws_ = wrapper_sites_cs(toks, f, dict(all_consts, **consts), wrappers)
            for s in ws_:
                if s["name"].startswith("(variable "):
                    sp_ = spans_of.setdefault(f, method_spans(toks))
                    enc = enclosing(sp_, s["tok"])
                    if enc and s["name"][10:-1] in enc[3] and enc[0] not in wrappers:
                        wrappers[enc[0]] = {"param": enc[3].index(s["name"][10:-1]), "file": f, "line": toks[enc[1]][2], "api": s["api"],
                                            "chained_from": s["api"]}
        if len(wrappers) == before:
            break
    # keep a chained wrapper only when most of its callers pass a procedure-name literal / constant (a method named Get or
    # Authenticate that forwards some parameter is not a stored-procedure wrapper)
    lit, tot = Counter(), Counter()
    for f, (toks, consts, lines, direct) in cs_files.items():
        for s in wrapper_sites_cs(toks, f, dict(all_consts, **consts), wrappers):
            tot[s["api"]] += 1
            lit[s["api"]] += not s["name"].startswith("(")
    dropped = {w for w, v in wrappers.items() if v.get("chained_from") and (lit[w] == 0 or lit[w] < 0.5 * tot[w])}
    while True:  # a wrapper chained from a rejected one goes too
        more = {w for w, v in wrappers.items() if w not in dropped and v.get("chained_from") in dropped}
        if not more:
            break
        dropped |= more
    for w in dropped:
        wrappers.pop(w)
    dropped = sorted(dropped)
    wrapper_defs = []
    for f, (toks, consts, lines, direct) in cs_files.items():
        cc = dict(all_consts, **consts)
        sites = [s for s in direct if not s.get("wrapper_definition")]
        wrapper_defs += [s for s in direct if s.get("wrapper_definition")]
        for s in sites:  # a variable that is a constant of another file
            if s["name"].startswith("(variable ") and s["name"][10:-1] in cc:
                s["how"], s["name"] = "constant " + s["name"][10:-1], cc[s["name"][10:-1]]
        for s in wrapper_sites_cs(toks, f, cc, wrappers):
            enc = enclosing(spans_of.get(f) or [], s["tok"]) if s["name"].startswith("(variable ") else None
            if enc and enc[0] in wrappers and s["name"][10:-1] in enc[3]:
                wrapper_defs.append(s)  # the call inside a wrapper that forwards its name parameter
                continue
            sites.append(s)
        procs += site_details(lines, sites)
    cs_files.clear()
    if sql_files:
        objs, _ = sp.scan_files(root, SKIP_DIRS), None
        sql_objects = Counter(o.get("kind") for r in objs for o in r.get("objects", []))
    else:
        sql_objects = Counter()
    cands = parse_all(cands) if cands else []
    # EXEC inside raw SQL counts as a procedure call too
    for c in cands:
        for callee in c.get("calls", []):
            procs.append({"file": c["file"], "line": c["line"], "name": callee, "how": "EXEC in SQL text", "api": "CommandType.Text",
                          "params": [], "output_params": 0, "return_value": False, "tvp": False, "sqldbtypes": [], "next_result": 0,
                          "columns_read": [], "xml_reader": False})
    by_proc = defaultdict(list)
    for s in procs:
        by_proc[s["name"]].append(s)
    proc_list = []
    for nm, ss in sorted(by_proc.items(), key=lambda x: (-len(x[1]), x[0].lower())):
        proc_list.append({"name": nm, "call_sites": len(ss), "files": sorted({s["file"] for s in ss}),
                          "apis": sorted({s["api"] for s in ss}), "params": sorted({p for s in ss for p in s["params"]}),
                          "output_params": sum(s["output_params"] for s in ss), "return_value": any(s["return_value"] for s in ss),
                          "tvp": any(s["tvp"] for s in ss), "multi_result": max(s["next_result"] for s in ss),
                          "for_xml": any(s["xml_reader"] for s in ss), "columns_read": sorted({c for s in ss for c in s["columns_read"]}),
                          "sites": [{k: s[k] for k in ("file", "line", "api", "how")} for s in ss]})
    # data files: only text that parses as T-SQL counts (supplier messages such as "insert into X" are not SQL)
    cands = [c for c in cands if not (c["source"].startswith("data:") and not c["parsed"])]
    for c in cands:
        t = c["text"]
        if not c["parsed"] and re.search(r"\$\w+", t) and "@" not in t:
            c["dialect"] = "not T-SQL ($-parameters: InfluxQL or similar)"
        elif not c["parsed"] and re.search(r"\bgroup\s+by\s+time\s*\(", t, re.I):
            c["dialect"] = "not T-SQL (InfluxQL)"
        else:
            c["dialect"] = "T-SQL" if c["parsed"] else "T-SQL (did not parse, review)"
    stmts = [c for c in cands if c["kind"].startswith("statement")]
    frags = [c for c in cands if c["kind"] == "fragment"]
    tables_r = Counter(t for c in stmts for t in c.get("reads", []))
    tables_w = Counter(t for c in stmts for t in c.get("writes", []))
    cons = Counter()
    for c in cands:
        cons.update(c["constructs"])
    levels = Counter()
    for c in cands:
        levels.update(c["conversion"])
    three_part = sorted({t.split(".")[0].replace("{?}", "(run-time name)") for c in stmts for t in c.get("reads", []) + c.get("writes", []) if t.count(".") >= 2})
    summary = {
        "files_scanned": dict(files_seen),
        "stored_procedures": {"distinct": len([p for p in proc_list if not p["name"].startswith("(")]), "call_sites": len(procs),
                              "wrapper_methods": len(wrappers), "via_wrappers": sum(1 for x in procs if x["how"].startswith("wrapper")),
                              "unresolved_names": sum(p["call_sites"] for p in proc_list if p["name"].startswith("(")),
                              "with_output_params": sum(1 for p in proc_list if p["output_params"]),
                              "with_return_value": sum(1 for p in proc_list if p["return_value"]),
                              "with_tvp": sum(1 for p in proc_list if p["tvp"]),
                              "multi_result": sum(1 for p in proc_list if p["multi_result"]),
                              "for_xml_readers": sum(1 for p in proc_list if p["for_xml"])},
        "raw_sql": {"statements": len(stmts), "parsed": sum(1 for c in stmts if c["parsed"]),
                    "did_not_parse": sum(1 for c in stmts if not c["parsed"]), "fragments": len(frags),
                    "dynamic": sum(1 for c in cands if c["dynamic"]), "by_source": dict(Counter(c["source"].split(":")[0] for c in cands)),
                    "by_statement": dict(Counter(s for c in stmts for s in c.get("statements", []))),
                    "by_dialect": dict(Counter(c["dialect"] for c in cands)),
                    "files": len({c["file"] for c in cands})},
        "conversion_levels": dict(levels),
        "constructs": dict(cons.most_common()),
        "tables_read": dict(tables_r.most_common()), "tables_written": dict(tables_w.most_common()),
        "databases_in_three_part_names": three_part,
        "sql_files": {"files": len(sql_files), "lines": sum(s["lines"] for s in sql_files), "objects": dict(sql_objects)},
        "data_access_api": {k: {"hits": v, "files": len(api_files[k])} for k, v in api.most_common()},
        "connection_strings": {"count": conn["connection_strings"], "files": sorted(conn["files"]),
                               "providers": dict(conn["providers"]), "databases": dict(conn["databases"])},
    }
    for c in cands:
        c["text"] = c["text"].replace(HOLE, "{?}")
        c.pop("context", None)
    out = {"repo": name, "root": root, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "engine": sp.engine(), "summary": summary,
           "wrappers": [dict(name=k, **v) for k, v in sorted(wrappers.items())], "wrappers_rejected": dropped, "procedures": proc_list, "statements": stmts, "fragments": frags}
    return out


def write(out, outdir):
    """sql-inventory.json and sql-inventory.csv."""
    os.makedirs(outdir, exist_ok=True)
    name, summary, proc_list, stmts, frags = out["repo"], out["summary"], out["procedures"], out["statements"], out["fragments"]
    levels = summary["conversion_levels"]
    jp = os.path.join(outdir, "sql-inventory.json")
    json.dump(out, open(jp, "w", encoding="utf-8"), indent=1)
    cp = os.path.join(outdir, "sql-inventory.csv")
    with open(cp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["type", "name_or_sql", "file", "line", "api_or_source", "parsed", "dynamic", "reads", "writes", "constructs",
                    "auto", "rewrite", "redesign", "flags"])
        for p in proc_list:
            for s in p["sites"]:
                flags = [f for f, on in (("OUTPUT params", p["output_params"]), ("return value", p["return_value"]), ("TVP", p["tvp"]),
                                         ("multi-result", p["multi_result"]), ("FOR XML", p["for_xml"])) if on]
                w.writerow(["stored procedure call", p["name"], s["file"], s["line"], s["api"] + " / " + s["how"], "", "", "", "", "",
                            "", "", "", "; ".join(flags)])
        for c in stmts + frags:
            w.writerow(["raw SQL " + c["kind"], " ".join(c["text"].split())[:600], c["file"], c["line"], c["source"], c["parsed"],
                        c["dynamic"], "; ".join(c.get("reads", [])), "; ".join(c.get("writes", [])),
                        "; ".join(f"{k} x{v}" for k, v in c["constructs"].items()), c["conversion"].get("auto", 0),
                        c["conversion"].get("rewrite", 0), c["conversion"].get("redesign", 0), "; ".join(x for x in (c.get("dialect", ""), c.get("parse_error", "")) if x)])
    s = summary
    print(f"{name}: {s['stored_procedures']['distinct']} stored procedures ({s['stored_procedures']['call_sites']} call sites), "
          f"{s['raw_sql']['statements']} raw SQL statements ({s['raw_sql']['parsed']} parsed), {s['raw_sql']['fragments']} fragments, "
          f"levels {dict(levels)} -> {jp}")
    return jp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default=None)
    a = ap.parse_args()
    inv = inventory(a.root, a.name)
    seen = (inv.get("summary") or {}).get("files_scanned") or {}
    if not any(seen.get(x) for x in CODE_EXT + VB_EXT):  # it inventories SQL called from code, not SQL definitions
        raise SystemExit(f"{a.root}: no C# or VB files, nothing to scan: raw_sql.py lists SQL that application code sends "
                         "(stored-procedure calls, raw statements), not the procedures a database project or script folder defines. "
                         "For SQL definitions use the SQL parser (codebase-documenter sql_parse.py --root <dir> --ext .sql,.txt).")
    write(inv, a.out)


if __name__ == "__main__":
    main()
