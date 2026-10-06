"""Method map: every method / function with its declaration (parameters, return type), callers and callees.

Part of the generic-graph adapter (runs after graph_reference.py). Writes into docs/reference/:
  methods.md            one section per project (nearest folder with a project manifest), one row per method:
                        declaration read from the source line graphify reports, "calls" and "called by" at method level
  methods-<project>.md  instead, when the estate has more methods than adapter_options.generic-graph.methods_split
                        (default 2000): methods.md becomes the index and each project gets its own page
and docs/agent/methods.json (compact, for tools and the flow viewer):
  {"<anchor>": {"name", "file", "line", "decl", "params": [...], "returns", "calls": [anchor...], "callers": [anchor...],
                "via": {anchor: "di registration" | "override" | "message" | ...}}}   (via: only calls bound at run time,
  from csharp_resolve.py; trace_flow.py prints them on each hop)

Calls come from graphify: EXTRACTED edges are shown plainly, INFERRED ones in italics (resolved by name, verify in code).
Declarations are parsed from the source text, so they work for any language with name(...) declarations
(C#, VB, Java, Kotlin, TypeScript / JavaScript, Python, Go, PHP, Swift, Rust); when parsing fails the first line is shown.
"""
import json
import os
import re
from collections import defaultdict

from graph_reference import CFG, DOCS, GRAPH, OPT, OUT, SKIP_PATH, esc, line_of, norm, slug
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

SRC_ROOT = os.environ.get("DOCS_SOURCE_ROOT") or CFG.get("source_root", ".")
SPLIT = OPT.get("methods_split", 2000)
MAX_LINKS = OPT.get("max_call_links", 12)
CALLS = {"calls", "indirect_call", "dispatches_to"}
PLAIN = {"local variable", "only implementation"}  # "partial class field" keeps its label: the field is in another file   # resolver edges that are ordinary static calls: no "via" label
MANIFEST = re.compile(r"\.(csproj|vbproj|fsproj)$|^(package\.json|pyproject\.toml|setup\.py|pom\.xml|build\.gradle(\.kts)?|go\.mod|Cargo\.toml|composer\.json)$", re.I)
MODIFIERS = {"public", "private", "protected", "internal", "static", "async", "virtual", "override", "abstract", "sealed",
             "extern", "unsafe", "new", "partial", "final", "synchronized", "readonly", "export", "default", "declare",
             "shared", "overridable", "overrides", "mustoverride", "notoverridable", "friend", "overloads", "function",
             "sub", "def", "func", "fun", "fn", "pub", "open", "suspend", "inline", "operator", "native", "transient",
             "volatile", "strictfp", "get", "set", "required", "const", "mutating", "nonmutating", "iterator"}
_lines = {}


def source_lines(path):
    if path not in _lines:
        rel = norm(path)
        cands = [os.path.join(SRC_ROOT, rel), path, rel]
        _lines[path] = None
        for c in cands:
            if os.path.isfile(c):
                try:
                    _lines[path] = open(c, encoding="utf-8-sig", errors="replace").read().splitlines()
                except OSError:
                    pass
                break
    return _lines[path]


def split_top(s, sep=","):
    out, depth, cur, quote = [], 0, [], None
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def match_paren(s, i):
    depth = 0
    for k in range(i, len(s)):
        if s[k] == "(":
            depth += 1
        elif s[k] == ")":
            depth -= 1
            if depth == 0:
                return k
    return -1


MODS = r"(?:public|private|protected|internal|static|async|override|virtual|sealed|new|abstract|extern|unsafe|partial|final|synchronized|Public|Private|Protected|Friend|Shared|Overrides|Overridable|Overloads|Async|MustOverride|NotOverridable)"


def overload_lines(path, name):
    """Lines of every declaration of `name` in the file (C# / VB / Java). The code graph keeps one node per name, so overloads
    share one entry: its calls, callers and reach are the union of all of them, which the pages must say."""
    if os.path.splitext(path)[1].lower() not in (".cs", ".vb", ".java"):
        return []
    short = name.split(".")[-1]
    rx = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:" + MODS + r"\s+)+(?:[\w<>\[\],.?() ]*?\s+)?(?:Sub\s+|Function\s+)?"
                    + re.escape(short) + r"\s*(?:<[^>()]*>|\(Of[^)]*\))?\s*\(")
    return [k for k, ln in enumerate(source_lines(path) or [], 1) if short in ln and rx.search(ln)]


def parse_decl(n, name):
    """(decl, params, returns) from the declaration at the node's source line, or None."""
    lines = source_lines(n.get("source_file") or "")
    ln = line_of(n)
    if not lines or not ln or ln > len(lines):
        return None
    ext = os.path.splitext(n["source_file"])[1].lower()
    vb, py, go = ext == ".vb", ext == ".py", ext == ".go"
    chunk = []
    for raw in lines[ln - 1:ln + 14]:
        t = raw.rstrip()
        if vb:
            t = re.sub(r"\s'.*$", "", t)
            cont = t.endswith(" _")
            chunk.append(t[:-2] if cont else t)
            if not cont:
                break
            continue
        t = re.sub(r"\s//.*$", "", t) if not py else re.sub(r"\s#.*$", "", t)
        chunk.append(t)
        if re.search(r"[{;]|=>|:\s*$", t) and "(" in " ".join(chunk) and match_paren(" ".join(chunk), " ".join(chunk).index("(")) > 0:
            break
    s = re.sub(r"\s+", " ", " ".join(chunk)).strip()
    s = re.sub(r"^(?:\[[^\]]*\]\s*)+", "", s)                       # C# attributes
    s = re.sub(r"^(?:@[\w.]+(?:\([^)]*\))?\s*)+", "", s)            # Java / TS / Python decorators
    s = re.sub(r"^(?:<[^>]*>\s*)+", "", s) if vb else s            # VB attributes
    # the parameter list is the "(" right after the name (tuple return types and Go receivers come earlier)
    m = re.search(r"(?<![\w.])" + re.escape(name) + r"\s*(?:<[^()]*>)?\s*(?:=\s*(?:async\s*)?)?\(", s)
    i = m.end() - 1 if m else s.find("(")
    if i < 0:
        return None
    j = match_paren(s, i)
    if j < 0:
        return None
    prefix, inner, after = s[:i].strip(), s[i + 1:j], s[j + 1:]
    if not m:
        return None
    params = [p for p in split_top(inner) if p]
    if py:
        params = [p for p in params if p not in ("self", "cls")]
    body = re.split(r"\{|=>|;|\bwhere\b(?=[^()]*$)", after, maxsplit=1)[0]
    if py:
        body = body.rsplit(":", 1)[0] if body.rstrip().endswith(":") else body
    body = body.strip()
    returns = ""
    if vb:
        m = re.match(r"(?i)As\s+(.+)", body)
        returns = m.group(1).strip() if m else ""
    elif body.startswith("->"):
        returns = body[2:].strip()
    elif body.startswith(":") and not py:
        returns = body[1:].strip()
    elif go:
        returns = body
    elif "=" not in prefix:
        toks = [t for t in (prefix[: prefix.rfind(name)] if name in prefix else "").split() if t.lower() not in MODIFIERS]
        returns = " ".join(toks)
    decl = (prefix + "(" + ", ".join(params) + ")" + ("" if not body else body if body.startswith(":") else " " + body)).strip()
    return decl[:220], params, returns


def first_line(n):
    lines = source_lines(n.get("source_file") or "")
    ln = line_of(n)
    return (lines[ln - 1].strip()[:160] if lines and ln and ln <= len(lines) else "")


def project_of(path, cache={}):
    """Nearest folder (relative to the source root) holding a project manifest; else the top folder."""
    rel = norm(path)
    d = os.path.dirname(rel)
    probe = d
    while True:
        if probe not in cache:
            full = os.path.join(SRC_ROOT, probe) if probe else SRC_ROOT
            try:
                cache[probe] = any(MANIFEST.search(f) for f in os.listdir(full))
            except OSError:
                cache[probe] = False
        if cache[probe]:
            return probe or "."
        if not probe:
            break
        probe = os.path.dirname(probe)
    return rel.split("/")[0] if "/" in rel else "."


def main():
    if not os.path.exists(GRAPH):
        raise SystemExit(f"method-reference: {GRAPH} not found — run code_graph.py build first")
    g = json.load(open(GRAPH, encoding="utf-8"))
    nodes = {n["id"]: n for n in g["nodes"] if n.get("source_file") and n.get("file_type", "code") == "code"
             and not SKIP_PATH.search(norm(n.get("source_file")))}
    owner = {e["target"]: e["source"] for e in g["links"] if e.get("relation") == "method" and e["source"] in nodes and e["target"] in nodes}
    methods = {i: n for i, n in nodes.items() if i in owner or (n.get("_callable") and not n.get("_callable_class"))}
    if not methods:
        print("methods: none found in graph.json")
        return

    def clean(label):
        return re.sub(r"\(\)$", "", str(label or "")).lstrip(".")

    def cls_name(i):
        return clean(nodes[owner[i]].get("label")) if i in owner else ""

    aid, used = {}, set()
    for i in sorted(methods, key=lambda i: (norm(nodes[i]["source_file"]), line_of(nodes[i]) or 0)):
        n = nodes[i]
        # short, readable anchors: owner (class, else file name) + method; overloads and clashes get the line number
        a = slug("mth", cls_name(i) or os.path.splitext(os.path.basename(n["source_file"]))[0], clean(n.get("label")))
        if a in used:
            a = f"{a}-l{line_of(n) or len(used)}"
        used.add(a)
        aid[i] = a
    out_e, in_e = defaultdict(dict), defaultdict(dict)   # i -> {j: inferred?}
    ctor_calls = defaultdict(set)                          # method -> classes it instantiates / calls statically
    via = defaultdict(dict)                                # i -> {j: how the call is bound at run time}
    for e in g["links"]:
        s, t, r = e["source"], e["target"], e.get("relation")
        if r not in CALLS or s not in methods or s == t:
            continue
        inferred = e.get("confidence", "EXTRACTED") != "EXTRACTED"
        if t in methods:
            out_e[s][t] = out_e[s].get(t, True) and inferred
            in_e[t][s] = in_e[t].get(s, True) and inferred
            if e.get("_origin") == "csharp-resolve" and e.get("context") and e["context"] not in PLAIN:
                via[s][t] = e["context"]
        elif t in nodes and nodes[t].get("_callable_class"):
            ctor_calls[s].add(t)

    proj = {i: project_of(nodes[i]["source_file"]) for i in methods}
    groups = defaultdict(list)
    for i in methods:
        groups[proj[i]].append(i)
    split = len(methods) > SPLIT
    page_of_group = {gname: (f"methods-{slug(gname) or 'root'}.md" if split else "methods.md") for gname in groups}
    page = {i: page_of_group[proj[i]] for i in methods}

    info = {}
    for i, n in methods.items():
        name = clean(n.get("label"))
        parsed = parse_decl(n, name)
        decl, params, returns = parsed if parsed else (first_line(n), None, "")
        info[i] = {"name": (cls_name(i) + "." if cls_name(i) else "") + name, "file": norm(n["source_file"]),
                   "line": line_of(n), "decl": decl, "params": params, "returns": returns}
        ov = overload_lines(n["source_file"], name)
        if len(ov) > 1:
            info[i]["overloads"] = ov

    def link(j, here, inferred=False, how=""):
        target = "" if page[j] == here else page[j]
        s = f"[{esc(info[j]['name'])}]({target}#{aid[j]})"
        return (f"*{s}*" if inferred else s) + (f" ({esc(how)})" if how else "")

    def links(edges, here, hows=None):
        items = sorted(edges.items(), key=lambda kv: (kv[1], info[kv[0]]["name"]))
        s = ", ".join(link(j, here, inf, (hows or {}).get(j, "")) for j, inf in items[:MAX_LINKS])
        return s + (f" +{len(items) - MAX_LINKS} more" if len(items) > MAX_LINKS else "") or "—"

    legend = ("Declarations are read from the source line graphify reports. *Italic* calls were resolved by name "
              "(INFERRED edges): check them in the code. A call followed by (di registration), (override), (message), "
              "(event) … is bound at run time: that is the method that actually runs, found by the C# resolver "
              "(see dependency-injection.md). Overloads of one method share one entry (the graph keys methods by name), so their "
              "calls and callers are merged; the declaration column lists the overloads' lines.")
    pages = defaultdict(list)
    for gname in sorted(groups):
        here = page_of_group[gname]
        ids = sorted(groups[gname], key=lambda i: (info[i]["file"], line_of(nodes[i]) or 0))
        by_owner = defaultdict(list)
        for i in ids:
            by_owner[(info[i]["file"], cls_name(i))].append(i)
        body = [f'<a id="{slug("prjm", gname)}"></a>', "", f"## {gname}", "", "[↑ Back to index](#index)", ""]
        for (f, c), mids in by_owner.items():
            body += [f"### {c or os.path.basename(f)}", "", f"File: `{f}`", "",
                     "| Method | Declaration | Calls | Called by |", "| --- | --- | --- | --- |"]
            for i in mids:
                x = info[i]
                calls = links(out_e[i], here, via[i])
                if ctor_calls[i]:
                    calls = (calls if calls != "—" else "") + ("; " if calls != "—" else "") + "creates " + ", ".join(
                        f"`{esc(clean(nodes[t].get('label')))}`" for t in sorted(ctor_calls[i])[:6])
                body.append(f'| <a id="{aid[i]}"></a>**{esc(x["name"])}** (`{esc(f)}:{x["line"] or "?"}`) | '
                            f'`{esc(x["decl"])}`'
                            + (f' · {len(x["overloads"])} overloads (lines {", ".join(map(str, x["overloads"]))}) share this entry: '
                               f'calls and callers are merged' if x.get("overloads") else "") + f' | {calls} | '
                            f'{links(in_e[i], here)} |')
            body.append("")
        pages[here] += body

    os.makedirs(OUT, exist_ok=True)
    total_calls = sum(len(v) for v in out_e.values())
    head = ["# Method map", "", f"Every method and function with its declaration, what it calls and what calls it "
            f"({len(methods):,} methods, {total_calls:,} method-to-method calls). {legend}", "", '<a id="index"></a>', "",
            "| Project | Methods | Page |", "| --- | ---: | --- |"]
    for gname in sorted(groups):
        p = page_of_group[gname]
        head.append(f"| [{esc(gname)}]({'' if p == 'methods.md' else p}#{slug('prjm', gname)}) | {len(groups[gname])} | {p} |")
    if split:
        open(os.path.join(OUT, "methods.md"), "w", encoding="utf-8", newline="\n").write("\n".join(head) + "\n")
        for p, body in pages.items():
            gname = next(k for k, v in page_of_group.items() if v == p)
            text = [f"# Methods: {gname}", "", legend, "", '<a id="index"></a>', "", "[All projects](methods.md)", ""] + body
            open(os.path.join(OUT, p), "w", encoding="utf-8", newline="\n").write("\n".join(text) + "\n")
    else:
        open(os.path.join(OUT, "methods.md"), "w", encoding="utf-8", newline="\n").write("\n".join(head + [""] + pages["methods.md"]) + "\n")

    agent = os.path.join(DOCS, "agent")
    os.makedirs(agent, exist_ok=True)
    data = {aid[i]: dict(info[i], page=page[i], calls=[aid[j] for j in out_e[i]], callers=[aid[j] for j in in_e[i]],
                         **({"via": {aid[j]: k for j, k in via[i].items()}} if via[i] else {}))
            for i in methods}
    open(os.path.join(agent, "methods.json"), "w", encoding="utf-8", newline="\n").write(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    parsed = sum(1 for x in info.values() if x["params"] is not None)
    stat("methods", methods=len(methods), calls=total_calls)
    print(f"methods: {len(methods)} in {len(groups)} projects, {parsed} declarations parsed, {total_calls} calls"
          + (f", split into {len(pages)} pages" if split else ""))


if __name__ == "__main__":
    main()
