"""Configuration map and network access per project (deterministic, standard library only).

`config_map()` lists, for every project, the configuration files and the settings in them that hold an address that changes (or must be
reachable) when the servers move to AWS: URLs, IP addresses, host names, UNC shares, local drive / folder paths, connection-string hosts,
NuGet feed URLs. One row = one setting in one file (key name, target host:port or path, line, environment of the file, what to do on AWS).
Values are never copied except the target address / path itself; secret-looking settings (passwords, keys, tokens) are skipped entirely and
user-info, query strings and URL paths are dropped.
`network_access()` turns the outbound destinations (scan_repo `network` facts + the config map) into the allow-list view: which project must
reach which host and port, what kind of destination it is, and what has to be opened, routed or re-registered on AWS.
"""
import os
import re
from collections import OrderedDict

from _common import OUT, SOURCE_DIR_SKIP, read_json, read_text, rel, save_config
from _infra import plausible_host

CFG_EXT = {".config", ".json", ".xml", ".ini", ".properties", ".env", ".conf", ".settings", ".toml", ".yml", ".yaml", ".pubxml"}
SKIP_FILE = re.compile(r"(?i)(package(-lock)?\.json$|yarn\.lock|tsconfig|launchsettings|\.deps\.json|\.runtimeconfig|bundleconfig|\.nuspec|\.resx|\.xsd|\.wsdl|\.xslt?$|"
                       r"\.min\.|packages\.config|\.csproj|appxmanifest|\.vsconfig|mappings?\.xml$|\.designer\.|schema|swagger|openapi|components\.json|angular\.json|"
                       r"\.eslintrc|\.prettierrc|\.babelrc|karma|protractor|jest|webpack|\.vscode|devcontainer)")
SECRET_KEY = re.compile(r"(?i)(pass(word|wd|phrase)?$|pwd$|secret|token$|api[_-]?key|access[_-]?key|private[_-]?key|credential|client[_-]?key|shared[_-]?key|signing[_-]?key|salt$|hash$|license[_-]?key|authorization)")
HOST_KEY = re.compile(r"(?i)(host|server|address|endpoint|url|uri|broker|smtp|proxy|bootstrap|nodes?|redis|memcache|aerospike|elastic|kafka|ldap|ftp|baseaddress|datasource|"
                      r"cache|queue|domain|origin|location|gateway|service|api|callback|redirect|webhook|feed)")
HOST_LAST = re.compile(r"(?i)host|server|address|endpoint|url|uri|broker|bootstrap|smtp|node|redis|memcache|aerospike|elastic|kafka|ldap|ftp|proxy|domain")  # a bare word is a host only when the LAST part of the setting name says so (DataSource, ServiceType, text are not)
PATH_KEY = re.compile(r"(?i)(path|dir|directory|folder|file|share|root|location|logs?|temp|tmp|template|export|import|drop|inbox|outbox|archive|storage|cache)")
URL_RX = re.compile(r"\b(https?|ftps?|sftp|ldaps?|net\.tcp|tcp|amqps?|redis|rediss|mongodb(?:\+srv)?|smtp|wss?|rtmp|jdbc:\w+)://(?:[^\s/@\"'<>]+@)?([A-Za-z0-9.\-]+|\[[0-9a-fA-F:]+\])(?::(\d{2,5}))?")
IP_RX = re.compile(r"(?<![\d.\w])((?:\d{1,3}\.){3}\d{1,3})(?::(\d{2,5}))?(?![\d.]*\w)")
UNC_RX = re.compile(r"\\\\([A-Za-z0-9][A-Za-z0-9._-]*)\\([^\s\"'<>|;,]+)")
DRIVE_RX = re.compile(r"(?<![\w/])([A-Za-z]):[\\/][^\"'<>|;\r\n]{1,150}")
ARG_START = re.compile(r"\s+(?:--?|/)[A-Za-z]\w*")  # a drive path ends where command-line arguments start
SECRET_WORD = re.compile(r"(?i)pass(word|wd)?|pwd|secret|token|api[_-]?key|access[_-]?key|credential")
UNIX_RX = re.compile(r"(?<![\w.:/])(/(?:var|opt|etc|home|mnt|srv|data|usr|app|logs?|tmp|shared)/[^\s\"'<>|;,]{0,150})")
NOISE_KEY = re.compile(r"(?i)(^|[./@])\$?(schema|ref|id)$|xmlns|xsi|namespace|licen[cs]e|helpurl|documentation|homepage|repository|bugs$")
DB_FILE = re.compile(r"(?i)^[A-Za-z]:|[\\/]\.{0,2}[^\\/]*\.(sdf|sqlite3?|db|mdf|ldf|mdb|accdb|xlsx?|csv)$|^[^\\/]*\.(sdf|sqlite3?|db|mdf|mdb|accdb)$|^\|")  # a file, not a server
PLACEHOLDER = re.compile(r"(\{\{.*?\}\}|\$\{.*?\}|#\{.*?\}#?|%[A-Za-z_]+%|__\w+__|\$\(.*?\)|<%.*?%>)")
CONN_HOST = re.compile(r"(?i)\b(?:data source|server|host|address|addr|network address)\s*=\s*(?:tcp:|np:)?([^;,\"'\s]+)(?:[,:](\d{2,5}))?")
ENV_NAME = re.compile(r"(?i)[._-](debug|release|dev|development|local|staging|stage|stag|uat|qa|test|testing|sandbox|prod|production|live|preprod|cdn|demo)\b")
SKIP_HOSTS = re.compile(r"(?i)^(localhost|127\..*|0\.0\.0\.0|::1|.*\.(w3|xmlsoap|microsoft|openxmlformats|schemas|nuget|oasis-open|xmlns)\..*|www\.w3\.org|schemas\.\w+\..*|"
                        r"json\.schemastore\.org|.*\.example\.(com|org)|example\.(com|org)|yourdomain\..*|your-?\w*\.com)$")
OPEN_TAG = re.compile(r"<([A-Za-z][\w.:-]*)(?:\s[^>]*)?(?<!/)>")
CLOSE_TAG = re.compile(r"</([A-Za-z][\w.:-]*)\s*>")
SECTIONS = {"appsettings", "connectionstrings", "system.servicemodel", "client", "mailsettings", "system.net", "log4net", "nlog", "serilog", "applicationsettings",
            "usersettings", "elasticsearch", "redis", "kafka", "smtp", "endpoints", "services"}
PORT_BY_SCHEME = {"http": 80, "https": 443, "ftp": 21, "ftps": 990, "sftp": 22, "ldap": 389, "ldaps": 636, "smtp": 25, "amqp": 5672, "amqps": 5671, "redis": 6379, "rediss": 6379,
                  "mongodb": 27017, "net.tcp": 808, "tcp": 0, "ws": 80, "wss": 443}


ENV_LABEL = {"stag": "staging", "stage": "staging", "dev": "development", "prod": "production"}


def env_of(filename):
    m = ENV_NAME.search(filename)
    if m:
        return ENV_LABEL.get(m.group(1).lower(), m.group(1).lower())
    return "default"


def classify_target(host, company_domains, host_kind, private_ip):
    h = host.lower().strip("[]")
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", h):
        return "private IP" if private_ip(h) else "public IP"
    if any(h == d or h.endswith("." + d) for d in company_domains):
        return "company domain"
    k = host_kind(host)
    return "internal host name" if k == "internal" else "external service"


ACTION = {
    "private IP": "Update the address if the target moves to AWS; otherwise allow this server's subnet to reach it (VPN / Direct Connect route plus security-group and firewall rule on both sides).",
    "internal host name": "The name must resolve from AWS (Route 53 Resolver / DNS forwarding to the on-premises DNS) and be reachable; update it if the target moves.",
    "company domain": "The company DNS record must resolve from AWS; point it at the new address if the target moves, and open the port to it.",
    "public IP": "A partner or provider may allow-list our source IP: give them the AWS NAT gateway Elastic IP before cut-over; the target itself does not change.",
    "external service": "Outbound internet access (NAT gateway or proxy) on the port; no change unless the provider allow-lists IP addresses.",
    "UNC share": "The file server and share must exist on AWS (Amazon FSx for Windows File Server or a server on EC2) or stay reachable; update the UNC path if it moves.",
    "local drive path": "Create the same drive letter and folder on the EC2 server (an EBS volume) or change the path; size the volume for the data kept there.",
    "unix path": "Create the same folder on the EC2 server (an EBS volume) or change the path.",
    "set at deploy time": "The value is injected at deploy time (token, variable): find out what the deployment tool sets for each environment and update it for AWS.",
}


def _items(key, value, section, company_domains, host_kind, private_ip):
    """Addresses and paths in one setting value: [(type, target, port, scheme, cls)]."""
    out = []
    v = value.strip()
    if not v:
        return out
    if PLACEHOLDER.search(v) and (HOST_KEY.search(key) or PATH_KEY.search(key)) and not (URL_RX.search(v) or UNC_RX.search(v)):
        out.append(("set at deploy time", PLACEHOLDER.search(v).group(0)[:60], None, "", "set at deploy time"))
        return out
    seen = set()
    for m in URL_RX.finditer(v):
        host = m.group(2).strip("[]")
        if SKIP_HOSTS.match(host) or "$" in host or host.startswith("{"):
            continue
        scheme = m.group(1).lower()
        port = int(m.group(3)) if m.group(3) else PORT_BY_SCHEME.get(scheme.split(":")[0], None)
        seen.add(host.lower())
        out.append(("URL", host, port, scheme, classify_target(host, company_domains, host_kind, private_ip)))
    for m in UNC_RX.finditer(v):
        out.append(("UNC share", f"\\\\{m.group(1)}\\{m.group(2)}".rstrip("\\")[:150], 445, "smb", "UNC share"))
        seen.add(m.group(1).lower())
    for m in CONN_HOST.finditer(v):
        host = m.group(1).strip("'\"")
        if DB_FILE.search(host) or host.lower() in seen or host in (".", "(local)", "localhost", "127.0.0.1") or host.lower().startswith(("(localdb)", "|datadirectory|")) or SKIP_HOSTS.match(host):
            continue
        seen.add(host.lower())
        port = int(m.group(2)) if m.group(2) else (1433 if re.search(r"(?i)initial catalog|database=|integrated security", v) else None)
        out.append(("connection string host", host, port, "tcp", classify_target(host, company_domains, host_kind, private_ip)))
    for m in IP_RX.finditer(v):
        ip = m.group(1)
        if ip in seen or ip.startswith(("0.", "127.", "255.")) or all(int(x) < 10 for x in ip.split(".")) or any(int(x) > 255 for x in ip.split(".")) or ip.endswith(".0.0"):
            continue
        seen.add(ip)
        out.append(("IP address", ip, int(m.group(2)) if m.group(2) else None, "ip", classify_target(ip, company_domains, host_kind, private_ip)))
    for m in DRIVE_RX.finditer(v):
        path = ARG_START.split(m.group(0), 1)[0].rstrip(" ;,")[:150]
        if not URL_RX.search(v[max(0, m.start() - 8):m.start() + 3]) and not SECRET_WORD.search(path):
            out.append(("local drive path", path, None, "path", "local drive path"))
    for m in UNIX_RX.finditer(v):
        out.append(("unix path", m.group(1)[:150], None, "path", "unix path"))
    if not out and HOST_LAST.search(re.split(r"[./@:]", key)[-1]) and not SECRET_KEY.search(key) and len(v) < 120 and not re.search(r"\s", v):
        m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?::(\d{2,5}))?", v)
        if m and plausible_host(m.group(1), m.group(2)) and not re.fullmatch(r"\d+(\.\d+)*", m.group(1)) and not re.fullmatch(r"(?i)\d{1,2}-[a-z]{3}-\d{4}|[\d-]+", m.group(1)) and len(m.group(1)) >= 3:
            h = m.group(1)
            if not SKIP_HOSTS.match(h):
                out.append(("host name", h, int(m.group(2)) if m.group(2) else None, "", classify_target(h, company_domains, host_kind, private_ip)))
    return out


def _json_lines(text):
    """(line_no, key path, value) for string settings in JSON (comments allowed), also for compact one-line files.
    A value inside an array takes the array's key; an object inside an array adds nothing to the path."""
    ctx, key, line, i, n = [], None, 1, 0, len(text)  # ctx: [(kind, name)], name = the key the container opened under
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += text.count("\n", i, j)
            i = j
            continue
        elif c in "{[":
            parent_is_obj = bool(ctx) and ctx[-1][0] == "obj"
            ctx.append(("obj" if c == "{" else "arr", key if parent_is_obj and key else ""))
            key = None
        elif c in "}]":
            if ctx:
                ctx.pop()
            key = None
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            s = text[i + 1:j]
            k = j + 1
            while k < n and text[k] in " \t\r\n":
                k += 1
            if k < n and text[k] == ":" and ctx and ctx[-1][0] == "obj":
                key = s
            else:
                names = [x[1] for x in ctx if x[1]]
                in_obj = bool(ctx) and ctx[-1][0] == "obj"
                if (in_obj and key) or (ctx and ctx[-1][0] == "arr" and names):
                    yield line, ".".join(names + ([key] if in_obj else [])), s.replace("\\\\", "\\")
                key = None
            i = j
        i += 1


def _xml_lines(text):
    """(line_no, key, value) from XML / .config by line: <add key= value=>, name= connectionString=, address=, url=, element text, and other attributes."""
    open_sections = []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("<!--") or s.startswith("<?"):
            continue
        for m in CLOSE_TAG.finditer(s):
            if open_sections and open_sections[-1].lower() == m.group(1).lower():
                open_sections.pop()
        for m in OPEN_TAG.finditer(s):
            if m.group(1).lower() in SECTIONS:
                open_sections.append(m.group(1))
        sect = open_sections[-1] if open_sections else ""
        attrs = dict((a.lower(), (a, v)) for a, v in re.findall(r"""([A-Za-z_][\w:.-]*)\s*=\s*"([^"]*)\"""", s))
        if re.match(r"<(assemblyBinding|bindingRedirect|dependentAssembly|assemblyIdentity|codeBase|runtime|configSections|section\b|sectionGroup|add\s+assembly=|compilation|httpRuntime|xml)", s, re.I) \
                and "address" not in attrs and "url" not in attrs:
            continue
        name = (attrs.get("key") or attrs.get("name") or attrs.get("id") or ("", ""))[1]
        for ak, (an, av) in attrs.items():
            if ak in ("key", "name", "id", "xmlns", "version", "publickeytoken", "oldversion", "newversion", "type", "assembly", "namespace", "culture") or ak.startswith("xmlns") or ak.startswith("xsi"):
                continue
            prefix = sect + "/" if sect else ""
            em = re.match(r"<([A-Za-z][\w.:-]*)", s)
            el = em.group(1) if em else ""
            if name and ak in ("value", "connectionstring"):
                kk = prefix + name  # <add key="Host" value="..."/>: the setting is called Host
            else:
                kk = prefix + (name or el) + "@" + an
            yield i, kk, av
        tm = re.match(r"^<([A-Za-z][\w.:-]*)>([^<]+)</\1>", s)
        if tm:
            yield i, (sect + "/" if sect else "") + tm.group(1), tm.group(2)


def _kv_lines(text, ext):
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith(("#", ";", "//", "[", "<!--")):
            continue
        m = re.match(r"^(?:export\s+)?([A-Za-z_][\w.:\-/ ]*?)\s*[:=]\s*(.*)$" if ext != ".env" else r"^(?:export\s+)?([A-Za-z_][\w.]*)\s*=\s*(.*)$", s)
        if m:
            yield i, m.group(1).strip(), m.group(2).strip().strip("\"'")


def config_map(repo_root, inv, cfg, host_kind, private_ip):
    """Rows for every address / path setting in the repository's configuration files, by project."""
    company = [d.lower() for d in cfg.get("company_domains", [])]
    skip = SOURCE_DIR_SKIP | {s.lower() for s in cfg.get("exclude_dirs", [])}
    oos = [os.path.normpath(os.path.join(repo_root, x)) for x in (inv.get("scope") or {}).get("skip_dirs", [])]
    pdirs = sorted(((os.path.normpath(os.path.dirname(os.path.join(repo_root, p["path"]))), p["name"]) for p in inv["projects"]), key=lambda x: -len(x[0]))
    rows, files = [], OrderedDict()
    for d, dirs, fns in os.walk(repo_root):
        dirs[:] = sorted(x for x in dirs if x.lower() not in skip and not x.startswith(".") and os.path.normpath(os.path.join(d, x)) not in oos)
        for fn in sorted(fns):
            ext = os.path.splitext(fn)[1].lower()
            low = fn.lower()
            if not (ext in CFG_EXT or low in ("nuget.config", ".env") or low.endswith(".env")) or SKIP_FILE.search(fn) or low.startswith(("stylecop", ".editorconfig", "coderabbit", ".coderabbit")):
                continue
            path = os.path.join(d, fn)
            try:
                if os.path.getsize(path) > 800_000:
                    continue
                text = read_text(path)
            except OSError:
                continue
            if ext in (".yml", ".yaml") and not re.search(r"(?i)(appsettings|config|settings|compose|application|values|env)", fn):
                continue
            proj = next((nm for pd, nm in pdirs if os.path.normpath(path).startswith(pd + os.sep)), "(repository)")
            template = bool(re.search(r"(?i)[._-](example|sample|template|tmpl|dist)([._-]|$)", fn))
            gen = _json_lines(text) if ext == ".json" else _xml_lines(text) if ext in (".config", ".xml", ".pubxml", ".settings") else _kv_lines(text, ext)
            n = 0
            for line_no, key, value in gen:
                last = re.split(r"[./@:]", key)[-1]
                if NOISE_KEY.search(key):
                    continue
                if SECRET_KEY.search(last) and not (URL_RX.search(value) or UNC_RX.search(value)):
                    continue
                for typ, target, port, scheme, cls in _items(key, value, "", company, host_kind, private_ip):
                    if SECRET_KEY.search(last) and typ not in ("URL", "UNC share"):
                        continue
                    if low == "nuget.config":
                        typ = "NuGet feed " + typ if typ == "URL" else typ
                    rows.append({"project": proj, "file": rel(path, repo_root), "line": line_no, "environment": env_of(fn), "template_file": template, "setting": key[:120],
                                 "type": typ, "target": target, "port": port, "protocol": scheme, "class": cls, "where": "config file",
                                 "action": ACTION.get(cls, "")})
                    n += 1
            if n:
                files[rel(path, repo_root)] = n
    # same setting repeated in several environment files stays one row per file (the environment column tells them apart)
    return rows, dict(files)


def code_literals(facts):
    """Hard-coded addresses in .cs/.vb (not configuration): changing them needs a code change."""
    rows = []
    for e in (facts or {}).get("endpoints", []):
        for ev in e.get("evidence", []):
            f = ev["file"].lower()
            if f.endswith((".cs", ".vb")):
                rows.append({"project": "", "file": ev["file"], "line": ev["line"], "host": e["host"], "kind": e["kind"], "schemes": e["schemes"]})
    return rows


NEEDS = {
    "private IP": ("update address or open route", "On-premises / private address: allow the AWS subnet to reach it (VPN or Direct Connect, route, security group, firewall) or update it if the target moves."),
    "internal host name": ("DNS must resolve from AWS", ACTION["internal host name"]),
    "company domain": ("DNS must resolve from AWS", ACTION["company domain"]),
    "public IP": ("register new egress IP", ACTION["public IP"]),
    "external service": ("outbound internet", ACTION["external service"]),
    "UNC share": ("file server must exist or be reachable", ACTION["UNC share"]),
}


def looks_like_noise(h):
    """A date, a one-letter token or a version number that the address pattern read as a host."""
    is_ip = bool(re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", h))
    if len(h) < 3:
        return True
    if not is_ip and re.search(r"(?i)^\d{1,2}-[a-z]{3}-\d{4}$|^[\d.]+$", h):
        return True
    return not (is_ip or "." in h or plausible_host(h, None))


def network_access(repo, inv, facts, cfgrows, host_kind, private_ip, company, index=None):
    """One row per (project, destination host, port): what must be reachable from AWS, and what to do about it."""
    rows = OrderedDict()
    pnames = {p["path"]: p["name"] for p in inv["projects"]}

    def add(project, host, port, scheme, role, cls, keys, evidence, source):
        k = (project, host.lower(), port)
        r = rows.get(k)
        if not r:
            r = rows[k] = {"repo": repo, "project": project, "destination": host, "port": port, "protocol": scheme, "role": role, "class": cls, "config_keys": [], "evidence": [], "found_in": set()}
        for x in keys:
            if x not in r["config_keys"]:
                r["config_keys"].append(x)
        for x in evidence:
            if x not in r["evidence"] and len(r["evidence"]) < 3:
                r["evidence"].append(x)
        r["found_in"].add(source)

    net = (facts or {}).get("network") or {}
    for o in net.get("outbound", []):
        if o.get("host") in ("localhost", "127.0.0.1"):
            continue
        h = o["host"]
        if looks_like_noise(h):
            continue  # a date, a one-letter token or a version number that the pattern read as an address
        cls = classify_target(o["host"], company, host_kind, private_ip)
        for pj in (o.get("projects") or ["(repository)"]):
            ev = o.get("evidence", [])
            if ev and all(re.search(r"\.(js|ts|html?|cshtml|aspx|ascx|razor)(:|$)", e, re.I) for e in ev):
                src = "front-end script (the user's browser calls it)"
            elif any(re.search(r"\.(cs|vb)(:|$)", e) for e in ev) and not o.get("keys"):
                src = "hard-coded in code"
            else:
                src = "configuration"
            add(pnames.get(pj, pj), o["host"], o.get("port"), o.get("scheme", ""), o.get("role", ""), cls, o.get("keys", []), ev, src)
    for r in cfgrows:
        if r["type"] in ("URL", "IP address", "connection string host", "host name", "UNC share") and r["class"] in NEEDS:
            host = r["target"] if r["type"] != "UNC share" else r["target"].split("\\")[2]
            add(r["project"], host, r["port"], r["protocol"], "", r["class"], [r["setting"]], [f"{r['file']}:{r['line']}"], "configuration")
    out = []
    with_port = {(r["project"], r["destination"].lower()) for r in rows.values() if r["port"]}
    for r in rows.values():
        if not r["port"] and (r["project"], r["destination"].lower()) in with_port:
            continue  # the same destination with a known port is already listed
        why, how = NEEDS.get(r["class"], ("", ""))
        srv = index.find(r["destination"]) if index else None
        if "front-end" in " ".join(r["found_in"]):
            why, how = "update the address (browser-side)", "Address called by the user's browser from a page or script: update it if the target moves; no server firewall rule, but it must be reachable from users (public DNS / load balancer)."
        out.append({**r, "config_keys": ", ".join(r["config_keys"][:4]), "evidence": "; ".join(r["evidence"]), "found_in": ", ".join(sorted(r["found_in"])),
                    "need": why, "what_to_do": how, "server_in_list": f"{srv['name']} ({srv['environment'] or '?'}, {srv['os'] or '?'})" if srv else ""})
    order = {"private IP": 0, "internal host name": 1, "company domain": 2, "UNC share": 3, "public IP": 4, "external service": 5}
    out.sort(key=lambda r: (order.get(r["class"], 9), r["project"], r["destination"]))
    return out


_GENERIC_TOKENS = {"repos", "repo", "src", "code", "source", "sourcefuse", "projects", "client", "clients", "gitlab", "github", "work", "dev", "main"}
_INTERNAL_TLDS = {"local", "lan", "internal", "corp", "intranet", "localdomain", "home"}  # internal names are handled as internal host names, not company domains
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}


def _registrable(host):
    labels = host.lower().strip(".").split(".")
    if len(labels) < 2 or not re.search(r"[a-z]", labels[-1]) or labels[-1] in _INTERNAL_TLDS:
        return None
    n = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-n:])


def detect_company_domains(cfg):
    """The client's own web domains, guessed from the hosts the scans found: a registrable domain whose name starts like the client name or like
    a folder of the repository path (client Acme + repos/Acme/ws -> acme.com). Returns [(domain, hosts)] by count."""
    tokens = set(re.findall(r"[a-z0-9]+", (cfg.get("client") or "").lower()))
    for r in cfg.get("estate_roots") or []:
        tokens |= set(re.findall(r"[a-z0-9]+", r.lower().replace("\\", "/")))
    stems = {t[:5] for t in tokens if len(t) >= 5 and t not in _GENERIC_TOKENS}
    seen = {}
    sdir = os.path.join(OUT, "scan")
    for fn in sorted(os.listdir(sdir)) if os.path.isdir(sdir) else []:
        d = read_json(os.path.join(sdir, fn), {}) or {}
        for e in d.get("endpoints", []):
            dom = _registrable(e.get("host", ""))
            if dom and any(dom.split(".")[-2 if len(dom.split(".")) == 2 else -3].startswith(s) for s in stems):
                seen[dom] = seen.get(dom, 0) + int(e.get("occurrences", 1) or 1)
    return sorted(seen.items(), key=lambda kv: -kv[1])


def ensure_company_domains(root, cfg):
    """assessment.json company_domains if set (by the user), else the detected ones, stored with company_domains_auto = true so the report asks to confirm."""
    if cfg.get("company_domains"):
        return [d.lower() for d in cfg["company_domains"]]
    found = [d for d, _ in detect_company_domains(cfg)]
    if found:
        cfg["company_domains"] = found
        cfg["company_domains_auto"] = True
        save_config(root, cfg)
        print("company web domains (detected from the hosts in the code, confirm with the client): " + ", ".join(found))
    return found
