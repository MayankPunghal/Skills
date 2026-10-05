"""Retrieval cards: the whole documentation as self-contained chunks, ready to embed in a local RAG index.

Writes docs/agent/cards.jsonl, one JSON object per line:
  {"id", "kind", "title", "breadcrumb", "text", "keys", "doc", "source", "related"}
  id          stable anchor (method / endpoint / table ... anchor, or page#section-part)
  text        what to embed: a context line (project · kind · name) followed by everything known about the item,
              joined from all reference exports, so one card answers "what is X, where is it, what calls it,
              what does it touch, what starts it" without other chunks
  keys        identifiers and their word splits (OrderWorkflow.ShipAsync -> order workflow ship async), for keyword search
  doc         page#anchor in the docs site; source: file:line in the code
  related     ids of linked cards (calls, callers, tables, endpoints ...) for one-hop expansion at query time

Entity cards come from docs/agent/*.json (methods, endpoints, db, db-access, errors, entry-points, dependencies)
and the flow specs; reference entities with no export (config keys, seed rows, classes, views ...) get a card from
entities.jsonl. Narrative pages are split at headings, then at paragraph / table-row boundaries above MAX_CHARS
with one block of overlap; code fences and tables are never cut mid-block, Mermaid source is dropped (captions stay).
Deterministic, no models, standard library only. Run after gen_agent_index.py:  python docs/_tools/gen_rag_cards.py
"""
import json
import os
import re
from collections import defaultdict

CFG = json.load(open("codebase-docs.json", encoding="utf-8")) if os.path.exists("codebase-docs.json") else {}
DOCS = CFG.get("docs_dir", "docs")
AGENT = os.path.join(DOCS, "agent")
PRODUCT = CFG.get("product") or CFG.get("code_name") or "Project"
MAX_CHARS = CFG.get("rag_card_max_chars", 2400)   # ~600 tokens: inside every small embedder's window
LIST_CAP = 12
SKIP_DIRS = {"_src", "_notes", "_tools", "agent", "assets", "reference"}
# pages and entity kinds that only add noise to retrieval (indexes of anchors, graph clusters)
SKIP_PAGES = set(CFG.get("rag_skip_pages", ["appendices/coverage.md"]))
SKIP_KINDS = {"community", "page", "section", "method", "endpoint", "error", "ui-trigger", "entry-point", "project", "package", "db-access"}
FRONT = re.compile(r"\A---\n.*?\n---\n", re.S)


def load(name, default=None):
    p = os.path.join(AGENT, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def words(s):
    """Identifier → lower-case words: OrderWorkflow.ShipAsync → order workflow ship async; usp_GetOrders → usp get orders."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s))
    return " ".join(w for w in re.split(r"[^A-Za-z0-9]+", s.lower()) if w)


def keys(*names):
    out = []
    for n in names:
        if not n:
            continue
        n = str(n)
        out += [n, words(n)] + [p.strip() for p in re.split(r"[./\\:]", n) if p.strip() and p != n]
    return list(dict.fromkeys(k for k in out if k))


def cap(items, n=LIST_CAP):
    items = [i for i in items if i]
    return ", ".join(items[:n]) + (f" (+{len(items) - n} more)" if len(items) > n else "")


def plain(md):
    md = re.sub(r"<a id=\"[^\"]*\"></a>", "", md)
    md = re.sub(r"<[^>]+>", "", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = md.replace("[↑ Back to index]", "")
    return md


CARDS = []


def card(id_, kind, title, lines, doc="", source="", related=(), key_names=(), breadcrumb=""):
    body = "\n".join(l for l in lines if l)
    text = f"{PRODUCT} · {kind} · {title}\n{body}".strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS - 40].rsplit("\n", 1)[0] + f"\n(truncated; full detail: {doc})"
    CARDS.append({"id": id_, "kind": kind, "title": title, "breadcrumb": breadcrumb or f"{kind} › {title}", "text": text,
                  "keys": keys(title, *key_names), "doc": doc, "source": source, "related": list(dict.fromkeys(r for r in related if r))[:40]})


def main():
    M = load("methods.json", {})
    EPS = load("endpoints.json", [])
    DB = load("db.json", {"routines": [], "tables": []})
    DBA = load("db-access.json", {})
    ERRS = load("errors.json", [])
    TR = load("entry-points.json", {"entries": [], "ui": []})
    DEPS = load("dependencies.json", {"projects": []})
    name = lambda a: (M.get(a) or {}).get("name", "")
    ref = "reference/"

    # indexes joining the exports
    db_of_method, sites_of_obj = defaultdict(list), defaultdict(list)
    for obj, sites in DBA.items():
        for s in sites:
            if s.get("tech") in ("view text", "mention"):
                continue
            sites_of_obj[obj.lower()].append(s)
            if s.get("anchor"):
                db_of_method[s["anchor"]].append(f"{obj} {s['op']} ({s['tech']}{', via ' + s['via'] if s.get('via') else ''})")
    err_of_method = defaultdict(list)
    for e in ERRS:
        if e.get("method"):
            err_of_method[e["method"]].append(e)
    ep_by_anchor = {e["anchor"]: e for e in EPS}
    ui_by_ep, ui_by_handler = defaultdict(list), defaultdict(list)
    for u in TR["ui"]:
        if u.get("endpoint"):
            ui_by_ep[u["endpoint"]].append(u)
        if u.get("handler"):
            ui_by_handler[u["handler"]].append(u)
    entry_by_handler, writers_of, err_entries = defaultdict(list), defaultdict(set), defaultdict(set)
    touches = {r["name"].lower(): r.get("touches", []) for r in DB.get("routines", [])}
    for e in TR["entries"]:
        entry_by_handler[e["handler"]].append(e)
        for obj, op, _ in e.get("db", []):
            if op not in ("read", "call"):
                writers_of[obj.lower()].add(f"{e['label']} ({op})")
                for t in touches.get(obj.lower(), []):
                    writers_of[t.lower()].add(f"{e['label']} (via {obj})")
        for x in e.get("errors", []):
            err_entries[x["anchor"]].add(e["label"])
    ui_txt = lambda u: f"\"{u['label']}\" {u['element']} ({u['event']}) on {u['file']}:{u['line']}"

    for a, x in M.items():
        own = entry_by_handler.get(a, [])
        card(a, "method", x["name"], [
            f"Defined in {x['file']}:{x['line']}",
            f"Declaration: {x['decl']}" if x.get("decl") else "",
            f"Parameters: {'; '.join(x['params'])}" if x.get("params") else "Parameters: none" if x.get("params") == [] else "",
            f"Returns: {x['returns']}" if x.get("returns") else "",
            f"Calls: {cap([name(b) for b in x.get('calls', [])])}" if x.get("calls") else "Calls: no other documented method",
            f"Called by: {cap([name(b) for b in x.get('callers', [])])}" if x.get("callers") else "Called by: nothing in the code (entry point, framework callback, or dead code)",
            f"Entry point itself: {cap([e['kind'] + ' ' + e['label'] for e in own])}" if own else "",
            f"Started by: {cap(x.get('entry_points', []))}" if x.get("entry_points") else "",
            f"UI that triggers it: {cap([ui_txt(u) for u in ui_by_handler.get(a, [])], 6)}" if ui_by_handler.get(a) else "",
            f"Database access in this method: {cap(db_of_method[a])}" if db_of_method.get(a) else "",
            f"Errors raised here: {cap([repr(e['message']) for e in err_of_method[a]], 6)}" if err_of_method.get(a) else "",
            f"Part of workflows: {', '.join(x['flows'])}" if x.get("flows") else "",
        ], doc=f"{ref}{x.get('page', 'methods.md')}#{a}", source=f"{x['file']}:{x['line']}",
            related=x.get("calls", [])[:15] + x.get("callers", [])[:15], key_names=(x["file"].rsplit("/", 1)[-1],))

    for e in EPS:
        ent = next((t for t in entry_by_handler.get(e.get("handler"), []) if t["kind"] == "endpoint" and t["label"] == f"{e['verb']} {e['route']}"), None)
        card(e["anchor"], "endpoint", f"{e['verb']} {e['route']}", [
            f"Framework: {e.get('framework', '')}; declared in {e['file']}:{e['line']}",
            f"Handler: {name(e['handler'])}" if e.get("handler") else (f"Inline handler registered in {name(e['registered_in'])}" if e.get("registered_in") else "Inline handler"),
            f"Parameters: {'; '.join(e['params'])}" if e.get("params") else "",
            f"Authorization: {e['auth']}" if e.get("auth") else "Authorization: none declared on the endpoint",
            f"Note: {e['note']}" if e.get("note") else "",
            f"Called from the UI: {cap([ui_txt(u) for u in ui_by_ep.get(e['anchor'], [])], 8)}" if ui_by_ep.get(e["anchor"]) else "Called from the UI: no static caller found",
            f"Reaches {ent['reaches']} methods; database: {cap([f'{o} {op} ({t})' for o, op, t in ent['db']])}" if ent and ent.get("db") else "",
            f"Errors it can return: {cap([repr(x['message']) for x in ent['errors']], 6)}" if ent and ent.get("errors") else "",
            f"Workflows: {', '.join(ent['flows'])}" if ent and ent.get("flows") else "",
        ], doc=f"{ref}endpoints.md#{e['anchor']}", source=f"{e['file']}:{e['line']}",
            related=[e.get("handler") or e.get("registered_in")] + [u["id"] for u in ui_by_ep.get(e["anchor"], [])], key_names=(e["route"], name(e.get("handler"))))

    for u in TR["ui"]:
        ep = ep_by_anchor.get(u.get("endpoint"))
        ent = next(iter(entry_by_handler.get(u.get("handler"), [])), None)
        card(u["id"], "ui-trigger", f"{u['label']} ({u['element']}, {u['event']})", [
            f"Screen file: {u['file']}:{u['line']}",
            f"Calls endpoint: {ep['verb']} {ep['route']}" if ep else f"Target: {u.get('target') or 'unknown'}",
            f"Handler method: {name(u['handler'])}" if u.get("handler") else "Handler: not resolved statically",
            f"Note: {u['note']}" if u.get("note") else "",
            f"Database reached: {cap([f'{o} {op} ({t})' for o, op, t in ent['db']])}" if ent and ent.get("db") else "",
            f"Errors the user can see: {cap([repr(x['message']) for x in ent['errors']], 6)}" if ent and ent.get("errors") else "",
        ], doc=f"{ref}ui-map.md#{u['id']}", source=f"{u['file']}:{u['line']}", related=[u.get("endpoint"), u.get("handler")],
            key_names=(u["file"].rsplit("/", 1)[-1], u.get("target")))

    for e in TR["entries"]:
        if e["kind"] == "endpoint":
            continue  # the endpoint card carries it
        card(e["id"], "entry-point", f"{e['kind']}: {e['label']}", [
            f"Handler: {name(e['handler'])} at {e['file']}:{e['line']}", f"Reaches {e['reaches']} methods",
            f"Database: {cap([f'{o} {op} ({t})' for o, op, t in e['db']])}" if e.get("db") else "",
            f"Errors: {cap([repr(x['message']) for x in e['errors']], 6)}" if e.get("errors") else "",
            f"Workflows: {', '.join(e['flows'])}" if e.get("flows") else ""],
            doc=f"{ref}entry-points.md#{e['id']}", source=f"{e['file']}:{e['line']}", related=[e["handler"]])

    def site_lines(obj):
        ss = sites_of_obj.get(obj.lower(), [])
        return [f"{s.get('method') or s['file']} — {s['op']} via {s['tech']}" + (f" ({s['via']})" if s.get("via") else "") + f" at {s['file']}:{s['line']}" for s in ss]

    for r in DB.get("routines", []):
        full = f"{r['schema']}.{r['name']}" if r.get("schema") else r["name"]
        card(r["anchor"], f"db-{r['kind']}", full, [
            f"Defined in {r['file']}:{r.get('line', '')}",
            f"Parameters: {'; '.join(r['params'])}" if r.get("params") else "Parameters: none",
            f"Returns: {r['returns']}" if r.get("returns") else "",
            f"Tables it touches: {', '.join(r['touches'])}" if r.get("touches") else "",
            f"Called from code: {cap(site_lines(r['name']), 10)}" if site_lines(r["name"]) else "Called from code: no call site found",
        ], doc=f"{ref}{r.get('page', 'db-routines.md')}#{r['anchor']}", source=f"{r['file']}:{r.get('line', '')}",
            related=[s.get("anchor") for s in sites_of_obj.get(r["name"].lower(), [])], key_names=(r["name"],))
    for t in DB.get("tables", []):
        full = f"{t['schema']}.{t['name']}" if t.get("schema") else t["name"]
        used_by = [r["name"] for r in DB.get("routines", []) if t["name"].lower() in (x.lower() for x in r.get("touches", []))]
        card(t["anchor"], "db-table", full, [
            f"Defined in {t['file']}", f"Columns: {', '.join(c.strip() for c in t.get('columns', []))}" if t.get("columns") else "",
            f"Used by routines: {cap(used_by)}" if used_by else "",
            f"Accessed from code: {cap(site_lines(t['name']), 10)}" if site_lines(t["name"]) else "Accessed from code: no direct access found",
            f"Changed by (entry points): {cap(sorted(writers_of.get(t['name'].lower(), [])), 10)}" if writers_of.get(t["name"].lower()) else "",
        ], doc=f"{ref}{t.get('page', 'db-tables.md')}#{t['anchor']}", source=t["file"],
            related=[s.get("anchor") for s in sites_of_obj.get(t["name"].lower(), [])], key_names=(t["name"],))

    for e in ERRS:
        card(e["anchor"], "error", e["message"][:90], [
            f"Message: {e['message']}", f"Kind: {e['kind']} ({e['type']})", f"Raised at {e['file']}:{e['line']}" + (f" in {name(e['method'])}" if e.get("method") else ""),
            f"A user meets it from: {cap(sorted(err_entries.get(e['anchor'], [])), 8)}" if err_entries.get(e["anchor"]) else ""],
            doc=f"{ref}errors.md#{e['anchor']}", source=f"{e['file']}:{e['line']}", related=[e.get("method")])

    pkgs = defaultdict(list)
    ver = lambda v: v.get("version", "") if isinstance(v, dict) else str(v)
    for p in DEPS.get("projects", []):
        plist = [f"{k} {ver(v)}" for k, v in (p.get("packages") or {}).items()]
        for k, v in (p.get("packages") or {}).items():
            pkgs[k].append((p["name"], ver(v)))
        card(p["anchor"], "project", p["name"], [
            f"Manifest: {p['file']}; {p.get('kind', '')} {p.get('framework', '')} {p.get('output', '')}".strip(),
            f"Layer {p['layer']}" if p.get("layer") is not None else "",
            f"Depends on: {cap(p.get('depends_on', []))}" if p.get("depends_on") else "Depends on: no other project",
            f"Used by: {cap(p.get('used_by', []))}" if p.get("used_by") else "Used by: no other project",
            f"Packages: {cap(plist, 25)}" if plist else ""],
            doc=f"{ref}dependencies.md#{p['anchor']}", source=p["file"])
    for k, uses in sorted(pkgs.items()):
        vs = sorted({v for _, v in uses if v})
        card("pkg-" + re.sub(r"[^a-z0-9]+", "-", k.lower()).strip("-"), "package", k, [
            f"Versions: {', '.join(vs)}" + (" (version drift between projects)" if len(vs) > 1 else ""),
            f"Used by projects: {cap([f'{p} ({v})' for p, v in uses], 20)}"],
            doc=f"{ref}dependencies.md#pkg-{re.sub(r'[^a-z0-9]+', '-', k.lower()).strip('-')}")

    fdir = os.path.join(DOCS, "_src", "workflows", "flows")
    for f in sorted(os.listdir(fdir)) if os.path.isdir(fdir) else []:
        if not f.endswith(".flow.json"):
            continue
        try:
            s = json.load(open(os.path.join(fdir, f), encoding="utf-8"))
        except ValueError:
            continue
        fid = s.get("id") or f[:-10]
        steps = [f"{k + 1}. [{st.get('lane', '')}] {st.get('text', '')}" + (f" ({st['ref']})" if isinstance(st.get("ref"), str) else "")
                 for k, st in enumerate(s.get("steps") or [])]
        card(f"flow-{fid}", "workflow", s.get("title") or fid, [
            s.get("summary", ""), f"Starts when: {s['trigger']}" if s.get("trigger") else "", f"Ends with: {s['outcome']}" if s.get("outcome") else "",
            "Steps:", *steps, *(f"Note: {n}" for n in s.get("notes") or [])],
            doc=f"workflows/flows/{fid}.md", key_names=(fid,))

    # reference entities the exports do not cover (config keys, seed rows, classes, views, roles ...)
    covered = {c["id"] for c in CARDS}
    ep = os.path.join(AGENT, "entities.jsonl")
    if os.path.exists(ep):
        for line in open(ep, encoding="utf-8"):
            e = json.loads(line)
            if e["kind"] in SKIP_KINDS or not e.get("anchor") or e["anchor"] in covered:
                continue
            card(e["anchor"], e["kind"], e["name"], [e.get("summary", ""), f"Database: {e['database']}" if e.get("database") else ""],
                 doc=f"{e['file'].removeprefix(DOCS + '/')}#{e['anchor']}")
            covered.add(e["anchor"])

    # narrative pages: heading-bounded chunks
    for d, dirs, files in os.walk(DOCS):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for fn in sorted(files):
            if fn.endswith(".md"):
                section_cards(os.path.join(d, fn))

    with open(os.path.join(AGENT, "cards.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
        for c in CARDS:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    kinds = defaultdict(int)
    for c in CARDS:
        kinds[c["kind"]] += 1
    big = sum(1 for c in CARDS if len(c["text"]) >= MAX_CHARS - 60)
    print(f"cards: {len(CARDS)} ({dict(sorted(kinds.items(), key=lambda kv: -kv[1]))}); {big} at the size cap")


def blocks(text):
    """Markdown → blocks that must stay whole: fenced code, tables, lists, paragraphs, headings."""
    out, cur, fence = [], [], False
    for line in text.splitlines():
        if line.startswith("```"):
            if fence:
                cur.append(line)
                out.append("\n".join(cur))
                cur, fence = [], False
            else:
                if cur:
                    out.append("\n".join(cur))
                cur, fence = [line], True
            continue
        if fence:
            cur.append(line)
        elif not line.strip():
            if cur:
                out.append("\n".join(cur))
            cur = []
        elif re.match(r"#{1,6}\s", line):
            if cur:
                out.append("\n".join(cur))
            out.append(line)
            cur = []
        else:
            cur.append(line)
    if cur:
        out.append("\n".join(cur))
    return [b for b in out if not b.startswith("```mermaid")]


def split_table(b, room):
    rows = b.splitlines()
    head, body = rows[:2], rows[2:]
    parts, cur = [], []
    for r in body:
        if cur and len("\n".join(head + cur + [r])) > room:
            parts.append("\n".join(head + cur))
            cur = []
        cur.append(r)
    return parts + (["\n".join(head + cur)] if cur else [])


def section_cards(path):
    rel = path.replace("\\", "/").removeprefix(DOCS + "/")
    if rel in SKIP_PAGES:
        return
    text =plain(re.sub(FRONT, "", open(path, encoding="utf-8").read()))
    stack, sections, cur = [], [], []

    def flush():
        body = [b for b in cur if b.strip()]
        if body:
            sections.append((list(stack), body))
    for b in blocks(text):
        m = re.match(r"(#{1,6})\s+(.+)", b)
        if m:
            flush()
            cur = []
            lvl = len(m.group(1))
            stack[:] = [s for s in stack if s[0] < lvl] + [(lvl, m.group(2).strip())]
            continue
        cur.append(b)
    flush()
    page = stack[0][1] if stack and stack[0][0] == 1 else (sections[0][0][0][1] if sections and sections[0][0] else rel)
    for heads, body in sections:
        crumb = " › ".join(h for _, h in heads) or page
        anchor = re.sub(r"[\s]+", "-", re.sub(r"[^\w\s-]", "", heads[-1][1].lower())).strip("-") if heads else ""
        room = MAX_CHARS - len(crumb) - 80
        pieces = []
        for b in body:
            pieces += split_table(b, room) if b.startswith("|") and len(b) > room else [b[i:i + room] for i in range(0, len(b), room)] if len(b) > room else [b]
        parts, cur_p = [], []
        for p in pieces:
            if cur_p and len("\n\n".join(cur_p + [p])) > room:
                parts.append(cur_p)
                tail = cur_p[-1]
                cur_p = [tail] if len(tail) < room // 4 and not tail.startswith(("|", "```")) else []  # one block of overlap
            cur_p.append(p)
        if cur_p:
            parts.append(cur_p)
        for k, ps in enumerate(parts):
            body_txt = "\n\n".join(ps)
            if len(re.sub(r"\W", "", body_txt)) < 40:
                continue  # nav stubs, lone links
            sid = f"{rel}#{anchor}" + (f"-part{k + 1}" if len(parts) > 1 else "")
            CARDS.append({"id": sid, "kind": "section", "title": heads[-1][1] if heads else page, "breadcrumb": f"{crumb}" + (f" (part {k + 1}/{len(parts)})" if len(parts) > 1 else ""),
                          "text": f"{PRODUCT} · {crumb}\n{body_txt}", "keys": keys(heads[-1][1] if heads else page),
                          "doc": f"{rel}#{anchor}" if anchor else rel, "source": "", "related": []})


if __name__ == "__main__":
    main()
