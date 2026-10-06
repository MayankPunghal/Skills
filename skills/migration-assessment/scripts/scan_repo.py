"""Run every deterministic migration check on one repository (or all) and write evidence-backed findings.

    python <skill>/scripts/scan_repo.py --repo NAME | --all [--force] [--online | --offline]   (online is the default)

Needs discover_estate.py first. Writes:
  assessment/findings/<repo>.json   findings: rule, category, severity, confidence, project, occurrences, evidence (file:line, masked)
  assessment/scan/<repo>.json       scan facts: files scanned per type, endpoints, connection strings (no secrets), packages,
                                    tests, case-mismatch checks, artefacts, category coverage (what was checked)
Engines: line rules (data/rules.json), package map (data/package_map.json, plus api.nuget.org when online: deprecation,
advisories, targets and licence history of every package, see licence_change()), config parser
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
import threading
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
               ".cmd": "script", ".vbs": "script", ".js": "js", ".xslt": "xml", ".xsl": "xml", ".pubxml": "xml", ".reg": "script", ".targets": "proj", ".props": "proj"}
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
IP_SKIP_LINE = re.compile(r"(?i)(GeneratedCode|TechTalk|\boid\b|TextExtension|\{text\}|1\.3\.6\.1|2\.5\.29|version|AssemblyVersion|AssemblyFileVersion|culture=|PublicKeyToken|\bv\d|codeBase|bindingRedirect|newVersion|oldVersion|"
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
        self.parsed_sql = False

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
            if rule.get("db_only"):  # database-side work: priced in the database estimate only, not in application packages
                f["db_only"] = True
        f["occurrences"] += count
        if file not in f["files"]:
            f["files"].append(file)
        if len(f["evidence"]) < MAX_EVIDENCE:
            ev = {"file": file, "line": line, "text": mask(text)}
            if extra:
                ev.update(extra)
            f["evidence"].append(ev)
        return f

    def synthetic(self, rid, cat, title, sev, conf, why, fix, alt="", effort="small-change", refs=None, question=None, db=None, baseline=False,
                  db_only=False):
        return {"id": rid, "cat": cat, "title": title, "sev": sev, "conf": conf, "why": why, "fix": fix, "alt": alt, "effort": effort,
                "refs": refs or [], "question": question, "db": db, "baseline": baseline, "db_only": db_only}

    # ---------------------------------------------------------------- parsed SQL (database objects and SQL embedded in code)
    def db_findings(self, dbi):
        """Findings from the T-SQL parser instead of line patterns: rules with a "parsed" mapping, plus one finding per construct
        that has no PostgreSQL equivalent (data/pg_conversion.json level "redesign"). Covers .sql objects and SQL in C#."""
        import _dbinventory as DBI
        mapped = [r for r in self.rules if r.get("parsed")]
        claimed = {k for r in mapped for k in r["parsed"].get("constructs", [])}
        sites = [(o, "database") for o in dbi.get("objects", [])] + [(o, "code") for o in dbi.get("code_sql", [])]
        for o, where in sites:
            project = self.project_of(os.path.join(self.root, o["file"]))
            label = f"{o.get('kind', '')} {o.get('name', '')}".strip() if where == "database" else "SQL embedded in code"
            calls = [c.split(".")[-1].lower() for c in o.get("calls", [])]
            cons = o.get("constructs") or {}
            for r in mapped:
                p = r["parsed"]
                hit_c = {k: cons[k] for k in p.get("constructs", []) if cons.get(k)}
                hit_p = sorted({c for c in calls if any(c.startswith(x) for x in p.get("calls", []))})
                n = sum(hit_c.values()) + len(hit_p)
                if n:
                    what = ", ".join([f"{k} x{v}" for k, v in hit_c.items()] + hit_p)
                    f = self.add(dict(r, db=dict(r.get("db") or {}, priced_by_inventory=True)), project, o["file"], o.get("line", 0),
                                 f"{label}: {what}", count=n, extra={"parsed": True})
                    f["source"] = "sql-parse"
            for k, v in cons.items():
                c = DBI.conversion(k)
                if c["level"] != "redesign" or k in claimed:
                    continue
                r = self.synthetic("DB-PG-" + slug(k).upper(), "database", f"No PostgreSQL equivalent: {k}", "High", "Confirmed",
                                   f"The T-SQL parser found `{k}`, which PostgreSQL cannot run as written; the feature has to be replaced "
                                   "by a different design before the object (or the SQL in code) can work on PostgreSQL.",
                                   c["pg"], effort="db-object-small", refs=["S11", "S12", "S14"],
                                   db={"pg": "redesign", "priced_by_inventory": True}, db_only=True)
                f = self.add(r, project, o["file"], o.get("line", 0), f"{label}: {k} x{v}", count=v, extra={"parsed": True})
                f["source"] = "sql-parse"
        for e in dbi.get("parse_errors", [])[:200]:
            r = self.synthetic("DB-SQL-SYNTAX", "database", "SQL script does not parse", "Medium", "Confirmed",
                               "Microsoft's T-SQL parser rejects this script, so it cannot be deployed as written (or it relies on a "
                               "tool-specific syntax such as SQLCMD variables). Objects in the failing batch are missing from the inventory.",
                               "Fix the syntax or confirm how the script is really deployed; rerun the scan.", effort="per-occurrence-small",
                               refs=["S11"], db={"pg": "rework", "priced_by_inventory": True}, db_only=True)
            f = self.add(r, self.project_of(os.path.join(self.root, e["file"])), e["file"], e.get("line", 0), e["message"])
            f["source"] = "sql-parse"

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
            if ftype == "sql" and self.parsed_sql and r.get("parsed"):  # the parser decides (db_findings), not the pattern
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
                    if r["id"] == "DATA-INTEGRATED-SECURITY" and re.search(r"(?i)\(localdb\)|AttachDbFilename|\bSQLEXPRESS\b", line):
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
                               "Store credentials in AWS Secrets Manager (with rotation); build the connection string at start-up.",
                               "Secrets Manager + rotation", "trivial", ["S11"])
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
                lic = n.get("licence_info") or {}
                if lic.get("verdict") and row["status"] in ("ok", "upgrade", "unknown", "licence"):
                    row["status"] = "licence"
                    row["severity"] = "Medium" if lic["verdict"] == "restrictive-now" else "Low"
                    row["note"] = lic["text"] + (" " + row["note"] if row["note"] and row["note"] not in lic["text"] else "")
                    row["licence"] = lic
                    if not row["replacement"] or row["replacement"] == "Current version":
                        row["replacement"] = (f"Stay on {lic['last_open']} (last version under {lic['used_label']}) or review / buy the new licence"
                                              if lic.get("last_open") else "Review the licence terms; find an open-source alternative if they do not fit")
            if online and (row.get("nuget") or {}).get("found"):
                row["recommendation"] = recommend(row, row["nuget"].get("versions_meta"), self.cfg.get("target_dotnet", "net10.0"))
                plat = row["nuget"].get("platform") or {}
                if (plat.get("win_only_native") or plat.get("win_only_lib")) and row["status"] in ("ok", "upgrade", "unknown", "licence", "replace"):
                    why = (f"ships native binaries only for Windows ({', '.join(plat['native_rids'])})" if plat.get("win_only_native")
                           else "its .NET builds target net*-windows only")
                    row["status"], row["severity"] = "windows-only", "High"
                    row["note"] = f"Windows-only on Linux: the version in use {why}. " + (row["note"] or "")
                    row["replacement"] = row["replacement"] if row["replacement"] not in ("", "Current version") else "A cross-platform package (or a version with linux-* binaries)"
            table.append(row)
            first = a["files"][0]
            line = self.find_line(first, pid)
            rec = row.get("recommendation") or {}
            if rec.get("action") == "downgrade":   # a suggestion, never enforced: the client may prefer to keep the version and buy the licence
                row["replacement"] = f"Optional, saves the licence cost: {rec['version']} ({rec['why']}). Or keep {', '.join(row['versions'])} with a licence."
            if rec.get("action") == "upgrade" and row["status"] not in ("blocker", "replace", "windows-only", "private"):
                big = any(k in r for r in rec.get("risks", []) for k in ("major version", "licence decision", "licence differs"))
                r = self.synthetic("PKG-UPGRADE", "packages", f"Package {pid}: {rec['action']} to {rec['version']}", "Medium" if big else "Low",
                                   "Confirmed", rec["why"] + (". Risks: " + "; ".join(rec["risks"]) if rec.get("risks") else "."),
                                   (f"Upgrade {pid} to {rec['version']} (the lowest safe version), not automatically to the latest." if rec["action"] == "upgrade"
                                    else f"Move {pid} back to {rec['version']} (last version under the old licence), or confirm the licence for the version in use."),
                                   rec["version"], "small-change" if big else "package-replace", ["S3"])
                r["id"] = f"PKG-UPG-{slug(pid)}"
                f = self.add(r, "(repository)", first, line, f"{pid} {', '.join(row['versions'])} -> {rec['version']}", count=len(a["projects"]))
                f["package"] = pid
                f["projects_affected"] = sorted(a["projects"])
            elif rec.get("risks") and any(k in x for x in rec["risks"] for k in ("Windows-only", "unmaintained")):
                r = self.synthetic("PKG-RISK", "packages", f"Package {pid}: {'; '.join(x for x in rec['risks'] if 'Windows-only' in x or 'unmaintained' in x)}",
                                   "Medium" if any("Windows-only" in x for x in rec["risks"]) else "Low", "Likely", "; ".join(rec["risks"]) + ".",
                                   "Plan a replacement, or confirm the package is still fit for the target.", "", "package-replace", ["S3"])
                r["id"] = f"PKG-RISK-{slug(pid)}"
                f = self.add(r, "(repository)", first, line, f"{pid} {', '.join(row['versions'])}", count=len(a["projects"]))
                f["package"] = pid
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
        winonly = {r["id"].lower() for r in table if r["status"] == "windows-only"}
        for r in table:
            deps = {dp.get("id", "").lower() for m in ((r.get("nuget") or {}).get("versions_meta") or []) if m["v"] in r["versions"]
                    for dp in m.get("deps", [])}
            hit = sorted(deps & winonly)
            if hit and r["status"] in ("ok", "upgrade", "unknown"):
                r["status"], r["severity"] = "windows-only", "Medium"
                r["note"] = f"Depends on Windows-only {', '.join(hit)}. " + (r["note"] or "")
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
                ("ssis", "DB-SSIS", "SSIS packages", "High", "SSIS packages need SQL Server Integration Services; they do not run against PostgreSQL.",
                 "Inventory packages; rebuild in AWS Glue / Step Functions, or keep SSIS against SQL Server while it remains.", "AWS Glue / Step Functions", {"pg": "redesign"}),
                ("ssrs", "DB-SSRS", "SSRS reports", "Medium", "SSRS reports are bound to SQL Server data sources and the SSRS server.",
                 "Decide where reports run and repoint data sources (PostgreSQL data source or the dual-database layer).", "PBIRS / QuickSight / SSRS on EC2", {"pg": "rework"}),
                ("ssas", "DB-SSAS", "SSAS models", "High", "SSAS models are bound to SQL Server and do not run against PostgreSQL.", "Keep SSAS on SQL Server while it remains, or move models to a managed analytics service.",
                 "Amazon Redshift + QuickSight", {"pg": "redesign"}),
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


# api.nuget.org state for this run: answers kept in memory (a failed lookup is not retried in the same run), and a breaker
# that stops further calls after repeated connection failures, so a machine without network does not wait out every timeout
_NET = {"lock": threading.Lock(), "raw": {}, "files": {}, "fail": 0, "ok": 0, "warned": False}
NET_FAIL_LIMIT = 5


def net_usable():
    with _NET["lock"]:
        if _NET["ok"] or _NET["fail"] < NET_FAIL_LIMIT:
            return True
        if not _NET["warned"]:
            _NET["warned"] = True
            print(f"WARN api.nuget.org unreachable ({_NET['fail']} connection failures): online package facts skipped for the "
                  "rest of this run; packages show as not verified. Rerun when online, or use --offline.")
        return False


def net_result(ok):
    with _NET["lock"]:
        _NET["ok" if ok else "fail"] += 1


def write_cache(path, obj):
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    os.replace(tmp, path)  # atomic, so a parallel lookup or a crash never sees half a file


def nuget_info(pid, versions, cache_dir):
    """Public package metadata from api.nuget.org (cached): latest version, frameworks, deprecation, vulnerabilities, licence.
    Only answers are cached on disk (a package, or 404 for one nuget.org does not have); network failures are retried next run."""
    os.makedirs(cache_dir, exist_ok=True)
    cp = os.path.join(cache_dir, slug(pid) + ".json")
    raw = _NET["raw"].get(pid.lower())
    if raw is None:
        try:
            raw = read_json(cp) if os.path.exists(cp) and time.time() - os.path.getmtime(cp) < 14 * 86400 else None
        except (ValueError, OSError):  # damaged cache entry (interrupted run): fetch again
            raw = None
        if raw is not None and (raw.get("error") and raw.get("status") != 404 or (raw.get("v", 0) < 3 and not raw.get("error"))):
            raw = None  # an older cache kept transient failures; v3 cache: licenseUrl + published
    if raw is None and not net_usable():
        raw = {"error": "api.nuget.org unreachable in this run", "status": None}
    elif raw is None:
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
            raw = {"v": 3, "items": [{"items": [{"catalogEntry": {k: it["catalogEntry"].get(k) for k in ("version", "listed", "published", "deprecation", "vulnerabilities", "licenseExpression", "licenseUrl", "dependencyGroups")}}
                                                for it in pg.get("items", [])]} for pg in pages]}
        except (urllib.error.URLError, OSError, ValueError) as ex:
            raw = {"error": str(ex)[:200], "status": getattr(ex, "code", None)}
        answered = not raw.get("error") or raw.get("status") is not None  # an HTTP status is an answer; no status = no connection
        net_result(answered)
        if not raw.get("error") or raw.get("status") == 404:
            write_cache(cp, raw)
    _NET["raw"][pid.lower()] = raw
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
            "vulnerable_versions": vuln, "licence": latest.get("licenseExpression"), "licence_info": licence_change(pid, entries, versions),
            "versions_meta": versions_meta(entries, versions), "platform": platform_assets(pid, entries, versions, cache_dir)}


def platform_assets(pid, entries, versions, cache_dir):
    """Native binaries in the version in use (runtimes/<rid>/native): Windows-only when every RID is win-*. Any package."""
    used = [v for v in versions if v]
    if not used:
        return None
    try:
        uv = max(used, key=ver_tuple)
    except ValueError:
        return None
    cp = os.path.join(cache_dir, f"{slug(pid)}-{slug(uv)}-files.json")
    key = cp.lower()
    files = _NET["files"].get(key)
    if files is None:
        try:
            files = read_json(cp) if os.path.exists(cp) else None
        except (ValueError, OSError):
            files = None
    if files is None and not net_usable():
        return None  # unknown, not "no native binaries"
    if files is None:
        try:
            reg = f"https://api.nuget.org/v3/registration5-gz-semver2/{pid.lower()}/{uv.lower()}.json"
            def get(u):
                with urllib.request.urlopen(urllib.request.Request(u, headers={"Accept-Encoding": "gzip", "User-Agent": "migration-assessment"}), timeout=20) as r:
                    b = r.read()
                return json.loads(gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b)
            leaf = get(get(reg)["catalogEntry"])
            files = [e.get("fullName", "") for e in leaf.get("packageEntries", [])]
            net_result(True)
            write_cache(cp, files)  # a version's file list never changes: cached for good, but only when it was read
        except (urllib.error.URLError, OSError, ValueError, KeyError) as ex:
            net_result(getattr(ex, "code", None) is not None or isinstance(ex, (ValueError, KeyError)))
            _NET["files"][key] = []
            return None  # failed lookup: unknown, retried next run
    _NET["files"][key] = files
    rids = sorted({f.split("/")[1] for f in files if f.lower().startswith("runtimes/") and f.count("/") >= 3 and "/native/" in f.lower()})
    libs = sorted({f.split("/")[1].lower() for f in files if f.lower().startswith("lib/") and f.count("/") >= 2})
    win_only_native = bool(rids) and all(r.lower().startswith("win") for r in rids)
    win_only_lib = bool(libs) and all("-windows" in l or l.startswith(("net4", "net3", "net2")) for l in libs) and any("-windows" in l for l in libs)
    return {"native_rids": rids, "win_only_native": win_only_native, "win_only_lib": win_only_lib}


# ---------------------------------------------------------------- version recommendation (any package, from nuget.org metadata)
def tfm_class(tfm, target_major):
    """'ok' (runs on the target .NET), 'windows' (target-compatible but Windows-only TFM), 'netfx' (.NET Framework only) or None."""
    t = (tfm or "").lower().lstrip(".")
    if t in ("", "any", "unsupported"):
        return None
    m = re.match(r"^net(?:coreapp)?(\d+)\.(\d+)(-windows.*)?$", t)
    if t.startswith(("netstandard", "netcoreapp")) or (m and int(m.group(1)) >= 5):
        if m and int(m.group(1)) >= 5 and int(m.group(1)) > target_major:
            return None                                   # needs a newer .NET than the target
        return "windows" if m and m.group(3) else "ok"
    if t.startswith(("netframework", "net4", "net3", "net2", "net1")) or re.match(r"^net\d{2,3}$", t):
        return "netfx"
    return None


def versions_meta(entries, versions):
    """Per-version facts the recommendation needs: frameworks, advisories, deprecation, licence rank, listed, published."""
    used = {v for v in versions if v}
    out = []
    for e in entries:
        v = e.get("version", "")
        if re.search(r"-", v) and v not in used:
            continue
        out.append({"v": v, "tfms": sorted({(g.get("targetFramework") or "any") for g in (e.get("dependencyGroups") or [])}),
                    "vuln": bool(e.get("vulnerabilities")), "deprecated": bool(e.get("deprecation")), "lic": licence_of(e)[0],
                    "lic_label": licence_of(e)[1],
                    "deps": [{"id": dp.get("id")} for g in (e.get("dependencyGroups") or []) for dp in (g.get("dependencies") or [])][:60],
                    "listed": e.get("listed", True) is not False, "published": (e.get("published") or "")[:10], "pre": "-" in v})
    return out


def recommend(row, meta, target):
    """Keep the version in use when it is safe on the target; otherwise the lowest version that fixes it, with the risks."""
    try:
        tmaj = int(re.match(r"net(\d+)", target).group(1))
    except (AttributeError, ValueError):
        tmaj = 10
    if not meta or not row["versions"]:
        return None
    by_v = {m["v"]: m for m in meta}
    cur = max(row["versions"], key=ver_tuple)
    cm = by_v.get(cur) or next((m for m in reversed(meta) if ver_tuple(m["v"]) <= ver_tuple(cur)), None)

    def compat(m):
        cls = {tfm_class(t, tmaj) for t in m["tfms"]} - {None}
        return "ok" if "ok" in cls else "windows" if "windows" in cls else "netfx" if "netfx" in cls else None

    def problems(m):
        p = []
        if compat(m) == "netfx":
            p.append(".NET Framework only")
        if m["vuln"]:
            p.append("has a published security advisory")
        if m["deprecated"]:
            p.append("deprecated on nuget.org")
        if not m["listed"]:
            p.append("unlisted on nuget.org")
        if m["pre"]:
            p.append("a prerelease")
        return p

    def lic_note(a, b):
        """Licence difference between two versions worth a risk line (also catches one custom licence replaced by another)."""
        if a.get("lic_label") and b.get("lic_label") and a["lic_label"] != b["lic_label"] and \
                ((b["lic"] or 0) > (a["lic"] or 0) or (b["lic"] or 0) >= 2):
            return f"licence differs: {a['v']} is {a['lic_label']}, {b['v']} is {b['lic_label']}: review the new terms"
        return None

    risks = []
    if len(row["versions"]) > 1:
        risks.append(f"{len(row['versions'])} different versions across projects ({', '.join(row['versions'])}): settle on one for the port")
    latest = next((m for m in reversed(meta) if not m["pre"] and m["listed"]), meta[-1])
    if latest.get("published") and latest["published"] < f"{datetime.date.today().year - 4}":
        risks.append(f"no release since {latest['published'][:4]}: likely unmaintained")
    if not cm:
        return {"action": "unknown", "version": None, "why": f"version {cur} not found on nuget.org", "risks": risks}
    if compat(cm) == "windows":
        risks.append("the target-compatible build is Windows-only (net*-windows): blocks Linux hosting")
    probs = problems(cm)
    lic = row.get("licence") or {}
    if lic.get("verdict") == "restrictive-now" and lic.get("last_open"):
        # the version in use is already under the new (paid / restrictive) licence: prefer the last open version when it is safe
        lo = by_v.get(lic["last_open"])
        if lo and not problems(lo) and compat(lo) in ("ok", "windows", None):
            if ver_tuple(lo["v"])[0] < ver_tuple(cm["v"])[0]:
                risks.append(f"moving back a major version ({ver_tuple(cm['v'])[0]} -> {ver_tuple(lo['v'])[0]}): check APIs the code uses")
            return {"action": "downgrade", "version": lo["v"], "risks": risks, "optional": True,
                    "why": f"{cur} is under {lic['used_label']}; {lo['v']} is the last version under {lo['lic_label']} and is compatible "
                           f"with {target}, with no advisories and not deprecated (or keep {cur} and buy / confirm the licence)"}
        probs.append(f"under {lic['used_label']} (the last open version {lic['last_open']} is not safe on {target})")
    if compat(cm) is None and not probs:
        return {"action": "keep", "version": cur, "risks": risks,
                "why": "no framework or security problem in the nuget.org metadata (frameworks not declared: confirm it builds on the target)"}
    if not probs:
        why = f"compatible with {target}, no advisories, not deprecated"
        if ver_tuple(latest["v"]) > ver_tuple(cur):
            why += f"; {latest['v']} is newer but upgrading is optional"
            lic = row.get("licence") or {}
            if lic.get("verdict") == "restrictive-on-upgrade":
                why += f" and changes the licence from {lic.get('changed_in')}"
        return {"action": "keep", "version": cur, "why": why, "risks": risks}
    cands = [m for m in meta if ver_tuple(m["v"]) >= ver_tuple(cm["v"]) and not problems(m) and compat(m) in ("ok", "windows")]
    same_lic = [m for m in cands if cm["lic"] is None or m["lic"] is None or m["lic"] <= cm["lic"]]
    pick = same_lic[0] if same_lic else (cands[0] if cands else None)
    if not pick:
        return {"action": "replace", "version": None, "why": f"{cur}: {'; '.join(probs)}; no later version fixes it", "risks": risks}
    if not same_lic:
        risks.append(f"every fixed version is under a more restrictive licence than {cur}: licence decision needed")
    elif lic_note(cm, pick):
        risks.append(lic_note(cm, pick))
    if ver_tuple(pick["v"])[0] > ver_tuple(cm["v"])[0]:
        risks.append(f"major version jump {ver_tuple(cm['v'])[0]} -> {ver_tuple(pick['v'])[0]}: breaking API changes likely")
    return {"action": "upgrade", "version": pick["v"], "why": f"{cur}: {'; '.join(probs)}. {pick['v']} is the lowest version that fixes it",
            "risks": risks}


# ---------------------------------------------------------------- licence classification (any package, from nuget.org metadata)
# Rank: 0 permissive, 1 weak copyleft, 2 custom licence file / vendor licence page (not machine-readable), 3 strong copyleft
# or source-available / commercial. Only SPDX ids and the licence URL are read; no package names are special-cased.
LIC_PERMISSIVE = re.compile(r"(?i)^(MIT(-0)?|Apache-2\.0|Apache-1\.1|BSD-\d-Clause.*|ISC|MS-PL|Unlicense|0BSD|Zlib|PostgreSQL|BSL-1\.0|CC0-1\.0|"
                            r"WTFPL|X11|PSF-2\.0|Python-2\.0|NCSA|Libpng|curl|BlueOak-1\.0\.0|UPL-1\.0)$")
LIC_WEAK = re.compile(r"(?i)^(LGPL-.*|MPL-.*|EPL-.*|MS-RL|CDDL-.*|CPL-1\.0)$")
LIC_STRONG = re.compile(r"(?i)^(GPL-.*|AGPL-.*|RPL-.*|OSL-.*|SSPL-.*|EUPL-.*|CPAL-.*|BUSL-.*|PolyForm-.*|Elastic-.*|CC-BY-NC.*|LicenseRef-.*)$")
LIC_URL_HINTS = [(r"(?i)\bagpl|/gpl|gnu\.org/licenses/(gpl|agpl)", 3), (r"(?i)lgpl|mozilla\.org/mpl|/mpl", 1),
                 (r"(?i)\bmit\b|/mit(\.|$|/)|opensource\.org/licenses/mit", 0), (r"(?i)apache\.org/licenses|apache-2|/apache", 0),
                 (r"(?i)/bsd", 0), (r"(?i)/ms-pl|microsoft public license", 0)]


def spdx_rank(expr):
    """Rank of an SPDX expression: OR takes the most permissive choice, AND the most restrictive."""
    def one(tok):
        tok = tok.strip("() ").split(" WITH ")[0].strip()
        if LIC_PERMISSIVE.match(tok):
            return 0
        if LIC_WEAK.match(tok):
            return 1
        return 3 if LIC_STRONG.match(tok) else 2
    return min(max(one(t) for t in re.split(r"\s+AND\s+", alt)) for alt in re.split(r"\s+OR\s+", expr.strip("() ")))


def licence_of(e):
    """(rank, label) of one catalog entry, or (None, label) when nothing is declared."""
    expr, url = (e.get("licenseExpression") or "").strip(), (e.get("licenseUrl") or "").strip()
    if expr:
        return spdx_rank(expr), expr
    if not url:
        return None, "no licence declared"
    if re.search(r"(?i)nuget\.org/packages/[^/]+/[^/]+/licen[cs]e", url):
        return 2, "a custom licence file"
    for rx, rank in LIC_URL_HINTS:
        if re.search(rx, url):
            return rank, url
    return 2, f"a licence page ({url})"


def licence_change(pid, entries, versions):
    """Did the licence get more restrictive, either before the version in use (restrictive-now) or after it
    (restrictive-on-upgrade)? Compares every published version, so it catches any package that went commercial."""
    rel = sorted((e for e in entries if not re.search(r"-", e.get("version", "")) and e.get("listed", True) is not False),
                 key=lambda e: ver_tuple(e.get("version", "0")))
    used = [v for v in versions if v]
    if not rel or not used:
        return None
    try:
        uv = max(used, key=ver_tuple)
        ue = next((e for e in reversed(rel) if ver_tuple(e["version"]) <= ver_tuple(uv)), rel[0])
    except ValueError:
        return None
    ur, ul = licence_of(ue)
    lr, ll = licence_of(rel[-1])
    perm = [e for e in rel if licence_of(e)[0] == 0]
    if ur is not None and ur >= 2 and perm and ver_tuple(perm[-1]["version"]) < ver_tuple(ue["version"]):
        was = licence_of(perm[-1])[1]
        return {"verdict": "restrictive-now", "used_label": ul, "latest_label": ll, "last_open": perm[-1]["version"],
                "text": f"Licence changed: version {uv} in use is under {ul}; versions up to {perm[-1]['version']} were {was}. "
                        "Check the terms (commercial licence or free edition) before shipping the port, or move back to "
                        f"{perm[-1]['version']}."}
    if ur is not None and lr is not None and lr > ur and lr >= 2:
        first = next(e for e in rel if ver_tuple(e["version"]) > ver_tuple(ue["version"]) and (licence_of(e)[0] or 0) > ur)
        last_open = max((e["version"] for e in rel if licence_of(e)[0] == ur and ver_tuple(e["version"]) < ver_tuple(first["version"])),
                        key=ver_tuple, default=None)
        return {"verdict": "restrictive-on-upgrade", "used_label": ul, "latest_label": ll, "last_open": last_open, "changed_in": first["version"],
                "text": f"Licence changes on upgrade: {uv} in use is {ul}, but from {first['version']} the package is under {ll}. "
                        f"Upgrading to a current major during the port is a licence decision"
                        + (f"; {last_open} is the last version under {ul}." if last_open else ".")}
    if ur == 3:
        return {"verdict": "restrictive-now", "used_label": ul, "latest_label": ll, "last_open": None,
                "text": f"Version {uv} in use is under {ul} (copyleft or source-available): check it fits how the product is distributed."}
    return None


def scan_repo(name, cfg, online):
    inv = read_json(os.path.join(OUT, "inventory", f"{name}.json"))
    if not inv:
        sys.exit(f"no inventory for {name}: run discover_estate.py first")
    t0 = time.time()
    s = Scan(name, inv, cfg)
    import _dbinventory
    s.facts["db_inventory"] = _dbinventory.inventory(inv["root"], cfg.get("exclude_dirs", []))
    s.parsed_sql = bool(s.facts["db_inventory"].get("engine"))
    s.scan_files()
    s.db_findings(s.facts["db_inventory"])
    s.packages(online)
    s.structure()
    s.case_paths()
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
