"""Run the documentation pipeline: reference adapters -> tag resolution -> agent index -> MkDocs site.

    python <skill>/scripts/build_site.py                 # everything
    python <skill>/scripts/build_site.py --skip-adapters  # only re-resolve narrative pages, index and site
    python <skill>/scripts/build_site.py --no-site        # skip mkdocs build (faster while writing)

Adapters (codebase-docs.json "adapters", run in order; generic-areas always last):
  generic-graph    components / modules / communities from graphify's graph.json (any language)
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
    "generic-graph": ["generic/graph_reference.py"],
    "generic-sql": ["generic/sql_reference.py"],
    "generic-config": ["generic/config_reference.py"],
    "generic-areas": ["generic/area_map.py"],
    "aspnet-mvc-ssdt": ["aspnet-mvc-ssdt/gen_reference.py", "aspnet-mvc-ssdt/gen_seeds.py",
                        "aspnet-mvc-ssdt/gen_inventory.py", "aspnet-mvc-ssdt/gen_ssrs.py"],
}
RUNTIME = ("build_docs.py", "gen_agent_index.py", "lookup.py")


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
        names = [n for n in cfg["adapters"] if n != "generic-areas"] + (["generic-areas"] if "generic-areas" in cfg["adapters"] else [])
        for name in names:
            scripts = ([name.split(":", 1)[1]] if name.startswith("custom:") else ADAPTER_SCRIPTS.get(name))
            if not scripts:
                print(f"unknown adapter: {name}")
                failed = True
                continue
            for s in scripts:
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
