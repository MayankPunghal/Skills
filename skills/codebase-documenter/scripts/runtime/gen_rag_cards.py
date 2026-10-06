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

Entity cards come from docs/agent/*.json (methods, endpoints, db, db-access, errors, entry-points, dependencies, di)
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
SKIP_PAGES = set(CFG.get("rag_skip_pages", ["appendices/coverage.md", "appendices/code-map.md"]))
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
    # real HTML tags only: keep generics (Task<Order>) and route segments (<int:id>)
    md = re.sub(r"</?(?:a|span|div|p|br|hr|img|iframe|details|summary|sup|sub|em|strong|b|i|code|pre|table|thead|tbody|tr|td|th|ul|ol|li)"
                r"(?:\s[^<>]*)?/?>", "", md, flags=re.I)
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
    DI = load("di.json", {})
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
            f"Note: {x['note']}" if x.get("note") else "",
            f"Parameters: {'; '.join(x['params'])}" if x.get("params") else "Parameters: none" if x.get("params") == [] else "",
            f"Returns: {x['returns']}" if x.get("returns") else "",
            f"Calls: {cap([name(b) + (' [' + x['via'][b] + ']' if b in (x.get('via') or {}) else '') for b in x.get('calls', [])])}" if x.get("calls") else "Calls: no other documented method",
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
            f"Reads: {', '.join(sorted(set(r['reads'])))}" if r.get("reads") else "",
            f"Writes: {', '.join(w['name'] + ' (' + w['op'] + ')' for w in r['writes'])}" if r.get("writes") else "",
            f"Calls: {', '.join(r['calls'])}" if r.get("calls") else "",
            f"Called by (SQL): {', '.join(r['called_by'])}" if r.get("called_by") else "",
            f"Tables it touches: {', '.join(r['touches'])}" if r.get("touches") and not (r.get("reads") or r.get("writes")) else "",
            f"PostgreSQL: {', '.join(f'{k} {v}' for k, v in sorted((r.get('conversion') or {}).items()))}"
            + (f"; no PostgreSQL equivalent: {', '.join(r['no_pg_equivalent'])}" if r.get("no_pg_equivalent") else "") if r.get("conversion") else "",
            f"Called from code: {cap(site_lines(r['name']), 10)}" if site_lines(r["name"]) else "Called from code: no call site found",
        ], doc=f"{ref}{r.get('page', 'db-routines.md')}#{r['anchor']}", source=f"{r['file']}:{r.get('line', '')}",
            related=[s.get("anchor") for s in sites_of_obj.get(r["name"].lower(), [])], key_names=(r["name"],))
    for t in DB.get("tables", []):
        full = f"{t['schema']}.{t['name']}" if t.get("schema") else t["name"]
        used_by = [r["name"] for r in DB.get("routines", []) if t["name"].lower() in (x.lower() for x in r.get("touches", []))]
        card(t["anchor"], "db-table", full, [
            f"Defined in {t['file']}" + (f":{t['line']}" if t.get("line") else ""),
            f"Columns: {', '.join(c.strip() for c in t.get('columns', []))}" if t.get("columns") else "",
            f"Primary key: {', '.join(t['primary_key'])}" if t.get("primary_key") else "",
            f"Foreign keys: {'; '.join(', '.join(fk.get('columns') or []) + ' -> ' + (fk.get('references') or '') for fk in t['foreign_keys'])}" if t.get("foreign_keys") else "",
            f"Read by routines: {cap(t['read_by'])}" if t.get("read_by") else "",
            f"Written by routines: {cap(t['written_by'])}" if t.get("written_by") else "",
            f"Used by routines: {cap(used_by)}" if used_by and not (t.get("read_by") or t.get("written_by")) else "",
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
            f"Used by projects: {cap([f'{p} ({v})' for p, v in uses], 20)}"]
            + [f"Version {v}: licence {i.get('licence') or 'not declared'}; builds for {', '.join(i.get('frameworks') or []) or 'unknown'}"
               + (f"; WINDOWS-ONLY ({i['why']}): blocks Linux hosting" if i.get("windows_only") else f"; {i['why']}" if i.get("why") else "")
               for v, i in sorted((DEPS.get("package_info") or {}).get(k, {}).items())],
            doc=f"{ref}dependencies.md#pkg-{re.sub(r'[^a-z0-9]+', '-', k.lower()).strip('-')}")

    di_cards(DI, ref)
    ui_cards(load("views.json", {}), load("portability.json", {}), ref)

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


def di_cards(DI, ref):
    """Dependency injection and run-time wiring (C#, generic-di adapter): one card per service, message, host, finding,
    plus the pipeline / jobs / events as one card each, so "what runs behind IOrderService" retrieves a self-contained answer."""
    if not DI:
        return
    page = f"{ref}dependency-injection.md"
    loc = lambda x: f"{x.get('file')}:{x.get('line')}"
    for s in DI.get("services", []):
        regs = s.get("registrations", [])
        card(s["anchor"], "di-service", s["service"], [
            f"{(s.get('kind') or 'type').capitalize()} defined in {s['file']}" if s.get("file") else "",
            *(f"Registered: {s['service']} -> {r['impl'] or '?'} ({r['lifetime']}" + (f", key {r['key']}" if r.get("key") else "")
              + f", {r['how']}, {r['container']}) in {', '.join(r.get('hosts') or ['?'])} at {loc(r)}"
              + (f" via module {r['module']}" if r.get("module") else "") for r in regs[:10]),
            "Not registered anywhere in this repository (registered elsewhere, by convention, or a missing registration)" if not regs else "",
            f"Also implemented by (never registered): {cap(s.get('unregistered_implementers', []))}" if s.get("unregistered_implementers") else "",
            f"Injected into: {cap(s.get('consumers', []), 20)}" if s.get("consumers") else "Injected into: no constructor found",
        ], doc=f"{page}#{s['anchor']}", source=s.get("file") or "", key_names=[r.get("impl") for r in regs])
    hosts = DI.get("anchors", {}).get("hosts", {})
    by_host = defaultdict(list)
    for r in DI.get("registrations", []):
        for h in r.get("hosts") or []:
            by_host[h].append(r)
    for h, a in hosts.items():
        feats = [n["kind"] for n in DI.get("notes", []) if n.get("host") == h]
        card(a, "di-host", f"Composition root of {h}", [
            f"{len(by_host[h])} registrations: " + cap([f"{r['service']} -> {r['impl']} ({r['lifetime']})" for r in by_host[h]], 30),
            f"Framework features switched on: {cap(feats, 20)}" if feats else ""], doc=f"{page}#{a}", key_names=(h,))
    for n, m in DI.get("messages", {}).items():
        a = DI.get("anchors", {}).get("messages", {}).get(n)
        if not a:
            continue
        card(a, "di-message", n, [
            f"Kind: {m.get('kind') or 'message'}",
            "Handled by: " + cap([f"{x['class']}.{x['method']} ({loc(x)})" for x in m.get("handlers", [])]),
            "Sent / published from: " + (cap([f"{(x.get('cls') or '')}.{x['method']} ({x['verb']}, {loc(x)})" for x in m.get("senders", [])])
                                         or "not found in the code (sent from outside, by reflection, or dead)")],
            doc=f"{page}#{a}", key_names=[x["class"] for x in m.get("handlers", [])])
    for f in DI.get("findings", []):
        if f.get("anchor"):
            card(f["anchor"], "di-finding", f"{f['kind']} ({f['severity']})", [f["text"], f"Where: {loc(f)}"],
                 doc=f"{page}#{f['anchor']}", source=loc(f), key_names=(f.get("class"), f.get("type")))
    groups = [("di-pipeline", "Request pipeline and implicit calls", [f"{p['kind']}: {p['type']} ({p.get('applies_to') or 'all'}) at {loc(p)}" for p in DI.get("pipeline", [])]),
              ("di-jobs", "Background jobs", [f"{j['type']}.{j['method']} via {j['api']}, scheduled from {(j.get('cls') or '')}.{j.get('caller') or '?'} at {loc(j)}" for j in DI.get("jobs", [])]),
              ("di-events", "Events and delegates", [f"{e['member']} {e['op']} {e['cls']}.{e['handler']} at {loc(e)}" for e in DI.get("events", [])]
               + [f"stored delegate {x['type']}.{x['member']}: built in {x.get('builder')} ({x.get('builder_file')}:{x.get('builder_line')}), invoked by {x.get('invoker_cls')}.{x.get('invoker')}" for x in DI.get("stored_delegates", [])]),
              ("di-options", "Options bindings", [f"{o['type']} bound to section {o.get('section') or '?'} ({o['how']}) at {loc(o)}" for o in DI.get("options", [])]),
              ("di-limits", "Run-time lookups static analysis cannot follow", [f"{r['text']} at {loc(r)}" for r in DI.get("reflection", [])])]
    for a, title, lines in groups:
        if lines:
            card(a, "di-wiring", title, lines[:60], doc=f"{page}#{a}")
    for n, parts in DI.get("partials", {}).items():
        a = re.sub(r"[^a-z0-9]+", "-", f"di-partial-{n}".lower()).strip("-")
        card(a, "partial-type", n, [f"Partial {parts[0]['kind']} split over {len(parts)} files:"]
             + [f"{p['file']}:{p['line']} declares " + (", ".join(p.get("methods", [])[:20]) or "no methods")
                + (f"; bases {', '.join(p['bases'])}" if p.get("bases") else "") for p in parts],
             doc=f"{page}#{a}", source=f"{parts[0]['file']}:{parts[0]['line']}", key_names=[p["file"].rsplit("/", 1)[-1] for p in parts])


def ui_cards(V, P, ref):
    """Views / pages (generic-views) and portability flags (generic-portability): one card per screen-like item and per
    rule, plus a totals card each, so "how many pages are there" and "what breaks on Linux" retrieve a direct answer."""
    if V.get("items"):
        page = f"{ref}views-and-pages.md"
        card("ui-totals", "ui-summary", "Views and pages: totals", [
            f"{len(V['items'])} UI files, {V.get('screens', 0)} screens a user can open",
            "By kind: " + ", ".join(f"{k} {n}" for k, n in sorted(V.get("totals", {}).items(), key=lambda kv: -kv[1]))],
            doc=f"{page}#ui-totals", key_names=("views", "pages", "screens"))
        for i in V["items"]:
            card(i["anchor"], "ui-view", f"{i['kind']} {i['name']}", [
                f"File: {i['file']} ({i['lines']} lines" + (f", code-behind {i['code_behind']} {i['code_lines']} lines" if i.get("code_behind") else "") + ")",
                f"Project: {i['project']}", f"Route: {i['route']}" if i.get("route") else "",
                f"Model / class: {i['model']}" if i.get("model") else "", f"Layout / master / base: {i['layout']}" if i.get("layout") else "",
                f"Handlers: {', '.join(i['handlers'])}" if i.get("handlers") else "", f"Title: {i['title']}" if i.get("title") else ""],
                doc=f"{page}#{i['anchor']}", source=i["file"], related=[i["action"]] if i.get("action") else [],
                key_names=(i["file"].rsplit("/", 1)[-1], i.get("route"), i.get("model")))
    if P.get("rules") is not None:
        page = f"{ref}platform-portability.md"
        card("port-summary", "portability-summary", "Platform portability (Windows to Linux): summary", [
            f"{sum(len(r['sites']) for r in P['rules'])} occurrences of {len(P['rules'])} of {P.get('rules_checked', 0)} portability rules",
            *(f"{r['severity']}: {r['title']} ({r['id']}), {len(r['sites'])} occurrences" for r in P["rules"][:40]),
            "Windows-only packages: " + (", ".join(f"{x['name']} {x['version']}" for x in P.get("windows_only_packages", [])) or "none found")],
            doc=f"{page}#port-summary", key_names=("linux", "portability", "windows-only"))
        for r in P["rules"]:
            card(r["anchor"], "portability-rule", f"{r['title']} ({r['id']})", [
                f"Severity {r['severity']}, category {r['category']}", f"Why: {r['why']}", f"Suggested fix: {r['fix']}",
                f"Replacement: {r['alt']}" if r.get("alt") else "",
                "Where: " + cap([f"{x['file']}:{x['line']}" for x in r["sites"]], 25)],
                doc=f"{page}#{r['anchor']}", source=f"{r['sites'][0]['file']}:{r['sites'][0]['line']}" if r["sites"] else "",
                related=[x["method"] for x in r["sites"] if x.get("method")][:20], key_names=(r["id"],))


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


def split_code(b, room):
    """Fenced code bigger than the budget: split at line boundaries, each part re-opened and closed with the same fence."""
    lines = b.splitlines()
    fence, body = lines[0], [l for l in lines[1:] if l.strip() != "```"]
    parts, cur = [], []
    for l in body:
        if cur and len("\n".join([fence] + cur + [l, "```"])) > room:
            parts.append("\n".join([fence] + cur + ["```"]))
            cur = []
        cur.append(l[:room - 20])
    return parts + (["\n".join([fence] + cur + ["```"])] if cur else [])


def split_prose(b, room):
    """Paragraph or list bigger than the budget: split at sentence (or line) boundaries, never mid-word."""
    units = re.split(r"(?<=[.!?])\s+|\n", b)
    parts, cur = [], ""
    for u in units:
        while len(u) > room:  # one enormous sentence: cut at the last space before the limit
            cut = u.rfind(" ", 0, room) if u.rfind(" ", 0, room) > 0 else room
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(u[:cut])
            u = u[cut:].lstrip()
        if cur and len(cur) + 1 + len(u) > room:
            parts.append(cur)
            cur = ""
        cur = f"{cur} {u}".strip() if cur else u
    return parts + ([cur] if cur else [])


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
            if len(b) <= room:
                pieces.append(b)
            elif b.startswith("|"):
                pieces += split_table(b, room)
            elif b.startswith("```"):
                pieces += split_code(b, room)
            else:
                pieces += split_prose(b, room)
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
