"""Dependency analysis (deterministic): what depends on what.

Two views, both derived from the client's code only:

  project_graph(c)   project -> project references (direct and transitive), fan-in / fan-out, layers (leaf-first port order),
                     cycles, which applications each project serves, and the blast radius of changing a project.
  workflows(c)       entry points (HTTP endpoints, MVC actions, Web Forms pages, hosted/background services, console jobs)
                     -> the projects, database objects, external systems and findings each one reaches.
  db_dependencies(c) database object -> objects it reads / writes / calls (T-SQL parser facts), and database object ->
                     workflows that depend on it (parsed SQL in code and object names passed as string literals).

Reachability uses the graphify code graph (assessment/graphs/<repo>/graphify-out/graph.json): calls / references /
inherits / implements edges, with interface -> implementation edges added so DI-style calls resolve. When no graph exists
the workflow falls back to the transitive project references of its own project. Results are name-based: the assessor
confirms them in review (references/dependency-analysis.md).
"""
import os
import re
from collections import defaultdict, deque

from _common import OUT, SOURCE_DIR_SKIP, read_json, read_text
import _findings as F

REACH_RELATIONS = {"calls", "inherits", "implements", "dispatches_to", "indirect_call"}  # dispatches_to: DI / override / message edges from csharp_resolve
MAX_DEPTH = 5
HUB_DEGREE = 40  # nodes with more outgoing edges are reached but not expanded (service locators, runners, base classes)
MAX_NODES = 4000
OBJ_KINDS = {"TABLE", "VIEW", "PROCEDURE", "FUNCTION", "TRIGGER", "SEQUENCE", "TYPE", "SYNONYM"}
MIN_NAME = 4

RX_MINIMAL = re.compile(r'\.Map(Get|Post|Put|Delete|Patch)\(\s*"([^"]*)"')
RX_CTRL = re.compile(r"(?m)^\s*(?:public\s+)?(?:sealed\s+|partial\s+|abstract\s+)*class\s+(\w+Controller)\b")
RX_ACTION = re.compile(r"(?m)^(?P<attrs>(?:\s*\[[^\]\n]+\]\s*\n)*)\s*public\s+(?:virtual\s+|override\s+)?(?:async\s+)?(?P<ret>[\w<>\[\],.? ]+?)\s+(?P<name>\w+)\s*\(")
RX_HOSTED = re.compile(r"(?m)class\s+(\w+)\b[^{;]*?:\s*[^{;]*\b(BackgroundService|IHostedService)\b")
RX_JOBCLASS = re.compile(r"(?m)class\s+(\w*(?:Job|Jobs|Worker|Batch|Task|Tasks|Scheduler|Processor|Importer|Exporter|Sync)\w*)\b")
RX_PUBLIC_METHOD = re.compile(r"(?m)^\s*public\s+(?:static\s+)?(?:async\s+)?(?:Task(?:<[^>]+>)?|void|int|bool)\s+(\w+)\s*\(")
RX_MAIN = re.compile(r"(?m)static\s+(?:async\s+)?(?:Task(?:<int>)?|void|int)\s+Main\s*\(")
RX_CALL = re.compile(r"\.(\w+)\s*\(")
RX_CONTRACT = re.compile(r"\[\s*(?:System\.ServiceModel\.)?ServiceContract\b[^\]]*\]\s*(?:\[[^\]]*\]\s*)*(?:public\s+|internal\s+)?(?:partial\s+)?interface\s+(\w+)")
RX_PAGEMODEL = re.compile(r"(?m)class\s+(\w+)\s*:\s*[^{;]*\bPageModel\b")
RX_HANDLER = re.compile(r"(?m)^\s*public\s+(?:virtual\s+|override\s+)?(?:async\s+)?[\w<>\[\],.? ]+?\s+(On(Get|Post|Put|Delete|Patch)\w*)\s*\(")
RX_RAZOR_PAGE = re.compile(r'(?m)^\s*@page\s+"([^"]*)"')
RX_STRING = re.compile(r'@"(?:[^"]|"")*"|"(?:[^"\\\n]|\\.)*"')
ACTION_RET = re.compile(r"(?i)Result|Task<?|ViewResult|IActionResult|ActionResult|Json|string")
SKIP_ACTIONS = {"Dispose", "OnActionExecuting", "OnActionExecuted", "OnException", "OnResultExecuting", "OnResultExecuted", "Initialize"}


# ------------------------------------------------------------------ project graph
def project_graph(c):
    """One dict per repository: nodes (projects) with direct/transitive deps, dependents, layer; plus edges and cycles."""
    out = {}
    for r in c.repos:
        inv = c.inv[r]
        if not inv:
            continue
        projs = {p["path"]: p for p in inv["projects"]}
        norm = {k.replace("\\", "/").lower(): k for k in projs}
        direct = {k: [] for k in projs}
        missing = defaultdict(list)
        for k, p in projs.items():
            for ref in p.get("project_references", []):
                t = norm.get(ref.replace("\\", "/").lower())
                if t:
                    direct[k].append(t)
                else:
                    missing[k].append(ref)
        dependents = {k: [] for k in projs}
        for k, ds in direct.items():
            for d in ds:
                dependents[d].append(k)

        def closure(start, edges):
            seen, stack = set(), list(edges[start])
            while stack:
                n = stack.pop()
                if n not in seen:
                    seen.add(n)
                    stack.extend(edges[n])
            return seen
        trans = {k: closure(k, direct) for k in projs}
        used_by = {k: closure(k, dependents) for k in projs}
        cycles = sorted({tuple(sorted((k, d))) for k in projs for d in trans[k] if k in trans[d] and k != d})
        layer, resolving = {}, set()

        def lay(k):
            if k in layer:
                return layer[k]
            if k in resolving:  # cycle: break it
                return 0
            resolving.add(k)
            layer[k] = 1 + max([lay(d) for d in direct[k]] or [-1])
            resolving.discard(k)
            return layer[k]
        for k in projs:
            lay(k)
        app_of = defaultdict(list)
        for a in c.cls["applications"]:
            if a["repo"] != r:
                continue
            for p in a["projects"]:
                app_of[p].append(a["name"])
        nodes = []
        for k, p in sorted(projs.items(), key=lambda kv: (layer[kv[0]], kv[1]["name"])):
            nodes.append({"path": k, "name": p["name"], "type": p["type"], "tfm": ", ".join(p.get("target_frameworks", [])),
                          "loc": p.get("loc_code", 0), "layer": layer[k],
                          "direct": [projs[d]["name"] for d in sorted(direct[k])], "transitive": [projs[d]["name"] for d in sorted(trans[k])],
                          "dependents": [projs[d]["name"] for d in sorted(dependents[k])], "used_by_all": [projs[d]["name"] for d in sorted(used_by[k])],
                          "apps": sorted({a for q in used_by[k] | {k} for a in app_of.get(q, [])}), "unresolved": sorted(missing.get(k, []))})
        out[r] = {"nodes": nodes, "edges": [[projs[a]["name"], projs[b]["name"]] for a, ds in direct.items() for b in ds],
                  "cycles": [[projs[a]["name"], projs[b]["name"]] for a, b in cycles]}
    return out


# ------------------------------------------------------------------ code graph helpers
def _load_graph(r):
    g = read_json(os.path.join(OUT, "graphs", r, "graphify-out", "graph.json"), None)
    if not g:
        return None
    nodes = {n["id"]: n for n in g.get("nodes", [])}
    adj = defaultdict(set)
    for l in g.get("links", g.get("edges", [])):
        s, t, rel = l.get("source"), l.get("target"), l.get("relation")
        if s in nodes and t in nodes and rel in REACH_RELATIONS:
            adj[s].add(t)
            if rel in ("implements", "inherits"):  # a call to the interface/base can land on the implementation
                adj[t].add(s)
    by_file = defaultdict(list)
    for n in nodes.values():
        by_file[(n.get("source_file") or "").replace("\\", "/")].append(n)
    sites = defaultdict(list)  # file -> (line, target): call sites, so lambdas and top-level statements get seeds too
    for l in g.get("links", g.get("edges", [])):
        if l.get("relation") in ("calls", "indirect_call") and l.get("source") in nodes and l.get("target") in nodes:
            m = re.search(r"\d+", str(l.get("source_location") or ""))
            if m:
                sites[(l.get("source_file") or "").replace("\\", "/")].append((int(m.group()), l["target"]))
    lines = {f: sorted({_line(n) for n in ns if _line(n)}) for f, ns in by_file.items()}
    methods = defaultdict(list)  # '.GetStockAsync()' -> nodes, for calls the graph could not type (injected parameters, lambdas)
    for n in nodes.values():
        if str(n.get("label", "")).startswith(".") and n.get("source_file"):
            methods[n["label"]].append(n["id"])
    return {"nodes": nodes, "adj": adj, "by_file": by_file, "sites": sites, "lines": lines, "methods": methods}


def _line(n):
    m = re.search(r"\d+", str(n.get("source_location") or ""))
    return int(m.group()) if m else 0


def strings_free(e, root):
    """Source lines of an entry point (comments and string literals removed) for call-name extraction."""
    try:
        lines = read_text(os.path.join(root, e["file"])).split("\n")
    except OSError:
        return ""
    txt = "\n".join(lines[max(e["line"] - 1, 0):e["end"] - 1 if e["end"] < 10 ** 9 else None])
    # strings first, so a // inside a URL literal is not mistaken for a comment that hides the rest of the line
    return re.sub(r"//[^\n]*", "", RX_STRING.sub('""', txt))


def _span(graph, n):
    """(file, first line, last line) a graph node covers: from its own line to the next node in the same file (method granularity)."""
    f, lo = (n.get("source_file") or "").replace("\\", "/"), _line(n)
    if not f or not lo:
        return None
    nxt = [x for x in graph["lines"].get(f, ()) if x > lo]
    return (f, lo, min(nxt[0] if nxt else lo + 400, lo + 400))


def _reach(graph, seeds, allowed=None):
    """BFS over call edges. `allowed(node)` prunes name-based hops into code the entry point cannot reference."""
    seen, q = set(seeds), deque((s, 0) for s in seeds)
    while q and len(seen) < MAX_NODES:
        n, d = q.popleft()
        if d >= MAX_DEPTH:
            continue
        if d > 0 and len(graph["adj"].get(n, ())) > HUB_DEGREE:
            continue
        for t in graph["adj"].get(n, ()):
            if t not in seen and (allowed is None or allowed(graph["nodes"][t])):
                seen.add(t)
                q.append((t, d + 1))
    return seen


# ------------------------------------------------------------------ entry points
def _skip(path):
    parts = {p.lower() for p in re.split(r"[\\/]", path)}
    return bool(parts & SOURCE_DIR_SKIP) or any(x in parts for x in ("bin", "obj"))


def _entry_points(root, inv):
    """Entry points found in source: dicts with kind, name, file, line, end (exclusive), project."""
    eps = []
    contracts = set()  # WCF service contracts anywhere in the repository (often in a shared contracts project)
    for p in inv["projects"]:
        for d, dirs, files in os.walk(os.path.join(root, os.path.dirname(p["path"]))):
            dirs[:] = [x for x in dirs if x.lower() not in SOURCE_DIR_SKIP and x.lower() not in ("bin", "obj") and not x.startswith(".")]
            for fn in files:
                if fn.lower().endswith(".cs") and os.path.getsize(os.path.join(d, fn)) < 2_000_000:
                    t = read_text(os.path.join(d, fn))
                    if "ServiceContract" in t:
                        contracts.update(RX_CONTRACT.findall(t))
    rx_service = re.compile(r"(?m)class\s+(\w+)\s*:\s*[^{;]*\b(" + "|".join(map(re.escape, sorted(contracts))) + r")\b") if contracts else None
    for p in inv["projects"]:
        pdir = os.path.join(root, os.path.dirname(p["path"]))
        is_exe = (p.get("output_type") or "").lower() in ("exe", "winexe") or p["type"] in ("aspnet-core", "netcore-other")
        for d, dirs, files in os.walk(pdir):
            dirs[:] = [x for x in dirs if x.lower() not in SOURCE_DIR_SKIP and x.lower() not in ("bin", "obj") and not x.startswith(".")]
            for fn in files:
                full = os.path.join(d, fn)
                rp = os.path.relpath(full, root).replace("\\", "/")
                low = fn.lower()
                if low.endswith(".aspx.cs") or low.endswith(".ashx.cs") or low.endswith(".asmx.cs"):
                    eps.append({"kind": "Web Forms page / handler", "name": fn[:-3], "file": rp, "line": 1, "end": 10 ** 9, "project": p["path"]})
                    continue
                if low.endswith(".razor"):  # Blazor routable component: the whole file (markup + @code) is the entry
                    pm = RX_RAZOR_PAGE.search(read_text(full)) if os.path.getsize(full) < 2_000_000 else None
                    if pm:
                        eps.append({"kind": "Blazor page", "name": pm.group(1) or fn[:-6], "file": rp, "line": 1, "end": 10 ** 9, "project": p["path"]})
                        cb = full + ".cs"
                        if os.path.exists(cb):
                            eps.append({"kind": "Blazor page", "name": (pm.group(1) or fn[:-6]) + " (code-behind)", "file": rp + ".cs", "line": 1,
                                        "end": 10 ** 9, "project": p["path"]})
                    continue
                if not low.endswith((".cs", ".vb")) or low.endswith(".designer.cs") or os.path.getsize(full) > 2_000_000:
                    continue
                text = read_text(full)

                def ln(pos):
                    return text.count("\n", 0, pos) + 1
                found = []
                for m in RX_MINIMAL.finditer(text):
                    found.append({"kind": "HTTP endpoint (minimal API)", "name": f"{m.group(1).upper()} {m.group(2)}", "line": ln(m.start())})
                cm = RX_CTRL.search(text)
                if cm:
                    cname = cm.group(1)[:-len("Controller")]
                    for m in RX_ACTION.finditer(text):
                        nm = m.group("name")
                        if nm in SKIP_ACTIONS or nm == cm.group(1) or not ACTION_RET.search(m.group("ret")):
                            continue
                        verb = re.search(r"\[Http(Get|Post|Put|Delete|Patch)", m.group("attrs") or "")
                        found.append({"kind": "MVC / API action", "name": (verb.group(1).upper() + " " if verb else "") + f"{cname}/{nm}", "line": ln(m.start("name"))})
                if rx_service:
                    for sm in rx_service.finditer(text):
                        body_end = len(text)
                        for m in RX_PUBLIC_METHOD.finditer(text, sm.end()):
                            if m.start() < body_end:
                                found.append({"kind": "WCF service operation", "name": f"{sm.group(1)}.{m.group(1)}", "line": ln(m.start())})
                        for m in RX_ACTION.finditer(text, sm.end()):
                            nm = m.group("name")
                            if nm != sm.group(1) and not any(x["name"] == f"{sm.group(1)}.{nm}" for x in found):
                                found.append({"kind": "WCF service operation", "name": f"{sm.group(1)}.{nm}", "line": ln(m.start("name"))})
                pmm = RX_PAGEMODEL.search(text)
                if pmm:
                    page = re.sub(r"Model$", "", pmm.group(1))
                    for m in RX_HANDLER.finditer(text):
                        found.append({"kind": "Razor Pages handler", "name": f"{page}.{m.group(1)}", "line": ln(m.start(1))})
                for m in RX_HOSTED.finditer(text):
                    found.append({"kind": "Background service", "name": m.group(1), "line": ln(m.start())})
                if is_exe and RX_MAIN.search(text) is None and not found:
                    jm = RX_JOBCLASS.search(text)
                    if jm and "Controller" not in jm.group(1):
                        for m in RX_PUBLIC_METHOD.finditer(text):
                            found.append({"kind": "Scheduled / batch job", "name": f"{jm.group(1)}.{m.group(1)}", "line": ln(m.start())})
                mm = RX_MAIN.search(text)
                if mm and not found:
                    found.append({"kind": "Process entry point (Main)", "name": os.path.basename(os.path.dirname(rp)) or fn, "line": ln(mm.start())})
                found.sort(key=lambda x: x["line"])
                for i, e in enumerate(found):
                    e.update({"file": rp, "project": p["path"], "end": found[i + 1]["line"] if i + 1 < len(found) else 10 ** 9})
                    eps.append(e)
    return eps


# ------------------------------------------------------------------ database objects
def _db_objects(c, r):
    inv = (c.scan[r] or {}).get("db_inventory") or {}
    return [o for o in inv.get("objects", []) if o["kind"] in OBJ_KINDS and len(o["name"].split(".")[-1]) >= MIN_NAME]


def _resolver(objs):
    full = {o["name"].lower(): o["name"] for o in objs}
    short = defaultdict(set)
    for o in objs:
        short[o["name"].split(".")[-1].lower()].add(o["name"])

    def get(name):
        n = (name or "").lower()
        if n in full:
            return full[n]
        if len(n.split(".")) >= 3:
            return None
        if "dbo." + n in full:
            return full["dbo." + n]
        c = short.get(n.split(".")[-1], set())
        return next(iter(c)) if len(c) == 1 else None
    return get


def db_dependencies(c):
    """Object -> objects it reads, writes, calls or is defined on (T-SQL parser facts); per repository."""
    out = {}
    for r in c.repos:
        objs = _db_objects(c, r)
        if not objs:
            continue
        get = _resolver(objs)
        edges = set()
        for o in objs:
            refs = list(o.get("reads", [])) + [w["name"] for w in o.get("writes", [])] + list(o.get("calls", [])) + list(o.get("functions", []))
            refs += [o["on_object"]] if o.get("on_object") else []
            refs += [fk.get("references") for fk in o.get("foreign_keys") or [] if fk.get("references")]
            for t in refs:
                tgt = get(t)
                if tgt and tgt != o["name"]:
                    edges.add((o["name"], tgt))
        out[r] = {"objects": objs, "edges": sorted(edges)}
    return out


def _db_sites(c, r, objs):
    """file -> [(line, object)]: SQL embedded in code (parsed) and object names passed as whole string literals."""
    inv = (c.scan[r] or {}).get("db_inventory") or {}
    get = _resolver(objs)
    sites = defaultdict(list)
    for s in inv.get("code_sql", []):
        for t in s.get("reads", []) + [w["name"] for w in s.get("writes", [])] + s.get("calls", []) + s.get("functions", []):
            o = get(t)
            if o:
                sites[s["file"]].append((s["line"], o))
    for s in inv.get("name_sites", []):
        o = get(s["object"])
        if o:
            sites[s["file"]].append((s["line"], o))
    return sites


# ------------------------------------------------------------------ workflows
def workflows(c):
    """Trace every entry point to the projects, database objects, external systems and findings it reaches."""
    pg = project_graph(c)
    rows = []
    for r in c.repos:
        inv = c.inv[r]
        if not inv:
            continue
        root = inv["root"]
        graph = _load_graph(r)
        pidx = F.project_index(inv)
        pname = {p["path"]: p["name"] for p in inv["projects"]}
        trans = {n["path"]: n["transitive"] for n in pg[r]["nodes"]}
        objs = _db_objects(c, r)
        ext = defaultdict(set)  # file -> external/internal hosts
        for e in (c.scan[r] or {}).get("endpoints", []):
            for ev in e.get("evidence", []):
                ext[ev["file"].replace("\\", "/")].add((ev.get("line") or 0, e["host"]))
        dbs = defaultdict(set)  # project -> databases named in its connection strings
        for cs in (c.scan[r] or {}).get("connection_strings", []):
            p = F.project_of_file(pidx, cs["file"])
            if p and cs.get("database"):
                dbs[p].add(cs["database"])
        fnd = defaultdict(list)  # file -> findings
        for f in c.findings:
            if f["repo"] == r and f["severity"] in ("Blocker", "High", "Medium"):
                for ev in f.get("evidence", []):
                    fnd[ev["file"].replace("\\", "/")].append(f)
        sites = _db_sites(c, r, objs)
        deps = defaultdict(set)  # routine -> the objects it reads / writes / calls (one level behind what code reaches)
        for a_, b_ in (db_dependencies(c).get(r) or {}).get("edges", []):
            deps[a_].add(b_)
        for e in _entry_points(root, inv):
            spans = [(e["file"], e["line"], e["end"])]  # (file, first line, last line exclusive) of code this workflow runs
            whole = e["kind"].startswith("Web Forms")
            if graph:
                seeds = {n["id"] for n in graph["by_file"].get(e["file"], []) if e["line"] <= _line(n) < e["end"] or (whole and _line(n) >= 0)}
                seeds |= {t for ln_, t in graph["sites"].get(e["file"], []) if e["line"] <= ln_ < e["end"]}
                ok = {e["project"]} | {p for p in pname if pname[p] in trans.get(e["project"], [])}

                def allowed(n):
                    f = (n.get("source_file") or "").replace("\\", "/")
                    return not f or F.project_of_file(pidx, f) in ok
                seeds = {x for x in seeds if allowed(graph["nodes"][x])}
                resolved = set()  # `x.Name(` calls in the entry's own lines that the graph did not link: unique-ish name match inside reachable projects
                for name in set(RX_CALL.findall(strings_free(e, root))):
                    cands = [i for i in graph["methods"].get("." + name + "()", ()) if allowed(graph["nodes"][i])]
                    if len(cands) == 1 and len(name) >= 8:
                        resolved.update(cands)
                resolved -= seeds
                seeds |= resolved
                reached = _reach(graph, seeds, allowed) if seeds else set()
                spans += [sp for sp in (_span(graph, graph["nodes"][n]) for n in reached) if sp]
                basis = "code graph" if seeds else "project references (no graph nodes for the entry point)"
            else:
                basis = "project references (no code graph)"
            if whole:
                spans[0] = (e["file"], 1, 10 ** 9)
            files = {f for f, _, _ in spans}
            projects = {F.project_of_file(pidx, f) for f in files if f} - {None}
            if not graph or basis.startswith("project references"):
                projects |= {p for p in pname if pname[p] in trans.get(e["project"], [])} | {e["project"]}
            projects.add(e["project"])
            direct = {o for f, lo, hi in spans for ln_, o in sites.get(f, ()) if lo <= ln_ < hi}
            dbobj = sorted(direct | {t for o in direct for t in deps.get(o, ())})

            def inside(f, ln_):
                return any(f == sf and lo <= ln_ < hi for sf, lo, hi in spans)
            hosts = sorted({h for f in files for ln_, h in ext.get(f, ()) if inside(f, ln_)})
            fs = {}
            for f in files:
                for x in fnd.get(f, ()):
                    if any(ev["file"].replace("\\", "/") == f and inside(f, ev.get("line") or 0) for ev in x.get("evidence", [])):
                        fs[x["ref"]] = x
            # the application whose own (entry) project holds the entry point; otherwise every application that includes it
            own = sorted({a["name"] for a in c.cls["applications"] if a["repo"] == r and a["projects"] and a["projects"][0] == e["project"]})
            apps = own or sorted({a["name"] for a in c.cls["applications"] if a["repo"] == r and e["project"] in a["projects"]})
            rows.append({"repo": r, "kind": e["kind"], "name": e["name"], "app": ", ".join(apps) or pname.get(e["project"], ""), "entry": f"{e['file']}:{e['line']}",
                         "entry_project": pname.get(e["project"], ""), "projects": sorted(pname[p] for p in projects if p in pname), "db_objects": dbobj,
                         "databases": sorted({d for p in projects for d in dbs.get(p, ())}), "external": hosts,
                         "findings": sorted(fs, key=lambda x: (fs[x]["severity"] != "Blocker", fs[x]["severity"] != "High", x)),
                         "files": len(files), "basis": basis})
    return rows


def object_dependents(c, wf):
    """Reverse index: database object -> workflows that touch it (by repository)."""
    idx = defaultdict(list)
    for w in wf:
        for o in w["db_objects"]:
            idx[(w["repo"], o)].append(f"{w['name']} ({w['entry_project']})")
    return idx
