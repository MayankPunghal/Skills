"""Generic SQL reference adapter: every database object, PARSED (Microsoft's T-SQL parser via scripts/sql_parse.py; sqlglot
fallback), never pattern-matched.

Pages (per database):
  db-tables.md     every table: columns (type, nullability, identity, default, computed, collation, PK / unique / FK,
                   rowversion), keys, foreign keys both ways, indexes (inline and CREATE INDEX), checks, temporal /
                   memory-optimized / graph flags, the routines that read and write it, and PostgreSQL type notes
  db-routines.md   every procedure, function, view and trigger: parameters (direction, default, READONLY), what it returns
                   (scalar / table / OUTPUT parameters / RETURN value / result sets), tables read and written (with the
                   operation), procedures and functions called, called by (SQL), used by (application), temp tables,
                   dynamic SQL, and the PostgreSQL conversion levels of its constructs; plus types, sequences, synonyms,
                   security policies and aggregates
  db-postgres.md   PostgreSQL conversion map (option postgres_notes, default on): construct levels per object, everything
                   that has no PostgreSQL equivalent with the replacement approach, data types to map, SQL embedded in code
Options (codebase-docs.json):
  "adapter_options": {"generic-sql": {"databases": [
      {"name": "Main", "path": "db/schema", "tables_page": "db-tables.md", "routines_page": "db-routines.md"},
      {"name": "Reporting", "path": "reporting", "tables_page": "reportdb-tables.md", "routines_page": "reportdb-routines.md"}],
    "edmx": ["Web/Models/Model.edmx"],             # optional ORM alias maps (EF function imports)
    "postgres_notes": true,                        # db-postgres.md and PostgreSQL columns
    "code_ext": [".cs", ".py", ".ts", ".js", ".java", ".cshtml"]}}
Without "databases", every folder holding a .sqlproj is one database, else the shallowest folders whose scripts define
tables (the first found writes db-tables.md / db-routines.md, others <folder>-tables.md / -routines.md).
Writes docs/agent/db.json (machine-readable copy for generic-dbaccess, tracing, RAG cards). Run by build_site.py.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import sql_parse  # noqa: E402
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

CFG = json.load(open("codebase-docs.json", encoding="utf-8"))
ROOT = os.environ.get("DOCS_SOURCE_ROOT") or CFG.get("source_root", ".")
OUT = os.path.join(CFG.get("docs_dir", "docs"), "reference")
OPT = CFG.get("adapter_options", {}).get("generic-sql", {})
SKIP_DIRS = {"bin", "obj", "packages", ".vs", "node_modules", ".git", "dist", "build", "vendor", "graphify-out"}
CODE_EXT = tuple(OPT.get("code_ext", [".cs", ".vb", ".cshtml", ".razor", ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".kt",
                                       ".go", ".rb", ".php", ".scala", ".rs"]))
PG_NOTES = OPT.get("postgres_notes", True)
BACK = "[↑ Back to index](#index)"
ROUTINE_KINDS = ("PROCEDURE", "FUNCTION", "VIEW", "TRIGGER")
OTHER_KINDS = ("TYPE", "SEQUENCE", "SYNONYM", "SECURITY POLICY", "AGGREGATE")
DB_EXPORT = {"routines": [], "tables": [], "objects": [], "engine": None}
_CODE_CACHE = None
_PG = None


def pg_table():
    global _PG
    if _PG is None:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "pg_conversion.json")
        _PG = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    return _PG


def conversion(label):
    pg = pg_table()
    if not pg:
        return {"level": "rewrite", "pg": ""}
    if label in pg["constructs"]:
        return pg["constructs"][label]
    for prefix, table in (("fn: ", "functions"), ("global: ", "globals"), ("data type: ", "data_types")):
        if label.startswith(prefix):
            k = label[len(prefix):]
            return pg[table].get(k) or pg[table].get(k.upper()) or pg["prefix_defaults"].get(prefix) or pg["default"]
    return pg["default"]


def type_conversion(sql_type):
    base = (sql_type or "").split("(")[0].strip().lower()
    if "(max)" in (sql_type or "").lower():
        base = base or "(max)"
    return (pg_table().get("data_types") or {}).get(base)


def code_files():
    """(relpath, text) for hand-written application code (generated / minified files excluded)."""
    global _CODE_CACHE
    if _CODE_CACHE is None:
        _CODE_CACHE = []
        for p in sql_parse.walk(ROOT, CODE_EXT, SKIP_DIRS):
            r = rel(p)
            if re.search(r"\.(designer|generated|g)\.\w+$|\.min\.js$|/(Web|Service) References/|/migrations?/", r, re.I):
                continue
            _CODE_CACHE.append((r, sql_parse.read_text(p)))
    return _CODE_CACHE


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


def md(s):
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def short(name):
    return name.split(".")[-1]


class Db:
    """One database: the parsed objects of its scripts, merged (ALTER TABLE ADD folds into its table)."""

    def __init__(self, name, path, results):
        self.name, self.path = name, path
        self.objects = []
        for r in results:
            for o in r.get("objects", []):
                if not o.get("name") or short(o["name"]).startswith(("#", "@")):
                    continue
                self.objects.append(dict(o, file=r["id"]))
        self.errors = [(r["id"], e) for r in results for e in r.get("errors", [])]
        tables = {}
        for o in self.objects:
            if o["kind"] == "TABLE" and str(o.get("verb", "")).startswith("create"):
                tables.setdefault(o["name"].lower(), o)
        merged = []
        for o in self.objects:
            t = tables.get(o["name"].lower())
            if o["kind"] == "TABLE" and o.get("verb") == "alter" and t is not None and t is not o:
                t["foreign_keys"] = (t.get("foreign_keys") or []) + (o.get("foreign_keys") or [])
                t["columns"] = (t.get("columns") or []) + (o.get("columns") or [])
                t["checks"] = (t.get("checks") or []) + (o.get("checks") or [])
                if o.get("primary_key") and not t.get("primary_key"):
                    t["primary_key"] = o["primary_key"]
                continue
            merged.append(o)
        self.objects = merged
        self.indexes = defaultdict(list)
        for o in self.objects:
            if o["kind"] == "INDEX":
                self.indexes[o["name"].lower()].append(o)
        counts = Counter(short(o["name"]).lower() for o in self.objects if o["kind"] != "INDEX")
        self.anchor_name = {o["name"].lower(): (short(o["name"]) if counts[short(o["name"]).lower()] == 1 else o["name"])
                            for o in self.objects if o["kind"] != "INDEX"}
        self.by_name = {o["name"].lower(): o for o in self.objects if o["kind"] != "INDEX"}
        self.by_short = defaultdict(list)
        for o in self.objects:
            if o["kind"] != "INDEX":
                self.by_short[short(o["name"]).lower()].append(o)

    def resolve(self, name):
        n = name.lower()
        if n in self.by_name:
            return self.by_name[n]
        if len(n.split(".")) >= 3:
            return None
        if "dbo." + n in self.by_name:
            return self.by_name["dbo." + n]
        c = self.by_short.get(n.split(".")[-1], [])
        return c[0] if len(c) == 1 else None

    def of(self, *kinds):
        return sorted((o for o in self.objects if o["kind"] in kinds), key=lambda o: short(o["name"]).lower())


def find_databases(results):
    """[(name, path, tables_page, routines_page)] from options, .sqlproj folders, or the folders whose scripts define tables."""
    if OPT.get("databases"):
        return [(d["name"], os.path.join(ROOT, d["path"]), d.get("tables_page"), d.get("routines_page")) for d in OPT["databases"]]
    roots = []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        if any(f.lower().endswith(".sqlproj") for f in files):
            roots.append(d)
            dirs[:] = []
    if not roots:
        hits = sorted({os.path.dirname(os.path.join(ROOT, r["id"])) for r in results
                       if any(o.get("kind") == "TABLE" for o in r.get("objects", []))}, key=len)
        if not hits:  # no tables: any folder with routines
            hits = sorted({os.path.dirname(os.path.join(ROOT, r["id"])) for r in results if r.get("objects")}, key=len)
        for h in hits:
            if not any(os.path.normpath(h).startswith(os.path.normpath(r) + os.sep) for r in roots):
                roots.append(h)
        roots = roots[:6]
    out = []
    for k, r in enumerate(roots):
        name = os.path.basename(os.path.normpath(r)) or "Database"
        pre = "db" if k == 0 else slug(name)
        out.append((name, r, f"{pre}-tables.md", f"{pre}-routines.md"))
    return out


def col_notes(c):
    notes = []
    if c.get("identity"):
        notes.append("identity")
    if c.get("primary_key"):
        notes.append("PK")
    if c.get("unique"):
        notes.append("unique")
    if c.get("rowversion"):
        notes.append("rowversion")
    if c.get("computed"):
        notes.append(f"computed: `{c['computed']}`")
    if c.get("default"):
        notes.append(f"default `{c['default']}`")
    if c.get("collation"):
        notes.append(f"collate {c['collation']}")
    if c.get("references"):
        notes.append(f"FK → {c['references']}")
    return ", ".join(notes)


def nullable(c, pk_cols):
    if c.get("nullable") is not None:
        return "yes" if c["nullable"] else "no"
    return "no" if c.get("primary_key") or c.get("identity") or c["name"].lower() in pk_cols else "yes"


def params_text(o):
    out = []
    for p in o.get("params") or []:
        s = f"{p['name']} {p.get('type') or ''}".strip()
        if p.get("default") is not None:
            s += f" = {p['default']}"
        if p.get("output"):
            s += " OUTPUT"
        if p.get("readonly"):
            s += " READONLY"
        out.append(s)
    return out


def returns_text(o):
    k = o["kind"]
    if k == "FUNCTION":
        return o.get("returns") or ""
    if k == "PROCEDURE":
        bits = []
        outp = [p["name"] for p in o.get("params") or [] if p.get("output")]
        if outp:
            bits.append("OUTPUT " + ", ".join(outp))
        if o.get("return_value"):
            bits.append("RETURN value")
        if o.get("result_sets"):
            bits.append(f"{o['result_sets']} result set(s)")
        return "; ".join(bits)
    if k == "VIEW":
        return f"rows ({', '.join(o['columns'])})" if o.get("columns") else "rows"
    if k == "TRIGGER":
        return f"{o.get('trigger_type', '')} {', '.join(o.get('trigger_events') or [])} on {o.get('on_object', '')}".strip()
    return ""


def levels(cons):
    lv, red = Counter(), []
    for k, n in (cons or {}).items():
        c = conversion(k)
        lv[c["level"]] += n
        if c["level"] == "redesign":
            red.append(k)
    return lv, sorted(red)


def pg_cell(o):
    lv, red = levels(o.get("constructs"))
    if not lv:
        return "—"
    s = " · ".join(f"{k} {lv[k]}" for k in ("auto", "rewrite", "redesign") if lv[k])
    return s + (f" — **no equivalent:** {', '.join(red)}" if red else "")


def generate(db, tables_page, routines_page, prefix_t="tbl", prefix_r="sp"):
    def link(name):
        o = db.resolve(name)
        if not o:
            return f"`{name}`"
        an = db.anchor_name[o["name"].lower()]
        if o["kind"] == "TABLE":
            return f"[{an}]({tables_page}#{slug(prefix_t, an)})"
        return f"[{an}]({routines_page}#{slug(prefix_r, an)})"

    # reverse maps: who reads / writes / calls each object
    read_by, written_by, called_by = defaultdict(set), defaultdict(set), defaultdict(set)
    for o in db.objects:
        if o["kind"] in ("TABLE", "INDEX"):
            continue
        me = o["name"]
        for t in o.get("reads", []):
            x = db.resolve(t)
            if x:
                read_by[x["name"].lower()].add(me)
        for w in o.get("writes", []):
            x = db.resolve(w["name"])
            if x:
                written_by[x["name"].lower()].add(f"{me}|{w['op']}")
        for c in (o.get("calls") or []) + (o.get("functions") or []):
            x = db.resolve(c)
            if x and x is not o:
                called_by[x["name"].lower()].add(me)
        if o.get("on_object"):
            x = db.resolve(o["on_object"])
            if x:
                called_by[x["name"].lower()].add(me)
    referenced_by = defaultdict(set)
    tables = db.of("TABLE")
    for t in tables:
        for fk in t.get("foreign_keys") or []:
            x = db.resolve(fk.get("references") or "")
            if x:
                referenced_by[x["name"].lower()].add((t["name"], ", ".join(fk.get("columns") or [])))
        for c in t.get("columns") or []:
            if c.get("references"):
                x = db.resolve(c["references"])
                if x:
                    referenced_by[x["name"].lower()].add((t["name"], c["name"]))

    # ---- tables page
    out = [f"# Database tables ({db.name})", "",
           "Every table defined in the database scripts, parsed with Microsoft's T-SQL parser. Each table lists its columns, "
           "keys and indexes, the tables it references and that reference it, and the routines that read or write it.",
           "", f"Total tables: {len(tables)}.", "", anchor("index"), "", "| Table | Columns | Read by | Written by | File |", "| --- | ---: | ---: | ---: | --- |"]
    for t in tables:
        an = db.anchor_name[t["name"].lower()]
        out.append(f"| [{t['name']}](#{slug(prefix_t, an)}) | {len(t.get('columns') or [])} | {len(read_by.get(t['name'].lower(), []))} | "
                   f"{len(written_by.get(t['name'].lower(), []))} | `{t['file']}:{t.get('line', 1)}` |")
    for t in tables:
        key = t["name"].lower()
        an = db.anchor_name[key]
        flags = [x for x, on in (("system-versioned (temporal)", t.get("temporal")), ("memory-optimized", t.get("memory_optimized")),
                                 (f"graph {t.get('graph')}", t.get("graph"))) if on]
        pk = [c.lower() for c in (t.get("primary_key") or [])]
        out += ["", anchor(slug(prefix_t, an)), "", f"## {t['name']}", "",
                f"Source: `{t['file']}:{t.get('line', 1)}` · {BACK}" + (f" · **{', '.join(flags)}**" if flags else ""), ""]
        if t.get("primary_key"):
            out.append(f"Primary key: `{', '.join(t['primary_key'])}`\n")
        cols = t.get("columns") or []
        if cols:
            out += ["| Column | Type | Nullable | Notes" + (" | PostgreSQL |" if PG_NOTES else " |"),
                    "| --- | --- | --- | ---" + (" | --- |" if PG_NOTES else " |")]
            for c in cols:
                row = f"| {md(c['name'])} | {md(c.get('type') or ('computed' if c.get('computed') else ''))} | {nullable(c, pk)} | {md(col_notes(c))}"
                if PG_NOTES:
                    tc = type_conversion(c.get("type"))
                    row += f" | {md(tc['pg']) if tc and tc['level'] != 'auto' else ''}"
                out.append(row + " |")
        fks = t.get("foreign_keys") or []
        if fks:
            out += ["", "**Foreign keys (this table → referenced table):**", ""]
            for fk in fks:
                out.append(f"- `{', '.join(fk.get('columns') or [])}` → {link(fk.get('references') or '')} `({', '.join(fk.get('ref_columns') or [])})`"
                           + (f" on delete {fk['on_delete']}" if fk.get("on_delete") not in (None, "NotSpecified", "NoAction") else ""))
        if referenced_by.get(key):
            out += ["", "**Referenced by:** " + ", ".join(f"{link(n)}.`{c}`" for n, c in sorted(referenced_by[key]))]
        uq = t.get("unique_constraints") or []
        if uq:
            out += ["", "**Unique:** " + "; ".join(f"`{', '.join(u)}`" for u in uq)]
        idx = (t.get("indexes") or []) + [{"name": i.get("index"), "columns": i.get("index_columns"), "unique": i.get("unique"),
                                            "include": i.get("include"), "filter": i.get("filter")} for i in db.indexes.get(key, [])]
        if idx:
            out += ["", "**Indexes:**", ""]
            for i in idx:
                out.append(f"- `{i.get('name') or '(unnamed)'}`{' unique' if i.get('unique') else ''} on `{', '.join(i.get('columns') or [])}`"
                           + (f" include `{', '.join(i['include'])}`" if i.get("include") else "") + (f" where `{i['filter']}`" if i.get("filter") else ""))
        if t.get("checks"):
            out += ["", "**Checks:** " + "; ".join(f"`{md(c)}`" for c in t["checks"])]
        if read_by.get(key):
            out += ["", "**Read by:** " + ", ".join(link(n) for n in sorted(read_by[key]))]
        if written_by.get(key):
            w = defaultdict(set)
            for x in written_by[key]:
                n, op = x.split("|")
                w[n].add(op)
            out += ["", "**Written by:** " + ", ".join(f"{link(n)} ({', '.join(sorted(ops))})" for n, ops in sorted(w.items()))]
        if called_by.get(key):
            out += ["", "**Triggers, synonyms and policies on it:** " + ", ".join(link(n) for n in sorted(called_by[key]))]
        DB_EXPORT["tables"].append({"name": short(t["name"]), "schema": t["name"].split(".")[0] if "." in t["name"] else "dbo",
                                    "full_name": t["name"], "columns": [f"{c['name']} {c.get('type') or ''}".strip() for c in cols],
                                    "primary_key": t.get("primary_key"), "foreign_keys": fks, "file": t["file"], "line": t.get("line"),
                                    "read_by": sorted(read_by.get(key, [])), "written_by": sorted(written_by.get(key, [])),
                                    "page": tables_page, "anchor": slug(prefix_t, an)})
    write(tables_page, "\n".join(out) + "\n")

    # ---- routines page
    used_by = app_usage(db)
    routines = db.of(*ROUTINE_KINDS)
    others = db.of(*OTHER_KINDS)
    out = [f"# Stored procedures, functions, views and triggers ({db.name})", "",
           "Every routine in the database scripts, parsed with Microsoft's T-SQL parser (not pattern-matched):", "",
           "- **Reads / Writes**: tables and views it reads, and the ones it changes with the operation (insert, update, delete, merge, truncate, select-into).",
           "- **Calls**: procedures it executes and functions it uses. **Called by (SQL)**: routines that execute or use it.",
           "- **Returns**: function return type; for procedures OUTPUT parameters, RETURN value and result sets; view columns; trigger events.",
           "- **Used by (application)**: code files that name it; the call-site link (generic-dbaccess) shows the calling method, the access technology and the operation.",
           "- **PostgreSQL**: how its constructs convert (automatic / rewrite / redesign); see [PostgreSQL conversion](db-postgres.md) for details." if PG_NOTES else "",
           "", anchor("index"), ""]
    for kind in ROUTINE_KINDS + OTHER_KINDS:
        n = sum(1 for o in routines + others if o["kind"] == kind)
        if n:
            out.append(f"- [{kind.title()}s ({n})](#{slug('kind', kind)})")
    for kind in ROUTINE_KINDS:
        group = [o for o in routines if o["kind"] == kind]
        if not group:
            continue
        out += ["", anchor(slug("kind", kind)), "", f"## {kind.title()}s ({len(group)})", "", BACK]
        for o in group:
            key = o["name"].lower()
            an = db.anchor_name[key]
            ps = params_text(o)
            rets = returns_text(o)
            out += ["", anchor(slug(prefix_r, an)), "", f"### {o['name']}", "",
                    f"`{o['file']}:{o.get('line', 1)}` · {o.get('lines', 1)} lines" + (" · CLR" if o.get("clr") else "")
                    + (" · dynamic SQL" if o.get("dynamic_sql") else "") + f" · [↑ {kind.title()}s](#{slug('kind', kind)})", ""]
            rows = []
            if ps:
                rows.append(("Parameters", ", ".join(f"`{md(p)}`" for p in ps)))
            if rets:
                rows.append(("Returns", md(rets)))
            if o.get("reads"):
                rows.append(("Reads", ", ".join(link(t) for t in sorted(set(o["reads"])))))
            if o.get("writes"):
                rows.append(("Writes", ", ".join(f"{link(w['name'])} ({w['op']})" for w in o["writes"])))
            calls = sorted(set((o.get("calls") or []) + [f for f in (o.get("functions") or []) if db.resolve(f)]))
            if calls:
                rows.append(("Calls", ", ".join(link(c) for c in calls)))
            if called_by.get(key):
                rows.append(("Called by (SQL)", ", ".join(link(c) for c in sorted(called_by[key]))))
            if o.get("temp_tables"):
                rows.append(("Temp tables", ", ".join(f"`{t}`" for t in o["temp_tables"])))
            users = sorted(used_by.get(key, []))
            if users:
                rows.append(("Used by (application)", ", ".join(f"`{u}`" for u in users[:10]) + (f" (+{len(users) - 10})" if len(users) > 10 else "")
                             + f" · [call sites](db-access.md#{slug('dba', short(o['name']))})"))
            if PG_NOTES:
                rows.append(("PostgreSQL", pg_cell(o)))
            if rows:
                out += ["| | |", "| --- | --- |"] + [f"| **{a}** | {b} |" for a, b in rows]
            DB_EXPORT["routines"].append({"name": short(o["name"]), "schema": o["name"].split(".")[0] if "." in o["name"] else "",
                                          "full_name": o["name"], "kind": kind.lower(), "params": ps, "returns": rets,
                                          "touches": sorted({short(t) for t in o.get("reads", [])} | {short(w["name"]) for w in o.get("writes", [])}
                                                            | {short(c) for c in calls}),
                                          "reads": o.get("reads", []), "writes": o.get("writes", []), "calls": calls,
                                          "called_by": sorted(called_by.get(key, [])), "constructs": o.get("constructs", {}),
                                          "conversion": dict(levels(o.get("constructs"))[0]), "no_pg_equivalent": levels(o.get("constructs"))[1],
                                          "file": o["file"], "line": o.get("line"), "page": routines_page, "anchor": slug(prefix_r, an)})
    for kind in OTHER_KINDS:
        group = [o for o in others if o["kind"] == kind]
        if not group:
            continue
        out += ["", anchor(slug("kind", kind)), "", f"## {kind.title()}s ({len(group)})", "", BACK, "",
                "| Name | Details | Used by | File |", "| --- | --- | --- | --- |"]
        for o in group:
            key = o["name"].lower()
            an = db.anchor_name[key]
            det = o.get("type_kind") or ""
            if o.get("columns") and kind == "TYPE":
                det += ": " + ", ".join(f"{c['name']} {c.get('type') or ''}".strip() for c in o["columns"])
            if o.get("on_object"):
                det += f"for {link(o['on_object'])}"
            if o.get("targets"):
                det += "on " + ", ".join(link(t) for t in o["targets"])
            users = sorted(called_by.get(key, set()) | set(used_by.get(key, [])))
            out.append(f"| {anchor(slug(prefix_r, an))}**{o['name']}** | {md(det)} | {', '.join(f'`{u}`' for u in users[:8])} | `{o['file']}:{o.get('line', 1)}` |")
            DB_EXPORT["objects"].append({"name": short(o["name"]), "full_name": o["name"], "kind": kind.lower(), "file": o["file"],
                                         "line": o.get("line"), "page": routines_page, "anchor": slug(prefix_r, an)})
    write(routines_page, "\n".join(x for x in out if x is not None) + "\n")
    return len(tables), len(routines) + len(others)


def app_usage(db):
    """Object -> application files that name it (identifier or string), EF function-import aliases followed."""
    names = {short(o["name"]).lower(): o["name"].lower() for o in db.objects if o["kind"] in ROUTINE_KINDS + OTHER_KINDS}
    alias = {}
    edmx_paths = [os.path.join(ROOT, p) for p in OPT.get("edmx", [])] if OPT.get("edmx") else list(sql_parse.walk(ROOT, (".edmx",), SKIP_DIRS))
    for edmx in edmx_paths:
        for imp, fn in re.findall(r'FunctionImportName="(\w+)"\s+FunctionName="[\w.]*?\.(\w+)"', sql_parse.read_text(edmx)):
            if fn.lower() in names:
                alias[imp.lower()] = names[fn.lower()]
    used = defaultdict(set)
    word = re.compile(r"[A-Za-z_]\w+")
    for fp, txt in code_files():
        for w in set(word.findall(txt)):
            lw = w.lower()
            target = names.get(lw) or alias.get(lw)
            if target:
                used[target].add(fp.split("/")[-1])
    return used


def postgres_page(dbs, code_sql, stats):
    """db-postgres.md: what converts automatically, what needs a rewrite, what has no PostgreSQL equivalent."""
    lv_all = Counter()
    red_rows, obj_rows, type_rows = [], [], Counter()
    for db in dbs:
        for o in db.objects:
            lv, red = levels(o.get("constructs"))
            lv_all.update(lv)
            if lv.get("rewrite") or lv.get("redesign"):
                an = db.anchor_name.get(o["name"].lower())
                page = db.tables_page if o["kind"] == "TABLE" else db.routines_page
                pref = "tbl" if o["kind"] == "TABLE" else "sp"
                obj_rows.append((o["name"], o["kind"], lv.get("auto", 0), lv.get("rewrite", 0), lv.get("redesign", 0), page, slug(pref, an or short(o["name"]))))
            for k in red:
                red_rows.append((k, o["name"], o["kind"], f"{o['file']}:{o.get('line', 1)}"))
            for c in o.get("columns") or []:
                tc = type_conversion(c.get("type"))
                if tc and tc["level"] != "auto":
                    type_rows[((c.get("type") or "").split("(")[0].lower(), tc["level"], tc["pg"])] += 1
    code_lv, code_red = Counter(), []
    for s in code_sql:
        cons = dict((s.get("script") or {}).get("constructs") or {})
        lv, red = levels(cons)
        code_lv.update(lv)
        for k in red:
            code_red.append((k, f"{s['file']}:{s['line']}"))
    out = ["# PostgreSQL conversion", "",
           "How the SQL Server code converts to PostgreSQL, construct by construct, from the parsed scripts and the SQL embedded "
           "in application code. **Automatic**: schema-conversion tooling or a direct rename handles it. **Rewrite**: PostgreSQL "
           "has an equivalent but the code is rewritten by hand. **Redesign**: no PostgreSQL equivalent; the feature needs a "
           "different design. Classification: the toolkit's pg_conversion.json (AWS SQL Server to Aurora PostgreSQL playbook, "
           "PostgreSQL documentation).", "",
           "| Level | In database objects | In SQL embedded in code |", "| --- | ---: | ---: |"]
    for k, label in (("auto", "Automatic"), ("rewrite", "Rewrite"), ("redesign", "Redesign (no equivalent)")):
        out.append(f"| {label} | {lv_all.get(k, 0)} | {code_lv.get(k, 0)} |")
    if red_rows or code_red:
        out += ["", "## No PostgreSQL equivalent", "", "| Construct | Where | Replacement approach |", "| --- | --- | --- |"]
        grp = defaultdict(list)
        for k, name, kind, at in red_rows:
            grp[k].append(f"{name} (`{at}`)")
        for k, at in code_red:
            grp[k].append(f"code `{at}`")
        for k, where in sorted(grp.items(), key=lambda x: -len(x[1])):
            out.append(f"| {md(k)} | {', '.join(where[:6])}{f' +{len(where) - 6} more' if len(where) > 6 else ''} | {md(conversion(k)['pg'])} |")
    if type_rows:
        out += ["", "## Column types to map by hand", "", "| SQL Server type | Columns | Level | PostgreSQL |", "| --- | ---: | --- | --- |"]
        for (t, lvl, pg), n in sorted(type_rows.items(), key=lambda x: -x[1]):
            out.append(f"| {md(t)} | {n} | {lvl} | {md(pg)} |")
    if obj_rows:
        out += ["", "## Objects that need manual work", "", "| Object | Kind | Automatic | Rewrite | Redesign |", "| --- | --- | ---: | ---: | ---: |"]
        for name, kind, a, r, d, page, an in sorted(obj_rows, key=lambda x: (-x[4], -x[3], x[0])):
            out.append(f"| [{name}]({page}#{an}) | {kind} | {a} | {r} | {d} |")
    if stats.get("candidates"):
        out += ["", "## SQL embedded in application code", "",
                f"{stats.get('accepted', 0)} statements parsed from string literals in {stats.get('files', 0)} source files "
                f"({sum(1 for s in code_sql if s.get('dynamic'))} built at run time). Every one runs as written against the "
                "database, so each needs the same conversion as a stored procedure; call sites are in [Database access](db-access.md)."]
    write("db-postgres.md", "\n".join(out) + "\n")


def main():
    eng = sql_parse.engine()
    DB_EXPORT["engine"] = eng
    if not eng:
        print("generic-sql: no SQL parser available (.NET SDK 8+ or pip sqlglot): run install_prerequisites.py")
        return
    results = sql_parse.scan_files(ROOT, SKIP_DIRS)
    dbs_cfg = find_databases(results)
    if not dbs_cfg:
        print("generic-sql: no SQL objects found under", ROOT)
    dbs = []
    for name, path, tp, rp in dbs_cfg:
        tp, rp = tp or "db-tables.md", rp or "db-routines.md"
        mine = [r for r in results if os.path.normpath(os.path.join(ROOT, r["id"])).startswith(os.path.normpath(path) + os.sep)]
        db = Db(name, path, mine)
        db.tables_page, db.routines_page = tp, rp
        nt, nr = generate(db, tp, rp)
        dbs.append(db)
        stat("sql-" + slug(name), tables=nt, routines=nr,  # plus one count per object kind: procedure, function, trigger, view ...
             **{k.lower().replace(" ", "_"): v for k, v in Counter(o["kind"] for o in db.objects).items()})
        print(f"generic-sql [{name}] tables {nt}, routines and other objects {nr}" + (f", {len(db.errors)} parse errors" if db.errors else "") + f" ({eng})")
    code_sql, stats = sql_parse.scan_code(ROOT, SKIP_DIRS) if dbs else ([], {})
    if dbs and PG_NOTES:
        postgres_page(dbs, code_sql, stats)
    if dbs:  # machine-readable copy for generic-dbaccess, tools and retrieval
        DB_EXPORT["code_sql"] = [{"file": s["file"], "line": s["line"], "reads": (s.get("script") or {}).get("reads", []),
                                  "writes": (s.get("script") or {}).get("writes", []), "calls": (s.get("script") or {}).get("calls", []),
                                  "functions": (s.get("script") or {}).get("functions", []), "dynamic": s.get("dynamic", False),
                                  "context": s.get("context", [])} for s in code_sql]
        DB_EXPORT["code_sql_stats"] = stats
        agent = os.path.join(CFG.get("docs_dir", "docs"), "agent")
        os.makedirs(agent, exist_ok=True)
        with open(os.path.join(agent, "db.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(DB_EXPORT, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
