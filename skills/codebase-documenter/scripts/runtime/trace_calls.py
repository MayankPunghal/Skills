"""Call trees from the documentation's method map: what a method calls, who calls it, and what starts it.

Usage (run from the folder Claude Code / your editor is opened in, so printed paths are clickable):
  python docs/_tools/trace_calls.py OrderService.Submit            # callees, 4 levels deep
  python docs/_tools/trace_calls.py OrderService.Submit --up       # callers ("what breaks if I change this?")
  python docs/_tools/trace_calls.py OrderService.Submit --entry    # entry points that reach it ("how does a user get here?")
  python docs/_tools/trace_calls.py Submit --depth 2 --max 60

Each line: name(parameters)  path:line. "↺" marks a method already shown above. A hop bound at run time shows how:
"[di registration]", "[override]", "[message]", "[event]", "[method group]", "[background job]", "[redirect]" ...
Calls include graphify's INFERRED (name-resolved) edges: verify in the code before stating them as fact.
--entry lists every endpoint, UI event or job that reaches the method, one call path each, and the buttons / links /
scripts that call those endpoints. Paths are under the source root when it is found (see lookup.py), else relative to
the repository root. Built for coding agents: plain text, bounded in size. The skill's trace_flow.py uses the same code
and adds --draft (a business-flow spec to edit).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))  # <root>/docs/_tools/trace_calls.py -> <root>


def load(agent_dir):
    p = os.path.join(agent_dir, "methods.json")
    if not os.path.exists(p):
        sys.exit(f"{p} not found: the method map is written by the generic-graph adapter (build_site.py)")
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


def hop(m, a, b):
    """How the call a -> b is bound at run time ("" for a plain call)."""
    return (m[a].get("via") or {}).get(b, "")


def tree(m, root, depth, up, limit, where=lambda f, ln: f"{f}:{ln}"):
    lines, seen = [], set()

    def walk(a, d, prefix, how=""):
        if len(lines) >= limit:
            return
        x = m[a]
        mark = " ↺" if a in seen else ""
        lines.append(f"{prefix}{f'[{how}] ' if how else ''}{x['name']}{params(x)}  {where(x['file'], x['line'])}{mark}")
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


def entries(agent_dir, m, target, where=lambda f, ln: f"{f}:{ln}"):
    """Entry points (endpoints, UI events, jobs) that reach `target`, each with one shortest call path and its UI triggers."""
    p = os.path.join(agent_dir, "entry-points.json")
    if not os.path.exists(p):
        sys.exit(f"{p} not found: entry points are written by the generic-trace adapter (build_site.py)")
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
        return [f"{m[target]['name']}: no entry point reaches it in the static call graph (dead code, reflection / run-time "
                "dispatch, or a missing edge; for C# check reference/dependency-injection.md)"]
    lines = [f"{m[target]['name']} is reached from {len(out)} entry point(s):"]
    for _, e, path in sorted(out, key=lambda t: t[0]):
        lines.append(f"  {e['kind']}: {e['label']}  ({where(e['file'], e['line'])})")
        lines.append(f"    {path}")
        for u in data["ui"]:
            if u.get("handler") == e["handler"] and u.get("endpoint"):
                lines.append(f"    UI: \"{u['label']}\" ({u['element']}, {u['event']})  {where(u['file'], u['line'])}")
    return lines


def pick(m, name):
    """The method for `name`, after printing the alternatives when the name is ambiguous."""
    hits = find(m, name)
    if not hits:
        sys.exit(f"no method matches {name!r} (try Class.Method, or lookup.py {name} --kind method)")
    if len(hits) > 1 and m[hits[0]]["name"].lower() != name.lower():
        print("several matches, using the first; qualify as Class.Method to pick another:")
        for h in hits[:10]:
            print(f"  {m[h]['name']}  {m[h]['file']}:{m[h]['line']}")
    return hits[0]


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name")
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--up", action="store_true", help="callers instead of callees")
    ap.add_argument("--entry", action="store_true", help="entry points that reach the method")
    ap.add_argument("--max", type=int, default=120)
    ap.add_argument("--src", help="source root (see lookup.py)")
    a = ap.parse_args()
    sys.path.insert(0, HERE)
    import lookup  # same folder: one source-root search and one path style for both tools
    src = lookup.find_source_root(a.src)

    def where(f, ln):
        return f"{lookup.rel(os.path.join(src, f)) if src else f}:{ln}"
    agent = os.path.join(BASE, "docs", "agent")
    m = load(agent)
    root = pick(m, a.name)
    print("\n".join(entries(agent, m, root, where) if a.entry else tree(m, root, a.depth, a.up, a.max, where)))


if __name__ == "__main__":
    main()
