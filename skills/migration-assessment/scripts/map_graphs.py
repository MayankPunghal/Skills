"""Map each repository with graphify (AST code graph) and derive the architecture facts the report needs.

    python <skill>/scripts/map_graphs.py --repo NAME | --all [--force] [--label] [--exports] [--merge]

Per repository (assessment/graphs/<repo>/):
  graphify extract <repo> --code-only        code graph (free, no LLM); third-party front-end libraries copied into the repo
                                             (jQuery, Bootstrap, WebForms scripts: codebase-documenter vendor_files.py) are excluded
  graphify cluster-only                      communities + GRAPH_REPORT.md
  csharp_resolve.py (codebase-documenter)    C# calls graphify misses: DI registrations (Microsoft DI, Autofac, Unity, Ninject,
                                             SimpleInjector, StructureMap, Windsor, Scrutor), overrides, keyed services,
                                             MediatR / bus messages, events, method groups, local variables, Hangfire / Quartz
                                             jobs, redirects, filters, stored delegates; writes csharp-resolve.json
  sql_graph.py (codebase-documenter)         database layer graphify cannot see: tables / procedures / functions / triggers as
                                             nodes; routine -> table reads / writes, routine calls, triggers, foreign keys, and
                                             C# method -> table / procedure from SQL embedded in code (T-SQL parser, no regex)
  community_names.py (codebase-documenter)   unique community names + one-line summaries without an LLM; with --label an
                                             LLM names them instead (cheap, one request per 25 communities)
  graphify export wiki / callflow-html (with --exports)   navigable wiki and Mermaid call flows for the architecture section
  analysis.json                              communities (size, folders, projects, summary), god nodes (hubs), observed
                                             project-to-project edges, per-file blast radius (how many other files
                                             depend on code in each file), node/edge counts, and "wiring": DI containers,
                                             registrations per host and lifetime, messages, pipeline, jobs, events,
                                             reflection, and run-time indirection per project (feeds the complexity factor)
  wiring-findings.json                       findings in the scan schema (legacy DI container, captive dependency,
                                             missing registration, service locator, reflection); _findings.load merges them
--merge builds assessment/graphs/estate-graph.json with `graphify merge-graphs` for cross-repository questions
(`graphify query/path/explain/affected --graph assessment/graphs/estate-graph.json`).
Keys: OPENROUTER_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY / MOONSHOT_API_KEY from the
environment only.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

from _common import OUT, documenter_dir, load_config, load_state, mark, mark_step, read_json, run, utf8_stdout, write_json

KEY_VARS = ["OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY"]
DEP_RELATIONS = {"calls", "references", "inherits", "implements", "imports", "reads_from", "indirect_call", "dispatches_to", "imports_from"}


def env_value(name):
    v = os.environ.get(name)
    if v or os.name != "nt":
        return v
    code, out = run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetEnvironmentVariable('{name}','User')"])
    return (out.strip() or None) if code == 0 else None


def graph_dir(repo):
    return os.path.join(OUT, "graphs", repo)


def doc_script(name):
    d = documenter_dir()
    p = os.path.join(d, "scripts", name) if d else None
    return p if p and os.path.exists(p) else None


def stale(out, *scripts):
    """True when the output is missing or older than a script that writes it: an upgraded skill refreshes existing graphs."""
    if not os.path.exists(out):
        return True
    paths = [doc_script(x) for x in scripts]
    return any(p and os.path.getmtime(p) > os.path.getmtime(out) for p in paths)


def resolve(repo, src):
    """C# calls graphify misses (codebase-documenter csharp_resolve.py). Idempotent: replaces its own earlier edges."""
    script = doc_script("csharp_resolve.py")
    if not script:
        print(f"{repo}: C# call resolution skipped (codebase-documenter not found; set CODEBASE_DOCUMENTER_DIR)")
        return False
    code, txt = run([sys.executable, script, "--source-root", src, "--graph-dir", os.path.join(graph_dir(repo), "graphify-out"), "--quiet"],
                    timeout=1800)
    if code:
        print(f"WARN {repo}: csharp_resolve failed ({code}): {txt[-300:]}")
    return code == 0


def sql_layer(repo, src):
    """Database objects and SQL edges (codebase-documenter sql_graph.py): procedures / tables / triggers as nodes, routine ->
    table reads / writes, routine calls, foreign keys, and C# method -> table / procedure from SQL embedded in code."""
    script = doc_script("sql_graph.py")
    if not script:
        return False
    code, txt = run([sys.executable, script, "--source-root", src, "--graph-dir", os.path.join(graph_dir(repo), "graphify-out"), "--quiet"],
                    timeout=1800)
    if code:
        print(f"WARN {repo}: sql_graph failed ({code}): {txt[-300:]}")
    return code == 0


def build(repo, src, force):
    out = graph_dir(repo)
    gj = os.path.join(out, "graphify-out", "graph.json")
    if os.path.exists(gj) and not force:
        return gj, "existing"
    os.makedirs(out, exist_ok=True)
    args = ["graphify", "extract", src, "--code-only", "--out", out] + (["--force"] if force else [])
    d = documenter_dir()
    if d:  # copied-in jQuery / Bootstrap / WebForms scripts would bury the real communities and hubs
        sys.path.insert(0, os.path.join(d, "scripts"))
        try:
            from vendor_files import graphify_excludes
            for x in graphify_excludes(src):
                args += ["--exclude", x]
        except ImportError:
            pass
    code, txt = run(args, timeout=7200)
    if code:
        print(f"WARN {repo}: graphify extract failed ({code}): {txt[-400:]}")
        return None, "failed"
    # resolve before clustering so DI / dispatch edges shape the communities, and again after: graph.json is undirected,
    # so cluster-only folds an edge into an existing reverse edge and drops our metadata
    resolve(repo, src)
    sql_layer(repo, src)  # database objects join the communities of the code that uses them
    code, txt = run(["graphify", "cluster-only", out, "--no-label", "--no-viz"], timeout=3600)
    if code:
        print(f"WARN {repo}: graphify cluster-only failed: {txt[-300:]}")
    resolve(repo, src)
    sql_layer(repo, src)
    return (gj if os.path.exists(gj) else None), "built"


def label(repo, llm):
    """Community names: heuristic (no LLM, always unique) or, with --label, an LLM; summaries either way."""
    script = doc_script("community_names.py")
    if not script:
        print(f"{repo}: community naming skipped (codebase-documenter not found)")
        return
    env, used = {}, None
    if llm:
        for n in KEY_VARS:
            v = env_value(n)
            if v:
                env[n], used = v, used or n
        if not used:
            print(f"{repo}: no LLM key in the environment; naming communities without an LLM")
    args = [sys.executable, script, "--graph-dir", os.path.join(graph_dir(repo), "graphify-out"), "--product", repo] + (["--llm"] if used else [])
    code, txt = run(args, env=env, timeout=3600)
    last = (txt.strip().splitlines() or [""])[-1]
    print(f"{repo}: community naming {'FAILED: ' + txt[-200:] if code else 'done'}{f' (LLM, key from {used})' if used and not code else ''}"
          f"{'' if code else ': ' + last[:160]}")


def exports(repo):
    d = graph_dir(repo)
    for args in (["export", "wiki"], ["export", "callflow-html", "--max-sections", "12"]):
        code, txt = run(["graphify"] + args, cwd=d, timeout=1800)
        print(f"{repo}: graphify {' '.join(args)} -> {'ok' if code == 0 else 'failed: ' + txt[-200:]}")


def analyse(repo, gj, inv):
    g = json.load(open(gj, encoding="utf-8"))
    nodes = {n["id"]: n for n in g.get("nodes", [])}
    edges = g.get("links") or g.get("edges") or []
    root = inv["root"]
    pdirs = sorted(((os.path.dirname(p["path"]).replace("\\", "/"), p["name"]) for p in inv["projects"]), key=lambda x: -len(x[0]))

    def norm(sf):
        sf = (sf or "").replace("\\", "/")
        r = root.replace("\\", "/").rstrip("/") + "/"
        if sf.startswith(r):
            sf = sf[len(r):]
        base = os.path.basename(root.rstrip("/\\"))
        if sf.startswith(base + "/"):
            sf = sf[len(base) + 1:]
        return sf

    def project(sf):
        for d, name in pdirs:
            if d and sf.startswith(d + "/"):
                return name
        return "(other)"

    labels_p = os.path.join(os.path.dirname(gj), ".graphify_labels.json")
    labels = read_json(labels_p, {}) or {}
    summaries = read_json(os.path.join(os.path.dirname(gj), "community-summaries.json"), {}) or {}
    comm = defaultdict(lambda: {"size": 0, "files": Counter(), "projects": Counter(), "name": ""})
    degree = Counter()
    file_of = {}
    for nid, n in nodes.items():
        sf = norm(n.get("source_file"))
        file_of[nid] = sf
        c = n.get("community")
        if c is not None:
            cc = comm[c]
            cc["size"] += 1
            if sf:
                cc["files"][os.path.dirname(sf)] += 1
                cc["projects"][project(sf)] += 1
            cc["name"] = labels.get(str(c)) or n.get("community_name") or f"Community {c}"
    dependents = defaultdict(set)
    proj_edges = Counter()
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s not in nodes or t not in nodes:
            continue
        degree[s] += 1
        degree[t] += 1
        if e.get("relation") not in DEP_RELATIONS:
            continue
        fs, ft = file_of.get(s), file_of.get(t)
        if fs and ft and fs != ft:
            dependents[ft].add(fs)
            ps, pt = project(fs), project(ft)
            if ps != pt and "(other)" not in (ps, pt):
                proj_edges[(ps, pt)] += 1
    god = []
    for nid, d in degree.most_common(60):
        n = nodes[nid]
        if n.get("file_type") != "code" or not n.get("_callable_class", n.get("_callable")):
            continue
        god.append({"label": n.get("label"), "degree": d, "file": file_of.get(nid), "line": n.get("source_location"), "project": project(file_of.get(nid) or "")})
        if len(god) >= 15:
            break
    communities = sorted(({"id": c, "name": v["name"], "size": v["size"], "folders": [f for f, _ in v["files"].most_common(3)],
                           "projects": [p for p, _ in v["projects"].most_common(3)],
                           "summary": (summaries.get(str(c)) or {}).get("summary", "")} for c, v in comm.items()), key=lambda x: -x["size"])
    impact = {f: len(s) for f, s in dependents.items()}
    ppaths = sorted(((os.path.dirname(p["path"]).replace("\\", "/"), p["path"]) for p in inv["projects"]), key=lambda x: -len(x[0]))

    def project_path(sf):
        return next((pp for d, pp in ppaths if d and sf.startswith(d + "/")), None)
    wire, wfind = wiring(repo, gj, edges, norm, project_path)
    tests = {p["name"] for p in inv["projects"] if p.get("type") == "test"}
    dbc = db_coupling(nodes, edges, file_of, project, tests)
    for row in dbc.get("shared", []):
        if len(row["app_writers"]) < 2:
            continue
        key = ("DB-MULTI-WRITER", "(repository)")
        f = next((x for x in wfind if (x["rule"], x["project"]) == key), None)
        if not f:
            f = {"id": f"{repo}:DB-MULTI-WRITER:repository", "repo": repo, "project": "(repository)", "rule": "DB-MULTI-WRITER",
                 "category": "database", "title": "Database objects written by more than one project", "severity": "Medium",
                 "confidence": "Confirmed", "occurrences": 0, "files": [], "evidence": [], "source": "sql-parse",
                 "why": "Several projects change the same table (directly or through procedures). In a dual-database or PostgreSQL move "
                        "they have to switch together, agree on one set of data rules (defaults, triggers, concurrency), and a "
                        "partial cut-over leaves the table written by both engines.",
                 "fix": "Give each shared table one owning project (or service) and route the other writers through it; plan the "
                        "cut-over of all writers as one step and test the data rules on both engines.",
                 "alt": "Keep the shared tables on one engine until every writer is ported.", "effort_key": "trivial", "baseline": True,
                 "db": None, "db_only": True, "question": "Which project owns each shared table, and can the other writers move to PostgreSQL at the same time?",
                 "refs": ["S15"]}
            wfind.append(f)
        f["occurrences"] += 1
        test_w = [p for p in row["writers"] if p in tests]
        text = (f"{row['name']} ({row['kind']}) written by {', '.join(row['app_writers'])}"
                + (f" (and tests: {', '.join(test_w)})" if test_w else "") + f"; read by {', '.join(row['readers']) or '-'}")
        # the DDL file when the table has one, otherwise one write site per writing project (EF / code-only schemas)
        sites = [{"file": row["file"], "line": row.get("line") or 1}] if row.get("file") else \
            [next(w for w in row.get("write_sites", []) if w["project"] == pr) for pr in row["writers"]
             if any(w["project"] == pr for w in row.get("write_sites", []))]
        for site in sites:
            if site["file"] not in f["files"]:
                f["files"].append(site["file"])
            if len(f["evidence"]) < 12:
                f["evidence"].append({"file": site["file"], "line": site["line"], "text": text})
    return {"repo": repo, "graph": gj.replace("\\", "/"), "nodes": len(nodes), "edges": len(edges), "communities": communities[:60],
            "community_count": len(communities), "god_nodes": god,
            "project_edges": [{"from": a, "to": b, "count": n} for (a, b), n in proj_edges.most_common(200)],
            "file_impact": dict(sorted(impact.items(), key=lambda x: -x[1])[:2000]), "wiring": wire, "database": dbc}, wfind


def db_coupling(nodes, edges, file_of, project, tests=frozenset()):
    """Who uses each database object (sql_graph.py edges): reading / writing projects, calling routines, code methods.
    Objects used by several projects couple them: they have to move to PostgreSQL (or stay dual) together, and a table
    written by more than one project needs one owner for its conversion and its data rules. Test projects are listed but not
    counted: an integration test that writes a table does not have to be cut over with the applications."""
    db = {i: n for i, n in nodes.items() if n.get("_db_object")}
    if not db:
        return {}
    use = {i: {"read_by": set(), "written_by": set(), "called_by": set(), "routines": set(), "methods": 0, "write_sites": []} for i in db}
    for e in edges:
        s, t, rel = e.get("source"), e.get("target"), e.get("relation")
        if t not in db or s not in nodes or e.get("_origin") != "sql-parse":
            continue
        u = use[t]
        if s in db:
            if db[s].get("kind") in ("PROCEDURE", "FUNCTION", "VIEW", "TRIGGER") and e.get("context") != "foreign key":
                u["routines"].add(nodes[s].get("label"))
            continue
        p = project(file_of.get(s) or "")
        u["methods"] += 1
        if rel == "writes_to":
            u["written_by"].add(p)
            loc = str(e.get("source_location") or nodes[s].get("source_location") or "")
            if file_of.get(s) and len(u["write_sites"]) < 6:  # evidence when the table has no DDL file (EF / code-only schema)
                u["write_sites"].append({"file": file_of[s], "line": int(loc[1:]) if loc[1:].isdigit() else 1, "project": p})
        elif rel == "calls":
            u["called_by"].add(p)
        else:
            u["read_by"].add(p)
    # a routine's callers also reach the tables it touches (one level: enough to see shared tables behind procedures)
    for e in edges:
        s, t, rel = e.get("source"), e.get("target"), e.get("relation")
        if s in db and t in db and e.get("_origin") == "sql-parse" and rel in ("reads_from", "writes_to"):
            callers = use[s]["called_by"]
            (use[t]["written_by"] if rel == "writes_to" else use[t]["read_by"]).update(callers)
    rows = []
    for i, u in use.items():
        projs = sorted((u["read_by"] | u["written_by"] | u["called_by"]) - {"(other)"})
        loc = str(db[i].get("source_location") or "")
        rows.append({"name": db[i].get("label"), "kind": db[i].get("kind"), "external": bool(db[i].get("external")),
                     "file": db[i].get("source_file"), "line": int(loc[1:]) if loc[1:].isdigit() else 0, "projects": projs, "writers": sorted(u["written_by"] - {"(other)"}),
                     "readers": sorted(u["read_by"] - {"(other)"}), "callers": sorted(u["called_by"] - {"(other)"}),
                     "routines": sorted(x for x in u["routines"] if x), "code_sites": u["methods"], "write_sites": u["write_sites"]})
        rows[-1]["app_projects"] = [p for p in projs if p not in tests]
        rows[-1]["app_writers"] = [p for p in rows[-1]["writers"] if p not in tests]
    shared = sorted((r for r in rows if len(r["app_projects"]) > 1), key=lambda r: (-len(r["app_writers"]), -len(r["app_projects"]), r["name"]))
    referenced = {nodes[e["target"]].get("label") for e in edges if e.get("_origin") == "sql-parse" and e.get("target") in db}
    unused = sorted(r["name"] for r in rows if not r["projects"] and not r["routines"] and not r["external"]
                    and r["kind"] not in ("TRIGGER", "SECURITY POLICY") and r["name"] not in referenced)  # run on table events
    by_project = Counter(p for r in rows for p in r["projects"])
    return {"objects": len(rows), "shared": shared[:200], "shared_count": len(shared),
            "multi_writer": [r["name"] for r in shared if len(r["app_writers"]) > 1], "test_projects": sorted(tests),
            "unused_in_code": unused[:300], "unused_count": len(unused), "objects_per_project": dict(by_project.most_common()),
            "usage": sorted(rows, key=lambda r: (-len(r["projects"]), -r["code_sites"]))[:500]}


# Edges csharp_resolve adds that are bound at run time (container, override, message, event, delegate, job, string route).
# "local variable" edges are plain static calls graphify's own pass missed, so they are not indirection; service-locator
# edges are counted from the locator list instead (every call site, not only those that resolved to a method).
STATIC_KINDS = {"local variable", "only implementation", "service locator", "partial class field"}
NAME_SAFE = re.compile(r"nameof\s*\(")   # GetMethod(nameof(X)) (EF HasDbFunction etc.): checked by the compiler, survives renames
CONTAINER_NOTES = {   # legacy containers: (severity, why)
    "unity": ("Medium", "Unity container: its ASP.NET / Web API / interception / convention packages are archived and no longer maintained"),
    "structuremap": ("Medium", "StructureMap is retired (last release 4.7.1); its author's successor is Lamar"),
    "ninject": ("Medium", "Ninject has seen little maintenance activity; ASP.NET Core integration is a separate community package"),
    "autofac": ("Low", "Autofac supports .NET 10 through Autofac.Extensions.DependencyInjection; the System.Web integration "
                       "(Autofac.Mvc5 / WebApi2) does not carry over"),
    "simpleinjector": ("Low", "Simple Injector supports .NET 10 with its ASP.NET Core integration package; the System.Web integration "
                              "does not carry over"),
    "windsor": ("Low", "Castle Windsor supports .NET through Castle.Windsor.Extensions.DependencyInjection; the System.Web "
                       "integration does not carry over"),
}


def wiring(repo, gj, edges, norm, project_path):
    """Run-time wiring facts from csharp-resolve.json + the graph, and findings in the scan schema."""
    cr = read_json(os.path.join(os.path.dirname(gj), "csharp-resolve.json"))
    if not cr:
        return None, []
    regs = cr.get("registrations", [])
    refl = [x for x in cr.get("reflection", []) if not NAME_SAFE.search(x.get("text", ""))]
    per = defaultdict(lambda: {"indirect": 0, "kinds": Counter(), "reflection": 0, "locators": 0, "registrations": 0})
    graphify_calls = 0
    for e in edges:
        if e.get("_origin") != "csharp-resolve":
            graphify_calls += e.get("relation") in ("calls", "indirect_call", "dispatches_to")
            continue
        kind = e.get("context") or "?"
        pp = project_path(norm(e.get("source_file")))
        if pp and kind not in STATIC_KINDS:
            per[pp]["indirect"] += 1
            per[pp]["kinds"][kind] += 1
    for key, items in (("reflection", refl), ("locators", cr.get("locators", [])), ("registrations", regs)):
        for x in items:
            pp = project_path(x.get("file") or "")
            if pp:
                per[pp][key] += 1
    msgs = cr.get("messages", {})
    w = {"containers": cr.get("containers", {}), "registrations": len(regs),
         "by_lifetime": dict(Counter(r.get("lifetime") or "?" for r in regs)),
         "by_host": dict(Counter(h for r in regs for h in (r.get("hosts") or ["(no host found)"]))),
         "keyed": sum(1 for r in regs if r.get("key")), "decorators": sum(1 for r in regs if r.get("how") == "decorator"),
         "factories": sum(1 for r in regs if "factory" in (r.get("how") or "")), "conventions": len(cr.get("conventions", [])),
         "modules": len((cr.get("composition") or {}).get("modules", [])), "consumers": len(cr.get("consumers", [])),
         "messages": len(msgs), "message_handlers": sum(len(d.get("handlers", [])) for d in msgs.values()),
         "pipeline": dict(Counter(x["kind"] for x in cr.get("pipeline", []))), "jobs": len(cr.get("jobs", [])),
         "events": len(cr.get("events", [])), "stored_delegates": len(cr.get("stored_delegates", [])),
         "dispatch_tables": len(cr.get("dispatch_tables", [])), "options": len(cr.get("options", [])),
         "locators": len(cr.get("locators", [])), "reflection": len(refl),
         "reflection_name_safe": len(cr.get("reflection", [])) - len(refl),
         "framework_features": sorted({n["kind"] for n in cr.get("notes", []) if n.get("kind")}),
         "edges_added": cr.get("edges_added", {}), "graphify_calls": graphify_calls,
         "resolver_findings": dict(Counter(f["kind"] for f in cr.get("findings", []))),
         "per_project": {pp: dict(v, kinds=dict(v["kinds"])) for pp, v in sorted(per.items())}}
    return w, wiring_findings(repo, cr, project_path)


def wiring_findings(repo, cr, project_path):
    """Porting-relevant wiring findings, in the scan finding schema (merged by _findings.load)."""
    out = {}

    def add(rule, project, title, sev, conf, why, fix, effort, ev, alt="", count=1, question=None):
        project = project or "(repository)"
        f = out.get((rule, project))
        if not f:
            f = out[(rule, project)] = {
                "id": f"{repo}:{rule}:{re.sub(r'[^A-Za-z0-9]+', '-', project).strip('-').lower()}", "repo": repo, "project": project,
                "rule": rule, "category": "di-wiring", "title": title, "severity": sev, "confidence": conf, "occurrences": 0,
                "files": [], "evidence": [], "why": why, "fix": fix, "alt": alt, "effort_key": effort, "baseline": False, "db": None,
                "question": question, "refs": ["S24"], "source": "graph"}
        f["occurrences"] += count
        if ev["file"] not in f["files"]:
            f["files"].append(ev["file"])
        if len(f["evidence"]) < 8:
            f["evidence"].append(ev)

    regs = cr.get("registrations", [])
    for c in cr.get("containers", {}):
        if c not in CONTAINER_NOTES:
            continue
        sev, why = CONTAINER_NOTES[c]
        for r in (x for x in regs if x.get("container") == c):
            add(f"DI-LEGACY-{c.upper()}", project_path(r["file"]), f"{c.title()} container registrations to move", sev, "Confirmed",
                why + ". Every registration has to be re-created in the new composition root (Program.cs), on Microsoft DI or the "
                "container's own ASP.NET Core integration; lifetimes, named / keyed and convention registrations differ per container.",
                "Move registrations to Microsoft.Extensions.DependencyInjection (keyed services for named registrations, Scrutor for "
                "scanning and decorators) or keep the container through its ASP.NET Core integration package.",
                "medium-change" if sev == "Medium" else "small-change",
                {"file": r["file"], "line": r["line"], "text": f"{r['service']} -> {r.get('impl') or '?'} ({r.get('lifetime')})"},
                alt="Microsoft DI + Scrutor; Lamar (StructureMap successor); Autofac / Simple Injector ASP.NET Core integration")
    for f in cr.get("findings", []):
        ev = {"file": f["file"], "line": f.get("line") or 1, "text": f["text"][:300]}
        pp = project_path(f["file"])
        k = f["kind"]
        if k == "captive dependency":
            add("DI-CAPTIVE", pp, "Captive dependency (singleton holds a scoped service)", "Medium", "Likely",
                "A singleton keeps a scoped service for the life of the process (stale DbContext, cross-request state, thread-safety "
                "bugs). ASP.NET Core validates scopes in Development and throws at startup, so this surfaces as a hard failure the "
                "moment the ported app runs.", "Make the consumer scoped, or inject IServiceScopeFactory and create a scope per "
                "operation.", "small-change", ev)
        elif k in ("missing registration", "possibly missing registration"):
            add("DI-MISSING-REG", pp, "Constructor dependency with no registration found", "Low", "Needs verification",
                "A class activated by the container needs a service the scan found no registration for. It may be registered by "
                "convention, by reflection or outside the repository; if not, the port fails at activation time.",
                "Confirm where the service is registered; add the registration to the new composition root.", "trivial", ev,
                question="Is this service registered somewhere the code scan cannot see (another repository, configuration, plug-in)?")
        elif k == "service locator":
            add("DI-SERVICE-LOCATOR", pp, "Service locator use (dependencies resolved at run time)", "Info", "Confirmed",
                "Dependencies resolved from the container inside methods are hidden from constructors, so the call graph and tests "
                "do not show them. Normal inside a scope created by a singleton or hosted service; costed in the complexity factor.",
                "Prefer constructor injection; keep IServiceScopeFactory for background work.", "per-occurrence-small", ev,
                count=f.get("count", 1))
    for x in cr.get("reflection", []):
        if NAME_SAFE.search(x.get("text", "")):
            continue
        add("DI-REFLECTION", project_path(x["file"]), "Reflection-based activation or member lookup", "Low", "Needs verification",
            "Types or members found by name at run time are invisible to the call graph. On Linux, assembly and file names are "
            "case-sensitive, and trimming / native AOT (if adopted) removes members only reflection uses.",
            "Check each site: replace with DI / generics where possible, or keep and test on Linux.", "small-change",
            {"file": x["file"], "line": x["line"], "text": x["text"][:200]})
    return sorted(out.values(), key=lambda f: f["id"])


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--label", action="store_true", help="name communities with an LLM (needs a key in the environment)")
    ap.add_argument("--exports", action="store_true", help="also export the graphify wiki and call-flow HTML")
    ap.add_argument("--merge", action="store_true", help="merge all repository graphs into one estate graph")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    if run(["graphify", "--help"])[0] != 0:
        sys.exit("graphify is not installed: run the codebase-documenter install_prerequisites.py (or: uv tool install \"graphifyy[sql,openai]\")")
    st = load_state(root)
    names = [a.repo] if a.repo else (sorted(st["repos"]) if a.all or a.merge else [])
    if not names:
        sys.exit("pass --repo NAME or --all (nothing to map)" if a.repo is None and not (a.all or a.merge) else "no repositories discovered: run discover_estate.py first")
    graphs = []
    for name in names:
        inv = read_json(os.path.join(OUT, "inventory", f"{name}.json"))
        if not inv:
            print(f"skip {name}: no inventory")
            continue
        done = st["repos"].get(name, {}).get("graph") == "done"
        gj, how = build(name, inv["root"], a.force)
        if not gj:
            mark(root, name, "graph", "failed")
            continue
        graphs.append(gj)
        gout = os.path.join(graph_dir(name), "graphify-out")
        if how == "existing":  # graph built before a layer existed, or by an older version of it: refresh that layer
            refresh = []
            if stale(os.path.join(gout, "csharp-resolve.json"), "csharp_resolve.py"):
                resolve(name, inv["root"])
                refresh.append("resolve")
            if refresh or stale(os.path.join(gout, "sql-graph.json"), "sql_graph.py", "sql_parse.py"):
                sql_layer(name, inv["root"])
                refresh.append("sql")
            if refresh:
                how = "existing+" + "+".join(refresh)
        if a.label or how != "existing" or not os.path.exists(os.path.join(gout, "community-summaries.json")):
            label(name, a.label)
        if a.exports:
            exports(name)
        if how != "existing" or a.force or a.label or not done or not os.path.exists(os.path.join(graph_dir(name), "analysis.json")):
            res, wf = analyse(name, gj, inv)
            write_json(os.path.join(graph_dir(name), "analysis.json"), res)
            write_json(os.path.join(graph_dir(name), "wiring-findings.json"), wf)
            w = res.get("wiring") or {}
            print(f"{name}: graph {res['nodes']:,} nodes / {res['edges']:,} edges, {res['community_count']} communities, "
                  f"top hub: {res['god_nodes'][0]['label'] if res['god_nodes'] else '-'} ({how})"
                  + (f"; wiring: {w['registrations']} registrations, {sum(w['edges_added'].values())} calls resolved beyond graphify, "
                     f"{len(wf)} finding(s)" if w else ""))
        mark(root, name, "graph")
    if a.merge and len(graphs) > 1:
        out = os.path.join(OUT, "graphs", "estate-graph.json")
        code, txt = run(["graphify", "merge-graphs"] + graphs + ["--out", out], timeout=3600)
        print(f"estate graph: {'ok -> ' + out if code == 0 else 'failed: ' + txt[-300:]}")
    mark_step(root, "graphs")


if __name__ == "__main__":
    main()
