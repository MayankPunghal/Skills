"""Derived views shared by the Markdown and HTML reports (deterministic): Linux readiness per application,
package groups, third-party services and integrations, and the layered architecture map."""
import os
import re
from collections import defaultdict

from _common import OUT, data, read_json
import _findings as F

WINDOWS_AUTH_RULES = {"AUTH-WINDOWS", "AUTH-IMPERSONATION", "DATA-INTEGRATED-SECURITY", "WIN-DIRSERVICES", "AUTH-DEFAULT-CREDENTIALS"}
REDESIGN_RULES = {"WIN-COM-INTEROP", "WIN-PINVOKE-WIN32", "INT-OFFICE-INTEROP", "INT-CRYSTAL", "INT-FAX", "API-ENTERPRISESERVICES", "API-WORKFLOW",
                  "API-REMOTING", "WIN-MSMQ", "WCF-BINDING", "WEB-WEBFORMS-UI", "DESK-WINFORMS", "DESK-WPF"}
PACKAGE_GROUPS = [  # (group, description) in display order
    ("Incompatible", "No path to .NET 10 / Linux: replace the package or keep the app on Windows"),
    ("Deprecated / end of life", "Marked deprecated on nuget.org or retired by the vendor: move to the named successor"),
    ("Framework-specific", ".NET Framework / System.Web flavour: replaced by the ASP.NET Core equivalent during the port"),
    ("Upgrade needed", "Works on .NET 10 in a newer version: the version in use is old or marked legacy"),
    ("Licence review", "Commercial or changed licence: confirm cost and terms for the new platform"),
    ("Private / unknown", "Not on nuget.org: needs source code or a private feed (CodeArtifact)"),
    ("Not verified (offline)", "Not in the package map and nuget.org was not queried: rerun the scan with --online (sends public package IDs only)"),
    ("Compatible", "Runs on .NET 10 and Linux (upgrade to a current version during the port)"),
    ("Not needed on .NET 10", "Polyfills and build helpers the platform provides"),
]
BUILD_LABEL = {"not-buildable": "legacy project: convert to SDK-style first", "framework-only": ".NET Framework target: cannot run on Linux",
               "windows-target": "Windows-only target", "planned": "planned (not run)", "built": "builds on Linux", "failed": "fails on Linux", "not run": "not run"}
DEPRECATED_TXT = re.compile(r"(?i)deprecat|retired|end of life|\bEOL\b|unmaintained|abandoned|no longer developed")


def segment_of(cats):
    return {c["id"]: c.get("segment", "") for c in cats}


def package_group(p):
    st = p.get("status")
    n = p.get("nuget") or {}
    if st in ("blocker", "windows-only"):
        return "Incompatible"
    if n.get("deprecated") or (st in ("replace", "upgrade") and DEPRECATED_TXT.search(p.get("note") or "")):
        return "Deprecated / end of life"
    if st == "unknown" and not n:
        return "Not verified (offline)"
    return {"replace": "Framework-specific", "upgrade": "Upgrade needed", "licence": "Licence review", "private": "Private / unknown",
            "unknown": "Private / unknown", "ok": "Compatible", "remove": "Not needed on .NET 10"}.get(st, "Compatible")


SOURCE_LABEL = {"url": "URL", "config-host": "host setting", "connection-string": "connection string", "wcf-client": "WCF client endpoint",
                "unc-path": "UNC path", "session-state": "session state setting"}
ROLE_NEEDS = {
    "Mail server (SMTP)": "SMTP egress on the port (AWS blocks port 25 by default: use 587 / Amazon SES, or request removal); relay allow-lists the new source IPs",
    "File transfer (SFTP / FTP)": "Egress to the partner's SFTP / FTP port; the partner allow-lists the NAT Elastic IPs; keys / known_hosts move to Secrets Manager (or AWS Transfer Family)",
    "Report server (SSRS / reporting)": "Report server stays reachable (VPN) or moves (SSRS on EC2 / RDS for SQL Server with SSRS, or replace the reports)",
    "Session state server (ASP.NET)": "ASP.NET State Service is Windows-only: move session state to ElastiCache (Redis) or a database",
    "Directory (LDAP / Active Directory)": "LDAP to the domain controllers over VPN, or AWS Managed Microsoft AD / AD Connector",
    "Identity provider": "HTTPS egress to the identity provider; register the new redirect URIs for the AWS host names",
}
NEEDS = {"internal": "Route from the AWS VPC to the client network (Site-to-Site VPN / Direct Connect), DNS for the name "
                     "(Route 53 Resolver outbound rule), security-group egress to the port; or the system moves to AWS too",
         "external": "Egress through a NAT gateway to the port; give the provider the NAT Elastic IPs if it allow-lists callers",
         "external-ip": "As external, and replace the literal IP with a DNS name in configuration"}


def network(c):
    """Network allow-list: outbound destinations (with ports) and inbound listeners from scan facts["network"]."""
    apps = c.cls["applications"]
    out, inb, clients, runtime, missing, drives = [], [], [], 0, [], []
    for r in c.repos:
        net = c.scan[r].get("network")
        inv = c.inv[r]
        if net is None:
            missing.append(r)
            continue
        for g in net["outbound"]:
            used = apps_for_files(g["files"], inv, apps) if inv else []
            needs = NEEDS.get(g["kind"], "")
            if g["scheme"] in ("sqlserver", "postgresql", "mysql"):
                needs = "Database: security-group rule to the database port (RDS in the VPC, or on-premises over VPN / Direct Connect)"
            elif g["scheme"] == "smb":
                needs = "SMB 445 to a file share: keep it on-premises over VPN / Direct Connect, or move it (Amazon FSx for Windows File Server / S3)"
            if g.get("role") in ROLE_NEEDS:  # role-specific need; an on-premises host still needs the route and DNS
                needs = ROLE_NEEDS[g["role"]] + ("; on-premises host: Site-to-Site VPN / Direct Connect route and Route 53 Resolver DNS"
                                                 if g["kind"] == "internal" and g["role"] != "Session state server (ASP.NET)" else "")  # state moves to AWS
            out.append({"role": g.get("role") or "-", "host": g["host"], "port": (f"{g['port']} (default)" if g.get("port_default") else str(g["port"])) if g["port"] else "?",
                        "protocol": g["scheme"], "kind": g["kind"], "applications": ", ".join(used) or ", ".join(p.split("/")[-1] for p in g["projects"][:3]) or "-",
                        "defined": ", ".join([f"`{k}`" for k in g["keys"][:4]] + (["…"] if len(g["keys"]) > 4 else [])
                                             + [SOURCE_LABEL.get(s, s) for s in g["sources"] if s != "url" or not g["keys"]]),
                        "evidence": "; ".join(g["evidence"][:2]) + (f" +{len(g['evidence']) - 2}" if len(g["evidence"]) > 2 else ""),
                        "needs": needs, "repo": r})
        for e in net["inbound"]:
            used = apps_for_files([e["file"]], inv, apps) if inv else []
            inb.append({"application": ", ".join(used) or e.get("app") or e["project"].split("/")[-1], "port": e["port"] or "?", "protocol": e["scheme"],
                        "source": e["source"], "evidence": f"{e['file']}:{e['line']}", "repo": r})
        for cl in net["clients"]:
            if not cl["keys"] and not cl["literals"]:
                runtime += 1
            clients.append(cl)
        for dv in net.get("drives", []):
            drives.append(dict(dv, repo=r))
    return {"outbound": out, "inbound": inb, "clients": clients, "runtime_clients": runtime, "missing": missing, "drives": drives}


JOB_AWS = {
    "Windows Task Scheduler": "EventBridge Scheduler triggering an ECS task (or Lambda); the command must run on Linux, or the task stays on a Windows EC2 host",
    "SQL Server Agent": "Kept on RDS for SQL Server (Agent supported) while SQL Server stays; on PostgreSQL use pg_cron (RDS / Aurora) or EventBridge Scheduler + a task",
    "Windows service": "Worker Service in a Linux container (ECS service), or kept on a Windows EC2 host",
    "Hangfire": "Runs inside the application container; job storage must follow the database (Hangfire.PostgreSql for PostgreSQL); safe with several instances",
    "Quartz.NET": "Runs inside the application container; use a clustered ADO.NET job store when more than one instance runs",
    "Hosted / background service": "Runs in every container instance: confirm that is safe with several instances, or give it its own ECS service with one task",
    "Console job (trigger outside the repository)": "Ask the client who runs it and when; then EventBridge Scheduler + ECS RunTask",
    "Azure Functions timer": "EventBridge Scheduler + Lambda",
    "Kubernetes CronJob": "EKS CronJob as is, or EventBridge Scheduler + ECS task",
    "CI pipeline schedule": "Stays with the CI/CD platform",
    "Schedule setting": "Carry the value to Parameter Store / the application configuration",
    "AWS EventBridge schedule": "Already an AWS schedule",
}


def jobs(c):
    """Scheduled and background jobs from scan facts["scheduled_jobs"], with the applications and the AWS target."""
    apps = c.cls["applications"]
    rows, missing = [], []
    for r in c.repos:
        js = c.scan[r].get("scheduled_jobs")
        if js is None:
            missing.append(r)
            continue
        inv = c.inv[r]
        for j in js:
            used = apps_for_files([j["file"]], inv, apps) if inv else []
            app = ", ".join(used) or os.path.splitext(j["project"].split("/")[-1])[0]
            if j["scheduler"] == "SQL Server Agent":
                app = "database server (msdb)"
            rows.append(dict(j, repo=r, application=app,
                             aws=JOB_AWS.get(j["scheduler"], "EventBridge Scheduler + ECS task")))
    return {"jobs": rows, "missing": missing}


def apps_for_files(files, inv, apps):
    pidx = F.project_index(inv)
    hit = set()
    for f in files:
        p = F.project_of_file(pidx, f)
        for a in apps:
            if a["repo"] == inv["repo"] and p in a["projects"]:
                hit.add(a["name"])
    return sorted(hit)


def linux_readiness(c):
    """One row per application: what stops it running on Linux, and a plain-language verdict."""
    seg = segment_of(c.cats)
    rows = []
    for a in c.cls["applications"]:
        fs = [f for f in c.findings if a["id"] in f.get("apps", [])]
        rid = lambda f: f["rule"].split(":")[0]
        win_api = [f for f in fs if f["category"] == "linux-readiness"]
        files = [f for f in fs if f["category"] == "file-handling"]
        tz = [f for f in fs if f["category"] == "time-culture"]
        auth = [f for f in fs if rid(f) in WINDOWS_AUTH_RULES]
        fw = [f for f in fs if seg.get(f["category"]) == "modernization" and f["severity"] in ("Blocker", "High")]
        pk = [f for f in fs if f["rule"].startswith("PKG-") and f.get("severity") in ("Blocker", "High")
              and any(s in f["rule"].upper() for s in ("BLOCKER", "WINDOWS"))]
        pk += [f for f in fs if f["category"] == "packages" and re.search(r"\((blocker|windows-only)\)", f["title"])]
        pk = list({f["id"]: f for f in pk}.values())
        redesign = sorted({f["title"] for f in fs if rid(f) in REDESIGN_RULES and f["severity"] in ("Blocker", "High")})
        lb = read_json(os.path.join(OUT, "scan", f"{a['repo']}.linux-build.json"))
        build = BUILD_LABEL.get(next((p["status"] for p in (lb or {}).get("projects", []) if p["project"] == a["entry"]), "not run"), "not run")
        fam = a.get("framework_family", "")
        modern = "netcore" in fam and not any(t.endswith("-windows") for t in a.get("target_frameworks", []))
        hi = lambda xs: sum(1 for f in xs if f["severity"] in ("Blocker", "High"))
        if a["r7"] == "Retire":
            status, level = "Retiring — not assessed for Linux", "na"
        elif a["type"] in ("winforms", "wpf"):
            status, level = "Windows-only (desktop client)", "windows"
        elif redesign and a["r7"] in ("Replatform", "Refactor"):
            status, level = "Ready after porting + replacing Windows-only parts", "port"
        elif redesign:
            status, level = "Blocked — stays on Windows until redesigned", "blocked"
        elif modern and not (hi(win_api) or hi(files) or fw or pk or auth):
            status, level = "Linux-ready", "ready"
        else:
            status, level = "Ready after porting to .NET 10", "port"
        issues = []
        if level == "port" and not modern:
            issues.append(f"port from {', '.join(a.get('target_frameworks', [])) or '.NET Framework'} to .NET 10")
        if redesign:
            issues.append("replace/redesign: " + ", ".join(redesign[:4]))
        if win_api:
            issues.append(f"{len(win_api)} Windows-only API finding(s)")
        if pk:
            issues.append(f"{len(pk)} incompatible package(s)")
        if auth:
            issues.append("Windows authentication / AD")
        if files:
            issues.append(f"{sum(f.get('occurrences', 1) for f in files)} path/file-system issue(s)")
        if tz:
            issues.append("time zone / culture")
        if a["r7"] in ("Retain", "Rehost") and level not in ("windows", "na"):
            issues.append(f"decision: {a['r7']} on Windows")
        rows.append({"app": a["name"], "id": a["id"], "repo": a["repo"], "type": a["type"], "framework": ", ".join(a.get("target_frameworks", [])) or fam,
                     "r7": a["r7"], "status": status, "level": level, "windows_apis": len(win_api), "framework_blockers": len(fw), "packages": len(pk),
                     "paths": sum(f.get("occurrences", 1) for f in files), "time_culture": len(tz), "windows_auth": len(auth), "linux_build": build,
                     "summary": "; ".join(issues) or "no Linux blockers found"})
    return rows


def linux_issue_types(c):
    """Aggregate Linux-relevant findings by issue type (rule): what breaks, where, how often, how to fix."""
    seg = segment_of(c.cats)
    by = defaultdict(lambda: {"apps": set(), "count": 0, "refs": [], "sev": "Info"})
    order = {"Blocker": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
    names = {a["id"]: a["name"] for a in c.cls["applications"]}
    for f in c.findings:
        if seg.get(f["category"]) != "linux" and f["rule"].split(":")[0] not in WINDOWS_AUTH_RULES | REDESIGN_RULES:
            continue
        k = f["title"] if not f["rule"].startswith(("NET-", "PKG-")) else f["rule"].split(":")[0]
        b = by[k]
        b["title"] = f["title"]
        b["apps"] |= {names.get(x, x) for x in f.get("apps", [])}
        b["count"] += f.get("occurrences", 1)
        b["refs"].append(f["ref"])
        b["fix"] = f.get("fix", "")
        b["why"] = f.get("why", "")
        if order.get(f["severity"], 9) < order.get(b["sev"], 9):
            b["sev"] = f["severity"]
    return sorted(({"issue": v["title"], "severity": v["sev"], "apps": ", ".join(sorted(v["apps"])) or "(repository-wide)", "occurrences": v["count"],
                    "refs": ", ".join(v["refs"][:8]), "why": v["why"], "fix": v["fix"]} for v in by.values()), key=lambda r: (order.get(r["severity"], 9), -r["occurrences"]))


def third_party(c):
    """External services (endpoints + service SDK packages), on-premises dependencies, identity providers."""
    sdks = data("service_sdks.json")["sdks"]
    for s in sdks:
        s["_rx"] = re.compile(rf"(?i)^(?:{s['match']})$")
    apps = c.cls["applications"]
    ext, onprem, sdk_rows = [], [], []
    for r in c.repos:
        inv = c.inv[r]
        if not inv:
            continue
        for e in c.scan[r].get("endpoints", []):
            used = apps_for_files(e["files"], inv, apps)
            row = {"system": e["host"], "protocols": ", ".join(e["schemes"]), "used_by": ", ".join(used) or "(shared/config)", "references": e["occurrences"],
                   "evidence": "; ".join(F.evidence_ref(x) for x in e["evidence"][:3]), "repo": r}
            if e["kind"] == "internal":
                row["needs"] = "Network path from AWS (Site-to-Site VPN / Direct Connect + DNS), or the system moves too"
                onprem.append(row)
            else:
                row["needs"] = "Outbound HTTPS from AWS; check IP allow-listing (new egress IPs), credentials and TLS" if e["kind"] == "external" else "Hard-coded public IP: move to DNS/config; partner allow-list"
                ext.append(row)
        for cs in c.scan[r].get("connection_strings", []):
            if cs.get("host") and not cs.get("localdb") and cs["host"] not in (".", "(local)", "localhost"):
                onprem.append({"system": f"{cs['host']} / {cs.get('database') or '-'}", "protocols": "sql", "used_by": ", ".join(apps_for_files([cs["file"]], inv, apps)) or "-",
                               "references": 1, "evidence": f"{cs['file']}:{cs['line']}", "repo": r, "needs": "Database server: convert for PostgreSQL (dual or PostgreSQL-only) or keep reachable"})
        for p in c.scan[r].get("packages", []):
            m = next((s for s in sdks if s["_rx"].match(p["id"])), None)
            if not m:
                continue
            g = s_m = m["_rx"].match(p["id"])
            svc = m["service"].replace("{1}", (g.group(1) if g and g.groups() else "") or "")
            sdk_rows.append({"service": svc, "package": p["id"], "versions": ", ".join(p["versions"]), "status": package_group(p),
                             "projects": len(p["projects"]), "aws": m["aws"], "repo": r})
            _ = s_m
    idp = [f for f in c.findings if f["rule"].split(":")[0] in ("AUTH-EXTERNAL-IDP", "AUTH-WSFED", "AUTH-WINDOWS", "WIN-DIRSERVICES")]
    other = [f for f in c.findings if f["rule"].split(":")[0] in ("NET-SMTP", "NET-FTP", "WCF-CLIENT", "WEB-ASMX", "INT-SSRS-CLIENT", "INT-SHAREPOINT-EXCHANGE", "NET-UNC-SHARE", "DB-DATABASE-MAIL")
             or f["rule"].startswith("MAN-")]
    return {"external": sorted(ext, key=lambda x: -x["references"]), "onprem": sorted(onprem, key=lambda x: -x["references"]),
            "sdks": sorted(sdk_rows, key=lambda x: x["service"]), "identity": idp, "other": other}


def architecture_map(c, max_external=18):
    """Layered map: clients -> applications -> shared libraries -> data -> external systems (nodes + edges)."""
    nodes, edges = [], []
    apps = c.cls["applications"]
    tp = third_party(c)
    for a in apps:
        col = "clients" if a["type"] in ("winforms", "wpf") else "apps"
        nodes.append({"id": a["id"], "label": a["name"], "sub": f"{a['type']} · {a['r7']}", "col": col, "r7": a["r7"]})
    if any(a["type"].startswith("aspnet") or a["type"] in ("website",) for a in apps):
        nodes.append({"id": "users", "label": "Users (browser)", "sub": "", "col": "clients", "r7": ""})
        for a in apps:
            if a["type"].startswith("aspnet") or a["type"] == "website":
                edges.append(["users", a["id"], "uses"])
    for r in c.repos:
        inv = c.inv[r]
        if not inv:
            continue
        for s in inv.get("shared_libraries", []):
            sid = "lib:" + s["path"]
            nodes.append({"id": sid, "label": s["name"], "sub": "shared library · " + ", ".join(s["target_frameworks"]), "col": "libs", "r7": ""})
            for a in apps:
                if a["repo"] == r and s["path"] in a["projects"][1:]:
                    edges.append([a["id"], sid, "references"])
        pidx = F.project_index(inv)
        seen_db = set()
        for cs in c.scan[r].get("connection_strings", []):
            if not cs.get("database"):
                continue
            did = "db:" + (cs.get("database") or "").lower()
            if did not in seen_db:
                seen_db.add(did)
                nodes.append({"id": did, "label": cs.get("database"), "sub": ("SQL Server · " + (cs.get("host") or "")) if not cs.get("localdb") else "SQL Server (dev: LocalDB)", "col": "data", "r7": ""})
            p = F.project_of_file(pidx, cs["file"])
            for a in apps:
                if a["repo"] == r and p in a["projects"]:
                    edges.append([a["id"], did, "reads/writes"])
        for p in inv["projects"]:
            if p["type"] == "database":
                did = "db:" + p["name"].lower()
                if did not in seen_db:
                    seen_db.add(did)
                    nodes.append({"id": did, "label": p["name"], "sub": "SQL Server database project", "col": "data", "r7": ""})
    ext = [("onprem", x) for x in tp["onprem"] if x["protocols"] != "sql"] + [("external", x) for x in tp["external"]]
    for kind, x in ext[:max_external]:
        eid = "ext:" + x["system"]
        nodes.append({"id": eid, "label": x["system"], "sub": "on-premises / internal" if kind == "onprem" else "third-party / external", "col": "external", "r7": kind})
        for n in apps:
            if n["name"] in x["used_by"].split(", "):
                edges.append([n["id"], eid, "calls"])
    if len(ext) > max_external:
        nodes.append({"id": "ext:more", "label": f"+{len(ext) - max_external} more systems", "sub": "see Third-party & integrations", "col": "external", "r7": "more"})
    for f in c.findings:  # desktop -> service links recorded by reviewers (manual findings) or WCF clients in desktop apps
        if f["rule"].startswith("MAN-") or f["rule"].startswith("WCF-CLIENT"):
            src = [a for a in apps if a["id"] in f.get("apps", []) and a["type"] in ("winforms", "wpf")]
            svc = [a for a in apps if a["type"] == "wcf-service" and a["repo"] == f["repo"] and a["r7"] != "Retire"]
            for s1 in src:
                for s2 in svc[:1]:
                    edges.append([s1["id"], s2["id"], "SOAP"])
    uniq = {tuple(e) for e in edges}
    return {"nodes": nodes, "edges": [list(e) for e in sorted(uniq)]}
