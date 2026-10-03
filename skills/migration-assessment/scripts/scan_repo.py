"""Run every deterministic migration check on one repository (or all) and write evidence-backed findings.

    python <skill>/scripts/scan_repo.py --repo NAME | --all [--force] [--online | --offline]

Needs discover_estate.py first. Writes:
  assessment/findings/<repo>.json   findings: rule, category, severity, confidence, project, occurrences, evidence (file:line, masked)
  assessment/scan/<repo>.json       scan facts: files scanned per type, endpoints, connection strings (no secrets), packages,
                                    tests, case-mismatch checks, artefacts, category coverage (what was checked)
Engines: line rules (data/rules.json), package map (data/package_map.json, plus api.nuget.org when online), config parser
(connection strings, appSettings secrets: key names only), endpoint extractor (URLs/IPs/UNC: internal vs external),
path-case checker (literals vs files on disk), structural checks (project format, TFM support, artefacts, tests, git).
Evidence snippets never contain secret values (see _common.mask).
"""
import argparse
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from _common import (OUT, SOURCE_DIR_SKIP, data, load_config, load_state, mark, mask, read_json, read_text, rel, slug,
                     utf8_stdout, write_json)

MAX_EVIDENCE = 25
MAX_FILE_BYTES = 2_500_000
TYPE_BY_EXT = {".cs": "cs", ".vb": "vb", ".aspx": "markup", ".ascx": "markup", ".master": "markup", ".asax": "markup", ".ashx": "markup",
               ".asmx": "markup", ".svc": "markup", ".cshtml": "markup", ".vbhtml": "markup", ".razor": "markup", ".config": "config",
               ".sql": "sql", ".csproj": "proj", ".vbproj": "proj", ".fsproj": "proj", ".ps1": "script", ".psm1": "script", ".bat": "script",
               ".cmd": "script", ".vbs": "script", ".js": "js", ".xslt": "xml", ".xsl": "xml", ".pubxml": "xml", ".targets": "proj", ".props": "proj"}
CI_NAMES = re.compile(r"(?i)^(azure-pipelines[\w.-]*\.ya?ml|jenkinsfile|\.gitlab-ci\.yml|buildspec[\w.-]*\.ya?ml|appveyor\.yml|bitbucket-pipelines\.yml|.*\.ya?ml)$")
VENDOR_JS = re.compile(r"(?i)(^|[\\/])(jquery|bootstrap|modernizr|respond|angular|knockout|moment|lodash|underscore|popper|datatables|select2|"
                       r"chosen|kendo|telerik|signalr|microsoftajax|microsoftmvc|_references|json2|toastr|sweetalert|chart|d3|highcharts|"
                       r"handlebars|mustache|backbone|require|vue|react|tinymce|ckeditor)[\w.\-]*\.js$|\.min\.js$")
COMMENT_LINE = {"cs": re.compile(r"^\s*(//|/\*|\*)"), "vb": re.compile(r"^\s*('|REM\s)", re.I), "sql": re.compile(r"^\s*--"),
                "script": re.compile(r"^\s*(#|REM\s|::)", re.I), "js": re.compile(r"^\s*(//|/\*|\*)")}
BLOCK_COMMENT = {"cs": re.compile(r"/\*.*?\*/", re.S), "js": re.compile(r"/\*.*?\*/", re.S), "sql": re.compile(r"/\*.*?\*/", re.S),
                 "config": re.compile(r"<!--.*?-->", re.S), "proj": re.compile(r"<!--.*?-->", re.S), "markup": re.compile(r"<%--.*?--%>|<!--.*?-->", re.S),
                 "xml": re.compile(r"<!--.*?-->", re.S)}

URL_RX = re.compile(r"(?i)\b(https?|net\.tcp|net\.pipe|ftp|sftp|ldaps?|amqps?|tcp)://([A-Za-z0-9_.\-]+|\[[0-9a-f:]+\])(:\d+)?([^\s\"'<>)]*)")
IP_RX = re.compile(r"(?<![\w.])((?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})(?![\w.])")
SKIP_HOSTS = re.compile(r"(?i)^(localhost|127\.0\.0\.1|0\.0\.0\.0|\+|\*|example\.(com|org)|.*\.example\.com|tempuri\.org|schemas\.(microsoft|xmlsoap|openxmlformats)\.(com|org)|"
                        r"www\.w3\.org|w3\.org|go\.microsoft\.com|aka\.ms|json-schema\.org|purl\.org|xmlns\.com|docs\.(microsoft|oasis-open)\.(com|org)|"
                        r"msdn\.microsoft\.com|learn\.microsoft\.com|www\.asp\.net|asp\.net|github\.com|raw\.githubusercontent\.com|.*\.githubusercontent\.com|"
                        r"getbootstrap\.com|jquery\.(com|org)|.*\.jquery\.com|jqueryui\.com|modernizr\.com|opensource\.org|www\.apache\.org|apache\.org|"
                        r"nuget\.org|api\.nuget\.org|www\.nuget\.org|swagger\.io|.*\.?swagger\.io|ietf\.org|tools\.ietf\.org|creativecommons\.org|"
                        r"fonts\.googleapis\.com|fonts\.gstatic\.com|www\.gnu\.org|gnu\.org|schemas\.android\.com|developer\.mozilla\.org|"
                        r"code\.jquery\.com|ajax\.aspnetcdn\.com|cdnjs\.cloudflare\.com|cdn\.jsdelivr\.net|unpkg\.com|stackoverflow\.com|"
                        r"microsoft\.com|www\.microsoft\.com|support\.microsoft\.com|mozilla\.org|www\.mozilla\.org|feross\.org|git\.io|"
                        r"schemas\.datacontract\.org|.*\.datacontract\.org|schemas\.openxmlformats\.org|semver\.org|spdx\.org|xmlsoap\.org|www\.omg\.org|ns\.adobe\.com|www\.iana\.org|iana\.org|.*\.local\.test)$")
IP_SKIP_LINE = re.compile(r"(?i)(GeneratedCode|TechTalk|oid|TextExtension|\{text\}|1\.3\.6\.1|2\.5\.29|version|AssemblyVersion|AssemblyFileVersion|culture=|PublicKeyToken|\bv\d|codeBase|bindingRedirect|newVersion|oldVersion|"
                          r"targetFramework|package id=|Version=\"|Include=\"[^\"]*,\s*Version)")
INTERNAL_SUFFIX = re.compile(r"(?i)\.(local|corp|lan|internal|intranet|intra|ad|domain|home|private|priv|loc|int|office|net\.local)$")
CONN_KEYS = {"server": re.compile(r"(?i)^(data\s*source|server|address|addr|network\s*address|host)$"),
             "database": re.compile(r"(?i)^(initial\s*catalog|database)$")}


def private_ip(ip):
    a, b = [int(x) for x in ip.split(".")[:2]]
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) or a == 127 or (a == 169 and b == 254)


PUBLIC_TLDS = set("com org net edu gov mil int io co ai app dev cloud info biz me tv us uk eu de fr in jp cn au ca nz sg hk ch nl be es it se no dk fi ie at pl pt br mx ru za ae sa kr tw global online site tech xyz store shop blog news media agency solutions services systems software digital network group company page aws amazon microsoft google azure".split())
ENV_TOKENS = re.compile(r"(?i)(^|[.\-])(intra|intranet|internal|corp|lan|uat|sit|preprod|pre-prod|staging|stage|lab|qa|sso-test|infra|onprem|on-prem|dmz)([.\-]|\d|$)")
PLACEHOLDER_HOSTS = {"url", "host", "hostname", "server", "servername", "yourserver", "myserver", "domain", "site", "webapihelppage", "your-domain", "yourdomain", "foo", "bar", "test", "example", "machine", "computer", "localhost"}


def host_kind(host):
    h = host.lower().strip("[]")
    if IP_RX.fullmatch(h):
        return "internal" if private_ip(h) else "external-ip"
    labels = h.split(".")
    if "." not in h or INTERNAL_SUFFIX.search(h) or (labels[-1] not in PUBLIC_TLDS and len(labels[-1]) != 2):
        return "internal"
    if ENV_TOKENS.search(h):
        return "internal"  # environment-specific / corporate host name: reachable only through the client network (verify)
    return "external"


def load_rules():
    rules = data("rules.json")["rules"]
    for r in rules:
        r["_pat"] = [re.compile(p) for p in r["pat"]]
        r["_any"] = re.compile("|".join(f"(?i:{p[4:]})" if p.startswith("(?i)") else f"(?:{p})" for p in r["pat"]), re.M)
        r["_req"] = re.compile(r["requires"], re.M) if r.get("requires") else None
        r["_not"] = re.compile(r["not"]) if r.get("not") else None
        r["_types"] = set(r["types"])
    return rules


def blank_comments(text, ftype):
    """Replace block comments with blanks (keeps line numbers) so commented-out code does not become evidence."""
    rx = BLOCK_COMMENT.get(ftype if ftype != "vb" else "none")
    if not rx:
        return text
    return rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


class Scan:
    def __init__(self, repo, inv, cfg):
        self.repo, self.inv, self.cfg = repo, inv, cfg
        self.root = inv["root"]
        self.rules = load_rules()
        self.findings = {}
        self.facts = {"files_scanned": Counter(), "lines_scanned": 0, "rules_run": len(self.rules), "endpoints": {}, "connection_strings": [],
                      "secret_settings": [], "case_checks": 0, "case_mismatches": 0, "tests": {}, "skipped_large": [], "health_endpoints": []}
        self.pdirs = sorted(((os.path.normpath(os.path.dirname(os.path.join(self.root, p["path"]))), p) for p in inv["projects"]), key=lambda x: -len(x[0]))
        self.proj_by_path = {p["path"]: p for p in inv["projects"]}
        self.files_ci = None

    def project_of(self, path):
        path = os.path.normpath(path)
        for d, p in self.pdirs:
            if path.startswith(d + os.sep):
                return p["path"]
        return "(repository)"

    def add(self, rule, project, file, line, text, count=1, extra=None):
        key = (rule["id"], project)
        f = self.findings.get(key)
        if not f:
            f = self.findings[key] = {
                "id": f"{self.repo}:{rule['id']}:{slug(project)}", "repo": self.repo, "project": project, "rule": rule["id"], "category": rule["cat"],
                "title": rule["title"], "severity": rule["sev"], "confidence": rule["conf"], "occurrences": 0, "files": [], "evidence": [],
                "why": rule.get("why", ""), "fix": rule.get("fix", ""), "alt": rule.get("alt", ""), "effort_key": rule.get("effort", "small-change"),
                "baseline": bool(rule.get("baseline")), "db": rule.get("db"), "question": rule.get("question"), "refs": rule.get("refs", []), "source": "scan"}
        f["occurrences"] += count
        if file not in f["files"]:
            f["files"].append(file)
        if len(f["evidence"]) < MAX_EVIDENCE:
            ev = {"file": file, "line": line, "text": mask(text)}
            if extra:
                ev.update(extra)
            f["evidence"].append(ev)
        return f

    def synthetic(self, rid, cat, title, sev, conf, why, fix, alt="", effort="small-change", refs=None, question=None, db=None, baseline=False):
        return {"id": rid, "cat": cat, "title": title, "sev": sev, "conf": conf, "why": why, "fix": fix, "alt": alt, "effort": effort,
                "refs": refs or [], "question": question, "db": db, "baseline": baseline}

    # ---------------------------------------------------------------- line rules
    def scan_files(self):
        skip = SOURCE_DIR_SKIP | {s.lower() for s in self.cfg.get("exclude_dirs", [])}
        for d, dirs, files in os.walk(self.root):
            dirs[:] = sorted(x for x in dirs if x.lower() not in skip and not x.startswith("."))
            for fn in files:
                path = os.path.join(d, fn)
                ext = os.path.splitext(fn)[1].lower()
                ftype = TYPE_BY_EXT.get(ext)
                rp = rel(path, self.root)
                if rp.lower().startswith(".github/workflows/") or (CI_NAMES.match(fn) and not fn.lower().endswith((".yml", ".yaml"))) or \
                        re.match(r"(?i)^(azure-pipelines|buildspec|\.gitlab-ci|appveyor|bitbucket-pipelines)", fn):
                    ftype = "ci"
                elif fn.lower().startswith("appsettings") and ext == ".json":
                    ftype = "config"
                elif fn.lower().startswith("dockerfile") or fn.lower() == "nuget.config":
                    ftype = "any-only"
                if not ftype:
                    continue
                if ftype == "js" and VENDOR_JS.search(rp):
                    continue
                try:
                    if os.path.getsize(path) > MAX_FILE_BYTES:
                        self.facts["skipped_large"].append(rp)
                        continue
                    text = read_text(path)
                except OSError:
                    continue
                self.facts["files_scanned"][ftype] += 1
                self.scan_text(rp, path, ftype, text)

    def scan_text(self, rp, path, ftype, text):
        clean = blank_comments(text, ftype)
        lines = None
        project = self.project_of(path)
        cl = COMMENT_LINE.get(ftype)
        for r in self.rules:
            if not (ftype in r["_types"] or "any" in r["_types"] or (ftype == "any-only" and "any" in r["_types"])):
                continue
            if ftype == "any-only" and "any" not in r["_types"]:
                continue
            if not r["_any"].search(clean):
                continue
            if r["_req"] and not r["_req"].search(clean):
                continue
            if lines is None:
                lines = clean.splitlines()
                self.facts["lines_scanned"] += len(lines)
            for i, line in enumerate(lines, 1):
                if cl and cl.match(line):
                    continue
                if r["_any"].search(line) and not (r["_not"] and r["_not"].search(line)):
                    if r["id"] == "DATA-INTEGRATED-SECURITY" and re.search(r"(?i)\(localdb\)|AttachDbFilename|SQLEXPRESS", line):
                        self.add(LOCALDB_RULE, project, rp, i, line)  # developer database: production auth is unknown
                        continue
                    self.add(r, project, rp, i, line)
        if ftype in ("cs", "vb", "config", "js", "sql", "markup", "script", "ci", "any-only"):
            self.endpoints(rp, project, clean, ftype)
        if ftype == "config":
            self.config_file(rp, project, text)
        if ftype in ("cs", "vb") and re.search(r"(?i)(MapHealthChecks|AddHealthChecks|/health|HealthCheck|\bhealthz\b)", clean):
            self.facts["health_endpoints"].append(rp)

    # ---------------------------------------------------------------- endpoints
    def endpoints(self, rp, project, text, ftype):
        cl = COMMENT_LINE.get(ftype)
        for i, line in enumerate(text.splitlines(), 1):
            if cl and cl.match(line):
                continue
            if "://" in line:
                for m in URL_RX.finditer(line):
                    scheme, host = m.group(1).lower(), m.group(2)
                    if SKIP_HOSTS.match(host) or host.startswith("{") or "$" in host or host.lower() in PLACEHOLDER_HOSTS:
                        continue
                    self.endpoint(host, scheme, rp, project, i, line, ftype)
            if IP_RX.search(line) and not IP_SKIP_LINE.search(line):
                for m in IP_RX.finditer(line):
                    ip = m.group(1)
                    octets = [int(x) for x in ip.split(".")]
                    if ip.startswith(("0.", "127.", "255.")) or ip.endswith(".0.0") or all(o < 10 for o in octets):
                        continue  # version-like dotted numbers (2.3.2.0, 1.1.0.1) are not addresses
                    self.endpoint(ip, "ip", rp, project, i, line, ftype)

    def endpoint(self, host, scheme, rp, project, line_no, line, ftype):
        e = self.facts["endpoints"].setdefault(host.lower(), {"host": host.lower(), "kind": host_kind(host), "schemes": [], "files": [], "occurrences": 0, "evidence": []})
        if scheme not in e["schemes"]:
            e["schemes"].append(scheme)
        if rp not in e["files"]:
            e["files"].append(rp)
        e["occurrences"] += 1
        if len(e["evidence"]) < 5:
            e["evidence"].append({"file": rp, "line": line_no, "text": mask(line)})
        kind = e["kind"]
        if kind == "internal":
            r = self.synthetic("NET-ENDPOINT-INTERNAL", "connectivity", f"On-premises / internal endpoint: {host}", "High", "Likely",
                               "Internal host names and private IPs resolve only inside the client network; from AWS they need VPN / Direct Connect, Route 53 Resolver rules, or the target system must move too.",
                               "Confirm what the host is, whether it moves to AWS, and the network path (Site-to-Site VPN / Direct Connect); replace literals with configuration.",
                               "AWS Site-to-Site VPN / Direct Connect; Route 53 Resolver", "small-change", ["S10"],
                               f"What is {host}, who owns it, and will it move to AWS or stay on-premises?")
        elif kind == "external-ip":
            r = self.synthetic("NET-ENDPOINT-PUBLIC-IP", "connectivity", f"Hard-coded public IP: {host}", "Medium", "Confirmed",
                               "Hard-coded IPs break when the provider changes them, and partners that allow-list our source IP must be told the new AWS egress IPs.",
                               "Use DNS names in configuration; plan fixed egress (NAT gateway Elastic IPs) and partner allow-list updates.", "NAT gateway EIPs", "trivial", ["S10"],
                               f"Does the service at {host} allow-list the client's current public IPs?")
        else:
            r = self.synthetic("NET-ENDPOINT-EXTERNAL", "dependencies", f"External service: {host}", "Info", "Confirmed",
                               "Third-party/external endpoint the application depends on; check IP allow-listing, credentials and TLS requirements before cut-over.",
                               "Record in the dependency map; confirm allow-listing and credentials for the AWS environment.", "", "trivial", ["S10"])
        r["id"] = r["id"] + ":" + slug(host)
        self.add(r, "(repository)", rp, line_no, line, extra={"host": host.lower(), "scheme": scheme})

    # ---------------------------------------------------------------- config files
    def config_file(self, rp, project, text):
        if rp.lower().endswith(".json"):
            try:
                obj = json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))
            except ValueError:
                return
            cs = obj.get("ConnectionStrings") if isinstance(obj, dict) else None
            if isinstance(cs, dict):
                for name, val in cs.items():
                    if isinstance(val, str):
                        self.connection(rp, project, name, val, "", self.line_of(text, name))
            return
        try:
            root = ET.fromstring(text.encode("utf-8"))
        except ET.ParseError:
            return
        for add in root.iter("add"):
            if add.get("connectionString") is not None and add.get("name"):
                self.connection(rp, project, add.get("name"), add.get("connectionString"), add.get("providerName", ""), self.line_of(text, add.get("name")))
            key = add.get("key")
            val = add.get("value")
            if key and val and re.search(r"(?i)(pass|pwd|secret|token|apikey|api_key|accesskey|privatekey|credential|clientkey|sharedkey)", key) \
                    and not re.fullmatch(r"(?i)\s*(|true|false|\d+|none|null|\$\(.*\)|#\{.*\}|__\w+__|\{.*\}|xxx+|\*+|changeme)\s*", val):
                self.facts["secret_settings"].append({"file": rp, "key": key})
                r = self.synthetic("CFG-SECRET-SETTING", "configuration-secrets", "Secret-like value stored in configuration", "High", "Likely",
                                   "Secrets in web.config/app.config are copied to every server and every repository clone.",
                                   "Move to AWS Secrets Manager / Parameter Store SecureString; rotate the value.", "AWS Secrets Manager", "trivial", ["S21"])
                self.add(r, project, rp, self.line_of(text, key), f'<add key="{key}" value="***" />')

    def connection(self, rp, project, name, cs, provider, line):
        parts = {}
        for kv in cs.split(";"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                parts[k.strip().lower()] = v.strip()
        server = next((v for k, v in parts.items() if CONN_KEYS["server"].match(k)), "")
        db = next((v for k, v in parts.items() if CONN_KEYS["database"].match(k)), "")
        integrated = bool(re.search(r"(?i)(integrated\s*security\s*=\s*(sspi|true|yes)|trusted_connection\s*=\s*(yes|true))", cs))
        has_pwd = bool(re.search(r"(?i)(password|pwd)\s*=\s*[^;]+", cs))
        ef = "metadata=" in cs.lower()
        if ef:
            inner = re.search(r'(?i)provider connection string\s*=\s*"?([^"]*)', cs)
            if inner:
                return self.connection(rp, project, name, inner.group(1).replace("&quot;", ""), provider, line)
        host = re.split(r"[\\,:]", server.replace("tcp:", ""))[0] if server else ""
        entry = {"file": rp, "line": line, "name": name, "provider": provider, "server": server, "host": host, "database": db,
                 "auth": "integrated" if integrated else ("sql-login" if has_pwd else "unspecified"), "password_in_config": has_pwd,
                 "attachdb": "attachdbfilename" in cs.lower(), "localdb": "(localdb)" in server.lower()}
        self.facts["connection_strings"].append(entry)
        if has_pwd:
            r = self.synthetic("CFG-PLAINTEXT-DB-PASSWORD", "configuration-secrets", "Database password in a connection string", "High", "Confirmed",
                               "Plain-text database credentials in config files are a compliance finding and block credential rotation.",
                               "Store credentials in AWS Secrets Manager (RDS integration supports rotation); build the connection string at start-up.",
                               "Secrets Manager + RDS rotation", "trivial", ["S11"])
            self.add(r, project, rp, line, f'<add name="{name}" connectionString="…password=***…" />')
        if host and not entry["localdb"] and host not in (".", "(local)", "localhost", "127.0.0.1"):
            self.endpoint(host, "sql", rp, project, line, f"connection string '{name}' -> {host}", "config")

    @staticmethod
    def line_of(text, needle):
        i = text.find(needle) if needle else -1
        return text.count("\n", 0, i) + 1 if i >= 0 else 1

    # ---------------------------------------------------------------- packages
    def packages(self, online):
        pm = data("package_map.json")["packages"]
        for e in pm:
            e["_rx"] = re.compile(rf"(?i)^(?:{e['match']})$")
        allp = defaultdict(lambda: {"versions": set(), "projects": set(), "files": []})
        for p in self.inv["projects"]:
            for k in p.get("packages", []):
                a = allp[k["id"]]
                a["versions"].add(k.get("version", ""))
                a["projects"].add(p["path"])
                a["files"].append(k.get("file", p["path"]))
        table = []
        if online:
            from concurrent.futures import ThreadPoolExecutor
            cache = os.path.join(OUT, "cache", "nuget")
            with ThreadPoolExecutor(max_workers=8) as ex:
                list(ex.map(lambda kv: nuget_info(kv[0], sorted(kv[1]["versions"]), cache), list(allp.items())))
        for pid, a in sorted(allp.items(), key=lambda x: x[0].lower()):
            m = next((e for e in pm if e["_rx"].match(pid)), None)
            row = {"id": pid, "versions": sorted(v for v in a["versions"] if v), "projects": sorted(a["projects"]),
                   "status": m["status"] if m else "unknown", "note": m["note"] if m else "", "replacement": m["replacement"] if m else "",
                   "severity": m["sev"] if m else "Info"}
            vb = (m or {}).get("vulnerable_below", {})
            limit = next((v for k, v in vb.items() if k.lower() == pid.lower()), None)
            if limit and any(ver_lt(v, limit) for v in row["versions"]):
                row["vulnerable"] = f"versions below {limit} have published advisories"
            if online:
                row["nuget"] = nuget_info(pid, row["versions"], os.path.join(OUT, "cache", "nuget"))
                n = row["nuget"]
                row["latest"] = n.get("latest")
                if n.get("vulnerable_versions"):
                    row["vulnerable"] = "; ".join(f"{v}: {', '.join(s)} severity advisory" for v, s in n["vulnerable_versions"].items())
                if n.get("used_version_deprecated") and not n.get("deprecated") and row["status"] in ("unknown", "ok"):
                    row["status"] = "upgrade"
                    row["note"] = (row["note"] + " " if row["note"] else "") + f"Version in use is marked {n['used_version_deprecated']} on nuget.org; latest is {n.get('latest')}."
                if n.get("deprecated") and row["status"] in ("unknown", "ok"):
                    row["status"], row["severity"] = "replace", "Medium"
                    row["note"] = (row["note"] + " " if row["note"] else "") + f"Deprecated on nuget.org: {n['deprecated']}"
                if row["status"] == "unknown" and n.get("found"):
                    if n.get("supports_modern"):
                        row["status"], row["note"] = "ok", f"Latest {n.get('latest')} targets {', '.join(n.get('frameworks', [])[:4])}"
                    else:
                        row["status"], row["severity"] = "replace", "Medium"
                        row["note"] = f"No .NET Standard/.NET target in latest {n.get('latest')} (targets {', '.join(n.get('frameworks', [])[:4]) or 'none listed'})"
                if row["status"] == "unknown" and not n.get("found"):
                    row["note"] = "Not on nuget.org: private/internal package (needs source or a CodeArtifact feed)."
                    row["status"], row["severity"] = "private", "Medium"
            table.append(row)
            first = a["files"][0]
            line = self.find_line(first, pid)
            if row["status"] in ("blocker", "replace", "windows-only", "licence", "private") and row["severity"] in ("Blocker", "High", "Medium", "Low"):
                eff = "package-blocker" if row["status"] in ("blocker", "windows-only") and row["severity"] in ("Blocker", "High") else "package-replace"
                r = self.synthetic(f"PKG-{row['status'].upper()}", "packages", f"Package {pid} ({row['status']})", row["severity"],
                                   "Confirmed" if row["status"] != "private" else "Needs verification", row["note"],
                                   f"Replace with: {row['replacement']}" if row["replacement"] else "Find a supported version or replacement.",
                                   row["replacement"], eff, ["S3"],
                                   "Can we get the source (or a .NET Standard build) of this private package?" if row["status"] == "private" else None)
                r["id"] = f"PKG-{slug(pid)}"
                r["baseline"] = bool((m or {}).get("baseline")) or (row["status"] == "replace" and row["severity"] in ("Info", "Low"))
                f = self.add(r, "(repository)", first, line, f"{pid} {', '.join(row['versions'])}", count=len(a["projects"]))
                f["package"] = pid
                f["projects_affected"] = sorted(a["projects"])
            if row.get("vulnerable"):
                r = self.synthetic("SEC-VULNERABLE-PACKAGE", "security", f"Vulnerable package {pid}", "High", "Confirmed",
                                   f"{pid} {', '.join(row['versions'])}: {row['vulnerable']}.", "Upgrade to a fixed version during the port.",
                                   row.get("replacement", ""), "trivial", ["S3"])
                r["id"] = f"SEC-VULN-{slug(pid)}"
                f = self.add(r, "(repository)", first, line, f"{pid} {', '.join(row['versions'])}")
                f["package"] = pid
        self.facts["packages"] = table

    def find_line(self, relfile, needle):
        try:
            return self.line_of(read_text(os.path.join(self.root, relfile)), needle)
        except OSError:
            return 1

    # ---------------------------------------------------------------- structural checks
    def structure(self):
        inv = self.inv
        for p in inv["projects"]:
            path = p["path"]
            if p.get("error"):
                continue
            if not p.get("sdk_style") and p["ext"] != ".sqlproj":
                r = self.synthetic("INV-LEGACY-PROJECT", "build-delivery", "Legacy (non-SDK) project file", "Medium", "Confirmed",
                                   "Old-style project files only build with Visual Studio MSBuild on Windows.", "Convert to SDK-style during the port.",
                                   "SDK-style project", "trivial", ["S3"], baseline=True)
                self.add(r, path, path, 1, f"{os.path.basename(path)}: ToolsVersion project, target {', '.join(p['target_frameworks'])}")
            if p.get("packages_config"):
                r = self.synthetic("INV-PACKAGES-CONFIG", "build-delivery", "packages.config package management", "Low", "Confirmed",
                                   "packages.config is not supported by SDK-style projects.", "Migrate to PackageReference.", "PackageReference", "trivial", ["S3"], baseline=True)
                self.add(r, path, os.path.join(os.path.dirname(path), "packages.config").replace("\\", "/"), 1, "packages.config")
            for t in p.get("tfm_support", []):
                if t["status"] in ("out-of-support", "ending-soon"):
                    sev = "High" if t["status"] == "out-of-support" else "Medium"
                    r = self.synthetic("INV-TFM-SUPPORT", "modern-on-windows" if "netcore" in p["framework_family"] else "inventory",
                                       f"Target framework {t['label']} ({t['status'].replace('-', ' ')})", sev, "Confirmed",
                                       f"{t['tfm']}: end of support {t['end_of_support']}. Unsupported runtimes get no security fixes.",
                                       f"Upgrade to {self.cfg.get('target_dotnet', 'net10.0')} (LTS, supported to 2028-11-14).", ".NET 10 LTS", "trivial", ["S4", "S5"])
                    self.add(r, path, path, self.find_line(path, "TargetFramework"), f"{t['tfm']} -> {t['label']} (EOS {t['end_of_support']})")
            if p["type"] in ("aspnet-core", "netcore-other") and "netfx" in p["framework_family"]:
                r = self.synthetic("INV-CORE-ON-FRAMEWORK", "inventory", "ASP.NET Core / SDK-style project still targeting .NET Framework", "Medium", "Confirmed",
                                   "ASP.NET Core 2.x on .NET Framework is a half-way port: it is out of support and still Windows-only.",
                                   f"Retarget to {self.cfg.get('target_dotnet', 'net10.0')} and update ASP.NET Core packages.", ".NET 10", "small-change", ["S4"])
                self.add(r, path, path, self.find_line(path, "TargetFramework"), f"{p.get('sdk')} targeting {', '.join(p['target_frameworks'])}")
        for w in inv.get("websites", []):
            r = self.synthetic("INV-WEBSITE-PROJECT", "web-platform", "ASP.NET Web Site project (no project file)", "High", "Confirmed",
                               "Web Site projects compile at runtime and are not supported by AWS Transform or SDK-style builds.",
                               "Convert to a Web Application project first, then port.", "Web Application project", "medium-change", ["S17"])
            self.add(r, w["path"], w["path"] + "/web.config", 1, f"{w['pages']} pages, App_Code: {w['app_code']}")
        arts = inv.get("artefacts", {})
        for kind, rid, title, sev, why, fix, alt, db in (
                ("ssis", "DB-SSIS", "SSIS packages", "High", "SSIS runs on RDS for SQL Server 2016-2022 via an option group (not on SQL Server 2025) and not with Babelfish.",
                 "Inventory packages; rehost on RDS SSIS / SQL Server on EC2, or rebuild in AWS Glue / Step Functions.", "AWS Glue / Step Functions / RDS SSIS", {"rds": "limited", "babelfish": "blocker"}),
                ("ssrs", "DB-SSRS", "SSRS reports", "Medium", "SSRS is an RDS option for SQL Server 2016-2022; from SQL Server 2025 reporting is Power BI Report Server.",
                 "Decide report hosting (RDS SSRS option, PBIRS, EC2) and data sources.", "RDS SSRS option / PBIRS / QuickSight", {"rds": "limited", "babelfish": "blocker"}),
                ("ssas", "DB-SSAS", "SSAS models", "High", "SSAS is not supported on RDS for SQL Server 2022+.", "Run SSAS on EC2 or move models to a managed analytics service.",
                 "SQL Server on EC2 / Amazon Redshift + QuickSight", {"rds": "blocker", "babelfish": "blocker", "ec2": "ok"}),
                ("crystal", "INT-CRYSTAL-FILES", "Crystal report definitions (.rpt)", "High", "Crystal Reports runtime is Windows/.NET Framework only.",
                 "Inventory reports; re-implement or retire.", "SSRS / PBIRS / reporting library", None),
                ("rdlc", "INT-RDLC-FILES", "RDLC local reports", "Medium", "RDLC rendering relies on the .NET Framework ReportViewer.",
                 "Re-host rendering (SSRS server / supported library).", "SSRS / Bold Reports", None),
                ("script", "BUILD-SCRIPTS", "Windows scripts (.ps1/.bat/.cmd/.vbs)", "Low", "Batch/VBScript do not run on Linux; Windows PowerShell scripts may use Windows-only modules (PowerShell 7 runs on Linux).",
                 "Review each script; port to pwsh 7 or bash; move deployment logic into CI/CD.", "PowerShell 7 / CodeBuild", None)):
            files = arts.get(kind) or []
            if not files:
                continue
            r = self.synthetic(rid, "database" if kind.startswith("ss") else ("integrations" if kind in ("crystal", "rdlc") else "build-delivery"),
                               f"{title}: {len(files)} file(s)", sev, "Confirmed", why, fix, alt,
                               "per-report" if kind in ("crystal", "rdlc", "ssrs") else ("db-object-medium" if kind.startswith("ss") else "small-change"), ["S12"], db=db)
            for fp in files[:MAX_EVIDENCE]:
                self.add(r, "(repository)", fp, 1, os.path.basename(fp))
            f = self.findings[(rid, "(repository)")]
            f["occurrences"] = len(files)
        dockers = arts.get("docker") or []
        if dockers:
            self.facts["dockerfiles"] = dockers
        # jQuery and other client libraries present as files
        for fp in arts.get("js_lib") or []:
            m = re.search(r"(?i)(jquery|bootstrap|angular|knockout|modernizr)-?(\d+(\.\d+){1,2})?(\.min)?\.js$", fp)
            if not m:
                continue
            lib, ver = m.group(1).lower(), m.group(2) or ""
            old = (lib == "jquery" and ver and ver_lt(ver, "3.5.0")) or (lib == "bootstrap" and ver and ver_lt(ver, "3.4.1")) or lib == "angular" or (lib == "modernizr" and ver and ver_lt(ver, "3.0"))
            if old:
                rule = next(r for r in self.rules if r["id"] == "FE-LEGACY-LIBS")
                self.add(rule, self.project_of(os.path.join(self.root, fp)), fp, 1, f"{os.path.basename(fp)} ({lib} {ver or 'version in file'})")
        # tests
        tests = {}
        for p in self.inv["projects"]:
            if p["type"] != "test":
                continue
            n, fw = 0, Counter()
            for k in p.get("packages", []):
                low = k["id"].lower()
                for name in ("mstest", "nunit", "xunit", "specflow", "reqnroll", "selenium", "playwright", "moq", "nsubstitute", "fluentassertions"):
                    if name in low:
                        fw[name] += 1
            if "microsoft.visualstudio.qualitytools.unittestframework" in {r.lower() for r in p.get("references", [])}:
                fw["mstest-v1"] += 1
            base = os.path.dirname(os.path.join(self.root, p["path"]))
            for d, dirs, files in os.walk(base):
                dirs[:] = [x for x in dirs if x.lower() not in SOURCE_DIR_SKIP]
                for fn in files:
                    if fn.endswith((".cs", ".vb")):
                        try:
                            n += len(re.findall(r"\[(TestMethod|Test|Fact|Theory|TestCase|DataTestMethod)\b|<(TestMethod|Test|Fact)\(?\)?>", read_text(os.path.join(d, fn))))
                        except OSError:
                            pass
            tests[p["path"]] = {"test_methods": n, "frameworks": sorted(fw)}
        self.facts["tests"] = tests
        total_tests = sum(t["test_methods"] for t in tests.values())
        kloc = max(self.inv["totals"]["loc"] / 1000.0, 0.001)
        self.facts["tests_per_kloc"] = round(total_tests / kloc, 2)
        if total_tests == 0 or total_tests / kloc < 2:
            r = self.synthetic("TEST-LOW-COVERAGE", "tests", f"Little or no automated test coverage ({total_tests} test methods for {kloc:.1f} KLOC)", "High", "Confirmed",
                               "Regression safety for the port depends on manual QA; this is the main cost and risk driver.",
                               "Build a characterisation/regression suite for critical workflows before porting (API + UI smoke tests), and budget QA accordingly.",
                               "xUnit/MSTest + Playwright", "medium-change", ["S9"])
            first = next(iter(tests), self.inv["projects"][0]["path"] if self.inv["projects"] else "(repository)")
            self.add(r, "(repository)", first, 1, f"{len(tests)} test project(s), {total_tests} test methods, {self.facts['tests_per_kloc']} per KLOC")
        # health checks
        webs = [p for p in self.inv["projects"] if p["type"].startswith("aspnet") or p["type"] == "wcf-service"]
        if webs and not self.facts["health_endpoints"]:
            r = self.synthetic("LOG-NO-HEALTHCHECK", "logging", "No health-check endpoint", "Low", "Likely",
                               "Load balancers and ECS/EKS need a health endpoint to route traffic and replace unhealthy tasks.",
                               "Add ASP.NET Core health checks (/health) covering database and key dependencies.", "Microsoft.Extensions.Diagnostics.HealthChecks", "trivial", ["S10"])
            self.add(r, webs[0]["path"], webs[0]["path"], 1, "no MapHealthChecks / health endpoint found in web projects")
        # modern .NET hosted on Windows
        for p in self.inv["projects"]:
            if "netcore" in p["framework_family"] and p["type"] in ("aspnet-core", "netcore-other") and not any(t.endswith("-windows") for t in p["target_frameworks"]):
                base = os.path.dirname(p["path"])
                win_hosting = [a for a in (self.inv["artefacts"].get("publish_profile", []) + self.inv["artefacts"].get("config", []) + self.inv["artefacts"].get("docker", []))
                               if a.startswith(base + "/") or a == base]
                if win_hosting:
                    r = self.synthetic("MOD-ON-WINDOWS", "modern-on-windows", "Modern .NET app with Windows/IIS hosting artefacts", "Medium", "Needs verification",
                                       "The app already runs on cross-platform .NET; if it is hosted on Windows/IIS today there may be no technical reason to keep paying for Windows.",
                                       "Confirm no Windows-only findings remain for this project, then replatform to Linux containers (ECS Fargate) directly.",
                                       "Linux containers on ECS Fargate", "small-change", ["S10"],
                                       question=f"Why is {p['name']} hosted on Windows today (IIS, Windows auth, a Windows-only dependency)?")
                    for w in win_hosting[:5]:
                        self.add(r, p["path"], w, 1, os.path.basename(w))
        # parallel development
        g = self.inv.get("git", {})
        if g.get("git"):
            th = data("estimation.json")["activity_thresholds"]
            cpw = g.get("commits_per_week") or 0
            level = "hot" if cpw >= th["hot_commits_per_week"] else ("active" if cpw >= th["active_commits_per_week"] else "quiet")
            self.facts["activity_level"] = level
            sev = {"hot": "High", "active": "Medium", "quiet": "Info"}[level]
            r = self.synthetic("DEV-ACTIVITY", "parallel-dev", f"Repository activity: {level} ({cpw} commits/week, {g.get('authors', 0)} authors in {g.get('window_days')} days)",
                               sev, "Confirmed", "Parallel feature work on the client branch while porting causes merge conflicts and drift; hot files conflict most.",
                               "Agree a merge strategy: short-lived port branches, frequent rebases, freeze windows for hot files, or a strangler-fig split that isolates ported code.",
                               "", "trivial", ["S9"])
            hot = ", ".join(f"{f} ({n})" for f, n in (g.get("hot_files") or [])[:5]) or "none in window"
            self.add(r, "(repository)", ".git", 1, f"branch {g.get('branch')}, last commit {g.get('last_commit')}, shallow={g.get('shallow')}; hot files: {hot}")

    # ---------------------------------------------------------------- path case
    def case_paths(self):
        idx = {}
        for d, dirs, files in os.walk(self.root):
            dirs[:] = [x for x in dirs if x.lower() not in SOURCE_DIR_SKIP and not x.startswith(".")]
            for fn in files:
                rp = rel(os.path.join(d, fn), self.root)
                idx.setdefault(rp.lower(), rp)
        lit = re.compile(r"[\"'](~?/[A-Za-z0-9_\-./]+\.(?:css|js|png|jpe?g|gif|svg|ico|cshtml|aspx|ascx|master|html?|json|xml|config|rdlc|xslt?|woff2?|ttf|pdf))[\"'?#]")
        for p in self.inv["projects"]:
            base = os.path.dirname(p["path"])
            pdir = os.path.join(self.root, base)
            for d, dirs, files in os.walk(pdir):
                dirs[:] = [x for x in dirs if x.lower() not in SOURCE_DIR_SKIP]
                for fn in files:
                    if os.path.splitext(fn)[1].lower() not in (".cs", ".vb", ".cshtml", ".aspx", ".ascx", ".master", ".config", ".vbhtml"):
                        continue
                    fp = os.path.join(d, fn)
                    try:
                        text = read_text(fp)
                    except OSError:
                        continue
                    for i, line in enumerate(text.splitlines(), 1):
                        for m in lit.finditer(line):
                            target = m.group(1).lstrip("~").lstrip("/")
                            cand = (base + "/" + target) if base else target
                            self.facts["case_checks"] += 1
                            actual = idx.get(cand.lower())
                            if actual and actual != cand:
                                self.facts["case_mismatches"] += 1
                                r = self.synthetic("FILE-CASE-MISMATCH", "file-handling", "Path literal differs in case from the file on disk", "Medium", "Confirmed",
                                                   "Linux file systems are case-sensitive: this reference works on Windows and returns 404/FileNotFound on Linux.",
                                                   "Fix the literal (or the file name) to match exactly; add a CI check.", "", "per-occurrence-small", ["S7"])
                                self.add(r, p["path"], rel(fp, self.root), i, f"{m.group(1)}  (file is {actual})")

    def result(self):
        using_rx = re.compile(r"^\s*(using\s+[\w.]+\s*;|Imports\s+[\w.]+)\s*$")
        rule_by_id = {r["id"]: r for r in self.rules}
        for f in self.findings.values():
            r = rule_by_id.get(f["rule"])
            if not r or any(p.startswith((r"^\s*using", r"^\s*Imports")) for p in r["pat"]):
                continue
            if f["evidence"] and all(using_rx.match(e["text"]) for e in f["evidence"]) and f["occurrences"] == len(f["evidence"]):
                f["severity"], f["confidence"], f["effort_key"] = "Low", "Likely", "trivial"
                f["note"] = "Only import directives were found (the namespace is probably unused): remove the import and confirm the build."
        out = sorted(self.findings.values(), key=lambda f: (SEV_ORDER.get(f["severity"], 9), f["category"], f["rule"], f["project"]))
        cats = Counter(f["category"] for f in out)
        self.facts["category_counts"] = dict(cats)
        self.facts["files_scanned"] = dict(self.facts["files_scanned"])
        self.facts["endpoints"] = sorted(self.facts["endpoints"].values(), key=lambda e: (e["kind"] != "internal", -e["occurrences"]))
        return out


LOCALDB_RULE = {"id": "CFG-DEV-DATABASE", "cat": "configuration-secrets", "title": "Connection strings point at a developer database (LocalDB / SQL Express)",
                "sev": "Low", "conf": "Confirmed", "why": "The repository only holds developer connection strings; production server, database and authentication mode are configured outside the code.",
                "fix": "Obtain the production connection configuration (names, servers, auth mode) from the client; move it to Parameter Store / Secrets Manager.",
                "alt": "", "effort": "trivial", "refs": ["S11"], "question": "Where are production connection strings configured (IIS, transforms, deployment tool), and do they use Windows or SQL authentication?"}
SEV_ORDER = {"Blocker": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


def ver_tuple(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-+]", v)[:4])


def ver_lt(a, b):
    try:
        return ver_tuple(a) < ver_tuple(b)
    except ValueError:
        return False


def nuget_info(pid, versions, cache_dir):
    """Public package metadata from api.nuget.org (cached): latest version, frameworks, deprecation, vulnerabilities, licence."""
    os.makedirs(cache_dir, exist_ok=True)
    cp = os.path.join(cache_dir, slug(pid) + ".json")
    if os.path.exists(cp) and time.time() - os.path.getmtime(cp) < 14 * 86400:
        raw = read_json(cp)
    else:
        url = f"https://api.nuget.org/v3/registration5-gz-semver2/{pid.lower()}/index.json"
        try:
            req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "migration-assessment"})
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
                    body = gzip.decompress(body)
            raw = json.loads(body)
            pages = []
            for page in raw.get("items", []):
                if "items" not in page:
                    with urllib.request.urlopen(urllib.request.Request(page["@id"], headers={"Accept-Encoding": "gzip"}), timeout=20) as r:
                        b = r.read()
                        page = json.loads(gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b)
                pages.append(page)
            raw = {"items": [{"items": [{"catalogEntry": {k: it["catalogEntry"].get(k) for k in ("version", "listed", "deprecation", "vulnerabilities", "licenseExpression", "dependencyGroups")}}
                                        for it in pg.get("items", [])]} for pg in pages]}
        except (urllib.error.URLError, OSError, ValueError) as ex:
            raw = {"error": str(ex)[:200], "status": getattr(ex, "code", None)}
        json.dump(raw, open(cp, "w", encoding="utf-8"))
    if raw.get("error"):
        return {"found": False, "error": raw["error"]} if raw.get("status") != 404 else {"found": False}
    entries = [it["catalogEntry"] for pg in raw.get("items", []) for it in pg.get("items", [])]
    if not entries:
        return {"found": False}
    listed = [e for e in entries if e.get("listed", True) is not False and not re.search(r"-", e.get("version", ""))] or entries
    latest = listed[-1]
    fws = sorted({(g.get("targetFramework") or "any").lower() for g in (latest.get("dependencyGroups") or [])})
    modern = (not fws) or any(re.match(r"^(\.netstandard|netstandard|\.netcoreapp|netcoreapp|net\d+\.\d+|any)", f) for f in fws)
    used = {ver_tuple(v) for v in versions if v}
    sevname = {"0": "low", "1": "moderate", "2": "high", "3": "critical"}
    vuln = {}
    for e in entries:
        if ver_tuple(e.get("version", "0")) in used and e.get("vulnerabilities"):
            vuln[e["version"]] = sorted({sevname.get(str(v.get("severity")), str(v.get("severity"))) for v in e["vulnerabilities"]})

    def dep_text(dep):
        if not dep:
            return None
        alt = (dep.get("alternatePackage") or {}).get("id")
        return ", ".join(dep.get("reasons", [])) + (f"; use {alt}" if alt else "")
    used_dep = next((e.get("deprecation") for e in entries if ver_tuple(e.get("version", "0")) in used and e.get("deprecation")), None)
    return {"found": True, "latest": latest.get("version"), "frameworks": fws, "supports_modern": modern,
            "deprecated": dep_text(latest.get("deprecation")), "used_version_deprecated": dep_text(used_dep),
            "vulnerable_versions": vuln, "licence": latest.get("licenseExpression")}


def scan_repo(name, cfg, online):
    inv = read_json(os.path.join(OUT, "inventory", f"{name}.json"))
    if not inv:
        sys.exit(f"no inventory for {name}: run discover_estate.py first")
    t0 = time.time()
    s = Scan(name, inv, cfg)
    s.scan_files()
    s.packages(online)
    s.structure()
    s.case_paths()
    import _dbinventory
    s.facts["db_inventory"] = _dbinventory.inventory(inv["root"], cfg.get("exclude_dirs", []))
    findings = s.result()
    s.facts["duration_s"] = round(time.time() - t0, 1)
    s.facts["generated"] = datetime.datetime.now().isoformat(timespec="seconds")
    s.facts["online_package_lookup"] = online
    write_json(os.path.join(OUT, "findings", f"{name}.json"), findings)
    write_json(os.path.join(OUT, "scan", f"{name}.json"), s.facts)
    sev = Counter(f["severity"] for f in findings)
    print(f"{name}: {len(findings)} findings ({', '.join(f'{k} {sev[k]}' for k in SEV_ORDER if sev[k])}); "
          f"{sum(s.facts['files_scanned'].values())} files, {s.facts['lines_scanned']:,} lines scanned in {s.facts['duration_s']}s; "
          f"{len(s.facts['endpoints'])} endpoints, {len(s.facts['connection_strings'])} connection strings, {len(s.facts.get('packages', []))} packages")
    return findings


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--online", action="store_true")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    online = (cfg.get("online_package_lookup") or a.online) and not a.offline
    st = load_state(root)
    names = [a.repo] if a.repo else (sorted(st["repos"]) if a.all else [])
    if not names:
        sys.exit("pass --repo NAME or --all")
    for n in names:
        if a.all and not a.force and st["repos"].get(n, {}).get("scan") == "done":
            continue
        scan_repo(n, cfg, online)
        mark(root, n, "scan")


if __name__ == "__main__":
    main()
