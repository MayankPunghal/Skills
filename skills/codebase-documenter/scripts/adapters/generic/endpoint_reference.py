"""Network endpoints: every outbound destination (inbound listener) the code and its configuration name, for firewall,
security-group, NAT and VPN allow-lists and for integration documentation. Detection lives in scripts/network_endpoints.py
(shared with migration-assessment).

Writes docs/reference/network-endpoints.md (anchors net-<host>-<port>, net-in-<n>, net-client-<n>) and
docs/agent/network.json:
  outbound   destination host, port, protocol, kind (internal / external / public IP), where it is defined (URL literal,
             config key, connection string, WCF client, UNC path) and the methods that read the key or hold the literal
  inbound    ports the applications listen on (launchSettings, Kestrel, ASPNETCORE_URLS / *_PORTS, Dockerfile EXPOSE,
             docker-compose, UseUrls / Listen in code, WCF services, IIS-hosted .svc / .asmx); routes are on endpoints.md
  clients    code that opens outbound connections (HttpClient, WCF, SMTP, FTP, Redis, RabbitMQ, Kafka, AWS / Azure SDKs ...)
             with the config keys next to it; a client with no key or literal gets its destination at run time
Names and hosts only: never a path, query string, user name or password.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import network_endpoints as NE  # noqa: E402
from _scan import BACK, DOCS, ROOT, Methods, esc, esc_text, options, project_of, read, slug, write_page  # noqa: E402

OPT = options("generic-endpoints")
KIND = {"internal": "Internal / on-premises", "external": "External service", "external-ip": "Public IP"}
SOURCE = {"url": "URL", "config-host": "host setting", "connection-string": "connection string", "wcf-client": "WCF client endpoint",
          "unc-path": "UNC path", "session-state": "session state setting"}
MAX_USERS = 8


def main():
    net = NE.scan(ROOT, OPT.get("exclude_dirs"))
    M = Methods()

    comp = os.path.join(DOCS, "reference", "components.md")
    cls_anchors = set(re.findall(r'<a id="(cls-[^"]+)"', read(comp))) if os.path.exists(comp) else set()

    def where(f, ln):
        a = M.enclosing(f, ln)
        if a and M.data[a].get("file") == f and M.data[a].get("line", 0) <= ln:
            return M.link(a, "")
        # constructors, field initialisers and top-level statements are not in the method map: link the enclosing class
        names = re.findall(r"\b(?:class|record|struct|module)\s+(\w+)", "\n".join(read(os.path.join(ROOT, f)).splitlines()[:ln]))
        c = slug("cls", f, names[-1]) if names else ""
        return f"[{esc(names[-1])}](components.md#{c}) (`{esc(f.split('/')[-1])}:{ln}`)" if c in cls_anchors else f"`{esc(f)}:{ln}`"

    dests = NE.destinations(net)
    # literal URLs in code: the method holding them uses the destination
    for g in dests:
        lit = [e.rsplit(":", 1) for e in g["evidence"]]
        g["code_users"] = sorted({(f, int(ln)) for f, ln in lit if os.path.splitext(f)[1].lower() in NE.CODE})
    out = ["# Network endpoints", "",
           "Every destination the code and its configuration call out to, and every port the applications listen on: the input for "
           "firewall rules, security groups, NAT / egress allow-lists, VPN routes and partner IP allow-lists. Hosts come from URL "
           "literals, host settings, connection strings, WCF client endpoints and UNC paths (scheme, host and port only, never paths, "
           "query strings or credentials). A destination built at run time is not visible; the outbound call sites below show where "
           "the code connects, with the configuration keys it reads. Ports in brackets are protocol defaults, not read from the code.", "",
           '<a id="index"></a>', "",
           f"- [Outbound destinations](#net-outbound): {len(dests)} "
           f"({', '.join(f'{KIND[k].lower()} {v}' for k, v in Counter(g['kind'] for g in dests).most_common()) or 'none'})",
           f"- [Inbound listeners](#net-inbound): {len(net['inbound'])}",
           f"- [Outbound call sites](#net-clients): {len(net['clients'])}", "",
           '<a id="net-outbound"></a>', "", "## Outbound destinations", "", BACK, ""]
    if dests:
        out += ["| Role | Destination | Port | Protocol | Kind | Defined in (how it is configured) | Used by | Evidence |",
                "| --- | --- | ---: | --- | --- | --- | --- | --- |"]
        for g in dests:
            port = (f"({g['port']})" if g["port_default"] else str(g["port"])) if g["port"] else "?"
            defined = ", ".join([f"`{esc(k)}`" for k in g["keys"]] + [SOURCE.get(s, s) for s in g["sources"] if s != "url" or not g["keys"]])
            users = [where(f, ln) for f, ln in (g["users"] + g["code_users"])]
            users = list(dict.fromkeys(users))
            shown = ", ".join(users[:MAX_USERS]) + (f" +{len(users) - MAX_USERS} more" if len(users) > MAX_USERS else "")
            ev = ", ".join(f"`{esc(e)}`" for e in g["evidence"][:3]) + (f" +{len(g['evidence']) - 3}" if len(g["evidence"]) > 3 else "")
            out.append(f'| {esc_text(g.get("role", "-"))} | <a id="{slug("net", g["host"], g["port"] or "x")}"></a>`{esc(g["host"])}` | {port} | {g["scheme"]} | {KIND[g["kind"]]} | '
                       f"{defined} | {shown or '_not traced to code (read through configuration binding or at run time)_'} | {ev} |")
    else:
        out.append("_No outbound destination is named in the code or configuration._")
    if net.get("drives"):
        out += ["", "**Drive letters other than C:** (often mapped network drives: they do not exist in a container or on a new host; ask what "
                "each maps to):", "", "| Drive | Config key | Evidence |", "| --- | --- | --- |"]
        out += [f"| `{d['drive']}` | {('`' + esc(d['key']) + '`') if d['key'] else '_code literal_'} | `{esc(d['file'])}:{d['line']}` |" for d in net["drives"]]
    out += ["", '<a id="net-inbound"></a>', "", "## Inbound listeners", "", BACK, "",
            "Ports opened by the applications. Development-only sources (launchSettings, IIS Express) show local ports; production "
            "ports come from the container / host configuration. HTTP routes behind each port are on the [endpoints](endpoints.md) page.", ""]
    if net["inbound"]:
        out += ["| Project | Port | Protocol | Source | Evidence |", "| --- | ---: | --- | --- | --- |"]
        for n, e in enumerate(net["inbound"], 1):
            out.append(f'| <a id="net-in-{n}"></a>{esc_text(e.get("app") or project_of(e["file"]))} | {e["port"] or "?"} | {e["scheme"]} | {esc_text(e["source"])} | '
                       f'`{esc(e["file"])}:{e["line"]}` |')
    else:
        out.append("_No listener configuration found._")
    out += ["", '<a id="net-clients"></a>', "", "## Outbound call sites", "", BACK, "",
            "Code that opens an outbound connection. **Destination** is the configuration key or literal named next to the call; "
            "_run time_ means the address is passed in from elsewhere (options class, constructor argument, database): follow the "
            "method to find it.", ""]
    if net["clients"]:
        by_tech = Counter(c["tech"] for c in net["clients"])
        out += ["Technologies: " + ", ".join(f"{t} {v}" for t, v in by_tech.most_common()), "",
                "| Method | Technology | Destination | Evidence |", "| --- | --- | --- | --- |"]
        key_host = defaultdict(set)
        for g in dests:
            for k in g["keys"]:
                key_host[k].add(f"{g['host']}:{g['port'] or '?'}")
        for n, c in enumerate(net["clients"], 1):
            dest = [f"`{esc(k)}`" + (f" → {', '.join(sorted(key_host[k]))}" if key_host.get(k) else "") for k in c["keys"]]
            dest += [f"`{esc(u)}`" for u in c["literals"]]
            out.append(f'| <a id="net-client-{n}"></a>{where(c["file"], c["line"])} | {c["tech"]} | {", ".join(dest) or "_run time_"} | '
                       f'`{esc(c["file"])}:{c["line"]}` |')
    else:
        out.append("_No outbound client construction found (HttpClient, WCF, SMTP, FTP, message brokers, cloud SDKs, sockets)._")
    write_page("network-endpoints.md", out)
    os.makedirs(os.path.join(DOCS, "agent"), exist_ok=True)
    doc = {"outbound": [{k: v for k, v in g.items() if k != "code_users"} | {"anchor": slug("net", g["host"], g["port"] or "x")} for g in dests],
           "inbound": net["inbound"], "clients": net["clients"], "drives": net.get("drives", [])}
    open(os.path.join(DOCS, "agent", "network.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(doc, ensure_ascii=False, indent=1, default=list))
    kinds = Counter(g["kind"] for g in dests)
    print(f"network-endpoints: {len(dests)} outbound destinations ({', '.join(f'{k} {v}' for k, v in kinds.most_common()) or 'none'}), "
          f"{len(net['inbound'])} inbound listeners, {len(net['clients'])} outbound call sites in {net['files_scanned']} files")


if __name__ == "__main__":
    main()
