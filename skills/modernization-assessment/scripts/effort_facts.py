"""Every fact the phased estimate needs for one repository, in one place, and the quantities behind each work item.

    py -X utf8 effort_facts.py [--repo X | --all]

Run after scan_repo.py (and atf_scan.py, build_check.py when used). Reads this assessment's own outputs, never changes
the repository:
  assessment/inventory/<repo>.json, scan/<repo>.json (packages, DLL references, endpoints, connection strings),
  findings/<repo>.json, atf/<repo>/atf.json (AWS Transform scanner cross-check), build/index.json (build_check.py),
  raw_sql.py's inventory (stored procedures, raw SQL, constructs, data-access API), and the code itself: Web Forms
  census, handlers and services, SOAP / WCF service references, web.config surface, request / response contracts, git.
Also runs aws_native.py for the repository (server-hosted services -> AWS managed services), with the source of the
libraries it references when the estate or `source_search_roots` holds it.

Writes assessment/effort/<repo>/: facts.json, effort-inputs.md (+ .html; quantities and evidence per work item, no
hours), aws-native.json / .md / .html. estimate_phases.py turns them into hours.
"""
import argparse
import glob
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone

from _common import OUT, load_config, load_state, read_json, utf8_stdout, write_json
from _mdhtml import write_pair

SKIP = {"bin", "obj", ".vs", ".git", "node_modules", "testresults"}
SEV = ["Blocker", "High", "Medium", "Low", "Info"]


def J(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def read(p):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return open(p, encoding=enc).read()
        except UnicodeDecodeError:
            continue
    return open(p, encoding="utf-8", errors="ignore").read()


def walk(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x.lower() not in SKIP and not (x.lower() == "packages" and
                   any(f.endswith(".nupkg") for s in os.listdir(os.path.join(d, x))[:5]
                       if os.path.isdir(os.path.join(d, x, s)) for f in os.listdir(os.path.join(d, x, s))))]
        for f in files:
            yield os.path.join(d, f)


def lines(p):
    try:
        return read(p).count("\n") + 1
    except OSError:
        return 0


def web_census(root, projects):
    """Web Forms pages / controls / masters / handlers / services per project, LOC with code-behind, control tags."""
    out = {}
    for pr in projects:
        pdir = os.path.join(root, os.path.dirname(pr["path"]))
        c = {"pages": [], "user_controls": [], "masters": [], "handlers": [], "asmx": [], "svc": [], "global_asax": [],
             "control_tags": Counter(), "viewstate_refs": 0, "update_panels": 0, "postback_handlers": 0}
        for p in walk(pdir):
            rel = os.path.relpath(p, root).replace("\\", "/")
            if "/Web References/" in rel or "/Service References/" in rel:
                continue
            low = p.lower()
            kind = {".aspx": "pages", ".ascx": "user_controls", ".master": "masters", ".ashx": "handlers", ".asmx": "asmx",
                    ".svc": "svc", ".asax": "global_asax"}.get(os.path.splitext(low)[1])
            if not kind:
                continue
            t = read(p)
            cb = [q for q in (p + ".cs", p + ".vb") if os.path.exists(q)]
            des = [q for q in (p + ".designer.cs", p + ".designer.vb") if os.path.exists(q)]
            c[kind].append({"file": rel, "markup_lines": t.count("\n") + 1, "code_behind_lines": sum(lines(q) for q in cb),
                            "designer_lines": sum(lines(q) for q in des)})
            for tag in re.findall(r"<(\w+):(\w+)", t):
                if tag[0].lower() not in ("xsl", "xs", "soap", "wsdl"):
                    c["control_tags"][tag[0] + ":" + tag[1]] += 1
            c["update_panels"] += len(re.findall(r"<asp:UpdatePanel", t, re.I))
            for q in cb:
                ct = read(q)
                c["viewstate_refs"] += len(re.findall(r"\bViewState\s*\[", ct))
                c["postback_handlers"] += len(re.findall(r"\bIsPostBack\b|_Click\s*\(|_SelectedIndexChanged\s*\(|_RowCommand\s*\(", ct))
        c["control_tags"] = dict(c["control_tags"].most_common())
        c["totals"] = {k: len(c[k]) for k in ("pages", "user_controls", "masters", "handlers", "asmx", "svc", "global_asax")}
        c["totals"]["markup_lines"] = sum(x["markup_lines"] for k in ("pages", "user_controls", "masters") for x in c[k])
        c["totals"]["code_behind_lines"] = sum(x["code_behind_lines"] for k in ("pages", "user_controls", "masters", "handlers", "asmx", "svc", "global_asax") for x in c[k])
        out[pr["path"]] = c
    return out


def service_refs(root):
    """Web References / Service References / Connected Services: generated proxies and how much hand-written code uses them."""
    refs = []
    for p in glob.glob(os.path.join(root, "**", "*"), recursive=True):
        b = os.path.basename(p)
        if os.path.isdir(p) and b in ("Web References", "Service References", "Connected Services"):
            for d in sorted(os.listdir(p)):
                full = os.path.join(p, d)
                if not os.path.isdir(full):
                    continue
                gen = [q for q in glob.glob(os.path.join(full, "*")) if q.lower().endswith((".cs", ".vb"))]
                gen_lines = sum(lines(q) for q in gen)
                src = " ".join(read(q) for q in gen)
                refs.append({"kind": b, "name": d, "folder": os.path.relpath(full, root).replace("\\", "/"),
                             "generated_lines": gen_lines, "operations": len(re.findall(r"SoapDocumentMethodAttribute|OperationContractAttribute", src)),
                             "types": len(re.findall(r"public partial class \w+", src)),
                             "wsdl": [os.path.basename(q) for q in glob.glob(os.path.join(full, "*.wsdl"))],
                             "urls": sorted(set(re.findall(r"https?://[^\s\"<]+", " ".join(read(q) for q in glob.glob(os.path.join(full, "*.discomap")) + glob.glob(os.path.join(full, "*.map"))))))[:5]})
    hand = [p for p in walk(root) if p.lower().endswith((".cs", ".vb")) and "Web References" not in p and "Service References" not in p]
    texts = {p: read(p) for p in hand}
    for r in refs:
        rx = re.compile(r"\b" + re.escape(r["name"]) + r"\.\w+")
        uses = Counter()
        for p, t in texts.items():
            n = len(rx.findall(t))
            if n:
                uses[os.path.relpath(p, root).replace("\\", "/")] = n
        r["hand_written_uses"] = sum(uses.values())
        r["files_using"] = len(uses)
        gen = " ".join(read(q) for q in glob.glob(os.path.join(root, r["folder"], "*")) if q.lower().endswith((".cs", ".vb")))
        names = set(re.findall(r"(?:SoapDocumentMethodAttribute|SoapRpcMethodAttribute|OperationContractAttribute)\([^)]*\)\][^\n]*\n[^\n]*?public\s+[\w.<>\[\], ]+\s+(\w+)\s*\(", gen))
        called = Counter()
        for t in texts.values():
            for n in names:
                k = len(re.findall(r"\.\s*" + re.escape(n) + r"\s*\(", t))
                if k:
                    called[n] += k
        r["operations_called"] = dict(called.most_common())
        r["soap_client_calls"] = sum(len(re.findall(r"\bnew\s+" + re.escape(r["name"]) + r"\.\w+(Service|Client|SoapClient|WS)\s*\(", read(p))) for p in hand)
    return refs


def config_surface(root):
    out = []
    for p in walk(root):
        b = os.path.basename(p).lower()
        if not (b == "web.config" or b == "app.config" or re.match(r"web\.\w+\.config$", b)):
            continue
        t = read(p)
        keys = re.findall(r'<add\s+key="([^"]+)"', t)
        out.append({"file": os.path.relpath(p, root).replace("\\", "/"), "transform": bool(re.match(r"web\.\w+\.config$", b)),
                    "custom_sections": re.findall(r'<section\s+name="([^"]+)"', t), "app_settings": len(keys),
                    "address_settings": [k for k in keys if re.search(r"url|uri|endpoint|host|server|path|dir|folder|ip\b", k, re.I)],
                    "feature_flags": [k for k in keys if re.match(r"(use|enable|disable|is)[A-Z_.]", k)],
                    "protected_sections": re.findall(r'<(\w+)\s+configProtectionProvider="([^"]+)"', t),
                    "protection_providers": re.findall(r'<add\s+[^>]*name="([^"]+)"[^>]*type="(System\.Configuration\.\w+ProtectedConfigurationProvider)"', t)
                    + re.findall(r'<add\s+[^>]*type="(System\.Configuration\.\w+ProtectedConfigurationProvider)"[^>]*name="([^"]+)"', t),
                    "key_containers": re.findall(r'keyContainerName="([^"]+)"', t),
                    "auth_mode": re.findall(r'<authentication\s+mode="(\w+)"', t), "impersonate": re.findall(r'<identity\s+impersonate="(\w+)"', t),
                    "handlers_modules": re.findall(r'<add\s+[^>]*name="([^"]+)"[^>]*type="([^"]+)"', t)[:20] if re.search(r"<(httpHandlers|httpModules|handlers|modules)", t) else [],
                    "config_source_files": re.findall(r'configSource="([^"]+)"', t), "session_state": re.findall(r"<sessionState\s+[^>]*mode=\"(\w+)\"", t),
                    "machine_key": "<machineKey" in t, "target_framework": re.findall(r'targetFramework="([^"]+)"', t)[:2],
                    "custom_errors": re.findall(r'<customErrors\s+mode="(\w+)"', t), "debug": re.findall(r'<compilation\s+[^>]*debug="(\w+)"', t)})
    return out


def contracts(root):
    """Public API surface: request / response classes, controllers, web methods, operation contracts, handlers."""
    rq, rs, ctrl, webm, ops = set(), set(), set(), 0, 0
    for p in walk(root):
        if not p.lower().endswith(".cs") or "Web References" in p or "Service References" in p:
            continue
        t = read(p)
        rq.update(re.findall(r"class\s+(\w+(?:RQ|Request))\b", t))
        rs.update(re.findall(r"class\s+(\w+(?:RS|Response))\b", t))
        ctrl.update(re.findall(r"class\s+(\w+Controller)\b", t))
        webm += len(re.findall(r"\[WebMethod", t))
        ops += len(re.findall(r"\[OperationContract", t))
    return {"request_types": sorted(rq), "response_types": sorted(rs), "controllers": sorted(ctrl), "web_methods": webm, "operation_contracts": ops}


def git_facts(root):
    def g(*a):
        try:
            return subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"branch": g("rev-parse", "--abbrev-ref", "HEAD"), "commit": g("rev-parse", "--short", "HEAD"),
            "last_commit": g("log", "-1", "--format=%ad %s", "--date=short"),
            "commits_365d": len(g("log", "--since=365.days", "--format=%h").splitlines()),
            "authors_365d": len(set(g("log", "--since=365.days", "--format=%ae").splitlines())), "first_commit": g("log", "--reverse", "--format=%ad", "--date=short").split("\n")[0]}


def code_usage(root):
    """Counts the estimate needs straight from the code: uses of ambient request context (CallContext / the class that
    wraps it, through its static Current) and configuration reads (ConfigurationManager / WebConfigurationManager)."""
    texts = {}
    for p in walk(root):
        if p.lower().endswith((".cs", ".vb")) and "Web References" not in p and "Service References" not in p:
            texts[p] = read(p)
    wrappers = sorted({c for t in texts.values() if re.search(r"\bCallContext\.", t) for c in re.findall(r"^\s*(?:(?:public|internal|static|sealed|partial|abstract)\s+)*class\s+([A-Z]\w*)", t, re.M)})
    uses, files = 0, 0
    for t in texts.values():
        n = sum(len(re.findall(r"\b" + re.escape(c) + r"\.Current\b", t)) for c in wrappers) + len(re.findall(r"\bCallContext\.\w+", t))
        uses, files = uses + n, files + (1 if n else 0)
    cfg = Counter()
    for p, t in texts.items():
        n = len(re.findall(r"\b(?:Web)?ConfigurationManager\.(?:AppSettings|ConnectionStrings|GetSection)\b", t))
        if n:
            cfg[os.path.relpath(p, root).replace("\\", "/")] = n
    return {"ambient_context": {"wrapper_classes": wrappers, "uses": uses, "files": files},
            "config_reads": {"reads": sum(cfg.values()), "files": len(cfg)}}


def network_roles(scan):
    """Outbound network targets; the scan guesses a role from the port, the setting names say what the server really is."""
    out = []
    for n in (scan.get("network") or {}).get("outbound", []):
        x = {k: n.get(k) for k in ("host", "port", "scheme", "kind", "role", "keys", "files")}
        keys, files = " ".join(x["keys"] or []), x["files"] or []
        corrected = None
        if re.search(r"aerospike", keys, re.I):
            corrected = ("Cache (Aerospike)", 3000)
        elif re.search(r"memcache", keys, re.I):
            corrected = ("Cache (Memcached)", 11211)
        elif re.search(r"\bmongo", keys, re.I):
            corrected = ("Document store (MongoDB)", 27017)
        elif files and all("/Web References/" in f or "/Service References/" in f for f in files):
            corrected = ("XML namespace in a WSDL / proxy (not a call)", None)
        if corrected and corrected[0] != x["role"]:
            x["scan_role"], x["role"] = x["role"], corrected[0]
            m = re.search(r"\((\w+)\)", corrected[0])
            if m and corrected[1]:
                x["scheme"] = m.group(1).lower()
            if corrected[1]:
                x["scan_port"], x["port"] = x["port"], str(corrected[1]) + " (default; not set in config)"
        out.append(x)
    return out


def library_dirs(scan):
    """Folders holding the source of DLLs this repository references (from the scan's DLL table), for aws_native.py."""
    out = set()
    invs = {os.path.splitext(os.path.basename(p))[0]: read_json(p) or {} for p in glob.glob(os.path.join(OUT, "inventory", "*.json"))}
    for b in scan.get("binary_references", []):
        for s in (b.get("source") or "").split("; "):
            path = re.sub(r" \([^)]*\)$", "", s.strip())
            if not path or path.startswith("no source"):
                continue
            if os.path.isabs(path):
                out.add(os.path.dirname(path))
            else:
                repo, _, rest = path.partition("/")
                root = (invs.get(repo) or {}).get("root")
                if root:
                    out.add(os.path.dirname(os.path.join(root, rest)))
    return sorted(out)


def collect(repo, cfg):
    import raw_sql
    import aws_native as AN
    inv = read_json(os.path.join(OUT, "inventory", repo + ".json"), {}) or {}
    root = inv["root"]
    scan = read_json(os.path.join(OUT, "scan", repo + ".json"), {}) or {}
    fnd = read_json(os.path.join(OUT, "findings", repo + ".json"), []) or []
    atf = read_json(os.path.join(OUT, "atf", repo, "atf.json"), {}) or {}
    sols = [s["id"] for s in (read_json(os.path.join(OUT, "solutions", "index.json"), {}) or {}).get("solutions", []) if s.get("repo") == repo]
    build = [b for b in (read_json(os.path.join(OUT, "build", "index.json"), {}) or {}).get("solutions", []) if b["id"] in sols]
    sql = raw_sql.inventory(root, repo)
    projects = inv.get("projects", [])
    facts = {"repo": repo, "root": root, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git": git_facts(root)}
    facts["solutions"] = [{"file": s.get("path") or s.get("file"), "projects": s.get("projects")} for s in inv.get("solutions", [])]
    facts["projects"] = [{"path": p["path"], "type": p.get("type"), "frameworks": p.get("target_frameworks"), "sdk_style": p.get("sdk_style"),
                          "packages_config": p.get("packages_config"), "output_type": p.get("output_type"), "deployable": p.get("deployable"),
                          "loc_handwritten": p.get("loc_handwritten"), "loc_markup": p.get("loc_markup"), "loc_generated": p.get("loc_generated"),
                          "loc_exec": p.get("loc_exec"), "loc_config": (p.get("loc") or {}).get("config"), "files_by_ext": p.get("files_by_ext"),
                          "complexity": p.get("complexity"), "project_references": p.get("project_references"),
                          "referenced_by": p.get("referenced_by")} for p in projects]
    facts["totals"] = inv.get("totals")
    facts["web"] = web_census(root, projects)
    facts["service_references"] = service_refs(root)
    facts["binary_references"] = scan.get("binary_references", [])
    facts["packages"] = [{"id": p["id"], "versions": p.get("versions"), "status": p.get("status"), "note": p.get("note"),
                          "replacement": p.get("replacement"), "supports_modern": (p.get("nuget") or {}).get("supports_modern"),
                          "latest": p.get("latest"), "frameworks": p.get("frameworks"), "runs_on_linux": p.get("runs_on_linux"),
                          "deprecated": (p.get("nuget") or {}).get("deprecated"), "vulnerable_used": bool(p.get("vulnerable"))}
                         for p in scan.get("packages", [])]
    facts["config"] = config_surface(root)
    facts["code_usage"] = code_usage(root)
    facts["contracts"] = contracts(root)
    facts["network"] = network_roles(scan)
    facts["endpoints"] = len(scan.get("endpoints") or [])
    facts["connection_strings"] = [{k: c.get(k) for k in ("file", "line", "name", "host", "database", "auth", "password_in_config")}
                                   for c in scan.get("connection_strings") or []]
    facts["scheduled_jobs"] = scan.get("scheduled_jobs") or []
    facts["tests"] = {"test_projects": [p["path"] for p in projects if p.get("type") == "test"], "scan": scan.get("tests"),
                      "tests_per_kloc": scan.get("tests_per_kloc")}
    facts["activity"] = scan.get("activity_level")
    facts["findings"] = sorted([{"rule": f["rule"], "title": f["title"], "severity": f["severity"], "category": f["category"],
                                 "project": f.get("project"), "occurrences": f.get("occurrences"), "files": len(f.get("files") or []),
                                 "evidence": [(e.get("file"), e.get("line")) for e in (f.get("evidence") or [])[:3]]} for f in fnd],
                               key=lambda x: (SEV.index(x["severity"]) if x["severity"] in SEV else 9, x["rule"]))
    facts["sql"] = {"summary": sql.get("summary"), "procedures": [{k: p[k] for k in ("name", "call_sites", "apis", "output_params", "tvp",
                                                                                     "multi_result", "for_xml", "params", "columns_read")}
                                                                  for p in sql.get("procedures", [])],
                    "statements": [{k: c.get(k) for k in ("file", "line", "source", "text", "parsed", "dynamic", "reads", "writes", "constructs",
                                                          "conversion", "redesign", "dialect")} for c in sql.get("statements", []) + sql.get("fragments", [])],
                    "wrappers": sql.get("wrappers")}
    rq = atf.get("rasql")
    if rq:
        facts["atf_rasql"] = {"atf_rows": rq["rows"], "ours": rq["ours"], "atf_other_counts": rq["atf_other_counts"], "ours_only": rq["ours_only"],
                              "inline_sql": {k: rq["inline_sql"][k] for k in ("atf", "matched", "atf_only_by_reason")},
                              "execute_calls": {k: rq["execute_calls"][k] for k in ("atf", "matched", "atf_only_by_reason")}}
    if atf.get("radnet"):
        facts["atf_radnet"] = {k: atf["radnet"][k] for k in ("loc_exec", "local_dlls", "nuget", "com", "dllimport")}
    facts["build"] = build
    out = os.path.join(OUT, "effort", repo)
    os.makedirs(out, exist_ok=True)
    choices = (read_json(os.path.join(out, "estimate-inputs.json"), {}) or {}).get("aws_native_choices", {}).get("value") or cfg.get("aws_native_choices") or {}
    aws = AN.scan(root, library_dirs(scan), facts, choices)
    write_json(os.path.join(out, "aws-native.json"), aws)
    write_pair(os.path.join(out, "aws-native.md"), AN.render(aws, repo))
    write_json(os.path.join(out, "facts.json"), json.loads(json.dumps(facts, default=str)))
    return facts


def render_md(f):
    sq = f["sql"]["summary"] or {}
    spx = sq.get("stored_procedures", {})
    raw = sq.get("raw_sql", {})
    api = sq.get("data_access_api", {})
    fnd = f["findings"]
    by_rule = {x["rule"]: x for x in fnd}
    L = [f"# Modernization effort inputs: {f['repo']}", "",
         f"Repository `{f['root']}` · branch {f['git'].get('branch')} · commit {f['git'].get('commit')} · last commit {f['git'].get('last_commit')}",
         f"Generated {f['generated']} by effort_facts.py from this assessment's inventory, scan, findings, raw_sql.py and the AWS Transform scanner cross-check.",
         "Quantities only: no hours (estimate_phases.py prices them). Every number links back to facts.json or the scan findings.", ""]

    # 1. shape
    t = f.get("totals") or {}
    L += ["## 1. Shape of the code", ""]
    rows = []
    for p in f["projects"]:
        w = f["web"].get(p["path"], {}).get("totals", {})
        rows.append([p["path"], p["type"], ", ".join(p["frameworks"] or []), "SDK" if p["sdk_style"] else "legacy",
                     "yes" if p["packages_config"] else "no", p["loc_handwritten"], p["loc_markup"], p["loc_generated"],
                     (p.get("complexity") or {}).get("methods"), (p.get("complexity") or {}).get("cc_per_method"),
                     f"{w.get('pages', 0)} / {w.get('user_controls', 0)} / {w.get('masters', 0)} / {w.get('handlers', 0)} / {w.get('asmx', 0) + w.get('svc', 0)}"])
    L += md_table(["Project", "Type", "Framework", "Project file", "packages.config", "C# lines (hand-written)", "Markup lines",
                   "Generated lines", "Methods", "Avg complexity", "Pages / controls / masters / handlers / services"], rows)
    c = f["contracts"]
    L += ["", f"- Solution(s): {len(f['solutions'])}; projects {t.get('projects')}; files {t.get('files')}; total lines {t.get('loc')} "
          f"(by kind {t.get('loc_by_language')}).",
          f"- Public API surface: {len(c['request_types'])} request types, {len(c['response_types'])} response types, "
          f"{len(c['controllers'])} controllers, {c['web_methods']} [WebMethod]s, {c['operation_contracts']} WCF operations.",
          f"- Request types: {', '.join(c['request_types'])}." if c["request_types"] else "- Request types: none found.",
          f"- Automated tests: {len(f['tests']['test_projects'])} test projects; {by_rule.get('TEST-LOW-COVERAGE', {}).get('title', 'no low-coverage finding')}.",
          f"- Activity: {f.get('activity')}; commits in the last 365 days {f['git'].get('commits_365d')} by {f['git'].get('authors_365d')} author(s); "
          f"history starts {f['git'].get('first_commit')} (a single-commit history means the repository was imported as a snapshot).", ""]

    # 2. Stage B
    L += ["## 2. Port to .NET 10 on Linux containers (Stage B items)", "",
          "### B1 Build and pipeline", ""]
    lb = f.get("build") or []
    for b in lb:
        st, rl = b.get("static") or {}, b.get("real") or {}
        L.append(f"- {b.get('id')}: static check {st.get('status', 'not run')}; real build {rl.get('status', 'NOT RUN')}"
                 + (f" ({rl.get('configuration')}, {rl.get('error_count')} errors)" if rl.get("configuration") else "") + " (build_check.py).")
        for pr in st.get("prerequisites", []):
            L.append(f"  - prerequisite: {pr}")
    L += [f"- Legacy (non-SDK) project files: {t.get('legacy_project_files')}; packages.config projects: {t.get('packages_config')}.",
          f"- Publish / transform files: {', '.join(x['file'] for x in f['config'] if x['transform']) or 'none'}; findings "
          + ", ".join(r for r in ("BUILD-WEB-TARGETS", "IIS-PUBLISH", "CFG-TRANSFORMS", "INV-LEGACY-PROJECT", "INV-PACKAGES-CONFIG") if r in by_rule) + ".", ""]

    L += ["### B3 What the porting engine ports, and what is left", ""]
    rows = []
    for x in fnd:
        if x["category"] in ("web-platform", "api-portability", "auth", "front-end", "state-scale", "hosting", "hypervisor",
                             "file-handling", "time-culture", "security", "logging", "configuration-secrets", "data-access", "database"):
            rows.append([x["severity"], x["rule"], x["title"], x["project"] or "", x["occurrences"], x["files"],
                         "; ".join(f"{e[0]}:{e[1]}" for e in x["evidence"][:2])])
    L += md_table(["Severity", "Rule", "Finding", "Project", "Occurrences", "Files", "Evidence"], rows) + [""]
    for p, w in f["web"].items():
        if w["totals"]["pages"] or w["totals"]["user_controls"]:
            L.append(f"- {p}: Web Forms {w['totals']['pages']} pages, {w['totals']['user_controls']} user controls, {w['totals']['masters']} master pages; "
                     f"{w['totals']['markup_lines']} markup lines + {w['totals']['code_behind_lines']} code-behind lines; ViewState uses {w['viewstate_refs']}, "
                     f"postback handlers {w['postback_handlers']}, UpdatePanels {w['update_panels']}; controls: "
                     + ", ".join(f"{k} x{v}" for k, v in list(w["control_tags"].items())[:15]) + ".")
        if w["totals"]["handlers"] or w["totals"]["asmx"] or w["totals"]["svc"]:
            L.append(f"- {p}: {w['totals']['handlers']} HTTP handler(s) (.ashx), {w['totals']['asmx']} ASMX, {w['totals']['svc']} WCF .svc: "
                     + ", ".join(x["file"] for k in ("handlers", "asmx", "svc") for x in w[k]) + ".")
    L.append("")

    L += ["### Service clients (SOAP / WCF references)", ""]
    rows = [[r["name"], r["kind"], r["generated_lines"], r["operations"], len(r.get("operations_called") or {}), r["types"],
             r["hand_written_uses"], r["files_using"], ", ".join(u for u in r["urls"] if "w3.org" not in u)] for r in f["service_references"]]
    L += (md_table(["Reference", "Kind", "Generated lines", "Operations defined", "Operations called", "Types", "Uses in hand-written code",
                    "Files using", "Endpoint"], rows) if rows else ["- none"]) + [""]
    for r in f["service_references"]:
        if r.get("operations_called"):
            L.append(f"- {r['name']} operations called: " + ", ".join(f"{k} x{v}" for k, v in r["operations_called"].items()) + ".")
    L.append("")

    L += ["### Binary (non-NuGet) references", ""]
    rows = [[b["project"], b["assembly"], b["built_for"], b["other_builds"], b["nuget"], b["runs_on_linux"], b["action"], b["source"]]
            for b in f["binary_references"]]
    L += (md_table(["Project", "Assembly", "Built for", "Other builds next to it", "nuget.org", "Runs on Linux", "Action", "Source"], rows)
          if rows else ["- none"]) + [""]

    L += ["### NuGet packages", ""]
    rows = [[p["id"], ", ".join(p["versions"] or []), p["status"], p.get("runs_on_linux") or "-", p.get("latest") or "-", p.get("frameworks") or "-",
             p.get("replacement") or "-", (p.get("note") or "-")[:120]] for p in f["packages"]]
    L += md_table(["Package", "Version", "Status", "Runs on Linux", "Latest", "Latest targets", "Replacement / action", "Note"], rows) + [""]

    L += ["### B7 Configuration, secrets, hosting coupling", ""]
    for cfg in f["config"]:
        if cfg["transform"]:
            continue
        L.append(f"- {cfg['file']}: {cfg['app_settings']} appSettings; custom sections {cfg['custom_sections']}; protected sections "
                 f"{cfg['protected_sections']} via {cfg['protection_providers']} (key container {cfg['key_containers']}); auth {cfg['auth_mode'] or '-'}; "
                 f"handlers/modules {[h[0] for h in cfg['handlers_modules'] if 'Protected' not in h[1]]}; external config files {cfg['config_source_files']}; "
                 f"compilation debug={cfg['debug']}; address settings {cfg['address_settings']}.")
    L.append(f"- Connection strings found by the scan: {len(f['connection_strings'])} "
             f"({Counter(c['file'] for c in f['connection_strings']).most_common()}); databases named: "
             f"{sorted({c['database'] for c in f['connection_strings'] if c.get('database')}) or 'none in clear text'}.")
    L.append("")

    # 3. Stage A
    L += ["## 3. SQL Server -> PostgreSQL, application side (Stage A items)", "",
          f"Parser: {f['sql'].get('summary', {}) and 'ScriptDom (T-SQL)'}; raw SQL found in {raw.get('files', 0)} files. "
          "Database objects themselves (procedure bodies, tables) are not in this repository; they are the DB team's scope.", ""]
    rows = [
        ["A1 Provider swap (System.Data.SqlClient -> Npgsql)", f"{api.get('System.Data.SqlClient using', {}).get('files', 0)} files import SqlClient; "
         f"Sql* objects created {api.get('Sql* types (new SqlConnection/Command/Parameter/DataAdapter)', {}).get('hits', 0)} times in "
         f"{api.get('Sql* types (new SqlConnection/Command/Parameter/DataAdapter)', {}).get('files', 0)} files; SqlDataReader {api.get('SqlDataReader', {}).get('hits', 0)} uses"],
        ["A2 Raw SQL dialect", f"{raw.get('statements', 0)} statements ({raw.get('parsed', 0)} parse as T-SQL, {raw.get('did_not_parse', 0)} do not), "
         f"{raw.get('fragments', 0)} fragments, {raw.get('dynamic', 0)} built at run time; conversion levels {sq.get('conversion_levels')}"],
        ["A3 Stored-procedure invocation", f"{spx.get('distinct', 0)} distinct procedures, {spx.get('call_sites', 0)} call sites "
         f"({spx.get('via_wrappers', 0)} through {spx.get('wrapper_methods', 0)} wrapper method(s)); unresolved names {spx.get('unresolved_names', 0)}"],
        ["A4 Multi-result sets", f"{spx.get('multi_result', 0)} procedures read more than one result set"],
        ["A5 Behaviour shim", f"SqlException.Number logic {api.get('SqlException.Number (error-number logic)', {}).get('hits', 0)} hits; "
         f"SqlDbType {api.get('SqlDbType', {}).get('hits', 0)}; OUTPUT params in {spx.get('with_output_params', 0)} procedures; "
         f"return values {spx.get('with_return_value', 0)}; table-valued params {spx.get('with_tvp', 0)}; transactions "
         f"{api.get('SqlTransaction / BeginTransaction', {}).get('hits', 0) + api.get('TransactionScope', {}).get('hits', 0)}"],
        ["A5b FOR XML results (no PostgreSQL equivalent)", f"{spx.get('for_xml_readers', 0)} procedures read through ExecuteXmlReader; "
         f"{api.get('ExecuteXmlReader (FOR XML)', {}).get('hits', 0)} ExecuteXmlReader references"],
        ["A6 FILESTREAM / SqlFileStream", f"{api.get('SqlFileStream', {}).get('hits', 0)} uses"],
        ["A7 Identity / EF store", f"EF6 {api.get('Entity Framework 6', {}).get('hits', 0)}, EF Core {api.get('EF Core', {}).get('hits', 0)} references"],
        ["A8 Cross-database references", f"databases in three-part names {sq.get('databases_in_three_part_names')}; "
         f"constructs: cross-database {sq.get('constructs', {}).get('cross-database', 0)}, run-time database name "
         f"{sq.get('constructs', {}).get('dynamic database name', 0)}; procedure names with a run-time database: "
         f"{sum(1 for p in f['sql']['procedures'] if '{db}' in p['name'])}"],
        ["A9 Connection re-points", f"{sq.get('connection_strings', {}).get('count', 0)} connection-string entries in "
         f"{len(sq.get('connection_strings', {}).get('files', []))} files; providers {sq.get('connection_strings', {}).get('providers')}"],
    ]
    L += md_table(["Work item", "Quantity in this repository"], rows) + [""]
    L += ["### Stored procedures called", ""]
    rows = [[p["name"], p["call_sites"], ", ".join(p["apis"]), len(p["params"]), p["output_params"], "yes" if p["for_xml"] else "",
             p["multi_result"] or "", len(p["columns_read"])] for p in f["sql"]["procedures"]]
    L += md_table(["Procedure", "Call sites", "Called through", "Parameters", "OUTPUT params", "FOR XML", "Extra result sets", "Columns read by name"], rows) + [""]
    L += ["### Raw SQL statements", ""]
    rows = [[f"{s['file']}:{s['line']}", s["source"], s["dialect"], " ".join((s["text"] or "").split())[:160],
             ", ".join(f"{k} x{v}" for k, v in (s["constructs"] or {}).items()), (s["conversion"] or {})] for s in f["sql"]["statements"]]
    L += (md_table(["Where", "How built", "Dialect", "SQL ({?} = run-time value)", "Constructs", "Conversion"], rows) if rows else ["- none"]) + [""]
    if f.get("atf_rasql"):
        at = f["atf_rasql"]
        L += ["### Cross-check with the AWS Transform scanner (RaSQL)", "",
              f"- RaSQL rows: {at['atf_rows']} ({at['atf_other_counts']}).",
              f"- Inline SQL: RaSQL {at['inline_sql']['atf']}, matched {at['inline_sql']['matched']}; RaSQL-only rows explained as {at['inline_sql']['atf_only_by_reason']}.",
              f"- Execute calls: RaSQL {at['execute_calls']['atf']}, matched {at['execute_calls']['matched']}; RaSQL-only rows explained as {at['execute_calls']['atf_only_by_reason']}.",
              f"- Found by our scan and not by RaSQL: {len(at['ours_only']['statements'])} statements, "
              f"{len(at['ours_only']['procedure_call_sites'])} procedure call sites "
              + ", ".join(f"{p['file']}:{p['line']} {p['name']}" for p in at["ours_only"]["procedure_call_sites"][:6]) + ".", ""]

    # 4. other data stores and network
    L += ["## 4. Other data stores, caches and network", ""]
    rows = [[n["host"], n["port"], n["scheme"], n["role"], n["kind"], ", ".join(n["keys"] or [])[:60], ", ".join(n["files"] or [])] for n in f["network"]]
    L += (md_table(["Host", "Port", "Scheme", "Role", "Kind", "Settings", "Files"], rows) if rows else ["- none"]) + [""]
    L += ["## 5. Every finding", ""]
    sev = Counter(x["severity"] for x in fnd)
    L.append("By severity: " + ", ".join(f"{s} {sev.get(s, 0)}" for s in SEV) + ".")
    L.append("")
    L += md_table(["Severity", "Rule", "Finding", "Project", "Occurrences", "Files"],
                  [[x["severity"], x["rule"], x["title"], x["project"] or "", x["occurrences"], x["files"]] for x in fnd])
    return "\n".join(L) + "\n"


def md_table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in r) + " |")
    return out


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    root, cfg = load_config()
    st = load_state(root)
    repos = [a.repo] if a.repo else sorted(r for r, v in st["repos"].items() if v.get("scope") != "out"
                                           and os.path.exists(os.path.join(OUT, "scan", r + ".json")))
    if not repos:
        raise SystemExit("no scanned repositories: run scan_repo.py first")
    for r in repos:
        f = collect(r, cfg)
        write_pair(os.path.join(OUT, "effort", r, "effort-inputs.md"), render_md(f))
        print(f"{r}: facts, effort inputs and AWS managed-service options -> {OUT}/effort/{r}/")


if __name__ == "__main__":
    main()
