"""Run the documentation pipeline: reference adapters -> tag resolution -> agent index -> MkDocs site.

    python <skill>/scripts/build_site.py                 # everything
    python <skill>/scripts/build_site.py --skip-adapters  # only re-resolve narrative pages, index and site
    python <skill>/scripts/build_site.py --no-site        # skip mkdocs build (faster while writing)

Adapters (codebase-docs.json "adapters", run in order; generic-areas always last):
  generic-graph    components / modules / communities from graphify's graph.json (any language), plus the method map
  generic-methods  only the method map (declarations, calls, called by): add it next to aspnet-mvc-ssdt
  generic-deps     project and package dependencies from build manifests (layers, cycles, version drift)
  generic-api      every HTTP endpoint: verb, route, handler, parameters, auth (ASP.NET, Express, NestJS, Flask, FastAPI,
                   Django, Spring, Go, OpenAPI files)
  generic-errors   error catalogue: every exception / validation / HTTP / database error message and its method
  generic-tests    test map: production methods the tests reach through the call graph, and the ones nothing tests
  generic-build    build and run facts for the runbook (toolchain, commands, launch profiles, Docker, CI, environments)
  generic-dbaccess database call sites: which method reads / writes / executes each table and routine, and with what
                   (ADO.NET, Dapper, EF Core / EF6 LINQ or raw SQL, NHibernate, JPA, JDBC ...)
  generic-trace    UI map (what each button / link / form / script calls, down to the database) and entry points
                   (endpoints, UI events, jobs) with everything each reaches; reverse indexes method -> entry points
  generic-di       C# dependency injection and indirect calls: registrations per host, services, constructor dependencies,
                   message handlers, request pipeline, jobs, events, options, wiring findings; first re-applies the resolved
                   calls (DI, overrides, messages, events, method groups, jobs, redirects, filters) to graph.json
  generic-views    every view, page and screen (MVC, Razor Pages, Blazor, Web Forms, ASMX / ASHX, WinForms, WPF / MAUI XAML)
                   with route, model, layout, code-behind, lines and totals per kind and project
  generic-portability  Windows-to-Linux / modern .NET portability flags (the migration-assessment portability rules only),
                   file:line per rule, plus the Windows-only packages from generic-deps
  generic-endpoints  network endpoints: every outbound destination (host, port, protocol, internal / external, config key,
                   methods that use it), every inbound listener (launchSettings, Kestrel, Docker, compose, WCF) and the outbound
                   call sites (HttpClient, WCF, SMTP, FTP, brokers, cloud SDKs): the input for allow-lists and integration docs
  generic-flows    business-flow pages + interactive viewer from docs/_src/workflows/flows/*.flow.json (runs late)
  generic-sql      tables and routines from .sql DDL (SSDT, migrations, schema folders)
  generic-config   configuration key names per config file (never values)
  generic-areas    code & data map by business area (narrative page; drives coverage)
  aspnet-mvc-ssdt  ASP.NET MVC controllers/actions, views, components, models, JS, EF aliases, SSDT seeds,
                   permissions, SSRS (options in adapter_options)
  custom:<path>    any project script that writes docs/reference/*.md following the anchor contract (reference/adapters.md)
Prints a compact summary; full adapter output only on failure.
"""
import argparse
import os
import re
import shutil
import sys

from _common import ADAPTERS, SKILL_DIR, load_config, run, tick, utf8_stdout

ADAPTER_SCRIPTS = {
    "generic-graph": ["generic/graph_reference.py", "generic/method_reference.py"],
    "generic-methods": ["generic/method_reference.py"],
    "generic-deps": ["generic/dependency_reference.py"],
    "generic-flows": ["generic/flow_pages.py"],
    "generic-api": ["generic/api_reference.py"],
    "generic-errors": ["generic/error_reference.py"],
    "generic-tests": ["generic/test_map.py"],
    "generic-build": ["generic/build_reference.py"],
    "generic-dbaccess": ["generic/db_access.py"],
    "generic-trace": ["generic/trace_map.py"],
    "generic-sql": ["generic/sql_reference.py"],
    "generic-config": ["generic/config_reference.py"],
    "generic-areas": ["generic/area_map.py"],
    "generic-di": ["generic/di_reference.py"],
    "generic-views": ["generic/view_reference.py"],
    "generic-portability": ["generic/portability_reference.py"],
    "generic-endpoints": ["generic/endpoint_reference.py"],
    "aspnet-mvc-ssdt": ["aspnet-mvc-ssdt/gen_reference.py", "aspnet-mvc-ssdt/gen_seeds.py",
                        "aspnet-mvc-ssdt/gen_inventory.py", "aspnet-mvc-ssdt/gen_ssrs.py"],
}
RUNTIME = ("build_docs.py", "gen_agent_index.py", "gen_rag_cards.py", "lookup.py")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-adapters", action="store_true")
    ap.add_argument("--no-site", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    docs = cfg["docs_dir"]
    env = {"DOCS_SOURCE_ROOT": cfg["source_root"]}
    tools = os.path.join(docs, "_tools")
    os.makedirs(tools, exist_ok=True)
    for f in RUNTIME:  # keep the project's runtime tools in step with the skill version
        shutil.copy2(os.path.join(SKILL_DIR, "scripts", "runtime", f), os.path.join(tools, f))
    failed = False
    if not a.skip_adapters:
        # these read the method map / finished reference, so they run after the others, in this order
        late = ["generic-api", "generic-errors", "generic-di", "generic-tests", "generic-dbaccess", "generic-trace", "generic-views",
                "generic-portability", "generic-endpoints", "generic-flows", "generic-areas"]
        names = [n for n in cfg["adapters"] if n not in late] + [n for n in late if n in cfg["adapters"]]
        done = set()
        if "generic-di" in cfg["adapters"]:
            # graphify update / an older graph may lack the resolved C# calls; every adapter below reads graph.json
            code, out = run([sys.executable, os.path.join(SKILL_DIR, "scripts", "csharp_resolve.py")])
            print(f"{'ok  ' if code == 0 else 'FAIL'} csharp-resolve: {' | '.join(l.strip() for l in out.strip().splitlines()[-2:])[:300]}")
            failed |= code != 0
        sg = os.path.join(cfg.get("graph_dir", ""), "sql-graph.json")
        sql_scripts = [os.path.join(SKILL_DIR, "scripts", f) for f in ("sql_graph.py", "sql_parse.py")]
        if os.path.exists(os.path.join(cfg.get("graph_dir", ""), "graph.json")) and \
                (not os.path.exists(sg) or any(os.path.getmtime(p) > os.path.getmtime(sg) for p in sql_scripts)):
            # database layer missing, or written by an older sql_graph.py: refresh it before the adapters read graph.json
            code, out = run([sys.executable, sql_scripts[0]])
            print(f"{'ok  ' if code == 0 else 'FAIL'} sql-graph: {' | '.join(l.strip() for l in out.strip().splitlines()[-2:])[:300]}")
            failed |= code != 0
        for name in names:
            scripts = ([name.split(":", 1)[1]] if name.startswith("custom:") else ADAPTER_SCRIPTS.get(name))
            if not scripts:
                print(f"unknown adapter: {name}")
                failed = True
                continue
            for s in scripts:
                if s in done:  # generic-graph already ran the method map
                    continue
                done.add(s)
                path = s if name.startswith("custom:") else os.path.join(ADAPTERS, s)
                e = dict(env, PYTHONPATH=os.path.dirname(path) + os.pathsep + os.environ.get("PYTHONPATH", ""))
                code, out = run([sys.executable, path], env=e)
                last = [l for l in out.strip().splitlines() if l.strip()][-3:]
                print(f"{'ok  ' if code == 0 else 'FAIL'} {name}/{os.path.basename(path)}: {' | '.join(last)[:300]}")
                if code or a.verbose:
                    print(out[-3000:])
                failed |= code != 0
    code, out = run([sys.executable, os.path.join(tools, "build_docs.py")])
    print("build_docs:", " · ".join(l for l in out.strip().splitlines() if not l.startswith("    "))[:600])
    unresolved = re.findall(r"UNRESOLVED (\w+): (\d+)", out)
    if unresolved:
        print("\n".join(l for l in out.splitlines() if l.startswith("    "))[:4000])
    failed |= code != 0
    code, out = run([sys.executable, os.path.join(tools, "gen_agent_index.py")])
    print("agent index:", out.strip()[:200])
    failed |= code != 0
    code, out = run([sys.executable, os.path.join(tools, "gen_rag_cards.py")])
    print("rag cards:", out.strip()[-300:])
    failed |= code != 0
    if not a.no_site:
        code, out = run([sys.executable, "-m", "mkdocs", "build"])
        warns = [l for l in out.splitlines() if "WARNING" in l and "MkDocs 2.0" not in l]
        print(f"mkdocs: {'ok' if code == 0 else 'FAILED'} · warnings: {len(warns)}")
        for w in warns[:30]:
            print("   ", w.split("WARNING -", 1)[-1].strip()[:240])
        if code and "No module named mkdocs" in out:
            print("    install: pip install mkdocs-material")
        failed |= code != 0
    if not failed and not unresolved:
        tick(cfg, "adapters chosen")
        tick(cfg, "pipeline runs clean")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
