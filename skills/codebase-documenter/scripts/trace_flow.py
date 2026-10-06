"""Call trees from the method map, to write business flows without opening every file.

    python <skill>/scripts/trace_flow.py <Class.Method | Method> [--depth 4] [--up] [--max 120]
    python <skill>/scripts/trace_flow.py <Class.Method> --draft <flow-id> [--depth 3]
    python <skill>/scripts/trace_flow.py <Class.Method> --entry

Prints the callees (or with --up the callers) of a method as an indented tree: name, file:line, parameters.
--entry answers "what starts this?": every endpoint, UI event or job that reaches the method, one call path each,
and the buttons / links / scripts that call those endpoints (needs the generic-trace adapter's entry-points.json).
"↺" marks a method already shown above. Calls include graphify's INFERRED (name-resolved) edges: verify in code.
A hop bound at run time shows how: "[di registration]", "[di decorator]", "[override]", "[message]", "[event]",
"[method group]", "[stored delegate]", "[background job]", "[redirect]", "[filter]" … (C#, from csharp_resolve.py).
--draft writes docs/_src/workflows/flows/<flow-id>.flow.json: one step per method in call order, lane = project,
step text = method name. Rewrite the texts in business language, merge or drop technical steps, add decisions,
data and external steps, then run build_site.py (reference/flows.md has the format).
Needs docs/agent/methods.json (written by the generic-graph adapter: build_site.py --no-site).
"""
import argparse
import json
import os
import re
import sys

from _common import load_config, utf8_stdout


def load(cfg):
    p = os.path.join(cfg["docs_dir"], "agent", "methods.json")
    if not os.path.exists(p):
        sys.exit(f"{p} not found: run build_site.py --no-site with the generic-graph adapter first")
    return json.load(open(p, encoding="utf-8"))


def find(m, name):
    n = name.lower()
    exact = [a for a, x in m.items() if x["name"].lower() == n]
    if exact:
        return exact
    return sorted((a for a, x in m.items() if x["name"].lower().endswith("." + n) or x["name"].lower().endswith(n)),
                  key=lambda a: len(m[a]["name"]))


def params(x):
    return "(" + ", ".join(x["params"]) + ")" if x.get("params") is not None else ""


def tree(m, root, depth, up, limit):
    lines, seen = [], set()

    def walk(a, d, prefix, how=""):
        if len(lines) >= limit:
            return
        x = m[a]
        mark = " ↺" if a in seen else ""
        lines.append(f"{prefix}{f'[{how}] ' if how else ''}{x['name']}{params(x)}  {x['file']}:{x['line']}{mark}")
        if a in seen or d >= depth:
            return
        seen.add(a)
        for b in (x["callers"] if up else x["calls"]):
            if b in m:
                walk(b, d + 1, prefix + "  ", hop(m, b, a) if up else hop(m, a, b))
    walk(root, 0, "")
    if len(lines) >= limit:
        lines.append(f"... truncated at {limit} lines (use --depth or --max)")
    return lines


def hop(m, a, b):
    """How the call a -> b is bound at run time ("" for a plain call)."""
    return (m[a].get("via") or {}).get(b, "")


def entries(cfg, m, target):
    """Entry points (endpoints, UI events, jobs) that reach `target`, each with one shortest call path and its UI triggers."""
    p = os.path.join(cfg["docs_dir"], "agent", "entry-points.json")
    if not os.path.exists(p):
        sys.exit(f"{p} not found: run build_site.py --no-site with the generic-trace adapter first")
    data = json.load(open(p, encoding="utf-8"))
    out = []
    for e in data["entries"]:
        prev, frontier = {e["handler"]: None}, [e["handler"]]
        while frontier and target not in prev:
            nxt = []
            for a in frontier:
                for b in (m.get(a) or {}).get("calls", []):
                    if b not in prev and b in m:
                        prev[b] = a
                        nxt.append(b)
            frontier = nxt
        if target in prev:
            path, a = [], target
            while a:
                p = prev[a]
                how = hop(m, p, a) if p else ""
                path.append((f"[{how}] " if how else "") + m[a]["name"])
                a = p
            out.append((len(path), e, " → ".join(reversed(path))))
    if not out:
        return [f"{m[target]['name']}: no entry point reaches it in the static call graph (dead code, reflection / run-time dispatch, or a missing edge; for C# check reference/dependency-injection.md)"]
    lines = [f"{m[target]['name']} is reached from {len(out)} entry point(s):"]
    for _, e, path in sorted(out, key=lambda t: t[0]):
        lines.append(f"  {e['kind']}: {e['label']}  ({e['file']}:{e['line']})")
        lines.append(f"    {path}")
        for u in data["ui"]:
            if u.get("handler") == e["handler"] and u.get("endpoint"):
                lines.append(f"    UI: \"{u['label']}\" ({u['element']}, {u['event']})  {u['file']}:{u['line']}")
    return lines


def lane_of(x):
    parts = x["file"].split("/")
    proj = next((p for p in parts[:-1] if "." in p or p not in ("src", "source", "app", "apps", "lib", "libs", "packages", "services")), parts[0])
    return proj.split(".")[-1] if proj.count(".") > 1 else proj


def draft(cfg, m, root, depth, flow_id):
    order, seen = [], set()

    def walk(a, d):
        if a in seen or d > depth:
            return
        seen.add(a)
        order.append(a)
        for b in m[a]["calls"]:
            if b in m:
                walk(b, d + 1)
    walk(root, 0)
    steps = [{"id": f"s{k + 1}", "lane": lane_of(m[a]), "text": m[a]["name"].split(".")[-1],
              "ref": "mth:" + m[a]["name"]} for k, a in enumerate(order)]
    lanes = list(dict.fromkeys(s["lane"] for s in steps))
    spec = {"id": flow_id, "title": "TODO: business name of the flow", "module": "", "summary": "TODO",
            "trigger": "TODO: who or what starts it", "outcome": "TODO: what is true when it ends",
            "lanes": lanes, "steps": steps, "notes": []}
    out = os.path.join(cfg["docs_dir"], "_src", "workflows", "flows", f"{flow_id}.flow.json")
    if os.path.exists(out):
        sys.exit(f"{out} exists; not overwriting (delete it or pick another id)")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8", newline="\n").write(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out}: {len(steps)} steps in {len(lanes)} lanes. Rewrite the TODOs and step texts in business language.")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--up", action="store_true")
    ap.add_argument("--max", type=int, default=120)
    ap.add_argument("--draft")
    ap.add_argument("--entry", action="store_true")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    m = load(cfg)
    hits = find(m, a.name)
    if not hits:
        sys.exit(f"no method matches {a.name!r} (try Class.Method, or lookup.py {a.name} --kind method)")
    if len(hits) > 1 and m[hits[0]]["name"].lower() != a.name.lower():
        print("several matches, using the first; qualify as Class.Method to pick another:")
        for h in hits[:10]:
            print(f"  {m[h]['name']}  {m[h]['file']}:{m[h]['line']}")
    if a.draft:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", a.draft):
            sys.exit("flow id: lower-case letters, digits and dashes")
        draft(cfg, m, hits[0], a.depth, a.draft)
        return
    if a.entry:
        print("\n".join(entries(cfg, m, hits[0])))
        return
    print("\n".join(tree(m, hits[0], a.depth, a.up, a.max)))


if __name__ == "__main__":
    main()
