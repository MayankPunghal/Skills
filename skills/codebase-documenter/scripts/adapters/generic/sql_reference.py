"""Generic SQL reference adapter: tables (columns, keys, FKs, referenced-by) and routines (procedures, functions,
views, triggers: parameters, tables touched, SQL callers, application callers) from `.sql` DDL files.

Works for SQL Server / SSDT projects and plain migration or schema folders. Options (codebase-docs.json):
  "adapter_options": {"generic-sql": {"databases": [
      {"name": "Main", "path": "db/schema", "tables_page": "db-tables.md", "routines_page": "db-routines.md"},
      {"name": "Reporting", "path": "reporting", "tables_page": "reportdb-tables.md", "routines_page": "reportdb-routines.md"}],
    "edmx": ["Web/Models/Model.edmx"],             # optional ORM alias maps (EF function imports)
    "code_ext": [".cs", ".py", ".ts", ".js", ".java", ".cshtml"]}}
Without "databases", every folder under the source root that contains CREATE TABLE statements is one database
(the first found writes db-tables.md / db-routines.md, others <folder>-tables.md / -routines.md).
Run by build_site.py (cwd = workspace root).
"""
import json
import os
import re
from collections import defaultdict

CFG = json.load(open("codebase-docs.json", encoding="utf-8"))
ROOT = os.environ.get("DOCS_SOURCE_ROOT") or CFG.get("source_root", ".")
OUT = os.path.join(CFG.get("docs_dir", "docs"), "reference")
OPT = CFG.get("adapter_options", {}).get("generic-sql", {})
SKIP_DIRS = {"bin", "obj", "packages", ".vs", "node_modules", ".git", "dist", "build", "vendor", "graphify-out"}
CODE_EXT = tuple(OPT.get("code_ext", [".cs", ".vb", ".cshtml", ".razor", ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".kt",
                                       ".go", ".rb", ".php", ".scala", ".rs"]))
BACK = "[↑ Back to index](#index)"
_CODE_CACHE = None


def code_files():
    """(relpath, text) for hand-written application code (generated / minified files excluded)."""
    global _CODE_CACHE
    if _CODE_CACHE is None:
        _CODE_CACHE = []
        for p in walk(ROOT, CODE_EXT):
            r = rel(p)
            if re.search(r"\.(designer|generated|g)\.\w+$|\.min\.js$|/(Web|Service) References/|/migrations?/", r, re.I):
                continue
            _CODE_CACHE.append((r, read(p)))
    return _CODE_CACHE


def walk(base, exts):
    for d, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith('.')]
        for f in files:
            if f.lower().endswith(exts):
                yield os.path.join(d, f)


def read(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if len(raw) > 3 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        return raw.decode("utf-16-le")
    return raw.decode("utf-8-sig", errors="replace")


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def write(name, text):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def slug(*parts):
    return re.sub(r"[^a-z0-9]+", "-", "-".join(parts).lower()).strip("-")


def anchor(aid):
    return f'<a id="{aid}"></a>'


def md_escape(s):
    return s.replace("|", "\\|").strip()


def split_columns(body):
    depth, cur, parts = 0, "", []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def iter_create_tables(text):
    """Every CREATE TABLE in a script (several per file allowed): (schema, name, column-list body)."""
    rx = re.compile(r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                    r"(?:[\[\"`]?(\w+)[\]\"`]?\.)?[\[\"`]?([\w ]+?)[\]\"`]?\s*\(", re.I)
    for m in rx.finditer(text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        yield (m.group(1) or "dbo"), m.group(2).strip(), text[m.end():i - 1]


def gen_tables(dbroot, title, fname, prefix="tbl"):
    tables = []
    for path in sorted(walk(dbroot, (".sql",))):
        text = re.sub(r"--[^\n]*", "", read(path))
        for schema, name, body in iter_create_tables(text):
            cols, fks = [], []
            for part in split_columns(body):
                up = part.upper()
                if up.startswith("CONSTRAINT") or up.startswith("PRIMARY KEY") or up.startswith("FOREIGN KEY") or up.startswith("UNIQUE") or up.startswith("INDEX"):
                    fk = re.search(r"FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+(?:\[?\w+\]?\.)?\[?(\w+)\]?\s*\(([^)]*)\)", part, re.I)
                    if fk:
                        fks.append((fk.group(1).replace("[", "").replace("]", "").strip(), fk.group(2), fk.group(3).replace("[", "").replace("]", "").strip()))
                    continue
                cm = re.match(r"\[?([\w ]+?)\]?\s+(.*)", part, re.S)
                if not cm:
                    continue
                cname, rest = cm.group(1), re.sub(r"\s+", " ", cm.group(2))
                tm = re.match(r"(\[?\w+\]?\s*(?:\([^)]*\))?)", rest)
                ctype = tm.group(1).replace("[", "").replace("]", "") if tm else rest
                if rest.upper().startswith("AS "):
                    ctype = "computed: " + rest[3:]
                nullable = "NOT NULL" not in rest.upper() and "PRIMARY KEY" not in rest.upper()
                ident = "IDENTITY" in rest.upper()
                dflt = re.search(r"DEFAULT\s*(\(.*?\)\)?|'[^']*'|\S+)", rest, re.I)
                notes = []
                if ident:
                    notes.append("identity")
                if "PRIMARY KEY" in rest.upper():
                    notes.append("PK")
                if dflt:
                    notes.append("default " + dflt.group(1))
                inline = re.search(r"REFERENCES\s+(?:[\[\"`]?\w+[\]\"`]?\.)?[\[\"`]?(\w+)[\]\"`]?\s*\(([^)]*)\)", rest, re.I)
                if inline:  # column-level FK (PostgreSQL / MySQL / SQLite style)
                    fks.append((cname, inline.group(1), inline.group(2).strip(" []\"`")))
                    notes.append("FK")
                cols.append((cname, ctype, "yes" if nullable else "no", ", ".join(notes)))
            for fk in re.finditer(r"FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+(?:\[?\w+\]?\.)?\[?(\w+)\]?\s*\(([^)]*)\)", body, re.I):
                t = (fk.group(1).replace("[", "").replace("]", "").strip(), fk.group(2), fk.group(3).replace("[", "").replace("]", "").strip())
                if t not in fks:
                    fks.append(t)
            tables.append((schema, name.strip(), rel(path), cols, fks))
            DB_EXPORT["tables"].append({"name": name.strip(), "schema": schema, "columns": [f"{c[0]} {c[1]}" for c in cols],
                                        "file": rel(path), "page": fname, "anchor": slug(prefix, name.strip())})
    names = {t[1].strip().lower() for t in tables}
    referenced_by = defaultdict(set)
    for schema, name, p, cols, fks in tables:
        for col, tgt, tcol in fks:
            referenced_by[tgt.lower()].add((name.strip(), col))
    out = [f"# {title}", "", "Every table defined in the database project, extracted from its `CREATE TABLE` script. "
           "Click a table name to jump to its column breakdown; foreign keys link to the referenced table.",
           "", f"Total tables: {len(tables)}.", "", anchor("index"), "", "| Table | Columns | File |", "| --- | --- | --- |"]
    for schema, name, p, cols, _ in sorted(tables, key=lambda t: t[1].lower()):
        out.append(f"| [{schema}.{name.strip()}](#{slug(prefix, name.strip())}) | {len(cols)} | `{p}` |")
    for schema, name, p, cols, fks in sorted(tables, key=lambda t: t[1].lower()):
        name = name.strip()
        out += ["", anchor(slug(prefix, name)), "", f"## {schema}.{name}", "", f"Source: `{p}` · {BACK}", "",
                "| Column | Type | Nullable | Notes |", "| --- | --- | --- | --- |"]
        for c in cols:
            out.append("| " + " | ".join(md_escape(x) for x in c) + " |")
        refs = referenced_by.get(name.lower())
        if fks:
            out += ["", "**Foreign keys (this table → referenced table):**", ""]
            for col, tgt, tcol in fks:
                tl = f"[`{tgt}`](#{slug(prefix, tgt)})" if tgt.lower() in names else f"`{tgt}`"
                out.append(f"- `{col}` → {tl} `.{tcol}`")
        if refs:
            out += ["", "**Referenced by:** " + ", ".join(f"[`{t}`](#{slug(prefix, t)}).`{c}`" for t, c in sorted(refs))]
    write(fname, "\n".join(out) + "\n")
    return len(tables)


def known_objects(dbroot):
    names = set()
    for path in walk(dbroot, (".sql",)):
        for m in re.finditer(r"CREATE\s+(?:TABLE|VIEW|FUNCTION|SYNONYM)\s+(?:\[?\w+\]?\.)?\[?(\w+)\]?", read(path), re.I):
            names.add(m.group(1).lower())
    return names


def parse_params(sig):
    """Full parameter list as written: '@OrderId int OUTPUT', '@Lines dbo.OrderLineType READONLY', 'OUT total numeric'."""
    s = re.sub(r"\s+", " ", sig).strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    parts = [p.strip() for p in split_columns(s) if p.strip()]
    if any(p.startswith("@") for p in parts):
        parts = [p for p in parts if p.startswith("@")]
    return [p for p in parts if re.match(r"(?i)(@|(?:IN|OUT|INOUT|VARIADIC)\s+)?\w", p)]


def select_columns(sql):
    """Column names of the first SELECT list (aliases preferred), at most 10."""
    m = re.search(r"\bSELECT\s+(?:DISTINCT\s+|TOP\s*\(?\s*\d+\s*\)?\s+)?(.*?)\bFROM\b", sql, re.S | re.I)
    if not m:
        return []
    cols = []
    for c in split_columns(m.group(1)):
        c = re.sub(r"\s+", " ", c).strip()
        alias = re.search(r"(?i)\bAS\s+\[?\"?(\w+)", c) or re.match(r"\[?(\w+)\]?\s*=", c) or re.search(r"[\[.\s\"]?(\w+)\]?\"?$", c)
        cols.append(alias.group(1) if alias else c[:30])
    return cols[:10] + (["…"] if len(cols) > 10 else [])


def returns_of(kind, sig_tail, head, body, params):
    """What a routine gives back: function return type, procedure OUTPUT params / RETURN codes / result sets, view columns."""
    if kind == "FUNCTION":
        m = re.match(r"\s*RETURNS\s+(@\w+\s+)?TABLE\s*\((.*?)\)\s*(?:AS|WITH|BEGIN)", sig_tail, re.S | re.I)
        if m:
            cols = [re.match(r"\s*\[?(\w+)", c).group(1) for c in split_columns(m.group(2)) if re.match(r"\s*\[?\w+", c) and not re.match(r"(?i)\s*(PRIMARY|UNIQUE|INDEX|CHECK|CONSTRAINT)\b", c)]
            return f"table ({', '.join(cols[:10])})"
        if re.match(r"\s*RETURNS\s+TABLE\b(?!\s*\()", sig_tail, re.I):
            cols = select_columns(body)
            return "table (inline" + (f": {', '.join(cols)}" if cols else "") + ")"
        m = re.match(r"\s*RETURNS\s+(SETOF\s+[\w.]+|TABLE\s*\([^)]*\)|[\w.\[\]]+(?:\s*\([^)]*\))?)", sig_tail, re.I)
        return re.sub(r"\s+", " ", m.group(1)).replace("[", "").replace("]", "") if m else ""
    if kind == "PROCEDURE":
        out = [p.split()[0] for p in params if re.search(r"(?i)\b(OUTPUT|OUT)\b|^(OUT|INOUT)\s", p)]
        codes = sorted(set(re.findall(r"(?i)\bRETURN\s+(-?\d+|@\w+)", body)), key=str)
        sets = [s for s in re.finditer(r"(?im)^\s*SELECT\s+(?!@\w+\s*=)", body)  # not INSERT … SELECT, subqueries, EXISTS
                if not re.search(r"(?is)(INSERT\s+(INTO\s+)?[^;]*|\(\s*|EXISTS\s*\(\s*|UNION(\s+ALL)?\s*|=\s*)$", body[max(0, s.start() - 300):s.start()])]
        bits = []
        if out:
            bits.append("OUTPUT " + ", ".join(out))
        if codes:
            bits.append("RETURN " + ", ".join(codes[:6]))
        if sets:
            cols = select_columns(body[sets[0].start():])
            bits.append(f"result sets ~{len(sets)}" + (f" (first: {', '.join(cols)})" if cols else ""))
        return "; ".join(bits)
    if kind == "VIEW":
        cols = select_columns(body)
        return f"rows ({', '.join(cols)})" if cols else ""
    if kind == "TRIGGER":
        m = re.search(r"\bON\s+([\w.\[\]]+)\s+(AFTER|FOR|INSTEAD\s+OF|BEFORE)\s+([\w ,]+)", head, re.I)
        return f"{m.group(2).upper()} {re.sub(r'[ ]+', ' ', m.group(3)).strip().upper()} on {m.group(1).replace('[', '').replace(']', '')}" if m else ""
    return ""


DB_EXPORT = {"routines": [], "tables": []}


def gen_routines(dbroot, title, fname, prefix="sp", table_page="db-tables.md", table_prefix="tbl"):
    known = known_objects(dbroot)
    rt_re = re.compile(r"CREATE\s+(?:OR\s+(?:ALTER|REPLACE)\s+)?(PROCEDURE|PROC|FUNCTION|VIEW|TRIGGER)\s+(?:\[?(\w+)\]?\.)?\[?([\w\-]+)\]?(.*?)(?:\bAS\b|\bRETURNS\b|\bWITH\b)", re.S | re.I)
    items = []
    for path in sorted(walk(dbroot, (".sql",))):
        raw = read(path)
        text = re.sub(r"--[^\n]*", "", raw)
        ms = list(rt_re.finditer(text))  # several routines per script are allowed (migrations)
        for k, m in enumerate(ms):
            kind = {"PROC": "PROCEDURE"}.get(m.group(1).upper(), m.group(1).upper())
            full = parse_params(m.group(4)) if kind in ("PROCEDURE", "FUNCTION") else []
            params = [(p.split(" ", 1) + [""])[:2] for p in full]
            body = text[m.end():ms[k + 1].start() if k + 1 < len(ms) else len(text)]
            tables = sorted(set(t for t in re.findall(r"(?:FROM|JOIN|INTO|UPDATE|MERGE)\s+(?:\[?dbo\]?\.)?\[?([A-Za-z_]\w+)\]?", body, re.I)
                                if t.lower() in known))
            rets = returns_of(kind, text[m.end(4):m.end(4) + 1500], m.group(4), body, full)
            items.append((kind, m.group(3), rel(path), params, tables, rets))
            DB_EXPORT["routines"].append({"name": m.group(3), "schema": m.group(2) or "", "kind": kind.lower(), "params": full,
                                          "returns": rets, "touches": tables, "file": rel(path),
                                          "line": text.count("\n", 0, m.start()) + 1, "page": fname, "anchor": slug(prefix, m.group(3))})
    table_names = set()
    for path in walk(dbroot, (".sql",)):
        for _, tname, _ in iter_create_tables(read(path)):
            table_names.add(tname.lower())
    routine_names = {i[1].lower() for i in items}
    used_by = defaultdict(set)
    word = re.compile(r"[A-Za-z_]\w+")
    # EF function imports can have a different C# name than the stored procedure (e.g. X_Func -> X)
    alias = {}
    for edmx in (os.path.join(ROOT, p) for p in OPT.get("edmx", [])) if OPT.get("edmx") else walk(ROOT, (".edmx",)):
        for imp, fn in re.findall(r'FunctionImportName="(\w+)"\s+FunctionName="[\w.]*?\.(\w+)"', read(edmx)):
            if fn.lower() in routine_names:
                alias[imp.lower()] = fn.lower()
    for fp, txt in code_files():
        for w in set(word.findall(txt)):
            lw = w.lower()
            target = lw if lw in routine_names else alias.get(lw)
            if target:
                used_by[target].add(fp)
    callers_sql = defaultdict(set)
    for kind, name, p, params, tables, _ in items:
        for t in tables:
            if t.lower() in routine_names and t.lower() != name.lower():
                callers_sql[t.lower()].add(name)
    for path in walk(dbroot, (".sql",)):
        txt = re.sub(r"--[^\n]*", "", read(path))
        m = rt_re.search(txt)
        if not m:
            continue
        for ex in re.findall(r"\bEXEC(?:UTE)?\s+(?:@\w+\s*=\s*)?(?:\[?dbo\]?\.)?\[?(\w+)\]?", txt, re.I):
            if ex.lower() in routine_names and ex.lower() != m.group(3).lower():
                callers_sql[ex.lower()].add(m.group(3))

    def link_obj(t):
        if t.lower() in routine_names:
            return f"[{t}](#{slug(prefix, t)})"
        if t.lower() in table_names:
            return f"[{t}]({table_page}#{slug(table_prefix, t)})"
        return t

    out = [f"# {title}", "", "Every stored procedure, function, view and trigger in the database project, extracted from source.",
           "",
           "- **Touches**: tables, views and functions this routine reads or writes (FROM / JOIN / INTO / UPDATE / MERGE). Each links to its definition.",
           "- **Called by (SQL)**: other routines that EXEC it or select from it.",
           "- **Returns**: function return type (scalar or table columns); for procedures OUTPUT parameters, RETURN codes and result sets (estimated from top-level SELECTs); view columns; trigger events.",
           "- **Used by (application)**: code files that mention the routine by name; the call-site link (when `generic-dbaccess` runs) shows each calling method, the access technology (ADO.NET, Dapper, EF, …) and the operation.",
           "", anchor("index"), ""]
    for kind in ("PROCEDURE", "FUNCTION", "VIEW", "TRIGGER"):
        group = sorted([i for i in items if i[0] == kind], key=lambda i: i[1].lower())
        if group:
            out.append(f"- [{kind.title()}s ({len(group)})](#{slug('kind', kind)})")
    for kind in ("PROCEDURE", "FUNCTION", "VIEW", "TRIGGER"):
        group = sorted([i for i in items if i[0] == kind], key=lambda i: i[1].lower())
        if not group:
            continue
        out += ["", anchor(slug("kind", kind)), "", f"## {kind.title()}s ({len(group)})", "", BACK, "",
                "| Name | Parameters | Returns | Touches | Called by (SQL) | Used by (application) | File |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for _, name, p, params, tables, rets in group:
            ps = ", ".join(f"{a} {b}".strip() for a, b in params)
            touches = ", ".join(link_obj(t) for t in tables[:30]) + (" …" if len(tables) > 30 else "")
            callers = ", ".join(f"[{c}](#{slug(prefix, c)})" for c in sorted(callers_sql.get(name.lower(), []))[:15])
            users = sorted(used_by.get(name.lower(), []))
            ushow = ", ".join(f"`{u.split('/')[-1]}`" for u in users[:8]) + (f" (+{len(users) - 8})" if len(users) > 8 else "")
            if users:
                ushow += f" · [call sites](db-access.md#{slug('dba', name)})"
            out.append(f"| {anchor(slug(prefix, name))}**{name}** | {md_escape(ps)} | {md_escape(rets) or '—'} | {touches} | {callers} | {ushow} | `{p}` |")
    write(fname, "\n".join(out) + "\n")
    return len(items)

def find_databases():
    if OPT.get("databases"):
        return [(d["name"], os.path.join(ROOT, d["path"]), d.get("tables_page"), d.get("routines_page")) for d in OPT["databases"]]
    roots = []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        if any(f.lower().endswith(".sqlproj") for f in files):
            roots.append(d)
            dirs[:] = []
    if not roots:  # no SSDT projects: the shallowest folders holding CREATE TABLE scripts
        hits = set()
        for p in walk(ROOT, (".sql",)):
            if re.search(r"CREATE\s+TABLE", read(p)[:20000], re.I):
                hits.add(os.path.dirname(p))
        for h in sorted(hits, key=len):
            if not any(h.startswith(r + os.sep) for r in roots):
                roots.append(h)
        roots = roots[:6]
    out = []
    for k, r in enumerate(roots):
        name = os.path.basename(r.rstrip("/\\")) or "Database"
        pre = "db" if k == 0 else slug(name)
        out.append((name, r, f"{pre}-tables.md", f"{pre}-routines.md"))
    return out


if __name__ == "__main__":
    dbs = find_databases()
    if not dbs:
        print("generic-sql: no SQL DDL found under", ROOT)
    for name, path, tp, rp in dbs:
        tp = tp or "db-tables.md"
        rp = rp or "db-routines.md"
        print(f"generic-sql [{name}] tables", gen_tables(path, f"Database tables ({name})", tp))
        print(f"generic-sql [{name}] routines", gen_routines(path, f"Stored procedures, functions and views ({name})", rp, table_page=tp))
    if dbs:  # machine-readable copy for generic-dbaccess, tools and retrieval
        agent = os.path.join(CFG.get("docs_dir", "docs"), "agent")
        os.makedirs(agent, exist_ok=True)
        with open(os.path.join(agent, "db.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(DB_EXPORT, fh, ensure_ascii=False, indent=1)
