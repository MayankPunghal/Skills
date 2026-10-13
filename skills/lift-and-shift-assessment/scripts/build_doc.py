"""Build the single assessment document (.docx) for the whole project and the small companion workbook (.xlsx).

    python <skill>/scripts/build_doc.py

The document is a clone of the reference document (the reference migration plan the manager supplied): same sections, same
headings, same order, same plain look. Only the content is ours. One document covers every repository, solution and project; solutions are
table rows. Project-level detail (150+ projects) lives in the workbook. Everything is DRAFT until the user says it is final
(intake.py --finalize). Evidence labels: VERIFIED (counted in the code), INFERRED (reasoned or estimated), UNKNOWN (needs input).
Sections 6-9 (mechanism, architecture, execution, waves) are our proposal for planning, labelled INFERRED; DevOps answers from the intake replace it.
"""
import datetime
import os
import re

from _common import OUT, data, load_config, read_json, slug, utf8_stdout, write_json
from _docx import Docx
from solutions import keys
import _xlsx
import _buildwhy as BW
import intake as I

CAP = 30  # rows per table in the document; the workbook has the full list
WORK_LABEL = {"build_artifacts": "Build check + deployable artifacts", "cicd_secrets": "CI/CD pipeline + Secrets Manager",
              "retarget": "Framework retarget", "validation_cutover": "Test-launch validation + cutover support"}
WORK_DOES = {
    "build_artifacts": "Restore and build every solution on a clean agent and hand the deployable artifacts and notes to DevOps.",
    "cicd_secrets": "A pipeline per solution; secrets and connection values read from AWS Secrets Manager; DNS names instead of IP addresses; third-party keys re-keyed.",
    "retarget": "Change the target framework, rebuild and run a regression pass. No C# change.",
    "validation_cutover": "Check that each workload starts clean on the AWS instance, triage migration-side defects and support the cutover.",
}
WINDOWS_ONLY = ("WIN-", "DATA-", "DB-", "AUTH-", "IIS-", "INT-", "WCF-", "WEB-", "BG-", "HOST-")
EVIDENCE = "Every material claim is labelled VERIFIED (measured/observed), INFERRED (reasoned from verified facts), or UNKNOWN (requires customer input)."


def h(x):
    return f"{x:g}"


def rng(a, b):
    return f"{h(a)}–{h(b)}"


def labels(sols):
    names = [s["solution"] for s in sols]
    return {s["id"]: (f"{s['repo']}/{s['solution']}" if names.count(s["solution"]) > 1 else s["solution"]) for s in sols}


INTAKE_Q = {q["id"]: q for q in data("intake.json")["questions"]}


def given(it, qid):
    """True when the user gave a real answer (not missing, not 'unknown')."""
    return it.get(qid) not in (None, "", [], "unknown")


def ans(it, qid):
    """The user's answer in words: the option label, the free text, or UNKNOWN."""
    if not given(it, qid):
        return "UNKNOWN"
    for o in INTAKE_Q.get(qid, {}).get("options", []):
        if o["value"] == it[qid]:
            return o["label"]
    return str(it[qid])


def decisions(d, it, pairs):
    """Bullets for the answered questions of a section; an answer of 'unknown' is listed as UNKNOWN so the gap stays visible."""
    rows = [f"{label}: {ans(it, qid)}" for label, qid in pairs if qid in it]
    if rows:
        d.bullets(rows)


def first_int(text, default):
    m = re.search(r"\d+", str(text or ""))
    return int(m.group()) if m else default


def capped(rows, sheet):
    return rows[:CAP], (f"Showing {CAP} of {len(rows)}; the full list is in the workbook, sheet {sheet}." if len(rows) > CAP else "")


STORE_DIRECTION = [  # what flows to and from an external component; the outbound call is counted in the code, the inbound side is reasoned (INFERRED)
    (r"(?i)mongo|redis|elastic|memcache|aerospike|influx|sql", "A self-hosted server moves to AWS with the applications. If a provider hosts it, its firewall must admit the new AWS addresses."),
    (r"(?i)stripe|braintree|paypal|payflow|alipay|payment|gateway|ipg-online|enett|payandshop|payeezy|trustcommerce|payfort", "The provider may call back into the application (return or notification URL) and may allow-list the sender address; both to be checked."),
    (r"(?i)sendgrid|smtp|mail", "Delivery or event webhooks into the application are possible; the sender address may be allow-listed."),
    (r"(?i)sharepoint|graph\.microsoft|microsoftonline|salesforce", "Sign-in redirect or callback URLs registered with the provider must match the new public address."),
    (r"(?i)sftp|ftp", "The partner may allow-list our address, or push files to us; to be checked."),
]


def direction(name, kind):
    """(outbound, inbound) wording for one external component."""
    out = "Application calls it (VERIFIED in code or config)"
    for rx, text in STORE_DIRECTION:
        if re.search(rx, name):
            return out, text + " (INFERRED)"
    return out, "Provider to confirm (see note)"


def framework_cell(s):
    counts = {}
    for p in s["projects"]:
        k = ", ".join(p.get("frameworks") or []) or "?"
        counts[k] = counts.get(k, 0) + 1
    return next(iter(counts)) if len(counts) == 1 else "; ".join(f"{k} x{n}" for k, n in sorted(counts.items(), key=lambda x: -x[1]))


def is_mixed(s):
    return len({",".join(p.get("frameworks") or []) for p in s["projects"]}) > 1 or len({p.get("family") for p in s["projects"]}) > 1


WORKBOOK_READ_ME = [
    ["Workbook of the assessment (DRAFT: nothing is final until confirmed)"],
    [""],
    ["How the sheets relate. Counts come from the code and config of the repositories only; nothing was run on any server."],
    ["Solutions / Projects / Workloads: what is in scope. Environments are not known, so one workload per solution is assumed."],
    ["Branches: the branch assessed for each repository, its last commit date and why that branch (the code was read from these branches; where the default branch is stale the integration branch was used)."],
    ["Build: one row per solution. Result of a real build on a clean machine, why it fails, what is needed and who provides it. Build detail: every finding behind it."],
    ["DataStores: for each solution, the data stores its projects use (found from packages and code) and the addresses that the repository's config names for that store type. It is NOT a server mapping: a name and an IP in the same cell are separate values, not the same server. 'Held outside the repository' means the code uses the store but no address for it is in the repository: it is set on the server, in the pipeline or in a vault, so DevOps has to supply it. The project count and the addresses are found independently."],
    ["Connections (to internal servers) lists the internal addresses and names each solution uses; ThirdParty lists outside services, licensed components and keys. Data stores such as Redis or MongoDB can appear in both because both read the same packages and calls."],
    ["Outbound: addresses the code or config uses to reach something (connection strings, URLs, host settings). Inbound: what each application listens on, read from launchSettings, Kestrel, IIS Express and WCF service settings. The real production binding of an IIS site is not in the code, so many rows say UNKNOWN until the server mapping is returned. Direction is decided from the setting and its context, not by running the application."],
    ["Settings: names and files only, never values. Estimate: every line of the hours in the document, per solution."],
]


def short_error(e):
    e = re.sub(r"\s*\[[A-Za-z]:\\.*$", "", e)  # first: the trailing [project path], which also holds the work folder
    e = re.sub(r"(?i)^.*?build.work.", "", e)
    return e[:150]


def finding_text(st, real):
    """Section 5.1 cell: for a failed build the plain reason, what is needed and who provides it; for a passing build a short result."""
    w = BW.why(st, real)
    if w:
        return f"Fails: {w[0]}. Needed: {w[1]} ({w[2]})."
    items = list(st.get("issues") or [])
    out = []
    if real.get("status") == "PASS":
        out.append(f"Builds ({real.get('configuration', 'Release')}, {real.get('seconds', '?')} s)")
        if items:
            out.append("warning only: " + "; ".join(items[:2]) + (f" and {len(items) - 2} more" if len(items) > 2 else ""))
        if BW.note(real):
            out.append(BW.note(real))
    else:
        out.append("Not built: " + str(real.get("detail") or "no result"))
    return "; ".join(out)


def connectivity_register(sols, lab):
    """Outbound and inbound addresses per solution, from the scan: what DevOps has to open, resolve or allow-list for every call to work."""
    outb, inb = [], []
    for sol in sols:
        paths = {p["path"] for p in sol["projects"]}
        net = (read_json(os.path.join(OUT, "scan", sol["repo"] + ".json"), {}) or {}).get("network") or {}
        for o in net.get("outbound", []):
            if not (set(o.get("projects") or []) & paths):
                continue
            kind = o.get("kind") or ""
            act = ("The server moves to AWS with the application: the address or a DNS name must resolve there; open the security group and port." if kind == "internal"
                   else "Allow outbound traffic; check whether the provider allow-lists the sender address (new AWS address)." if kind == "external"
                   else "Confirm what this address is, then treat it as internal or external.")
            outb.append([lab[sol["id"]], o["host"], o.get("port") or "", o.get("scheme") or "", kind or "unclassified", o.get("role") or "", ", ".join((o.get("keys") or [])[:3]),
                         ", ".join((o.get("evidence") or [])[:2]), act])
        listeners = {x.get("project"): x for x in net.get("inbound", [])}
        for p in sol["projects"]:
            if not p["deployable"] or p.get("type") in ("windows-service", "console"):
                continue  # only web deployables listen for calls
            x = listeners.get(p["path"])
            inb.append([lab[sol["id"]], p["name"], (f"{x.get('scheme') or ''} {x.get('host') or ''}:{x.get('port')}".strip() if x and x.get("port") else f"{x.get('scheme') or 'http(s)'}, host and port from the IIS site binding" if x else "web site binding in IIS (not in code)"),
                        x["source"] if x else "UNKNOWN until the server mapping is returned",
                        "Site binding (host name, port, https) is created on the AWS instance, the load balancer listener and DNS name point to it, the certificate is installed, and callers (including external ones) can reach it."])
    return sorted(outb, key=lambda r: (r[0], r[4], str(r[1]))), inb


def solution_names(s):
    out = set()
    for p in s["projects"]:
        out |= keys(p)
    return out


def windows_only(sols):
    """Windows-only components found by the scan: {rule: {title, solutions, projects}} (counted in the code, carried forward unchanged)."""
    out = {}
    for repo in sorted({s["repo"] for s in sols}):
        for f in read_json(os.path.join(OUT, "findings", repo + ".json"), []) or []:
            if not f["rule"].startswith(WINDOWS_ONLY):
                continue
            for s in sols:
                if s["repo"] == repo and (f.get("project") or "").lower() in solution_names(s):
                    e = out.setdefault(f["rule"], {"title": f["title"], "solutions": set(), "projects": set()})
                    e["solutions"].add(s["id"])
                    e["projects"].add((repo, f["project"]))
    return out


def hardcoded_secret_solutions(sols, lab):
    found = set()
    for repo in sorted({s["repo"] for s in sols}):
        for f in read_json(os.path.join(OUT, "findings", repo + ".json"), []) or []:
            if f["rule"] == "CFG-HARDCODED-SECRET":
                found |= {lab[s["id"]] for s in sols if s["repo"] == repo and (f.get("project") or "").lower() in solution_names(s)}
    return sorted(found)


def branch_rows(cfg):
    """One row per repository: the branch that was assessed and its last commit (read from the local checkout, no network)."""
    import subprocess
    notes = cfg.get("branch_notes") or {}
    rows = []
    for r_ in cfg.get("estate_roots") or []:
        def git(*a):
            try:
                return subprocess.check_output(["git", "-C", r_] + list(a), text=True, stderr=subprocess.DEVNULL).strip()
            except Exception:
                return ""
        name = os.path.basename(r_.replace("\\", "/").rstrip("/"))
        rows.append([name, git("branch", "--show-current") or "UNKNOWN", git("log", "-1", "--format=%cs") or "UNKNOWN", notes.get(name.lower(), "Default branch; no newer branch exists." if name else "")])
    return rows


HELD_OUTSIDE = "held outside the repository (not in code or config)"


def role_text(o):
    """Address type and likely role for one address; INFERRED from setting names and ports (the confidence stays in the discussion, not in the documents)."""
    if not o or not o.get("role"):
        return "unclear from the code"
    return o["role"]


def address_rows(roles, lab_by_repo, conns):
    """Rows for the address table: address, type, likely role, DevOps servers with that role, solutions."""
    rows = []
    for (to, kind), sols_ in sorted(conns.items()):
        o = roles.get(to)
        if kind == "private IP":
            n = (o or {}).get("devops_servers_with_role") or 0
            rows.append([to, "private IP", role_text(o), str(n) if n else "-", ", ".join(sorted(sols_))[:60]])
    for o in sorted((x for x in roles.values() if x["type"] == "public IP"), key=lambda x: x["address"]):
        rows.append([o["address"], "public IP", role_text(o), "-", ", ".join(sorted({lab_by_repo.get(r, r) for r in o.get("solutions_repos") or []}))[:60]])
    return rows


def main():
    utf8_stdout()
    root, cfg = load_config()
    os.chdir(root)
    import intake as _intake
    _intake.require(cfg, root, ['before_scan', 'after_scan', 'after_build'], "build_doc.py")
    idx = read_json(os.path.join(OUT, "solutions", "index.json"))
    tp = read_json(os.path.join(OUT, "solutions", "third_party.json"))
    est = read_json(os.path.join(OUT, "estimate.json"))
    if not (idx and tp and est):
        raise SystemExit("run solutions.py, third_party.py and estimate_hours.py first")
    bc = {s["id"]: s for s in (read_json(os.path.join(OUT, "build", "index.json"), {}) or {}).get("solutions", [])}
    it = cfg.get("intake") or {}
    sel = I.selected(cfg)
    final = it.get("final")
    sols = idx["solutions"]
    lab = labels(sols)
    tps = {s["id"]: s for s in tp["solutions"]}
    roles = {o["address"]: o for o in (read_json(os.path.join(OUT, "infra", "address_roles.json"), {}) or {}).get("addresses", [])}
    lab_by_repo = {s["repo"].lower(): lab[s["id"]] for s in sols}
    meta_path = os.path.join(OUT, "documents", "meta.json")
    meta = read_json(meta_path, {"revision": 0})
    meta["revision"] += 1
    write_json(meta_path, meta)
    client = cfg.get("client") or "Client"
    nproj = sum(len(s["projects"]) for s in sols) - len(idx["shared_projects"])
    repos = sorted({s["repo"] for s in sols})
    ndep = sum(len(s["deployables"]) for s in sols)
    wl = [(f"WL-{i + 1:02d}", s, w) for i, (s, w) in enumerate((s, w) for s in sols for w in s["workloads"])]
    tot = est["total"]
    envs_all = sorted({e for s in sols for e in s["environments"]})
    envs_unknown = idx["environments_assumed"] or not it.get("environments_confirmed")
    note = (it.get("devops_notes") or "").strip()
    mech = {"mgn": "Option A: AWS Application Migration Service (MGN), block-level replication", "rebuild": "Option B: rebuild on a fresh AMI",
            "both": "Option A first (MGN), Option B later"}.get(it.get("devops_mechanism"), "UNKNOWN: not decided")
    blocked = [s for s in sols if bc.get(s["id"], {}).get("static", {}).get("status") == "BLOCKED" and bc.get(s["id"], {}).get("real", {}).get("status") != "PASS"]  # a passing real build outranks the static guess
    real_fail = [s for s in sols if bc.get(s["id"], {}).get("real", {}).get("status") == "FAIL"]
    wo = windows_only(sols)
    rekey = {}
    for s in sols:
        for i in tps[s["id"]]["licensed_and_integrations"]:
            rekey.setdefault((i["name"], i["kind"]), {"item": i, "solutions": []})["solutions"].append(lab[s["id"]])
    hardcoded = hardcoded_secret_solutions(sols, lab)
    nv, nf = sum(len(s["env_vars"]) for s in sols), sum(len(s["config_files"]) for s in sols)
    nep = sum(len(s["endpoints"]) for s in sols)
    secrets_on = "cicd_secrets" in sel  # the secrets section is written only when the work is in scope
    n_secrets = "5.2" if secrets_on else None
    n_addr = "5.3" if secrets_on else "5.2"
    n_fw = "5.4" if secrets_on else "5.3"

    register = connectivity_register(sols, lab)
    import _docx
    _docx.LINK_URL = (cfg.get("workbook_url") or "").strip() or None  # set once the workbook is on Drive: "workbook" in the text becomes a link
    d = Docx()
    d.title(f"{client} Migration - {len(sols)} Solutions ({len(repos)} Repositories) to AWS on Windows (Phase 1)")

    # 1 ------------------------------------------------------------------
    d.h1("1. Document control")
    d.table([["Field", "Value"],
             ["Engagement", f"{client}: {cfg.get('engagement') or 'AWS Lift-and-Shift Assessment'}"],
             ["Phase covered", "**" + ans(it, "phase_covered")],
             ["Version", f"{'Final' if final else 'Draft'} {meta['revision']}"],
             ["Date", datetime.date.today().isoformat()],
             ["Status", f"Final (confirmed by {final['by']}, {final['date']})" if final else "Draft for review. Nothing is final until confirmed; every hour can be revised."],
             ["Created By", cfg.get("prepared_by") or "UNKNOWN"],
             ["Evidence convention", EVIDENCE]], [26, 74])
    d.h2("1.1 Scope box")
    if cfg.get("branch_notes"):
        d.p("Branch assessed and its last commit date per repository: workbook, sheet Branches (integration branch where the default is stale; INFERRED).")
    d.p("IN SCOPE for this plan:", bold=True)
    d.bullets([f"{WORK_LABEL[k]}: {WORK_DOES[k]}" for k in WORK_LABEL if k in sel] or ["UNKNOWN: no work item selected"])
    rows = [["Environment", "Server", "OS", "Specs", "IP Address", "IIS App Pools"]]
    svr = read_json(os.path.join(OUT, "infra", "servers.json"))
    os_txt = hyp_txt = None
    if svr and svr.get("servers"):
        from collections import Counter
        win = Counter(m.group(1) for x in svr["servers"] for m in [re.search(r"Windows Server (\d{4})", x.get("os") or "")] if m)
        ubu = [(m.group(1) + "0" if m.group(1).endswith(".4") else m.group(1)) for x in svr["servers"] for m in [re.search(r"Ubuntu(?: Server)? (\d+\.\d+)", x.get("os") or "")] if m]
        os_txt = ("Windows Server " + ", ".join(f"{v} ({n})" for v, n in win.most_common()) if win else "") +                  ("; Ubuntu " + min(ubu, key=float) + " to " + max(ubu, key=float) + f" ({len(ubu)})" if ubu else "") + " (DevOps list)"
        hy = Counter((x.get("hypervisor") or "").strip() for x in svr["servers"])
        hyp_txt = ", ".join(f"{n} on {k}" for k, n in hy.most_common() if k not in ("", "-")) + (f"; {hy.get('', 0) + hy.get('-', 0)} not stated" if hy.get("", 0) + hy.get("-", 0) else "") + " (DevOps list)"
    it = dict(it)
    if os_txt and not given(it, "windows_versions"):
        it["windows_versions"] = os_txt
    if svr and svr.get("servers") and not given(it, "build_agent"):
        ci = [x for x in svr["servers"] if any(r_.get("role") == "ci" for r_ in x.get("roles") or [])]
        if ci:
            it["build_agent"] = "; ".join(f"{x['name']}: " + ("Build Tools " + ", ".join(sorted(set(re.findall(r"Build Tools (\d{4})", x.get("applications") or "")))) if re.search(r"Build Tools \d{4}", x.get("applications") or "") else "no Build Tools listed") for x in ci) + " (DevOps list)"
    miss = {}
    for x in sols:
        w = BW.why(bc.get(x["id"], {}).get("static", {}), bc.get(x["id"], {}).get("real", {}))
        for tok in re.findall(r"(?:[\w.]+\.csproj|AssemblyInfo\.cs)", w[1]) if w and "the client" in w[2] else []:
            miss.setdefault("Properties\\AssemblyInfo.cs" if tok == "AssemblyInfo.cs" else tok.replace(".csproj", " project"), []).append(lab[x["id"]])
    if miss and not given(it, "missing_references"):
        it["missing_references"] = "; ".join(f"{k} ({', '.join(v)})" for k, v in miss.items()) + " (VERIFIED: absent on every GitLab branch)"
    if svr and svr.get("servers"):
        import statistics
        by_env = {}
        for x in svr["servers"]:
            by_env.setdefault(x["environment"] or "(blank)", []).append(x)
        num = lambda v: [int(float(y)) for y in v if str(y).replace(".", "", 1).isdigit()]
        for e, xs in sorted(by_env.items(), key=lambda kv: -len(kv[1])):
            win = sum(1 for x in xs if x["os_family"] == "windows")
            cores, mem = num(x["cores"] for x in xs), num(x["memory_gb"] for x in xs)
            rows.append([e, f"{len(xs)} servers", f"{win} Windows, {sum(1 for x in xs if x['os_family'] == 'linux')} Linux",
                         f"typical {int(statistics.median(cores)) if cores else '?'} cores, {int(statistics.median(mem)) if mem else '?'} GB",
                         "not in the list", "UNKNOWN until applications are mapped to servers"])
    else:
        for e in envs_all or ["UNKNOWN (1 per solution assumed)"]:
            rows.append([e, "UNKNOWN", ans(it, "windows_versions"), "UNKNOWN", "UNKNOWN", "UNKNOWN"])
    d.table(rows, [16, 14, 20, 22, 14, 24])
    sl = it.get("server_list")
    if svr and svr.get("servers"):
        d.p(f"Server list: DevOps inventory ({os.path.basename(svr['source'])}, {len(svr['servers'])} servers). It is the source of truth for servers, environments and sizing. "
            "Which application runs on which server is UNKNOWN until the mapping is returned; workloads are confirmed from it.")
    else:
        d.p("Server list: " + {"provided": "provided (" + ans(it, "server_list_detail") + ")", "none": "none exists; server details are UNKNOWN",
                               "later": "exists but not received yet; server details are UNKNOWN"}.get(sl, "UNKNOWN") + ".")
    if envs_unknown:
        d.p("Environments are UNKNOWN or not confirmed: 1 environment per solution is assumed. Confirm them before this document is finalised.", bold=True)
    opt = [k for k in WORK_LABEL if k not in sel]
    if opt:
        d.p("Optional IN Scope:", bold=True)
        d.bullets([f"{WORK_LABEL[k]}: {WORK_DOES[k]}" for k in opt])
    d.p("NOT in scope: any change to the applications' code or job logic, modernisation, Linux or native AWS services, DevOps and database work (separate teams)."
        + (" Installing or running anything on the current servers." if it.get("source_access") == "no_changes" else ""))
    d.p("Explicit carry-forward statement", bold=True)
    d.p("Every Windows-only component in the applications, like")
    top = sorted(wo.values(), key=lambda e: -len(e["projects"]))[:8]
    d.bullets([f"{e['title']} ({len(e['projects'])} project(s), {len(e['solutions'])} solution(s) — VERIFIED in the current codebase)" for e in top] or ["None found by the scan"])
    d.lead("Carries forward UNCHANGED in Phase 1.", "On Windows EC2, they work exactly as they do today.")

    # 2 ------------------------------------------------------------------
    d.h1("2. Executive summary")
    d.lead("What Phase 1 achieves.", f"Phase 1 moves {len(sols)} solutions ({nproj} projects, {ndep} deployables, {len(repos)} repositories) out of the current hosting and onto "
           f"AWS EC2 on the same Windows/IIS platform with the minimum change. Developer effort: {rng(tot['low'], tot['high'])} hours "
           f"({rng(est['days_low'], est['days_high'])} dev-days) including a {est['contingency_pct']}% buffer (Section 10).")
    d.p("What Phase 1 deliberately does not do", bold=True)
    dbl = {"stay": "It does not touch the database: the databases stay where they are today and are reached over the network link.",
           "move_with": "The databases move with the applications; the database move itself is not priced here (DB team).",
           "move_separately": "It does not touch the database: the databases move separately (DB team)."}.get(it.get("database_location"), "Database location: UNKNOWN (not decided).")
    d.bullets([dbl,
               "It does not change the applications' code or architecture." + (" The framework retarget is a project-file change only." if "retarget" in sel else ""),
               "Its Windows-only dependencies carry forward unchanged."])
    svc = sum(1 for s in sols for p in s["projects"] if p.get("type") == "windows-service" and p["deployable"])
    if svc:
        d.lead("What Phase 1 achieves for the Windows services.", f"{svc} Windows services move with the same schedules and configuration; "
               + ("their configuration values come from AWS Secrets Manager." if "cicd_secrets" in sel else "configuration changes are UNKNOWN until CI/CD + Secrets Manager is decided."))

    # 3 ------------------------------------------------------------------
    d.h1("3. 7R disposition — Phase 1 workloads")
    d.p(f"This section evaluates the {len(wl)} workloads in this phase's scope against all seven Rs with qualitative verdicts.")
    d.p("Architecture Diagram", bold=True)
    d.p("UNKNOWN: to be provided by DevOps.")
    d.p("Solutions in scope (the split by environment is not known: one workload per solution is assumed)" if envs_unknown else "Confirmed Workloads as per architecture above", bold=True)
    for wid, s, w in wl[:CAP]:
        d.p(f"{wid} = {lab[s['id']]}" + ("" if envs_unknown else f" — {w['environment']}") + f" ({len(w['deployables'])} deployable(s))")
    if len(wl) > CAP:
        d.p(f"Showing {CAP} of {len(wl)} workloads; the full list is in the workbook, sheet Workloads.")
    d.table([["Workload", "R", "Verdict", "Rationale"],
             ["All workloads", "Retire", "Rejected", "The applications are live; no successor system is named."],
             ["All workloads", "Retain", "Rejected", "Staying put keeps the current hosting dependency."],
             ["All workloads", "Rehost", "**Selected — Phase 1", "Same Windows platform and framework; lowest change and risk; no C# change."],
             ["All workloads", "Relocate", "Possible, not selected" if it.get("current_hosting") == "VMware" else "Disqualified" if given(it, "current_hosting") else "Possible for the VMware servers only, not selected" if hyp_txt else "UNKNOWN",
              "VMware Cloud on AWS fits a VMware source; Rehost is chosen." if it.get("current_hosting") == "VMware" else
              ("Relocate means VMware Cloud on AWS; the source is " + ans(it, "current_hosting") + ".") if given(it, "current_hosting") else ("Relocate means VMware Cloud on AWS and applies only to VMware servers. Hypervisors in the server list: " + hyp_txt + ". Rehost is chosen. (INFERRED: which hypervisor each application runs on is not known.)") if hyp_txt else "Applies only to a VMware source; the current hosting is UNKNOWN."],
             ["All workloads", "Replatform", "Rejected as the primary disposition", "Adds change without removing a blocker." + (" The framework retarget is folded into Rehost." if "retarget" in sel else "")],
             ["All workloads", "Refactor", "Deferred", "A separate modernisation effort (migration-assessment)."],
             ["All workloads", "Repurchase", "Rejected", "No purchasable substitute is named."]], [16, 14, 24, 46])
    d.p(f"NOTE: Rehost all {len(wl)} workloads; Replatform only as the optional framework retarget; Refactor explicitly deferred.")

    # 4 ------------------------------------------------------------------
    d.h1("4. Current state")
    d.p("All figures below are counted in the current codebase (VERIFIED):")
    rows = [["Solution", "Repository", "Framework", "Projects", "Deployables", "Lines of code"]]
    for s in sols:
        rows.append([lab[s["id"]], s["repo"], framework_cell(s), len(s["projects"]), len(s["deployables"]), s["loc"]])
    cut, n1 = capped(rows[1:], "Solutions")
    d.table([rows[0]] + cut, [26, 26, 14, 10, 12, 12])
    if n1:
        d.p(n1)
    testish = sorted({f"{p['name']} ({x['solution']})" for x in sols for p in x["projects"] if p["deployable"] and re.search(r"(?i)test|sample|demo", p["name"] + " " + p["path"])})
    if testish:
        d.p(f"Deployable by count; looks like a test tool, UNKNOWN: {', '.join(testish[:6])}.")
    mixed_n = sum(1 for x in sols if is_mixed(x))
    d.p(f"{mixed_n} of {len(sols)} solutions mix frameworks or project kinds (VERIFIED). Every project (type, framework, deployable) is listed per solution in the workbook, sheet Projects.")
    loose = idx.get("loose_projects") or []
    if loose:
        d.p(f"{len(loose)} projects are in no solution file (VERIFIED) and are not estimated until the client confirms they are deployed. The list: workbook, sheet LooseProjects.")
    for f in idx.get("folded_solutions") or []:
        d.p(f"{f['solution_file']} ({f['repo']}) holds only projects that {f['into']} also holds, so it is counted as part of {f['into']}.")
    stores = {}
    for repo in sorted({x["repo"] for x in sols}):
        for dep in (read_json(os.path.join(OUT, "infra", repo + ".json"), {}) or {}).get("dependencies", []):
            if dep.get("kind") not in ("database", "cache", "search"):
                continue
            for x in sols:
                if x["repo"] != repo:
                    continue
                own = [p for p in x["projects"] if p["path"] in (dep.get("projects") or [])]
                if own:
                    m = stores.setdefault((lab[x["id"]], dep["label"]), {"projects": set(), "hosts": set()})
                    m["projects"].update(p["name"] for p in own)
                    m["hosts"].update(str(h.get("host") if isinstance(h, dict) else h) for h in dep.get("hosts") or [])
    if stores:
        d.p(f"Data stores: {len(stores)} solution and store pairs found in code and config (VERIFIED). Per solution, with the addresses the configuration names for that store type (not a mapping of names to servers): workbook, sheet DataStores.")
    d.p("External integrations and licensed components", bold=True)
    keyed = sorted(n for (n, _k), m in rekey.items() if m["item"]["rekey"])
    if rekey:
        d.p(f"{len(rekey)} components found in code and config (VERIFIED); {len(keyed)} hold a key that is re-keyed on AWS"
            + (f": {', '.join(keyed[:10])}{' ...' if len(keyed) > 10 else ''}" if keyed else "")
            + ". Per component: what the application calls, inbound callbacks and allow-lists, and the key or licence: workbook, sheet ThirdParty.")
        d.p("Callbacks and allow-lists: UNKNOWN until each provider confirms.")
    else:
        d.p("None found.")
    d.p("Windows-Only Dependencies — Carried Forward Unchanged in Phase 1", bold=True)
    rows = [["Dependency", "Usage Detail (VERIFIED, current codebase)", "Windows-Native Status", "Phase 1 Status"]]
    for e in sorted(wo.values(), key=lambda e: -len(e["projects"])):
        rows.append([e["title"], f"{len(e['projects'])} project(s) in {len(e['solutions'])} solution(s)", "Works on Windows EC2 as-is", "Carried forward unchanged"])
    if len(rows) > 1:
        cut, n3 = capped(rows[1:], "Solutions")
        d.table([rows[0]] + cut, [30, 32, 20, 18])
        if n3:
            d.p(f"Showing {CAP} of {len(rows) - 1}; the rest are in assessment/findings.")
    else:
        d.p("None found by the scan.")

    # 5 ------------------------------------------------------------------
    d.h1("5. Prerequisites")
    d.h2("5.1 Make the build reproducible")
    rows = [["Solution", "Build result", "Finding"]]
    for s in sols:
        b = bc.get(s["id"], {})
        st = b.get("static", {})
        if st and st["status"] != "READY":
            rows.append([lab[s["id"]], b.get("real", {}).get("status", "NOT RUN"), finding_text(st, b.get("real", {}))])
    if len(rows) > 1:
        d.p("Build results come from a real build of a copy of each solution and from the project references. The result, the reason it fails and what is needed, per solution: workbook, sheet Build.")
    sib = {}
    for s in sols:
        for k, v in (bc.get(s["id"], {}).get("static", {}).get("sibling_folders") or {}).items():
            sib.setdefault(k, {"repos": set(), "files": set()})
            sib[k]["repos"].add(s["repo"])
            sib[k]["files"].update(v)
    if sib:
        merged = {}
        for k, v in sib.items():
            m_ = merged.setdefault(k.lower(), {"name": k, "files": set(), "repos": set()})
            m_["files"] |= v["files"]
            m_["repos"] |= v["repos"]
        d.p("Shared folders outside the repositories (VERIFIED), to be checked out beside them on the build agent: " + "; ".join(f"{v['name']} ({len(v['files'])} files)" for _, v in sorted(merged.items())) + ".")
    tools = sorted({x for st in bc.values() for x in st.get("static", {}).get("prerequisites", [])
                    if x.startswith(("Visual Studio Build Tools", "NuGet restore", "the .NET Framework targeting pack", "dotnet SDK"))})
    if tools and "build_artifacts" in sel:
        d.p("Install on the build agent (a separate machine from the application servers):", bold=True)
        fx = sorted({t.rsplit(" ", 1)[1] for t in tools if t.startswith("Visual Studio Build Tools: MSBuild + .NET Framework")}, key=lambda v: [int(x) for x in v.split(".")])
        sdk = sorted({v for t in tools if t.startswith("dotnet SDK for ") for v in t[len("dotnet SDK for "):].split(",")})
        rest = [t for t in tools if not t.startswith(("Visual Studio Build Tools: MSBuild + .NET Framework", "dotnet SDK for "))]
        old = [v for v in fx if [int(x) for x in v.split(".")] < [4, 7]]
        d.bullets(rest + ([f"Visual Studio Build Tools: MSBuild + .NET Framework {', '.join(fx)}"] if fx else []) + ([f"dotnet SDK for {', '.join(sdk)}"] if sdk else [])
                  + ([f"Targeting packs for .NET Framework {', '.join(old)}: current Visual Studio no longer ships them (Developer Packs, or the Microsoft.NETFramework.ReferenceAssemblies NuGet packages)."] if old else [])
                  + (["dotnet build cannot build the web projects (they need Microsoft.WebApplication.targets from the Build Tools): MSBuild is required."] if any("WebApplication.targets" in t for t in tools) else []))
    decisions(d, it, [("CI platform today", "ci_platform_today"), ("Windows build agent with MSBuild", "build_agent"), ("Private feeds and GAC references", "private_feeds"),
                      ("Files missing from the repositories", "missing_references")])
    real = [bc.get(s["id"], {}).get("real", {}).get("status", "NOT RUN") for s in sols]
    d.p(f"Real build: {real.count('PASS')} passed, {real.count('FAIL')} failed, {real.count('NOT RUN')} not run" + (" (UNKNOWN until run; it must pass before artifacts are produced)." if "NOT RUN" in real else "."))
    fails = [(x["id"], BW.why(bc.get(x["id"], {}).get("static", {}), bc.get(x["id"], {}).get("real", {}))) for x in sols]
    fails = [(i, w) for i, w in fails if w]
    if fails:
        need_client = sum(1 for _, w in fails if "the client" in w[2])
        d.p(f"Of the {len(fails)} failed builds, {need_client} need files from the client (DLLs, project folders or source files missing from the repositories); "
            f"{len(fails) - need_client} need a build-agent or project setting that we or DevOps can do. Details: the workbook, sheet Build.")
    ci_names = [x["name"] for x in (svr or {}).get("servers", []) if any(r_.get("role") == "ci" for r_ in x.get("roles") or [])]
    n_pub = sum(1 for r_ in cfg.get("estate_roots") or [] for _dp, _dn, fns in os.walk(r_) for f_ in fns if f_.lower().endswith(".pubxml"))
    n_jf = sum(1 for r_ in cfg.get("estate_roots") or [] for _dp, _dn, fns in os.walk(r_) for f_ in fns if f_.lower() in ("jenkinsfile", "azure-pipelines.yml", ".gitlab-ci.yml", "buildspec.yml"))
    if ci_names or n_pub:
        d.p(f"CI/CD today: the repositories contain {n_jf} pipeline files and the {n_pub} publish profiles only copy to local folders. "
            + (f"The DevOps list names Jenkins servers ({', '.join(ci_names)}), so job settings and per-environment values live there (INFERRED)." if ci_names else "")
            + "")
    if secrets_on:
        d.h2("5.2 Secrets into Secrets Manager, then rotate" if hardcoded else "5.2 Secrets into Secrets Manager")
        d.p(f"VERIFIED: the code reads {nv} environment variables and {nf} config files hold hard-coded values across {len(sols)} solutions. Names and files (no values): workbook, sheet Settings.")
        if hardcoded:
            d.p(f"Hard-coded credentials found in {len(hardcoded)} solution(s): {', '.join(hardcoded[:8])}{' ...' if len(hardcoded) > 8 else ''}. "
                "They are present in source history and must be treated as compromised; the migration must not copy them into AWS.")
        decisions(d, it, [("Secrets kept today", "existing_vault"), ("Secrets reach the applications by", "secrets_injection"), ("Rotation", "secrets_rotation"),
                          ("Secrets created and supplied by", "secrets_owner"), ("Hard-coded credentials rotated by", "credential_rotation_owner")])
    d.h2(f"{n_addr} Internal addresses and connectivity")
    conns = {}
    for s in sols:
        for c in tps[s["id"]]["server_to_server"]:
            conns.setdefault((c["to"], c["kind"]), set()).add(lab[s["id"]])
    d.p(f"VERIFIED: {nep} internal addresses and host names are in code and config (one count per solution that uses them; {len(set((e['destination']) for x in sols for e in x['endpoints']))} distinct, of which {len(set(e['destination'] for x in sols for e in x['endpoints'] if e['class'] == 'private IP'))} are IP addresses; only hard-coded IPs need replacing by names, host names and domains already are names). The self-hosted servers behind them move to AWS too, so each address or name must keep working there (same address, or a DNS name for the new server)."
        + (" With CI/CD + Secrets Manager in scope, the values move into Secrets Manager." if secrets_on else ""))
    arows = address_rows(roles, lab_by_repo, conns)
    if arows:
        names_n = sum(1 for o in roles.values() if o["type"] not in ("private IP", "public IP"))
        d.p("Most likely role (INFERRED from setting names and ports; DevOps to confirm). Public IPs change with the egress address. "
            f"The {names_n} host names and domains are typed in the workbook, sheet Connections.")
        d.p(f"{len(arows)} internal and public IP addresses, each with its type, most likely role and the number of DevOps servers with that role: workbook, sheet Connections.")
    d.p("Every outbound and inbound address of each solution is listed in the workbook (sheets Outbound and Inbound) and handed to DevOps at deployment so that every call works.")
    decisions(d, it, [("Database location", "database_location"), ("Mail from AWS", "mail_relay"), ("Folders and shares", "file_shares"),
                      ("Windows / Active Directory identity", "ad_domain"), ("Third-party IP allow-lists", "ip_allowlists"), ("Machine names, hardware ids, licence servers", "machine_bound"),
                      ("Public DNS and TLS certificates", "public_endpoints")])
    d.h2(f"{n_fw} Framework version")
    if "retarget" in sel:
        n = sum(len(s["retarget_projects"]) for s in sols)
        d.p(f"{n} project(s) retarget to .NET Framework {idx['retarget_to']}" + (" (target UNKNOWN until decided)." if idx["retarget_to"] == "unknown" else ". This is a build-level change, not a code change."))
        d.bullets([f"Automated regression tests: {ans(it, 'regression_tests')}."])
    else:
        d.p("Framework retarget is not selected for the dev team in this estimate.")

    # 6 ------------------------------------------------------------------
    chosen = it.get("devops_mechanism") if it.get("devops_mechanism") in ("mgn", "rebuild", "both") else "mgn"
    assumed_mech = it.get("devops_mechanism") not in ("mgn", "rebuild", "both")
    no_agents = it.get("source_access") == "no_changes"  # nothing may be installed or run on the current servers: no replication agent
    if no_agents:
        chosen, assumed_mech = "rebuild", False
    d.h1("6. Migration approach")
    d.p("Option A — AWS Application Migration Service (MGN)", bold=True)
    d.p("NOT AVAILABLE: it needs an agent on every source server, and nothing may be installed or run on the current servers." if no_agents else
        "Fastest possible exit. It carries every undocumented IIS setting, scheduled task, registry entry and codec, and it does not depend on fixing the build first.")
    d.p("Option B — Rebuild on fresh AMI (deploy from CI onto a clean Windows image)", bold=True)
    d.p("Launch a fresh AWS-provided Windows Server AMI, install IIS and dependencies from a scripted definition, and deploy the application. "
        "Produces a known-clean, reproducible server. Depends on the Section 5 prerequisites being complete and on a reproducible build.")
    d.p("Selected mechanism per workload", bold=True)
    d.p(f"Source operating systems: {ans(it, 'windows_versions') if given(it, 'windows_versions') or not os_txt else os_txt}." + ("" if no_agents else " MGN support for these versions is checked against the current MGN support matrix."))
    mech_name = {"mgn": "Option A — MGN block-level replication", "rebuild": "Option B — rebuild on fresh AMI", "both": "Option A first, Option B later"}[chosen]
    d.table([["Workload", "Mechanism", "Rationale"],
             ["All workloads", mech_name + (" (INFERRED: assumed for planning)" if assumed_mech else ""),
              "Lowest change and fastest exit; no dependency on the build." if chosen != "rebuild" else
              "The only option that needs nothing on the current servers; needs the Section 5 prerequisites and the settings the client supplies (8.1)." if no_agents else
              "Known-clean reproducible server; needs the Section 5 prerequisites first."]], [22, 44, 34])

    # waves: the strategy the user chose; our proposal (rehearsal on the smallest solution, then batches) is the default
    strategy = it.get("wave_strategy") if given(it, "wave_strategy") else "rehearsal_batches"
    per_wave = first_int(it.get("wave_detail"), 10) if strategy == "rehearsal_batches" else 10
    ordered = sorted(sols, key=lambda s: (len(s["endpoints"]), len(s["workloads"])))
    plan = []  # (kind, solutions, workloads in the wave)
    if strategy == "single":
        plan.append(("Single cutover", ordered, len(wl)))
    elif strategy == "by_environment" and envs_all:
        lower = [e for e in envs_all if e.lower() not in ("prod", "production", "live")] + [e for e in envs_all if e.lower() in ("prod", "production", "live")]
        for e in lower:
            ss = [x for x in sols if e in x["environments"]]
            plan.append((f"Environment {e}", ss, sum(len(x["deployables"]) for x in ss)))
    elif strategy == "other":
        plan.append(("As stated: " + ans(it, "wave_detail"), [], 0))
    elif ordered:
        plan.append(("Rehearsal", [ordered[0]], len(ordered[0]["workloads"])))
        cur, n = [], 0
        for s in ordered[1:]:
            if cur and n + len(s["workloads"]) > per_wave:
                plan.append(("Batch", cur, n))
                cur, n = [], 0
            cur.append(s)
            n += len(s["workloads"])
        if cur:
            plan.append(("Batch", cur, n))
    nonprod = [e for e in envs_all if e.lower() not in ("prod", "production", "live")]
    web = sum(1 for s in sols for p in s["projects"] if p["deployable"] and p.get("type") not in ("windows-service", "console"))

    # 7 ------------------------------------------------------------------
    d.h1("7. Target architecture on AWS Windows")
    d.p("Proposed for planning (INFERRED). " + (("DevOps notes: " + note) if note else "DevOps to confirm or replace."))
    d.table([["Component", "Proposed (INFERRED)"],
             ["Compute", f"{len(wl)} workloads on right-sized Windows Server EC2 instances; same OS and .NET Framework as today."],
             ["Web traffic", f"Application Load Balancer in front of the {web} web deployable(s); IIS unchanged." if web else "No web deployables."],
             ["Region and landing zone", f"Region {ans(it, 'aws_region')}; landing zone: {ans(it, 'aws_landing_zone')}."],
             ["Connectivity", f"The {len(conns)} internal servers in Section {n_addr} move to AWS with the applications; link to the current network while both run: {ans(it, 'aws_connectivity')}; security groups per workload; outbound access to the external third parties in Section 4."],
             ["Logging and monitoring", "CloudWatch agent for the Windows event log and application logs; instance-size review after 14 days."],
             ["Backup", "EBS snapshots on a schedule; source servers kept as the rollback target until sign-off."]], [24, 76])
    if "cicd_secrets" in sel:
        d.h2("7.1 AWS Secrets Manager integration (design for prerequisite 5.2)")
        d.table([["Aspect", "Design (INFERRED)"],
                 ["Secret layout", "One secret per solution, environment and concern (connection values, third-party keys, licence keys); JSON key–value per secret."],
                 ["Encryption", "Customer-managed KMS key; the key policy limits Decrypt to the instance roles and the pipeline role."],
                 ["Access", "EC2 instance profiles (no stored AWS credentials, IMDSv2 only); each role scoped to its environment's secret path; CloudTrail data events on."],
                 ["Network", "Secrets Manager interface VPC endpoint; retrieval never leaves the VPC."],
                 ["Injection — applications", f"{ans(it, 'secrets_injection')}. The code reads {nv} environment variables (VERIFIED); {nf} config files are tokenised (assessment/configtpl) for the values that are not environment variables."
                  + (" The application reading Secrets Manager itself is a C# change and is not in this estimate." if it.get("secrets_injection") == "sdk" else "")],
                 ["Rotation", ans(it, "secrets_rotation") + ". Compromised plaintext values are never copied into AWS."],
                 ["Created and supplied by", ans(it, "secrets_owner")],
                 ["Third-party keys", f"{sum(1 for m in rekey.values() if m['item']['rekey'])} keys or licences are re-keyed on AWS (Section 4); licence terms for the new servers to be confirmed."]], [24, 76])

    # 8 ------------------------------------------------------------------
    d.h1("8. Migration execution per workload")
    steps_mgn = [f"Prerequisites for cutover: build passes (5.1), connectivity to the internal addresses in place ({n_addr})" + (f", secrets staged ({n_secrets})." if secrets_on else "."),
                 "MGN agents installed on the source servers; replication reaches the continuous state.",
                 "Test launch (non-disruptive): right-sized instances launched in an isolated security group; the application starts, configuration and connection values are verified.",
                 "The AWS copy runs next to the source, which stays up and keeps serving. Cutover is a DNS event with no downtime; the source server stays untouched as the rollback target.",
                 f"Post-cutover: {ans(it, 'hypercare_days')} days of CloudWatch observation, then instance-size confirmation; MGN agents removed and replication stopped."]
    steps_rebuild = ["Prerequisites: build passes (5.1)" + (", pipeline per solution in place, configuration values and secrets staged." if secrets_on else "; configuration values stay as they are in the repositories."),
                     "Launch a fresh Windows Server AMI; install IIS and dependencies from the scripted definition; deploy the artifact.",
                     *([f"Settings that exist only on the current servers (IIS sites and app pools, certificates, scheduled tasks) are supplied by: {ans(it, 'source_settings')}."] if no_agents else []),
                     "Test launch in an isolated security group; the application starts, configuration and connection values are verified.",
                     "The AWS copy runs next to the source, which stays up and keeps serving. Cutover is a DNS event with no downtime; the source server stays untouched as the rollback target.",
                     f"Post-cutover: {ans(it, 'hypercare_days')} days of observation, then instance-size confirmation."]
    steps = steps_rebuild if chosen == "rebuild" else steps_mgn
    d.h2(f"8.1 Web deployables ({web})")
    d.bullets((steps + [f"Artifact form: {ans(it, 'artifact_format')}." if "build_artifacts" in sel else "Artifacts: not selected."]) if web else ["No web deployables."])
    d.h2(f"8.2 Windows services and jobs ({ndep - web})")
    d.bullets((steps + [f"Scheduled jobs and services in the test launch: {ans(it, 'job_schedules')}."]) if ndep - web else ["No Windows services or jobs."])
    d.h2("8.3 Sequencing dependency between the workloads")
    shared = sorted(((k, v) for k, v in conns.items() if len(v) > 1), key=lambda x: -len(x[1]))[:5]
    d.p(("The database never moves in Phase 1, so no solution has a hard ordering constraint on another. " if it.get("database_location") == "stay" else
         f"Database location: {ans(it, 'database_location')}. ") + "Internal servers are lifted with the solutions that use them (INFERRED); solutions sharing an internal server go in the same or consecutive waves, "
        "and the first wave proves the connectivity before anything else cuts over."
        + (" Shared internal servers (VERIFIED): " + "; ".join(f"{k[0]} ({len(v)} solutions)" for k, v in shared) + "." if shared else ""))

    # 9 ------------------------------------------------------------------
    d.h1("9. Wave plan and cutover")
    d.p("Wave rule: " + {"rehearsal_batches": f"a rehearsal wave on the smallest solution, then batches of at most {per_wave} workloads ordered by fewest internal connections",
                         "by_environment": "lower environments first, production last", "single": "one cutover for everything",
                         "other": ans(it, "wave_detail")}.get(strategy, "UNKNOWN")
        + ("" if given(it, "wave_strategy") else " (INFERRED: proposed, not confirmed)") + ". The order is an estimate from the code only (INFERRED)" + f". Cutover restrictions: {ans(it, 'maintenance_windows')}.")
    rows = [["Wave", "Content", "Entry criteria", "Exit criteria", "Rollback"],
            ["0 — Foundations", "Connectivity, access and approvals" + ("; secrets staged" if secrets_on else "") + "; build verified (5.1).", f"Landing zone: {ans(it, 'aws_landing_zone')}; network approvals in place.",
             f"Every internal endpoint in {n_addr} resolves and connects on AWS" + ("; secrets staged." if secrets_on else "."), "N/A"]]
    for i, (kind, ss, nw) in enumerate(plan, 1):
        names = ", ".join(lab[x["id"]] for x in ss)
        rows.append([f"{i} — {kind}", f"{nw} workload(s): {names[:90]}{'...' if len(names) > 90 else ''}",
                     "Previous wave stable." if i > 1 else "Wave 0 exit criteria met.",
                     "Test-launch validation passes (Section 11); defects triaged." if kind == "Rehearsal" else f"Smoke tests pass; hypercare ({ans(it, 'hypercare_days')} days) ends; sign-off.",
                     "Repoint DNS to the source server (kept running)."])
    rows.append(["Decommission", "Source servers stopped, final snapshots archived.", f"All waves stable after the parallel-run period ({ans(it, 'parallel_run_days')} days after the last wave).", "Sign-off.", "N/A"])
    cut = rows[:CAP + 1] + rows[-1:] if len(rows) > CAP + 2 else rows
    d.table(cut, [14, 30, 20, 20, 16])
    if len(rows) > CAP + 2:
        d.p(f"Showing {CAP} of {len(rows) - 2} waves; the later waves follow the same pattern.")
    d.p("Cutover-day runbook skeleton: freeze deploys → snapshot targets → verify connectivity → execute the cutover step → smoke tests (Section 11) → open traffic → hypercare "
        "→ go/no-go checkpoint at +2 h and +24 h with rollback pre-authorised.")

    # 10 -----------------------------------------------------------------
    d.h1("10. Effort estimate and timeline")
    d.p(("" if it.get("estimate_basis") == "as_agreed" else "The basis chosen in the intake differs from the one the rates were calibrated to; the rates are NOT recalibrated, so treat the hours with caution. ") + "Planning-grade developer hours, AI-assisted, for the selected work items only. Lines marked INFERRED have no sample behind them; the others are calibrated to the reference estimate. "
        "Nothing is final until confirmed.")
    if envs_unknown:
        ev = est["by_work_item"].get("validation_cutover")
        if ev:
            f = 1 + est["contingency_pct"] / 100
            d.p(f"Environments are not known, so the hours are per solution with one environment each. Each additional environment with the same deployables would add about {rng(round(ev['low'] * f), round(ev['high'] * f))} hours (test launch and cutover, with buffer); environment-specific values for each extra environment are not counted. INFERRED.")
    d.p("Application Effort Estimates", bold=True)
    lines = {}
    for e in est["solutions"]:
        for x in e["lines"]:
            m = lines.setdefault(x["id"], {"label": x["label"], "unit": x["unit"], "plural": x.get("plural", x["unit"] + "s"), "n": 0, "low": 0, "high": 0, "basis": x["basis"], "item": x["work_item"]})
            m["n"] += x["count"]
            m["low"] += x["low"]
            m["high"] += x["high"]
    rows = [["App-side work", "Hours"]]
    order = {ln["id"]: i for i, ln in enumerate(l for it_ in data("hours.json")["items"].values() for l in it_["lines"])}
    for m_id, m in sorted(lines.items(), key=lambda kv: order.get(kv[0], 99)):
        rows.append([f"{m['label']} ({m['n']} {m['unit'] if m['n'] == 1 else m['plural']})" + (" — INFERRED" if m["basis"] == "inferred" else ""), rng(round(m["low"], 1), round(m["high"], 1))])
    rows.append([f"Contingency buffer (~{est['contingency_pct']}%)", rng(est["contingency"]["low"], est["contingency"]["high"])])
    rows.append([f"**Total (incl. buffer) ≈ {rng(tot['low'], tot['high'])} hours", f"**(~{rng(est['days_low'], est['days_high'])} dev-days)"])
    d.table(rows, [78, 22])
    d.p("Solution-wise breakdown (before buffer)", bold=True)
    ests = {s["id"]: s for s in est["solutions"]}
    rows = [["Solution", "Hours"]]
    for s in sorted(sols, key=lambda x: -ests[x["id"]]["high"]):
        rows.append([lab[s["id"]], rng(round(ests[s["id"]]["low"], 1), round(ests[s["id"]]["high"], 1))])
    cut = rows[:CAP + 1] + [["**All solutions (before buffer)", f"**{rng(est['subtotal']['low'], est['subtotal']['high'])}"],
                            [f"Contingency buffer (~{est['contingency_pct']}%)", rng(est["contingency"]["low"], est["contingency"]["high"])],
                            [f"**Total (incl. buffer) ≈ {rng(tot['low'], tot['high'])} hours", f"**(~{rng(est['days_low'], est['days_high'])} dev-days)"]]
    d.table(cut, [78, 22])
    if len(rows) > CAP + 1:
        d.p(f"The {CAP} largest of {len(sols)} solutions are shown; the rest are in the workbook, sheet Solutions.")

    # 11 -----------------------------------------------------------------
    d.h1(f"11. Validation and testing — executed by {client}")
    d.lead("Responsibility split:", f"{client} executes the functional, integration and acceptance testing and provides the sign-off for each wave. "
           "The delivery team operates the migration, provides the test checklists, environments and runbooks, and supports defect triage where the cause is migration-side "
           "(connectivity" + (", secrets" if secrets_on else "") + f", DNS, instance configuration). Application-behaviour defects are triaged with {client}'s team, since there are no application code changes in this phase.")
    d.bullets([f"{len(wl)} workload(s) test-launched on AWS in an isolated security group; each starts without errors.",
               "Per deployable: one read path and one write path work against the AWS database.",
               f"Every internal endpoint in Section {n_addr} resolves and connects.",
               "Each re-keyed third-party integration is called once and succeeds."])

    os.makedirs(os.path.join(OUT, "documents"), exist_ok=True)
    base = os.path.join(OUT, "documents", slug(client) + "-lift-and-shift-assessment")
    try:
        open(base + ".docx", "ab").close()
    except PermissionError:  # the file is open in Word or a viewer: write the new revision beside it instead of failing
        base += f"-rev{meta['revision']}"
        print(f"the document is open in another program: writing {os.path.basename(base)}.docx instead (close the old one and delete it when done)")
    d.save(base + ".docx")

    sheets =[_xlsx.auto("Branches", [["Repository", "Branch assessed", "Last commit", "Why this branch"]] + branch_rows(cfg)),
              _xlsx.auto("Solutions", [["Solution", "Repository", "Projects", "Deployables", "Workloads", "Environments", "Env vars", "Config files", "Internal endpoints", "Static build", "Low (h)", "High (h)"]] +
                         [[lab[s["id"]], s["repo"], len(s["projects"]), len(s["deployables"]), len(s["workloads"]), ", ".join(s["environments"]) or "UNKNOWN",
                           len(s["env_vars"]), len(s["config_files"]), len(s["endpoints"]), bc.get(s["id"], {}).get("static", {}).get("status", ""),
                           round(ests[s["id"]]["low"], 1), round(ests[s["id"]]["high"], 1)] for s in sols]),
              _xlsx.auto("Projects", [["Solution", "Project", "Type", "Framework", "Deployable", "Retarget", "Lines of code"]] +
                         [[lab[s["id"]], p["name"], p.get("type") or "", ", ".join(p.get("frameworks") or []), "yes" if p["deployable"] else "",
                           "yes" if p["name"] in s["retarget_projects"] else "", p["loc"]] for s in sols for p in s["projects"]]),
              _xlsx.auto("Outbound", [["Solution", "To (host or IP)", "Port", "Protocol", "Kind", "Purpose", "Config keys", "Where (file:line)", "What DevOps ensures"]] + register[0]),
              _xlsx.auto("Inbound", [["Solution", "Project", "Listens as", "Source", "What DevOps ensures"]] + register[1]),
              _xlsx.auto("LooseProjects", [["Repository", "Project", "Type", "Framework", "Deployable", "Lines of code"]] +
                         [[x["repo"], x["name"], x.get("type") or "", ", ".join(x.get("frameworks") or []), "yes" if x["deployable"] else "", x["loc"]] for x in (idx.get("loose_projects") or [])]),
              _xlsx.auto("Workloads", [["Workload", "Solution", "Environment", "Deployables", "Deployable names"]] + [[wid, lab[s["id"]], w["environment"], len(w["deployables"]), ", ".join(w["deployables"])] for wid, s, w in wl]),
              _xlsx.auto("Settings", [["Solution", "Kind", "Name"]] +
                         [[lab[s["id"]], "environment variable", v] for s in sols for v in s["env_vars"]] +
                         [[lab[s["id"]], "config file with hard-coded values", f] for s in sols for f in s["config_files"]]),
              _xlsx.auto("ThirdParty", [["Solution", "Component", "Kind", "Vendor", "Key or licence on AWS", "Outbound (app to it)", "Inbound and allow-lists", "Evidence"]] +
                         [[lab[s["id"]], i["name"], i["kind"], i["vendor"], "Re-key" if i["rekey"] else "Confirm licence terms" if i["kind"] == "licensed component" else "Outbound access only", *direction(i["name"], i["kind"]), i["evidence"]]
                          for s in sols for i in tps[s["id"]]["licensed_and_integrations"]]),
              _xlsx.auto("Connections", [["Solution", "To", "Type", "Most likely (inferred from setting names and ports; to be confirmed)", "DevOps servers with that role", "Projects"]] +
                         [[lab[s["id"]], c["to"], c["kind"], role_text(roles.get(c["to"])), (roles.get(c["to"]) or {}).get("devops_servers_with_role") or "", ", ".join(c["projects"])] for s in sols for c in tps[s["id"]]["server_to_server"]] +
                         [[lab_by_repo.get(r, r), o["address"], "public IP", role_text(o), "", ""] for o in roles.values() if o["type"] == "public IP" for r in o.get("solutions_repos") or []]),
              _xlsx.auto("Build", [["Solution", "Result", "Why it fails", "What is needed", "Who provides it", "Notes", "Configuration", "Seconds", "Errors"]] +
                         [[lab[s["id"]], bc.get(s["id"], {}).get("real", {}).get("status", "NOT RUN")] +
                          list(BW.why(bc.get(s["id"], {}).get("static", {}), bc.get(s["id"], {}).get("real", {})) or ("", "", "")) +
                          [BW.note(bc.get(s["id"], {}).get("real", {})), bc.get(s["id"], {}).get("real", {}).get("configuration", ""),
                           bc.get(s["id"], {}).get("real", {}).get("seconds", ""), bc.get(s["id"], {}).get("real", {}).get("error_count", "")] for s in sols]),
              _xlsx.auto("Build detail", [["Solution", "Static check", "Finding or prerequisite", "Real build", "Configuration", "Errors"]] +
                         [[lab[s["id"]], bc.get(s["id"], {}).get("static", {}).get("status", ""), x, bc.get(s["id"], {}).get("real", {}).get("status", "NOT RUN"),
                           bc.get(s["id"], {}).get("real", {}).get("configuration", ""), bc.get(s["id"], {}).get("real", {}).get("error_count", "")]
                          for s in sols for x in (bc.get(s["id"], {}).get("static", {}).get("issues", []) + bc.get(s["id"], {}).get("static", {}).get("prerequisites", []))]),
              _xlsx.auto("DataStores", [["Solution", "Store", "Projects that use it", "Addresses in this repository's config for this store (not a server mapping)"]] +
                         [[a, b, len(m["projects"]), ", ".join(sorted(m["hosts"])) or HELD_OUTSIDE] for (a, b), m in sorted(stores.items())]),
              _xlsx.auto("Estimate", [["Solution", "Work item", "Line", "Count", "Per", "Low (h)", "High (h)", "Basis"]] +
                         [[lab[e["id"]], WORK_LABEL[x["work_item"]], x["label"], x["count"], x["unit"], round(x["low"], 2), round(x["high"], 2),
                           "Sample" if x["basis"] == "sample" else "INFERRED"] for e in est["solutions"] for x in e["lines"]])]
    _xlsx.write(base + ".xlsx", [("Read me", WORKBOOK_READ_ME, [120], [0])] + sheets)
    write_json(os.path.join(OUT, "documents", "built.json"), {"docx": base + ".docx", "xlsx": base + ".xlsx", "revision": meta["revision"], "total": tot,
                                                              "final": bool(final), "lines": [m["label"] for m in lines.values()]})
    print(f"built {base}.docx (revision {meta['revision']}, {'FINAL' if final else 'DRAFT'}) and {base}.xlsx")


if __name__ == "__main__":
    main()
