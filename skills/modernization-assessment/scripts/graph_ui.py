"""Graph explorer: one offline page per repository to ask the code graph a developer's questions, plus a small local
server that adds free-text questions answered by graphify itself.

    py -X utf8 graph_ui.py --repo NAME            # (re)build assessment/graphs/<repo>/explorer.html and wiki-html/
    py -X utf8 graph_ui.py --serve [--port 8765]  # serve assessment/ on 127.0.0.1 and answer graphify questions

explorer.html (works from disk, no server, no internet):
  Blast radius   pick a class, method, file or external package: everything that depends on it, directly and up to N
                 steps away, grouped by project and file, with the deployables that must be retested
  Depends on     the reverse: what it needs (what must exist or be ported first)
  Path           shortest dependency chain between two things (calls, references, inheritance, SQL reads / writes)
  Hubs           the most depended-on classes and files: change them last and test them most
  Ask graphify   with --serve: graphify query / explain / path / affected run on the repository graph and the answer
                 is shown; without the server the exact command is shown to copy
Links at the top open graphify's own pages: graph.html, GRAPH_TREE.html, the call flows and the wiki (wiki-html/).
map_graphs.py calls build() after the exports. Read-only on the graph; the server binds to 127.0.0.1 only, runs only
graphify query / explain / path / affected with the arguments as a list (no shell), and serves files under assessment/.
"""
import argparse
import glob
import html
import http.server
import json
import os
import re
import sys
import urllib.parse

from _common import OUT, load_config, read_json, run, tool_exe, utf8_stdout

STRUCT = {"defines", "method", "case_of", "contains"}  # source contains target
DEP = ["calls", "references", "inherits", "implements", "imports", "dispatches_to", "indirect_call", "reads_from", "writes_to",
       "executes", "uses", "triggers", "registers", "resolves_to", "publishes", "handles"]


def graph_dir(repo):
    return os.path.join(OUT, "graphs", repo)


def compact(repo):
    """graph.json -> arrays small enough to embed: labels, files, lines, kinds, parents, dependency edges, projects."""
    gj = os.path.join(graph_dir(repo), "graphify-out", "graph.json")
    g = json.load(open(gj, encoding="utf-8"))
    nodes = g.get("nodes", [])
    idx = {n["id"]: i for i, n in enumerate(nodes)}
    files, fidx = [], {}
    lab, fil, line, kind, comm = [], [], [], [], []
    for n in nodes:
        f = (n.get("source_file") or "").replace("\\", "/")
        if f not in fidx:
            fidx[f] = len(files)
            files.append(f)
        lab.append(n.get("label") or n["id"])
        fil.append(fidx[f])
        m = re.match(r"L(\d+)", str(n.get("source_location") or ""))
        line.append(int(m.group(1)) if m else 0)
        kind.append(3 if n.get("file_type") == "concept" else 0 if n.get("_callable_class") else 1 if n.get("_callable") else 2 if f else 4)
        comm.append(n.get("community", -1) if isinstance(n.get("community"), int) else -1)
    parent = [-1] * len(nodes)
    rels, ridx, edges = [], {}, []
    for e in g.get("links") or g.get("edges") or []:
        s, t = idx.get(e.get("source")), idx.get(e.get("target"))
        if s is None or t is None or s == t:
            continue
        r = e.get("relation") or "references"
        if r in STRUCT:
            if parent[t] < 0:
                parent[t] = s
            continue
        if r not in ridx:
            ridx[r] = len(rels)
            rels.append(r)
        edges += [s, t, ridx[r]]
    inv = read_json(os.path.join(OUT, "inventory", f"{repo}.json"), {}) or {}
    mentions(inv.get("root"), files, fidx, lab, fil, line, kind, comm, parent, edges, rels, ridx)
    projects = sorted(({"name": p["name"], "dir": os.path.dirname(p["path"]).replace("\\", "/"), "deployable": bool(p.get("deployable")), "type": p.get("type", "")}
                       for p in inv.get("projects", [])), key=lambda p: -len(p["dir"]))
    names = {}
    for c in json.load(open(os.path.join(graph_dir(repo), "graphify-out", ".graphify_labels.json"), encoding="utf-8")).items() if os.path.exists(
            os.path.join(graph_dir(repo), "graphify-out", ".graphify_labels.json")) else []:
        names[str(c[0])] = c[1] if isinstance(c[1], str) else str(c[1])
    return {"repo": repo, "labels": lab, "files": files, "file": fil, "line": line, "kind": kind, "community": comm, "parent": parent,
            "rels": rels, "edges": edges, "projects": projects, "communities": names, "graph": os.path.relpath(gj).replace("\\", "/")}


SOURCE_EXT = (".cs", ".vb", ".aspx", ".ascx", ".master", ".cshtml", ".vbhtml", ".asax", ".ashx", ".asmx", ".svc")
GENERIC = {"Base", "Common", "Config", "Data", "Error", "Errors", "Helper", "Helpers", "Item", "Items", "List", "Manager", "Model", "Program",
           "Request", "Response", "Result", "Service", "Settings", "Startup", "Status", "Type", "Utils", "Value", "Values"}


def mentions(root, files, fidx, lab, fil, line, kind, comm, parent, edges, rels, ridx):
    """Fallback edges for what the graph misses (static calls through nested classes, markup, late binding): a file whose
    source names a class defined in another file 'mentions' it. Only class names that are unique in the repository and not
    generic words; the explorer labels these edges as text matches."""
    if not root or not os.path.isdir(root):
        return
    cls = {}
    for i, k in enumerate(kind):
        if k == 0 and files[fil[i]] and len(lab[i]) >= 4 and lab[i] not in GENERIC:
            cls.setdefault(lab[i], []).append(i)
    uniq = {n: v[0] for n, v in cls.items() if len(v) == 1}
    if not uniq:
        return
    rx = re.compile(r"\b(" + "|".join(sorted(map(re.escape, uniq), key=len, reverse=True)) + r")\b")
    top = {}  # file -> the one node that stands for it in mention edges (a file node: one edge per file and class)
    in_file = {}  # file -> its top-level classes, which depend on whatever their file mentions (so blast radius walks on)
    for i, k in enumerate(kind):
        if k == 0 and (parent[i] < 0 or kind[parent[i]] != 0):
            in_file.setdefault(fil[i], []).append(i)
    have = {(edges[j], edges[j + 1]) for j in range(0, len(edges), 3)}
    r = ridx.setdefault("mentions", len(rels))
    if r == len(rels):
        rels.append("mentions")
    rf = ridx.setdefault("in file", len(rels))
    if rf == len(rels):
        rels.append("in file")
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in ("bin", "obj", ".git", ".vs", "packages", "node_modules")]
        for f in fs:
            if not f.lower().endswith(SOURCE_EXT):
                continue
            rp = os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")
            try:
                text = open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            fi0 = fidx.get(rp)
            found = {m for m in rx.findall(text) if fi0 is None or fil[uniq[m]] != fi0}
            if not found:
                continue
            if rp not in fidx:
                fidx[rp] = len(files)
                files.append(rp)
            fi = fidx[rp]
            srcs = top.get(fi)
            if not srcs:
                srcs = [len(lab)]
                top[fi] = srcs
                lab.append(os.path.basename(rp))
                fil.append(fi)
                line.append(0)
                kind.append(2)
                comm.append(-1)
                parent.append(-1)
                for c in in_file.get(fi, []):
                    edges += [c, srcs[0], rf]
            for name in found:
                t = uniq[name]
                if fil[t] == fi:
                    continue
                for s in srcs:
                    if (s, t) not in have:
                        have.add((s, t))
                        edges += [s, t, r]


def wiki_html(repo):
    """wiki/*.md -> wiki-html/*.html (links rewritten), so the wiki opens in a browser."""
    from _mdhtml import page
    src = os.path.join(graph_dir(repo), "graphify-out", "wiki")
    if not os.path.isdir(src):
        return 0
    dst = os.path.join(graph_dir(repo), "graphify-out", "wiki-html")
    os.makedirs(dst, exist_ok=True)
    n = 0
    for p in glob.glob(os.path.join(src, "*.md")):
        md = open(p, encoding="utf-8", errors="ignore").read()
        out = re.sub(r'href="([^":#]+)\.md(#[^"]*)?"', lambda m: f'href="{m.group(1)}.html{m.group(2) or ""}"', page(md))
        with open(os.path.join(dst, os.path.splitext(os.path.basename(p))[0] + ".html"), "w", encoding="utf-8") as fh:
            fh.write(out)
        n += 1
    return n


def build(repo):
    d = compact(repo)
    n = wiki_html(repo)
    go = os.path.join(graph_dir(repo), "graphify-out")
    links = [(t, os.path.relpath(os.path.join(go, f), graph_dir(repo)).replace("\\", "/")) for t, f in (
        ("Interactive graph", "graph.html"), ("Code tree", "GRAPH_TREE.html"), ("Call flows", f"{repo}-callflow.html"),
        ("Wiki", "wiki-html/index.html"), ("Graph report", "GRAPH_REPORT.md")) if os.path.exists(os.path.join(go, f))]
    page = TEMPLATE.replace("__TITLE__", html.escape(f"{repo} code graph explorer")).replace(
        "__LINKS__", " ".join(f'<a href="{html.escape(h)}" target="_blank" rel="noopener">{html.escape(t)}</a>' for t, h in links)).replace(
        "__DATA__", json.dumps(d, separators=(",", ":")).replace("</", "<\\/"))
    p = os.path.join(graph_dir(repo), "explorer.html")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(page)
    return f"explorer {os.path.relpath(p)} ({len(page) // 1024} KB, {len(d['labels']):,} nodes, {len(d['edges']) // 3:,} dependency edges); wiki pages {n}"


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/ping"):
            return self._json({"ok": True, "graphify": bool(tool_exe("graphify"))})
        if self.path in ("/", "/index.html"):  # a start page: the report and each repository's explorer
            links = [(os.path.basename(p), p) for p in sorted(glob.glob(os.path.join("report", "*.html")))] + \
                    [(f"Code explorer: {p.split(os.sep)[1]}", p) for p in sorted(glob.glob(os.path.join("graphs", "*", "explorer.html")))]
            b = ("<!doctype html><meta charset='utf-8'><title>Assessment</title><body style='font:15px system-ui;margin:40px;line-height:1.8'><h1>Assessment</h1><ul>"
                 + "".join(f"<li><a href='/{urllib.parse.quote(p.replace(os.sep, '/'))}'>{html.escape(t)}</a></li>" for t, p in links) + "</ul></body>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/graphify"):
            return self.send_error(404)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0) or 0) or b"{}")
        except ValueError:
            return self.send_error(400)
        cmd, repo = body.get("cmd"), re.sub(r"[^\w.\-]", "", str(body.get("repo") or ""))
        a, b = str(body.get("a") or "")[:300], str(body.get("b") or "")[:300]
        gj = os.path.join(os.getcwd(), "graphs", repo, "graphify-out", "graph.json")
        if cmd not in ("query", "explain", "path", "affected") or not a or not os.path.isfile(gj):
            return self._json({"ok": False, "out": "unknown command, empty question or no graph for this repository"})
        args = [tool_exe("graphify") or "graphify", cmd, a] + ([b] if cmd == "path" and b else []) + ["--graph", gj]
        if cmd == "query":
            args += ["--budget", str(min(4000, int(body.get("budget") or 1500)))]
        if cmd == "affected":
            args += ["--depth", str(min(5, int(body.get("depth") or 2)))]
        code, out = run(args, timeout=300)
        return self._json({"ok": code == 0, "out": out[-20000:], "command": " ".join(args[1:])})

    def _json(self, obj):
        b = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def serve(port):
    os.chdir(OUT)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    pages = sorted(glob.glob(os.path.join("graphs", "*", "explorer.html")))
    print(f"serving {os.getcwd()} on http://127.0.0.1:{port}/ (Ctrl+C stops it)")
    for p in pages:
        print(f"  http://127.0.0.1:{port}/{urllib.parse.quote(p.replace(os.sep, '/'))}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    root, _ = load_config()
    os.chdir(root)
    if a.serve:
        return serve(a.port)
    repos = [a.repo] if a.repo else sorted(os.path.basename(os.path.dirname(os.path.dirname(p))) for p in glob.glob(os.path.join(OUT, "graphs", "*", "graphify-out", "graph.json")))
    if not repos:
        sys.exit("no code graph yet: run map_graphs.py first")
    for r in repos:
        print(f"{r}: {build(r)}")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light dark">
<title>__TITLE__</title>
<style>
:root{--bg:#fff;--fg:#1d2329;--muted:#5b6670;--line:#dfe3e7;--soft:#f4f6f8;--accent:#0b6e74;--hi:#b42318;--warn:#b54708;--ok:#067647;--code:#f2f4f6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14181c;--fg:#e4e8ec;--muted:#9aa5ae;--line:#2c343b;--soft:#1c2227;--accent:#5ccfcf;--hi:#f97066;--warn:#fdb022;--ok:#47cd89;--code:#1f262c}}
:root[data-theme=dark]{--bg:#14181c;--fg:#e4e8ec;--muted:#9aa5ae;--line:#2c343b;--soft:#1c2227;--accent:#5ccfcf;--hi:#f97066;--warn:#fdb022;--ok:#47cd89;--code:#1f262c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0}header .links a{margin-right:12px;color:var(--accent)}main{max-width:1240px;margin:0 auto;padding:16px}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:8px 0 16px;flex-wrap:wrap}.tabs button{background:none;border:0;border-bottom:2px solid transparent;padding:8px 12px;color:var(--muted);font:inherit;cursor:pointer}
.tabs button.on{color:var(--fg);border-color:var(--accent);font-weight:600}.pane{display:none}.pane.on{display:block}
input,select,button.b{font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 10px}button.b{cursor:pointer;background:var(--soft)}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0}.pick{position:relative;flex:1;min-width:260px}.pick input{width:100%}
.sugg{position:absolute;top:100%;left:0;right:0;background:var(--bg);border:1px solid var(--line);border-radius:6px;max-height:320px;overflow:auto;z-index:4;display:none}
.sugg div{padding:5px 10px;cursor:pointer;border-bottom:1px solid var(--soft)}.sugg div:hover,.sugg div.a{background:var(--soft)}.k{font-size:11px;color:var(--muted);margin-left:6px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:12px 0}.tile{border:1px solid var(--line);border-radius:8px;padding:10px}.tile .v{font-size:22px;font-weight:600}.tile .l{color:var(--muted);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}th{background:var(--soft);position:sticky;top:52px}
code,.mono{font:12px ui-monospace,SFMono-Regular,Consolas,monospace}.muted{color:var(--muted)}details{border:1px solid var(--line);border-radius:6px;margin:6px 0;padding:4px 10px}summary{cursor:pointer;font-weight:600}
.chain{display:flex;flex-direction:column;gap:2px;margin-top:10px}.chain .n{border:1px solid var(--line);border-radius:6px;padding:6px 10px}.chain .r{color:var(--muted);font-size:12px;padding-left:18px}
pre{background:var(--code);padding:12px;border-radius:6px;overflow:auto;white-space:pre-wrap}.tag{display:inline-block;border:1px solid var(--line);border-radius:10px;padding:0 8px;font-size:12px;margin-right:4px}
.hi{color:var(--hi);font-weight:600}.note{background:var(--soft);border-left:3px solid var(--accent);padding:8px 12px;border-radius:4px;margin:10px 0}
@media (max-width:640px){th{top:0}header{position:static}}
</style></head><body>
<header><h1>__TITLE__</h1><span class="links">__LINKS__</span><span style="flex:1"></span><button class="b" id="theme" title="Light or dark">Theme</button></header>
<main>
<p class="muted" id="stats"></p>
<div class="tabs" role="tablist"><button data-p="blast" class="on">Blast radius</button><button data-p="deps">Depends on</button><button data-p="path">Path</button><button data-p="hubs">Hubs</button><button data-p="ask">Ask graphify</button></div>
<section class="pane on" id="p-blast"><p>What breaks or must be retested if this changes: everything that calls, references, inherits or reads it, directly and up to the chosen number of steps away.</p>
 <div class="row"><div class="pick"><input id="b-q" placeholder="Class, method, file or package (type 2+ letters)" autocomplete="off"><div class="sugg"></div></div>
 <label>Steps <select id="b-d"><option>1</option><option selected>2</option><option>3</option><option>4</option><option value="9">all</option></select></label></div><div id="b-out"></div></section>
<section class="pane" id="p-deps"><p>What this needs: the code, packages and database objects it uses. Everything here must exist (or be ported) before it can move.</p>
 <div class="row"><div class="pick"><input id="d-q" placeholder="Class, method or file" autocomplete="off"><div class="sugg"></div></div>
 <label>Steps <select id="d-d"><option>1</option><option selected>2</option><option>3</option><option value="9">all</option></select></label></div><div id="d-out"></div></section>
<section class="pane" id="p-path"><p>How does A reach B? The shortest chain of calls, references, inheritance and SQL reads / writes.</p>
 <div class="row"><div class="pick"><input id="pa-q" placeholder="From" autocomplete="off"><div class="sugg"></div></div><div class="pick"><input id="pb-q" placeholder="To" autocomplete="off"><div class="sugg"></div></div><button class="b" id="p-go">Find path</button></div><div id="p-out"></div></section>
<section class="pane" id="p-hubs"><p>The most depended-on classes and files. Changes here have the widest blast radius: port them early behind tests, change their behaviour last.</p><div id="h-out"></div></section>
<section class="pane" id="p-ask"><p>Free-text questions about the code, answered by graphify on this repository's graph.</p>
 <div class="row"><select id="a-c"><option value="query">Question (query)</option><option value="explain">Explain a class or method</option><option value="affected">What is affected by</option><option value="path">Path from A to B</option></select>
 <input id="a-q" style="flex:1;min-width:260px" placeholder="e.g. where are supplier requests sent"><input id="a-b" style="display:none;min-width:200px" placeholder="To (for path)"><button class="b" id="a-go">Ask</button></div>
 <div id="a-out"></div></section>
</main>
<script type="application/json" id="g">__DATA__</script>
<script>
const G = JSON.parse(document.getElementById('g').textContent);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const N = G.labels.length, KIND = ['class','method','member','concept','external'];
const out = Array.from({length:N}, () => []), inn = Array.from({length:N}, () => []), kids = Array.from({length:N}, () => []);
for (let i = 0; i < G.edges.length; i += 3) { out[G.edges[i]].push([G.edges[i+1], G.edges[i+2]]); inn[G.edges[i+1]].push([G.edges[i], G.edges[i+2]]); }
G.parent.forEach((p, i) => { if (p >= 0) kids[p].push(i); });
const file = i => G.files[G.file[i]] || '';
const where = i => file(i) ? file(i) + (G.line[i] ? ':' + G.line[i] : '') : '(outside the repository)';
const proj = f => { if (!f) return null; const p = G.projects.find(p => !p.dir || f.startsWith(p.dir + '/')); return p || null; };
const owner = i => { let x = i, n = 0; while (x >= 0 && G.kind[x] !== 0 && G.parent[x] >= 0 && n++ < 8) x = G.parent[x]; return G.kind[x] === 0 ? x : i; };
const name = i => { const o = owner(i); return o !== i && G.kind[i] === 1 ? G.labels[o] + G.labels[i] : G.labels[i]; };
document.getElementById('stats').textContent = `${N.toLocaleString()} nodes · ${(G.edges.length/3).toLocaleString()} dependency edges · ${G.files.filter(Boolean).length.toLocaleString()} files · ${G.projects.length} projects · graph ${G.graph}`;
// search index: classes first, then methods, files, externals
const files = G.files.map((f, i) => [f, i]).filter(x => x[0]);
function search(q) { q = q.toLowerCase(); if (q.length < 2) return []; const r = [];
  for (let i = 0; i < N && r.length < 400; i++) if (G.labels[i].toLowerCase().includes(q)) r.push({t:'n', i, s:(G.kind[i]===0?0:G.kind[i]===4?2:1) + (G.labels[i].toLowerCase()===q?-1:0)});
  for (const [f, fi] of files) if (f.toLowerCase().includes(q) && r.length < 450) r.push({t:'f', f, fi, s:1.5});
  return r.sort((a,b) => a.s - b.s).slice(0, 40); }
function picker(inp, onPick) { const box = inp.nextElementSibling; let items = [], act = -1;
  const draw = () => { box.innerHTML = items.map((x, j) => `<div data-j="${j}" class="${j===act?'a':''}">${x.t==='f' ? '<b>' + esc(x.f) + '</b><span class="k">file</span>' : esc(name(x.i)) + `<span class="k">${KIND[G.kind[x.i]]} · ${esc(where(x.i))}</span>`}</div>`).join(''); box.style.display = items.length ? 'block' : 'none'; };
  inp.oninput = () => { items = search(inp.value.trim()); act = -1; draw(); };
  inp.onkeydown = e => { if (e.key === 'ArrowDown') { act = Math.min(items.length-1, act+1); draw(); e.preventDefault(); } else if (e.key === 'ArrowUp') { act = Math.max(0, act-1); draw(); e.preventDefault(); }
    else if (e.key === 'Enter' && items.length) { choose(items[Math.max(0, act)]); e.preventDefault(); } else if (e.key === 'Escape') { box.style.display = 'none'; } };
  box.onmousedown = e => { const d = e.target.closest('div[data-j]'); if (d) { e.preventDefault(); choose(items[+d.dataset.j]); } };
  inp.onblur = () => setTimeout(() => box.style.display = 'none', 150);
  function choose(x) { box.style.display = 'none'; inp.value = x.t === 'f' ? x.f : name(x.i); inp.dataset.sel = JSON.stringify(x); onPick && onPick(x); } }
const seeds = x => { if (x.t === 'f') { const s = []; for (let i = 0; i < N; i++) if (G.file[i] === x.fi) s.push(i); return s; }
  const s = [x.i], st = [x.i]; while (st.length) { const v = st.pop(); for (const k of kids[v]) { s.push(k); st.push(k); } } return s; };
function walk(x, depth, adj) { const start = new Set(seeds(x)); const dist = new Map(); let front = [...start]; start.forEach(i => dist.set(i, 0));
  for (let d = 1; d <= depth && front.length; d++) { const nx = []; for (const v of front) for (const [w, r] of adj[v]) if (!dist.has(w)) { dist.set(w, d); nx.push(w); } front = nx; }
  for (const i of start) dist.delete(i); return dist; }
function report(x, depth, adj, host, verb) {
  const dist = walk(x, depth, adj); const by = new Map(); const ext = [];
  for (const [i, d] of dist) { const f = file(i); if (!f) { ext.push([i, d]); continue; } const p = proj(f); const pk = p ? p.name : '(no project)';
    if (!by.has(pk)) by.set(pk, {p, files: new Map()}); const F = by.get(pk).files; if (!F.has(f)) F.set(f, []); F.get(f).push([i, d]); }
  const fcount = [...by.values()].reduce((a, b) => a + b.files.size, 0); const classes = new Set([...dist.keys()].map(owner).filter(i => G.kind[i] === 0 && file(i)));
  const dep = [...by.values()].filter(b => b.p && b.p.deployable).map(b => b.p.name);
  host.innerHTML = `<div class="tiles"><div class="tile"><div class="v">${dist.size}</div><div class="l">code elements ${verb}</div></div><div class="tile"><div class="v">${classes.size}</div><div class="l">classes</div></div>
   <div class="tile"><div class="v">${fcount}</div><div class="l">files</div></div><div class="tile"><div class="v">${by.size}</div><div class="l">projects</div></div><div class="tile"><div class="v">${dep.length}</div><div class="l">deployables to retest</div></div></div>
   ${dep.length ? `<p><b>Deployables:</b> ${dep.map(d => `<span class="tag">${esc(d)}</span>`).join('')}</p>` : ''}
   ${[...by.entries()].sort((a,b) => b[1].files.size - a[1].files.size).map(([pk, b]) => `<details ${by.size < 4 ? 'open' : ''}><summary>${esc(pk)} <span class="muted">${b.p && b.p.deployable ? 'deployable · ' : ''}${b.files.size} file(s)</span></summary>
     <table><thead><tr><th>File</th><th>What</th><th>Steps</th></tr></thead><tbody>${[...b.files.entries()].sort((a,b)=>Math.min(...a[1].map(x=>x[1]))-Math.min(...b[1].map(x=>x[1]))).map(([f, xs]) => {
       const top = xs.sort((a,b)=>a[1]-b[1]).slice(0, 8); return `<tr><td class="mono">${esc(f)}</td><td>${top.map(([i]) => esc(name(i)) + (G.line[i] ? `<span class="k">L${G.line[i]}</span>` : '')).join(', ')}${xs.length > 8 ? ` <span class="muted">+${xs.length-8} more</span>` : ''}</td><td>${Math.min(...xs.map(x=>x[1]))}</td></tr>`; }).join('')}</tbody></table></details>`).join('')}
   ${ext.length ? `<details><summary>Outside the repository (${ext.length}): framework and package types</summary><p>${ext.slice(0, 200).map(([i]) => `<span class="tag">${esc(G.labels[i])}</span>`).join('')}</p></details>` : ''}
   ${!dist.size ? '<p class="note">Nothing found in the graph. Classes reached only by reflection, configuration, DI by name or other repositories do not show here.</p>' : ''}`; }
let bSel = null, dSel = null;
picker(document.getElementById('b-q'), x => { bSel = x; report(x, +document.getElementById('b-d').value, inn, document.getElementById('b-out'), 'depend on it'); });
document.getElementById('b-d').onchange = () => bSel && report(bSel, +document.getElementById('b-d').value, inn, document.getElementById('b-out'), 'depend on it');
picker(document.getElementById('d-q'), x => { dSel = x; report(x, +document.getElementById('d-d').value, out, document.getElementById('d-out'), 'it uses'); });
document.getElementById('d-d').onchange = () => dSel && report(dSel, +document.getElementById('d-d').value, out, document.getElementById('d-out'), 'it uses');
picker(document.getElementById('pa-q')); picker(document.getElementById('pb-q'));
document.getElementById('p-go').onclick = () => { const A = JSON.parse(document.getElementById('pa-q').dataset.sel || 'null'), B = JSON.parse(document.getElementById('pb-q').dataset.sel || 'null'); const h = document.getElementById('p-out');
  if (!A || !B) { h.innerHTML = '<p class="note">Pick both ends from the suggestions.</p>'; return; }
  const src = seeds(A), dst = new Set(seeds(B));
  const bfs = und => { const prev = new Map(); const q = [...src]; src.forEach(s => prev.set(s, null));
    while (q.length) { const v = q.shift(); if (dst.has(v)) { const chain = []; let c = v; while (c !== null) { chain.unshift(c); c = prev.get(c) === null ? null : prev.get(c)[0]; } return {chain, prev}; }
      const nb = und ? out[v].map(e => [e[0], e[1], 1]).concat(inn[v].map(e => [e[0], e[1], -1])) : out[v].map(e => [e[0], e[1], 1]);
      for (const [w, r, dir] of nb) if (!prev.has(w)) { prev.set(w, [v, r, dir]); q.push(w); } } return null; };
  let res = bfs(false), und = false; if (!res) { res = bfs(true); und = true; }
  if (!res) { h.innerHTML = '<p class="note">No connection in the graph.</p>'; return; }
  h.innerHTML = (und ? '<p class="note">No one-way dependency chain from A to B; this is the shortest connection in either direction (arrows show the real direction).</p>' : '') +
    '<div class="chain">' + res.chain.map((i, j) => { const p = res.prev.get(i); return (j && p ? `<div class="r">${p[2] < 0 ? '↑ the next line ' + esc(G.rels[p[1]]) + ' this one (reverse direction)' : '↓ ' + esc(G.rels[p[1]])}</div>` : '') + `<div class="n"><b>${esc(name(i))}</b> <span class="k">${KIND[G.kind[i]]} · ${esc(where(i))}</span></div>`; }).join('') + '</div>'; };
(function hubs() { const cls = new Map(), fl = new Map();
  for (let i = 0; i < N; i++) { const f = file(i); if (!f) continue; const o = owner(i); for (const [w] of inn[i]) { const wf = file(w); if (!wf || wf === f) continue;
    if (G.kind[o] === 0) { if (!cls.has(o)) cls.set(o, new Set()); cls.get(o).add(wf); } if (!fl.has(f)) fl.set(f, new Set()); fl.get(f).add(wf); } }
  const top = (m, n) => [...m.entries()].sort((a,b) => b[1].size - a[1].size).slice(0, n);
  document.getElementById('h-out').innerHTML = `<h3>Classes used from the most other files</h3><table><thead><tr><th>Class</th><th>Where</th><th>Used from files</th><th>Project</th></tr></thead><tbody>${top(cls, 30).map(([i, s]) => { const p = proj(file(i));
    return `<tr><td><b>${esc(G.labels[i])}</b></td><td class="mono">${esc(where(i))}</td><td>${s.size}</td><td>${esc(p ? p.name : '')}</td></tr>`; }).join('')}</tbody></table>
    <h3>Files used from the most other files</h3><table><thead><tr><th>File</th><th>Used from files</th><th>Project</th></tr></thead><tbody>${top(fl, 30).map(([f, s]) => { const p = proj(f); return `<tr><td class="mono">${esc(f)}</td><td>${s.size}</td><td>${esc(p ? p.name : '')}</td></tr>`; }).join('')}</tbody></table>`; })();
// Ask graphify: the local server (graph_ui.py --serve) runs graphify; opened from disk, show the command to copy
let server = false; fetch('/api/ping').then(r => r.json()).then(j => { server = !!(j && j.ok); }).catch(() => {});
const ac = document.getElementById('a-c'); ac.onchange = () => { document.getElementById('a-b').style.display = ac.value === 'path' ? '' : 'none'; };
document.getElementById('a-go').onclick = async () => { const cmd = ac.value, a = document.getElementById('a-q').value.trim(), b = document.getElementById('a-b').value.trim(), h = document.getElementById('a-out');
  if (!a) return; const q = s => '"' + s.replace(/"/g, '\\"') + '"';
  const line = `graphify ${cmd} ${q(a)}${cmd === 'path' && b ? ' ' + q(b) : ''} --graph ${G.graph}${cmd === 'query' ? ' --budget 1500' : ''}`;
  if (!server) { h.innerHTML = `<p class="note">Opened from disk, so this page cannot run graphify. Run <code>py -X utf8 &lt;skill&gt;/scripts/graph_ui.py --serve</code> in the workspace and open the page from the address it prints, or run this from the workspace folder:</p><pre>${esc(line)}</pre>`; return; }
  h.innerHTML = '<p class="muted">Asking graphify…</p>';
  try { const r = await fetch('/api/graphify', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({cmd, a, b, repo: G.repo})}); const j = await r.json();
    h.innerHTML = `<p class="muted mono">${esc(j.command || line)}</p><pre>${esc(j.out || '(no answer)')}</pre>`; } catch (e) { h.innerHTML = `<p class="note">The server did not answer: ${esc(e)}</p>`; } };
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => { document.querySelectorAll('.tabs button').forEach(x => x.classList.toggle('on', x === b)); document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === 'p-' + b.dataset.p)); });
document.getElementById('theme').onclick = () => { const r = document.documentElement; const cur = r.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); r.dataset.theme = cur === 'dark' ? 'light' : 'dark'; };
const h0 = new URLSearchParams(location.hash.slice(1)); if (h0.get('q')) { const i = document.getElementById('b-q'); i.value = h0.get('q'); i.oninput(); }
</script></body></html>
"""


if __name__ == "__main__":
    main()
