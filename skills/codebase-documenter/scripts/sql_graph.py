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
Idempotent: nodes and edges with _origin "sql-parse" are replaced on every run; graphify's own are never touched.
Writes sql-graph.json beside graph.json (counts, unresolved names) for reports.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_config, utf8_stdout  # noqa: E402
import sql_parse  # noqa: E402

ORIGIN = "sql-parse"
SYSTEM = ("sys.", "information_schema.", "inserted", "deleted")


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
    g = json.load(open(gpath, encoding="utf-8"))
    g["nodes"] = [n for n in g["nodes"] if n.get("_origin") != ORIGIN]
    g["links"] = [e for e in g["links"] if e.get("_origin") != ORIGIN]
    nodes = {n["id"]: n for n in g["nodes"]}

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
            return node_id(real)
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
        nid = node_id(o["name"])
        have.add(nid)
        new_nodes.append({"id": nid, "label": o["name"], "file_type": "code", "_origin": ORIGIN, "_db_object": True, "kind": o["kind"],
                          "norm_label": o["name"].lower(), "source_file": o["file"], "source_location": f"L{o.get('line', 1)}",
                          "metadata": {"lines": o.get("lines"), "params": [p.get("name") for p in o.get("params") or []],
                                       "constructs": len(o.get("constructs") or {})}})

    def link(s, t, rel, ctx, sf, line, meta=None):
        if s and t and s != t:
            new_links.append({"source": s, "target": t, "relation": rel, "_origin": ORIGIN, "confidence": "EXTRACTED",
                              "confidence_score": 1.0, "context": ctx, "source_file": sf, "source_location": f"L{line}" if line else None,
                              "weight": 1.0, "metadata": meta or {}})
            kinds[ctx + " " + rel] += 1

    for key, o in objs.items():
        s, sf, ln = node_id(o["name"]), o["file"], o.get("line")
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
        for fk in o.get("foreign_keys") or []:
            link(s, ensure(fk["references"], "TABLE"), "references", "foreign key", sf, ln, {"columns": fk.get("columns")})

    # C# methods that run SQL: the enclosing graphify method node of each parsed literal
    owners = {e["target"] for e in g["links"] if e.get("relation") == "method"}
    by_file = defaultdict(list)
    roots = [os.path.abspath(src), os.path.abspath(ws)]
    src_abs = os.path.normcase(os.path.abspath(src))
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
            if kind_of[real.lower()] == "TABLE" and "." not in v:  # a bare word such as "Orders" is too often UI text
                continue
            cands = [(ln, i) for ln, i in by_file.get(rp.lower(), []) if ln <= line] or                 [(ln, i) for ln, i in any_by_file.get(rp.lower(), []) if ln <= line]
            if cands:
                rel = "calls" if kind_of[real.lower()] in ("PROCEDURE", "FUNCTION") else "references"
                link(max(cands)[1], node_id(real), rel, "name in code", rp, line, {"literal": value})
                named += 1
    # parameter types: table-valued parameters and alias types used by routines
    for key, o in objs.items():
        for prm in o.get("params") or []:
            t = (prm.get("type") or "").split("(")[0].strip()
            if t and names.get(t) and kind_of.get(names.get(t).lower()) == "TYPE":
                link(node_id(o["name"]), node_id(names.get(t)), "references", "parameter type", o["file"], o.get("line"))

    g["nodes"] += new_nodes
    g["links"] += new_links
    tmp = gpath + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(g, fh, ensure_ascii=False)
    os.replace(tmp, gpath)
    summary = {"engine": eng, "objects": len(objs), "external_objects": sum(1 for n in new_nodes if n.get("external")),
               "edges": dict(kinds), "embedded_sql": stats, "embedded_sql_without_method": no_method,
               "unresolved_names": dict(unresolved.most_common(50))}
    with open(os.path.join(gdir, "sql-graph.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=1, ensure_ascii=False)
    if not a.quiet:
        print(f"sql_graph [{eng}]: {len(objs)} database objects (+{summary['external_objects']} referenced only from code), "
              f"{len(new_links)} edges: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common(8))
              + f"; {stats.get('accepted', 0)} SQL statements in code ({no_method} outside a known method)")


if __name__ == "__main__":
    main()
