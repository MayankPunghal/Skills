"""Dependency injection and indirect calls (C#), from graphify-out/csharp-resolve.json written by scripts/csharp_resolve.py.

Writes docs/reference/dependency-injection.md (anchors di-…) and docs/agent/di.json:
  summary          containers, host applications, registrations by lifetime, the call edges added to the graph by kind
  composition      per host application: every registration (service, implementation, lifetime, how, key, where, via module)
  services         per service type: implementations (registered and merely implementing), consumers, lifetime per host
  dependencies     per class: what its constructor / primary constructor / [Inject] / [FromServices] / @inject receives
  messages         per message type: kind, handlers, the methods that send / publish it
  pipeline         middleware, filters (global and by attribute), endpoint filters, pipeline behaviours, startup filters,
                   validators, interceptors, hosted services, hubs: code that runs without a visible caller
  jobs / events    background jobs (Hangfire, Quartz) and event / delegate subscriptions
  options          options classes and the configuration sections bound to them
  findings         missing registration, captive dependency, multiple registrations, service locator, message issues
  limits           reflection and dynamic sites the resolver cannot follow
Run after the method map (it links methods), so build_site.py runs it with the late adapters.
"""
import json
import os
import re
from collections import Counter, defaultdict

from _scan import BACK, CFG, DOCS, Methods, esc, esc_text, slug, write_page
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

GRAPH_DIR = CFG.get("graph_dir", "graphify-out")
M = Methods()
EDGE_MEANING = {
    "di registration": "interface / abstract service method → the implementation the container is told to build",
    "di decorator": "service method → the decorator wrapping it (Scrutor Decorate)",
    "implementation (no registration found)": "interface method → each implementer (no registration seen; one of them runs)",
    "only implementation": "interface method → its only implementation (no registration seen)",
    "override": "abstract / virtual method → each override in a derived class",
    "keyed service": "method → the keyed implementation its class asked for ([FromKeyedServices])",
    "message": "method sending / publishing a message → each handler of that message",
    "local variable": "call on a local variable whose type is known (foreach item, GetRequiredService<T>(), new T(), cast)",
    "partial class field": "call on a field declared in another file of the same partial class",
    "service locator": "GetRequiredService<T>().Method() → T.Method",
    "event": "method raising an event / invoking a delegate → each subscribed handler",
    "method group": "method passing another method as a value (Select(Format), MapGet(\"/x\", Health), Task.Run(Work))",
    "background job": "method enqueuing / scheduling a job → the job method (runs later, on a worker)",
    "redirect": "MVC action → the action it redirects to (RedirectToAction)",
    "filter": "action → the filter hooks that run around it ([ServiceFilter] / [TypeFilter] / filter attributes)",
}


def anchors(page):
    p = os.path.join(DOCS, "reference", page)
    return set(re.findall(r'<a id="([^"]+)"', open(p, encoding="utf-8").read())) if os.path.exists(p) else set()


def main():
    src = os.path.join(GRAPH_DIR, "csharp-resolve.json")
    if not os.path.exists(src):
        print("dependency-injection: graphify-out/csharp-resolve.json not found (run code_graph.py build, or csharp_resolve.py)")
        return
    d = json.load(open(src, encoding="utf-8"))
    types = d.get("types", {})
    comp = anchors("components.md")

    def cls(name):
        t = types.get(name)
        if t:
            a = slug("cls", t["file"], name)
            if a in comp:
                return f"[{esc(name)}](components.md#{a})"
        return f"`{esc(name)}`"

    def svc(name):
        return f"[{esc(name)}](#{slug('di', name)})" if name in svc_names else cls(name)

    def method_link(file, line, label):
        a = M.enclosing(file, line + 1) if line else None
        return M.link(a) if a else f"`{esc(label)}`"

    def src_ref(file, line):
        return f"`{esc(file)}:{line}`"

    regs = d.get("registrations", [])
    cons = d.get("consumers", [])
    msgs = d.get("messages", {})
    svc_names = {r["service"] for r in regs} | {x.get("needs") or x["type"] for c in cons for x in c["params"]
                                                 if types.get(x.get("needs") or x["type"], {}).get("kind") == "interface"}
    hosts = sorted({h for r in regs for h in r.get("hosts", [])})
    out = ["# Dependency injection and indirect calls", "",
           "How objects are wired together and which calls happen without a visible caller: container registrations, constructor "
           "dependencies, message handlers, the request pipeline, background jobs, events and delegates. Read from the C# source "
           "by `csharp_resolve.py`; the calls it resolves are added to the code graph, so the method map, entry points, test map "
           "and flows follow them. Resolved calls are inferred from the code (registrations, types, names); confirm a surprising "
           "one in the source.", "", '<a id="index"></a>', "",
           "| Section | Items |", "| --- | ---: |"]
    sections = [("Summary", "di-summary", 1), ("Framework features", "di-features", len(d.get("notes", []))),
                ("Composition roots", "di-hosts", len(regs)),("Services", "di-services", len(svc_names)),
                ("Constructor dependencies", "di-dependencies", len(cons)), ("Messages", "di-messages", len(msgs)),
                ("Request pipeline and implicit calls", "di-pipeline", len(d.get("pipeline", []))),
                ("Background jobs", "di-jobs", len(d.get("jobs", []))), ("Events and delegates", "di-events", len(d.get("events", []))),
                ("Options bindings", "di-options", len(d.get("options", []))), ("Convention scans", "di-conventions", len(d.get("conventions", []))),
                ("Partial types", "di-partials", len(d.get("partials", {}))),
                ("Findings", "di-findings", len(d.get("findings", []))), ("Limits", "di-limits", len(d.get("reflection", [])))]
    out += [f"| [{t}](#{a}) | {n} |" for t, a, n in sections]

    # summary
    lt = Counter(r["lifetime"] for r in regs)
    out += ["", '<a id="di-summary"></a>', "", "## Summary", "", BACK, "",
            f"- C# files scanned: {d.get('files_scanned', 0)}",
            "- Containers: " + (", ".join(f"{k} ({v})" for k, v in sorted(d.get("containers", {}).items())) or "none found"),
            "- Host applications (where registrations run): " + (", ".join(f"`{esc(h)}`" for h in hosts) or "none"),
            "- Registrations by lifetime: " + (", ".join(f"{k} {v}" for k, v in lt.most_common()) or "none"),
            "- Registration modules: " + (", ".join(f"`{esc(m)}`" for m in d.get("composition", {}).get("modules", [])) or "none"), "",
            "Calls added to the code graph (graphify cannot see these from the syntax alone):", "",
            "| Kind | Calls | Meaning |", "| --- | ---: | --- |"]
    out += [f"| {esc(k)} | {v} | {esc(EDGE_MEANING.get(k, ''))} |" for k, v in sorted(d.get("edges_added", {}).items(), key=lambda kv: -kv[1])]
    if d.get("skipped_wide"):
        out += ["", "Interfaces with more implementers than `adapter_options.generic-di.max_implementers` and no registration were not "
                "expanded: " + ", ".join(f"{cls(x['type'])} ({x['implementers']})" for x in d["skipped_wide"][:30]) + "."]

    # framework features switched on in the composition roots
    out += ["", '<a id="di-features"></a>', "", "## Framework features", "", BACK, "",
            "Framework and library services each application switches on (`services.Add…` calls other than plain registrations): "
            "session, caching, health checks, authentication, SignalR, MediatR, message buses, validators …", "",
            "| Feature | Application | Call | Where |", "| --- | --- | --- | --- |"]
    out += [f"| {esc(n['kind'])} | `{esc(n.get('host') or '')}` | `{esc(n['text'][:120])}` | {src_ref(n['file'], n['line'])} |"
            for n in sorted(d.get("notes", []), key=lambda n: (n.get("host") or "", n["kind"]))]

    # composition roots
    out += ["", '<a id="di-hosts"></a>', "", "## Composition roots", "", BACK, "",
            "Every registration, grouped by the application that runs it. Registrations inside a registration module (an extension "
            "method such as `AddInfrastructure`, or a container module class) count for every application that calls the module."]
    by_host = defaultdict(list)
    for r in regs:
        for h in r.get("hosts") or ["?"]:
            by_host[h].append(r)
    for h in sorted(by_host):
        out += ["", f'<a id="{slug("di-host", h)}"></a>', "", f"### {esc(h)}", "",
                "| Service | Implementation | Lifetime | How | Key | Registered at |", "| --- | --- | --- | --- | --- | --- |"]
        for r in sorted(by_host[h], key=lambda r: (r["service"].lower(), r["file"], r["line"])):
            via = f" via `{esc(r['module'])}`" if r.get("module") else ""
            impl = "(generated client)" if r.get("external") else cls(r["impl"]) if r["impl"] != r["service"] else "itself"
            out.append(f"| {svc(r['service'])} | {impl} | {esc(r['lifetime'])} | {esc(r['how'])} ({esc(r['container'])}) | "
                       f"{esc(r['key'] or '')} | {src_ref(r['file'], r['line'])}{via} |")

    # services
    impl_of = defaultdict(list)
    for r in regs:
        impl_of[r["service"]].append(r)
    consumers_of = defaultdict(list)
    for c in cons:
        for x in c["params"]:
            consumers_of[x.get("needs") or x["type"]].append((c, x))
    implementers = defaultdict(set)
    for n, t in types.items():
        for b in t.get("bases", []):
            implementers[b].add(n)
    out += ["", '<a id="di-services"></a>', "", "## Services", "", BACK, "",
            "One row per service type: what the container builds for it, other classes implementing it that are never registered, "
            "and the classes that receive it.", "", "| Service | Implementations (lifetime · host) | Also implemented by | Consumers |",
            "| --- | --- | --- | --- |"]
    svc_rows = []
    for s in sorted(svc_names, key=str.lower):
        rs = impl_of.get(s, [])
        impls = "; ".join(dict.fromkeys(f"{cls(r['impl']) if r['impl'] != s else 'itself'} ({esc(r['lifetime'])}"
                                        + (f", key {esc(r['key'])}" if r.get("key") else "") + f" · {esc(', '.join(r.get('hosts', [])))})"
                                        for r in rs)) or "**not registered**"
        others = sorted(implementers.get(s, set()) - {r["impl"] for r in rs})
        users = sorted({c["class"] for c, _ in consumers_of.get(s, [])})
        out.append(f'| <a id="{slug("di", s)}"></a>{cls(s)} | {impls} | {", ".join(cls(o) for o in others[:10]) or "—"} | '
                   f'{", ".join(cls(u) for u in users[:15]) + (f" +{len(users) - 15} more" if len(users) > 15 else "") or "—"} |')
        svc_rows.append({"service": s, "anchor": slug("di", s), "kind": types.get(s, {}).get("kind"), "file": types.get(s, {}).get("file"),
                         "registrations": [{k: r.get(k) for k in ("impl", "lifetime", "key", "how", "container", "hosts", "file", "line", "module")}
                                           for r in rs], "unregistered_implementers": others, "consumers": users})

    # dependencies
    lifetime_of = {}
    for r in regs:
        lifetime_of.setdefault(r["impl"], r["lifetime"])
    out += ["", '<a id="di-dependencies"></a>', "", "## Constructor dependencies", "", BACK, "",
            "What each class receives from the container. Framework types (loggers, options, HttpClient …) are listed too; they are "
            "registered by the framework.", "", "| Class | Lifetime | Receives |", "| --- | --- | --- |"]
    for c in sorted(cons, key=lambda c: (c["class"].lower(), c["file"])):
        recv = ", ".join(f"{svc(x.get('needs') or x['type']) if (x.get('needs') or x['type']) in svc_names else '`' + esc(x.get('display') or x['type']) + '`'}"
                         + (f" key `{esc(x['key'])}`" if x.get("key") else "") + ("" if x["via"] == "constructor" else f" ({esc(x['via'])})")
                         for x in c["params"])
        out.append(f'| <a id="{slug("di-cls", c["class"], c["file"])}"></a>{cls(c["class"]) if not c.get("view") else "`" + esc(c["file"]) + "`"} | '
                   f'{esc(lifetime_of.get(c["class"], "—"))} | {recv} |')

    # messages
    out += ["", '<a id="di-messages"></a>', "", "## Messages", "", BACK, "",
            "Requests, commands, queries, notifications and events dispatched through a mediator or message bus, with their handlers "
            "and the methods that send them. The graph links each sender to each handler.", "",
            "| Message | Kind | Handlers | Sent / published from |", "| --- | --- | --- | --- |"]
    for name in sorted(msgs, key=str.lower):
        m = msgs[name]
        hs = ", ".join(f"{cls(h['class'])}.{method_link(h['file'], h['line'] - 1, h['method'])}" for h in m["handlers"])
        ss = ", ".join(dict.fromkeys(f"{method_link(s['file'], s['line'], (s.get('cls') or '') + '.' + s['method'])} ({esc(s['verb'])})"
                                     for s in m.get("senders", []))) or "— (not found in code)"
        out.append(f'| <a id="{slug("di-msg", name)}"></a>{cls(name)} | {esc(m.get("kind") or "message")} | {hs} | {ss} |')

    # pipeline
    out += ["", '<a id="di-pipeline"></a>', "", "## Request pipeline and implicit calls", "", BACK, "",
            "Code the framework runs without a visible caller: around every request (middleware, global filters, startup filters), "
            "around chosen actions (filter attributes), around every mediator request (pipeline behaviours), or on its own "
            "(hosted services, hubs). Order of middleware is the order of the `Use…` calls in the host's startup code.", "",
            "| Kind | Type | Applies to | Where |", "| --- | --- | --- | --- |"]
    for p in sorted(d.get("pipeline", []), key=lambda p: (p["kind"], p["type"])):
        where = src_ref(p["file"], p["line"]) + (" (declared; registration not found)" if p.get("declared_only") and p["kind"] in ("middleware", "MVC filter") else "")
        out.append(f"| {esc(p['kind'])} | {cls(p['type'])} | {esc(p.get('applies_to') or 'all requests' if p['kind'] in ('middleware', 'global filter', 'startup filter') else p.get('applies_to') or '—')} | {where} |")

    # jobs, events
    out += ["", '<a id="di-jobs"></a>', "", "## Background jobs", "", BACK, "", "| Job | API | Scheduled from |", "| --- | --- | --- |"]
    for j in d.get("jobs", []):
        out.append(f"| {cls(j['type'])}.{esc(j['method'])} | {esc(j['api'])} | {method_link(j['file'], j['line'], (j.get('cls') or '') + '.' + (j.get('caller') or '?'))} ({src_ref(j['file'], j['line'])}) |")
    out += ["", '<a id="di-events"></a>', "", "## Events and delegates", "", BACK, "",
            "Subscriptions (`+=`) and delegate assignments (`=`) to methods. The graph links the method that raises the event or "
            "invokes the delegate to each handler.", "", "| Event / delegate | Handler | Subscribed in |", "| --- | --- | --- |"]
    for e in d.get("events", []):
        out.append(f"| `{esc(e['member'])}` ({'subscription' if e['op'] == '+=' else 'assignment'}) | {cls(e['cls'])}.`{esc(e['handler'])}` | {src_ref(e['file'], e['line'])} |")

    # options, conventions
    out += ["", '<a id="di-options"></a>', "", "## Options bindings", "", BACK, "",
            "Options classes bound to configuration sections (see the configuration reference for the keys).", "",
            "| Options class | Section | How | Where |", "| --- | --- | --- | --- |"]
    out += [f"| {cls(o['type'])} | `{esc(o['section'] or '—')}` | {esc(o['how'])} | {src_ref(o['file'], o['line'])} |" for o in d.get("options", [])]
    out += ["", '<a id="di-conventions"></a>', "", "## Convention scans", "", BACK, "",
            "Assembly scans register classes by rule instead of one by one. The classes the rule matches in this repository are "
            "listed when the rule could be read (AssignableTo, name filters); otherwise the scan is unresolved.", "",
            "| Scan | Lifetime | Classes matched | Where |", "| --- | --- | --- | --- |"]
    for c in d.get("conventions", []):
        out.append(f"| `{esc(c['text'][:160])}` | {esc(c.get('lifetime', '?'))} | {', '.join(cls(x) for x in c.get('resolved', [])[:20]) or 'unresolved'} | {src_ref(c['file'], c['line'])} |")

    # partial types
    out += ["", '<a id="di-partials"></a>', "", "## Partial types", "", BACK, "",
            "Classes (and structs, records, interfaces) whose code is split over several files with `partial`: generated code next "
            "to hand-written code (designer files, source generators, EF scaffolding), or one large class cut into parts. Read every "
            "part before describing the class; fields, constructors and base types declared in one part apply to all of them.", "",
            "| Type | Part (file) | Base types declared here | Methods declared here |", "| --- | --- | --- | --- |"]
    for n, parts in sorted(d.get("partials", {}).items(), key=lambda kv: kv[0].lower()):
        for k, p in enumerate(parts):
            ms = p.get("methods", [])
            first = f'<a id="{slug("di-partial", n)}"></a>{cls(n.split(".")[-1])}' if k == 0 else ""
            out.append(f'| {first} | '
                       f'{src_ref(p["file"], p["line"])} | {", ".join(cls(b) for b in p.get("bases", [])) or "—"} | '
                       f'{", ".join("`" + esc(m) + "`" for m in ms[:20]) + (f" +{len(ms) - 20} more" if len(ms) > 20 else "") or "—"} |')

    # findings
    out += ["", '<a id="di-findings"></a>', "", "## Findings", "", BACK, "",
            "Wiring problems visible in the code. Verify each before reporting it: a registration made outside this repository "
            "(another package, runtime configuration) would clear a missing-registration finding.", "",
            "| Severity | Kind | Detail | Source |", "| --- | --- | --- | --- |"]
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    for i, f in enumerate(sorted(d.get("findings", []), key=lambda f: (order.get(f["severity"], 9), f["kind"]))):
        f["anchor"] = slug("di-find", i + 1)
        out.append(f'| <a id="{slug("di-find", i + 1)}"></a>{f["severity"]} | {esc(f["kind"])} | {esc_text(f["text"])} | {src_ref(f["file"], f["line"])} |')

    # limits
    out += ["", '<a id="di-limits"></a>', "", "## Limits", "", BACK, "",
            "Calls decided at run time that no static reading can resolve: reflection, `Activator.CreateInstance`, types loaded "
            "by name, `dynamic`, containers configured from XML / JSON files, and proxies. The sites found are listed so they can "
            "be checked by hand.", "", "| What | Where |", "| --- | --- |"]
    out += [f"| `{esc(r['text'])}` | {src_ref(r['file'], r['line'])} |" for r in d.get("reflection", [])[:200]]
    write_page("dependency-injection.md", out)

    agent = os.path.join(DOCS, "agent")
    os.makedirs(agent, exist_ok=True)
    slim = {k: v for k, v in d.items() if k != "types"}
    slim["services"] = svc_rows
    slim["anchors"] = {"hosts": {h: slug("di-host", h) for h in by_host}, "messages": {n: slug("di-msg", n) for n in msgs},
                       "sections": {a: t for t, a, _ in sections}}
    open(os.path.join(agent, "di.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(slim, ensure_ascii=False, separators=(",", ":")))
    stat("di", registrations=len(regs), hosts=len(hosts), services=len(svc_names), findings=len(d.get("findings", [])))
    print(f"dependency-injection: {len(regs)} registrations in {len(hosts)} hosts, {len(svc_names)} services, {len(cons)} classes with "
          f"dependencies, {len(msgs)} messages, {len(d.get('pipeline', []))} pipeline items, {len(d.get('findings', []))} findings, "
          f"{sum(d.get('edges_added', {}).values())} graph calls added")


if __name__ == "__main__":
    main()
