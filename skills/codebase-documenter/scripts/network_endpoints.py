"""Network endpoints of a source tree: every outbound destination the code or its configuration names, every inbound
listener it opens, and the code that makes outbound calls. Standard library only; shared by the codebase-documenter
adapter generic-endpoints (docs/reference/network-endpoints.md) and the migration-assessment scanner (network allow-list).

    import network_endpoints as NE
    net = NE.scan(root)            # {"outbound": [...], "inbound": [...], "clients": [...], "files_scanned": n}

outbound  {host, port, scheme, kind, source, key, file, line}   one row per place a destination is named
          source: "url" (a URL literal in code, config, scripts or front end), "config-host" (a bare host / host:port under
          a host-like key: Smtp:Host, Redis:Server, Kafka:BootstrapServers ...), "connection-string" (Server= / Host= /
          Data Source=), "wcf-client" (system.serviceModel client endpoint)
          kind: internal (private IP, single-label or corporate / environment host name), external, external-ip
inbound   {port, scheme, host, source, file, line}   launchSettings, Kestrel endpoints, Urls, ASPNETCORE_URLS / *_PORTS,
          Dockerfile EXPOSE, docker-compose ports, UseUrls / Listen* in code, WCF service addresses, IIS-hosted .svc / .asmx
clients   {tech, file, line, keys}   code that opens an outbound connection (HttpClient, WCF proxies, SmtpClient, FTP, Redis,
          RabbitMQ, Kafka, AWS / Azure SDK clients, LDAP, gRPC, SignalR client, sockets, MSMQ) and the configuration keys
          named next to it, which is how a run-time destination is tied back to the code; "same_app": true for browser calls
          (fetch / jQuery) to a relative URL or @Url.Action: the application calling itself, not an outbound destination
Third-party code: scan(root, skip_dirs, vendored={relative paths}) marks outbound rows found in those files "third_party"
(destinations() keeps the flag only when every evidence is third-party) and drops their client rows.
config_users {key -> [(file, line)]}   code lines that read a configuration key that holds a destination

Values are never returned: only scheme, host and port of a URL (no path, query or user info) and key NAMES.
Regular expressions over text, not a compiler: hosts built at run time are invisible (the client rows show where they are
used), and a literal can sit in dead code. Flags for review, never enforced.
"""
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

MAX_BYTES = 2_500_000
SKIP_DIRS = {".git", ".vs", ".idea", "bin", "obj", "node_modules", "packages", "dist", "build", "out", "target", "vendor", ".venv",
             "venv", "__pycache__", "coverage", "graphify-out", "testresults", "artifacts", "publish"}
TEXT_EXT = {".cs", ".vb", ".fs", ".config", ".json", ".xml", ".yml", ".yaml", ".env", ".properties", ".toml", ".ini", ".ps1", ".psm1",
            ".bat", ".cmd", ".sh", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".cshtml", ".vbhtml", ".razor", ".aspx",
            ".ascx", ".master", ".asax", ".ashx", ".asmx", ".svc", ".wsdl", ".disco", ".svcmap", ".datasource", ".pubxml", ".py",
            ".java", ".kt", ".go", ".rb", ".php", ".sql", ".tf", ".bicep", ".html", ".htm"}
NAMES = re.compile(r"(?i)^(dockerfile.*|docker-compose.*\.ya?ml|compose\.ya?ml|\.env(\..+)?|jenkinsfile)$")
VENDOR = re.compile(r"(?i)(^|/)(wwwroot/lib|scripts/(jquery|bootstrap|modernizr|respond|knockout|angular)|lib/(jquery|bootstrap))|"
                    r"\.min\.(js|css)$|(^|/)(jquery|bootstrap|modernizr|respond|knockout|angular|moment|lodash|signalr)[\w.\-]*\.js$|"
                    r"package-lock\.json$|yarn\.lock$|\.deps\.json$|\.runtimeconfig\.json$|(^|/)packages\.lock\.json$")
CODE = {".cs", ".vb", ".fs", ".java", ".kt", ".go", ".rb", ".php", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue"}
COMMENT = {"c": re.compile(r"^\s*(//|/\*|\*(?!\w)|\*\s)"), "hash": re.compile(r"^\s*#(?!!)"), "vb": re.compile(r"^\s*('|REM\s)", re.I),
           "sql": re.compile(r"^\s*--"), "bat": re.compile(r"^\s*(REM\s|::)", re.I), "xml": re.compile(r"^\s*<!--")}
COMMENT_OF = {".cs": "c", ".fs": "c", ".java": "c", ".kt": "c", ".go": "c", ".php": "c", ".js": "c", ".mjs": "c", ".cjs": "c",
              ".ts": "c", ".tsx": "c", ".jsx": "c", ".vue": "c", ".vb": "vb", ".py": "hash", ".rb": "hash", ".sh": "hash",
              ".ps1": "hash", ".psm1": "hash", ".yml": "hash", ".yaml": "hash", ".properties": "hash", ".toml": "hash",
              ".env": "hash", ".tf": "hash", ".ini": "hash", ".sql": "sql", ".bat": "bat", ".cmd": "bat"}

SCHEME_PORT = {"http": 80, "https": 443, "ws": 80, "wss": 443, "ftp": 21, "ftps": 990, "sftp": 22, "ssh": 22, "ldap": 389,
               "ldaps": 636, "amqp": 5672, "amqps": 5671, "mqtt": 1883, "mqtts": 8883, "redis": 6379, "rediss": 6380,
               "mongodb": 27017, "postgres": 5432, "postgresql": 5432, "mysql": 3306, "sqlserver": 1433, "smtp": 25, "smtps": 465,
               "net.tcp": 808, "grpc": 443, "smb": 445, "aspnet-state": 42424, "kafka": 9092, "nats": 4222, "imap": 143, "imaps": 993, "pop3": 110, "pop3s": 995}
URL = re.compile(r"(?i)(?<![\w.+-])(https?|wss?|net\.tcp|ftps?|sftp|ssh|ldaps?|amqps?|mqtts?|rediss?|mongodb(?:\+srv)?|postgres(?:ql)?|"
                 r"mysql|sqlserver|smtps?|grpc|kafka|nats|imaps?|pop3s?|tcp)://(?:[^\s/@\"'<>]+@)?([A-Za-z0-9_.\-]+|\[[0-9a-fA-F:]+\])(?::(\d{1,5}))?")
IP = re.compile(r"^(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$")
HOSTLIKE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z][A-Za-z0-9\-]{0,62}(?::\d{1,5})?$|"
                      r"^(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?$")
# documentation, schema, CDN and package hosts: never a run-time dependency worth allow-listing
DOC_HOSTS = re.compile(r"(?i)^(localhost|0\.0\.0\.0|\+|\*|.*\.example\.(com|org|net)|example\.(com|org|net)|tempuri\.org|"
                       r"schemas\.[\w.]+|.*\.?w3\.org|go\.microsoft\.com|aka\.ms|json-schema\.org|.*\.?purl\.org|xmlns\.com|"
                       r"(docs|learn|msdn|support|www)\.microsoft\.com|microsoft\.com|(www\.)?asp\.net|github\.com|.*\.githubusercontent\.com|"
                       r"getbootstrap\.com|.*\.?jquery\.(com|org)|jqueryui\.com|modernizr\.com|opensource\.org|(www\.)?apache\.org|"
                       r"(www\.|api\.)?nuget\.org|.*\.?swagger\.io|.*\.?ietf\.org|creativecommons\.org|fonts\.(googleapis|gstatic)\.com|"
                       r"(www\.)?gnu\.org|developer\.mozilla\.org|(www\.)?mozilla\.org|ajax\.aspnetcdn\.com|cdnjs\.cloudflare\.com|"
                       r"cdn\.jsdelivr\.net|unpkg\.com|stackoverflow\.com|.*\.datacontract\.org|semver\.org|spdx\.org|.*\.?xmlsoap\.org|"
                       r"(www\.)?omg\.org|ns\.adobe\.com|(www\.)?iana\.org|dotnet\.microsoft\.com|(www\.)?docker\.com|hub\.docker\.com|"
                       r"mcr\.microsoft\.com|registry\.npmjs\.org|(www\.)?npmjs\.com|pypi\.org|(www\.)?python\.org|keepachangelog\.com|"
                       r"(www\.)?youtube\.com|img\.shields\.io|shields\.io|badge\.fury\.io|.*\.local\.test)$")
PLACEHOLDER_HOST = re.compile(r"(?i)^(url|host|hostname|server|servername|yourserver|myserver|your-?\w+|my-?server|domain|site|foo|bar|test|"
                              r"example|machine|computer|server_?name|host_?name|xxx+|changeme|placeholder)$")
INTERNAL_SUFFIX = re.compile(r"(?i)\.(local|corp|lan|internal|intranet|intra|ad|domain|home|private|priv|loc|int|office)$")
ENV_TOKENS = re.compile(r"(?i)(^|[.\-])(intra|intranet|internal|corp|lan|uat|sit|preprod|pre-prod|staging|stage|lab|qa|infra|onprem|on-prem|dmz)([.\-]|\d|$)")
PUBLIC_TLDS = set("com org net edu gov mil int io co ai app dev cloud info biz me tv us uk eu de fr in jp cn au ca nz sg hk ch nl be es it "
                  "se no dk fi ie at pl pt br mx ru za ae sa kr tw global online site tech xyz store shop blog news media agency solutions "
                  "services systems software digital network group company page aws amazon microsoft google azure".split())

# configuration keys whose value is a destination (leaf of the key path); a scheme is guessed from the whole path
HOST_KEY = re.compile(r"(?i)(^|[_.\-])(host|hostname|host_?name|hosts|server|servername|server_?name|servers|endpoint|address|broker|brokers|"
                      r"brokerlist|bootstrap_?servers|bootstrapservers|url|uri|baseurl|base_?url|baseaddress|base_?address|serviceurl|apiurl|"
                      r"smtp|smtpserver|smtphost|mailserver|ftpserver|ldapserver|redis|connection)$|(host|server|endpoint|url|uri|address)$")
# keys that hold the application's OWN address: inbound, never an outbound destination
SELF_KEY = re.compile(r"(?i)(^|[:._\-])(cookie\w*|domain|redirect\w*|callback\w*|return\w*|postlogout\w*|signedout\w*|logout\w*|"
                      r"allowedorigins?|cors\w*|origins?|allowedhosts|publicurl|siteurl|site_?url|appurl|app_?url|applicationurl|"
                      r"frontendurl|clienturl|selfurl|publicorigin)(:|$)|(^|:)(urls|kestrel)(:|$)")
SCHEME_HINT = [(re.compile(r"(?i)smtp|mail|email"), "smtp"), (re.compile(r"(?i)redis|cache"), "redis"),
               (re.compile(r"(?i)rabbit|amqp"), "amqp"), (re.compile(r"(?i)kafka|bootstrap"), "kafka"),
               (re.compile(r"(?i)mongo"), "mongodb"), (re.compile(r"(?i)ldap|activedirectory|\bad\b"), "ldap"),
               (re.compile(r"(?i)sftp"), "sftp"), (re.compile(r"(?i)unc|share|fileserver|filesrv|files"), "smb"), (re.compile(r"(?i)ftp"), "ftp"), (re.compile(r"(?i)elastic|opensearch"), "https"),
               (re.compile(r"(?i)postgres|npgsql|pgsql"), "postgresql"), (re.compile(r"(?i)mysql"), "mysql"),
               (re.compile(r"(?i)sql|database|\bdb\b"), "sqlserver"), (re.compile(r"(?i)mqtt"), "mqtt"), (re.compile(r"(?i)nats"), "nats")]
CONN_HOST = re.compile(r"(?i)^(data\s*source|server|address|addr|network\s*address|host|hostname|endpoint|endpoints)$")

# outbound client constructions in code (technology label, pattern)
CLIENTS = [("HTTP (HttpClient)", r"\bnew\s+HttpClient\b|\bAddHttpClient\b|\bIHttpClientFactory\b|\bCreateClient\s*\(|\bHttpClient\.\w+Async\b"),
           ("HTTP (WebRequest / WebClient)", r"\bWebRequest\.Create(Http)?\b|\bnew\s+WebClient\b|\bHttpWebRequest\b"),
           ("HTTP (RestSharp / Refit / Flurl)", r"\bnew\s+RestClient\b|\bRestService\.For\b|\bAddRefitClient\b|\.WithUrl\s*\(|\bFlurlClient\b"),
           ("HTTP (fetch / axios / jQuery)", r"\bfetch\s*\(|\baxios(\.\w+)?\s*\(|\$\.(ajax|get|post|getJSON)\s*\("),
           ("SOAP / WCF client", r"\bChannelFactory\s*<|\bClientBase\s*<|\bSoapHttpClientProtocol\b|\bnew\s+\w+(Soap)?Client\s*\(\s*\"?\w*Endpoint"),
           ("SMTP", r"\bnew\s+SmtpClient\b|\bSmtpClient\s*\(|\bMailKit\b|\bSendGridClient\b|\bAmazonSimpleEmailService\w*Client\b"),
           ("FTP / SFTP", r"\bFtpWebRequest\b|\bnew\s+FtpClient\b|\bAsyncFtpClient\b|\bnew\s+SftpClient\b|\bWinSCP\b|\bSessionOptions\b"),
           ("Redis", r"\bConnectionMultiplexer\.Connect\w*\b|\bAddStackExchangeRedisCache\b|\bRedisCache\b"),
           ("RabbitMQ / AMQP", r"\bnew\s+ConnectionFactory\b|\bUsingRabbitMq\b|\bRabbitMQ\b"),
           ("Kafka", r"\bProducerBuilder\s*<|\bConsumerBuilder\s*<|\bProducerConfig\b|\bConsumerConfig\b"),
           ("Azure SDK", r"\bnew\s+(BlobServiceClient|ServiceBusClient|EventHubProducerClient|QueueClient|SecretClient|CosmosClient|TableServiceClient)\b"),
           ("AWS SDK", r"\bnew\s+Amazon\w+Client\b|\bAddAWSService\s*<"),
           ("gRPC", r"\bGrpcChannel\.ForAddress\b|\bAddGrpcClient\b"),
           ("SignalR client", r"\bnew\s+HubConnectionBuilder\b"),
           ("LDAP / Active Directory", r"\bnew\s+LdapConnection\b|\bnew\s+DirectoryEntry\b|\bnew\s+PrincipalContext\b|\bDirectorySearcher\b"),
           ("TCP / UDP socket", r"\bnew\s+(TcpClient|UdpClient)\b|\bnew\s+Socket\s*\("),
           ("MSMQ", r"\bnew\s+MessageQueue\b|\bMessageQueue\.(Create|Exists)\b"),
           ("Elasticsearch / OpenSearch", r"\bnew\s+(ElasticClient|ElasticsearchClient|OpenSearchClient)\b"),
           ("MongoDB", r"\bnew\s+MongoClient\b")]
CLIENT_RX = [(t, re.compile(p)) for t, p in CLIENTS]
# a browser call to the application itself: a relative URL string ('/Charting/Save', 'api/orders'), or a URL built by the
# server-side view helpers (@Url.Action, Url.Content, ResolveUrl)
SAME_APP = re.compile(r"""(?:\burl\s*:\s*|\bfetch\s*\(\s*|\$\.(?:ajax|get|post|getJSON)\s*\(\s*)(?:[\w.]+\s*\+\s*)?["'`](?![a-z][\w+.-]*:|//|\$\{)"""
                      r"""|@?Url\.(?:Action|Content|RouteUrl)\s*\(|ResolveUrl\s*\(""", re.I)
# configuration keys named in code: config["A:B"], GetValue<T>("A:B"), GetSection("A"), GetConnectionString("X"), AppSettings["K"]
KEY_IN_CODE = re.compile(r"""(?:Configuration|config|_config|_configuration|cfg|settings|AppSettings|ConnectionStrings)\s*\[\s*["']([\w:.\-]+)["']\s*\]|"""
                         r"""(?:GetValue\s*<[^>]+>|GetValue\s*\(\s*Of\s+\w+\s*\)|GetSection|GetConnectionString|GetRequiredSection|"""
                         r"""AppSettings|ConnectionStrings)\s*\(\s*["']([\w:.\-]+)["']""", re.I)  # VB: AppSettings("Key")
# \\server\share (also escaped "\\\\server\\share" in C# literals): SMB to a file server
UNC = re.compile(r"(?<![\w\\])\\{2,4}([A-Za-z0-9][A-Za-z0-9.\-]{1,62})\\{1,2}[\w$.\-]+")
INBOUND_CODE = re.compile(r"""\.UseUrls\s*\(\s*["']([^"']+)["']|\.Listen(?:Any|Local)?IP\s*\(\s*(\d{2,5})|\.Listen\s*\(\s*IPAddress\.\w+\s*,\s*(\d{2,5})|"""
                          r"""\bapp\.Run\s*\(\s*["'](https?://[^"']+)["']|\.listen\s*\(\s*(\d{2,5})""")


SCRIPT_EXTS = {".ps1", ".psm1", ".psd1", ".bat", ".cmd", ".sh", ".bash"}
SCRIPT_MESSAGE = re.compile(r"(?i)^\s*(@?echo\b|Write-\w+|throw\b|Read-Host\b|Out-Host\b|printf?\b|Show-\w+)")

ROLES = [  # (pattern over scheme / source / key / URL path, role) - first match wins
    (r"^(smtps?|imaps?|pop3s?)\b|mail|smtp|sendgrid|mailgun|\bses\b|email\.[\w-]+\.amazonaws", "Mail server (SMTP)"),
    (r"^(sftp|ftps?|ssh)\b|sftp|\bftp", "File transfer (SFTP / FTP)"),
    (r"^smb\b|unc-path", "File share (SMB)"),
    (r"^ldaps?\b|ldap|activedirectory|domaincontroller", "Directory (LDAP / Active Directory)"),
    (r"reportserver|reportservice|reportexecution|ssrs|/reports?\b|crystal", "Report server (SSRS / reporting)"),
    (r"^aspnet-state\b|session-state", "Session state server (ASP.NET)"),
    (r"^(sqlserver|postgres(ql)?|mysql|mongodb(\+srv)?)\b", "Database"),
    (r"^rediss?\b|redis|memcache|elasticache", "Cache (Redis)"),
    (r"^(amqps?|kafka|mqtts?|nats)\b|rabbit|servicebus|kafka|activemq|\bqueue|\bsqs\b|\bsns\b|eventhub", "Message broker / queue"),
    (r"authority|identity|oidc|oauth|openid|\bsts\b|adfs|\blogin\.|\bsso\b|saml|issuer|okta|auth0|keycloak|cognito", "Identity provider"),
    (r"elastic|opensearch|\bseq\b|splunk|loki|datadog|newrelic|applicationinsights|logstash|graylog|sentry|otlp|opentelemetry", "Logging / monitoring"),
    (r"payment|stripe|paypal|braintree|adyen|worldpay|authorize\.net", "Payment gateway"),
    (r"\bs3\b|s3\.|blob\.core|\bstorage\b|bucket", "Object storage"),
    (r"twilio|\bsms\b|nexmo|vonage", "SMS / messaging"),
    (r"^net\.tcp\b|wcf-client|\.svc\b|\.asmx\b|soap|wsdl", "SOAP / WCF service"),
    (r"^grpc\b", "gRPC service"),
    (r"^wss?\b", "WebSocket"),
    (r"^https?\b", "HTTP service / API"),
]
ROLE_RX = [(re.compile(p, re.I), r) for p, r in ROLES]


def role_of(scheme, source, key, hint):
    text = f"{scheme} {source} {key} {hint}"
    for rx, r in ROLE_RX:
        if rx.search(text):
            return r
    return "Network service"


def host_kind(host):
    h = host.lower().strip("[]")
    if IP.match(h):
        a, b = [int(x) for x in h.split(".")[:2]]
        private = a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) or (a == 169 and b == 254) or a == 100 and 64 <= b <= 127
        return "internal" if private else "external-ip"
    labels = h.split(".")
    if len(labels) == 1 or INTERNAL_SUFFIX.search(h) or (labels[-1] not in PUBLIC_TLDS and len(labels[-1]) != 2) or ENV_TOKENS.search(h):
        return "internal"
    return "external"


def usable_host(host):
    h = host.lower().strip("[]")
    if not h or DOC_HOSTS.match(h) or PLACEHOLDER_HOST.match(h) or h.startswith(("127.", "0.", "255.")) or h in ("::1", "[::1]"):
        return False
    if IP.match(h) and (h.endswith(".0.0") or all(int(o) < 10 for o in h.split("."))):
        return False  # version-like dotted numbers (2.3.2.0, 1.1.0.1)
    return "{" not in h and "$" not in h and "%" not in h and not h.endswith((".dll", ".exe", ".cs", ".json", ".xml", ".js", ".css"))


def scheme_for(path):
    for rx, s in SCHEME_HINT:
        if rx.search(path):
            return s
    return "tcp"


def split_host_port(value):
    v = value.strip()
    if v.startswith("[") and "]" in v:
        h, _, rest = v[1:].partition("]")
        return h, int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else None
    if v.count(":") == 1:
        h, p = v.split(":")
        return h, int(p) if p.isdigit() else None
    return v, None


class Scan:
    def __init__(self, root, skip_dirs=None, vendored=None):
        self.root = root
        self.vendored = vendored or set()
        self.skip = SKIP_DIRS | {s.lower() for s in (skip_dirs or [])}
        self.outbound, self.inbound, self.clients = [], [], []
        self.dest_keys = set()
        self.drives = []  # drive letters other than C: in configuration / code literals: often mapped network drives
        self.key_reads = defaultdict(list)  # key name in code -> [(file, line)]
        self.seen = set()
        self.files = 0

    # ------------------------------------------------------------ helpers
    def out(self, host, port, scheme, source, file, line, key="", hint=""):
        host = host.strip().strip(".").lower()
        if not usable_host(host):
            return
        scheme = scheme.lower()
        default = not port
        port = port or SCHEME_PORT.get(scheme.replace("+srv", ""))
        k = (host, port, file, line)
        if k in self.seen:  # a URL under a config key is found twice: by the key (kept) and by the line scan
            return
        self.seen.add(k)
        self.outbound.append({"host": host, "port": port, "scheme": scheme, "kind": host_kind(host), "source": source, "key": key,
                              "file": file, "line": line, "port_default": default, "role": role_of(scheme, source, key, f"{host} {hint}"),
                              "third_party": file in self.vendored})
        if key:
            self.dest_keys.add(key)

    def inb(self, port, scheme, source, file, line, host="", app=""):
        try:
            port = int(port) if port not in (None, "") else None
        except ValueError:
            return
        k = ("in", port, scheme, file, app)  # one row per port and file: the http and https launch profiles repeat the http port
        if k not in self.seen:
            self.seen.add(k)
            self.inbound.append({"port": port, "scheme": scheme, "host": host, "source": source, "file": file, "line": line, "app": app})

    def inbound_url(self, url, source, file, line, app=""):
        for part in re.split(r"[;,\s]+", url):
            m = re.match(r"(?i)(https?)://([^/:]+|\[[^\]]+\])(?::(\d+))?", part.strip())
            if m:
                self.inb(m.group(3) or SCHEME_PORT[m.group(1).lower()], m.group(1).lower(), source, file, line, m.group(2), app)

    @staticmethod
    def line_of(text, needle, start=0):
        i = text.find(needle, start) if needle else -1
        return text.count("\n", 0, i) + 1 if i >= 0 else 1

    # ------------------------------------------------------------ walk
    def run(self):
        for d, dirs, files in os.walk(self.root):
            dirs[:] = sorted(x for x in dirs if x.lower() not in self.skip and not x.startswith("."))
            for fn in sorted(files):
                ext = os.path.splitext(fn)[1].lower()
                if ext not in TEXT_EXT and not NAMES.match(fn):
                    continue
                path = os.path.join(d, fn)
                rp = os.path.relpath(path, self.root).replace("\\", "/")
                if VENDOR.search(rp):
                    continue
                try:
                    if os.path.getsize(path) > MAX_BYTES:
                        continue
                    text = open(path, encoding="utf-8-sig", errors="replace").read()
                except OSError:
                    continue
                self.files += 1
                self.file(rp, fn, ext, text)
        return self.result()

    def file(self, rp, fn, ext, text):
        low = fn.lower()
        inbound_lines = set()
        if ext == ".config" or ext in (".xml", ".pubxml") and "<configuration" in text[:4000]:
            inbound_lines = self.xml_config(rp, text)
        elif ext == ".json":
            self.json_config(rp, low, text)
        elif ext in (".env", ".properties", ".ini") or low.startswith(".env"):
            self.flat_config(rp, text, "=")
        elif ext in (".yml", ".yaml"):
            self.yaml_config(rp, low, text)
        if low.startswith("dockerfile"):
            self.dockerfile(rp, text)
        if ext in (".svc", ".asmx"):
            self.inb(None, "http(s)", "IIS-hosted service (" + ext + "): port from the IIS site binding", rp, 1)
        if ext in CODE:
            self.code(rp, ext, text)
        cm = COMMENT.get(COMMENT_OF.get(ext, ""))
        for i, line in enumerate(text.splitlines(), 1):
            if "\\\\" in line and not (cm and cm.match(line)) and ext not in (".md", ".sql"):
                for m in UNC.finditer(line):
                    h = m.group(1)
                    if not re.fullmatch(r"(?i)\?|\.|localhost|wsl\$|wsl\.localhost|tsclient|[a-z]", h) and not re.fullmatch(r"\d+", h):
                        self.out(h, None, "smb", "unc-path", rp, i)
            if ext in (".cs", ".vb") and not (cm and cm.match(line)):
                for dm in re.finditer(r'(?:@"|")([D-Zd-z]):\\', line):  # "Z:\\exports" / @"Z:\exports" in a string literal
                    self.drives.append({"drive": dm.group(1).upper() + ":", "key": "", "file": rp, "line": i})
            if "://" not in line or i in inbound_lines or (cm and cm.match(line)) or re.search(r"(?i)xmlns|schemaLocation|<!DOCTYPE|\$schema", line):
                continue
            if ext in SCRIPT_EXTS and SCRIPT_MESSAGE.match(line):
                continue  # Write-Host / echo / throw: a help or download link printed to the user, not a connection
            if ext in (".cs", ".vb") and line.lstrip().startswith(("///", "'''", "[assembly:", "<Assembly:")):
                continue
            for m in URL.finditer(line):
                scheme = m.group(1).lower()
                if scheme == "tcp" and ext not in (".config", ".json", ".yml", ".yaml", ".env", ".properties", ".cs", ".vb"):
                    continue
                self.out(m.group(2), int(m.group(3)) if m.group(3) else None, scheme, "url", rp, i, hint=line[m.end():m.end() + 60])

    # ------------------------------------------------------------ config formats
    def config_value(self, rp, line, key, value, port_hint=None):
        """A configuration value: a URL is found by the line scan; a bare host or host:port under a host-like key is a destination."""
        if isinstance(value, str) and SELF_KEY.search(key):  # the application's own address (cookie domain, redirect URI, CORS origin)
            for m in URL.finditer(value):
                s = m.group(1).lower()
                self.seen.add((m.group(2).lower(), int(m.group(3)) if m.group(3) else SCHEME_PORT.get(s), rp, line))  # not by the line scan either
            return
        if not isinstance(value, str) or "://" in value:
            if isinstance(value, str) and "://" in value:
                m = URL.search(value)
                if m:
                    self.dest_keys.add(key)
                    self.out(m.group(2), int(m.group(3)) if m.group(3) else None, m.group(1), "url", rp, line, key, value[m.end():m.end() + 60])
            return
        dm = re.match(r"^\s*([D-Zd-z]):\\", value)
        if dm:
            self.drives.append({"drive": dm.group(1).upper() + ":", "key": key, "file": rp, "line": line})
            return
        u = UNC.search(value)
        if u:
            self.out(u.group(1), None, "smb", "unc-path", rp, line, key)
            return
        leaf = re.split(r"[:.]", key)[-1]
        if not HOST_KEY.search(leaf):
            return
        for part in re.split(r"[,;\s]+", value.strip()):
            if HOSTLIKE.match(part):
                h, p = split_host_port(part)
                self.out(h, p or port_hint, scheme_for(key), "config-host", rp, line, key)
            elif part and "." not in part and re.fullmatch(r"[A-Za-z][\w\-]{2,}(:\d{1,5})?", part) and re.search(r"(?i)(host|server|broker)", leaf) \
                    and not re.search(r"(?i)^(true|false|none|null|default|local|auto)$", part):
                h, p = split_host_port(part)  # single-label server name (SQLPROD01, mailhub): internal by definition
                self.out(h, p, scheme_for(key), "config-host", rp, line, key)

    def connection_string(self, rp, line, name, cs, provider=""):
        parts = {}
        for kv in cs.split(";"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                parts[k.strip().lower()] = v.strip().strip("'\"")
        if "provider connection string" in parts:  # EF6 metadata wrapper
            inner = re.search(r'(?i)provider connection string\s*=\s*"?([^"]*)', cs)
            if inner:
                return self.connection_string(rp, line, name, inner.group(1).replace("&quot;", ""), provider)
        server = next((v for k, v in parts.items() if CONN_HOST.match(k)), "")
        if not server:
            first = cs.split(",")[0].strip()  # StackExchange.Redis: "host:6379,password=…,ssl=True"
            if HOSTLIKE.match(first) or re.fullmatch(r"[A-Za-z][\w\-]+:\d{2,5}", first):
                h, p = split_host_port(first)
                self.out(h, p, "redis" if re.search(r"(?i)redis|cache", name + cs) else scheme_for(name), "connection-string", rp, line, name)
            return
        server = re.sub(r"(?i)^tcp:", "", server)
        low = server.lower()
        if "(localdb)" in low or low in (".", "(local)", "localhost", "127.0.0.1") or low.startswith((".\\", "(local)\\", "localhost\\")):
            return
        port = parts.get("port")
        hostpart = re.split(r"\\", server)[0]
        m = re.match(r"^(.*?)[,:](\d{2,5})$", hostpart)
        if m:
            hostpart, port = m.group(1), m.group(2)
        if re.search(r"(?i)npgsql|postgres", provider + name) or ("host" in parts and ("username" in parts or "port" in parts)):
            scheme = "postgresql"
        elif re.search(r"(?i)mysql", provider + name) or "uid" in parts and "port" in parts and "initial catalog" not in parts:
            scheme = "mysql"
        elif re.search(r"(?i)oracle", provider) or "(description=" in low:
            return  # TNS descriptors: hosts inside are rare in .NET estates; left to the reviewer
        else:
            scheme = "sqlserver"
        for h in hostpart.split(","):
            self.out(h, int(port) if port and str(port).isdigit() else None, scheme, "connection-string", rp, line, name)

    def xml_config(self, rp, text):
        """web.config / app.config: appSettings, connectionStrings, WCF client (outbound) and service (inbound) endpoints."""
        inbound_lines = set()
        try:
            root = ET.fromstring(text.encode("utf-8"))
        except ET.ParseError:
            return inbound_lines
        settings = {a.get("key", "").lower(): a.get("value") or "" for a in root.iter("add") if a.get("key")}
        for add in root.iter("add"):
            if add.get("connectionString") is not None and add.get("name"):
                self.connection_string(rp, self.line_of(text, f'"{add.get("name")}"'), add.get("name"), add.get("connectionString"),
                                       add.get("providerName", ""))
            elif add.get("key") and add.get("value") is not None:
                pk = re.sub(r"(?i)(host|hostname|server|address)$", "port", add.get("key"))  # SftpHost + SftpPort
                sib = settings.get(pk.lower(), "") if pk != add.get("key") else ""
                self.config_value(rp, self.line_of(text, f'"{add.get("key")}"'), add.get("key"), add.get("value"), int(sib) if sib.isdigit() else None)
            if add.get("baseAddress"):
                ln = self.line_of(text, add.get("baseAddress"))
                inbound_lines.add(ln)
                self.inbound_url(add.get("baseAddress"), "WCF service base address", rp, ln)
        handled = {"key", "value", "name", "connectionString", "providerName", "address", "baseAddress", "binding", "contract"}

        def walk(el, path):
            tag = el.tag.split("}")[-1]
            here = f"{path}/{tag}" if path else ("" if tag == "configuration" else tag)
            here = here.lstrip("/")
            port = el.get("port") if (el.get("port") or "").isdigit() else None
            for attr, val in el.attrib.items():
                a = attr.split("}")[-1]
                if a != "connectionString" and a.lower().endswith("connectionstring") and val:  # <sessionState stateConnectionString=…>
                    ln = self.line_of(text, f'{attr}="')
                    st = re.match(r"(?i)\s*tcpip\s*=\s*([^:;\s]+)(?::(\d+))?", val)
                    if st:
                        self.out(st.group(1), int(st.group(2)) if st.group(2) else None, "aspnet-state", "session-state", rp, ln, f"{here}:{a}")
                    else:
                        self.connection_string(rp, ln, f"{here}:{a}", val)
                    continue
                if a not in handled and val and HOST_KEY.search(a):
                    self.config_value(rp, self.line_of(text, f'{attr}="{val}"'), f"{here}:{a}", val, int(port) if port else None)
            if HOST_KEY.search(tag) and el.get("value") and tag != "add":
                self.config_value(rp, self.line_of(text, el.get("value")), here, el.get("value"))
            for ch in el:
                walk(ch, here)
        walk(root, "")
        for sm in root.iter("system.serviceModel"):
            for client in sm.iter("client"):
                for ep in client.iter("endpoint"):
                    m = URL.search(ep.get("address") or "")
                    if m:
                        self.out(m.group(2), int(m.group(3)) if m.group(3) else None, m.group(1), "wcf-client", rp,
                                 self.line_of(text, ep.get("address")), ep.get("name") or ep.get("contract") or "")
            for services in sm.iter("services"):
                for ep in services.iter("endpoint"):
                    addr = ep.get("address") or ""
                    if "://" in addr:
                        ln = self.line_of(text, addr)
                        inbound_lines.add(ln)
                        self.inbound_url(addr, "WCF service endpoint", rp, ln)
        return inbound_lines

    def json_config(self, rp, low, text):
        try:
            obj = json.loads(re.sub(r"(?m)^\s*//.*$", "", text))
        except ValueError:
            return
        if not isinstance(obj, dict):
            return
        if low == "launchsettings.json":
            for name, prof in (obj.get("profiles") or {}).items():
                if isinstance(prof, dict):
                    if prof.get("applicationUrl"):
                        self.inbound_url(prof["applicationUrl"], f"launchSettings profile {name} (local development)", rp,
                                         self.line_of(text, prof["applicationUrl"]))
                    env = prof.get("environmentVariables") or {}
                    for k in ("ASPNETCORE_URLS", "ASPNETCORE_HTTP_PORTS", "ASPNETCORE_HTTPS_PORTS"):
                        if isinstance(env.get(k), str):
                            self.env_listener(k, env[k], f"launchSettings profile {name}", rp, self.line_of(text, k))
            iis = (obj.get("iisSettings") or {}).get("iisExpress") or {}
            if isinstance(iis, dict) and iis.get("applicationUrl"):
                self.inbound_url(iis["applicationUrl"], "IIS Express (local development)", rp, self.line_of(text, iis["applicationUrl"]))
            return
        cs = obj.get("ConnectionStrings")
        if isinstance(cs, dict):
            for name, val in cs.items():
                if isinstance(val, str):
                    self.connection_string(rp, self.line_of(text, f'"{name}"'), name, val)
        kes = (obj.get("Kestrel") or {}).get("Endpoints") if isinstance(obj.get("Kestrel"), dict) else None
        if isinstance(kes, dict):
            for name, ep in kes.items():
                if isinstance(ep, dict) and isinstance(ep.get("Url"), str):
                    self.inbound_url(ep["Url"], f"Kestrel endpoint {name}", rp, self.line_of(text, ep["Url"]))
        if isinstance(obj.get("Urls"), str):
            self.inbound_url(obj["Urls"], "Urls setting", rp, self.line_of(text, '"Urls"'))

        def walk(o, path, start):
            hint = next((int(v) for k, v in o.items() if isinstance(k, str) and k.lower() == "port" and str(v).isdigit()), None)                 if isinstance(o, dict) else None
            for k, v in (o.items() if isinstance(o, dict) else enumerate(o) if isinstance(o, list) else []):
                p = f"{path}:{k}" if path else str(k)
                if p.split(":")[0].lower() in ("connectionstrings", "kestrel", "logging", "$schema") or p == "Urls":
                    continue
                if isinstance(v, str):
                    ln = self.line_of(text, f'"{k}"', start) if isinstance(k, str) else self.line_of(text, v, start)
                    self.config_value(rp, ln, p, v, hint)
                elif isinstance(v, (dict, list)):
                    pos = text.find(f'"{k}"', start) if isinstance(k, str) else -1
                    walk(v, p, pos if pos >= 0 else start)
        walk(obj, "", 0)

    def flat_config(self, rp, text, sep):
        for i, line in enumerate(text.splitlines(), 1):
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][\w.\-:]*)\s*[=:]\s*['\"]?([^'\"#\s]*)", line)
            if m and not line.lstrip().startswith(("#", ";")):
                k, v = m.group(1), m.group(2)
                if k.upper() in ("ASPNETCORE_URLS", "ASPNETCORE_HTTP_PORTS", "ASPNETCORE_HTTPS_PORTS"):
                    self.env_listener(k.upper(), v, "environment file", rp, i)
                else:
                    self.config_value(rp, i, k.replace("__", ":"), v)

    def yaml_config(self, rp, low, text):
        compose = low.startswith(("docker-compose", "compose."))
        if re.search(r"(?m)^kind:\s*Ingress\b", text):
            return  # Kubernetes Ingress hosts are inbound names, not destinations
        stack, in_ports, service = [], False, ""
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#") or not line.strip():
                continue
            ind = len(line) - len(line.lstrip())
            if compose:
                if re.match(r"^\s*ports\s*:\s*$", line):
                    in_ports, ports_ind = True, ind
                    continue
                if in_ports:
                    m = re.match(r"^\s*-\s*['\"]?([\d.:]+?)(?:/(tcp|udp))?['\"]?\s*$", line)
                    if m and ind > ports_ind - 1:
                        parts = m.group(1).split(":")  # "8080:80", "127.0.0.1:8080:80", "80"
                        pub, cont = (parts[-2], parts[-1]) if len(parts) > 1 else (parts[0], None)
                        self.inb(pub, m.group(2) or "tcp", f"docker-compose service {service or '?'}: published port"
                                 + (f" (container port {cont})" if cont else ""), rp, i, app=f"compose service {service}" if service else "")
                        continue
                    in_ports = False
            m = re.match(r"^(\s*)-?\s*([A-Za-z_][\w.\-]*)\s*[:=]\s*['\"]?([^'\"#]*?)['\"]?\s*$", line)
            if not m:
                continue
            while stack and stack[-1][0] >= ind:
                stack.pop()
            k, v = m.group(2), m.group(3).strip()
            stack.append((ind, k))
            if compose and len(stack) == 2 and stack[0][1] == "services":
                service = k
            if k.upper() in ("ASPNETCORE_URLS", "ASPNETCORE_HTTP_PORTS", "ASPNETCORE_HTTPS_PORTS"):
                self.env_listener(k.upper(), v, "compose / pipeline environment" if compose else "YAML setting", rp, i)
            elif v:
                self.config_value(rp, i, ":".join(s[1] for s in stack).replace("__", ":"), v)

    def dockerfile(self, rp, text):
        # the application the image runs: ENTRYPOINT ["dotnet", "X.dll"], else the project it publishes
        m = re.search(r'(?im)^\s*(?:ENTRYPOINT|CMD)\b.*?([\w.\-]+)\.dll', text) or re.search(r"(?i)dotnet\s+publish\s+\S*?([\w.\-]+)\.(?:cs|vb|fs)proj", text)
        app = m.group(1) if m else ""
        for i, line in enumerate(text.splitlines(), 1):
            m = re.match(r"(?i)^\s*EXPOSE\s+(.+)$", line)
            if m:
                for p in m.group(1).split():
                    pm = re.match(r"(\d{2,5})(?:/(tcp|udp))?$", p)
                    if pm:
                        self.inb(pm.group(1), pm.group(2) or "tcp", "Dockerfile EXPOSE", rp, i, app=app)
            m = re.match(r"(?i)^\s*ENV\s+(ASPNETCORE_URLS|ASPNETCORE_HTTP_PORTS|ASPNETCORE_HTTPS_PORTS)[\s=]+[\"']?([^\"'\s]+)", line)
            if m:
                self.env_listener(m.group(1).upper(), m.group(2), "Dockerfile ENV", rp, i, app)

    def env_listener(self, key, value, source, rp, line, app=""):
        if key == "ASPNETCORE_URLS":
            self.inbound_url(value, f"{source}: ASPNETCORE_URLS", rp, line, app)
        else:
            for p in re.split(r"[;,\s]+", value):
                if p.isdigit():
                    self.inb(p, "https" if "HTTPS" in key else "http", f"{source}: {key}", rp, line, app=app)

    # ------------------------------------------------------------ code
    def code(self, rp, ext, text):
        cm = COMMENT.get(COMMENT_OF.get(ext, ""))
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if cm and cm.match(line):
                continue
            for m in KEY_IN_CODE.finditer(line):
                self.key_reads[m.group(1) or m.group(2)].append((rp, i))
            for t, rx in CLIENT_RX:
                if rx.search(line):
                    if t.startswith("HTTP (fetch") and ext not in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue"):
                        continue
                    def found(txt):
                        return (sorted({a or b for a, b in KEY_IN_CODE.findall(txt)}),
                                sorted({f"{m.group(1).lower()}://{m.group(2).lower()}" for m in URL.finditer(txt) if usable_host(m.group(2))}))
                    if rp in self.vendored:  # a library's own calls (jszip, summernote ...) are not the application's
                        break
                    keys, urls = found(line)
                    if not keys and not urls:  # var url = config["X"]; var http = new HttpClient { BaseAddress = new Uri(url) }
                        keys, urls = found(" ".join(x for x in lines[max(0, i - 3):i - 1] if not (cm and cm.match(x))
                                                    and not any(r.search(x) for _, r in CLIENT_RX)))  # not another call's address
                    row = {"tech": t, "file": rp, "line": i, "keys": keys, "literals": urls}
                    if t.startswith("HTTP (fetch") and not urls and SAME_APP.search(" ".join(lines[i - 1:i + 4])):
                        row["same_app"] = True  # $.ajax({ url: '/Charting/Save' }) / fetch('@Url.Action(...)'): calls this application
                    self.clients.append(row)
                    break
            for m in INBOUND_CODE.finditer(line):
                if m.group(1) or m.group(4):
                    self.inbound_url(m.group(1) or m.group(4), "code (UseUrls / app.Run)", rp, i)
                else:
                    self.inb(m.group(2) or m.group(3) or m.group(5), "tcp", "code (Listen)", rp, i)

    # ------------------------------------------------------------ result
    def result(self):
        users = {}
        for key in self.dest_keys:
            parts = re.split(r"[:.]", key)
            hits = list(self.key_reads.get(key, []))
            if len(parts) > 1:  # GetSection("Partner") + options binding, or the leaf alone when it is distinctive
                hits += self.key_reads.get(":".join(parts[:-1]), [])
                hits += [h for k, v in self.key_reads.items() if k == parts[-1] and len(parts[-1]) > 4 for h in v]
            users[key] = sorted(set(hits))
        return {"outbound": sorted(self.outbound, key=lambda e: (e["host"], e["port"] or 0, e["file"], e["line"])),
                "inbound": sorted(self.inbound, key=lambda e: (e["file"], e["line"])),
                "clients": self.clients, "config_users": users, "drives": self.drives, "files_scanned": self.files}


def scan(root, skip_dirs=None, vendored=None):
    return Scan(root, skip_dirs, vendored).run()


def destinations(net):
    """Outbound rows grouped by (host, port, scheme) for allow-lists: kind, sources, keys, files, first evidence."""
    groups = {}
    for e in net["outbound"]:
        g = groups.setdefault((e["host"], e["port"], e["scheme"]), {"host": e["host"], "port": e["port"], "scheme": e["scheme"],
                                                                   "kind": e["kind"], "sources": set(), "keys": set(), "files": [], "evidence": [],
                                                                   "port_default": True, "third_party": True})
        g["port_default"] = g["port_default"] and e.get("port_default", False)
        g["third_party"] = g["third_party"] and e.get("third_party", False)
        g["sources"].add(e["source"])
        if g.get("role") in (None, "HTTP service / API", "Network service"):
            g["role"] = e.get("role") or g.get("role")
        if e["key"]:
            g["keys"].add(e["key"])
        if e["file"] not in g["files"]:
            g["files"].append(e["file"])
        g["evidence"].append(f"{e['file']}:{e['line']}")
        g.setdefault("_tp", set()).update([e["file"]] if e.get("third_party") else [])
    out = []
    for g in groups.values():
        tp = g.pop("_tp", set())
        if tp and not g["third_party"]:  # named by the application too: cite the application's files, not the library copies
            g["files"] = [f for f in g["files"] if f not in tp]
            g["evidence"] = [x for x in g["evidence"] if x.rsplit(":", 1)[0] not in tp]
        g["sources"], g["keys"] = sorted(g["sources"]), sorted(g["keys"])
        g["users"] = sorted({u for k in g["keys"] for u in net.get("config_users", {}).get(k, [])})
        out.append(g)
    return sorted(out, key=lambda g: ({"internal": 0, "external-ip": 1}.get(g["kind"], 2), g["host"], g["port"] or 0))


if __name__ == "__main__":
    import sys
    r = scan(sys.argv[1] if len(sys.argv) > 1 else ".")
    for g in destinations(r):
        print(f"OUT {g['kind']:<12} {g['scheme']}://{g['host']}:{g['port'] or '?'}  keys={','.join(g['keys']) or '-'}  {g['evidence'][0]}"
              + (f" (+{len(g['evidence']) - 1})" if len(g["evidence"]) > 1 else ""))
    for e in r["inbound"]:
        print(f"IN  {e['scheme']}:{e['port'] or '?'}  {e['source']}  {e['file']}:{e['line']}")
    print(f"{len(r['clients'])} outbound client call sites; {r['files_scanned']} files")
