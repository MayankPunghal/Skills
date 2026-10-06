"""Assemble the client report and machine-readable exports from the assessment data (deterministic).

    python <skill>/scripts/build_report.py [--template PATH] [--out NAME]

Template: references/report-template.md (single place for section order, headings and wording; calibrate it from
your own sample reports). Placeholders:
  {{meta:<key>}}        values from assessment.json / computed metadata (client, prepared_by, date, version …)
  {{block:<name>}}      generated tables/diagrams (see BLOCKS below)
  {{narrative:<name>}}  text written by the assessor in assessment/narrative/<name>.md (HTML comments stripped)
Outputs (assessment/report/):
  <Client>-AWS-Migration-Assessment.md, findings.csv, findings.json, applications.csv, packages.csv, open-questions.csv, endpoints.csv
"""
import argparse
import csv
import datetime
import json
import os
import re
import shutil
from collections import Counter, defaultdict

from _common import OUT, SKILL_DIR, data, load_config, mark_step, read_json, slug, utf8_stdout, write_text
import _findings as F
import _dependencies as D
import _analysis as A

SEVS = ["Blocker", "High", "Medium", "Low", "Info"]


def md_escape(s):
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def table(cols, rows):
    if not rows:
        return "_None._"
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    out += ["| " + " | ".join(md_escape(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def hd(days, hours=None):
    """'40–96 h (5–12 d)' from a [low, high] days range (hours derived when not given)."""
    if not days:
        return "-"
    hours = hours or [round(days[0] * 8), round(days[1] * 8)]
    return f"{round(hours[0])}–{round(hours[1])} h ({days[0]:g}–{days[1]:g} d)"


def rng(r, unit=""):
    return f"{round(r[0])}–{round(r[1])}{unit}"


class Ctx:
    def __init__(self, root, cfg):
        self.root, self.cfg = root, cfg
        self.repos = F.repos(root)
        self.inv = {r: F.load_inventory(root, r) for r in self.repos}
        self.scan = {r: read_json(os.path.join(OUT, "scan", f"{r}.json"), {}) or {} for r in self.repos}
        self.graph = {r: read_json(os.path.join(OUT, "graphs", r, "analysis.json"), None) for r in self.repos}
        self.findings = []
        for r in self.repos:
            if self.inv[r]:
                self.findings += F.assign_apps(F.load(root, r), self.inv[r])
        self.findings.sort(key=F.sort_key)
        self.cls = read_json(os.path.join(OUT, "classification.json"), {"applications": [], "hybrid": []})
        self.est = read_json(os.path.join(OUT, "estimate.json"), {"work_packages": [], "databases": [], "totals": {}, "timeline": [], "assumptions": []})
        self.cats = data("categories.json")["categories"]
        self.apps = {a["id"]: a for a in self.cls["applications"]}
        self.wp = {w["id"]: w for w in self.est.get("work_packages", [])}
        for i, f in enumerate(self.findings, 1):
            f["ref"] = f"F-{i:03d}"
        VALUES.clear()  # {{v:path}} tags: numbers in narratives come from the data, so a rescan cannot leave them stale
        VALUES.update({"estimate": self.est, "classification": self.cls, "inventory": self.inv, "scan": self.scan,
                       "findings": {"total": len(self.findings), **{s.lower(): n for s, n in Counter(f["severity"] for f in self.findings).items()}}})
        FINDING_REFS.clear()  # rule -> findings, for {{f:RULE}} tags in narratives (F-numbers change whenever findings change)
        for f in self.findings:
            FINDING_REFS.setdefault(f["rule"].lower(), []).append(f)


# ------------------------------------------------------------------ blocks
def b_headline(c):
    t = c.est.get("totals", {})
    sev = Counter(f["severity"] for f in c.findings)
    r7 = Counter(a["r7"] for a in c.cls["applications"])
    loc = sum((c.inv[r] or {}).get("totals", {}).get("loc", 0) for r in c.repos)
    rows = [("Repositories / solutions / projects", f"{len(c.repos)} / {sum(len(c.inv[r]['solutions']) for r in c.repos if c.inv[r])} / {sum(len(c.inv[r]['projects']) for r in c.repos if c.inv[r])}"),
            ("Applications assessed", str(len(c.cls["applications"]))),
            ("Lines of code (C#, VB.NET, markup)", f"{loc:,}"),
            ("Recommended path (7R)", ", ".join(f"{k} {v}" for k, v in r7.most_common()) or "-"),
            ("Findings", ", ".join(f"{k} {sev[k]}" for k in SEVS if sev[k]) or "none"),
            ("Effort" + (" (AI-assisted delivery)" if c.est.get("ai_assisted") else ""),
             f"likely (P50) {t.get('likely_hours', '-')} h / {t['likely_days']} d; 80% range (P10–P90) {hd(t['total_days'], t.get('total_hours'))}"
             + (f"; commitment (P80) {t['p80_hours']} h" if t.get("p80_hours") else "") if t.get("total_days") else "not estimated"),
            ("Manual-equivalent effort (for comparison)", hd(t["manual_equivalent_days"], t.get("manual_equivalent_hours")) if t.get("manual_equivalent_days") else "-"),
            ("Indicative duration", f"~{t.get('duration_weeks')} weeks at P50" + (f", ~{t['duration_weeks_p80']} weeks at P80" if t.get("duration_weeks_p80") else "")
             + f" with {c.est.get('engineers')} engineers" + sprint_note(c.est.get("sprints") or {}) if t.get("duration_weeks") else "-"),
            ("Target platform", f"{pretty_tfm(c.cfg.get('target_dotnet', 'net10.0'))} (LTS, supported to 2028-11-14) on Linux, AWS")]
    return table(["Measure", "Value"], rows)


def b_key_risks(c):
    top = [f for f in c.findings if f["severity"] in ("Blocker", "High")][:8]
    return table(["Ref", "Severity", "Finding", "Where"], [(f["ref"], f["severity"], f["title"], ", ".join(c.apps[a]["name"] for a in f.get("apps", []) if a in c.apps) or f["repo"]) for f in top])


def b_scope(c):
    rows = []
    for r in c.repos:
        inv, s = c.inv[r], c.scan[r]
        if not inv:
            continue
        g = inv.get("git", {})
        rows.append((r, inv["root"], f"{inv['totals']['files']:,}", f"{sum(s.get('files_scanned', {}).values()):,}", f"{s.get('lines_scanned', 0):,}",
                     f"{g.get('branch', '-')} @ {g.get('last_commit', '-')}" + (" (shallow clone)" if g.get("shallow") else ""),
                     "yes" if c.graph.get(r) else "no"))
    return table(["Repository", "Path", "Files", "Files scanned", "Lines scanned", "Branch / last commit", "Code graph"], rows)


def b_method(c):
    rules = data("rules.json")["rules"]
    online = any(c.scan[r].get("online_package_lookup") for r in c.repos)
    rows = [("Inventory", "Solution/project parsing (SDK-style and legacy), target frameworks, project types, packages, lines of code, git history"),
            ("Code graph", "graphify AST graph per repository: communities, hub classes, observed project dependencies, per-file blast radius"),
            ("Static checks", f"{len(rules)} evidence rules across {len({r['cat'] for r in rules})} categories (C#, VB.NET, Razor/Web Forms markup, config, T-SQL, project files, scripts, CI)"),
            ("Configuration", "web.config / app.config / appsettings parsing: connection strings (servers, databases, auth mode), secret-like settings (names only)"),
            ("Packages", "NuGet package map (Windows-only, replace, licence, vulnerable)" + (" + api.nuget.org metadata (frameworks, deprecation, advisories)" if online else "")),
            ("Endpoints", "URLs, host names, IPs and UNC paths classified internal (on-prem) vs external"),
            ("Linux file-system", "Path-literal case check against files on disk; drive letters; separators"),
            ("Review", "Findings marked Needs verification were read in context by the assessor; verdicts are recorded with the evidence"),
            ("Estimation", f"Parametric model {c.est.get('model_version', '')}: coding hours only: project conversion by type, size and complexity + remediation per finding + database code conversion (no QA, DevOps, PM or contingency)")]
    return table(["Step", "What was done"], rows)


def b_not_assessed(c):
    rows = [("Running infrastructure", "Servers, OS versions, IIS settings, app-pool identities, scheduled tasks, certificates and firewall rules are not in the repositories; listed as open questions."),
            ("Production configuration", "Connection strings and secrets in production are configured outside the code; only repository config was read (values never copied)."),
            ("Runtime behaviour", "No application was executed against production data; performance and load characteristics are not assessed."),
            ("Data volumes", "Database sizes and growth are needed for migration timing (DMS / native backup-restore) and are not in the code.")]
    for r in c.repos:
        s = c.scan[r]
        if s.get("skipped_large"):
            rows.append((f"{r}: large files", f"{len(s['skipped_large'])} files above the scan size limit were not scanned (e.g. {s['skipped_large'][0]})."))
        if (c.inv[r] or {}).get("git", {}).get("shallow"):
            rows.append((f"{r}: git history", "Shallow clone: commit activity is partial."))
        if not c.graph.get(r):
            rows.append((f"{r}: code graph", "Graph not built; architecture facts come from project references only."))
    return table(["Area", "Why it could not be assessed from code"], rows)


def b_inventory(c):
    rows = []
    for a in c.cls["applications"]:
        w = c.wp.get(a["id"], {})
        deps = len(a["projects"]) - 1
        rows.append((a["name"], a["repo"], a["type"], ", ".join(a.get("target_frameworks", [])) or a.get("framework_family"), f"{a['loc']:,}", deps,
                     a["r7"], a["target"].split(" - ")[0], f"{hd(w['total_days'], w.get('total_hours'))} [{w.get('complexity')}]" if w else "-", a["risk"]))
    return table(["Application", "Repository", "Type", "Framework", "LOC", "Project deps", "7R", "Target", "Effort", "Risk"], rows)


def b_linux_readiness(c):
    rows = [(r["app"], r["framework"], r["status"], r["windows_apis"], r["framework_blockers"], r["packages"], r["paths"], r["time_culture"], r["windows_auth"], r["linux_build"], r["summary"])
            for r in A.linux_readiness(c)]
    legend = ("\n\n**Linux-ready**: already cross-platform, no blockers. **Ready after porting**: moves to .NET 10 on Linux with code changes listed in the findings. "
              "**Blocked**: Windows-bound and kept on Windows by decision until redesigned (apps being ported replace their Windows-only parts and show as Ready after porting). **Windows-only (desktop)**: client app, runs on user machines.")
    return table(["Application", "Framework", "Linux readiness", "Windows APIs", "Framework blockers", "Incompatible packages", "Path issues", "Time/culture", "Windows auth", "Linux build", "What stops it"], rows) + legend


def b_linux_issues(c):
    rows = [(r["severity"], r["issue"], r["apps"], r["occurrences"], r["refs"], F.short(r["fix"], 200)) for r in A.linux_issue_types(c)]
    return table(["Severity", "What breaks on Linux", "Applications", "Occurrences", "Findings", "Fix"], rows)


def b_package_groups(c):
    out = []
    allp = [dict(p, repo=r) for r in c.repos for p in c.scan[r].get("packages", [])]
    for g, desc in A.PACKAGE_GROUPS:
        ps = [p for p in allp if A.package_group(p) == g]
        out.append(f"**{g}** ({len(ps)}): {desc}.\n")
        if ps and g not in ("Compatible", "Not needed on .NET 10"):
            out.append(table(["Package", "Version(s)", "Latest", "Advisories", "Note", "Replacement"],
                             [(p["id"], ", ".join(p["versions"]), p.get("latest", "") or "", p.get("vulnerable", "") or "", F.short(p.get("note"), 140), F.short(p.get("replacement"), 100)) for p in ps]) + "\n")
        elif ps:
            out.append(", ".join(sorted(p["id"] for p in ps)) + "\n")
    vul = [p for p in allp if p.get("vulnerable")]
    out.append(f"**Packages with published security advisories** ({len(vul)}): " + ("; ".join(f"{p['id']} {', '.join(p['versions'])} ({p['vulnerable']})" for p in vul) or "none") + "\n")
    return "\n".join(out)


def b_third_party(c):
    tp = A.third_party(c)
    out = ["**Third-party / external services called from the code**\n",
           table(["System", "Protocol", "Used by", "References", "Evidence", "Needed on AWS"], [(x["system"], x["protocols"], x["used_by"], x["references"], x["evidence"], x["needs"]) for x in tp["external"]]),
           "\n**On-premises / internal systems** (need a network path from AWS or must move too)\n",
           table(["System", "Protocol", "Used by", "References", "Evidence", "Needed on AWS"], [(x["system"], x["protocols"], x["used_by"], x["references"], x["evidence"], x["needs"]) for x in tp["onprem"]]),
           "\n**Service SDKs in use**\n",
           table(["Service", "Package", "Version(s)", "Package status", "Projects", "On AWS"], [(x["service"], x["package"], x["versions"], x["status"], x["projects"], x["aws"]) for x in tp["sdks"]])]
    return "\n".join(out)


def b_projects(c):
    rows = []
    for r in c.repos:
        for p in (c.inv[r] or {}).get("projects", []):
            sup = "; ".join(f"{t['label']} ({t['status']})" for t in p.get("tfm_support", []))
            rows.append((r, p["path"], p["type"], ", ".join(p.get("target_frameworks", [])), "SDK" if p.get("sdk_style") else "legacy",
                         "packages.config" if p.get("packages_config") else "PackageReference", ", ".join(p.get("languages", [])), f"{p.get('loc_code', 0):,}", sup))
    return table(["Repository", "Project", "Type", "TFM", "Format", "Packages", "Language", "LOC", "Support status"], rows)


def _list(x, n=6):
    return "<br>".join(x[:n]) + (f"<br>+{len(x) - n} more" if len(x) > n else "") if x else "-"


def b_project_deps(c):
    """Project interdependencies: who references whom, build / port order (leaf first) and blast radius."""
    out = []
    for r, g in D.project_graph(c).items():
        out.append(f"**{r}** — {len(g['nodes'])} projects, {len(g['edges'])} project references.\n")
        out.append("```mermaid\nflowchart LR")
        ids = {n["name"]: f"p{i}" for i, n in enumerate(g["nodes"])}
        for n in g["nodes"]:
            out.append(f'  {ids[n["name"]]}["{n["name"]}<br/><small>{n["type"]} · {n["tfm"]}</small>"]')
        for a_, b_ in g["edges"]:
            out.append(f"  {ids[a_]} --> {ids[b_]}")
        out.append("```\n")
        out.append(table(["Layer", "Project", "Type / TFM", "Depends on (direct)", "Needed by (direct)", "Change impact (all dependents)", "Applications affected"],
                         [(n["layer"], n["name"], f"{n['type']} · {n['tfm']}", _list(n["direct"]), _list(n["dependents"]), _list(n["used_by_all"]), _list(n["apps"])) for n in g["nodes"]]))
        out.append("\nLayer 0 projects reference nothing and are ported first; a project is ported after every project it references (or is multi-targeted / retained). "
                   "'Change impact' lists every project that rebuilds when the project changes, which sets the regression-test scope.")
        if g["cycles"]:
            out.append("\n**Circular references:** " + "; ".join(f"{a_} ↔ {b_}" for a_, b_ in g["cycles"]) + " (break before porting).")
        unres = [(n["name"], ", ".join(n["unresolved"])) for n in g["nodes"] if n["unresolved"]]
        if unres:
            out.append("\n**References to projects outside this repository (need their source or a package):**\n\n" + table(["Project", "References"], unres))
        out.append("")
    return "\n".join(out) or "_No projects inventoried._"


def b_workflows(c):
    """Entry point -> projects, database objects, external systems and findings it depends on."""
    wf = D.workflows(c)
    if not wf:
        return "_No entry points detected (HTTP endpoints, MVC actions, Web Forms pages, background services, console jobs)._"
    out = [f"{len(wf)} entry points traced. Reach is derived from the code graph (calls, references, inheritance, interface implementations) and string literals naming database objects; "
           "treat it as a strong lead to confirm in review, not a proof (reflection, DI by convention, dynamic SQL and EF-generated SQL are not visible).\n"]
    by_app = defaultdict(list)
    for w in wf:
        by_app[(w["repo"], w["app"])].append(w)
    for (r, app), ws in by_app.items():
        out.append(f"#### {app} ({r})\n")
        out.append(table(["Workflow", "Kind", "Entry", "Projects reached", "Database objects", "External systems", "Findings on the path"],
                         [(w["name"], w["kind"], f"`{w['entry']}`", _list(w["projects"], 5), _list(w["db_objects"], 6), _list(w["external"], 4), ", ".join(w["findings"][:8]) or "-") for w in ws]))
        out.append("")
    return "\n".join(out)


def b_db_dependents(c):
    """Database object -> other objects it calls, and the workflows that depend on it."""
    dd = D.db_dependencies(c)
    idx = D.object_dependents(c, D.workflows(c))
    out = []
    for r, g in dd.items():
        calls, called_by = defaultdict(list), defaultdict(list)
        for a_, b_ in g["edges"]:
            calls[a_].append(b_)
            called_by[b_].append(a_)
        rows = []
        for o in g["objects"]:
            wfs = sorted(set(idx.get((r, o["name"]), [])))
            if not (calls.get(o["name"]) or called_by.get(o["name"]) or wfs):
                continue
            rows.append((o["name"], o["kind"], f"`{o['file']}:{o['line']}`", _list(sorted(calls.get(o["name"], [])), 5), _list(sorted(called_by.get(o["name"], [])), 5), _list(wfs, 5)))
        unused = len(g["objects"]) - len(rows)
        out.append(f"**{r}** — {len(g['objects'])} database objects; {len(rows)} with a detected dependency, {unused} with none found (unused, or reached only through EF-generated SQL / dynamic SQL).\n")
        out.append(table(["Object", "Kind", "Defined", "Uses (objects)", "Used by (objects)", "Used by (workflows)"], rows))
        out.append("")
    return "\n".join(out) or "_No database objects inventoried._"

def b_db_coupling(c):
    """Shared database objects (map_graphs analysis.database, from the parsed SQL and the code graph): which applications read,
    write and call each one. Objects shared by several applications tie their migration together."""
    out = []
    for r in c.repos:
        g = (c.graph.get(r) or {}).get("database") or {}
        if not g:
            continue
        inv = c.inv.get(r) or {}
        pname_path = {p["name"]: p["path"] for p in inv.get("projects", [])}
        app_of = {}
        for a in c.cls["applications"]:
            if a["repo"] == r:
                for pp in a["projects"]:
                    app_of.setdefault(pp, []).append(a["name"])

        def apps(projects):
            names = sorted({x for p in projects for x in (app_of.get(pname_path.get(p, ""), []) or [p])})
            return ", ".join(names) or "-"
        out.append(f"**{r}** — {g['objects']} database objects; **{g['shared_count']} shared by more than one project**, "
                   f"{len(g.get('multi_writer', []))} written by more than one (finding DB-MULTI-WRITER), "
                   f"{g.get('unused_count', 0)} with no caller found in code or SQL.\n")
        if g.get("shared"):
            out.append(table(["Object", "Kind", "Written by", "Read by", "Executed by", "Through routines", "Code sites"],
                             [(x["name"], x["kind"], apps(x["writers"]), apps(x["readers"]), apps(x["callers"]),
                               _list(x.get("routines", []), 4), x.get("code_sites", 0)) for x in g["shared"][:40]]))
            if g["shared_count"] > 40:
                out.append(f"\n_{g['shared_count'] - 40} more in assessment/graphs/{r}/analysis.json (database.shared)._")
        if g.get("objects_per_project"):
            out.append("\nDatabase objects each project touches: " + ", ".join(f"{p} {n}" for p, n in list(g["objects_per_project"].items())[:15]) + ".\n")
        if g.get("unused_in_code"):
            out.append("No caller found (check before removing: jobs, reports, other databases or dynamic SQL may use them): "
                       + ", ".join(f"`{x}`" for x in g["unused_in_code"][:30]) + (" …" if g.get("unused_count", 0) > 30 else "") + "\n")
    return "\n".join(out) or "_No database layer in the code graph (rerun map_graphs.py with the codebase-documenter and a SQL parser installed)._"


def b_architecture_diagram(c):
    """Layered Mermaid map (same model as the HTML map): clients -> applications -> shared libraries -> data -> external systems.
    Retired applications are left out to keep the picture readable; they are listed under the diagram."""
    m = A.architecture_map(c, max_external=10)
    retired = {n["id"] for n in m["nodes"] if n.get("r7") == "Retire"}
    ids = {}

    def nid(x):
        return ids.setdefault(x, f"n{len(ids)}")

    def label(n):
        return (n["label"] + ("<br/><small>" + n["sub"] + "</small>" if n.get("sub") else "")).replace('"', "'")
    lines = ["```mermaid", "flowchart LR"]
    for col, title in (("clients", "Clients"), ("apps", "Applications"), ("libs", "Shared libraries"), ("data", "Data"), ("external", "External systems")):
        ns = [n for n in m["nodes"] if n["col"] == col and n["id"] not in retired]
        if not ns:
            continue
        lines.append(f'  subgraph {col}["{title}"]')
        lines.append("    direction TB")
        for n in ns:
            shape = ('[("' + label(n) + '")]') if col == "data" else (('{{"' + label(n) + '"}}') if col == "external" else ('["' + label(n) + '"]'))
            lines.append(f"    {nid(n['id'])}{shape}")
        lines.append("  end")
    for a_, z, k in m["edges"]:
        if a_ in retired or z in retired or a_ not in ids or z not in ids:
            continue
        lines.append(f"  {nid(a_)} --> {nid(z)}")
    lines.append("```")
    note = ""
    if retired:
        names = sorted(n["label"] for n in m["nodes"] if n["id"] in retired)
        note = "\n\nNot shown (to be retired): " + ", ".join(names) + "."
    return "\n".join(lines) + note


def b_graph_insights(c):
    out = []
    for r in c.repos:
        g = c.graph.get(r)
        if not g:
            continue
        out.append(f"**{r}** — {g['nodes']:,} code elements, {g['edges']:,} relationships, {g['community_count']} clusters (graphify).\n")
        out.append(table(["Hub (most connected)", "Connections", "Defined in"], [(x["label"], x["degree"], f"{x['file']}:{str(x.get('line') or '').lstrip('L')}") for x in g["god_nodes"][:8]]))
        if g.get("project_edges"):
            out.append("\nCode-level dependencies observed between projects (calls/references found in the graph; name-based, verify before relying on them):\n")
            out.append(table(["From", "To", "References"], [(e["from"], e["to"], e["count"]) for e in g["project_edges"][:15]]))
        big = [x for x in g["communities"] if not re.search(r"(?i)scripts|wwwroot|/lib", " ".join(x["folders"]))][:8]
        if big:
            out.append("\nLargest code clusters:\n")
            out.append(table(["Cluster", "What it holds", "Elements", "Main folders", "Projects"],
                             [(x["name"], F.short(x.get("summary") or "", 160), x["size"], ", ".join(x["folders"]), ", ".join(x["projects"])) for x in big]))
        out.append("")
    return "\n".join(out) or "_Code graph not built._"


WIRING_MEANING = {
    "di registration": "interface call dispatched to the class the DI container registers for it",
    "di decorator": "call passes through a registered decorator first",
    "keyed service": "named / keyed registration picked by key at the injection site",
    "implementation (no registration found)": "interface call that can reach any implementation (no registration found)",
    "override": "virtual / abstract call dispatched to an override in a subclass",
    "message": "MediatR / bus message sent to its handler",
    "event": "event raised and handled by a subscriber",
    "method group": "method passed as a delegate and called later",
    "stored delegate": "lambda stored in an object and invoked elsewhere",
    "dispatch table": "handler picked from a dictionary / switch of delegates",
    "background job": "Hangfire / Quartz job enqueued for later",
    "redirect": "MVC RedirectToAction / string route to another action",
    "filter": "MVC filter attribute run around an action",
    "service locator": "service resolved from the container inside a method",
    "local variable": "static call through a local or loop variable (missed by graphify's own pass, not run-time bound)",
    "only implementation": "interface call with a single implementation",
    "partial class field": "static call on a field declared in another file of the same partial class",
}


def b_wiring(c):
    out = []
    for r in c.repos:
        w = (c.graph.get(r) or {}).get("wiring")
        if not w:
            continue
        cont = ", ".join(f"{k} ({v})" for k, v in w["containers"].items()) or "none found"
        hosts = ", ".join(f"{h} ({n})" for h, n in sorted(w["by_host"].items(), key=lambda x: -x[1]))
        lts = ", ".join(f"{k} {v}" for k, v in sorted(w["by_lifetime"].items(), key=lambda x: -x[1]))
        out.append(f"**{r}** — DI containers: {cont}. {w['registrations']} registrations"
                   + (f" in {hosts}" if hosts else "") + (f"; lifetimes: {lts}" if lts else "") + ". "
                   + f"{w['consumers']} classes take dependencies through constructors or `@inject`.\n")
        added = w.get("edges_added") or {}
        if added:
            out.append(f"Calls the code graph could not see and the C# resolver added (graphify found {w['graphify_calls']:,} calls itself):\n")
            out.append(table(["How the call is bound", "Calls", "Meaning"],
                             [(k, n, WIRING_MEANING.get(k, "")) for k, n in sorted(added.items(), key=lambda x: -x[1])]))
        facts = [(label, w.get(key)) for label, key in (("keyed registrations", "keyed"), ("decorators", "decorators"), ("factory registrations", "factories"),
                                                         ("assembly-scan conventions", "conventions"), ("registration modules", "modules"),
                                                         ("message types", "messages"), ("message handlers", "message_handlers"),
                                                         ("background jobs", "jobs"), ("event subscriptions", "events"), ("stored delegates", "stored_delegates"),
                                                         ("dispatch tables", "dispatch_tables"), ("options bindings", "options"),
                                                         ("service-locator calls", "locators"), ("reflection sites", "reflection")) if w.get(key)]
        if facts or w.get("pipeline"):
            out.append("\n" + "; ".join(f"{n} {label}" for label, n in facts)
                       + ("; pipeline: " + ", ".join(f"{k} ({n})" for k, n in w["pipeline"].items()) if w.get("pipeline") else "") + ".\n")
        if w.get("framework_features"):
            out.append(f"Framework features registered (re-created in the new composition root): {', '.join('`' + x + '`' for x in w['framework_features'][:20])}.\n")
        pp = sorted(w.get("per_project", {}).items(), key=lambda x: -(x[1]["indirect"] + x[1]["locators"]))
        rows = [(os.path.splitext(os.path.basename(p))[0], v["indirect"], v["locators"], v["reflection"], v["registrations"],
                 ", ".join(f"{k} {n}" for k, n in sorted(v["kinds"].items(), key=lambda x: -x[1])[:3]))
                for p, v in pp[:12] if v["indirect"] or v["locators"] or v["reflection"] or v["registrations"]]
        if rows:
            out.append("\nPer project (run-time-bound and service-locator calls per KLOC raise the project's complexity factor, section 8):\n")
            out.append(table(["Project", "Run-time-bound calls", "Service-locator calls", "Reflection", "Registrations", "Main kinds"], rows))
        out.append("")
    if not out:
        return "_Run-time wiring not analysed (no C# resolver output; rerun map_graphs.py with the codebase-documenter installed)._"
    out.append("_Source: codebase-documenter `csharp_resolve.py` over the graphify graph (regular expressions, not a compiler: "
               "verify a surprising edge in code). Findings are in category “Dependency injection and run-time wiring”._")
    return "\n".join(out)


def b_dependencies(c):
    rows = []
    for r in c.repos:
        for e in c.scan[r].get("endpoints", []):
            kind = {"internal": "On-prem / internal", "external": "External service", "external-ip": "Public IP"}.get(e["kind"], e["kind"])
            ev = e["evidence"][0] if e.get("evidence") else {}
            rows.append((kind, e["host"], ", ".join(e["schemes"]), e["occurrences"], f"{ev.get('file')}:{ev.get('line')}" if ev else "", r))
        for cs in c.scan[r].get("connection_strings", []):
            rows.append(("Database", f"{cs.get('host') or '-'} / {cs.get('database') or '-'}", f"{cs.get('provider') or 'SqlClient'}; auth {cs.get('auth')}" + ("; LocalDB (dev)" if cs.get("localdb") else ""),
                         1, f"{cs['file']}:{cs['line']}", r))
    rows.sort(key=lambda x: (x[0] != "On-prem / internal", x[0], x[1]))
    return table(["Kind", "System", "Protocol / details", "References", "First evidence", "Repository"], rows)


def b_network(c):
    """Network allow-list: what the AWS VPC must let out (egress, VPN routes, partner allow-lists) and in (listeners)."""
    nw = A.network(c)
    if nw["missing"] and not (nw["outbound"] or nw["inbound"]):
        return "_Network allow-list not analysed (codebase-documenter not found; set CODEBASE_DOCUMENTER_DIR and rerun scan_repo.py --force)._"
    tech = Counter(cl["tech"] for cl in nw["clients"])
    out = ["**Network allow-list: outbound (egress)**: every destination named in code or configuration (URL literals, host settings, "
           "connection strings, WCF client endpoints, UNC shares). Ports marked (default) are the protocol default, not read from the code. "
           "Destinations built at run time are not visible: confirm the list with the client's network team.\n",
           table(["Role", "Destination", "Port", "Protocol", "Kind", "Applications", "Defined in (how it is configured)", "Evidence", "Needed on AWS"],
                 [(x["role"], f"`{x['host']}`", x["port"], x["protocol"], {"internal": "On-prem / internal", "external": "External", "external-ip": "Public IP"}.get(x["kind"], x["kind"]),
                   x["applications"], x["defined"], x["evidence"], x["needs"]) for x in nw["outbound"]]) if nw["outbound"] else "_No outbound destination named in code or configuration._",
           "\n**Inbound listeners**: ports the applications open. launchSettings / IIS Express are local development ports; on AWS the ALB "
           "listens on 443 and forwards to the container port.\n",
           table(["Application / project", "Port", "Protocol", "Source", "Evidence"],
                 [(x["application"], x["port"], x["protocol"], x["source"], x["evidence"]) for x in nw["inbound"]]) if nw["inbound"] else "_No listener configuration found._"]
    if nw["drives"]:
        out.append("\n**Drive letters other than C:** (often mapped network drives, which do not exist in a container or on a new host): "
                   + "; ".join(f"`{d['drive']}` " + (f"in `{d['key']}` " if d["key"] else "") + f"({d['file']}:{d['line']})" for d in nw["drives"][:20])
                   + ". Ask what each maps to; replace with a share path from configuration (Amazon FSx) or object storage (S3).")
    if nw["clients"]:
        out.append(f"\n**Outbound call sites**: {len(nw['clients'])} ({', '.join(f'{t} {v}' for t, v in tech.most_common())}); "
                   f"{nw['runtime_clients']} get their destination at run time (no configuration key or literal next to the call): ask the client where those addresses come from.")
    return "\n".join(out)


def b_jobs(c):
    """Scheduled and background jobs: what runs, when, how it is configured, and where it goes on AWS."""
    jb = A.jobs(c)
    if jb["missing"] and not jb["jobs"]:
        return "_Scheduled jobs not analysed (codebase-documenter not found; set CODEBASE_DOCUMENTER_DIR and rerun scan_repo.py --force)._"
    if not jb["jobs"]:
        return ("**Scheduled and background jobs**: none found in the repository (no Task Scheduler, SQL Agent, Hangfire, Quartz, hosted "
                "service, timer or CronJob). Ask the client whether anything runs on a schedule outside the code.")
    win = sum(1 for j in jb["jobs"] if j["windows_only"])
    return ("**Scheduled and background jobs**: what runs on a schedule or in the background, how often, and how it is configured. "
            f"{len(jb['jobs'])} found, {win} on a Windows-only scheduler. Jobs triggered from outside the repository (Task Scheduler on a "
            "server, Control-M, an operator) are invisible here: confirm the full list with the client.\n\n"
            + table(["Job", "Scheduler", "Schedule", "Runs", "Configured by", "Application", "Windows-only", "On AWS", "Evidence"],
                    [(j["name"] or "-", j["scheduler"], j["schedule"] or "-", f"`{j['target']}`" if j["target"] else "-", j["configured_by"] or "-",
                      j["application"], "yes" if j["windows_only"] else "no", j["aws"], f"{j['file']}:{j['line']}") for j in jb["jobs"]]))


def b_methodology(c):
    """How the estimate was calculated: the steps, the formulas and this assessment's own numbers as a worked example."""
    est, cfg = c.est, data("estimation.json")
    t, sp = est.get("totals", {}), est.get("sprints") or {}
    if not t.get("likely_hours"):
        return "_Not estimated._"
    f = est.get("ai_factors") or {}
    pc = lambda r: f"{round(r[0] * 100)}–{round(r[1] * 100)} %"
    wps = est.get("work_packages", [])
    conv = [x for wp in wps for x in wp.get("conversion", [])]
    fnd = [x for wp in wps for x in wp.get("findings", [])]
    big = max(conv, key=lambda x: x["manual_hours"][1], default=None)
    many = max((x for x in fnd if x.get("occurrences", 1) > 1), key=lambda x: x["manual_hours"][1], default=None)
    rc = cfg.get("rollup", {})
    team = cfg["team"]
    hpd = est.get("hours_per_day", 8)
    pos = sorted(set((est.get("likely_position") or {}).values())) or [cfg["likely_position"]]
    p10, p90 = t["total_hours"]
    p50, p80 = t["likely_hours"], t.get("p80_hours", t["likely_hours"])
    lo_pct, hi_pct = round(100 * (p10 - p50) / p50), round(100 * (p90 - p50) / p50)
    out = ["The estimate is built **bottom-up from the code**, not from a top-down guess. Every project, every finding and every database object "
           "becomes a work item with a low and a high number of hours. AI-assisted delivery factors are applied, a simulation combines the "
           "items into a range, and the sprint plan turns hours into calendar time. Every rate and factor sits in one file "
           f"(`scripts/data/estimation.json`, version `{cfg.get('version', '-')}`), so a reviewer can trace each hour.\n",
           "**Step 1: work items from the code.** The scanners count hand-written lines (generated, designer and vendored code excluded), "
           "findings with their occurrences, and database objects and T-SQL constructs. "
           f"This assessment: {len(conv)} project conversions and {len(fnd)} findings in application packages"
           + (", plus the database inventory" if est.get("databases") else "") + ".\n",
           "**Step 2: project conversion (manual hours).**\n",
           "```text\nconversion hours = (set-up + code KLOC × rate + markup KLOC × markup rate) × complexity factor × size factor\n```\n",
           "- *Set-up*: fixed hours per project (project file, build, references), by project type.",
           "- *Code KLOC × rate*: hand-written code only, at the published productivity for that kind of port (for example ASP.NET Core "
           "retarget vs Web Forms rewrite). *Markup KLOC × markup rate*: views, pages and other markup.",
           "- *Complexity factor*: decision density, fan-in, very large files and run-time-bound calls (section 8.3).",
           f"- *Size factor*: `max(1, (repository KLOC / {(cfg.get('scale') or {}).get('reference_kloc', 10)}) ^ {(cfg.get('scale') or {}).get('exponent', 0.1)})`, "
           "the COCOMO II diseconomy of scale: bigger code bases cost more per line. "
           + ("This assessment: " + ", ".join(f"{r} {v:g}×" for r, v in (est.get("scale") or {}).items()) + "." if est.get("scale") else "")]
    if big:
        ptype = (re.search(r"\(([\w\-]+),", big["item"]) or [None, ""])[1]
        rate = cfg["conversion_hours_per_kloc"].get(ptype)
        fixed = cfg["conversion_fixed_hours"].get(ptype, cfg["conversion_fixed_hours"].get("default"))
        markup = cfg["markup_hours_per_kloc"].get(ptype)
        inputs = ([f"set-up {fixed[0]:g}–{fixed[1]:g} h"] if fixed else []) + [f"{big['kloc']} code KLOC"] + \
                 ([f"rate {rate[0]:g}–{rate[1]:g} h/KLOC ({ptype})"] if rate else []) + \
                 ([f"{big['markup_kloc']} markup KLOC at {markup[0]:g}–{markup[1]:g} h/KLOC"] if markup and big.get("markup_kloc") else []) + \
                 [f"complexity {big.get('complexity_factor', 1)}× ({big.get('complexity_why', '-')})"] + \
                 ([f"size factor {big['size_factor']:g}×"] if big.get("size_factor") else [])
        out.append(f"- Example from this code base: *{big['item']}*: " + ", ".join(inputs)
                   + f" → **{big['manual_hours'][0]:g}–{big['manual_hours'][1]:g} h manual**.")
    fh = cfg["finding_hours"]
    out += ["\n**Step 3: findings (manual hours).** Each finding is priced by its effort class, growing with occurrences up to a cap:\n",
            "```text\nfinding hours = fixed + per-occurrence × (occurrences − 1), capped\n```\n",
            table(["Effort class", "Fixed (low–high)", "Per extra occurrence", "Cap"],
                  [(k, f"{v['fixed'][0]:g}–{v['fixed'][1]:g} h", f"{v['per'][0]:g}–{v['per'][1]:g} h", f"{v['cap'][0]:g}–{v['cap'][1]:g} h")
                   for k, v in fh.items() if k in ("trivial", "small-change", "medium-change", "large-change")])]
    if many:
        out.append(f"\nExample: *{many['title']}* ({many['occurrences']} occurrences) → {many['manual_hours'][0]:g}–{many['manual_hours'][1]:g} h manual. "
                   "Findings already covered by the conversion rate add nothing (no double counting).")
    db = next((d["options"][d["selected"]] for d in est.get("databases", []) if d.get("selected") not in (None, "none")), None)
    if db and db.get("breakdown_manual_hours"):
        b = db["breakdown_manual_hours"]
        rows = [(n, f"{b[k][0]:g}–{b[k][1]:g} h") for k, n in (("objects", "Convert database objects (tables, views, routines, triggers, types) by kind and size band"),
                                                              ("constructs", "Rewrite / redesign T-SQL constructs PostgreSQL cannot run as written"),
                                                              ("code", "Data-access code (embedded SQL, procedure calls, provider APIs)"),
                                                              ("findings", "Database findings"), ("dual_extra", "Provider-neutral data layer (dual database)")) if b.get(k)]
        out += ["\n**Step 4: database code (manual hours).** Each object is priced by kind and size band, each T-SQL construct by how it converts "
                "(automatic, rewrite, redesign), and each data-access call site in C#. This assessment:\n",
                table(["Part", "Manual hours (low–high)"], rows)]
    out += ["\n**Step 5: AI-assisted delivery.** Coding agents and conversion tools do the mechanical part; engineers direct, review and fix:\n",
            "```text\nAI-assisted hours = manual hours × factor\n```\n",
            f"- Code: {pc(f.get('code', [1, 1]))} of manual effort; database conversion: {pc(f.get('db', [1, 1]))}; redesign work with no "
            f"mechanical path (Web Forms UI, constructs with no PostgreSQL equivalent, the dual-database layer): {pc(f.get('redesign', [1, 1]))}.",
            "- The factor is drawn **once per simulated project**, not per item: if the tools help less than hoped, they help less everywhere.",
            "\n**Step 6: a three-point estimate per item.** Each item has a low, a high and a most likely value:\n",
            "```text\nlikely = low + position × (high − low)        position = " + " / ".join(f"{p:g}" for p in pos) + "\n```\n",
            "\n**Step 7: Monte Carlo roll-up into a range.** Adding every low and every high would assume every item lands at the same extreme "
            f"together, which gave {t.get('bounds_hours', [0, 0])[0]}–{t.get('bounds_hours', [0, 0])[1]} h here. Instead the project is simulated "
            f"{rc.get('iterations', 4000):,} times (fixed seed, so reruns give the same numbers):\n",
            "```text\nper run:  z_shared ~ N(0,1)\n"
            f"          per item: z = √{rc.get('correlation', 0.3)} · z_shared + √{round(1 - rc.get('correlation', 0.3), 2)} · z_own"
            "      (items share risk: correlation " + f"{rc.get('correlation', 0.3)})\n"
            "          u = Φ(z);  hours = triangular⁻¹(u; low, likely, high) × AI factor\n"
            "          total = Σ items\n"
            "result:   P10 / P50 / P80 / P90 of the totals\n```\n",
            f"- **P50 (likely) = {p50} h**: half of the simulated projects finish below it.",
            f"- **P10–P90 = {p10}–{p90} h**: the 80 % range ({lo_pct:+d} % / {hi_pct:+d} % around P50).",
            f"- **P80 = {p80} h**: the commitment figure; four in five simulated projects finish within it.",
            f"- The correlation of {rc.get('correlation', 0.3)} is the default the GAO Cost Estimating and Assessment Guide (GAO-20-195G) takes from the "
            "DoD / NASA Joint Agency Cost and Schedule Risk Handbook when item correlations are unknown.",
            "- " + ("This spread is within AACE 18R-97 **Class 3** accuracy (−10…−20 % / +10…+30 %)" if lo_pct >= -20 and hi_pct <= 30 else
                    "This spread is within AACE 18R-97 **Class 4** accuracy (−15…−30 % / +20…+50 %)" if lo_pct >= -30 and hi_pct <= 50 else
                    "This spread is wider than AACE 18R-97 Class 4: treat the estimate as Class 5 (order of magnitude) until the open questions are answered")
            + ", the expected band for an estimate built from the code before detailed design.",
            "\n**Step 8: hours to days and calendar time.**\n",
            "```text\nperson-days = hours ÷ " + f"{hpd:g}" + "\ncapacity per sprint = engineers × days per week × sprint weeks × hours per day × efficiency\n```\n"]
    if sp.get("plan"):
        eng = sp["engineers"]
        out += [f"- This assessment: {eng} × {team['days_per_week']} × {sp['length_weeks']} × {hpd:g} × {team['efficiency']} = "
                f"**{sp['capacity_per_sprint_hours']} h per sprint**. Sprint 1 loses {sp.get('onboarding_days', 0)} onboarding day(s) "
                f"(capacity {sp['plan'][0]['capacity_hours']} h).",
                f"- P50 work of {p50} h, planned in dependency order → **{sp['sprints_p50']} sprint(s), about {sp['weeks_p50']} weeks**; at P80 "
                f"({p80} h) → **{sp['sprints_p80']} sprint(s), about {sp['weeks_p80']} weeks**.",
                f"- Person-days: {p50} h ÷ {hpd:g} = {t.get('likely_days')} days at P50; {p80} h ÷ {hpd:g} = {t.get('p80_days')} days at P80."]
    out += ["\n**What the numbers do not include:** QA and test cycles, DevOps / infrastructure, project management, data migration and "
            "contingency (section 8.7). Add them on top, using the organisation's own ratios.",
            "\n**Sources:** AACE International Recommended Practices 18R-97 and 41R-08; GAO Cost Estimating and Assessment Guide (GAO-20-195G); "
            "COCOMO II (scale and reuse); PERT / triangular three-point estimating; published AWS Transform for .NET and code-migration case "
            "studies for the AI-assisted factors (references/estimation-validation.md)."]
    return "\n".join(out)


def evidence_cell(f, n=2):
    ev = f.get("evidence") or []
    cells = [f"`{F.evidence_ref(e)}`" for e in ev[:n]]
    more = (f.get("occurrences") or len(ev)) - len(cells)
    return "<br>".join(cells) + (f"<br>+{more} more" if more > 0 else "")


def b_findings_summary(c):
    rows = []
    for cat in c.cats:
        fs = [f for f in c.findings if f["category"] == cat["id"]]
        s = Counter(f["severity"] for f in fs)
        rows.append((cat["title"], *[s[k] or "" for k in SEVS], "checked, none found" if not fs else f"{len(fs)} finding(s)"))
    return table(["Category", *SEVS, "Status"], rows)


def b_findings_by_category(c):
    out = []
    segs = {x["id"]: x for x in data("categories.json").get("segments", [])}
    last = None
    for n, cat in enumerate(c.cats, 1):
        fs = [f for f in c.findings if f["category"] == cat["id"]]
        if cat.get("segment") != last and cat.get("segment") in segs:
            last = cat["segment"]
            out.append(f"**{segs[last]['title']}** — {segs[last]['description']}\n")
        out.append(f"### 5.{n} {cat['title']}\n")
        out.append(f"_Checked:_ {cat['scanned']}.\n")
        extra = CATEGORY_EXTRAS.get(cat["id"])
        if extra:
            out.append(extra(c) + "\n")
        if not fs:
            if cat["id"] not in INFO_ONLY:
                out.append("**Checked, none found.**\n")
            continue
        rows = []
        for f in fs:
            where = ", ".join(c.apps[a]["name"] for a in f.get("apps", []) if a in c.apps) or (f["project"] if f["project"] != "(repository)" else f["repo"])
            fix = f.get("fix", "") + (f" _Alternative:_ {f['alt']}" if f.get("alt") else "") + (f" _Note:_ {f['note']}" if f.get("note") else "")
            if f.get("review", {}).get("note"):
                fix += f" _Review:_ {f['review']['note']}"
            rows.append((f["ref"], f["severity"], f["confidence"], f["title"], where, f.get("occurrences", 1), evidence_cell(f), F.short(f.get("why"), 220), F.short(fix, 320)))
        out.append(table(["Ref", "Severity", "Confidence", "Finding", "Where", "Count", "Evidence", "Impact", "Recommendation"], rows) + "\n")
    return "\n".join(out)


def extra_tooling(c):
    rows = [("Windows-only API usage, unsupported .NET Framework technologies", "This scan (rules), .NET platform analyzer CA1416 after retargeting, AWS Transform assessment", "Confirm each hit is reachable; decide replacement"),
            ("Package compatibility", "Package map + nuget.org metadata; AWS Transform / GitHub Copilot app modernization assessment", "Licence and vendor roadmap decisions"),
            ("Architecture, dependencies", "graphify code graph; CAST Imaging / CAST Highlight (if licensed)", "Business-flow meaning, ownership"),
            ("Infrastructure, scheduled tasks, certificates, IIS settings", "Not visible to code scanners", "Server inventory with the client (AWS Application Discovery Service / Migration Evaluator / OLA)"),
            ("Runtime verification on Linux", "`dotnet build` on Linux / WSL / container after SDK conversion (validate_linux_build.py)", "Workflow testing by QA with domain knowledge")]
    out = table(["Area", "Automated by", "Needs people"], rows)
    for r in c.repos:
        lb = read_json(os.path.join(OUT, "scan", f"{r}.linux-build.json"))
        if not lb:
            continue
        how = f"executed with runner `{lb['runner']}`" if lb.get("executed") else "planned only (not executed: needs a Linux runner and package/image downloads)"
        out += f"\n\n**Linux build validation — {r}** ({how}):\n\n"
        out += table(["Project", "TFM", "Result", "Detail"], [(p["project"], ", ".join(p["tfms"]), p["status"], F.short(p.get("detail"), 160)) for p in lb["projects"]])
    return out


def extra_inventory(c):
    t = Counter()
    for r in c.repos:
        for p in (c.inv[r] or {}).get("projects", []):
            t[p["type"]] += 1
    return "Project types: " + ", ".join(f"{k} {v}" for k, v in t.most_common()) + ". Full list: Appendix A2."


def extra_parallel(c):
    rows = []
    for r in c.repos:
        g = (c.inv[r] or {}).get("git", {})
        if g.get("git"):
            rows.append((r, g.get("branch"), g.get("last_commit"), g.get("commits"), g.get("commits_per_week"), g.get("authors"), c.scan[r].get("activity_level", "-"),
                         ", ".join(f for f, _ in (g.get("hot_files") or [])[:3])))
    return table(["Repository", "Branch", "Last commit", "Commits (window)", "Per week", "Authors", "Level", "Hot files"], rows)


def extra_tests(c):
    rows = []
    for r in c.repos:
        for p, t in c.scan[r].get("tests", {}).items():
            rows.append((r, p, t["test_methods"], ", ".join(t["frameworks"])))
    return table(["Repository", "Test project", "Test methods", "Frameworks"], rows) + "\n\n" + \
        "Tests per KLOC: " + ", ".join(f"{r} {c.scan[r].get('tests_per_kloc', 0)}" for r in c.repos)


INFO_ONLY = {"tooling"}  # explanatory categories: a table, never findings
CATEGORY_EXTRAS = {"tooling": extra_tooling, "inventory": extra_inventory, "parallel-dev": extra_parallel, "tests": extra_tests}


DB_LABEL = {"postgresql": "PostgreSQL only", "dual": "Dual: SQL Server and PostgreSQL"}


def b_database(c):
    out = []
    for d in c.est.get("databases", []):
        sel = d.get("selected", d.get("recommended"))
        out.append(f"**{d['repo']}** — databases: {', '.join(d['databases'])}" + (f"; connections in code: {', '.join(d['connections'])}" if d["connections"] else "") + "\n")
        rows = []
        for t, label in DB_LABEL.items():
            o = d["options"].get(t)
            if not o:
                continue
            rows.append((label + (" — selected" if t == sel else ""), hd(o["days"], o.get("hours")), f"{o.get('likely_hours', '-')} h", ", ".join(o.get("redesign", [])) or "none",
                         ", ".join(o.get("rework", [])) or "-"))
        out.append(table(["Scenario (code and SQL conversion only)", "Effort (AI-assisted, P10–P90)", "Likely (P50)", "No PostgreSQL equivalent (redesign)", "Needs rework"], rows))
        out.append(f"\n{d['note']}\n")
    feats = [f for f in c.findings if f["category"] == "database"]
    if feats:
        out.append("SQL Server features found that need work for PostgreSQL (details in 5, Database):\n")
        out.append(table(["Ref", "Feature", "PostgreSQL impact", "Count", "Evidence"], [(f["ref"], f["title"], (f.get("db") or {}).get("pg", "convert"), f.get("occurrences"), evidence_cell(f, 1)) for f in feats]))
    elif not out:
        out.append("No SQL Server database code (SSDT projects, .sql files) was found in the repositories; database fit is assessed from connection strings only.")
    return "\n".join(out)


def b_db_inventory(c):
    import _dbinventory as DBI
    out = []
    lvl_name = {"auto": "Automatic (tooling / rename, review only)", "rewrite": "Manual rewrite (PostgreSQL equivalent exists)",
                "redesign": "Redesign (no PostgreSQL equivalent)"}
    for d in c.est.get("databases", []):
        inv = d.get("inventory") or {}
        if not inv:
            continue
        if inv.get("note"):
            out.append(f"**{d['repo']}** — {inv['note']}\n")
        k = inv.get("kinds", {})
        rs = inv.get("routine_sizes", {})
        eng = {"scriptdom": "Microsoft's T-SQL parser (ScriptDom)",
               "sqlglot": "sqlglot (fallback parser: procedural T-SQL may be partly unparsed)"}.get(inv.get("engine"), "no parser")
        errs = inv.get("parse_errors") or []
        out.append(f"**{d['repo']}** — {sum(k.values())} database objects, {inv.get('sql_lines', 0):,} lines of T-SQL, parsed with {eng}"
                   + (f"; {len(errs)} syntax errors (finding DB-SQL-SYNTAX)" if errs else "; no syntax errors") + ".\n")
        if k:
            out.append(table(["Object type", "Count"], sorted(k.items(), key=lambda x: -x[1])))
            out.append("\nRoutine size (procedures, functions, triggers, views): " + ", ".join(f"{s} {rs.get(s, 0)}" for s in ("small", "medium", "large"))
                       + " (small ≤ 50 lines, large > 200).\n")
        conv = inv.get("conversion") or {}
        opt = d["options"].get("dual") or d["options"].get("postgresql") or {}
        bk = (opt.get("breakdown_manual_hours") or {}).get("construct_levels", {})
        if conv:
            out.append("**PostgreSQL conversion of the SQL constructs** (every construct the parser found, classified by data/pg_conversion.json):\n")
            out.append(table(["Level", "In database objects", "In SQL embedded in code", "Manual-equivalent hours"],
                             [(lvl_name[lv], (conv.get("database") or {}).get(lv, 0), (conv.get("code") or {}).get(lv, 0), rng(bk[lv]) if bk.get(lv) else "-")
                              for lv in ("auto", "rewrite", "redesign")]))
        red = inv.get("redesign_items") or []
        if red:
            groups = {}
            for it in red:
                g = groups.setdefault(it["construct"], {"n": 0, "where": [], "pg": it["pg"]})
                g["n"] += it["count"]
                g["where"].append(f"{it['object'] or it['kind']} (`{it['file']}:{it['line']}`)")
            out.append("\n**Cannot be converted as written: no PostgreSQL equivalent** (a design decision is needed before the port):\n")
            out.append(table(["Construct", "Occurrences", "Where", "Replacement approach"],
                             [(kk, g["n"], ", ".join(g["where"][:4]) + (f" +{len(g['where']) - 4} more" if len(g["where"]) > 4 else ""), g["pg"])
                              for kk, g in sorted(groups.items(), key=lambda x: -x[1]["n"])]))
        cons = inv.get("constructs", {})
        if cons:
            rows = [(kk, n, DBI.conversion(kk)["level"], DBI.conversion(kk)["pg"]) for kk, n in sorted(cons.items(), key=lambda x: -x[1])[:40]]
            out.append("\n" + table(["T-SQL construct (database objects)", "Occurrences", "Level", "PostgreSQL approach"], rows)
                       + (f"\n_{len(cons) - 40} rarer constructs are in assessment/scan/{d['repo']}.json (db_inventory.constructs)._" if len(cons) > 40 else ""))
        st = inv.get("code_sql_stats") or {}
        code = dict(inv.get("code", {}))
        if st.get("candidates"):
            code_cons = inv.get("code_constructs") or {}
            out.append(f"\n**SQL embedded in application code**: {st.get('accepted', 0)} statements parsed from string literals across {st.get('files', 0)} C# files "
                       f"({code.get('dynamic_sql_in_code', 0)} built at run time; {st.get('parse_errors', 0)} SQL-looking literals are fragments or text and are not counted).\n")
            if code_cons:
                out.append(table(["T-SQL construct (embedded SQL)", "Occurrences", "Level", "PostgreSQL approach"],
                                 [(kk, n, DBI.conversion(kk)["level"], DBI.conversion(kk)["pg"]) for kk, n in sorted(code_cons.items(), key=lambda x: -x[1])[:20]]))
        code["EDMX function imports"] = inv.get("edmx_function_imports", 0)
        names = {"stored_procedure_calls": "Stored-procedure calls in code", "inline_sql_strings": "SQL statements embedded in code (parsed)",
                 "tsql_in_strings": "Embedded statements needing a rewrite or redesign", "dynamic_sql_in_code": "Embedded statements built at run time",
                 "sqlclient_usage": "SqlClient usage (provider swap to Npgsql)", "dapper_calls": "Dapper calls", "ef6_contexts": "Entity Framework contexts"}
        out.append("\n" + table(["Data-access code (changes for PostgreSQL / dual)", "Count"], [(names.get(a, a), b) for a, b in code.items() if b]))
        if errs:
            out.append("\nSyntax errors reported by the parser (first 10): " + "; ".join(f"`{e['file']}:{e['line']}` {e['message']}" for e in errs[:10]) + "\n")
        for t in ("postgresql", "dual"):
            o = d["options"].get(t)
            if o and o.get("breakdown_manual_hours"):
                bkk = o["breakdown_manual_hours"]
                out.append(f"\n**{DB_LABEL[t]}** — manual-equivalent hours: objects {rng(bkk['objects'])}, T-SQL constructs {rng(bkk['constructs'])}, "
                           f"data-access code {rng(bkk['code'])}, findings without a PostgreSQL equivalent {rng(bkk['findings'])}"
                           + (f", provider-neutral data layer {rng(bkk['dual_extra'])}" if t == "dual" else "")
                           + f". AI-assisted total: {hd(o['days'], o['hours'])}. Data migration, tooling set-up and database testing are not included.\n")
    return "\n".join(out) or "_No database code in the repositories._"


def b_scenarios(c):
    comp = c.est.get("comparisons") or []
    if not comp:
        return "_Scenarios not computed (rerun estimate_effort.py)._"
    out = ["**Code-side options** (database scenario: " + (c.est.get("scenario", {}).get("database_label") or "") + "; coding effort only)\n"]
    out.append(table(["Option", "Effort (AI-assisted, P10–P90)", "Likely (P50)", "Manual likely", "Duration", "Notes"],
                     [(("**" if x["selected"] else "") + x["label"] + (" (selected)**" if x["selected"] else ""), hd(x["total_days"], x["total_hours"]), f"{x['likely_hours']} h / {x['likely_days']} d",
                       f"{x['manual_likely_hours']} h", f"~{x['duration_weeks']} weeks", " ".join(x.get("notes", []))[:300]) for x in comp if x["kind"] == "hosting"]))
    out.append("\n**Database code options** (code scenario: " + (c.est.get("scenario", {}).get("hosting_label") or "") + ")\n")
    out.append(table(["Option", "Database work (P10–P90)", "Total effort (AI-assisted, P10–P90)", "Likely (P50)", "Manual likely", "Duration"],
                     [(("**" if x["selected"] else "") + x["label"] + (" (selected)**" if x["selected"] else ""), rng(x.get("database_hours", [0, 0]), " h"), hd(x["total_days"], x["total_hours"]),
                       f"{x['likely_hours']} h / {x['likely_days']} d", f"{x['manual_likely_hours']} h", f"~{x['duration_weeks']} weeks") for x in comp if x["kind"] == "database"]))
    return "\n".join(out)


def b_optional(c):
    """Optional modernizations: managed AWS services the code could adopt. Reported beside the estimate, never in it."""
    items = c.est.get("optional") or []
    if not items:
        return "_No optional modernization opportunities were detected (SMTP / SMS, Kafka / message queues, local file storage, in-process caches and schedulers, custom authentication, file logging, self-hosted search)._"
    rows = [(o["title"], o["aws"], o["count"], ", ".join(f"`{f['file']}:{f['line']}`" for f in o["files"][:2]) + (f" +{o['count'] - 2} more" if o["count"] > 2 else ""),
             rng(o["hours"], " h"), o["why"]) for o in items]
    t = (c.est.get("totals") or {}).get("optional_hours", [0, 0])
    return ("These are improvements the client may choose; none is needed to run on Linux or AWS and **none is included in the effort estimate**. Hours are AI-assisted coding hours per item.\n\n" +
            table(["Opportunity", "Suggested AWS service", "Files", "Evidence", "Coding effort", "Why consider it"], rows) +
            f"\n\nIf every item were adopted: {rng(t, ' h')} of additional coding.")


def b_app_plans(c):
    out = []
    for a in c.cls["applications"]:
        w = c.wp.get(a["id"], {})
        fs = [f for f in c.findings if a["id"] in f.get("apps", []) and f["severity"] in ("Blocker", "High")]
        out.append(f"### {a['name']} ({a['repo']})\n")
        out.append(table(["Item", "Value"], [("Type / framework", f"{a['type']} / {', '.join(a.get('target_frameworks', [])) or a.get('framework_family')}"), ("Size", f"{a['loc']:,} lines, {len(a['projects'])} project(s)"),
                                             ("Recommendation (7R)", f"**{a['r7']}**" + (" — reviewer decision" if a.get("decision_source") == "review" else " — draft from rules, pending review")),
                                             ("Target", a["target"]), ("Effort", f"{hd(w['total_days'], w.get('total_hours'))}, likely {w.get('likely_hours', '-')} h / {w.get('likely_days')} d, size {w.get('complexity')}" if w else "-"),
                                             ("Risk / confidence", f"{a['risk']} / {a.get('confidence')}")]))
        out.append("\n**Why:** " + " ".join(a.get("rationale", [])))
        if a.get("options"):
            out.append("\n**Options considered:** " + " ".join(f"({i}) {o}" for i, o in enumerate(a["options"], 1)))
        if fs:
            out.append("\n**Blocking / high findings:** " + "; ".join(f"{f['ref']} {f['title']}" for f in fs[:10]))
        if w.get("drivers"):
            out.append("\n**Main effort drivers:** " + "; ".join(w["drivers"]))
        if a.get("notes"):
            out.append("\n**To confirm:** " + " ".join(a["notes"]))
        out.append("")
    return "\n".join(out)


def b_hybrid(c):
    if not c.cls.get("hybrid"):
        return "_No library is shared between applications, so no hybrid (.NET Standard 2.0) step is needed._"
    rows = [(h["library"], ", ".join(h["used_by"]), ", ".join(h["current"]), ", ".join(h["retained_consumers"]) or "-", ", ".join(h["modernized_consumers"]) or "-", h["plan"], h["note"]) for h in c.cls["hybrid"]]
    return table(["Shared library", "Used by", "Current TFM", "Stays on .NET Framework", "Moves to .NET 10", "Plan", "Note"], rows)


def b_estimate(c):
    rows = []
    for w in sorted(c.est.get("work_packages", []), key=lambda w: -w["likely_days"]):
        rows.append((w["name"], w.get("r7") or w["kind"], hd(w["total_days"], w.get("total_hours")), f"{w.get('likely_hours', '-')} h / {w['likely_days']} d",
                     hd(w.get("manual_days"), w.get("manual_hours")) if w.get("manual_days") else "-", w["complexity"], "; ".join(w["drivers"][:3])))
    for d in c.est.get("databases", []):
        sel = d.get("selected", d["recommended"])
        if sel == "none":
            continue
        o = d["options"][sel]
        rows.append((f"{d['repo']}: database code ({sel})", "database", hd(o["days"], o.get("hours")), f"{o.get('likely_hours', '-')} h / {o['likely']} d",
                     hd([round(x / 8, 1) for x in o["manual_hours"]], o["manual_hours"]), "-", ", ".join(o.get("redesign", []) + o.get("rework", [])) or "-"))
    t = c.est.get("totals", {})
    rows.append(("**Total (coding only)**", "", f"**{hd(t.get('total_days', [0, 0]), t.get('total_hours'))}**", f"**{t.get('likely_hours', '-')} h / {t.get('likely_days', '-')} d**",
                 hd(t.get("manual_equivalent_days"), t.get("manual_equivalent_hours")) if t.get("manual_equivalent_days") else "", "",
                 f"{t.get('kloc', '-')} KLOC, {t.get('likely_hours_per_kloc', '-')} likely h/KLOC"))
    note = ""
    if t.get("p80_hours"):
        note = ("\n\nRanges are the 80% interval (P10–P90) of a Monte Carlo roll-up of every item's three-point estimate; **likely is P50** and the "
                f"**commitment figure is P80: {t['p80_hours']} h ({t.get('p80_days')} d)**. Package ranges do not add up to the total range: independent "
                "items partly cancel, which is why the total is narrower than the sum of its parts. Adding every item's low and every item's high gives "
                f"{rng(t.get('bounds_hours', [0, 0]), ' h')}, extremes that need every item at the same end at once (not a planning range).")
    return table(["Work package", "7R / kind", "Effort (AI-assisted, P10–P90)", "Likely (P50)", "Manual equivalent (P10–P90)", "Size", "Main drivers"], rows) + note


def sprint_note(sp):
    if not sp.get("plan"):
        return ""
    return (f"; {sp['sprints_p50']} sprint(s) of {sp['length_weeks']} weeks at P50 ({sp['sprints_p80']} at P80) from "
            + (sp["start_date"] if sp.get("start_date") else "the day of codebase access"))


def b_sprints(c):
    """Coding sprint plan from the day of codebase access (estimate.json "sprints")."""
    sp = c.est.get("sprints") or {}
    if not sp.get("plan"):
        return "_No sprint plan (rerun estimate_effort.py)._"
    rows = []
    for s in sp["plan"]:
        when = f"{s['start']} to {s['end']}" if s.get("start") else f"weeks {s['weeks']}"
        work = "<br>".join(f"{'DB' if r['lane'] == 'database' else 'App'}: {r['work']} — {r['hours']} h ({r['status']})" for r in s["items"])
        if s.get("onboarding"):
            work = f"Onboarding, {s['onboarding']}<br>" + work
        rows.append((f"Sprint {s['sprint']}", when, f"{s['capacity_hours']} h", f"{s['planned_hours']} h", work))
    head = (f"{sp['length_weeks']}-week sprints starting on the day the team gets codebase access"
            + (f" ({sp['start_date']})" if sp.get("start_date") else " (no date given: pass --start-date or set scenario.start_date)")
            + f". Team of {sp['engineers']} engineers"
            + (f", {sp['db_engineers']} of them on the database lane (unused lane capacity flows to the other lane)" if sp.get("db_engineers") else "")
            + f"; capacity {sp['capacity_per_sprint_hours']} h per sprint at the team efficiency. Work is planned at P50 in dependency order "
            "(shared libraries, repository-wide items, application waves). "
            + f"**{sp['sprints_p50']} sprint(s) at P50"
            + (f", ending {sp['end_p50']}" if sp.get("end_p50") else "") + f"; {sp['sprints_p80']} at P80"
            + (f", ending {sp['end_p80']}" if sp.get("end_p80") else "") + ".** Coding only: QA, release and data migration are planned separately.\n\n")
    return head + table(["Sprint", "Dates", "Capacity", "Planned (P50)", "Work"], rows)


def b_multipliers(c):
    """How the hours are built: the factors the engine applied (all in scripts/data/estimation.json)."""
    est = data("estimation.json")
    f = c.est.get("ai_factors") or {}
    pc = lambda r: rng([x * 100 for x in r], "%")
    cx = est["complexity"]
    rate = est["conversion_hours_per_kloc"]
    rows = [("Scope", "Coding effort only", "code and SQL conversion, fixing findings, unit tests written with the code; QA, DevOps, project management, drift and contingency are excluded"),
            ("Scenario", (c.est.get("scenario") or {}).get("hosting_label", "-"), "database: " + ((c.est.get("scenario") or {}).get("database_label") or "-")),
            ("AI-assisted code work", pc(f.get("code", [1, 1])) + " of manual effort" if c.est.get("ai_assisted") else "off (manual estimate)", "coding agents / AWS Transform for .NET / GitHub Copilot app modernization do the mechanical part; engineers direct, review and fix"),
            ("AI-assisted database conversion", pc(f.get("db", [1, 1])) + " of manual effort" if c.est.get("ai_assisted") else "off", "AWS DMS Schema Conversion (generative AI) + review for T-SQL to PL/pgSQL"),
            ("AI-assisted redesign work", pc(f.get("redesign", [1, 1])) + " of manual effort" if c.est.get("ai_assisted") else "off",
             "work with no mechanical path: Web Forms UI rewrite, medium / large findings, constructs with no PostgreSQL equivalent, dual-database abstraction (published AI gains are for mechanical changes)"),
            ("Size factor", ", ".join(f"{r} {v:.2f}x" for r, v in (c.est.get("scale") or {}).items()) or "1.00x",
             f"project conversion hours x max(1, (repository KLOC / {est['scale']['reference_kloc']}) ^ {est['scale']['exponent']}) (COCOMO II diseconomy of scale); 'likely' at {int(est['likely_position_large'] * 100)}% of the range for repositories of {est['scale']['large_kloc']}+ KLOC" if est.get("scale") else "-"),
            ("Port rate per KLOC (manual)", ", ".join(f"{k} {v[0]:g}–{v[1]:g} h" for k, v in rate.items() if k in ("class-library", "web-library", "aspnet-core", "aspnet-mvc", "aspnet-webapi", "wcf-service", "aspnet-webforms")), "hand-written lines; generated code excluded; markup has its own rate"),
            ("Complexity factor", f"{cx['min']}–{cx['max']}x", "decision density (" + ", ".join(f"≤{lim:g}/KLOC {fac}x" for lim, fac in cx["decisions_per_kloc_bands"][:-1]) + f", above {cx['decisions_per_kloc_bands'][-2][0]:g}/KLOC {cx['decisions_per_kloc_bands'][-1][1]}x) + {cx['fan_in_extra']}x for projects with {cx['fan_in_threshold']}+ dependents + {cx['big_file_extra']}x per file over 800 lines"
             + (" + " + ", ".join(f"{e:g}x at >{lim:g}" for (lim, _), (_, e) in zip(cx["indirection_per_kloc_bands"], cx["indirection_per_kloc_bands"][1:]))
                + " run-time-bound calls/KLOC (DI dispatch, overrides, messages, events, delegates, jobs, service locator: C# resolver)"
                + f" + {cx.get('reflection_extra', 0)}x per reflection site (cap {cx.get('reflection_cap', 0)}x)" if cx.get("indirection_per_kloc_bands") else ""))]
    return table(["Factor", "Value", "How it is used"], rows)


def b_timeline(c):
    tl = c.est.get("timeline", [])
    if not tl:
        return "_Not estimated._"
    today = datetime.date.today()
    base = today + datetime.timedelta(days=(7 - today.weekday()) % 7 or 7)  # indicative start: next Monday
    lines = ["```mermaid", "gantt", "  title Indicative plan (week 1 = " + base.isoformat() + ")", "  dateFormat YYYY-MM-DD", "  axisFormat %d %b"]
    for i, p in enumerate(tl):
        name = re.sub(r"[:#;]", " ", p["phase"])[:60]
        start = base + datetime.timedelta(weeks=p["start"])
        lines.append(f"  {name} :p{i}, {start.isoformat()}, {p['weeks'] * 7}d")
    lines.append("```")
    rows = [(p["phase"], f"week {p['start'] + 1}", f"{p['weeks']} week{'s' if p['weeks'] != 1 else ''}") for p in tl]
    return "\n".join(lines) + "\n\n" + table(["Phase", "Starts", "Duration"], rows)


def b_assumptions(c):
    return "\n".join(f"- {x}" for x in c.est.get("assumptions", []))


def b_risks(c):
    rows = []
    for f in c.findings:
        if f["severity"] in ("Blocker", "High") and f["confidence"] != "Confirmed":
            rows.append((f["ref"], f["title"], f["severity"], f["confidence"], "Verify in code / with client before committing to the estimate"))
    for a in c.cls["applications"]:
        if a["risk"] == "High":
            rows.append((a["name"], f"{a['r7']} with " + (", ".join(a.get("windows_bound") or []) or "high-severity findings"), "High", a.get("confidence"), "Prototype the hardest change first (spike) in wave 1"))
    return table(["Ref / application", "Risk", "Severity", "Confidence", "Mitigation"], rows)


STANDARD_QUESTIONS = [
    ("Infrastructure", "Server inventory per application: OS version, CPU/RAM, IIS version and modules, app-pool identities, and current utilisation (for right-sizing)."),
    ("Infrastructure", "Hypervisor and network: VMware / Hyper-V / Proxmox version, static IPs, VLANs and firewall rules the applications rely on."),
    ("Infrastructure", "Scheduled tasks, Windows services and SQL Agent jobs running on the servers (the repositories rarely contain all of them)."),
    ("Security", "Certificates in use (TLS, client, signing) and where their private keys live."),
    ("Security", "Compliance regime (HIPAA, PCI DSS, SOC 2, ISO 27001) and data-residency constraints that limit AWS Regions or services."),
    ("Identity", "How users authenticate today (AD, ADFS, Entra ID, local accounts) and whether a move to SSO/OIDC is acceptable."),
    ("Data", "Database sizes, growth, maintenance windows and acceptable downtime for cut-over."),
    ("Integrations", "Partners that allow-list our source IPs, VPN tunnels and on-prem systems that stay on-premises."),
    ("Delivery", "Branching model, release cadence, and whether a code-freeze window per wave is possible."),
    ("Testing", "Availability of QA with domain knowledge, test environments and test data per wave."),
    ("Licensing", "Current Windows Server and SQL Server licences (edition, cores, Software Assurance / licence mobility) for the cost model (AWS OLA).")]


def open_questions(c):
    qs, seen = [], set()
    for f in c.findings:
        q = f.get("question")
        if q and q not in seen:
            seen.add(q)
            qs.append(("Code finding", q, f["ref"]))
    for a in c.cls["applications"]:
        for n in a.get("notes", []):
            qs.append(("Application", n, a["name"]))
    for area, q in STANDARD_QUESTIONS:
        qs.append((area, q, "standard"))
    return qs


def b_open_questions(c):
    return table(["#", "Area", "Question", "Raised by"], [(i, a, q, r) for i, (a, q, r) in enumerate(open_questions(c), 1)])


def b_testing(c):
    rows = []
    for r in c.repos:
        s = c.scan[r]
        kloc = (c.inv[r] or {}).get("totals", {}).get("loc", 0) / 1000.0
        tests = sum(t["test_methods"] for t in s.get("tests", {}).values())
        rows.append((r, len(s.get("tests", {})), tests, s.get("tests_per_kloc", 0), f"{kloc:.1f}"))
    return table(["Repository", "Test projects", "Test methods", "Tests / KLOC", "KLOC"], rows)


def b_merge(c):
    return extra_parallel(c)


def b_cost(c):
    apps = c.cls["applications"]
    off_windows = [a["name"] for a in apps if a["r7"] in ("Replatform", "Refactor") and "Linux" in a["target"]]
    on_windows = [a["name"] for a in apps if a["r7"] in ("Retain", "Rehost") and a["type"] not in ("winforms", "wpf")]
    desk = [a["name"] for a in apps if a["type"] in ("winforms", "wpf")]
    dbs = c.est.get("databases", [])
    rows = [("Applications moving to Linux (Windows Server licence removed)", len(off_windows), ", ".join(off_windows) or "-"),
            ("Applications staying on Windows (licence retained: EC2 Windows licence-included or BYOL)", len(on_windows), ", ".join(on_windows) or "-"),
            ("Desktop clients (run on user machines; not a server licence)", len(desk), ", ".join(desk) or "-"),
            ("Database groups: selected target", len(dbs), "; ".join(f"{d['repo']}: {DB_LABEL.get(d.get('selected', d['recommended']), d['recommended'])}" for d in dbs) or "-")]
    return table(["Licensing effect", "Count", "Applications / databases"], rows) + \
        "\n\nCosts are not priced from code. Use the client's licence and utilisation data with an AWS Optimization and Licensing Assessment (OLA) or the AWS Pricing Calculator; record the figures in the cost narrative."


def b_appendix_packages(c):
    rows = []
    for r in c.repos:
        for p in c.scan[r].get("packages", []):
            rec = p.get("recommendation") or {}
            reco = (f"{rec['action']} {rec.get('version') or ''}".strip() + (" ⚠ " + "; ".join(rec["risks"]) if rec.get("risks") else "")) if rec else ""
            rows.append((p["id"], ", ".join(p["versions"]), p.get("latest", ""), p["status"], F.short(reco, 160), p.get("vulnerable", ""), F.short(p.get("note"), 140), F.short(p.get("replacement"), 100), len(p["projects"]), r))
    return ("Recommendation (online scan): **keep** the version in use when it runs on the target framework, has no advisories, is "
            "not deprecated and its licence has not changed; otherwise **upgrade** to the lowest version that fixes it (not "
            "automatically the latest), with the risks that brings (major version jump, licence change, Windows-only build).\n\n"
            + table(["Package", "Version(s)", "Latest", "Status", "Recommendation", "Advisories", "Note", "Replacement", "Projects", "Repository"], rows))


def b_appendix_winapi(c):
    rows = []
    for f in c.findings:
        if f["category"] in ("linux-readiness", "api-portability", "wcf-desktop", "web-platform"):
            for e in f.get("evidence", []):
                rows.append((f["ref"], f["rule"], f["title"], f"`{F.evidence_ref(e)}`", F.short(e.get("text"), 140)))
    return table(["Ref", "Rule", "API / technology", "Location", "Code"], rows)


def b_appendix_raw(c):
    rows = []
    for r in c.repos:
        rows += [(r, f"{OUT}/inventory/{r}.json", "inventory"), (r, f"{OUT}/findings/{r}.json", "all findings with evidence"), (r, f"{OUT}/scan/{r}.json", "scan facts, endpoints, connection strings, packages, tests")]
        if c.graph.get(r):
            rows.append((r, c.graph[r]["graph"], "graphify graph (query with `graphify query --graph …`)"))
    rows += [("estate", f"{OUT}/classification.json", "7R draft and decisions"), ("estate", f"{OUT}/estimate.json", "effort model output"),
             ("estate", f"{OUT}/report/findings.csv", "findings for spreadsheets")]
    return table(["Scope", "File", "Contents"], rows)


def b_appendix_sources(c):
    p = os.path.join(SKILL_DIR, "references", "sources.md")
    if not os.path.exists(p):
        return "_See the skill's references/sources.md._"
    text = open(p, encoding="utf-8").read()
    m = re.search(r"(?s)<!-- report:sources -->(.*?)<!-- /report:sources -->", text)
    return (m.group(1) if m else text).strip()


def b_appendix_projects(c):
    return b_projects(c)


BLOCKS = {"scenarios": b_scenarios, "db-inventory": b_db_inventory, "linux-readiness": b_linux_readiness, "linux-issues": b_linux_issues, "package-groups": b_package_groups, "third-party": b_third_party, "headline": b_headline, "key-risks": b_key_risks, "scope": b_scope, "method": b_method, "not-assessed": b_not_assessed, "inventory": b_inventory,
          "architecture-diagram": b_architecture_diagram, "graph-insights": b_graph_insights, "wiring": b_wiring, "project-deps": b_project_deps, "workflows": b_workflows, "db-dependents": b_db_dependents, "db-coupling": b_db_coupling, "optional": b_optional, "dependencies": b_dependencies, "network": b_network, "jobs": b_jobs, "methodology": b_methodology,
          "findings-summary": b_findings_summary, "findings-by-category": b_findings_by_category, "database": b_database, "app-plans": b_app_plans,
          "hybrid": b_hybrid, "estimate": b_estimate, "multipliers": b_multipliers, "timeline": b_timeline, "sprints": b_sprints, "assumptions": b_assumptions,
          "risks": b_risks, "open-questions": b_open_questions, "testing": b_testing, "merge": b_merge, "cost": b_cost,
          "appendix-packages": b_appendix_packages, "appendix-winapi": b_appendix_winapi, "appendix-raw": b_appendix_raw,
          "appendix-sources": b_appendix_sources, "appendix-projects": b_appendix_projects}


def pretty_tfm(t):
    m = re.match(r"^net(\d+)\.(\d+)$", t or "")
    if not m:
        return t or ""
    return f".NET {m.group(1)}" + (f".{m.group(2)}" if m.group(2) != "0" else "")


FINDING_REFS = {}
VALUES = {}
FTAG = re.compile(r"\{\{f:([\w.:\-]+)(?:@([^}]+))?\}\}")
VTAG = re.compile(r"\{\{v:([^}|]+)(?:\|(\w+))?\}\}")


def value_tag(m):
    """{{v:estimate.totals.likely_hours}} -> 370; {{v:path|len}} counts a list or dict; numbers keep a thousands separator."""
    cur = VALUES
    for part in m.group(1).strip().split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.lstrip("-").isdigit() and -len(cur) <= int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return f"**[value {m.group(1)} not found]**"
    if m.group(2) == "len":
        cur = len(cur) if isinstance(cur, (list, dict)) else cur
    if isinstance(cur, bool) or cur is None or isinstance(cur, (dict, list)):
        return f"**[value {m.group(1)} is not a number or text]**"
    if isinstance(cur, float):
        return f"{cur:,.1f}".rstrip("0").rstrip(".") if cur != int(cur) else f"{int(cur):,}"
    return f"{cur:,}" if isinstance(cur, int) else str(cur)


def tags(text):
    return VTAG.sub(value_tag, FTAG.sub(finding_tag, text))


def finding_tag(m):
    """{{f:RULE}} -> the current F-number(s) of that rule; {{f:RULE@text}} -> only those whose project / applications contain text."""
    rule, where = m.group(1).lower(), (m.group(2) or "").strip().lower()
    fs = FINDING_REFS.get(rule, [])
    if where:
        fs = [f for f in fs if where in (f.get("project") or "").lower() or any(where in a.lower() for a in f.get("apps") or [])]
    return ", ".join(f["ref"] for f in fs) if fs else f"**[finding {m.group(1)}{'@' + m.group(2) if m.group(2) else ''} not found]**"


def narrative(name):
    p = os.path.join(OUT, "narrative", f"{name}.md")
    if not os.path.exists(p):
        return f"_Narrative '{name}' not written yet._"
    t = open(p, encoding="utf-8").read()
    t = re.sub(r"(?s)<!--.*?-->", "", t).strip()
    t = re.sub(r"^#\s.*\n", "", t)  # the template supplies the heading
    t = tags(t)
    return t or f"_Narrative '{name}' not written yet._"


def exports(c, rdir):
    os.makedirs(rdir, exist_ok=True)
    with open(os.path.join(rdir, "findings.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["ref", "id", "repo", "applications", "project", "category", "rule", "title", "severity", "confidence", "occurrences", "evidence", "why", "fix", "alternative", "question", "review_verdict", "review_note"])
        for f in c.findings:
            w.writerow([f["ref"], f["id"], f["repo"], "; ".join(c.apps[a]["name"] for a in f.get("apps", []) if a in c.apps), f.get("project"), f["category"], f["rule"], f["title"],
                        f["severity"], f["confidence"], f.get("occurrences"), " ; ".join(F.evidence_ref(e) for e in f.get("evidence", [])), f.get("why"), f.get("fix"), f.get("alt"),
                        f.get("question") or "", (f.get("review") or {}).get("verdict", ""), (f.get("review") or {}).get("note", "")])
    json.dump(c.findings, open(os.path.join(rdir, "findings.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    with open(os.path.join(rdir, "applications.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "name", "repo", "type", "framework", "loc", "r7", "target", "risk", "confidence", "effort_low", "effort_high", "effort_likely", "complexity", "decision_source"])
        for a in c.cls["applications"]:
            wp = c.wp.get(a["id"], {})
            w.writerow([a["id"], a["name"], a["repo"], a["type"], ", ".join(a.get("target_frameworks", [])), a["loc"], a["r7"], a["target"], a["risk"], a.get("confidence"),
                        (wp.get("total_days") or ["", ""])[0], (wp.get("total_days") or ["", ""])[1], wp.get("likely_days", ""), wp.get("complexity", ""), a.get("decision_source")])
    with open(os.path.join(rdir, "packages.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["repo", "package", "versions", "latest", "status", "severity", "vulnerable", "note", "replacement", "projects",
                    "recommendation", "recommended_version", "recommendation_why", "risks"])
        for r in c.repos:
            for p in c.scan[r].get("packages", []):
                rec = p.get("recommendation") or {}
                w.writerow([r, p["id"], "; ".join(p["versions"]), p.get("latest", ""), p["status"], p["severity"], p.get("vulnerable", ""), p.get("note"), p.get("replacement"), "; ".join(p["projects"]),
                            rec.get("action", ""), rec.get("version") or "", rec.get("why", ""), "; ".join(rec.get("risks", []))])
    with open(os.path.join(rdir, "open-questions.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["#", "area", "question", "raised_by", "answer"])
        for i, (a, q, r) in enumerate(open_questions(c), 1):
            w.writerow([i, a, q, r, ""])
    nw = A.network(c)
    with open(os.path.join(rdir, "network-allowlist.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["direction", "repo", "host_or_application", "port", "protocol", "kind", "applications", "defined_in", "evidence", "needed_on_aws", "role"])
        for x in nw["outbound"]:
            w.writerow(["outbound", x["repo"], x["host"], x["port"], x["protocol"], x["kind"], x["applications"], x["defined"].replace("`", ""), x["evidence"], x["needs"], x["role"]])
        for x in nw["inbound"]:
            w.writerow(["inbound", x["repo"], x["application"], x["port"], x["protocol"], "listener", x["application"], x["source"], x["evidence"], "", "Inbound listener"])
    with open(os.path.join(rdir, "scheduled-jobs.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["repo", "job", "scheduler", "schedule", "runs", "configured_by", "application", "windows_only", "on_aws", "evidence"])
        for j in A.jobs(c)["jobs"]:
            w.writerow([j["repo"], j["name"], j["scheduler"], j["schedule"], j["target"], j["configured_by"].replace("`", ""), j["application"],
                        "yes" if j["windows_only"] else "no", j["aws"], f"{j['file']}:{j['line']}"])
    with open(os.path.join(rdir, "endpoints.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["repo", "host", "kind", "schemes", "occurrences", "files"])
        for r in c.repos:
            for e in c.scan[r].get("endpoints", []):
                w.writerow([r, e["host"], e["kind"], "; ".join(e["schemes"]), e["occurrences"], "; ".join(e["files"][:20])])


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default=os.path.join(SKILL_DIR, "references", "report-template.md"))
    ap.add_argument("--out")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    c = Ctx(root, cfg)
    ndir, tdir = os.path.join(OUT, "narrative"), os.path.join(SKILL_DIR, "templates", "narrative")
    os.makedirs(ndir, exist_ok=True)
    for fn in os.listdir(tdir):  # narratives added to the skill after the workspace was created
        if fn.endswith(".md") and not os.path.exists(os.path.join(ndir, fn)):
            shutil.copy2(os.path.join(tdir, fn), os.path.join(ndir, fn))
            print(f"new narrative stub: {fn} (write it, then rebuild)")
    tpl = open(a.template, encoding="utf-8").read()
    tpl = re.sub(r"(?s)<!--\s*guide:.*?-->\s*", "", tpl)  # template guidance never reaches the client
    meta = {"client": cfg.get("client") or "Client", "prepared_by": cfg.get("prepared_by", ""), "engagement": cfg.get("engagement"),
            "date": datetime.date.today().isoformat(), "target": pretty_tfm(cfg.get("target_dotnet", "net10.0")), "compliance": ", ".join(cfg.get("compliance") or []) or "not stated",
            "hosting": cfg.get("current_hosting") or "not stated", "version": "1.0", "repos": str(len(c.repos))}

    def sub(m):
        kind, name = m.group(1), m.group(2)
        if kind == "meta":
            return str(meta.get(name, ""))
        if kind == "narrative":
            return narrative(name)
        fn = BLOCKS.get(name)
        return fn(c) if fn else f"_Unknown block {name}._"
    report = re.sub(r"\{\{(meta|block|narrative):([\w-]+)\}\}", sub, tpl)
    rdir = os.path.join(OUT, "report")
    name = a.out or f"{slug(meta['client']).title().replace('-', '')}-AWS-Migration-Assessment.md"
    report = tags(report)  # tags in decisions / reviews too
    write_text(os.path.join(rdir, name), report)
    exports(c, rdir)
    mark_step(root, "report")
    print(f"report: {OUT}/report/{name} ({len(report.splitlines())} lines); exports: findings.csv/json, applications.csv, packages.csv, open-questions.csv, endpoints.csv, network-allowlist.csv, scheduled-jobs.csv")


if __name__ == "__main__":
    main()
