"""Server-dependency and hosting-evidence detection for one repository (deterministic, standard library only).

`detect(repo, inv, facts, cfg)` answers two questions from the code:
  1. Which kinds of server does this repository depend on (SQL Server, Redis, Elasticsearch, Kafka, SMTP, SFTP, Memcached,
     Aerospike, RabbitMQ, LDAP, file shares, proxies ...)?  Catalogue: data/infra_deps.json. Evidence = package, code, config key
     or docker-compose image, each with file:line. Config VALUES are never stored; only host names / IPs / ports are kept,
     because they are what ties a dependency to a server in the client's infrastructure list.
  2. Where does the code say it is hosted (Windows / Linux), and from which evidence? Labelled "inferred from code, unverified".
`link(deps, servers)` ties each dependency to the client's server list (see import_servers.py).
"""
import os
import re
from collections import Counter, defaultdict

from _common import SOURCE_DIR_SKIP, data, mask, read_text, rel

CONFIG_EXT = {".config", ".json", ".xml", ".yml", ".yaml", ".ini", ".env", ".properties", ".settings", ".toml", ".conf"}
CODE_EXT = {".cs", ".vb"}
PROJ_EXT = {".csproj", ".vbproj", ".fsproj", ".props", ".targets"}
SKIP_FILE = re.compile(r"(?i)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|\.min\.|\.designer\.|\.g\.cs$|\.xsd$|\.wsdl$|nuget\.config$|\.resx$|tsconfig|launchsettings)")
MAX_BYTES = 1_500_000
EVIDENCE_PER_VIA = 5
HOST_RX = re.compile(r"(?<![\w@.\\-])((?:\d{1,3}\.){3}\d{1,3}|[A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)+|[A-Za-z][A-Za-z0-9_-]{2,})(?::(\d{2,5}))?(?![\w.-]*\()")
NOT_HOST = {"true", "false", "null", "none", "server", "host", "hostname", "localhost", "string", "value", "key", "name", "password", "user", "username", "port", "http", "https",
            "tcp", "ssl", "tls", "timeout", "database", "catalog", "integrated", "security", "trusted", "connection", "connectionstring", "data", "source", "initial", "provider",
            "version", "encrypt", "pooling", "false", "enabled", "yes", "no", "add", "key", "type", "remove", "clear", "settings", "section", "default", "development",
            "production", "staging", "info", "warning", "error", "debug", "trace", "level", "enable", "disable", "relay", "smtp", "ftp", "sftp", "redis", "kafka", "elastic",
            "elasticsearch", "memcached", "aerospike", "rabbitmq", "ldap", "proxy", "cache", "queue", "topic", "group", "client", "consumer", "producer", "nodes", "servers",
            "hosts", "uri", "url", "address", "endpoint", "bootstrapservers", "bootstrap", "sasl", "plaintext", "mechanism", "protocol", "username", "credentials", "application"}
FILE_LIKE = re.compile(r"(?i)\.(cs|vb|json|xml|config|dll|exe|js|css|html?|aspx?|cshtml|png|jpe?g|gif|svg|txt|log|csv|xlsx?|sql|bak|zip|pdf|ico|woff2?|ttf|xslt?|yml|yaml)$")
SECTION_NAME = re.compile(r"^(system|microsoft|newtonsoft|nuget|windows|xmlns|schemas)\b", re.I)
DOCKER_FILE = re.compile(r"(?i)^(dockerfile.*|docker-compose.*\.ya?ml|compose.*\.ya?ml)$")
_cat = None


def catalogue():
    global _cat
    if _cat is None:
        _cat = []
        for t in data("infra_deps.json")["types"]:
            t = dict(t)
            for k in ("packages", "code", "config_keys", "config_values", "compose_image"):
                t["_" + k] = re.compile(t[k]) if t.get(k) and t[k] not in ("^$", "(?!)") else None
            _cat.append(t)
    return _cat


def key_of(line):
    """The setting NAME on a config line (never the value)."""
    m = re.search(r"""\b(?:key|name)\s*=\s*["']([^"']+)["']""", line) or re.match(r"""\s*["']?([\w.:/@ -]+?)["']?\s*[:=]""", line) or re.match(r"\s*<([\w.:-]+)[\s>/]", line)
    return m.group(1).strip() if m else ""


def _value_part(line):
    m = re.search(r"""\bvalue\s*=\s*["']([^"']*)["']""", line) or re.search(r"""\bconnectionString\s*=\s*["']([^"']*)["']""", line, re.I)
    if m:
        return m.group(1)
    m = re.search(r"""[:=]\s*["']?(.*)""", line)
    return m.group(1) if m else line


TLD_OK = {"local", "lan", "corp", "internal", "intra", "intranet", "home", "localdomain", "com", "net", "org", "io", "co", "ai", "cloud", "info", "biz", "edu", "gov", "app", "dev"}


def plausible_host(h, port):
    """True for an IP, a dotted name that ends like a domain, or a short bare server name; false for namespaces, keys and tokens."""
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", h):
        return not (h.startswith(("0.", "127.", "255.")) or all(int(x) < 10 for x in h.split(".")))
    if len(h) > 45 or re.fullmatch(r"[0-9a-fA-F]{12,}", h):
        return False
    labels = h.split(".")
    if len(labels) > 1:
        tld = labels[-1].lower()
        return tld.isalpha() and (len(tld) == 2 or tld in TLD_OK) and not any(len(x) > 30 for x in labels)
    if len(h) > 30:
        return False
    if port:
        return not re.search(r"[a-z][A-Z]\d|\d[A-Za-z]+\d", h)  # a bare name with a port; random-looking mixes are keys
    # bare names without a port: SBSQL01, Redis-Production, dev_redis_1 (letters, optional separators, optional number); never camel-case mixes with digits
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z]*[-_]?\d{1,3}", h) or re.fullmatch(r"[A-Za-z0-9]+([-_][A-Za-z0-9]+)+", h)) and not re.search(r"[a-z][A-Z]\d|\d[A-Za-z]+\d", h)


def host_tokens(text, ports):
    """Host names / IPs (with optional port) in a value. No credentials: user-info and key=value pairs are not hosts."""
    out = []
    text = re.sub(r"(?i)(user id|uid|user|username|password|pwd|pass|secret|token|apikey|accesskey|key|salt|hash)\s*[=:]\s*[^;,\s\"']*", " ", text)
    for m in HOST_RX.finditer(text):
        h, port = m.group(1), m.group(2)
        low = h.lower()
        if low in NOT_HOST or FILE_LIKE.search(h) or SECTION_NAME.match(h) or (re.fullmatch(r"\d+(\.\d+)*", h) and not re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", h)):
            continue
        if not plausible_host(h, port):
            continue
        out.append({"host": h, "port": int(port) if port else None})
    return out[:6]


class Hit:
    def __init__(self, t):
        self.t = t
        self.via = defaultdict(list)
        self.projects = set()
        self.hosts = {}
        self.files = set()

    def add(self, via, file, line, text, project=None):
        if len(self.via[via]) < EVIDENCE_PER_VIA:
            self.via[via].append({"file": file, "line": line, "text": mask(text)})
        self.files.add(file)
        if project:
            self.projects.add(project)

    def host(self, host, port, file, line):
        k = (host.lower(), port)
        if k not in self.hosts and len(self.hosts) < 25:
            self.hosts[k] = {"host": host, "port": port, "file": file, "line": line}


def detect_dependencies(repo_root, inv, facts, cfg):
    cat = catalogue()
    hits = {t["id"]: Hit(t) for t in cat}
    skip = SOURCE_DIR_SKIP | {s.lower() for s in cfg.get("exclude_dirs", [])}
    oos = [os.path.normpath(os.path.join(repo_root, x)) for x in (inv.get("scope") or {}).get("skip_dirs", [])]
    pdirs = sorted(((os.path.normpath(os.path.dirname(os.path.join(repo_root, p["path"]))), p["path"]) for p in inv["projects"]), key=lambda x: -len(x[0]))

    def owner(path):
        n = os.path.normpath(path)
        return next((pp for d, pp in pdirs if n.startswith(d + os.sep)), None)

    for d, dirs, files in os.walk(repo_root):
        dirs[:] = sorted(x for x in dirs if x.lower() not in skip and not x.startswith(".") and os.path.normpath(os.path.join(d, x)) not in oos)
        for fn in files:
            path = os.path.join(d, fn)
            ext = os.path.splitext(fn)[1].lower()
            is_docker = bool(DOCKER_FILE.match(fn))
            if SKIP_FILE.search(fn) and not is_docker:
                continue
            if not (ext in PROJ_EXT or ext in CODE_EXT or ext in CONFIG_EXT or fn.lower() == "packages.config" or is_docker or ext in (".pubxml",)):
                continue
            try:
                if os.path.getsize(path) > MAX_BYTES:
                    continue
                text = read_text(path)
            except OSError:
                continue
            rp = rel(path, repo_root)
            proj = owner(path)
            low = fn.lower()
            if ext in PROJ_EXT or low == "packages.config":
                pk = re.findall(r"""(?:<PackageReference\b[^>]*?\bInclude|<package\b[^>]*?\bid|<Reference\b[^>]*?\bInclude)\s*=\s*["']([^"',]+)""", text)
                for pid in pk:
                    for t in cat:
                        if t["_packages"] and t["_packages"].search(pid):
                            line = next((i for i, l in enumerate(text.splitlines(), 1) if pid in l), 1)
                            hits[t["id"]].add("package", rp, line, f"package {pid}", proj or rp)
                continue
            lines = text.splitlines()
            if ext in CODE_EXT:
                for t in cat:
                    rx = t["_code"]
                    if not rx or not rx.search(text):
                        continue
                    for i, line in enumerate(lines, 1):
                        if re.match(r"\s*(//|/\*|\*|')", line):
                            continue
                        if rx.search(line):
                            hits[t["id"]].add("code", rp, i, line.strip()[:160], proj)
                            if t["id"] in ("sftp-ftp", "ldap-ad"):
                                for ht in host_tokens(re.sub(r"^.*?(?=(?:s?ftp|ldap)://)", "", line, flags=re.I), t["ports"]):
                                    hits[t["id"]].host(ht["host"], ht["port"], rp, i)
                continue
            if is_docker:
                for i, line in enumerate(lines, 1):
                    if re.match(r"\s*(image\s*:|FROM\s)", line, re.I):
                        for t in cat:
                            if t["_compose_image"] and t["_compose_image"].search(line):
                                hits[t["id"]].add("docker-compose", rp, i, line.strip()[:120], proj)
                continue
            if ext in CONFIG_EXT or ext == ".pubxml":
                for i, line in enumerate(lines, 1):
                    if len(line) > 2000 or re.match(r"\s*(<!--|//|#)", line):
                        continue
                    k = key_of(line)
                    for t in cat:
                        matched_key = bool(t["_config_keys"] and k and t["_config_keys"].search(k))
                        matched_val = bool(t["_config_values"] and t["_config_values"].search(line))
                        if not (matched_key or matched_val):
                            continue
                        if t["id"] == "session-state-server" and not matched_val:
                            continue
                        hits[t["id"]].add("config", rp, i, f"config key: {k}" if matched_key else f"setting pattern: {t['label']}", proj)
                        if t["id"] in ("sql-server", "mysql", "postgresql", "oracle", "mongodb") and not re.search(r"(?i)\b(Data Source|Server|Host|mongodb://)", line):
                            continue
                        for ht in host_tokens(_value_part(line), t["ports"]):
                            hits[t["id"]].host(ht["host"], ht["port"], rp, i)
    # connection strings parsed by scan_repo (provider, host): the most reliable host source for databases
    for c in (facts or {}).get("connection_strings", []):
        prov = (c.get("provider") or "").lower()
        tid = "mysql" if "mysql" in prov else "postgresql" if "npgsql" in prov else "oracle" if "oracle" in prov else "sql-server"
        h = c.get("host")
        if h and not c.get("template"):
            hits[tid].add("connection-string", c["file"], c["line"], f"connection string: {c.get('name')}", owner(os.path.join(repo_root, c["file"])))
            hits[tid].host(h, None, c["file"], c["line"])
    return hits


def finalize(hits):
    out = []
    for tid, h in hits.items():
        if not h.via:
            continue
        via = set(h.via)
        if via == {"config"} and not h.hosts and not any(e["text"].startswith("setting pattern") for e in h.via["config"]):
            continue  # a key name alone, no host and no value pattern: too weak to report
        if via == {"docker-compose"}:
            strength = "local-dev only"
        elif via & {"code", "connection-string"} and via & {"package", "config", "connection-string"}:
            strength = "confirmed (library and use in code or config)"
        elif via & {"code", "connection-string"}:
            strength = "likely (used in code)"
        elif "package" in via:
            strength = "likely (library referenced, use not traced)"
        else:
            strength = "possible (configuration key only)"
        ev = []
        for v in ("connection-string", "code", "package", "config", "docker-compose"):
            for e in h.via.get(v, [])[:3]:
                ev.append({"via": v, **e})
        out.append({"type": tid, "label": h.t["label"], "kind": h.t["kind"], "strength": strength, "found_by": sorted(via), "projects": sorted(h.projects),
                    "files": len(h.files), "hosts": sorted(h.hosts.values(), key=lambda x: (x["host"].lower(), x["port"] or 0)), "evidence": ev[:10],
                    "aws": h.t["aws"], "lift_and_shift": h.t["lift_and_shift"], "ports": h.t["ports"], "server_roles": h.t["server_roles"]})
    return out


# ------------------------------------------------------------------------------------------------ hosting evidence
def hosting_evidence(repo_root, inv, cfg):
    skip = SOURCE_DIR_SKIP | {s.lower() for s in cfg.get("exclude_dirs", [])}
    sig, pipelines = [], []

    def add(os_, kind, strength, file, line, text):
        if len(sig) < 60:
            sig.append({"os": os_, "kind": kind, "strength": strength, "file": file, "line": line, "text": mask(text)[:160]})

    for p in inv["projects"]:
        fam = p.get("framework_family", "")
        if "netfx" in fam and p.get("deployable"):
            add("windows", ".NET Framework", "strong", p["path"], 1, f"{p['name']} targets {', '.join(p.get('target_frameworks', []))}: .NET Framework runs on Windows only")
        if p.get("web_root") and "netfx" in fam:
            add("windows", "IIS web.config", "strong", p["path"], 1, f"{p['name']}: ASP.NET (System.Web) application: IIS on Windows")
        elif p.get("web_root"):
            add("windows", "web.config in modern .NET", "indicative", p["path"], 1, f"{p['name']}: web.config present (IIS hosting module; Kestrel on Linux does not need it)")
        if p.get("type") in ("windows-service", "service", "netcore-worker"):
            add("windows" if p.get("type") != "netcore-worker" else "neutral", f"service project ({p.get('type')})", "indicative", p["path"], 1,
                f"{p['name']} is a service/worker: installed as a Windows service or systemd unit (check the install scripts)")
    for d, dirs, files in os.walk(repo_root):
        dirs[:] = [x for x in dirs if x.lower() not in skip and not x.startswith(".")]
        depth = os.path.relpath(d, repo_root).count(os.sep)
        if depth > 6:
            dirs[:] = []
        for fn in files:
            low, ext = fn.lower(), os.path.splitext(fn)[1].lower()
            path = os.path.join(d, fn)
            rp = rel(path, repo_root)
            if not (ext in (".pubxml", ".service", ".sh", ".ps1", ".bat", ".cmd", ".md", ".txt", ".rtf", ".conf") or low.startswith(("dockerfile", "docker-compose", "jenkinsfile", ".gitlab-ci", "azure-pipelines", "compose"))
                    or low in ("nssm_configuration.md",)):
                continue
            if low.startswith(("jenkinsfile", ".gitlab-ci", "azure-pipelines")):
                pipelines.append(rp)
            try:
                if os.path.getsize(path) > 400_000:
                    continue
                text = read_text(path)
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if ext == ".pubxml":
                    m = re.search(r"<(PublishUrl|MSDeployServiceURL|DeployIisAppPath|WebPublishMethod|RuntimeIdentifier|SiteUrlToLaunchAfterPublish)>([^<]+)<", line)
                    if m:
                        k, v = m.group(1), m.group(2).strip()
                        if k == "RuntimeIdentifier":
                            add("linux" if v.startswith("linux") else "windows", "publish profile runtime", "strong", rp, i, f"publish profile targets {v}")
                        elif k == "PublishUrl" and re.match(r"^[A-Za-z]:\\", v):
                            add("windows", "publish to a drive-letter folder", "indicative", rp, i, f"publishes to {v} (a Windows folder: manual or script-based deployment)")
                        elif k in ("MSDeployServiceURL", "DeployIisAppPath", "WebPublishMethod") and re.search(r"(?i)msdeploy|iis|\.|/", v):
                            add("windows", "Web Deploy / IIS", "strong", rp, i, f"{k}: {v}")
                    continue
                if low.startswith("dockerfile") or low.startswith(("docker-compose", "compose")):
                    if re.match(r"(?i)\s*FROM\s", line):
                        if re.search(r"(?i)windowsservercore|nanoserver|servercore", line):
                            add("windows", "Windows container image", "strong", rp, i, line.strip())
                        elif re.search(r"(?i)mcr\.microsoft\.com/dotnet|alpine|ubuntu|debian", line):
                            add("linux", "Linux container image", "strong", rp, i, line.strip())
                    continue
                if ext == ".service" and re.match(r"\s*ExecStart\s*=", line):
                    add("linux", "systemd unit", "strong", rp, i, "systemd service unit (ExecStart)")
                    break
                if low.startswith(("jenkinsfile", ".gitlab-ci", "azure-pipelines")):
                    if re.search(r"(?i)\b(windows|win-?server|msbuild|iisreset|powershell)\b", line):
                        add("windows", "pipeline step or agent", "indicative", rp, i, line.strip())
                    elif re.search(r"(?i)\b(ubuntu|linux|docker\s+build|\bsh\s+['\"]|apt-get)\b", line):
                        add("linux", "pipeline step or agent", "indicative", rp, i, line.strip())
                    continue
                if ext in (".ps1", ".bat", ".cmd") and re.search(r"(?i)\b(sc\.exe\s+create|sc\s+create|nssm|installutil|iisreset|appcmd|New-WebSite|New-WebAppPool|New-Service|schtasks|Import-Module WebAdministration)\b", line):
                    add("windows", "Windows install / IIS script", "strong", rp, i, line.strip())
                    break
                if ext == ".sh" and re.search(r"(?i)\b(systemctl|apt(-get)?|yum|dnf|nginx|supervisorctl|chmod \+x)\b", line):
                    add("linux", "Linux install script", "strong", rp, i, line.strip())
                    break
                if ext in (".md", ".txt", ".rtf") and re.search(r"(?i)\b(IIS|Windows Server|Windows Service|NSSM|systemd|Ubuntu|nginx|Apache httpd)\b", line) and depth <= 2:
                    k = re.search(r"(?i)\b(IIS|Windows Server|Windows Service|NSSM|systemd|Ubuntu|nginx|Apache httpd)\b", line).group(1)
                    add("windows" if k.lower() in ("iis", "windows server", "windows service", "nssm") else "linux", "documentation mentions " + k, "indicative", rp, i, line.strip())
                    break
    strong = Counter(s["os"] for s in sig if s["strength"] == "strong" and s["os"] in ("windows", "linux"))
    weak = Counter(s["os"] for s in sig if s["strength"] != "strong" and s["os"] in ("windows", "linux"))
    if strong["windows"] and strong["linux"]:
        os_, basis = "mixed", "strong Windows and Linux evidence in different parts of the repository: decide per project"
    elif strong["windows"] or strong["linux"]:
        os_ = "windows" if strong["windows"] else "linux"
        basis = "strong evidence in code (technology or deployment file)"
    elif weak["windows"] or weak["linux"]:
        os_ = "windows" if weak["windows"] >= weak["linux"] else "linux"
        basis = "indicative evidence only (hints in scripts, documents or settings)"
    else:
        os_, basis = "unknown", "no deployment, service or hosting file in the repository"
    deploys = sorted({s["kind"] for s in sig})
    return {"os_inferred": os_, "basis": basis, "status": "inferred from code: unverified until the server OS is confirmed" if os_ != "unknown" else "unknown: ask the client's DevOps team",
            "pipeline_files": pipelines[:10],
            "deployment_files": deploys, "signals": sig}
