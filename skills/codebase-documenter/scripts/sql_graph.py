"""Add the database layer to the graphify graph: database objects as nodes, and the edges graphify cannot see.

    python <skill>/scripts/sql_graph.py [--quiet]                                  # documentation workspace
    python <skill>/scripts/sql_graph.py --source-root SRC --graph-dir DIR [--quiet]  # standalone (migration-assessment)

graphify extracts no nodes from .sql files and does not read SQL inside C# strings, so procedures, tables and the code that
uses them are disconnected. This script parses both with sql_parse.py (Microsoft's T-SQL parser, sqlglot fallback) and adds:
  nodes   one per table / view / procedure / function / trigger / type / sequence / synonym defined in .sql files, plus
          tables and procedures that only SQL in code refers to (marked external); kind, file:line, conversion levels
  edges   routine -> table   reads_from / writes_to (op in metadata)        routine -> routine / function   calls
          trigger -> table   references (context "trigger on")             table -> table   references ("foreign key")
          synonym -> target  references ("synonym for")
          C# method -> table / routine   reads_from / writes_to / calls (context "embedded SQL", the enclosing method of
          the string literal, from graphify's own method nodes)
          page -> table / routine   from Web Forms data source markup (Select/Insert/Update/DeleteCommand; context
          "markup SQL", from the code-behind class, else a node for the markup file)
          C# method -> table   references (context "name in code") for a bare table name in a table-name setting
          (TableName = "X", DestinationTableName, ToTable("X"), [Table("X")])
          C# method -> procedure   calls (context "name in code (not defined in the repository)") for every procedure
          code_routines.py finds the code running by name without a definition here (external node)
Idempotent: nodes and edges with _origin "sql-parse" are replaced on every run. When graphify already has a node for the
object (its [sql] extra parses .sql files: same file, same label), that node is reused and annotated instead of adding a
twin, because graphify merges same-file same-label nodes on reload and then refuses to save the smaller graph; the
attributes added here are listed in the node's _sql_parse_keys and removed again on the next run.
Writes sql-graph.json beside graph.json (counts, unresolved names) for reports.
"""
import argparse
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_config, utf8_stdout  # noqa: E402
import sql_parse  # noqa: E402

ORIGIN = "sql-parse"
ANNOT = "_sql_parse_keys"  # attributes this script added to a graphify node it reused
SYSTEM = ("sys.", "information_schema.", "inserted", "deleted")
MARKUP_EXTS = (".aspx", ".ascx", ".master")
# <asp:SqlDataSource SelectCommand="..." UpdateCommand="dbo.usp_X" ...>: the attribute value only; the SQL itself goes to the parser
CMD_ATTR = re.compile(r'\b(Select|Insert|Update|Delete)Command\s*=\s*"([^"]*)"', re.I)
# a table-name setting earlier in the same statement: TableName = "X", TableName = config["k"] ?? "X", DestinationTableName = "X",
# ToTable("X"), [Table("X")], NHibernate Table("X"); not new DataTable("X") (an in-memory ADO.NET table)
TABLE_SETTING = re.compile(r'(?i)(?<!data)table\w*\s*(?:=|\(|:)[^;]*$')
_LINES = {}


def lines_of(path, rp):
    if rp not in _LINES:
        _LINES.clear()  # one file at a time is enough: literals are visited file by file
        _LINES[rp] = sql_parse.read_text(path).splitlines()
    return _LINES[rp]


def table_context(lines, line, value):
    """True when the C# literal sits in a table-name setting (AddDistributedSqlServerCache, SqlBulkCopy, EF ToTable, …)."""
    text = lines[line - 1] if 0 < line <= len(lines) else ""
    i = text.find('"' + value + '"')
    return i > 0 and bool(TABLE_SETTING.search(text[:i]))


def node_id(name):
    return "sql_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class Names:
    """Resolve a name as written in SQL (schema optional, any case, brackets already removed) to a defined object."""

    def __init__(self):
        self.full, self.short = {}, defaultdict(set)

    def add(self, name):
        self.full[name.lower()] = name
        self.short[name.split(".")[-1].lower()].add(name)

    def get(self, name):
        n = name.lower()
        if n in self.full:
            return self.full[n]
        parts = n.split(".")
        if len(parts) >= 3:  # db.schema.name / server.db.schema.name: another database, never a local object
            return None
        cands = self.short.get(parts[-1], set())
        if len(parts) == 1 and "dbo." + n in self.full:
            return self.full["dbo." + n]
        return next(iter(cands)) if len(cands) == 1 else None


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-root")
    ap.add_argument("--graph-dir")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.source_root and a.graph_dir:
        ws, src, gdir = os.getcwd(), a.source_root, a.graph_dir
    else:
        ws, cfg = load_config()
        src, gdir = cfg["source_root"], cfg["graph_dir"]
    gpath = os.path.join(gdir, "graph.json")
    if not os.path.exists(gpath):
        sys.exit(f"sql_graph: {gpath} not found (build the graph first)")
    eng = sql_parse.engine()
    if not eng:
        print("sql_graph: skipped (no SQL parser: run install_prerequisites.py)")
        return
    if a.source_root and a.graph_dir:
        cfg = {}
    g = json.load(open(gpath, encoding="utf-8"))
    g["nodes"] = [n for n in g["nodes"] if n.get("_origin") != ORIGIN]
    g["links"] = [e for e in g["links"] if e.get("_origin") != ORIGIN]
    for n in g["nodes"]:
        for k in n.pop(ANNOT, None) or []:
            n.pop(k, None)
    nodes = {n["id"]: n for n in g["nodes"]}
    src_abs = os.path.normcase(os.path.abspath(src))

    def rel_src(sf):
        """A graph source_file as a lower-case path relative to the source root, or None outside it."""
        for r in (os.path.abspath(src), os.path.abspath(ws)):
            p = os.path.normcase(os.path.abspath(os.path.join(r, sf)))
            if p.startswith(src_abs + os.sep):
                return os.path.relpath(p, src_abs).replace("\\", "/").lower()
        return None

    twins = {}  # (file, label) -> graphify's own node: graphify merges a same-file same-label node into it on reload
    for i, n in nodes.items():
        if n.get("source_file") and str(n.get("label") or "").strip():
            twins.setdefault((rel_src(n["source_file"]), str(n["label"]).strip()), i)
    ids = {}  # object name (lower case) -> node id

    def oid(name):
        return ids.get(name.lower()) or node_id(name)

    def add_node(nid, attrs):
        """Append a node, or annotate graphify's twin of it (same file and label) and return the twin's id."""
        twin = twins.get((rel_src(attrs["source_file"]), attrs["label"].strip())) if attrs.get("source_file") else None
        if not twin:
            new_nodes.append(dict(attrs, id=nid))
            return nid
        n = nodes[twin]
        added = [k for k in attrs if k not in n and k != "_origin"]
        for k in added:
            n[k] = attrs[k]
        n[ANNOT] = added
        return twin

    files = sql_parse.scan_files(src)
    code, stats = sql_parse.scan_code(src)
    names, objs = Names(), {}
    for r in files:
        for o in r.get("objects", []):
            nm = o.get("name") or ""
            if not nm or nm.split(".")[-1].startswith(("#", "@")) or o.get("kind") == "INDEX":
                continue
            if nm.lower() not in objs or str(o.get("verb", "")).lower().startswith("create"):
                objs[nm.lower()] = dict(o, file=r["id"])
            names.add(nm)
    new_nodes, new_links, kinds = [], [], Counter()
    unresolved = Counter()
    have = set()

    def ensure(name, kind_hint):
        real = names.get(name)
        if real:
            return oid(real)
        if kind_hint == "FUNCTION" or name.lower().startswith(SYSTEM):  # x.Method() may be a column method; catalog views are not app objects
            return None
        if len(name.split(".")) >= 3:
            unresolved[name] += 1
            return None
        nid = node_id(name)
        if nid not in have:
            have.add(nid)
            new_nodes.append({"id": nid, "label": name, "file_type": "code", "_origin": ORIGIN, "_db_object": True, "kind": kind_hint,
                              "external": True, "norm_label": name.lower(), "source_file": None, "source_location": None})
        return nid

    for key, o in objs.items():
        nid = add_node(node_id(o["name"]), {
            "label": o["name"], "file_type": "code", "_origin": ORIGIN, "_db_object": True, "kind": o["kind"],
            "norm_label": o["name"].lower(), "source_file": o["file"], "source_location": f"L{o.get('line', 1)}",
            "metadata": {"lines": o.get("lines"), "params": [p.get("name") for p in o.get("params") or []],
                         "constructs": len(o.get("constructs") or {})}})
        ids[key] = nid
        have.add(nid)

    def link(s, t, rel, ctx, sf, line, meta=None):
        if s and t and s != t:
            new_links.append({"source": s, "target": t, "relation": rel, "_origin": ORIGIN, "confidence": "EXTRACTED",
                              "confidence_score": 1.0, "context": ctx, "source_file": sf, "source_location": f"L{line}" if line else None,
                              "weight": 1.0, "metadata": meta or {}})
            kinds[ctx + " " + rel] += 1

    for key, o in objs.items():
        s, sf, ln = oid(o["name"]), o["file"], o.get("line")
        for t in o.get("reads", []):
            link(s, ensure(t, "TABLE"), "reads_from", "sql", sf, ln)
        for w in o.get("writes", []):
            link(s, ensure(w["name"], "TABLE"), "writes_to", "sql", sf, ln, {"op": w["op"]})
        for c in o.get("calls", []):
            if not c.split(".")[-1].lower().startswith(("sp_", "xp_")):
                link(s, ensure(c, "PROCEDURE"), "calls", "sql", sf, ln)
        for f in o.get("functions", []):
            link(s, ensure(f, "FUNCTION"), "calls", "sql", sf, ln)
        if o.get("on_object"):
            link(s, ensure(o["on_object"], "TABLE"), "references", "trigger on" if o["kind"] == "TRIGGER" else "synonym for", sf, ln,
                 {"events": o.get("trigger_events"), "type": o.get("trigger_type")})
        for t in o.get("targets") or []:  # security policy -> protected tables
            link(s, ensure(t, "TABLE"), "references", "security policy on", sf, ln)
        for fn in o.get("predicates") or []:  # security policy -> the predicate function it runs on every row
            link(s, ensure(fn, "FUNCTION"), "calls", "security predicate", sf, ln)
        for fk in o.get("foreign_keys") or []:
            link(s, ensure(fk["references"], "TABLE"), "references", "foreign key", sf, ln, {"columns": fk.get("columns")})

    # C# methods that run SQL: the enclosing graphify method node of each parsed literal
    owners = {e["target"] for e in g["links"] if e.get("relation") == "method"}
    by_file = defaultdict(list)
    roots = [os.path.abspath(src), os.path.abspath(ws)]
    for i in owners:
        n = nodes.get(i)
        if not n or not n.get("source_file"):
            continue
        m = re.match(r"L(\d+)", str(n.get("source_location") or ""))
        if not m:
            continue
        for r in roots:
            p = os.path.normcase(os.path.abspath(os.path.join(r, n["source_file"])))
            if p.startswith(src_abs + os.sep) or p == src_abs:
                by_file[os.path.relpath(p, src_abs).replace("\\", "/").lower()].append((int(m.group(1)), i))
                break
    any_by_file = defaultdict(list)  # every graphify node with a location: constants classes have no methods
    for i, n in nodes.items():
        m = re.match(r"L(\d+)", str(n.get("source_location") or ""))
        if m and n.get("source_file"):
            for r in roots:
                p = os.path.normcase(os.path.abspath(os.path.join(r, n["source_file"])))
                if p.startswith(src_abs + os.sep):
                    any_by_file[os.path.relpath(p, src_abs).replace("\\", "/").lower()].append((int(m.group(1)), i))
                    break
    for v in list(by_file.values()) + list(any_by_file.values()):
        v.sort()
    no_method = 0
    for s in code:
        cands = [(ln, i) for ln, i in by_file.get(s["file"].lower(), []) if ln <= s["line"]]
        mid = max(cands)[1] if cands else None
        if not mid:
            no_method += 1
            continue
        sc = s.get("script") or {}
        meta = {"dynamic": s.get("dynamic", False), "at": f"{s['file']}:{s['line']}"}
        for t in sc.get("reads", []):
            link(mid, ensure(t, "TABLE"), "reads_from", "embedded SQL", s["file"], s["line"], meta)
        for w in sc.get("writes", []):
            link(mid, ensure(w["name"], "TABLE"), "writes_to", "embedded SQL", s["file"], s["line"], dict(meta, op=w["op"]))
        for c in sc.get("calls", []):
            if not c.split(".")[-1].lower().startswith(("sp_", "xp_")):
                link(mid, ensure(c, "PROCEDURE"), "calls", "embedded SQL", s["file"], s["line"], meta)
        for f in sc.get("functions", []):
            link(mid, ensure(f, "FUNCTION"), "calls", "embedded SQL", s["file"], s["line"], meta)

    # object NAMES in C# literals: procedures run with CommandType.StoredProcedure / EXEC wrappers, TVP type names, mapped views
    named = 0
    kind_of = {k: o["kind"] for k, o in objs.items()}
    for path in sql_parse.walk(src, (".cs",)):
        rp = os.path.relpath(path, src).replace("\\", "/")
        lits = sql_parse.csharp_literals(sql_parse.read_text(path))
        for line, value in lits:
            v = value.strip().replace("[", "").replace("]", "")
            if " " in v or not v or v[0].isdigit():
                continue
            real = names.get(v)
            if not real or kind_of.get(real.lower()) not in ("PROCEDURE", "FUNCTION", "TYPE", "VIEW", "SEQUENCE", "TABLE"):
                continue
            if kind_of[real.lower()] == "TABLE" and "." not in v and not table_context(lines_of(path, rp), line, value):
                continue  # a bare word such as "Orders" is too often UI text, unless a table-name setting takes it
            cands = [(ln, i) for ln, i in by_file.get(rp.lower(), []) if ln <= line] or                 [(ln, i) for ln, i in any_by_file.get(rp.lower(), []) if ln <= line]
            if cands:
                rel = "calls" if kind_of[real.lower()] in ("PROCEDURE", "FUNCTION") else "references"
                link(max(cands)[1], oid(real), rel, "name in code", rp, line, {"literal": value})
                named += 1
    # procedures the code runs by name with no definition in the repository (code_routines.py): an external node each, so
    # `graphify affected "<procedure>"` still reaches the code that runs it in a code-only database
    import code_routines
    helpers = (cfg.get("adapter_options", {}).get("generic-sql", {}).get("code_only_helpers") if not a.source_root else None)
    code_only = 0
    for key, r in code_routines.find(src, helpers)["routines"].items():
        if names.get(r["name"]) or names.get(f"{r['schema']}.{r['name']}" if r["schema"] else r["name"]):
            continue  # defined in a script: the literal scan above already linked it
        nid = ensure(f"{r['schema']}.{r['name']}" if r["schema"] else r["name"], "PROCEDURE")
        for c in r["calls"]:
            cands = [(ln, i) for ln, i in by_file.get(c["file"].lower(), []) if ln <= c["line"]]
            if cands:
                link(max(cands)[1], nid, "calls", "name in code (not defined in the repository)", c["file"], c["line"], {"via": c["via"]})
                code_only += 1
    # Web Forms data source controls: Select/Insert/Update/DeleteCommand attributes hold SQL or a procedure name in the markup,
    # where the C# scan never looks. The edge starts at the page's code-behind class (or a node for the markup file).
    cmds, markup = [], 0
    for path in sql_parse.walk(src, MARKUP_EXTS):
        rp = os.path.relpath(path, src).replace("\\", "/")
        text = sql_parse.read_text(path)
        for m in CMD_ATTR.finditer(text):
            value = html.unescape(m.group(2)).strip()
            if value:
                cmds.append({"file": rp, "line": text.count("\n", 0, m.start()) + 1, "verb": m.group(1), "value": value})
    sql_items = [{"id": f"m{k}", "text": c["value"]} for k, c in enumerate(cmds) if " " in c["value"]]
    parsed = {r.get("id"): r for r in sql_parse.parse(sql_items)} if sql_items else {}
    for k, c in enumerate(cmds):
        cb = sorted((ln, i) for ln, i in any_by_file.get(c["file"].lower() + ".cs", []) if nodes[i].get("_callable_class"))
        sid = cb[0][1] if cb else "markup_" + re.sub(r"[^a-z0-9]+", "_", c["file"].lower()).strip("_")
        if not cb and sid in ids:
            sid = ids[sid]
        elif not cb and sid not in have:
            have.add(sid)
            ids[sid] = add_node(sid, {"label": os.path.basename(c["file"]), "file_type": "code", "_origin": ORIGIN, "_markup": True,
                                      "norm_label": os.path.basename(c["file"]).lower(), "source_file": c["file"], "source_location": "L1"})
            sid = ids[sid]
        meta = {"dynamic": False, "at": f"{c['file']}:{c['line']}", "command": c["verb"] + "Command"}
        if " " not in c["value"]:  # a procedure name (…CommandType="StoredProcedure")
            real = names.get(c["value"].replace("[", "").replace("]", ""))
            if real and kind_of.get(real.lower()) in ("PROCEDURE", "FUNCTION"):
                link(sid, oid(real), "calls", "markup SQL", c["file"], c["line"], meta)
                markup += 1
            continue
        sc = (parsed.get(f"m{k}") or {}).get("script") or {}
        for t in sc.get("reads", []):
            link(sid, ensure(t, "TABLE"), "reads_from", "markup SQL", c["file"], c["line"], meta)
        for w in sc.get("writes", []):
            link(sid, ensure(w["name"], "TABLE"), "writes_to", "markup SQL", c["file"], c["line"], dict(meta, op=w["op"]))
        for cl in sc.get("calls", []):
            if not cl.split(".")[-1].lower().startswith(("sp_", "xp_")):
                link(sid, ensure(cl, "PROCEDURE"), "calls", "markup SQL", c["file"], c["line"], meta)
        for f in sc.get("functions", []):
            link(sid, ensure(f, "FUNCTION"), "calls", "markup SQL", c["file"], c["line"], meta)
        markup += bool(sc)
    # parameter types: table-valued parameters and alias types used by routines
    for key, o in objs.items():
        for prm in o.get("params") or []:
            t = (prm.get("type") or "").split("(")[0].strip()
            if t and names.get(t) and kind_of.get(names.get(t).lower()) == "TYPE":
                link(oid(o["name"]), oid(names.get(t)), "references", "parameter type", o["file"], o.get("line"))

    g["nodes"] += new_nodes
    g["links"] += new_links
    tmp = gpath + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(g, fh, ensure_ascii=False)
    os.replace(tmp, gpath)
    summary = {"engine": eng, "objects": len(objs), "external_objects": sum(1 for n in new_nodes if n.get("external")),
               "edges": dict(kinds), "embedded_sql": stats, "embedded_sql_without_method": no_method, "markup_commands": len(cmds), "markup_commands_linked": markup, "code_only_calls": code_only,
               "unresolved_names": dict(unresolved.most_common(50))}
    with open(os.path.join(gdir, "sql-graph.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=1, ensure_ascii=False)
    if not a.quiet:
        print(f"sql_graph [{eng}]: {len(objs)} database objects (+{summary['external_objects']} referenced only from code), "
              f"{len(new_links)} edges: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common(8))
              + f"; {stats.get('accepted', 0)} SQL statements in code ({no_method} outside a known method)"
              + (f"; {markup}/{len(cmds)} data source commands in markup" if cmds else "")
              + (f"; {code_only} calls to procedures not defined in the repository" if code_only else ""))


if __name__ == "__main__":
    main()
