"""Database access map: every place the code reaches a table, view, procedure or function, how, and from which method.

Writes docs/reference/db-access.md (anchors dba-<object>; tag [[dba:usp_PlaceOrder]]) and docs/agent/db-access.json.
Needs docs/agent/db.json (generic-sql) and, for method names, docs/agent/methods.json (method map). For each call site:
  called from   the enclosing method (linked to the method map), file:line
  how           ADO.NET, Dapper, EF Core LINQ / raw SQL / mapping, EF6, NHibernate, LINQ to SQL, JDBC / JPA, Node SQL
                clients, Python DB-API / SQLAlchemy, Go database/sql, name constant (followed to its usages), view text
  operation     read / insert / update / delete / merge / exec / call, from the SQL text or the ORM call
Tables are matched only from PARSED SQL (generic-sql parses every SQL statement embedded in string literals with Microsoft's
T-SQL parser: tables read, tables written with the operation, procedures and functions called), from object names passed
as whole string literals (CommandType.StoredProcedure, name constants), and through ORM mappings (DbSet / Set<T>,
ToTable / [Table], NHibernate ClassMap), so a class or a word that happens to share a table's name is not counted.
Static analysis: SQL built at run time, stored in config or reached through generic repositories may be missed.
Options (adapter_options.generic-dbaccess): skip_regex, max_sites (default 80 per object).
"""
import bisect
import json
import os
import re
from collections import Counter, defaultdict

from _scan import BACK, DOCS, Methods, esc, line_at, options, read, slug, walk, write_page
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

OPT = options("generic-dbaccess")
MAX_SITES = OPT.get("max_sites", 80)
CODE = {".cs", ".vb", ".fs", ".java", ".kt", ".scala", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".go", ".rb", ".php",
        ".cshtml", ".razor", ".aspx", ".ascx", ".xml", ".hbm"}
VIEW_EXT = {".cshtml", ".razor", ".aspx", ".ascx"}
STRING = re.compile(r'@"(?:[^"]|"")*"|\$?"""[\s\S]*?"""|\$?@?"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`[^`]*`')
TECH = [
    ("EF raw SQL", re.compile(r"FromSql(Raw|Interpolated)?\s*[<(]|ExecuteSql(Raw|Interpolated)?(Async)?\s*\(|SqlQuery(Raw)?\s*<|Database\.SqlQuery|ExecuteSqlCommand")),
    ("EF mapping", re.compile(r"HasDbFunction|\[DbFunction|DbFunction\(|ToFunction\(|ToView\(|ToSqlQuery\(|UsingStoredProcedure|MapToStoredProcedures|EdmFunction|ExecuteFunction")),
    ("NHibernate", re.compile(r"CreateSQLQuery|GetNamedQuery|CreateQuery\(|\bISession\b|\bQueryOver<|\bSession\.(Query|Get|Load)")),
    ("Dapper", re.compile(r"\.(Query|QueryAsync|QueryFirst\w*|QuerySingle\w*|QueryMultiple\w*|Execute|ExecuteAsync|ExecuteScalar\w*|ExecuteReader\w*)\s*(<[^>()]*>)?\s*\(")),
    ("ADO.NET", re.compile(r"\b(Sql|Npgsql|Oracle|MySql|OleDb|Odbc|SQLite|Db)Command\b|CreateCommand\(|CommandText|Execute(Reader|NonQuery|Scalar)(Async)?\s*\(|DataAdapter|SqlBulkCopy|CommandType\.StoredProcedure")),
    ("LINQ to SQL", re.compile(r"\bDataContext\b|ExecuteQuery<|ExecuteCommand\(")),
    ("JPA", re.compile(r"@Procedure|createStoredProcedureQuery|NamedStoredProcedureQuery|createNativeQuery|@Query\(")),
    ("JDBC", re.compile(r"prepareCall|prepareStatement|CallableStatement|jdbcTemplate|JdbcTemplate")),
    ("Node SQL client", re.compile(r"\.(query|execute|raw)\s*\(|knex|sequelize|\$queryRaw|\$executeRaw")),
    ("Python DB-API / SQLAlchemy", re.compile(r"cursor\.(execute|callproc|executemany)|\.execute\(\s*text\(|session\.execute")),
    ("Go database/sql", re.compile(r"\.(Query|QueryRow|Exec)(Context)?\s*\(")),
]
CONST = re.compile(r"(?:\bconst\s+\w+|\bstatic\s+readonly\s+\w+|\bstatic\s+final\s+\w+|\bfinal\s+static\s+\w+|\bConst)\s+(\w+)\s*(?:As\s+\w+\s*)?=\s*(?:[\w.]+\s*[+&]\s*)*$")


def classify(window, ext, file_text):
    if ext in VIEW_EXT:
        return "view text"
    for name, rx in TECH:
        if rx.search(window):
            if name == "Dapper" and "Dapper" not in file_text:
                continue
            if name.startswith("EF") and "System.Data.Entity" in file_text:
                return name.replace("EF", "EF6")
            return name
    return "mention"


def main():
    dbj = os.path.join(DOCS, "agent", "db.json")
    if not os.path.exists(dbj):
        print("db-access: docs/agent/db.json not found (needs generic-sql earlier in the adapters)")
        return
    db = json.load(open(dbj, encoding="utf-8"))
    objs = {}
    for r in db.get("routines", []):
        objs.setdefault(r["name"].lower(), dict(r, type=r["kind"]))
    for t in db.get("tables", []):
        objs.setdefault(t["name"].lower(), dict(t, type="table", kind="table"))
    for o in db.get("objects", []):
        objs.setdefault(o["name"].lower(), dict(o, type=o["kind"]))
    if not objs:
        print("db-access: no database objects")
        return
    skip = re.compile(OPT["skip_regex"]) if OPT.get("skip_regex") else None
    M = Methods()
    files = [(p, f) for p, f in walk(exts=CODE) if not (skip and skip.search(p)) and not re.search(r"(^|/)migrations?/|\.designer\.\w+$", p, re.I)]
    texts = {p: read(f) for p, f in files}
    sites = defaultdict(list)   # object -> [site]
    constants = {}              # const name -> (object, path, line)

    def method_window(path, line, text):
        a = M.enclosing(path, line)
        lines = text.splitlines()
        if a:
            start = M.data[a]["line"]
            nxt = [ln for ln, _ in M.by_file.get(path, []) if ln > start]
            end = min(nxt) - 1 if nxt else min(len(lines), start + 80)
            if start <= line <= end:
                return a, "\n".join(lines[max(0, line - 9):min(end, line + 8)]), "\n".join(lines[start - 1:end])
        return a, "\n".join(lines[max(0, line - 9):line + 8]), ""

    def record(obj, path, line, text, op, via="", tech=None):
        if any(x["file"] == path and x["line"] == line and x["op"] == op for x in sites[obj]):
            return  # one row per object, line and operation (an attribute can match two patterns)
        a, near, whole = method_window(path, line, text)
        ext = os.path.splitext(path)[1].lower()
        t = tech or classify(near, ext, text)
        if t == "mention" and whole:
            t = classify(whole, ext, text)
        sites[obj].append({"method": a, "file": path, "line": line, "tech": t, "op": op, "via": via})

    # SQL statements in code: parsed by generic-sql (Microsoft's T-SQL parser), one site per object the statement touches
    def key_of(name):
        k = name.split(".")[-1].lower()
        return k if k in objs and len(name.split(".")) < 3 else None
    for site in db.get("code_sql", []):
        path, line = site["file"], site["line"]
        text = texts.get(path)
        if text is None:
            continue
        seen = set()
        dyn = " (dynamic SQL)" if site.get("dynamic") else ""
        for w in site.get("writes", []):
            k = key_of(w["name"])
            if k and (k, w["op"]) not in seen:
                seen.add((k, w["op"]))
                record(k, path, line, text, w["op"] + dyn)
        for t in site.get("reads", []):
            k = key_of(t)
            if k and (k, "read") not in seen:
                seen.add((k, "read"))
                record(k, path, line, text, "read" + dyn)
        for c in site.get("calls", []) + site.get("functions", []):
            k = key_of(c)
            if k and k not in seen:
                seen.add(k)
                record(k, path, line, text, "exec" if objs[k]["type"] == "procedure" else "call")
    # object NAMES as whole string literals: procedures run with CommandType.StoredProcedure, name constants
    for path, text in texts.items():
        ext = os.path.splitext(path)[1].lower()
        for s in STRING.finditer(text):
            lit = s.group(0)
            inner = lit.lstrip("@$").strip("\"'`").strip().replace("[", "").replace("]", "")
            if not inner or " " in inner or len(inner) > 128:
                continue
            obj = inner.split(".")[-1].lower()
            if obj not in objs or (objs[obj]["type"] == "table" and "." not in inner):
                continue
            o = objs[obj]
            line = line_at(text, s.start())
            op = "exec" if o["type"] == "procedure" else "call" if o["type"] == "function" else "read"
            head = text[text.rfind("\n", 0, s.start()) + 1:s.start()]
            c = CONST.search(head)
            if c:
                owner = re.findall(r"\b(?:class|struct|record|interface|Module|Class|Structure|object)\s+(\w+)", text[:s.start()])
                constants[c.group(1)] = (obj, path, line, owner[-1] if owner else "")
                record(obj, path, line, text, op, tech="name constant")
                continue
            record(obj, path, line, text, op)
        # routines referenced as identifiers (EF function imports, DbFunction methods) outside strings
        if ext not in VIEW_EXT:
            for m in re.finditer(r"\[DbFunction\(\s*\"(\w+)\"|HasDbFunction\([^)]*?\bnameof\((\w+)\)", text):
                obj = (m.group(1) or m.group(2) or "").lower()
                if obj in objs:
                    record(obj, path, line_at(text, m.start()), text, "call", tech="EF mapping")

    # follow name constants (ProcNames.PlaceOrder = "dbo.usp_PlaceOrder") to where they are used: qualified by the declaring
    # class anywhere, bare only in the declaring file or a file that imports the class statically; a type, method or property
    # that merely shares the constant's name (record WarehouseDashboard) is not a use
    if constants:
        crx = re.compile(r"(?<![\w.])(?:(?:\w+\s*\.\s*)*?(\w+)\s*\.\s*)?(" + "|".join(re.escape(c) for c in constants) + r")\b(?![ \t]*[(<{]|[ \t]+(?!(?:Then|And|Or|AndAlso|OrElse|Is|is|as|As)\b)\w)")
        for path, text in texts.items():
            for m in crx.finditer(text):
                obj, dpath, dline, owner = constants[m.group(2)]
                line = line_at(text, m.start())
                if path == dpath and line == dline:
                    continue
                qual = m.group(1)
                if qual and owner and qual != owner:
                    continue
                if not qual and path != dpath and not (owner and re.search(r"\busing\s+static\s+[\w.]*\b" + re.escape(owner) + r"\s*;|\bImports\s+[\w.]*\b" + re.escape(owner) + r"\b", text)):
                    continue
                o = objs[obj]
                record(obj, path, line, text, "exec" if o["type"] == "procedure" else "call" if o["type"] == "function" else "read",
                       via=m.group(0))

    # ORM mappings: DbSet<E> Prop / Set<E>() with ToTable / [Table] / name match; NHibernate ClassMap<E> Table("X")
    table_of_entity, sets, ef6_sets, core_sets = {}, {}, set(), set()
    for path, text in texts.items():
        if not path.endswith((".cs", ".vb")):
            continue
        for m in re.finditer(r"\[Table\(\s*\"(\w+)\"[^\]]*\]\s*(?:\[[^\]]*\]\s*)*(?:public\s+|internal\s+)?(?:sealed\s+|partial\s+)*(?:class|record)\s+(\w+)", text):
            table_of_entity[m.group(2)] = m.group(1)
        for m in re.finditer(r"Entity<(\w+)>", text):
            seg = text[m.end():m.end() + 600]
            seg = seg.split("Entity<")[0]
            t = re.search(r"ToTable\(\s*\"(\w+)\"|ToView\(\s*\"(\w+)\"", seg)
            if t:
                table_of_entity[m.group(1)] = t.group(1) or t.group(2)
        for m in re.finditer(r"ClassMap<(\w+)>[\s\S]{0,800}?\bTable\(\s*\"(?:\w+\.)?\[?(\w+)\]?\"", text):
            table_of_entity.setdefault(m.group(1), m.group(2))
        for m in re.finditer(r"\b(?:I?DbSet)<(\w+)>\s+(\w+)", text):
            sets[m.group(2)] = m.group(1)
            (ef6_sets if "System.Data.Entity" in text else core_sets).add(m.group(2))

    def table_for(entity, prop=None):
        for cand in (table_of_entity.get(entity), entity, prop, (prop or "")[:-1], entity + "s", entity + "es"):
            if cand and cand.lower() in objs and objs[cand.lower()]["type"] in ("table", "view"):
                return cand.lower()
        return None
    if sets:
        prx = re.compile(r"\b(\w*(?:db|Db|DB|context|Context|ctx|Ctx|session|Session)\w*|this)\s*\.\s*(" + "|".join(re.escape(p) for p in sets) + r")\b(?!\s*[{;=]\s*(?:get|set)?)")
        for path, text in texts.items():
            if not path.endswith((".cs", ".vb")):
                continue
            strs = [(s.start(), s.end()) for s in STRING.finditer(text)]
            starts = [a for a, _ in strs]
            for m in prx.finditer(text):
                i = bisect.bisect_left(starts, m.start()) - 1
                if i >= 0 and strs[i][0] < m.start() < strs[i][1]:
                    continue  # inside SQL text ("FROM dbo.Customers"), not a DbSet access
                prop = m.group(2)
                obj = table_for(sets[prop], prop)
                if not obj:
                    continue
                tail = text[m.end():text.find(";", m.end()) if text.find(";", m.end()) > 0 else m.end() + 300][:400]
                w = re.search(r"\.(AddRange|Add|AddAsync|RemoveRange|Remove|Update|UpdateRange|Attach|ExecuteUpdate\w*|ExecuteDelete\w*)\s*\(", tail)
                op = {"Add": "insert", "AddAsync": "insert", "AddRange": "insert", "Remove": "delete", "RemoveRange": "delete",
                      "Attach": "update"}.get(w.group(1), "update" if w and "Update" in w.group(1) else "delete" if w and "Delete" in w.group(1) else "read") if w else "read"
                record(obj, path, line_at(text, m.start()), text, op, via=f"DbSet {prop}",
                       tech="EF6 LINQ" if ("System.Data.Entity" in text or (prop in ef6_sets and prop not in core_sets)) else "EF Core LINQ")
    for path, text in texts.items():
        for m in re.finditer(r"\b(?:Query|QueryOver|Get|Load)<(\w+)>\s*\(", text):
            if m.group(1) in table_of_entity and "ClassMap" not in text[:0] and ("NHibernate" in text or "ISession" in text or "session" in text.lower()):
                obj = table_for(m.group(1))
                if obj:
                    record(obj, path, line_at(text, m.start()), text, "read", via=f"{m.group(0)[:-1]}", tech="NHibernate")

    # ---- write
    techs = Counter(s["tech"] for v in sites.values() for s in v)
    used = {k for k, v in sites.items() if any(s["tech"] not in ("view text", "mention") for s in v)}
    unused = sorted((objs[k] for k in objs if k not in sites), key=lambda o: (o["type"], o["name"].lower()))
    out = ["# Database access", "",
           f"Every place the code reaches a database object: the calling method, the access technology and the operation "
           f"({sum(len(v) for v in sites.values())} call sites on {len(sites)} of {len(objs)} objects). Technologies: "
           + ", ".join(f"{k} {v}" for k, v in techs.most_common()) + ". Static analysis: SQL built at run time, kept in "
           "configuration or reached through generic repositories may be missed; \"view text\" and \"mention\" rows are "
           "references, not proven calls.", "", '<a id="index"></a>', "",
           "| Object | Kind | Call sites | Technologies | Operations |", "| --- | --- | ---: | --- | --- |"]
    order = sorted(sites, key=lambda k: (objs[k]["type"], objs[k]["name"].lower()))
    for k in order:
        o, ss = objs[k], sites[k]
        out.append(f"| [{esc(o['name'])}](#{slug('dba', o['name'])}) | {o['type']} | {len(ss)} | "
                   f"{', '.join(sorted({s['tech'] for s in ss}))} | {', '.join(sorted({s['op'] for s in ss}))} |")
    if unused:
        out += ["", f"**No call site found in code ({len(unused)}):** " + ", ".join(
            f"[{esc(o['name'])}]({o['page']}#{o['anchor']}) ({o['type']})" for o in unused)
            + ". They may be called by other databases, jobs, reports or external systems; check before calling them unused."]
    for k in order:
        o, ss = objs[k], sites[k]
        sig = ""
        if o["type"] != "table":
            sig = (f" · parameters: `{esc(', '.join(o.get('params') or [])) or 'none'}`" + (f" · returns: {esc(o['returns'])}" if o.get("returns") else ""))
        out += ["", f'<a id="{slug("dba", o["name"])}"></a>', "", f"## {o['name']} ({o['type']})", "",
                f"Definition: [{esc(o['name'])}]({o['page']}#{o['anchor']}){sig} · {BACK}", "",
                "| Called from | How | Operation | Source |", "| --- | --- | --- | --- |"]
        for s in sorted(ss, key=lambda s: (s["tech"] in ("view text", "mention"), s["file"], s["line"]))[:MAX_SITES]:
            frm = M.link(s["method"]) or "—"
            how = s["tech"] + (f" (via `{esc(s['via'])}`)" if s["via"] else "")
            out.append(f"| {frm} | {how} | {s['op']} | `{esc(s['file'])}:{s['line']}` |")
        if len(ss) > MAX_SITES:
            out.append(f"| … {len(ss) - MAX_SITES} more | | | |")
    write_page("db-access.md", out)
    data = {objs[k]["name"]: [dict(s, method=(M.data.get(s["method"]) or {}).get("name"), anchor=s["method"]) for s in sites[k]] for k in order}
    os.makedirs(os.path.join(DOCS, "agent"), exist_ok=True)
    open(os.path.join(DOCS, "agent", "db-access.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(data, ensure_ascii=False, indent=1))
    stat("db-access", sites=sum(len(v) for v in sites.values()), objects=len(objs), objects_reached=len(sites), objects_called=len(used))
    print(f"db-access: {sum(len(v) for v in sites.values())} call sites on {len(sites)}/{len(objs)} objects ({len(used)} with real calls); "
          + ", ".join(f"{k} {v}" for k, v in techs.most_common(6)))


if __name__ == "__main__":
    main()
