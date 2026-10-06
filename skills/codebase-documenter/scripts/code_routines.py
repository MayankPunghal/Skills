"""Stored procedures that application code calls by name, for repositories that hold no database scripts.

Many legacy .NET applications run hundreds of procedures whose definitions live only in the production database. The
procedure names are still in the code, so this module lists them with their call sites. It is a lead, not a schema:
parameters, tables and bodies are unknown until the DDL is exported. Shared by survey_codebase.py (adapter hints),
the generic-sql adapter (db-code-routines.md and db.json "defined": false) and sql_graph.py (graph edges).
Standard library only; comments are blanked first, so commented-out calls do not count.

What counts as a call, only in files that set CommandType.StoredProcedure (or call a helper that does):
  - new SqlCommand("Name", ...)   any ...Command class, verbatim strings too
  - cmd.CommandText = "Name"
  - a string variable or const named like sql / proc / sp / cmd / command / query assigned "Name", then used
  - Helper("Name", ...) or Helper(CONST, ...) where Helper is a method of the code base that takes the name as a string
    parameter and runs it as a stored procedure (adapter_options.generic-sql.code_only_helpers names more, and can map a
    helper to its database: {"ExecReporting": "Reporting"})
  - Dapper / EF: Query("Name", ..., commandType: CommandType.StoredProcedure); "EXEC Name ..." strings
"Name" is one identifier, optionally schema-qualified (dbo.Name, [dbo].[Name]). A const declared more than once in a file
is ambiguous and not followed.

    python <skill>/scripts/code_routines.py <source root>     # list the procedures found and their call sites
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from code_text import strip_comments  # noqa: E402

SKIP = {".git", "node_modules", "bin", "obj", "packages", ".vs", "dist", "build", "target", "__pycache__", ".venv", "venv",
        ".idea", "graphify-out", "site", "publish", "vendor", "coverage"}
NAME = r"(?:\[?[A-Za-z_]\w*\]?\.)?\[?[A-Za-z_][\w$#]*\]?"
LIT = r'@?"(' + NAME + r')"'
SP_FLAG = re.compile(r"CommandType\s*\.\s*StoredProcedure|commandType\s*:\s*CommandType\.StoredProcedure")
NEW_CMD = re.compile(r"\bnew\s+\w*Command\s*\(\s*" + LIT)
CMD_TEXT = re.compile(r"\.\s*CommandText\s*=\s*" + LIT)
CMD_TEXT_VAR = re.compile(r"\.\s*CommandText\s*=\s*([A-Za-z_]\w*)\s*;")
NEW_CMD_VAR = re.compile(r"\bnew\s+\w*Command\s*\(\s*([A-Za-z_]\w*)\s*[,)]")
VAR_ASSIGN = re.compile(r"(?:\b(?:const\s+)?(?:string|var)\s+)?\b([A-Za-z_]\w*)\s*=\s*" + LIT + r"\s*;")
VAR_NAME = re.compile(r"(?i)(sql|proc|sp|cmd|command|query|stored)")
DAPPER = re.compile(r"\.\s*(?:Query|QueryAsync|QueryFirst\w*|QuerySingle\w*|QueryMultiple\w*|Execute|ExecuteAsync|ExecuteScalar\w*|"
                    r"ExecuteReader\w*)\s*(?:<[^;()]*>)?\s*\(\s*" + LIT + r"[^;]*?commandType\s*:\s*CommandType\.StoredProcedure", re.S)
# "EXEC Name", "EXEC dbo.Name @a, @b", $"EXEC Name {id}" -- not prose such as "execute query error"
EXEC_STR = re.compile(r'"\s*(?:EXEC|EXECUTE)\s+(' + NAME + r')(?=\s*["; ]*$|\s*"|\s*;|\s+[@{?:]|\s+\d)', re.I | re.M)
METHOD = re.compile(r"(?m)^[ \t]*(?:\[[^\]\n]*\][ \t]*)*(?:(?:public|private|protected|internal|static|virtual|override|async|sealed|"
                    r"new|extern|unsafe|partial)\s+)+[\w<>\[\],.? ]+?\s+([A-Z_a-z]\w*)\s*\(([^)]*)\)\s*(?:where[^{]*)?\{")
KEYWORDS = {"if", "for", "foreach", "while", "switch", "using", "lock", "return", "catch", "new", "sizeof", "typeof", "nameof"}


def clean(name):
    parts = [p.strip("[]") for p in name.split(".")]
    return (parts[0] if len(parts) > 1 else ""), parts[-1]


def methods_in(text):
    """[(start, end, name, params)] of method bodies (brace matched on comment-free text)."""
    out = []
    for m in METHOD.finditer(text):
        if m.group(1) in KEYWORDS:
            continue
        depth, k = 0, m.end() - 1
        while k < len(text):
            ch = text[k]
            depth += (ch == "{") - (ch == "}")
            if depth == 0:
                break
            k += 1
        out.append((m.end(), k, m.group(1), m.group(2)))
    return out


def walk(root, exts=(".cs", ".vb")):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
        for f in files:
            if f.lower().endswith(exts) and not re.search(r"(?i)\.(designer|g|generated)\.(cs|vb)$", f):
                p = os.path.join(d, f)
                yield os.path.relpath(p, root).replace("\\", "/"), p


def read(p):
    try:
        return open(p, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return ""


def find(root, extra_helpers=None, files=None):
    """{"routines": {name_lower: {"name", "schema", "calls": [{"file", "line", "method", "via", "database"}]}},
        "helpers": {helper: database or ""}, "files_with_flag": n}"""
    extra_helpers = dict(extra_helpers or {})
    srcs = [(r, strip_comments(t, vb=r.lower().endswith(".vb"))) for r, t in (files or ((r, read(p)) for r, p in walk(root)))]
    # 1. helpers: methods that take the procedure name as a string parameter and run it as a stored procedure
    helpers = dict(extra_helpers)
    for rel, text in srcs:
        if not SP_FLAG.search(text):
            continue
        for a, b, name, params in methods_in(text):
            body = text[a:b]
            if not SP_FLAG.search(body):
                continue
            for pm in re.finditer(r"\bstring\s+([A-Za-z_]\w*)", params):
                pn = pm.group(1)
                if re.search(r"\.\s*CommandText\s*=\s*" + pn + r"\b|\bnew\s+\w*Command\s*\(\s*" + pn + r"\b|\(\s*" + pn
                             + r"\s*,[^;]*commandType\s*:\s*CommandType\.StoredProcedure", body):
                    helpers.setdefault(name, "")
    helper_call = re.compile(r"(?<![\w.])(?:[A-Za-z_]\w*\s*\.\s*)?(" + "|".join(map(re.escape, sorted(helpers))) + r")\s*\(\s*(?:"
                             + LIT + r"|([A-Za-z_]\w*)\s*[,)])") if helpers else None
    found, flagged = {}, 0

    def add(name, rel, text, pos, via, methods, database=""):
        schema, short = clean(name)
        if not short or short.lower() in KEYWORDS:
            return
        line = text.count("\n", 0, pos) + 1
        meth = next((mn for a, b, mn, _ in methods if a <= pos <= b), "")
        r = found.setdefault(short.lower(), {"name": short, "schema": schema, "calls": []})
        if schema and not r["schema"]:
            r["schema"] = schema
        call = {"file": rel, "line": line, "method": meth, "via": via, "database": database}
        if not any(c["file"] == rel and c["line"] == line for c in r["calls"]):
            r["calls"].append(call)
    for rel, text in srcs:
        has_flag = bool(SP_FLAG.search(text))
        if not has_flag and not (helper_call and helper_call.search(text)):
            continue
        flagged += has_flag
        methods = methods_in(text)
        consts = {}
        for m in VAR_ASSIGN.finditer(text):
            consts.setdefault(m.group(1), []).append((m.group(2), m.start()))

        def value_of(var, pos):
            """The literal a variable holds at pos: the last assignment above it in the same method (the usual
            `const string sql = "X"; Helper(sql);`), else a class-level const declared once in the file (a name declared
            with several values at class level is ambiguous and not followed)."""
            body = next(((a, b) for a, b, _, _ in methods if a <= pos <= b), None)
            hits = consts.get(var, [])
            if body:
                local = [v for v, at in hits if body[0] <= at < pos]
                if local:
                    return local[-1]
            outside = {v for v, at in hits if not any(a <= at <= b for a, b, _, _ in methods)}
            return outside.pop() if len(outside) == 1 else None
        if has_flag:
            for rx, via in ((NEW_CMD, "command text"), (CMD_TEXT, "command text"), (DAPPER, "Dapper / commandType")):
                for m in rx.finditer(text):
                    add(m.group(1), rel, text, m.start(), via, methods)
            for rx in (CMD_TEXT_VAR, NEW_CMD_VAR):
                for m in rx.finditer(text):
                    v = m.group(1)
                    val = value_of(v, m.start()) if VAR_NAME.search(v) else None
                    if val:
                        add(val, rel, text, m.start(), f"variable {v}", methods)
            for m in EXEC_STR.finditer(text):
                add(m.group(1), rel, text, m.start(), "EXEC in a string", methods)
        if helper_call:
            for m in helper_call.finditer(text):
                h, lit, var = m.group(1), m.group(2), m.group(3)
                val = lit or (value_of(var, m.start()) if var else None)
                if val:
                    add(val, rel, text, m.start(), f"helper {h}" + (f" ({var})" if var else ""), methods, helpers.get(h, ""))
    return {"routines": found, "helpers": helpers, "files_with_flag": flagged}


if __name__ == "__main__":
    res = find(sys.argv[1] if len(sys.argv) > 1 else ".")
    for k, r in sorted(res["routines"].items()):
        c = r["calls"][0]
        print(f"{(r['schema'] + '.') if r['schema'] else ''}{r['name']:<40} {len(r['calls'])} call(s)  first: {c['file']}:{c['line']} ({c['via']})")
    print(f"{len(res['routines'])} procedures named in code; helpers: {', '.join(sorted(res['helpers'])) or 'none'}", file=sys.stderr)
