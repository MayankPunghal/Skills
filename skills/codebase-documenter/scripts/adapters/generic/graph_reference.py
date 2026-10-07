"""Stack-agnostic reference pages built from graphify's graph.json (any language graphify parses).

Writes into docs/reference/:
  components.md   every class/type (anchor cls-…) and free function (fn-…): file:line, members, calls into, called by,
                  inherits/implements, fixed values a C# class sets (constructors, initializers, constants) — grouped by
                  folder, with an index table
  modules.md      every source file (mod-…): what it defines, which files it calls / is called by
  communities.md  every graphify community (com-…): name, size, main folders, main members

Run by pipeline.py (cwd = workspace root). Paths in the pages are relative to the source root.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

CFG = json.load(open("codebase-docs.json", encoding="utf-8"))
DOCS = CFG.get("docs_dir", "docs")
OUT = os.path.join(DOCS, "reference")
SRC = CFG.get("source_root", ".").replace("\\", "/").strip("/")
GRAPH = os.path.join(CFG.get("graph_dir", "graphify-out"), "graph.json")
OPT = CFG.get("adapter_options", {}).get("generic-graph", {})
MAX_MEMBERS = OPT.get("max_members", 40)
SKIP_PATH = re.compile(OPT.get("skip_regex", r"(^|/)(bin|obj|node_modules|dist|build|vendor|packages|__pycache__)/|\.min\.js$|\.designer\.cs$"), re.I)
BACK = "[↑ Back to index](#index)"
CALLS = {"calls", "indirect_call", "dispatches_to"}
INHERIT = {"inherits", "implements"}


def slug(*parts):
    return re.sub(r"[^a-z0-9]+", "-", "-".join(str(p) for p in parts).lower()).strip("-")


_PREFIXES = {SRC}
if os.path.isabs(CFG.get("source_root", ".")):
    try:
        _PREFIXES.add(os.path.relpath(CFG["source_root"], os.getcwd()).replace("\\", "/"))
    except ValueError:
        pass
_PREFIXES = sorted((x.strip("/") for x in _PREFIXES if x and x not in (".",)), key=len, reverse=True)


def norm(path):
    """Path relative to the source root, whichever folder graphify was run from."""
    p = (path or "").replace("\\", "/")
    for pre in _PREFIXES:
        if p.startswith(pre + "/"):
            return p[len(pre) + 1:]
        if pre.count("/") and p.startswith(pre.split("/")[-2] + "/" + pre.split("/")[-1] + "/"):
            return p.split("/", 2)[2]
    return p


def line_of(n):
    m = re.match(r"L(\d+)", str(n.get("source_location") or ""))
    return int(m.group(1)) if m else None


def esc(s):
    return str(s).replace("|", "\\|")


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from code_text import block_close, code_only  # noqa: E402

MAX_DEFAULTS = OPT.get("max_defaults", 8)
_CODE = {}
# a value worth showing: a number, true / false, or a call on numbers (AddDays(21), TimeSpan.FromMinutes(30)); string values are
# never shown (they may be secrets), nor objects (new X()) or nulls
SHOWN_VALUE = re.compile(r"\d|\btrue\b|\bfalse\b", re.I)


def _code(f):
    if f not in _CODE:
        try:
            raw = open(os.path.join(CFG.get("source_root", "."), f), encoding="utf-8-sig", errors="replace").read()
            _CODE[f] = (raw, code_only(raw))
        except OSError:
            _CODE[f] = ("", "")
    return _CODE[f]


def defaults_of(name, f, ln):
    """Fixed values a C# class sets ["Member = value (:line)"]: assignments in its constructors, property / field initializers
    and constants with number or true/false values. Business rules such as a 21-day trial or a 30-minute timeout often live
    only there, out of reach of the method map (graphify has no constructor nodes)."""
    if not f.endswith(".cs") or not ln:
        return []
    raw, code = _code(f)
    if not code:
        return []
    starts = [0] + [k + 1 for k, ch in enumerate(code) if ch == "\n"]
    head = re.compile(r"\b(?:class|struct|record)\s+" + re.escape(name) + r"\b[^{;]*\{")
    m = head.search(code, starts[min(ln, len(starts)) - 1] if ln <= len(starts) else 0) or head.search(code)
    if not m:
        return []
    o = m.end() - 1
    c = block_close(code, o)
    body = code[o + 1:c]
    # blank nested types: their members are not this class's
    for nm in list(re.finditer(r"\b(?:class|struct|record|interface|enum)\s+\w+[^{;]*\{", body)):
        e = block_close(body, nm.end() - 1)
        body = body[:nm.start()] + re.sub(r"[^\n]", " ", body[nm.start():e + 1]) + body[e + 1:]
    out = []

    def keep(member, s, e, at):
        val = re.sub(r"\s+", " ", raw[o + 1 + s:o + 1 + e]).strip()
        if '"' in val or "'" in val or not SHOWN_VALUE.search(val) or re.match(r"new\b(?!\s*(?:DateTime|DateTimeOffset|TimeSpan)\s*\()", val) or len(val) > 70:
            return
        line = code.count("\n", 0, o + 1 + at) + 1
        item = f"{member} = {val} (:{line})"
        if item not in out:
            out.append(item)
    for cm in re.finditer(r"(?:^|[;{}\]\s])(?:(?:public|protected|internal|private|static)\s+)*" + re.escape(name)
                          + r"\s*\([^)]*\)\s*(?::\s*(?:base|this)\s*\([^)]*\)\s*)?\{", body):
        cb, ce = cm.end() - 1, block_close(body, cm.end() - 1)
        for am in re.finditer(r"(?:^|[;{}\s])(?:this\.)?([A-Za-z_]\w*)\s*=(?![=>])\s*([^;{}]+);", body[cb + 1:ce]):
            keep(am.group(1), cb + 1 + am.start(2), cb + 1 + am.end(2), cb + 1 + am.start(1))
    for pm in re.finditer(r"\b([A-Za-z_]\w*)\s*\{\s*(?:(?:public|protected|internal|private)\s+)?get;\s*(?:(?:public|protected|internal|private|init)\s+)?(?:set;|init;)?\s*\}\s*=\s*([^;]+);", body):
        keep(pm.group(1), pm.start(2), pm.end(2), pm.start(1))
    for km in re.finditer(r"\bconst\s+[\w.<>?]+\s+([A-Za-z_]\w*)\s*=\s*([^;]+);", body):
        keep(km.group(1), km.start(2), km.end(2), km.start(1))
    return out[:MAX_DEFAULTS]


def main():
    if not os.path.exists(GRAPH):
        sys.exit(f"graph-reference: {GRAPH} not found — run graph.py build first")
    g = json.load(open(GRAPH, encoding="utf-8"))
    nodes = {n["id"]: n for n in g["nodes"] if n.get("source_file") and n.get("file_type", "code") == "code"
             and not SKIP_PATH.search(norm(n.get("source_file")))}
    owner = {}           # method id -> class id
    members = defaultdict(list)
    for e in g["links"]:
        if e.get("relation") == "method" and e["source"] in nodes and e["target"] in nodes:
            owner[e["target"]] = e["source"]
            members[e["source"]].append(e["target"])
    classes = {i: n for i, n in nodes.items() if n.get("_callable_class")}
    funcs = {i: n for i, n in nodes.items() if n.get("_callable") and not n.get("_callable_class") and i not in owner}

    def unit(i):  # the documented unit a node belongs to (class for methods)
        return owner.get(i, i)
    calls_out, calls_in, inherits = defaultdict(Counter), defaultdict(Counter), defaultdict(set)
    file_out, file_in = defaultdict(Counter), defaultdict(Counter)
    for e in g["links"]:
        s, t, r = e["source"], e["target"], e.get("relation")
        if s not in nodes or t not in nodes:
            continue
        if r in CALLS and e.get("confidence", "EXTRACTED") == "EXTRACTED":
            us, ut = unit(s), unit(t)
            if us != ut:
                calls_out[us][ut] += 1
                calls_in[ut][us] += 1
            fs, ft = norm(nodes[s]["source_file"]), norm(nodes[t]["source_file"])
            if fs != ft:
                file_out[fs][ft] += 1
                file_in[ft][fs] += 1
        elif r in INHERIT:
            inherits[unit(s)].add((r, t))

    aid = {}
    for i, n in list(classes.items()) + list(funcs.items()):
        f = norm(n["source_file"])
        aid[i] = slug("cls" if i in classes else "fn", f, n.get("label", ""))

    def clean(label):  # graphify labels functions "name()" and methods ".name()"
        return re.sub(r"\(\)$", "", str(label or "")).lstrip(".")

    for n in nodes.values():
        n["label"] = clean(n.get("label"))

    def link(i):
        n = nodes.get(i)
        if not n or i not in aid:
            return esc(n.get("label", i)) if n else esc(i)
        return f"[{esc(n.get('label'))}](#{aid[i]})"

    def folder(i):
        f = norm(nodes[i]["source_file"])
        return "/".join(f.split("/")[:-1][:3]) or "."

    units = sorted(list(classes) + list(funcs), key=lambda i: (folder(i), norm(nodes[i]["source_file"]), nodes[i].get("label", "")))
    by_folder = defaultdict(list)
    for i in units:
        by_folder[folder(i)].append(i)
    os.makedirs(OUT, exist_ok=True)

    # ---------------- components.md
    out = ["# Code components", "",
           "Every class / type and free function found by graphify in the source tree, generated from `graph.json` "
           "(EXTRACTED call edges only). Click a name in the index to jump to its entry; each entry links its callers and callees. "
           "**Sets** lists the fixed values a C# class assigns in its constructors, property initializers and constants (numbers, "
           "true / false and calls on them such as `AddDays(21)`; text values are never shown).", "",
           f"Total: {len(classes):,} classes / types, {len(funcs):,} functions.", "", '<a id="index"></a>', "",
           "| Folder | Classes | Functions |", "| --- | ---: | ---: |"]
    for fo, ids in by_folder.items():
        out.append(f"| [{esc(fo)}](#{slug('area', fo)}) | {sum(1 for i in ids if i in classes)} | {sum(1 for i in ids if i in funcs)} |")
    n_defaults = 0
    for fo, ids in by_folder.items():
        out += ["", f'<a id="{slug("area", fo)}"></a>', "", f"## {fo}", "", BACK, "",
                "| Name | Kind | File | Members | Calls into | Called by |", "| --- | --- | --- | --- | --- | --- |"]
        for i in ids:
            n = nodes[i]
            f = norm(n["source_file"])
            ln = line_of(n)
            mem = [nodes[m].get("label") for m in members.get(i, []) if m in nodes]
            mem_s = ", ".join(f"`{esc(x)}`" for x in sorted(set(mem))[:MAX_MEMBERS]) + (f" +{len(set(mem)) - MAX_MEMBERS}" if len(set(mem)) > MAX_MEMBERS else "")
            inh = ", ".join(f"{r} {link(t)}" for r, t in sorted(inherits.get(i, [])))
            co = ", ".join(link(t) for t, _ in calls_out[i].most_common(12)) + (" …" if len(calls_out[i]) > 12 else "")
            ci = ", ".join(link(t) for t, _ in calls_in[i].most_common(12)) + (" …" if len(calls_in[i]) > 12 else "")
            kind = "class" if i in classes else "function"
            dflt = defaults_of(n.get("label", ""), f, ln) if i in classes else []
            if dflt:
                n_defaults += 1
                # first in the cell: the agent index keeps only the start of a long row
                mem_s = "Sets: " + ", ".join(f"`{esc(x.rsplit(' (', 1)[0])}` ({x.rsplit(' (', 1)[1]}" for x in dflt) + ("<br>" + mem_s if mem_s else "")
            out.append(f'| <a id="{aid[i]}"></a>**{esc(n.get("label"))}**{" (" + inh + ")" if inh else ""} | {kind} | '
                       f'`{esc(f)}`{":" + str(ln) if ln else ""} | {mem_s} | {co} | {ci} |')
    open(os.path.join(OUT, "components.md"), "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")

    # ---------------- modules.md
    files = defaultdict(list)
    for i in units:
        files[norm(nodes[i]["source_file"])].append(i)
    out = ["# Source files", "", "Every source file that defines at least one class or function, with the files it calls and is called by "
           "(from graph.json call edges).", "", f"Total: {len(files):,} files.", "", '<a id="index"></a>', "",
           "| File | Defines | Calls into (files) | Called by (files) |", "| --- | --- | ---: | ---: |"]
    for f in sorted(files):
        out.append(f"| [`{esc(f)}`](#{slug('mod', f)}) | {len(files[f])} | {len(file_out[f])} | {len(file_in[f])} |")
    for f in sorted(files):
        out += ["", f'<a id="{slug("mod", f)}"></a>', "", f"### {f}", "", f"File: `{f}` · {BACK}", "",
                "- Defines: " + ", ".join(link(i) for i in files[f]),
                "- Calls into: " + (", ".join(f"[`{esc(t)}`](#{slug('mod', t)})" for t, _ in file_out[f].most_common(15)) or "—"),
                "- Called by: " + (", ".join(f"[`{esc(t)}`](#{slug('mod', t)})" for t, _ in file_in[f].most_common(15)) or "—")]
    open(os.path.join(OUT, "modules.md"), "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")

    # ---------------- communities.md
    labels = {}
    lp = os.path.join(CFG.get("graph_dir", "graphify-out"), ".graphify_labels.json")
    if os.path.exists(lp):
        labels = json.load(open(lp, encoding="utf-8"))
    sp = os.path.join(CFG.get("graph_dir", "graphify-out"), "community-summaries.json")
    sums = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    comm = defaultdict(list)
    for i in units:
        c = nodes[i].get("community")
        if c is not None:
            comm[c].append(i)
    out = ["# Code communities", "", "Clusters of tightly connected code found by graphify (community detection). Useful to see which "
           "classes form one feature or subsystem. Names and summaries come from community_names.py (heuristic, or an LLM "
           "when one was used). The Types column counts classes, records, interfaces and free functions; the summary's member count also includes "
           "methods and files.", "", '<a id="index"></a>', "", "| Community | Types | Summary | Main folders |", "| --- | ---: | --- | --- |"]
    ordered = sorted(comm.items(), key=lambda kv: -len(kv[1]))
    for c, ids in ordered:
        name = labels.get(str(c)) or nodes[ids[0]].get("community_name") or f"Community {c}"
        dirs = Counter(folder(i) for i in ids)
        summ = esc((sums.get(str(c)) or {}).get("summary", ""))
        out.append(f"| [{esc(name)}](#{slug('com', c)}) | {len(ids)} | {summ} | {', '.join('`' + esc(d) + '`' for d, _ in dirs.most_common(3))} |")
    for c, ids in ordered:
        name = labels.get(str(c)) or nodes[ids[0]].get("community_name") or f"Community {c}"
        hubs = sorted(ids, key=lambda i: -(len(calls_in[i]) + len(calls_out[i])))[:25]
        s = sums.get(str(c)) or {}
        out += ["", f'<a id="{slug("com", c)}"></a>', "", f"## {name}", "", f"Community id {c} · {len(ids)} types · {BACK}", ""]
        if s.get("summary"):
            out += [s["summary"] + (f" Distinguishing terms: {', '.join(s.get('terms', [])[:6])}." if s.get("terms") else ""), ""]
        out += ["Main members (most connected first): " + ", ".join(link(i) for i in hubs)]
    open(os.path.join(OUT, "communities.md"), "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    stat("graph", classes=len(classes), functions=len(funcs), files=len(files), communities=len(comm), classes_with_defaults=n_defaults)
    print(f"graph-reference: {len(classes)} classes, {len(funcs)} functions, {len(files)} files, {len(comm)} communities")


if __name__ == "__main__":
    main()
