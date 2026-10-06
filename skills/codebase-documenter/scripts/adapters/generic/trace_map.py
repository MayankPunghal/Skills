"""UI-to-backend trace and entry points: what a button calls, and what starts a method.

Writes into docs/reference/:
  ui-map.md        every UI trigger (Razor / Razor Pages links, buttons and forms, Html.BeginForm / ActionLink, Web Forms
                   server-control events, Blazor @onclick, XAML Click, WinForms designer events, onclick / React / Vue /
                   Angular bindings, fetch / axios / $.ajax / HttpClient calls) → endpoint → handler method → what it reaches
                   (methods, database objects with operation and technology). Anchors ui-…
  entry-points.md  every entry point (endpoint, UI event handler, background job / message handler / scheduled function)
                   with the methods, database objects, errors and flows it reaches (anchors ent-…), plus reverse indexes:
                   method → entry points, UI triggers and flows; table → entry points that change it; error → where users
                   meet it.
and docs/agent/entry-points.json; adds "entry_points" and "flows" to docs/agent/methods.json.
Needs the method map; uses endpoints.json (generic-api), db-access.json (generic-dbaccess), errors.json (generic-errors)
and flow specs when present. Static: dynamic routes, reflection and DI-only dispatch are shown as unresolved.
Options (adapter_options.generic-trace): max_depth (default 8), skip_regex.
"""
import json
import os
import re
from collections import defaultdict, deque

from _scan import BACK, DOCS, ROOT, Methods, esc, esc_text, line_at, options, read, slug, walk, write_page

OPT = options("generic-trace")
DEPTH = OPT.get("max_depth", 8)
M = Methods()
UI_EXT = {".cshtml", ".razor", ".aspx", ".ascx", ".master", ".html", ".htm", ".xaml", ".js", ".mjs", ".jsx", ".ts", ".tsx", ".vue", ".cs", ".vb"}
UI_SKIP = re.compile(r"(^|/)(\.git|bin|obj|node_modules|dist|build|out|vendor|packages|wwwroot/lib|coverage)(/|$)|\.min\.js$", re.I)
JOB_FILE = re.compile(r":\s*[^{]*\b(BackgroundService|IHostedService|IJob|IInvocable|IConsumer<|INotificationHandler<|IRequestHandler<|IHandleMessages<)|"
                      r"\[(FunctionName|Function|TimerTrigger|QueueTrigger)\b|@(Scheduled|KafkaListener|RabbitListener|JmsListener|SqsListener)\b|"
                      r"\bstatic\s+(?:async\s+)?(?:void|Task|int|Task<int>)\s+Main\s*\(")
JOB_METHOD = re.compile(r"\.(ExecuteAsync|Execute|Run|RunAsync|Main|Handle|HandleAsync|Consume|Invoke|Process\w*)$")


def load(name):
    p = os.path.join(DOCS, "agent", name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"@\([^)]*\)|@[\w.]+(\([^)]*\))?|&\w+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()[:50]


def razor_attr(attrs, name):
    """Value of a Razor tag-helper attribute; keeps `@(cond ? "A" : "B")` whole."""
    m = re.search(r"\b" + name + r"=\"(@\([^)]*\)|[^\"]*)\"", attrs)
    return m.group(1) if m else None


def segs(url):
    url = re.sub(r"^\w+://[^/]+", "", url.split("?")[0].split("#")[0])
    url = re.sub(r"\$\{[^}]*\}|'\s*\+\s*[^+]+\+\s*'|\"\s*\+\s*[^+]+\+\s*\"|\{\{[^}]*\}\}|@[\w.]+", "*", url)
    return [s for s in url.strip("/").split("/") if s != ""]


def route_matches(route, url):
    a, b = segs(route), segs(url)
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x.lower() == y.lower() or "*" in y or re.fullmatch(r"\{[^}]*\}|:\w+\??|<[^>]*>", x):
            continue
        return False
    return True


class Endpoints:
    def __init__(self):
        self.rows = load("endpoints.json") or []
        self.by_handler = defaultdict(list)
        for e in self.rows:
            name = (M.data.get(e.get("handler")) or {}).get("name")
            if name:
                self.by_handler[name.lower()].append(e)

    def mvc(self, ctl, action, verb, area=None):
        cands = self.by_handler.get(f"{ctl}controller.{action}".lower(), [])
        # same controller name in several MVC areas: keep the ones in the view's area (or outside any area)
        if area:
            in_area = [e for e in cands if f"/areas/{area.lower()}/" in "/" + e["file"].lower()]
        else:
            in_area = [e for e in cands if "/areas/" not in "/" + e["file"].lower()]
        cands = in_area or cands
        pick = [e for e in cands if e["verb"] == verb] or [e for e in cands if e["verb"] == "ANY"] or cands
        return pick[0] if pick else None

    def url(self, url, verb):
        cands = [e for e in self.rows if route_matches(e["route"], url)]
        pick = [e for e in cands if e["verb"] == verb.upper()] or [e for e in cands if e["verb"] == "ANY"] or cands
        return pick[0] if pick else None


def handler_in(path, name):
    """Method anchor for an event handler `name` declared in `path` (or its code-behind / partial class file)."""
    bases = [path, path + ".cs", path + ".vb", re.sub(r"\.designer\.(cs|vb)$", r".\1", path, flags=re.I), re.sub(r"\.razor$", ".razor.cs", path)]
    for b in bases:
        for _, a in M.by_file.get(b, []):
            if M.data[a]["name"].lower().endswith("." + name.lower()) or M.data[a]["name"].lower() == name.lower():
                return a
    return None


def ui_triggers(EP):
    rows, js_funcs, bindings = [], defaultdict(list), []
    skip = re.compile(OPT["skip_regex"]) if OPT.get("skip_regex") else None
    for path, full in walk(exts=UI_EXT, skip=UI_SKIP):
        if skip and skip.search(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        text = None

        def add(line, element, label, event, target=None, endpoint=None, handler=None, note=""):
            rows.append({"file": path, "line": line, "element": element, "label": label, "event": event, "target": target,
                         "endpoint": endpoint, "handler": handler or (endpoint.get("handler") if endpoint else None), "note": note})
        if ext in (".cshtml", ".razor"):
            text = read(full)
            parts = path.split("/")
            ctl = parts[parts.index("Views") + 1] if "Views" in parts and parts.index("Views") + 2 < len(parts) else None
            area = parts[parts.index("Areas") + 1] if "Areas" in parts else None
            view = os.path.splitext(parts[-1])[0]
            if ctl == "Shared":
                ctl = None
            for m in re.finditer(r"<(form|a|button|input)\b([^>]*)>", text, re.I):
                tag, attrs = m.group(1).lower(), m.group(2)
                act, c, page, ph = (razor_attr(attrs, n) for n in ("asp-action", "asp-controller", "asp-page", "asp-page-handler"))
                if not (act or c or page or ph or tag == "form"):
                    continue
                line = line_at(text, m.start())
                if tag == "form":
                    body = text[m.end():text.find("</form", m.end()) if text.find("</form", m.end()) > 0 else m.end() + 2000]
                    b = re.search(r"<button[^>]*>(.*?)</button>|<input[^>]*type=\"submit\"[^>]*value=\"([^\"]*)\"", body, re.S | re.I)
                    label = strip_html((b.group(1) or b.group(2)) if b else "")
                    verb = (re.search(r"\bmethod=\"(\w+)\"", attrs, re.I) or [None, "GET"])[1].upper()
                else:
                    end = text.find(f"</{tag}", m.end())
                    label = strip_html(text[m.end():end]) if 0 < end < m.end() + 600 else strip_html(re.search(r"value=\"([^\"]*)\"", attrs).group(1)) if re.search(r"value=\"([^\"]*)\"", attrs) else tag
                    before = text[:m.start()]
                    fo = before.rfind("<form")
                    verb = "GET"
                    if tag in ("button", "input") and fo > before.rfind("</form"):
                        verb = (re.search(r"\bmethod=\"(\w+)\"", text[fo:fo + 400], re.I) or [None, "GET"])[1].upper()
                if page is not None or ph is not None:
                    pg = page if page is not None else "/" + "/".join(parts[parts.index("Pages") + 1:])[:-7] if "Pages" in parts else ""
                    hname = f"On{verb.title()}{ph or ''}"
                    pfile = next((p for p in M.by_file if p.lower().endswith(("pages" + pg + ".cshtml.cs").lower())), None)
                    h = next((a for _, a in M.by_file.get(pfile, []) if re.search(r"\." + hname + r"(Async)?$", M.data[a]["name"])), None) if pfile else None
                    add(line, tag, label or f"→ {pg}", verb, target=f"page {pg}" + (f" handler {ph}" if ph else ""), handler=h)
                    continue
                actions = re.findall(r"\"(\w+)\"", act) if act and act.startswith("@") else [act] if act else [view]
                cname = c if c is not None else ctl
                if not actions or (cname or "").startswith("@"):
                    add(line, tag, label or {"a": "link"}.get(tag, tag), verb, target=f"{cname or '?'}/{act or '?'}", note="dynamic target (set at run time)")
                    continue
                for a in actions:
                    if not label:
                        label = f"→ {a}"
                    ep = EP.mvc(cname, a, verb, area) if cname else None
                    add(line, tag, label, verb, target=f"{('/' + area) if area else ''}/{cname or '?'}/{a}", endpoint=ep,
                        note=("conditional: one of " + " / ".join(actions)) if len(actions) > 1 else "" if ep or cname else "controller not known from the view path")
            for m in re.finditer(r"Html\.(BeginForm|ActionLink|BeginRouteForm)\(\s*(\"[^\"]*\"\s*,\s*)?\"(\w+)\"\s*,\s*\"(\w+)\"", text):
                verb = "POST" if m.group(1) != "ActionLink" else "GET"
                label = (m.group(2) or "").strip(' ",') if m.group(1) == "ActionLink" else "form"
                action, cname = m.group(3), m.group(4)
                add(line_at(text, m.start()), m.group(1), label, verb, target=f"/{cname}/{action}", endpoint=EP.mvc(cname, action, verb, area))
            for m in re.finditer(r"@on(click|submit|change|input)=\"(?:\(\)\s*=>\s*)?(\w+)", text):  # Blazor
                add(line_at(text, m.start()), "element", m.group(2), m.group(1), target=f"method {m.group(2)}", handler=handler_in(path, m.group(2)))
            for m in re.finditer(r"\b(OnValidSubmit|OnSubmit|OnClick)=\"@?(\w+)\"", text):
                add(line_at(text, m.start()), "component", m.group(2), m.group(1), target=f"method {m.group(2)}", handler=handler_in(path, m.group(2)))
        if ext in (".aspx", ".ascx", ".master"):
            text = read(full)
            for m in re.finditer(r"<asp:(\w+)\b([^>]*)>", text, re.I):
                attrs = m.group(2)
                label = (re.search(r"\bText=\"([^\"]*)\"", attrs) or re.search(r"\bID=\"([^\"]*)\"", attrs) or [None, m.group(1)])[1]
                for ev, h in re.findall(r"\b(On\w+|SelectMethod|UpdateMethod|InsertMethod|DeleteMethod)=\"(\w+)\"", attrs):
                    if ev.lower() in ("onclientclick",):
                        continue
                    add(line_at(text, m.start()), f"asp:{m.group(1)}", label, ev, target=f"code-behind {h}", handler=handler_in(path, h))
        if ext == ".xaml":
            text = read(full)
            for m in re.finditer(r"<(\w+)\b[^>]*?\b(Click|Checked|SelectionChanged|TextChanged)=\"(\w+)\"", text):
                add(line_at(text, m.start()), m.group(1), m.group(1), m.group(2), target=f"code-behind {m.group(3)}", handler=handler_in(path, m.group(3)))
            for m in re.finditer(r"<(\w+)\b[^>]*?\bCommand=\"\{Binding\s+(\w+)", text):
                add(line_at(text, m.start()), m.group(1), m.group(1), "Command", target=f"view-model {m.group(2)}", note="command binding (view model)")
        if ext in (".cs", ".vb") and re.search(r"\.designer\.(cs|vb)$", path, re.I):
            text = read(full)
            labels = dict(re.findall(r"this\.(\w+)\.Text\s*=\s*\"([^\"]*)\"", text))
            for m in re.finditer(r"this\.(\w+)\.(\w+)\s*\+=\s*(?:new\s+[\w.]+\()?(?:this\.)?(\w+)\)?", text):
                add(line_at(text, m.start()), m.group(1), labels.get(m.group(1), m.group(1)), m.group(2), target=f"code-behind {m.group(3)}",
                    handler=handler_in(path, m.group(3)))
        if ext in (".js", ".mjs", ".jsx", ".ts", ".tsx", ".vue", ".html", ".htm", ".cshtml", ".razor"):
            text = text if text is not None else read(full)
            for rx, vg, ug in ((r"fetch\(\s*([`'\"])(.+?)\1(?:\s*,\s*\{[^}]*?method\s*:\s*['\"](\w+))?", 3, 2),
                               (r"axios\.(get|post|put|delete|patch)\(\s*([`'\"])(.+?)\2", 1, 3),
                               (r"\$\.(get|post|getJSON)\(\s*(['\"`])(.+?)\2", 1, 3),
                               (r"\$\.ajax\(\s*\{[^}]*?url\s*:\s*(['\"`])(.+?)\1[^}]*?(?:type|method)\s*:\s*['\"](\w+)", 3, 2),
                               (r"\bhttp\.(get|post|put|delete|patch)\s*(?:<[^>()]*>)?\(\s*([`'\"])(.+?)\2", 1, 3)):
                for m in re.finditer(rx, text, re.S):
                    verb = (m.group(vg) or "GET").upper().replace("GETJSON", "GET")
                    url = m.group(ug)
                    if not url.startswith(("/", "http", "${", "api", "~")) and "/" not in url:
                        continue
                    before = text[max(0, m.start() - 3000):m.start()]
                    fn = re.findall(r"(?:function\s+(\w+)|(\w+)\s*[:=]\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*=>|\w+\s*=>)|^\s*(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{)", before, re.M)
                    fname = next((x for x in reversed([g for t in fn for g in t if g]) if x not in ("if", "for", "while", "switch", "catch", "function")), "")
                    ep = EP.url(url, verb)
                    js_funcs[fname].append((path, line_at(text, m.start()), verb, url, ep))
            for m in re.finditer(r"\bon(click|submit|change)=\"(\w+)\(|onClick=\{(?:\(\)\s*=>\s*)?(\w+)|@click(?:\.\w+)?=\"(\w+)|v-on:click=\"(\w+)|\(click\)=\"(\w+)\(|"
                                 r"addEventListener\(\s*['\"](click|submit|change)['\"]\s*,\s*(\w+)", text):
                g = [x for x in m.groups() if x]
                fname, ev = g[-1], ("click" if len(g) == 1 else g[0])
                bindings.append((path, line_at(text, m.start()), fname, ev))
    bound = set()
    for path, line, fname, ev in bindings:
        for jpath, jline, verb, url, ep in js_funcs.get(fname, []):
            bound.add((jpath, jline))
            rows.append({"file": path, "line": line, "element": "element", "label": fname, "event": ev, "target": f"{verb} {url}",
                         "endpoint": ep, "handler": ep and ep.get("handler"), "note": f"via {fname}() in `{jpath}:{jline}`"})
    for fname, calls in js_funcs.items():
        for jpath, jline, verb, url, ep in calls:
            if (jpath, jline) not in bound:
                rows.append({"file": jpath, "line": jline, "element": "script", "label": fname or "(script)", "event": "call",
                             "target": f"{verb} {url}", "endpoint": ep, "handler": ep and ep.get("handler"), "note": ""})
    return rows


def reach(start):
    seen, q = {start}, deque([(start, 0)])
    while q:
        a, d = q.popleft()
        if d >= DEPTH:
            continue
        for b in (M.data.get(a) or {}).get("calls", []):
            if b not in seen and b in M.data:
                seen.add(b)
                q.append((b, d + 1))
    return seen


def main():
    if not M.data:
        print("trace: docs/agent/methods.json not found (needs generic-graph or generic-methods earlier)")
        return
    EP = Endpoints()
    dba = load("db-access.json") or {}
    errs = load("errors.json") or []
    db = load("db.json") or {}
    touches = {r["name"].lower(): r.get("touches", []) for r in db.get("routines", [])}
    db_by_method = defaultdict(list)
    for obj, sites in dba.items():
        for s in sites:
            if s.get("anchor") and s["tech"] not in ("view text", "mention"):
                db_by_method[s["anchor"]].append((obj, s["op"], s["tech"]))
    err_by_method = defaultdict(list)
    for e in errs:
        if e.get("method"):
            err_by_method[e["method"]].append(e)
    # flows: method anchors referenced by each flow spec
    flows, flow_of = {}, defaultdict(set)
    fdir = os.path.join(DOCS, "_src", "workflows", "flows")
    name_idx = defaultdict(list)
    for a, x in M.data.items():
        name_idx[x["name"].lower()].append(a)
    for f in sorted(os.listdir(fdir)) if os.path.isdir(fdir) else []:
        if f.endswith(".flow.json"):
            try:
                spec = json.load(open(os.path.join(fdir, f), encoding="utf-8"))
            except ValueError:
                continue
            fid = spec.get("id") or f[:-10]
            flows[fid] = spec.get("title") or fid
            for s in spec.get("steps") or []:
                for r in ([s.get("ref")] if isinstance(s.get("ref"), str) else s.get("ref") or []):
                    if r.startswith("mth:"):
                        for a in name_idx.get(r[4:].lower(), []):
                            flow_of[a].add(fid)

    # ---- entry points
    entries = []  # {id, kind, label, handler, file, line, endpoint}
    for e in EP.rows:
        if e.get("handler") and e["handler"] in M.data:
            entries.append({"kind": "endpoint", "label": f"{e['verb']} {e['route']}", "handler": e["handler"], "file": e["file"], "line": e["line"],
                            "link": f"endpoints.md#{e['anchor']}"})
    ui = ui_triggers(EP)
    used = set()
    for u in ui:
        u["id"] = uid = slug("ui", u["file"], u["line"])
        n = 2
        while u["id"] in used:
            u["id"] = f"{uid}-{n}"
            n += 1
        used.add(u["id"])
        if u["handler"] and not u["endpoint"] and u["handler"] in M.data:  # code-behind / Blazor / desktop events are entry points
            entries.append({"kind": "UI event", "label": f"{u['label']} ({u['event']})", "handler": u["handler"], "file": u["file"], "line": u["line"],
                            "link": f"ui-map.md#{u['id']}"})
    job_files = {p for p in M.by_file if JOB_FILE.search(read(os.path.join(ROOT, p)))}
    for p in sorted(job_files):
        for _, a in M.by_file[p]:
            # only methods nothing in the code calls: the host / scheduler / broker invokes them
            if JOB_METHOD.search(M.data[a]["name"]) and not M.data[a].get("callers") and not re.search(r"(^|/)tests?/|Tests?\.\w+$", p):
                entries.append({"kind": "job / handler", "label": M.data[a]["name"], "handler": a, "file": p, "line": M.data[a]["line"], "link": ""})
    # framework-invoked code from the C# resolver (middleware, filters, behaviours, hosted services, hubs ...): no caller in code
    di = load("di.json") or {}
    hook = re.compile(r"\.(Invoke|InvokeAsync|On[A-Z]\w*|Handle|HandleAsync|ExecuteAsync|StartAsync|StopAsync|Configure|Validate\w*|"
                      r"BindModelAsync|SendAsync|\w+Executing\w*|\w+Executed\w*)$")
    pipe_types = {}
    for p in di.get("pipeline", []):
        pipe_types.setdefault(p["type"], p["kind"])
    hubs = {p["type"] for p in di.get("pipeline", []) if p["kind"] == "SignalR hub"}
    known = {e["handler"] for e in entries}
    for a, x in M.data.items():
        owner = x["name"].split(".", 1)[0] if "." in x["name"] else ""
        if owner in pipe_types and a not in known and not x.get("callers") and (hook.search(x["name"]) or owner in hubs):
            entries.append({"kind": pipe_types[owner], "label": x["name"], "handler": a, "file": x["file"], "line": x["line"],
                            "link": "dependency-injection.md#di-pipeline"})
    seen_e, uniq = set(), []
    for e in entries:
        k = (e["kind"], e["label"], e["handler"])
        if k not in seen_e:
            seen_e.add(k)
            uniq.append(e)
    entries = uniq
    ui_by_handler = defaultdict(list)
    for u in ui:
        if u["handler"]:
            ui_by_handler[u["handler"]].append(u)
    method_entries, table_writers, err_entries = defaultdict(list), defaultdict(set), defaultdict(set)
    for e in entries:
        e["id"] = eid = slug("ent", e["kind"], e["label"])
        n = 2
        while e["id"] in used:
            e["id"] = f"{eid}-{n}"
            n += 1
        used.add(e["id"])
        r = reach(e["handler"])
        e["reach"] = r
        e["db"] = sorted({x for a in r for x in db_by_method.get(a, [])})
        e["errors"] = [x for a in r for x in err_by_method.get(a, [])]
        e["flows"] = sorted({f for a in r for f in flow_of.get(a, set())})
        for a in r:
            method_entries[a].append(e)
        for obj, op, tech in e["db"]:
            if op not in ("read", "call"):
                table_writers[obj.lower()].add((e["id"], e["label"], op))
                for t in touches.get(obj.lower(), []):
                    table_writers[t.lower()].add((e["id"], e["label"], f"via {obj}"))
        for x in e["errors"]:
            err_entries[x["anchor"]].add((e["id"], e["label"]))

    def elink(e):
        return f"[{esc_text(e['label'])}](#{e['id']})"

    def dbs(items, cap=8):
        g = defaultdict(list)
        for o, op, t in items:
            g[(o, op)].append(t)
        keys = sorted(g)
        s = ", ".join(f"`{o}` {op} ({', '.join(sorted(set(g[(o, op)])))})" for o, op in keys[:cap])
        return (s + (f" +{len(keys) - cap}" if len(keys) > cap else "")) or "—"

    # ---- ui-map.md
    by_file = defaultdict(list)
    for u in ui:
        by_file[u["file"]].append(u)
    resolved = sum(1 for u in ui if u["handler"])
    out = ["# UI map", "",
           f"What each screen element calls: {len(ui)} UI triggers, {resolved} traced to a handler method. Follow a row from the "
           "element to the endpoint, the handler, and the database objects the handler reaches (through the call graph), "
           "to see what a button really does. Dynamic targets (built at run time) are marked.", "", '<a id="index"></a>', "",
           "| UI file | Triggers |", "| --- | ---: |"]
    out += [f"| [{esc_text(f)}](#{slug('uif', f)}) | {len(v)} |" for f, v in sorted(by_file.items())]
    for f, us in sorted(by_file.items()):
        out += ["", f'<a id="{slug("uif", f)}"></a>', "", f"## {f}", "", BACK, "",
                "| Element | Calls | Handler | Reaches (database) |", "| --- | --- | --- | --- |"]
        for u in sorted(us, key=lambda u: u["line"]):
            ep = u["endpoint"]
            calls = (f"[{esc_text(ep['verb'] + ' ' + ep['route'])}](endpoints.md#{ep['anchor']})" if ep else esc_text(u["target"] or "—"))
            h = u["handler"]
            r = reach(h) if h else set()
            items = sorted({x for a in r for x in db_by_method.get(a, [])})
            note = f" · {esc_text(u['note'])}" if u["note"] else ""
            hl = M.link(h) or (f"inline handler in {M.link(ep['registered_in'])}" if ep and ep.get("registered_in") in M.data else "—")
            out.append(f'| <a id="{u["id"]}"></a>**{esc_text(u["label"])}** ({u["element"]}, {u["event"]}) `{esc(u["file"])}:{u["line"]}` | '
                       f'{calls}{note} | {hl} | {dbs(items, 6)} |')
    write_page("ui-map.md", out)

    # ---- entry-points.md
    out = ["# Entry points", "",
           f"Where work starts ({len(entries)}: endpoints, UI event handlers, background jobs and message handlers) and everything "
           "each one reaches through the call graph: methods, database objects, errors a user can see, and documented flows. "
           "The reverse indexes answer debugging questions: which screens and endpoints run a method, who changes a table, "
           "where users meet an error. Static reachability: calls resolved from the code are followed (for C#, also dependency "
           "injection, overrides, messages, events, stored delegates, jobs and filters, see the dependency-injection reference); "
           "reflection and dispatch built at run time are not, so treat absences as \"not shown by the code\".", "", '<a id="index"></a>', "",
           "- [Entry points](#entries) · [Method → entry points](#by-method) · [Who changes each table](#by-table) · [Where users meet each error](#by-error)", "",
           '<a id="entries"></a>', "", "## Entry points", "", BACK, "",
           "| Entry point | Handler | Reaches | Database | Errors it can raise | Flows |", "| --- | --- | ---: | --- | --- | --- |"]
    for e in sorted(entries, key=lambda e: (e["kind"], e["label"].lower())):
        src = f"[{esc_text(e['label'])}]({e['link']})" if e["link"] else esc_text(e["label"])
        errs_s = ", ".join(f"[{esc_text(x['message'][:40])}](errors.md#{x['anchor']})" for x in e["errors"][:4]) + (f" +{len(e['errors']) - 4}" if len(e["errors"]) > 4 else "")
        fl = ", ".join(f"[{esc_text(flows[f])}](../workflows/flows/{f}.md)" for f in e["flows"]) or "—"
        out.append(f'| <a id="{e["id"]}"></a>{e["kind"]}: {src} | {M.link(e["handler"])} | {len(e["reach"])} methods | {dbs(e["db"])} | {errs_s or "—"} | {fl} |')
    out += ["", '<a id="by-method"></a>', "", "## Method → entry points", "", BACK, "",
            "Every method reached from at least one entry point: the entry points and UI triggers that run it, and the flows it belongs to.", "",
            "| Method | Started by | UI triggers | Flows |", "| --- | --- | --- | --- |"]
    for a in sorted(method_entries, key=lambda a: M.data[a]["name"].lower()):
        es = method_entries[a]
        uis = [u for e in es for u in ui_by_handler.get(e["handler"], []) if u["endpoint"]] + ui_by_handler.get(a, [])
        uis = list({(u["file"], u["line"]): u for u in uis}.values())
        ui_s = ", ".join(f"[{esc_text(u['label'])}](ui-map.md#{u['id']})" for u in uis[:4]) + (f" +{len(uis) - 4}" if len(uis) > 4 else "")
        fl = sorted(flow_of.get(a, set()) | {f for e in es for f in e["flows"]})
        out.append(f'| <a id="{slug("entm", a)}"></a>{M.link(a)} | {", ".join(elink(e) for e in es[:5])}{f" +{len(es) - 5}" if len(es) > 5 else ""} | '
                   f'{ui_s or "—"} | {", ".join(esc_text(flows[f]) for f in fl) or "—"} |')
    out += ["", '<a id="by-table"></a>', "", "## Who changes each table", "", BACK, "",
            "Entry points that insert, update, delete or merge rows, directly or through a procedure that touches the table.", "",
            "| Object | Changed by |", "| --- | --- |"]
    for t in sorted(table_writers):
        ws = sorted(table_writers[t], key=lambda w: w[1].lower())
        out.append(f"| `{esc(t)}` | " + ", ".join(f"[{esc_text(lbl)}](#{i}) ({esc_text(op)})" for i, lbl, op in ws[:8]) + (f" +{len(ws) - 8}" if len(ws) > 8 else "") + " |")
    out += ["", '<a id="by-error"></a>', "", "## Where users meet each error", "", BACK, "",
            "| Error | Raised in | Reached from |", "| --- | --- | --- |"]
    for x in errs:
        if x.get("method") and err_entries.get(x["anchor"]):
            es = sorted(err_entries[x["anchor"]], key=lambda w: w[1].lower())
            out.append(f"| [{esc_text(x['message'][:70])}](errors.md#{x['anchor']}) | {M.link(x['method'])} | "
                       + ", ".join(f"[{esc_text(lbl)}](#{i})" for i, lbl in es[:6]) + (f" +{len(es) - 6}" if len(es) > 6 else "") + " |")
    write_page("entry-points.md", out)

    # ---- machine-readable
    agent = os.path.join(DOCS, "agent")
    ej = [{k: (sorted(v) if isinstance(v, set) else v) for k, v in e.items() if k != "reach"} | {"reaches": len(e["reach"])} for e in entries]
    open(os.path.join(agent, "entry-points.json"), "w", encoding="utf-8", newline="\n").write(json.dumps({"entries": ej, "ui": [dict(u, endpoint=u["endpoint"] and u["endpoint"]["anchor"]) for u in ui]},
                                                                                           ensure_ascii=False, indent=1, default=str))
    for a, x in M.data.items():
        x["entry_points"] = [e["label"] for e in method_entries.get(a, [])][:10]
        x["flows"] = sorted(flow_of.get(a, set()) | {f for e in method_entries.get(a, []) for f in e["flows"]})
    open(os.path.join(agent, "methods.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(M.data, ensure_ascii=False, separators=(",", ":")))
    print(f"trace: {len(ui)} UI triggers ({resolved} to a handler), {len(entries)} entry points, "
          f"{len(method_entries)} methods reachable, {len(table_writers)} objects with writers")


if __name__ == "__main__":
    main()
