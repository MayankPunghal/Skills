"""Map each repository with graphify (AST code graph) and derive the architecture facts the report needs.

    python <skill>/scripts/map_graphs.py --repo NAME | --all [--force] [--label] [--exports] [--merge]

Per repository (assessment/graphs/<repo>/):
  graphify extract <repo> --code-only        code graph (free, no LLM)
  graphify cluster-only                      communities + GRAPH_REPORT.md
  graphify label (with --label)              LLM community names, only when an API key is in the environment
  graphify export wiki / callflow-html (with --exports)   navigable wiki and Mermaid call flows for the architecture section
  analysis.json                              communities (size, folders, projects), god nodes (hubs), observed
                                             project-to-project edges, per-file blast radius (how many other files
                                             depend on code in each file), node/edge counts
--merge builds assessment/graphs/estate-graph.json with `graphify merge-graphs` for cross-repository questions
(`graphify query/path/explain/affected --graph assessment/graphs/estate-graph.json`).
Keys: OPENROUTER_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY from the environment only.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

from _common import OUT, load_config, load_state, mark, mark_step, read_json, run, utf8_stdout, write_json

KEY_VARS = ["OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
DEP_RELATIONS = {"calls", "references", "inherits", "implements", "imports", "reads_from", "indirect_call", "dispatches_to", "imports_from"}


def env_value(name):
    v = os.environ.get(name)
    if v or os.name != "nt":
        return v
    code, out = run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetEnvironmentVariable('{name}','User')"])
    return (out.strip() or None) if code == 0 else None


def label_env():
    for n in KEY_VARS:
        v = env_value(n)
        if not v:
            continue
        if n == "OPENROUTER_API_KEY":
            return {"OPENAI_API_KEY": v, "OPENAI_BASE_URL": "https://openrouter.ai/api/v1"}, "openai", n
        return {n: v}, {"OPENAI_API_KEY": "openai", "ANTHROPIC_API_KEY": "claude", "GEMINI_API_KEY": "gemini"}[n], n
    return None, None, None


def graph_dir(repo):
    return os.path.join(OUT, "graphs", repo)


def build(repo, src, force):
    out = graph_dir(repo)
    gj = os.path.join(out, "graphify-out", "graph.json")
    if os.path.exists(gj) and not force:
        return gj, "existing"
    os.makedirs(out, exist_ok=True)
    args = ["graphify", "extract", src, "--code-only", "--out", out] + (["--force"] if force else [])
    code, txt = run(args, timeout=7200)
    if code:
        print(f"WARN {repo}: graphify extract failed ({code}): {txt[-400:]}")
        return None, "failed"
    code, txt = run(["graphify", "cluster-only", out, "--no-label", "--no-viz"], timeout=3600)
    if code:
        print(f"WARN {repo}: graphify cluster-only failed: {txt[-300:]}")
    return (gj if os.path.exists(gj) else None), "built"


def label(repo):
    env, backend, name = label_env()
    if not env:
        print(f"{repo}: community naming skipped (no LLM key in the environment)")
        return
    code, txt = run(["graphify", "label", graph_dir(repo), f"--backend={backend}", "--missing-only", "--batch-size=4"], env=env, timeout=3600)
    fail = re.search(r"(?i)labeling failed \((.{0,160})", txt)
    print(f"{repo}: community naming {'FAILED: ' + fail.group(1) if fail or code else 'done'} (key from {name})")


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
                           "projects": [p for p, _ in v["projects"].most_common(3)]} for c, v in comm.items()), key=lambda x: -x["size"])
    impact = {f: len(s) for f, s in dependents.items()}
    return {"repo": repo, "graph": gj.replace("\\", "/"), "nodes": len(nodes), "edges": len(edges), "communities": communities[:60],
            "community_count": len(communities), "god_nodes": god,
            "project_edges": [{"from": a, "to": b, "count": n} for (a, b), n in proj_edges.most_common(200)],
            "file_impact": dict(sorted(impact.items(), key=lambda x: -x[1])[:2000])}


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
        if a.label:
            label(name)
        if a.exports:
            exports(name)
        if how != "existing" or a.force or a.label or not done or not os.path.exists(os.path.join(graph_dir(name), "analysis.json")):
            res = analyse(name, gj, inv)
            write_json(os.path.join(graph_dir(name), "analysis.json"), res)
            print(f"{name}: graph {res['nodes']:,} nodes / {res['edges']:,} edges, {res['community_count']} communities, "
                  f"top hub: {res['god_nodes'][0]['label'] if res['god_nodes'] else '-'} ({how})")
        mark(root, name, "graph")
    if a.merge and len(graphs) > 1:
        out = os.path.join(OUT, "graphs", "estate-graph.json")
        code, txt = run(["graphify", "merge-graphs"] + graphs + ["--out", out], timeout=3600)
        print(f"estate graph: {'ok -> ' + out if code == 0 else 'failed: ' + txt[-300:]}")
    mark_step(root, "graphs")


if __name__ == "__main__":
    main()
