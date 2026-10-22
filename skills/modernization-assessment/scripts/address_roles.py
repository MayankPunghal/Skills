"""What each internal address most likely is (Redis, SQL Server, file share ...), with a confidence, from the repositories only.

    python <skill>/scripts/address_roles.py

Reads assessment/solutions/index.json (the internal addresses and names each solution uses), then finds every place the estate roots name
that address and reads the SETTING NAME, the port and the connection-string shape around it. Values are never stored or printed: the
output keeps key names and ports only. Writes assessment/infra/address_roles.json.

Confidence: HIGH  = the setting name or connection string says it (RedisConnection, Mongo_..., Initial Catalog ...) and nothing contradicts it
            MEDIUM = only a well-known port, a URL scheme, or a weak setting name points to it
            MIXED  = the evidence disagrees (for example a Mongo setting with the SQL Server port): check with DevOps
            UNKNOWN = no setting name, port or scheme to read
It is an inference from static text: nothing was run, and no server was asked.
Run after solutions.py and map_infra.py (the devops count reads assessment/infra/servers.json, the public IPs read assessment/scan/<repo>.json).
"""
import os
import re

from _common import skip_dir, OUT, load_config, load_state, mark_step, read_json, utf8_stdout, write_json

EXT = (".config", ".json", ".xml", ".cs", ".ini", ".txt", ".yml", ".yaml", ".settings", ".vb", ".aspx", ".asmx", ".js", ".env", ".properties", ".cshtml")
SKIP = {".git", "node_modules", "bin", "obj", "packages"}

KEY_ROLE = [(r"redis", "Redis"), (r"memcach|enyim", "Memcached"), (r"mongo", "MongoDB"), (r"elastic|opensearch|eshost|esurl", "Elasticsearch"),
            (r"aerospike", "Aerospike"), (r"smtp|mailserver|mailhost", "SMTP"), (r"ftp", "FTP"), (r"rabbit|amqp", "RabbitMQ"), (r"kafka", "Kafka"),
            (r"proxy", "Proxy"), (r"syncserver|sync", "Sync service"), (r"sql", "SQL Server")]
WEAK_KEY_ROLE = [(r"share|unc|exportpath|filepath|folder|directory", "File share"), (r"loadbalanc", "Load balancer"), (r"url|endpoint|baseaddress|api", "Web service / API")]
PORT_ROLE = {1433: "SQL Server", 6379: "Redis", 11211: "Memcached", 27017: "MongoDB", 9200: "Elasticsearch", 9300: "Elasticsearch", 25: "SMTP", 465: "SMTP",
             587: "SMTP", 21: "FTP", 22: "SFTP", 5672: "RabbitMQ", 9092: "Kafka", 3128: "Proxy", 445: "File share", 80: "Web service / API", 443: "Web service / API",
             8080: "Web service / API", 8443: "Web service / API"}
LIST_ROLE = {"Redis": "redis", "MongoDB": "mongodb", "SQL Server": "sql-server", "Elasticsearch": "elasticsearch", "Memcached": "memcached", "Aerospike": "aerospike",
             "SMTP": "smtp", "FTP": "ftp", "Kafka": "kafka", "Proxy": "proxy", "Sync service": "sync", "Load balancer": "load-balancer"}
STORES = {"Redis", "MongoDB", "SQL Server", "Elasticsearch", "Memcached", "Aerospike", "SMTP", "FTP", "Kafka", "RabbitMQ", "Proxy", "Sync service"}


GENERIC_KEYS = {"connectionstring", "host", "address", "value", "uri", "url", "baseurl", "this.url", "port", "server", "endpoint"}
CONTEXT_WORDS = [(r"aerospike", "Aerospike"), (r"redis", "Redis"), (r"memcach|enyim", "Memcached"), (r"mongo", "MongoDB"), (r"elasticsearch|opensearch", "Elasticsearch"),
                 (r"rabbitmq", "RabbitMQ"), (r"kafka", "Kafka")]


def key_of(line, start, end=None):
    """The setting name on this line that holds the address (name only)."""
    end = start if end is None else end
    before = line[:start]
    for rx in (r"""(?:key|name)\s*=\s*["']([^"']{2,80})["'][^<>]*$""", r"""["']([A-Za-z_][\w.:/\-]{1,80})["']\s*:\s*["'][^"']*$""",
               r"""^\s*([A-Za-z_][\w.\-]{1,80})\s*[=:]\s*["']?[^"']*$""", r"""\b([A-Za-z_][\w.]{2,60})\s*=\s*["'][^"']*$"""):
        m = re.search(rx, before)
        if m:
            found = m.group(1)
            break
    else:
        found = ""
    if not found or found.lower() in GENERIC_KEYS:  # <add connectionString="..." name="Mongo_..." />: the name can come after the value
        m = re.search(r"""\b(?:name|key)\s*=\s*["']([^"']{2,80})["']""", line[end:])
        if m:
            return m.group(1)
    return found


def hit_roles(line, start, end, key):
    k = key.lower()
    low = line.lower()
    explicit = None
    weak = None
    if re.search(r"initial catalog|integrated security|trusted_connection|data source\s*=|server\s*=.*database\s*=", low):
        explicit = "SQL Server"
    elif "mongodb://" in low:
        explicit = "MongoDB"
    elif re.search(r"redis://|,\s*abortconnect|connecttimeout", low):
        explicit = "Redis"
    for rx, role in KEY_ROLE:
        if explicit is None and re.search(rx, k):
            explicit = role
    for rx, role in WEAK_KEY_ROLE:
        if weak is None and re.search(rx, k):
            weak = role
    pm = re.match(r"[:,](\d{2,5})\b", line[end:])
    port = int(pm.group(1)) if pm else None
    if port is None:
        pk = re.search(r"""(?:port)["']?\s*[=:]\s*["']?(\d{2,5})""", line[end:end + 80].lower())
        port = int(pk.group(1)) if pk else None
    scheme = re.search(r"(https?|ftps?|sftp|smtps?)://[^\s\"']*$", line[:end].lower())
    sch = None
    if scheme:
        sch = "Web service / API" if scheme.group(1).startswith("http") else ("FTP" if "ftp" in scheme.group(1) else "SMTP")
    return explicit, weak or sch, port, PORT_ROLE.get(port)


def context_role(fname, lines, i):
    """A store named in the file name or in the 3 lines either side (weak evidence: MEDIUM at best)."""
    near = (fname + " " + " ".join(l[:300] for l in lines[max(0, i - 3):i + 4])).lower()
    for rx, role in CONTEXT_WORDS:
        if re.search(rx, near):
            return role
    return None


PUBLIC_RULES = [(r"<proxy\b", "Outbound proxy (suppliers may allow-list it)"), (r"influx", "Metrics server (InfluxDB)"), (r"allowedip|allowlist|whitelist|clientip", "Allow-listed or client IP in a setting"),
                (r"8\.8\.8\.8", "Internet connectivity test (Google DNS)"), (r"<url>|\burl\b|https?://", "Supplier or partner endpoint"), (r"//", "Mentioned in a code comment only")]


def public_ips(repos):
    """Public IPs in the scans: type, role from the surrounding setting name (never the values), where it is used."""
    found = {}
    for repo in repos:
        d = read_json(os.path.join(OUT, "scan", repo + ".json"), {}) or {}
        def walk(o):
            if isinstance(o, dict):
                if o.get("kind") == "external-ip" and o.get("host") and o.get("evidence"):
                    yield o
                for v in o.values():
                    yield from walk(v)
            elif isinstance(o, list):
                for v in o:
                    yield from walk(v)
        for o in walk(d):
            f = found.setdefault(o["host"], {"roles": set(), "ports": set(), "repos": set(), "places": 0})
            f["repos"].add(repo)
            f["places"] += o.get("occurrences") or 1
            if o.get("port"):
                f["ports"].add(o["port"])
            for ev in o["evidence"][:3]:
                t = (ev.get("text") if isinstance(ev, dict) else str(ev)).lower()
                for rx, role in PUBLIC_RULES:
                    if re.search(rx, t):
                        f["roles"].add(role)
                        break
                pm = re.search(r"port=[\"']?(\d{2,5})", t)
                if pm:
                    f["ports"].add(int(pm.group(1)))
    out = []
    for h, f in sorted(found.items()):
        roles = sorted(f["roles"])
        out.append({"address": h, "type": "public IP", "role": " / ".join(roles) if roles else "", "confidence": ("HIGH" if len(roles) == 1 and roles[0] != "Mentioned in a code comment only" else "MIXED" if len(roles) > 1 else "UNKNOWN"),
                    "keys": [], "ports": sorted(f["ports"])[:4], "places": f["places"], "devops_servers_with_role": 0, "solutions_repos": sorted(f["repos"])})
    return out


def main():
    utf8_stdout()
    root, cfg = load_config()
    os.chdir(root)
    idx = read_json(os.path.join(OUT, "solutions", "index.json"))
    if not idx:
        raise SystemExit("run solutions.py first")
    st = load_state(root)
    repos = sorted(r for r in st["repos"] if st["repos"][r].get("scope") != "out")
    dest = {}
    for s in idx["solutions"]:
        for e in s["endpoints"]:
            dest.setdefault(e["destination"], e["class"])
    names = sorted(dest, key=len, reverse=True)
    if not names:
        out = public_ips(repos)
        write_json(os.path.join(OUT, "infra", "address_roles.json"), {"addresses": out})
        mark_step(root, "address_roles")
        print(f"no internal addresses in the solutions; {len(out)} public IP(s) listed")
        return
    rx = re.compile(r"(?<![\w.\-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w\-]|\.\w)", re.I)
    low_map = {n.lower(): n for n in names}
    hits = {n: [] for n in names}
    for r_ in cfg.get("estate_roots") or []:
        for dp, dn, fn in os.walk(r_):
            dn[:] = [d for d in dn if not skip_dir(dp, d, SKIP, fold=False)]
            for f in fn:
                if not f.lower().endswith(EXT):
                    continue
                p = os.path.join(dp, f)
                try:
                    if os.path.getsize(p) > 3_000_000:
                        continue
                    text = open(p, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                if not rx.search(text):
                    continue
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if len(line) > 4000:
                        continue
                    for m in rx.finditer(line):
                        n = low_map[m.group(1).lower()]
                        key = key_of(line, m.start(), m.end())
                        ctx = context_role(f, lines, i)
                        hits[n].append((key,) + hit_roles(line, m.start(), m.end(), key) + (ctx,))
    servers = (read_json(os.path.join(OUT, "infra", "servers.json")) or {}).get("servers", [])
    count = {}
    for x in servers:
        for r_ in x.get("roles") or []:
            count[r_["role"]] = count.get(r_["role"], 0) + 1
    out = []
    for n in names:
        hs = hits[n]
        explicit = {h[1] for h in hs if h[1]}
        weak = {h[2] for h in hs if h[2]}
        ports = sorted({h[3] for h in hs if h[3]})
        port_roles = {h[4] for h in hs if h[4]}
        ctx_roles = {h[5] for h in hs if h[5]}
        web = "Web service / API" in weak or "Web service / API" in port_roles
        keys = sorted({h[0] for h in hs if h[0]})
        roles = explicit or port_roles or weak or ctx_roles
        if not hs or not roles:
            role, conf = "", "UNKNOWN"
        elif len(explicit) > 1 or (explicit and port_roles and not port_roles & explicit and not port_roles <= {"Web service / API"}):
            role, conf = " / ".join(sorted(explicit | (port_roles - {"Web service / API"}))), "MIXED"
        elif explicit:
            role, conf = sorted(explicit)[0], "HIGH"
        elif port_roles:
            role, conf = sorted(port_roles)[0], "MEDIUM"
        elif weak:
            role, conf = sorted(weak)[0], "MEDIUM"
        else:
            role, conf = " / ".join(sorted(ctx_roles)), "MEDIUM" if len(ctx_roles) == 1 else "MIXED"
        if conf in ("HIGH", "MEDIUM") and role in STORES and web:
            role += " and Web service / API"
        first = role.split(" / ")[0].split(" and ")[0]
        out.append({"address": n, "type": dest[n], "role": role, "confidence": conf, "keys": keys[:4], "ports": ports[:4],
                    "places": len(hs), "devops_servers_with_role": count.get(LIST_ROLE.get(first, ""), 0) if conf != "UNKNOWN" else 0})
    out += public_ips(repos)
    write_json(os.path.join(OUT, "infra", "address_roles.json"), {"addresses": out})
    mark_step(root, "address_roles")
    tally = {}
    for o in out:
        tally[o["confidence"]] = tally.get(o["confidence"], 0) + 1
    print(f"{len(out)} addresses: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    ip = [o for o in out if o["type"] == "private IP"]
    print(f"of the {len(ip)} private IPs: " + ", ".join(f"{k} {sum(1 for o in ip if o['confidence'] == k)}" for k in ("HIGH", "MEDIUM", "MIXED", "UNKNOWN")))


if __name__ == "__main__":
    main()
