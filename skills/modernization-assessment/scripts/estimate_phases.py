"""Phased bottom-up modernization estimate per repository, in developer working hours (AI-assisted, tool-run).

    py -X utf8 estimate_phases.py [--repo X | --all] [--compare '{"label": [low, high]}']

Run after effort_facts.py. Operating model: tool-run, no hand-coding. One porting engine per repository (AWS Transform
for .NET, or the AWS DevTx Version Upgrade Toolkit) does the .NET 10 port; Claude with the dotnet-modernization skill
carries out every remediation pattern the engine leaves and the AWS managed-service swaps, as reviewed batches; the DB
porting agent (or Claude with the DB porting skills) adds the PostgreSQL path beside SQL Server in the data-access layer.
The hours are engineer time to run the tools, approve plans, review pull requests, fix what the gates reject, decide
designs and sign off. Planning grade: +-25%. Buffer 15% on the subtotal by default.

Every line = quantity from the code (assessment/effort/<repo>/facts.json) x a rate range per unit (+ a fixed part).
Rates live in RATES below, each with the basis it was set from. Per-repository assumptions live in
assessment/effort/<repo>/estimate-inputs.json: written on the first run with every value this skill can read from
the code (ambient-context uses, configuration reads, SQL connections), the 7R per project from classification.json,
the intake answers (environments, AWS managed services) and defaults marked ASSUMED or UNKNOWN; the user edits it and
re-runs. Every assumption is printed in the output. Stage S (server-hosted services to AWS managed services) comes
from effort_facts.py's aws-native.json.

Writes assessment/effort/<repo>/estimate.json and estimate.md (+ .html), and assessment/effort/estimate-phases.json
(every repository: phases, totals, calendar) for build_summary.py.
"""
import argparse
import json
import os
import re
import sys

from _common import OUT, load_config, load_state, read_json, utf8_stdout, write_json
from _mdhtml import write_pair

# rate per unit (low, high) hours. Basis: a reference modernization plan priced item by item for a tool-run port of a
# comparable .NET Framework web estate (B1 build 16-32, B2 parity 24-40 for 14 request templates, B3 engine runs +
# review 24-40, B7 middleware/config/containers 24-48, B8 canary 24-40 for 3 environments, A1 provider swap 40-64,
# A2 inline SQL 32-56 for about 1,000 candidates, A3 procedure re-pointing 24-40, A5 shim 16-32, A8 cross-database
# 24-40, A9 re-points 12-24 for 6 waves), scaled to this repository's quantities; data/estimation.json per-occurrence
# rates for findings.
RATES = {
    "solution_build": (6, 10), "project_sdk": (1, 2), "package": (0.1, 0.2), "binary_ref": (0.5, 1.5),
    "parity_base": (8, 12), "request_type": (0.5, 1.0), "page_smoke": (0.5, 1.0),
    "transform_project": (4, 8), "review_kloc": (0.5, 1.0),
    "handler": (6, 10), "asmx_svc": (4, 8), "response_end": (0.25, 0.5), "windows_auth": (2, 4),
    "ambient_base": (6, 10), "ambient_use": (0.05, 0.1),
    "soap_reference": (3, 5), "soap_op": (0.75, 1.5), "webapi_op": (0.25, 0.5), "load_balancer": (4, 8), "webrequest": (0.5, 1.0),
    "config_read": (0.1, 0.2), "custom_section": (1, 2), "protected_config": (3, 6), "external_config": (0.5, 1.0),
    "pkg_remove": (0.1, 0.25), "pkg_windows_only": (1, 3), "pkg_unmaintained": (1, 3), "pkg_major": (1, 2), "lib_remove": (2, 4),
    "page": (4, 7), "user_control": (2, 4), "master": (2, 4), "control_toolkit": (2, 4),
    "containerise": (4, 7), "health": (1, 2), "canary_env_deployable": (2, 4),
    "sqlclient_file": (1.5, 3), "sql_objects_50": (1, 2),
    "stmt_auto": (0.25, 0.5), "stmt_rewrite": (1, 2), "stmt_redesign": (2, 4), "stmt_unparsed": (1, 2), "stmt_dynamic": (1, 1),
    "proc": (0.4, 0.8), "call_site": (0.1, 0.2), "multi_result": (2, 4),
    "shim_base": (4, 8), "sql_error_number": (0.5, 1.0), "output_param_proc": (0.5, 1.0), "tvp_proc": (2, 4),
    "for_xml_proc": (3, 6), "cross_db": (2, 4), "cross_db_base": (2, 2), "repoint": (0.5, 1.0), "db_parity_proc": (0.25, 0.5),
    # DB porting agent (dual database): engineer time per run and per item of its DB contract / report. INFERRED until
    # a measured run on the estate: calibrate after the first one.
    "dbagent_run": (4, 8), "dbagent_proc_review": (0.15, 0.3), "dbagent_stmt_review": (0.25, 0.5), "dbagent_open_items": (4, 10),
}
# Who does each work item. One porting engine per project (estimate-inputs.json "port_engine": "devtx" = AWS's Version
# Upgrade Toolkit: Upgrade Assistant + Kiro CLI with its 28-file .NET knowledge base, iterated to a green build; or
# "aws-transform" = AWS Transform for .NET), never both. What that engine does not cover goes to Claude with the
# dotnet-modernization skill as clean-up after the engine's run. One database tool ("db_tool": "db-agent" = the DB
# porting agent, or "claude" = Claude with the DB porting skills when the agent is not approved or the repository is
# too complex for it). The rates are the same whichever engine runs: they are engineer time to run, review and fix.
ENGINES = {"devtx": "AWS DevTx Version Upgrade Toolkit", "aws-transform": "AWS Transform for .NET"}
ENGINE_COVERS = {  # work items the engine's own run carries out (the rest of stage B is Claude clean-up)
    "devtx": {"B1", "B3", "B5", "B9", "B10", "B11"},  # KB 01/27, 06, 28 (CallContext), 25/26 (Web Forms), 19 (containers)
    "aws-transform": {"B1", "B3", "B9", "B10"},       # projects, packages, Web Forms -> Blazor; CallContext / containers left
}
DB_TOOLS = {"db-agent": "the DB porting agent", "claude": "Claude with the DB porting skills"}


def db_tool(inp):
    v = inp.get("db_tool", {}).get("value", "db-agent")
    return v if v in DB_TOOLS else "db-agent"
FIXED_OWNER = {"B2": "Claude", "B12": "Engineers + DevOps", "A8": "Engineers (design)", "A9": "DevOps (configuration)",
               "A10": "Engineers (PostgreSQL test environment)"}
PHASES = [  # (id, title, who, items): the readable view; the detail table keeps every line item
    ("P1", "Prepare: baseline build, golden request/response files, page smoke tests", "claude", ["B2"]),
    ("P2", "Port to .NET 10 with the engine", "engine", None),
    ("P3", "Clean-up of what the engine leaves", "claude", None),
    ("P4", "Data access: PostgreSQL path beside SQL Server", "db", ["A1", "A2", "A3", "A4", "A5", "A5b", "A8"]),
    ("P5", "Server-hosted services to AWS managed services", "claude", "S"),
    ("P6", "Verify and cut over: data-access parity, connection re-points, canary per environment", "people", ["A10", "A9", "B12"]),
]


def owner(iid, stage, inp):
    eng = inp.get("port_engine", {}).get("value", "devtx")
    if iid in FIXED_OWNER:
        return FIXED_OWNER[iid]
    if stage == "A":
        return DB_TOOLS[db_tool(inp)]
    if stage == "S":
        return "Claude (clean-up)"
    return ENGINES[eng] if iid in ENGINE_COVERS[eng] else f"Claude (clean-up after {ENGINES[eng]})"


def phases(I, inp):
    eng = inp.get("port_engine", {}).get("value", "devtx")
    out = []
    for pid, title, who, ids in PHASES:
        if ids is None:
            cov = ENGINE_COVERS[eng]
            ids = [x["id"] for x in I if x["stage"] == "B" and x["id"] not in FIXED_OWNER and ((x["id"] in cov) == (pid == "P2"))]
        elif ids == "S":
            ids = [x["id"] for x in I if x["stage"] == "S"]
        its = [x for x in I if x["id"] in ids]
        if not its:
            continue
        w = {"engine": ENGINES[eng], "claude": "Claude", "db": DB_TOOLS[db_tool(inp)],
             "people": "Engineers + DevOps"}[who]
        out.append({"id": pid, "title": title.replace("the engine", ENGINES[eng]) if pid == "P2" else title, "who": w, "items": [x["id"] for x in its],
                    "what": [short(x) for x in its], "low": round(sum(x["low"] for x in its), 1), "high": round(sum(x["high"] for x in its), 1)})
    return out


SHORT = {"B1": "SDK-style projects, Linux CI build", "B2": "parity harness", "B3": "engine runs + review", "B4": "HTTP handlers / ASMX entry points",
         "B5": "CallContext ambient context", "B6": "SOAP service clients", "B7": "Windows-only APIs", "B8": "config + secrets",
         "B9": "packages", "B10": "admin UI (Web Forms)", "B11": "Linux container + health check", "B12": "canary per environment",
         "A1": "tool run + plan approval", "A2": "raw SQL", "A3": "procedure contract", "A4": "multi-result sets", "A5": "open items, error numbers",
         "A5b": "FOR XML results", "A8": "cross-database names", "A9": "connection re-points", "A10": "data-access parity"}


def short(x):
    return SHORT.get(x["id"]) or re.split(r" \(|: | -> Amazon ", x["label"])[0]


# per-occurrence rates for Windows-only / hosting findings (rule -> rate)
FINDING_RATES = {
    "API-BINARYFORMATTER": (1, 2), "API-ENTERPRISESERVICES": (1, 2), "SEC-WEAK-CRYPTO": (0.5, 1),
    "TZ-WINDOWS-ID": (0.5, 1), "TZ-LOCAL-TIME": (0.1, 0.25), "HV-MACHINE-NAME": (0.25, 0.5), "FILE-BACKSLASH": (0.25, 0.5),
    "FILE-LOCAL-WRITE": (0.5, 1), "FILE-DRIVE-LETTER": (0.5, 1), "STATE-APP-CACHE": (0.25, 0.5), "LOG-FILE-TARGETS": (1, 2),
    "AUTH-DEFAULT-CREDENTIALS": (0.5, 1), "LS-CLIENT-IP-LOGIC": (1, 2), "LS-LOCALHOST-SERVICE": (0.25, 0.5),
    "API-REGISTRY": (1, 2), "API-EVENTLOG": (0.5, 1), "API-COM-INTEROP": (4, 8), "API-PINVOKE": (2, 4), "API-SYSTEM-DRAWING": (1, 3),
}
SEV = ["Blocker", "High", "Medium", "Low", "Info"]


def occ(facts, rule, projects=None):
    return sum(f["occurrences"] or 0 for f in facts["findings"] if f["rule"] == rule and (projects is None or f["project"] in projects))


def line(items, stage, iid, label, parts, basis, status="VERIFIED", note="", tool=None):
    """parts: [(quantity, unit, rate key or (low, high))]; quantity 0 parts are dropped."""
    lo = hi = 0.0
    drivers = []
    for q, unit, rate in parts:
        if not q:
            continue
        r = RATES[rate] if isinstance(rate, str) else rate
        lo += q * r[0]
        hi += q * r[1]
        drivers.append(f"{q:g} {unit} x {r[0]:g}-{r[1]:g} h")
    items.append({"stage": stage, "id": iid, "label": label, "low": round(lo, 1), "high": round(hi, 1), "drivers": drivers,
                  "basis": basis, "status": status, "note": note, "tool": tool})


def build(f, inp):
    """Work items for one repository under one set of assumptions."""
    envs = inp["environments"]["value"]
    retired = set(inp.get("retire_projects", {}).get("value", []))
    ui_retired = inp.get("admin_ui", {}).get("value") == "retire"
    keep = [p for p in f["projects"] if p["path"] not in retired]
    deployables = [p for p in keep if p.get("deployable")]
    sq = f["sql"]["summary"]
    spx, raw, api = sq["stored_procedures"], sq["raw_sql"], sq["data_access_api"]
    web = {k: v for k, v in f["web"].items() if k not in retired}
    I = []

    # ---------------- Stage B: port to .NET 10 on Linux containers
    bins = {b["assembly"] for b in f["binary_references"] if b["project"] not in retired}
    line(I, "B", "B1", "Build + pipeline: SDK-style projects, PackageReference, Library references, Linux CI build",
         [(len(f["solutions"]), "solution", "solution_build"), (sum(1 for p in keep if not p["sdk_style"]), "legacy project files", "project_sdk"),
          (len(f["packages"]), "NuGet packages", "package"), (len(bins), "binary (non-NuGet) references", "binary_ref")],
         "reference plan B1 16-32 h (one web solution, agent-scaffolded)")
    pages = sum(len([x for x in w["pages"] if not os.path.basename(x["file"]).lower().startswith("test")]) for w in web.values())
    line(I, "B", "B2", "Parity harness: golden request/response files per API request type, page smoke tests",
         [(1, "harness", "parity_base"), (len(f["contracts"]["request_types"]) + len(f["contracts"]["controllers"]), "request types / controllers", "request_type"),
          (0 if ui_retired else pages, "admin pages", "page_smoke")],
         "reference plan B2 24-40 h for 14 templates; automated tests counted in facts.json", "INFERRED")
    kloc = sum((p["loc_handwritten"] or 0) + (p["loc_markup"] or 0) for p in keep) / 1000
    line(I, "B", "B3", "Porting engine runs + review of the ported branch",
         [(len(keep), "projects", "transform_project"), (round(kloc, 1), "KLOC hand-written + markup reviewed", "review_kloc")],
         "reference plan B3 24-40 h")
    handlers = sum(w["totals"]["handlers"] for w in web.values())
    line(I, "B", "B4", "HTTP entry points to ASP.NET Core (handlers, ASMX / WCF services, Response.End, Windows auth)",
         [(handlers, "HTTP handlers", "handler"), (sum(w["totals"]["asmx"] + w["totals"]["svc"] for w in web.values()), "ASMX / .svc services", "asmx_svc"),
          (occ(f, "WEB-RESPONSE-END", [p["path"] for p in keep if f["web"].get(p["path"], {}).get("totals", {}).get("pages", 0) <= 1]), "Response.End / Transfer outside pages", "response_end"),
          (occ(f, "AUTH-WINDOWS"), "Windows-auth configs", "windows_auth")],
         "INFERRED from the handler census; Transform does not port IHttpAsyncHandler plumbing by itself")
    amb = inp.get("ambient_context_uses", {}).get("value", 0)
    line(I, "B", "B5", "Ambient request context (CallContext / HttpContext.Current) to AsyncLocal / HttpContext",
         [(1 if amb else 0, "context class", "ambient_base"), (amb, "uses", "ambient_use"),
          (occ(f, "WEB-HTTPCONTEXT-CURRENT"), "HttpContext.Current", (0.25, 0.5))],
         "INFERRED; .NET Remoting CallContext.HostContext does not exist on .NET 10")
    refs = [r for r in f["service_references"]]
    called = sum(len(r.get("operations_called") or {}) for r in refs)
    on_webapi = inp.get("soap_operations_with_webapi", {}).get("value", 0)
    line(I, "B", "B6", "Service clients: SOAP references regenerated / moved to Web API, client-side load balancer replaced",
         [(len(refs), "SOAP / WCF references", "soap_reference"), (called - on_webapi, "SOAP-only operations called", "soap_op"),
          (on_webapi, "operations already on Web API (verify)", "webapi_op"),
          (1 if any(re.search(r"(?i)load\.?balanc", b) for b in bins) else 0, "client-side load balancer", "load_balancer"),
          (occ(f, "API-WEBREQUEST"), "WebRequest / WebClient", "webrequest")],
         "INFERRED; dotnet-svcutil (System.ServiceModel.Http) or the existing WS Web API",
         "INFERRED" if not inp.get("soap_fallback", {}).get("answered") else "VERIFIED", inp.get("soap_fallback", {}).get("note", ""))
    parts = []
    for rule, rate in FINDING_RATES.items():
        n = occ(f, rule, [p["path"] for p in keep])
        if n:
            parts.append((n, rule, rate))
    line(I, "B", "B7", "Windows-only APIs and hosting assumptions (formatters, COM+, crypto, time zones, paths, machine name, caches)",
         parts, "modernization-assessment per-occurrence rates; time zones: containers run UTC")
    cfg = [c for c in f["config"] if not c["transform"]]
    sections = {s for c in cfg for s in c["custom_sections"]}
    line(I, "B", "B8", "Configuration + secrets: web.config to appsettings / env / Secrets Manager, protected sections, custom sections",
         [(inp.get("config_reads", {}).get("value", 0), "ConfigurationManager reads", "config_read"), (len(sections), "custom config sections", "custom_section"),
          (sum(1 for c in cfg if c["protected_sections"]), "configs with protected sections", "protected_config"),
          (len({x for c in cfg for x in c["config_source_files"]}) + sum(1 for c in cfg if any("log4net" in x for x in c["config_source_files"])), "external config files", "external_config")],
         "reference plan B7 24-48 h (middleware / config / containerisation together)")
    pk = f["packages"]
    aws = f.get("_aws_native") or {}
    in_s = {p.lower() for s in aws.get("services", []) for p in s["packages"]} if inp.get("aws_native", {}).get("value") else set()
    risk = [x for x in f["findings"] if x["rule"].startswith("PKG-RISK-") and x["rule"][9:].lower() not in in_s]  # Stage S covers the rest
    libs_removed = inp.get("libraries_removed", {}).get("value", [])
    line(I, "B", "B9", "Packages and libraries: remove polyfills, replace Windows-only / unmaintained, major upgrades, drop unused libraries",
         [(sum(1 for p in pk if p["status"] == "remove"), "polyfill packages", "pkg_remove"),
          (sum(1 for p in pk if p["status"] == "windows-only"), "Windows-only packages", "pkg_windows_only"),
          (len(risk), "unmaintained packages", "pkg_unmaintained"),
          (len(inp.get("major_upgrades", {}).get("value", [])), "major-version upgrades", "pkg_major"),
          (len(libs_removed), "libraries removed", "lib_remove")],
         "INFERRED from the package scan")
    adm = [(k, w) for k, w in web.items() if w["totals"]["pages"] > 1]
    if ui_retired:
        line(I, "B", "B10", "Admin Web Forms UI: retired (decision in estimate-inputs.json)", [], "client decision", "VERIFIED")
    else:
        line(I, "B", "B10", "Admin Web Forms UI to Razor Pages / Blazor (" + inp.get("admin_ui", {}).get("value", "port") + ")",
             [(sum(len([x for x in w["pages"] if not os.path.basename(x["file"]).lower().startswith("test")]) for k, w in adm), "pages", "page"),
              (sum(w["totals"]["user_controls"] for k, w in adm), "user controls", "user_control"),
              (sum(w["totals"]["masters"] for k, w in adm), "master pages", "master"),
              (1 if any("AjaxControlToolkit" == b["assembly"] for b in f["binary_references"]) else 0, "third-party control library", "control_toolkit")],
             "INFERRED; no public per-page Web Forms port data; the reference plan priced 14 pages through the engine + agent specs", "INFERRED")
    line(I, "B", "B11", "Containerise: Linux image per deployable, health endpoint, stdout logging, task definition inputs",
         [(len(deployables), "deployables", "containerise"), (len(deployables) if any(x["rule"] == "LOG-NO-HEALTHCHECK" for x in f["findings"]) else 0, "health endpoints", "health")],
         "3-6 h per deployable plus health check (earlier calibrated draft)")
    line(I, "B", "B12", "Canary / cutover support",
         [(len(deployables) * envs, f"deployable x environment ({len(deployables)} x {envs})", "canary_env_deployable")],
         "reference plan B8 24-40 h for 3 environments", inp["environments"].get("status", "UNKNOWN"))

    # ---------------- Stage A: SQL Server -> PostgreSQL, application side
    st = f["sql"]["statements"]
    if not inp.get("database_port", {}).get("value", True):
        pass  # no PostgreSQL path in scope (assessment scenario database = none): stage A is not priced
    elif db_tool(inp) == "db-agent":
        line(I, "A", "A1", "DB porting agent run: analyse, approve the plan, execute (seams, Sql/PostgreSql resources, DB contract), build + checklist, review the pull request",
             [(1, "run", "dbagent_run")], "the agent's own phases: human approval gate, real build, self-repair", "INFERRED", tool="DB porting agent")
        line(I, "A", "A2", "Review the agent's raw-SQL conversions; redesign statements stay with an engineer",
             [(sum(1 for s in st if not (s["conversion"] or {}).get("redesign")), "statements", "dbagent_stmt_review"),
              (sum(1 for s in st if (s["conversion"] or {}).get("redesign")), "statements (redesign)", "stmt_redesign"),
              (sum(1 for s in st if s["dynamic"]), "statements built at run time", "stmt_dynamic")], "INFERRED", "VERIFIED", tool="DB porting agent + engineer review")
        line(I, "A", "A3", "Check the DB contract per procedure (PostgreSQL name, call form, argument order) against the DB team's conversion",
             [(spx["distinct"], "procedures", "dbagent_proc_review")], "the agent writes the contract and lints the code against it", tool="DB porting agent + engineer review")
        line(I, "A", "A4", "Multi-result-set remediation", [(spx["multi_result"], "procedures", "multi_result")], "reference plan A4", tool="DB porting agent")
        line(I, "A", "A5", "Open items from the agent's checklist and report; SQL Server error-number logic",
             [(1, "run", "dbagent_open_items"), (api.get("SqlException.Number (error-number logic)", {}).get("hits", 0), "SqlException.Number sites", "sql_error_number"),
              (spx["with_output_params"], "procedures with OUTPUT params", "output_param_proc"), (spx["with_tvp"], "procedures with table-valued params", "tvp_proc")],
             "INFERRED", tool="Engineers")
    else:
        line(I, "A", "A1", "Provider swap SqlClient -> Npgsql (agent spec on the data-access layer)",
             [(api.get("System.Data.SqlClient using", {}).get("files", 0) + api.get("Microsoft.Data.SqlClient using", {}).get("files", 0), "files importing SqlClient", "sqlclient_file"),
              (round(api.get("Sql* types (new SqlConnection/Command/Parameter/DataAdapter)", {}).get("hits", 0) / 50, 1), "x50 Sql* object creations", "sql_objects_50")],
             "reference plan A1 40-64 h for a corpus of about 10,000 data-access findings")
        line(I, "A", "A2", "Raw SQL to PostgreSQL dialect (and parameterise concatenated values)",
             [(sum(1 for s in st if s["parsed"] and not (s["conversion"] or {}).get("rewrite") and not (s["conversion"] or {}).get("redesign")), "statements (auto)", "stmt_auto"),
              (sum(1 for s in st if (s["conversion"] or {}).get("rewrite") and not (s["conversion"] or {}).get("redesign")), "statements (rewrite)", "stmt_rewrite"),
              (sum(1 for s in st if (s["conversion"] or {}).get("redesign")), "statements (redesign)", "stmt_redesign"),
              (sum(1 for s in st if not s["parsed"] and s.get("dialect", "").startswith("T-SQL")), "statements that did not parse", "stmt_unparsed"),
              (sum(1 for s in st if s["dynamic"]), "statements built at run time", "stmt_dynamic")],
             "reference plan A2 32-56 h for about 1,000 candidates")
        line(I, "A", "A3", "Stored-procedure invocation re-pointed (functions / CALL, parameter names and types, column-name casing)",
             [(spx["distinct"], "procedures", "proc"), (spx["call_sites"], "call sites", "call_site")],
             "reference plan A3 24-40 h; per procedure because each converted signature is checked")
        line(I, "A", "A4", "Multi-result-set remediation", [(spx["multi_result"], "procedures", "multi_result")], "reference plan A4")
        line(I, "A", "A5", "Behaviour shim: exceptions, types, date/time, collation",
             [(1, "review", "shim_base"), (api.get("SqlException.Number (error-number logic)", {}).get("hits", 0), "SqlException.Number sites", "sql_error_number"),
              (spx["with_output_params"], "procedures with OUTPUT params", "output_param_proc"), (spx["with_tvp"], "procedures with table-valued params", "tvp_proc")],
             "reference plan A5 16-32 h")
    if not inp.get("database_port", {}).get("value", True):
        return finish(I, f, inp)
    line(I, "A", "A5b", "FOR XML results (no PostgreSQL equivalent): application side of the redesign",
         [(spx["for_xml_readers"], "procedures read through ExecuteXmlReader", "for_xml_proc")],
         "INFERRED; approach depends on the DB team's conversion", "INFERRED")
    xdb = sq["constructs"].get("dynamic database name", 0) + sum(1 for p in f["sql"]["procedures"] if "{db}" in p["name"]) + \
        sum(1 for s in st if "cross-database" in (s["constructs"] or {}) and "dynamic database name" not in (s["constructs"] or {}))
    line(I, "A", "A8", "Cross-database references", [(1 if xdb else 0, "design", "cross_db_base"), (xdb, "statements / procedures", "cross_db")],
         "reference plan A8 24-40 h (estate-wide)", "VERIFIED" if not xdb else "INFERRED", "the target database grouping decides schema vs separate connection")
    line(I, "A", "A9", "Connection re-points per environment",
         [(inp.get("sql_connections", {}).get("value", 1) * envs, "connection x environment", "repoint")], "reference plan A9 12-24 h for 6 waves",
         inp["environments"].get("status", "UNKNOWN"))
    line(I, "A", "A10", "Data-access parity on PostgreSQL non-prod (read paths compared per procedure)",
         [(spx["distinct"], "procedures", "db_parity_proc")], "the reference plan gates parity; the DB porting agent runs no live database test", "INFERRED")

    return finish(I, f, inp)


def finish(I, f, inp):
    aws = f.get("_aws_native") or {}
    # ---------------- Stage S: server-hosted services to AWS managed services (aws-native.json from aws_native.py)
    if inp.get("aws_native", {}).get("value") and aws:
        choices = inp.get("aws_native_choices", {}).get("value", {})
        for n, svc in enumerate(aws["services"], 1):
            opt = next((o for o in svc["options"] if o["id"] == choices.get(svc["id"])), None) or next(o for o in svc["options"] if o["chosen"])
            ev = [f"{len(svc['provider_files'])} wrapper file(s) here" if svc["provider_files"] else "",
                  f"{svc['consumer_sites']} call sites" if svc["consumer_sites"] else "", f"{svc['config_entries']} config entries" if svc["config_entries"] else ""]
            line(I, "S", f"S{n}", f"{svc['label']} -> {opt['aws']} ({opt['change']})", [(1, "option", tuple(opt["hours"]))],
                 f"aws_native.py rates x AI factor ({opt['factor']}); wrapper: {svc['client_code']}", "VERIFIED", opt["work"])
            I[-1]["drivers"] = ["; ".join(x for x in ev if x) + f": manual-equivalent {opt['manual_hours'][0]:g}-{opt['manual_hours'][1]:g} h"]
    for x in I:
        x["tool"] = owner(x["id"], x["stage"], inp)
    return I


def profile(f, inp):
    """Application profile: projects with line counts and the 7R decision from estimate-inputs.json."""
    r7 = inp.get("r7", {}).get("value", {})
    L = ["## Application profile", "",
         "Lines are non-blank lines of code: hand-written C#/VB, markup (.aspx/.ascx/.master/.cshtml/.js) and generated "
         "(designer files, SOAP proxies), which the port regenerates rather than reviews. 7R decisions and the reasoning: "
         "estimate-inputs.json r7 (from classification.json), definitions in references/seven-rs.md.", "",
         "| Project | Type | Hand-written | Markup | Generated | Deployable | 7R | Why | Then |", "|---|---|---|---|---|---|---|---|---|"]
    for p in f["projects"]:
        d = r7.get(p["path"], {})
        L.append(f"| {p['path']} | {p['type']} | {p.get('loc_handwritten') or 0:,} | {p.get('loc_markup') or 0:,} | {p.get('loc_generated') or 0:,} | "
                 f"{'yes' if p.get('deployable') else 'no'} | {d.get('r', '-')} | {d.get('why', '')} | {d.get('then', '')} |")
    t = [sum(p.get(k) or 0 for p in f["projects"]) for k in ("loc_handwritten", "loc_markup", "loc_generated")]
    L.append(f"| **Total** | | **{t[0]:,}** | **{t[1]:,}** | **{t[2]:,}** | | | | |")
    return L


def hits(api, key):
    return api.get(key, {}).get("hits", 0)


def pg_considerations(f, inp):
    """What the SQL Server -> PostgreSQL move has to handle in this repository's code (the DB objects are the DB team's)."""
    sq = f["sql"]["summary"]
    spx, raw, api = sq["stored_procedures"], sq["raw_sql"], sq["data_access_api"]
    procs = f["sql"]["procedures"]
    readers = [p for p in procs if set(p.get("apis") or []) & {"ExecuteReader", "Fill", "DataAdapter", "ExecuteXmlReader", "SqlDataAdapter"}]
    rows = [
        ("Raw SQL statements in code (not in procedures)", raw["statements"], f"{raw['parsed']} parsed, {raw['dynamic']} built at run time, "
         f"{sq['conversion_levels'].get('rewrite', 0)} need a rewrite, {sq['conversion_levels'].get('redesign', 0)} a redesign; {raw['files']} files",
         "Dialect resource per database (Sql / PostgreSql resources); concatenated values become parameters"),
        ("Stored procedures called from code", spx["distinct"], f"{spx['call_sites']} call sites", "DB contract per procedure: PostgreSQL name, call form, argument order"),
        ("Procedures that return result sets (refcursor or set-returning function)", len(readers),
         ", ".join(p["name"] for p in readers[:6]) + (f" and {len(readers) - 6} more" if len(readers) > 6 else ""),
         "A PostgreSQL procedure cannot return rows: the DB team writes a function RETURNS TABLE / SETOF, or a procedure with an "
         "INOUT refcursor that the code FETCHes in the same transaction; the call form goes in the DB contract"),
        ("Procedures returning several result sets (NextResult / DataSet with several tables)", spx["multi_result"], "",
         "One refcursor per result set, fetched in one transaction, or one function per result set"),
        ("OUTPUT parameters / return values", spx["with_output_params"] + spx["with_return_value"], "",
         "INOUT parameters; a RETURN value becomes an OUT parameter or the function result"),
        ("Table-valued parameters (SqlDbType.Structured)", spx["with_tvp"], "", "Arrays or composite types (Npgsql maps both)"),
        ("FOR XML results read through ExecuteXmlReader", spx["for_xml_readers"], f"{api.get('ExecuteXmlReader (FOR XML)', {}).get('hits', 0)} reads",
         "No PostgreSQL equivalent: query_to_xml / xmlagg in the function, or build the XML in C#"),
        ("Cross-database (three-part) names", sq["constructs"].get("cross-database", 0), ", ".join(sq.get("databases_in_three_part_names") or []),
         "Schemas in one database, or a second connection; decided with the target database grouping"),
        ("SqlException.Number checks", api.get("SqlException.Number (error-number logic)", {}).get("hits", 0), "",
         "Map to PostgreSQL SQLSTATE codes (PostgresException.SqlState) on the PostgreSQL path"),
        ("Files using the SqlClient API", api.get("System.Data.SqlClient using", {}).get("files", 0) + api.get("Microsoft.Data.SqlClient using", {}).get("files", 0),
         f"{api.get('Sql* types (new SqlConnection/Command/Parameter/DataAdapter)', {}).get('hits', 0)} Sql* object creations",
         "Behind a provider seam: SqlClient for SQL Server, Npgsql for PostgreSQL"),
        ("SqlBulkCopy", hits(api, "SqlBulkCopy"), "", "Bulk-insert seam over COPY (binary); batch size, column mapping, identity and trigger options reproduced"),
        ("Transactions (SqlTransaction, BeginTransaction, TransactionScope)", hits(api, "SqlTransaction / BeginTransaction") + hits(api, "TransactionScope"), "",
         "An error aborts the whole PostgreSQL transaction (catch-and-continue needs a savepoint); retry on 40001 for RepeatableRead / "
         "Serializable; TransactionScope over two resources is restructured (no distributed transactions on Linux)"),
        ("SqlDependency / SqlFileStream", hits(api, "SqlDependency") + hits(api, "SqlFileStream"), "",
         "No equivalent: LISTEN/NOTIFY or polling; files to S3"),
        ("OLE DB / ODBC commands", hits(api, "OleDb / Odbc"), "", "Npgsql with named parameters (positional ? placeholders go)"),
        ("ORM in use (Dapper, EF6, EF Core)", hits(api, "Dapper") + hits(api, "Entity Framework 6") + hits(api, "EF Core"), "",
         "Npgsql provider; provider-specific migrations; xmin for row versions; raw SQL through the dialect resources"),
    ]
    L = ["## SQL Server -> PostgreSQL: what the code has to handle", "",
         "Counts from this repository's code. Database objects (procedure bodies, functions, views, triggers) are converted by the DB team; "
         "the code follows the DB contract agreed with them.", "",
         "| Item | Count | Detail | How it is handled |", "|---|---|---|---|"]
    for name, n, det, how in rows:
        L.append(f"| {name} | {n} | {det} | {how} |")
    L += ["", "Checked on every statement and procedure as well: identifier case (PostgreSQL folds unquoted names to lower case, so "
          "columns read by name must match), bit -> boolean, datetime -> timestamp, TOP -> LIMIT, ISNULL -> COALESCE, GETDATE() -> now(), "
          "+ string concatenation -> ||, @@IDENTITY / SCOPE_IDENTITY() -> RETURNING, NOLOCK hints, temp tables, transactions and isolation "
          "level, collation and case-insensitive comparisons, ExecuteScalar result types (bigint / numeric / bool), DateTime.Kind against "
          "timestamp / timestamptz and microsecond precision, NULL ordering, MERGE -> ON CONFLICT, IN lists -> = ANY(array). "
          "Full list: dotnet-modernization playbook raw-sql-and-data-access."]
    return L


def totals(I, inp):
    buf = inp.get("buffer", {}).get("value", 0.15)
    sub_lo, sub_hi = sum(x["low"] for x in I), sum(x["high"] for x in I)
    return sub_lo, sub_hi, buf, sub_lo * (1 + buf), sub_hi * (1 + buf)


def occ_rules(f, pattern):
    return sum(x["occurrences"] or 0 for x in f["findings"] if re.search(pattern, x["rule"]))


def inputs_for(repo, f, cfg, d):
    """estimate-inputs.json for one repository: kept as the user edited it; missing keys are added with what the code
    shows (VERIFIED), the intake answers, the 7R from classification.json, or a default marked ASSUMED / UNKNOWN."""
    p = os.path.join(d, "estimate-inputs.json")
    inp = read_json(p, {}) or {}
    intake = cfg.get("intake") or {}
    envs = intake.get("environments")
    n_env = len([e for e in re.split(r"[,;]", envs) if e.strip()]) if isinstance(envs, str) and envs.strip() and envs != "unknown" else (
        envs if isinstance(envs, int) else None)
    cls = read_json(os.path.join(OUT, "classification.json"), {}) or {}
    r7 = {}
    apps = [a for a in cls.get("applications", []) if a.get("repo") == repo]
    for primary in (True, False):  # an application's own project first; a project it only references keeps its owner's 7R
        for app in apps:
            for pr in (app.get("projects") or [])[:1] if primary else (app.get("projects") or [])[1:]:
                if pr not in r7:
                    r7[pr] = {"r": app.get("r7"), "why": " ".join(app.get("rationale") or [])[:300], "then": app.get("target", "")}
    plan = read_json(os.path.join(OUT, "execution-plan.json"), {}) or {}
    engine = next((x.get("engine") for x in plan.get("repos", plan.get("repositories", [])) if isinstance(x, dict) and x.get("repo") == repo), None)
    amb = (f.get("code_usage") or {}).get("ambient_context") or {}
    cr = (f.get("code_usage") or {}).get("config_reads") or {}
    aws = read_json(os.path.join(d, "aws-native.json"), {}) or {}
    svc_pkgs = [re.escape(p) for s in aws.get("services", []) for p in s.get("packages", [])] + [
        s["detect"]["packages"] for s in (read_json(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "aws_native.json"), {}) or {}).get("services", [])
        if s.get("detect", {}).get("packages")]
    sqlcs = {c.get("name") for c in f.get("connection_strings", []) if not re.search(r"(?i)mongo|redis", (c.get("name") or "") + (c.get("host") or ""))}
    dbs = (cfg.get("scenario") or {}).get("database", "dual")
    defaults = {
        "environments": {"value": n_env or 3, "status": "VERIFIED" if n_env else "UNKNOWN",
                         "question": "How many environments does each application run in (dev, staging, prod assumed)?",
                         "note": "From the intake answers." if n_env else "Assumed dev, staging, prod: ask the client."},
        "admin_ui": {"value": "port", "status": "UNKNOWN" if any(w["totals"]["pages"] > 1 for w in f.get("web", {}).values()) else "VERIFIED",
                     "note": "Port the Web Forms admin pages (Blazor / Razor Pages) or retire them? Set \"retire\" to drop item B10.",
                     "question": "Port the Web Forms admin pages (Blazor / Razor Pages), or retire them?"},
        "retire_projects": {"value": [], "status": "UNKNOWN", "note": "Project paths to leave out entirely.",
                            "question": "Is any project in this repository retired instead of ported?"},
        "ambient_context_uses": {"value": amb.get("uses", occ_rules(f, r"CALLCONTEXT|AMBIENT")), "status": "VERIFIED",
                                 "note": f"CallContext and {', '.join(amb.get('wrapper_classes') or []) or 'no wrapper class'}.Current uses in {amb.get('files', '?')} files."},
        "soap_operations_with_webapi": {"value": 0, "status": "ASSUMED", "note": "SOAP operations already reachable through a Web API: set when known."},
        "soap_fallback": {"answered": False, "status": "UNKNOWN" if f.get("service_references") else "VERIFIED",
                          "note": "Can SOAP-only operations move to an existing Web API instead of a regenerated client?",
                          "question": "Can the SOAP-only operations move to an existing Web API instead of a regenerated SOAP client?"},
        "config_reads": {"value": cr.get("reads", occ_rules(f, r"^API-CONFIGMANAGER$|^LNX-CFG-CONFIGMANAGER$")), "status": "VERIFIED",
                         "note": f"ConfigurationManager reads in {cr.get('files', '?')} files."},
        "libraries_removed": {"value": [], "status": "ASSUMED", "note": "Libraries dropped instead of ported."},
        "major_upgrades": {"value": sorted({b["assembly"] for b in f.get("binary_references", []) if "PackageReference" in (b.get("action") or "")
                                            and not any(re.match(rx, b["assembly"], re.I) for rx in svc_pkgs)}),
                           "status": "INFERRED", "note": "DLLs that become a current nuget.org package (the scan's DLL table); clients of server-hosted services are priced in stage S."},
        "sql_connections": {"value": max(1, len(sqlcs)), "status": "VERIFIED" if sqlcs else "ASSUMED", "note": "Distinct SQL connection-string names in config."},
        "excluded": {"value": "Database-side object conversion (DB team), data migration, AWS resources and networking (DevOps)", "status": "INFERRED", "note": ""},
        "buffer": {"value": 0.15, "status": "INFERRED", "note": "Planning buffer on the subtotal."},
        "hours_per_day": {"value": 6, "status": "INFERRED", "note": "Focused hours a day."},
        "team": {"value": [1, 2], "status": "INFERRED", "note": "Calendar shown for 1 and 2 developers."},
        "port_engine": {"value": engine if engine in ENGINES else "devtx", "status": "VERIFIED" if engine in ENGINES else "UNKNOWN",
                        "note": "One porting engine per repository: \"devtx\" or \"aws-transform\" (plan_execution.py decides); same hours either way.",
                        "question": "Which porting engine: AWS Transform for .NET or the AWS DevTx Version Upgrade Toolkit? (same hours either way)"},
        "db_tool": {"value": "db-agent", "status": "INFERRED", "note": "\"db-agent\" (the DB porting agent) or \"claude\" (Claude with the DB porting skills)."},
        "database_port": {"value": dbs != "none", "status": "VERIFIED", "note": f"Assessment scenario database = {dbs}."},
        "aws_native": {"value": intake.get("aws_native", "later") == "now", "status": "VERIFIED" if intake.get("aws_native") else "UNKNOWN",
                       "note": "Intake: move server-hosted services to AWS managed services now (in the total) or later (listed, not in the total).",
                       "question": "Move the server-hosted services (caches, mail, logging, ...) to AWS managed services now (priced in) or later?"},
        "aws_native_choices": {"value": cfg.get("aws_native_choices") or {}, "status": "INFERRED", "note": "Per service the first option of data/aws_native.json unless chosen here."},
        "r7": {"value": r7, "status": "INFERRED", "note": "From classification.json (decisions.json overrides)."},
        "scenarios": {"value": {}, "status": "INFERRED", "note": "What-ifs: {name: {question, set: {key: value}, add: [{id, label, low, high}]}}."},
    }
    changed = False
    for k, v in defaults.items():
        if k not in inp:
            inp[k] = v
            changed = True
        elif k == "r7" and not inp[k].get("value"):
            inp[k] = v
            changed = True
    if inp.get("db_tool", {}).get("value") not in DB_TOOLS:  # a tool name this version does not know
        inp["db_tool"]["value"] = "db-agent"
        changed = True
    if changed or not os.path.exists(p):
        write_json(p, inp)
    return inp


def estimate_repo(repo, cfg, a):
    d = os.path.join(OUT, "effort", repo)
    f = read_json(os.path.join(d, "facts.json"))
    if not f:
        print(f"{repo}: no facts.json: run effort_facts.py first")
        return None
    inp = inputs_for(repo, f, cfg, d)
    f["_aws_native"] = read_json(os.path.join(d, "aws-native.json"))
    a.out = d
    I = build(f, inp)
    sub_lo, sub_hi, buf, tot_lo, tot_hi = totals(I, inp)
    # scenarios: the same estimate with some assumptions changed (the open client questions)
    scen = []
    for name, sc in inp.get("scenarios", {}).get("value", {}).items():
        alt = json.loads(json.dumps(inp))
        for k, v in sc.get("set", {}).items():
            alt.setdefault(k, {})["value"] = v
        J = build(f, alt)
        for x in sc.get("add", []):
            J.append({"stage": x.get("stage", "B"), "id": x["id"], "label": x["label"], "low": x["low"], "high": x["high"],
                      "drivers": [], "basis": "scenario", "status": "INFERRED", "note": ""})
        t = totals(J, alt)
        scen.append({"name": name, "question": sc.get("question", ""), "total": [round(t[3]), round(t[4])],
                     "delta": [round(t[3] - tot_lo), round(t[4] - tot_hi)]})
    stages = {s: (sum(x["low"] for x in I if x["stage"] == s), sum(x["high"] for x in I if x["stage"] == s)) for s in ("A", "B", "S")}
    hpd = inp.get("hours_per_day", {}).get("value", 6)
    res = {"repo": f["repo"], "items": I, "stages": stages, "subtotal": [round(sub_lo), round(sub_hi)], "buffer": buf,
           "total": [round(tot_lo), round(tot_hi)], "dev_days": [round(tot_lo / hpd), round(tot_hi / hpd)], "hours_per_day": hpd,
           "inputs": inp, "rates": RATES, "finding_rates": FINDING_RATES, "scenarios": scen}
    team = inp.get("team", {}).get("value", [1, 2])
    res["calendar_weeks"] = {str(n): [round(tot_lo / (n * hpd * 5), 1), round(tot_hi / (n * hpd * 5), 1)] for n in team}
    os.makedirs(a.out, exist_ok=True)

    eng_name = ENGINES[inp.get("port_engine", {}).get("value", "devtx")]
    db_name = DB_TOOLS[db_tool(inp)]
    ph = phases(I, inp)
    res["phases"] = ph
    json.dump(res, open(os.path.join(a.out, "estimate.json"), "w", encoding="utf-8"), indent=1)
    L = [f"# Modernization estimate: {f['repo']}", "",
         f"Tool-run, no hand-coding. **{eng_name}** ports the code (one engine for the whole repository); **Claude** with the "
         f"dotnet-modernization skill cleans up what that engine does not cover; **{db_name}** adds the PostgreSQL path beside SQL Server. "
         "Engineers run the tools, approve plans, review, fix what the gates reject and sign off. "
         "Planning grade, +-25%. Quantities come from facts.json, rates from estimate_phases.py, assumptions from estimate-inputs.json.", "",
         f"**Total {res['total'][0]}-{res['total'][1]} h** (subtotal {res['subtotal'][0]}-{res['subtotal'][1]} h + {buf:.0%} buffer) = "
         f"{res['dev_days'][0]}-{res['dev_days'][1]} dev-days at {hpd} h.", "",
         "## Plan", "", "| Phase | Who | What | Hours |", "|---|---|---|---|"]
    for p in ph:
        L.append(f"| {p['id']} {p['title']} | {p['who']} | {'; '.join(p['what'])} | {p['low']:.0f}-{p['high']:.0f} |")
    L += [f"| Buffer {buf:.0%} | | | {sub_lo * buf:.0f}-{sub_hi * buf:.0f} |", f"| **Total** | | | **{res['total'][0]}-{res['total'][1]}** |", ""]
    L += profile(f, inp) + [""] + pg_considerations(f, inp)
    L += ["", "## Detail by line item", "", "Every hour figure is INFERRED (an estimate). The last column labels the quantities it is built from.", "",
          "| # | Phase | Work item | Done by | Hours | How the hours are built | Basis | Quantities |", "|---|---|---|---|---|---|---|---|"]
    pof = {i: p["id"] for p in ph for i in p["items"]}
    for x in sorted(I, key=lambda x: (pof.get(x["id"], "P9"), x["id"])):
        L.append(f"| {x['id']} | {pof.get(x['id'], '')} | {x['label']} | {x['tool']} | {x['low']:g}-{x['high']:g} | {'; '.join(x['drivers']) or '-'} | {x['basis']}"
                 + (f" ({x['note']})" if x["note"] else "") + f" | {x['status']} |")
    aws = f.get("_aws_native")
    if aws and inp.get("aws_native", {}).get("value") and aws.get("library_hours", [0, 0])[1]:
        L += ["", f"Not in the total: the service wrappers inside shared libraries ({', '.join(aws['libraries'])}), "
              f"{aws['library_hours'][0]:g}-{aws['library_hours'][1]:g} h, are counted once with that library's own port. Details: aws-native.md."]
    L += ["", "## Assumptions (estimate-inputs.json)", ""]
    for k, v in inp.items():
        if isinstance(v, dict):
            if k not in ("scenarios", "aws_native_choices", "r7"):
                L.append(f"- **{k}**: {v.get('value', 'not answered')} ({v.get('status', '')}). {v.get('note', '')}")
    L += ["", f"## Calendar ({hpd} focused hours a day, 5 days a week)", ""]
    for n, w in res["calendar_weeks"].items():
        L.append(f"- {n} developer(s): {w[0]}-{w[1]} weeks of build effort.")
    if scen:
        L += ["", "## What the open questions change", "", "| If | Client question | Total | Change |", "|---|---|---|---|"]
        for x in scen:
            L.append(f"| {x['name']} | {x['question']} | {x['total'][0]}-{x['total'][1]} h | {x['delta'][0]:+d} to {x['delta'][1]:+d} h |")
    if a.compare:
        L += ["", "## Compared with earlier estimates", "", "| Estimate | Hours |", "|---|---|",
              f"| This bottom-up estimate | {res['total'][0]}-{res['total'][1]} |"]
        for k, v in json.loads(a.compare).items():
            L.append(f"| {k} | {v[0]:g}-{v[1]:g} |")
    write_pair(os.path.join(a.out, "estimate.md"), "\n".join(L) + "\n")
    print(f"{f['repo']}: B {stages['B'][0]:.0f}-{stages['B'][1]:.0f} h, A {stages['A'][0]:.0f}-{stages['A'][1]:.0f} h, S {stages['S'][0]:.0f}-{stages['S'][1]:.0f} h, total {res['total'][0]}-{res['total'][1]} h")
    return res


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--compare", help="earlier estimate to compare with: JSON {label: [low, high]}")
    a = ap.parse_args()
    root, cfg = load_config()
    st = load_state(root)
    repos = [a.repo] if a.repo else sorted(r for r, v in st["repos"].items() if v.get("scope") != "out"
                                           and os.path.exists(os.path.join(OUT, "effort", r, "facts.json")))
    if not repos:
        raise SystemExit("no effort facts: run effort_facts.py first")
    allp = read_json(os.path.join(OUT, "effort", "estimate-phases.json"), {"repos": {}}) or {"repos": {}}
    for r in repos:
        res = estimate_repo(r, cfg, a)
        if res:
            allp["repos"][r] = {k: res[k] for k in ("phases", "stages", "subtotal", "buffer", "total", "dev_days", "hours_per_day", "calendar_weeks", "scenarios")}
            allp["repos"][r]["engine"] = ENGINES[res["inputs"].get("port_engine", {}).get("value", "devtx")]
            allp["repos"][r]["db_tool"] = DB_TOOLS[db_tool(res["inputs"])]
            allp["repos"][r]["open"] = [k for k, v in res["inputs"].items() if isinstance(v, dict) and v.get("status") == "UNKNOWN"]
    allp["total"] = [sum(v["total"][0] for v in allp["repos"].values()), sum(v["total"][1] for v in allp["repos"].values())]
    write_json(os.path.join(OUT, "effort", "estimate-phases.json"), allp)
    print(f"estate: {allp['total'][0]}-{allp['total'][1]} h over {len(allp['repos'])} repositor{'y' if len(allp['repos']) == 1 else 'ies'} -> {OUT}/effort/estimate-phases.json")


if __name__ == "__main__":
    main()
