"""graphify orchestration for codebase-documenter — deterministic wrappers so the agent runs one command per step.

    python <skill>/scripts/code_graph.py check                    # is graphify installed? which LLM keys are available?
    python <skill>/scripts/code_graph.py build [--semantic] [--deep] [--postgres DSN] [--force]
                                                                  # extract -> C# call resolver -> cluster -> resolver -> names
    python <skill>/scripts/code_graph.py label [--model M] [--engine auto|llm|heuristic|graphify] [--only-missing]
                                                                  # build already names communities heuristically (free);
                                                                  # label upgrades them with an LLM when a key exists
    python <skill>/scripts/code_graph.py labels-review            # placeholders / weak / duplicate community names
    python <skill>/scripts/code_graph.py rename <community-id> "<Name>"   # hand-name one community
    python <skill>/scripts/code_graph.py export [--obsidian] [--graphml] [--svg]
    python <skill>/scripts/code_graph.py summary                  # writes docs/_notes/01-graph.md + docs/_notes/areas.json
    python <skill>/scripts/code_graph.py ask "<topic>" [--budget 800] [--affected]   # query + top-node explain in one call
    python <skill>/scripts/code_graph.py hook                     # git hooks: keep the graph current after commits
    python <skill>/scripts/code_graph.py resolve                  # re-add C# DI / dispatch / message / event edges (after graphify update)
    python <skill>/scripts/code_graph.py all [--label]            # build → (label) → export → summary

Never pass API keys on the command line; they are read from environment variables (process or, on Windows,
the user environment set with `setx`).
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

from _common import load_config, run, tick, utf8_stdout, write

KEY_VARS = ["OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY"]
# Community naming is a small, high-volume job, so the default is the cheapest capable model on OpenRouter.
# Override per project (codebase-docs.json -> graph.model), per machine (CODEBASE_DOCS_LLM_MODEL) or per run (--model).
DEFAULT_MODEL = {"OPENROUTER_API_KEY": "z-ai/glm-5.3-flash"}
MODEL_ENV = "CODEBASE_DOCS_LLM_MODEL"
SUGGEST = """Community naming needs an LLM key (optional; without one, communities keep generated names).
  Recommended: OpenRouter + GLM 5.3 Flash (cheap, good at short labels).
    1. Create a key at https://openrouter.ai/keys
    2. Windows:  setx OPENROUTER_API_KEY "<key>"     macOS/Linux:  export OPENROUTER_API_KEY=<key>  (add to your shell profile)
    3. Open a new terminal and rerun.
  Alternatives (first one found is used): OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, DEEPSEEK_API_KEY,
  MOONSHOT_API_KEY, or any OpenAI-compatible endpoint via codebase-docs.json -> graph.base_url + graph.api_key_env.
  Pick another model any time: --model <id>, graph.model, or the CODEBASE_DOCS_LLM_MODEL environment variable."""
PLACEHOLDER = re.compile(r"(?i)^community \d+$")


def env_value(name):
    v = os.environ.get(name)
    if v or os.name != "nt":
        return v
    code, out = run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetEnvironmentVariable('{name}','User')"])
    return out.strip() or None if code == 0 else None


def gfy(args, env=None, check=False, timeout=None):
    code, out = run(["graphify"] + args, env=env, timeout=timeout)
    if check and code:
        sys.exit(f"graphify {' '.join(args)} failed:\n{out[-3000:]}")
    return code, out


def label_env(cfg, model_arg=None):
    """Map the available key to graphify's OpenAI-compatible backend (OpenRouter preferred when present)."""
    g = cfg["graph"]
    want = g.get("api_key_env")
    names = [want] if want else KEY_VARS
    for n in names:
        v = env_value(n)
        if not v:
            continue
        chosen = model_arg or g.get("model") or env_value(MODEL_ENV) or DEFAULT_MODEL.get(n)
        if n == "OPENROUTER_API_KEY":
            return {"OPENAI_API_KEY": v, "OPENAI_BASE_URL": g.get("base_url") or "https://openrouter.ai/api/v1",
                    "OPENAI_MODEL": chosen or ""}, "openai", n
        backend = {"OPENAI_API_KEY": "openai", "ANTHROPIC_API_KEY": "claude", "GEMINI_API_KEY": "gemini",
                   "DEEPSEEK_API_KEY": "deepseek", "MOONSHOT_API_KEY": "kimi"}.get(n, g.get("backend") or "openai")
        env = {n: v}
        if g.get("base_url"):
            env["OPENAI_BASE_URL"] = g["base_url"]
        if chosen:
            env["OPENAI_MODEL"] = chosen
        return env, backend, n
    return None, None, None


def labels_path(cfg):
    return os.path.join(cfg["graph_dir"], ".graphify_labels.json")


def load_graph(cfg):
    return json.load(open(os.path.join(cfg["graph_dir"], "graph.json"), encoding="utf-8"))


def cmd_check(cfg, a):
    code, out = gfy(["--help"])
    print("graphify:", "installed" if code == 0 else 'NOT installed -> python <skill>/scripts/install_prerequisites.py')
    found = [n for n in KEY_VARS if env_value(n)]
    print("LLM keys available:", ", ".join(found) if found else "none (community naming and semantic extraction will be skipped)")
    env, backend, name = label_env(cfg)
    if env:
        print(f"naming model: {env.get('OPENAI_MODEL') or backend + ' default'} via {name}"
              f"  (change: --model, graph.model, or {MODEL_ENV})")
    else:
        print(SUGGEST)
    print("graph:", "present" if os.path.exists(os.path.join(cfg["graph_dir"], "graph.json")) else "not built")


def graph_size(cfg):
    """(nodes per source language, top folders by script nodes) from graph.json, for the size check after extract."""
    try:
        g = load_graph(cfg)
    except (OSError, ValueError):
        return Counter(), Counter()
    langs, js_dirs = Counter(), Counter()
    for n in g.get("nodes", []):
        sf = str(n.get("source_file") or "").replace("\\", "/")
        ext = os.path.splitext(sf)[1].lower()
        if not ext:
            continue
        lang = {".cs": "C#", ".vb": "VB", ".js": "JavaScript", ".mjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
                ".jsx": "JavaScript", ".py": "Python", ".java": "Java", ".sql": "SQL"}.get(ext, ext)
        langs[lang] += 1
        if lang == "JavaScript":
            rel = os.path.relpath(sf, cfg["source_root"]).replace("\\", "/") if os.path.isabs(sf) else sf
            js_dirs["/".join(rel.split("/")[:3][:-1]) or "."] += 1
    return langs, js_dirs


def cmd_build(cfg, a):
    from _common import GraphLock
    with GraphLock(cfg, "build"):
        build(cfg, a)


def build(cfg, a):
    import time
    from _common import step
    t_all = time.time()
    src = cfg["source_root"]
    args = ["extract", src, "--out", "."]
    if not a.semantic:
        args.append("--code-only")
    elif a.deep:
        args += ["--mode", "deep"]
    if a.force:
        args.append("--force")
    if a.postgres:
        args += ["--postgres", a.postgres]
    from vendor_files import graphify_excludes  # copied-in jQuery / Bootstrap / WebForms scripts are not the project's code
    t = time.time()
    step("finding vendored front-end libraries ...")
    rep = {}
    excl = graphify_excludes(src, report=rep)
    for x in excl:
        args += ["--exclude", x]
    if excl:
        step(f"excluding {len(excl)} vendored pattern(s): {len(rep.get('configured', []))} configured folder(s), "
             f"{len(rep.get('folders', []))} library folder(s), {rep.get('files', 0)} single file(s)", t)
    env = None
    if a.semantic:
        env, backend, name = label_env(cfg)
        if not env:
            sys.exit("--semantic needs an LLM key (see `code_graph.py check`); run without it for AST-only extraction")
        args += ["--backend", backend]
    shown, skip = [], False
    for x in args:  # the --exclude list can be long: count it instead of printing every pattern
        if skip:
            skip = False
            continue
        if x == "--exclude":
            skip = True
            continue
        shown.append(x)
    print("$ graphify " + " ".join(shown) + (f" (+{len(excl)} --exclude patterns)" if excl else ""), flush=True)
    t = time.time()
    step("1/6 graphify extract (the longest step on a big repository) ...")
    code, out = gfy(args, env=env)
    print(out[-1500:], flush=True)
    if code:
        sys.exit(code)
    langs, js_dirs = graph_size(cfg)
    step("1/6 extract done: " + (", ".join(f"{k} {v}" for k, v in langs.most_common(6)) + " nodes" if langs else "no nodes"), t)
    code_nodes = langs.get("C#", 0) + langs.get("VB", 0)
    if code_nodes and langs.get("JavaScript", 0) > code_nodes:
        print(f"WARNING: the graph holds more JavaScript nodes ({langs['JavaScript']}) than C# / VB nodes ({code_nodes}). Copied "
              "libraries are probably still inside. Largest script folders: "
              + ", ".join(f"{d} ({n})" for d, n in js_dirs.most_common(5))
              + ". Add the library folders to graph.vendor_dirs in codebase-docs.json and rerun with --force.", flush=True)
    t = time.time()
    step("2/6 C# call resolver (first pass) ...")
    resolve_calls(quiet=True)  # before clustering: DI / dispatch edges help communities group interfaces with implementations
    step("3/6 database layer (first pass) ...", t)
    t = time.time()
    sql_layer(quiet=True)      # database objects + SQL edges, so tables cluster with the code that uses them
    step("4/6 clustering ...", t)
    t = time.time()
    code, out = gfy(["cluster-only", ".", "--no-label"] + (["--no-viz"] if a.no_viz else []))
    print(out[-800:], flush=True)
    if "NOT written" in out or "Refusing to overwrite" in out:  # graphify kept the old graph: no communities this run
        print("WARNING: graphify did not save the clustered graph (it merged nodes on reload and refused to write a smaller "
              "graph), so communities are missing or stale. Log it in SKILL-ISSUES.md.", flush=True)
    step("5/6 C# call resolver and database layer (second pass) ...", t)
    t = time.time()
    resolve_calls()            # again after: graphify stores an undirected simple graph, so A->B merges into an existing B->A
    sql_layer()
    step("6/6 naming communities ...", t)
    t = time.time()
    name_communities([])       # heuristic names straight away (free, unique); `label` upgrades them with an LLM
    step("graph build finished", t_all)
    if code == 0:
        tick(cfg, "graphify installed, graph built")


def name_communities(extra):
    code, out = run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "community_names.py")] + extra)
    print(out.strip()[-2500:])
    return code


def resolve_calls(quiet=False):
    """C# calls graphify cannot see (DI, overrides, messages, events, jobs ...): scripts/csharp_resolve.py, idempotent."""
    code, out = run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "csharp_resolve.py")]
                    + (["--quiet"] if quiet else []))
    if not quiet or code:
        print(out.strip()[-1500:])


def sql_layer(quiet=False):
    """Database objects and SQL edges graphify cannot see: scripts/sql_graph.py (T-SQL parser), idempotent."""
    code, out = run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql_graph.py")]
                    + (["--quiet"] if quiet else []))
    if not quiet or code:
        print(out.strip()[-1500:])


def cmd_resolve(cfg, a):
    from _common import GraphLock
    with GraphLock(cfg, "resolve"):
        resolve_calls()
        sql_layer()


def cmd_label(cfg, a):
    """LLM community names with a rich per-community profile (community_names.py --llm); heuristic names stay as the
    fallback for any community the model does not name. --engine heuristic: no LLM; --engine graphify: graphify's own labeller."""
    if a.engine in ("auto", "llm", "heuristic"):
        env, _, _ = label_env(cfg, a.model)
        if a.engine == "heuristic" or not env:
            if not env and a.engine != "heuristic":
                print(SUGGEST)
                print("No LLM key: heuristic names kept (unique, built from member names, namespaces, folders and roles).")
            name_communities([])
            return
        extra = ["--llm"] + (["--model", a.model] if a.model else []) + (["--only-missing"] if a.only_missing else [])
        if name_communities(extra) == 0:
            tick(cfg, "communities named")
        review(cfg)
        return
    env, backend, name = label_env(cfg, a.model)
    if not env:
        print(SUGGEST)
        print("SKIPPED: no LLM API key found; communities keep their heuristic names (optional step).")
        return
    model = env.get("OPENAI_MODEL") or a.model or cfg["graph"].get("model")
    for rnd in range(1, a.rounds + 1):
        args = ["label", ".", f"--backend={backend}", "--missing-only", f"--batch-size={cfg['graph'].get('batch_size', 2)}"]
        if model:
            args.append(f"--model={model}")
        print(f"round {rnd}: graphify {' '.join(args)}  (key from {name})")
        code, out = gfy(args, env=env)
        fail = re.search(r"labeling failed \((.{0,160})", out)
        if fail:
            print(f"LABELING FAILED (key {name}): {fail.group(1)}\n"
                  "Communities keep fallback names. Fix the key/model (codebase-docs.json → graph) and rerun, or skip naming.")
            break
        print(out[-600:])
        missing = review(cfg, quiet=True)
        if not missing:
            tick(cfg, "communities named")
            break
    review(cfg)


def review(cfg, quiet=False):
    p = labels_path(cfg)
    if not os.path.exists(p):
        if not quiet:
            print("no labels file yet")
        return []
    labels = json.load(open(p, encoding="utf-8"))
    ph = [k for k, v in labels.items() if PLACEHOLDER.match(str(v))]
    weak = [k for k, v in labels.items() if not PLACEHOLDER.match(str(v)) and " " not in str(v).strip()]
    dup = [v for v, c in Counter(labels.values()).items() if c > 1 and not PLACEHOLDER.match(str(v))]
    if not quiet:
        print(f"communities: {len(labels)} · placeholders: {len(ph)} · one-word: {len(weak)} · duplicated names: {len(dup)}")
        if weak:
            print("one-word labels to improve (code_graph.py rename <id> \"<Name>\"):", ", ".join(f"{k}={labels[k]}" for k in weak[:30]))
        if dup:
            print("duplicated names:", "; ".join(dup[:20]))
    return ph


def cmd_rename(cfg, a):
    p = labels_path(cfg)
    labels = json.load(open(p, encoding="utf-8"))
    labels[str(a.id)] = a.name
    write(p, json.dumps(labels, indent=2, ensure_ascii=False))
    sp = os.path.join(cfg["graph_dir"], "community-summaries.json")
    if os.path.exists(sp):  # keep the hand-given name when names are regenerated
        s = json.load(open(sp, encoding="utf-8"))
        if str(a.id) in s:
            s[str(a.id)].update(name=a.name, source="manual")
            write(sp, json.dumps(s, indent=1, ensure_ascii=False))
    print(f"community {a.id} -> {a.name}  (run `code_graph.py export` to refresh wiki/report)")


def tree_root(cfg):
    """graphify stores source_file relative to the folder it extracted: the source root or the workspace."""
    try:
        g = load_graph(cfg)
        sample = next((n.get("source_file") for n in g["nodes"] if n.get("source_file")), "")
    except Exception:
        return "."
    src = cfg["source_root"].replace("\\", "/").strip("/")
    return cfg["source_root"] if src not in ("", ".") and sample.replace("\\", "/").startswith(src + "/") else "."


def cmd_export(cfg, a):
    g = cfg["graph_dir"]
    gj = os.path.join(g, "graph.json")
    lab = labels_path(cfg)
    lab_args = ["--labels", lab] if os.path.exists(lab) else []
    steps = [
        ["export", "wiki", "--graph", gj] + lab_args,
        ["export", "html", "--graph", gj] + lab_args,
        ["export", "callflow-html", "--graph", gj, "--output", os.path.join(g, "CALLFLOW.html"), "--lang", "en"] + lab_args,
        ["tree", "--graph", gj, "--root", tree_root(cfg), "--label", cfg.get("code_name") or cfg.get("product") or "project",
         "--output", os.path.join(g, "GRAPH_TREE.html")],
    ]
    if a.obsidian:
        steps.append(["export", "obsidian", "--graph", gj, "--dir", os.path.join(g, "obsidian")] + lab_args)
    if a.graphml:
        steps.append(["export", "graphml", "--graph", gj])
    if a.svg:
        steps.append(["export", "svg", "--graph", gj] + lab_args)
    for s in steps:
        code, out = gfy(s)
        print(("ok   " if code == 0 else "FAIL ") + "graphify " + " ".join(s[:2]) + ("" if code == 0 else "\n" + out[-500:]))


def cmd_summary(cfg, a):
    """Write docs/_notes/01-graph.md (facts the research phase needs) and areas.json (candidate research areas)."""
    g = load_graph(cfg)
    gj = os.path.join(cfg["graph_dir"], "graph.json")
    nodes, links = g["nodes"], g["links"]
    rels = Counter(e.get("relation") for e in links)
    conf = Counter(e.get("confidence") for e in links)
    labels = {}
    if os.path.exists(labels_path(cfg)):
        labels = json.load(open(labels_path(cfg), encoding="utf-8"))
    comm_nodes = defaultdict(list)
    for n in nodes:
        if n.get("community") is not None:
            comm_nodes[n["community"]].append(n)
    _, gods = gfy(["god-nodes", "--top", "20", "--graph", gj])
    _, bench = gfy(["benchmark", gj], timeout=600)
    _, diag = gfy(["diagnose", "multigraph", "--graph", gj, "--max-examples", "3"])
    exts = Counter(os.path.splitext(n.get("source_file") or "")[1].lower() for n in nodes if n.get("source_file"))
    out = ["# 01 — Code graph (graphify)", "", "Generated by `code_graph.py summary`. Use it to plan research areas; verify every fact in code.", "",
           "## Size", "", f"- Nodes: {len(nodes):,} · edges: {len(links):,} · communities: {len(comm_nodes):,}",
           "- Edge relations: " + ", ".join(f"{k} {v:,}" for k, v in rels.most_common(12)),
           "- Confidence: " + ", ".join(f"{k} {v:,}" for k, v in conf.most_common()),
           "- Node files by extension: " + ", ".join(f"{k or '(none)'} {v:,}" for k, v in exts.most_common(12)), "",
           "## God nodes (most connected — architectural hubs)", "", "```", gods.strip()[:4000], "```", "",
           "## Largest communities", "", "| Id | Name | Nodes | Summary | Top folders |", "| ---: | --- | ---: | --- | --- |"]
    sp = os.path.join(cfg["graph_dir"], "community-summaries.json")
    sums = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    areas = []
    for cid, ns in sorted(comm_nodes.items(), key=lambda kv: -len(kv[1]))[:60]:
        dirs = Counter(os.path.dirname(n.get("source_file") or "") for n in ns if n.get("source_file"))
        top = [d for d, _ in dirs.most_common(3)]
        name = labels.get(str(cid)) or ns[0].get("community_name") or f"Community {cid}"
        summ = (sums.get(str(cid)) or {}).get("summary", "")
        out.append(f"| {cid} | {name} | {len(ns):,} | {summ.replace('|', '/')} | {', '.join('`' + d + '`' for d in top)} |")
        files = [f for f, _ in Counter((n.get("source_file") or "").replace("\\", "/") for n in ns if n.get("source_file")).most_common(10)]
        areas.append({"community": cid, "name": name, "size": len(ns), "folders": top, "files": files, "summary": summ})
    rp = os.path.join(cfg["graph_dir"], "csharp-resolve.json")
    if os.path.exists(rp):
        r = json.load(open(rp, encoding="utf-8"))
        out += ["", "## Calls resolved beyond graphify (csharp_resolve.py)", "",
                f"- Registrations: {len(r.get('registrations', []))} in hosts "
                + ", ".join(sorted({h for x in r.get('registrations', []) for h in x.get('hosts', [])})),
                "- Containers: " + (", ".join(f"{k} {v}" for k, v in r.get("containers", {}).items()) or "none"),
                "- Edges added: " + (", ".join(f"{k} {v}" for k, v in sorted(r.get("edges_added", {}).items(), key=lambda kv: -kv[1])) or "none"),
                f"- Messages: {len(r.get('messages', {}))} · pipeline items: {len(r.get('pipeline', []))} · jobs: {len(r.get('jobs', []))} · "
                f"events: {len(r.get('events', []))} · stored delegates: {len(r.get('stored_delegates', []))} · reflection sites: {len(r.get('reflection', []))}",
                f"- Wiring findings: {len(r.get('findings', []))} (see docs/reference/dependency-injection.md after build_site)"]
    out += ["", "## Token economy (graphify benchmark)", "", "```", bench.strip()[-1500:], "```", "",
            "## Multigraph diagnosis", "", "```", diag.strip()[-1200:], "```", "",
            "## Views", "", f"- Wiki: `{cfg['graph_dir']}/wiki/index.md` · HTML: `graph.html`, `CALLFLOW.html`, `GRAPH_TREE.html` · report: `GRAPH_REPORT.md`"]
    docs = cfg["docs_dir"]
    write(os.path.join(docs, "_notes", "01-graph.md"), "\n".join(out) + "\n")
    write(os.path.join(docs, "_notes", "graph-communities.json"), json.dumps(areas, indent=1, ensure_ascii=False))
    print(f"wrote {docs}/_notes/01-graph.md ({len(comm_nodes)} communities, top {len(areas)} listed)")
    tick(cfg, "exports (wiki")


def cmd_ask(cfg, a):
    gj = os.path.join(cfg["graph_dir"], "graph.json")
    code, out = gfy(["query", a.topic, "--budget", str(a.budget), "--graph", gj])
    print(out.strip())
    if a.affected:
        hit = re.search(r"^\s*[-*]?\s*([A-Za-z_][\w.]+)", out, re.M)
        if hit:
            code, aff = gfy(["affected", hit.group(1), "--depth", "1", "--graph", gj])
            print("\n--- affected by", hit.group(1), "---\n" + aff.strip()[:3000])


def cmd_hook(cfg, a):
    for s in (["hook", "install"], ["hook", "status"]):
        code, out = gfy(s)
        print(out.strip()[-600:])


def cmd_all(cfg, a):
    cmd_build(cfg, a)
    if a.label:
        cmd_label(cfg, a)
    cmd_export(cfg, a)
    cmd_summary(cfg, a)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("check")
    for name in ("build", "all"):
        b = sp.add_parser(name)
        b.add_argument("--semantic", action="store_true", help="also LLM-extract docs/papers (needs a key)")
        b.add_argument("--deep", action="store_true")
        b.add_argument("--force", action="store_true")
        b.add_argument("--postgres")
        b.add_argument("--no-viz", action="store_true")
        b.add_argument("--obsidian", action="store_true")
        b.add_argument("--graphml", action="store_true")
        b.add_argument("--svg", action="store_true")
        if name == "all":
            b.add_argument("--label", action="store_true")
            b.add_argument("--model")
            b.add_argument("--rounds", type=int, default=5)
            b.add_argument("--engine", default="auto")
            b.add_argument("--only-missing", action="store_true")
    l = sp.add_parser("label")
    l.add_argument("--model")
    l.add_argument("--rounds", type=int, default=5)
    l.add_argument("--engine", choices=["auto", "llm", "heuristic", "graphify"], default="auto")
    l.add_argument("--only-missing", action="store_true", help="LLM only for communities still named by the heuristic")
    sp.add_parser("labels-review")
    r = sp.add_parser("rename")
    r.add_argument("id")
    r.add_argument("name")
    e = sp.add_parser("export")
    e.add_argument("--obsidian", action="store_true")
    e.add_argument("--graphml", action="store_true")
    e.add_argument("--svg", action="store_true")
    sp.add_parser("summary")
    q = sp.add_parser("ask")
    q.add_argument("topic")
    q.add_argument("--budget", type=int, default=800)
    q.add_argument("--affected", action="store_true")
    sp.add_parser("hook")
    sp.add_parser("resolve")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    {"check": cmd_check, "build": cmd_build, "label": cmd_label, "labels-review": lambda c, x: review(c), "rename": cmd_rename,
     "export": cmd_export, "summary": cmd_summary, "ask": cmd_ask, "hook": cmd_hook, "all": cmd_all, "resolve": cmd_resolve}[a.cmd](cfg, a)


if __name__ == "__main__":
    main()
