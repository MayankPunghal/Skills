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
    blocked = [s for s in sols if bc.get(s["id"], {}).get("static", {}).get("status") == "BLOCKED"]
    real_fail = [s for s in sols if bc.get(s["id"], {}).get("real", {}).get("status") == "FAIL"]
    wo = windows_only(sols)
    rekey = {}
    for s in sols:
        for i in tps[s["id"]]["licensed_and_integrations"]:
            rekey.setdefault((i["name"], i["kind"]), {"item": i, "solutions": []})["solutions"].append(lab[s["id"]])
    hardcoded = hardcoded_secret_solutions(sols, lab)
    nv, nf = sum(len(s["env_vars"]) for s in sols), sum(len(s["config_files"]) for s in sols)
    nep = sum(len(s["endpoints"]) for s in sols)

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
    d.p("IN SCOPE for this plan:", bold=True)
    d.bullets([f"{WORK_LABEL[k]}: {WORK_DOES[k]}" for k in WORK_LABEL if k in sel] or ["UNKNOWN: no work item selected"])
    rows = [["Environment", "Server", "OS", "Specs", "IP Address", "IIS App Pools"]]
    for e in envs_all or ["UNKNOWN (1 per deployable assumed)"]:
        rows.append([e, "UNKNOWN", ans(it, "windows_versions"), "UNKNOWN", "UNKNOWN", "UNKNOWN"])
    d.table(rows, [22, 14, 14, 14, 18, 18])
    sl = it.get("server_list")
    d.p("Server list: " + {"provided": "provided (" + ans(it, "server_list_detail") + ")", "none": "none exists; server details are UNKNOWN",
                           "later": "exists but not received yet; server details are UNKNOWN"}.get(sl, "UNKNOWN") + ".")
    if envs_unknown:
        d.p("Environments are UNKNOWN or not confirmed: 1 environment per deployable is assumed. Confirm them before this document is finalised.", bold=True)
    opt = [k for k in WORK_LABEL if k not in sel]
    if opt:
        d.p("Optional IN Scope:", bold=True)
        d.bullets([f"{WORK_LABEL[k]}: {WORK_DOES[k]}" for k in opt])
    d.p("NOT in scope: any change to the applications' code or job logic, modernisation, Linux or native AWS services, DevOps and database work (separate teams).")
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
    d.p("Confirmed Workloads as per architecture above", bold=True)
    for wid, s, w in wl[:CAP]:
        d.p(f"{wid} = {lab[s['id']]} / {w['deployable']} ({w['environment']})")
    if len(wl) > CAP:
        d.p(f"Showing {CAP} of {len(wl)} workloads; the full list is in the workbook, sheet Workloads.")
    d.table([["Workload", "R", "Verdict", "Rationale"],
             ["All workloads", "Retire", "Rejected", "The applications are live; no successor system is named."],
             ["All workloads", "Retain", "Rejected", "Staying put keeps the current hosting dependency."],
             ["All workloads", "Rehost", "**Selected — Phase 1", "Same Windows platform and framework; lowest change and risk; no C# change."],
             ["All workloads", "Relocate", "Possible, not selected" if it.get("current_hosting") == "VMware" else "Disqualified" if given(it, "current_hosting") else "UNKNOWN",
              "VMware Cloud on AWS fits a VMware source; Rehost is chosen." if it.get("current_hosting") == "VMware" else
              ("Relocate means VMware Cloud on AWS; the source is " + ans(it, "current_hosting") + ".") if given(it, "current_hosting") else "Applies only to a VMware source; the current hosting is UNKNOWN."],
             ["All workloads", "Replatform", "Rejected as the primary disposition", "Adds change without removing a blocker." + (" The framework retarget is folded into Rehost." if "retarget" in sel else "")],
             ["All workloads", "Refactor", "Deferred", "A separate modernisation effort (migration-assessment)."],
             ["All workloads", "Repurchase", "Rejected", "No purchasable substitute is named."]], [16, 14, 24, 46])
    d.p(f"NOTE: Rehost all {len(wl)} workloads; Replatform only as the optional framework retarget; Refactor explicitly deferred.")

    # 4 ------------------------------------------------------------------
    d.h1("4. Current state")
    d.p("All figures below are counted in the current codebase (VERIFIED):")
    rows = [["Solution", "Repository", "Framework", "Projects", "Deployables", "Lines of code"]]
    for s in sols:
        rows.append([lab[s["id"]], s["repo"], ", ".join(s["frameworks"]) or "?", len(s["projects"]), len(s["deployables"]), s["loc"]])
    cut, n1 = capped(rows[1:], "Solutions")
    d.table([rows[0]] + cut, [26, 26, 14, 10, 12, 12])
    if n1:
        d.p(n1)
    d.p("External integrations and licensed components", bold=True)
    rows = [["Component", "Kind", "Solutions", "Key or licence on AWS"]]
    for (name, kind), m in sorted(rekey.items(), key=lambda x: (not x[1]["item"]["rekey"], x[0])):
        rows.append([name, kind, ", ".join(sorted(set(m["solutions"])))[:60],
                     "Re-key (VERIFIED)" if m["item"]["rekey"] else "Confirm licence terms (UNKNOWN)" if kind == "licensed component" else "Outbound access only"])
    if len(rows) > 1:
        cut, n2 = capped(rows[1:], "ThirdParty")
        d.table([rows[0]] + cut, [30, 18, 30, 22])
        if n2:
            d.p(n2)
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
    d.h2("5.1 Make the build reproducible" + (" — HARD BLOCKER" if blocked or real_fail else ""))
    rows = [["Solution", "Static check", "Real build", "Finding"]]
    for s in sols:
        b = bc.get(s["id"], {})
        st = b.get("static", {})
        if st and st["status"] != "READY":
            rows.append([lab[s["id"]], st["status"], b.get("real", {}).get("status", "NOT RUN"), (st["issues"] or st["prerequisites"] or [""])[0]])
    if len(rows) > 1:
        d.p("The table reflects the current state.")
        cut, n4 = capped(rows[1:], "Solutions")
        d.table([rows[0]] + cut, [24, 16, 12, 48])
        if n4:
            d.p(n4)
    decisions(d, it, [("CI platform today", "ci_platform_today"), ("Windows build agent with MSBuild", "build_agent"), ("Private feeds and GAC references", "private_feeds"),
                      ("Files missing from the repositories", "missing_references")])
    real = [bc.get(s["id"], {}).get("real", {}).get("status", "NOT RUN") for s in sols]
    d.p(f"Real build: {real.count('PASS')} passed, {real.count('FAIL')} failed, {real.count('NOT RUN')} not run" + (" (UNKNOWN until run; it must pass before artifacts are produced)." if "NOT RUN" in real else "."))
    d.h2("5.2 Secrets into Secrets Manager" + (", then rotate — HARD BLOCKER (P0, independent of migration)" if hardcoded else ""))
    if "cicd_secrets" in sel:
        d.p(f"VERIFIED: the code reads {nv} environment variables and {nf} config files hold hard-coded values across {len(sols)} solutions. Names and files (no values): workbook, sheet Settings.")
    else:
        d.p("CI/CD + Secrets Manager is not selected for the dev team in this estimate.")
    if hardcoded:
        d.p(f"Hard-coded credentials found in {len(hardcoded)} solution(s): {', '.join(hardcoded[:8])}{' ...' if len(hardcoded) > 8 else ''}. "
            "They are present in source history and must be treated as compromised; the migration must not copy them into AWS.")
    decisions(d, it, [("Secrets kept today", "existing_vault"), ("Secrets reach the applications by", "secrets_injection"), ("Rotation", "secrets_rotation"),
                      ("Secrets created and supplied by", "secrets_owner"), ("Hard-coded credentials rotated by", "credential_rotation_owner")])
    d.h2("5.3 Connection-string indirection" + (" — HARD BLOCKER" if nep else ""))
    conns = {}
    for s in sols:
        for c in tps[s["id"]]["server_to_server"]:
            conns.setdefault((c["to"], c["kind"]), set()).add(lab[s["id"]])
    d.p(f"VERIFIED: {nep} internal addresses and host names are set in the code and config. Set them to customer-controlled DNS names.")
    rows = [["To", "What is there", "Solutions"]] + [[k[0], k[1], ", ".join(sorted(v))[:70]] for k, v in sorted(conns.items())]
    if len(rows) > 1:
        cut, n5 = capped(rows[1:], "Connections")
        d.table([rows[0]] + cut, [28, 28, 44])
        if n5:
            d.p(n5)
    decisions(d, it, [("Database location", "database_location"), ("Mail from AWS", "mail_relay"), ("Folders and shares", "file_shares"),
                      ("Windows / Active Directory identity", "ad_domain"), ("Third-party IP allow-lists", "ip_allowlists"), ("Machine names, hardware ids, licence servers", "machine_bound"),
                      ("Public DNS and TLS certificates", "public_endpoints")])
    d.h2("5.4 Framework version")
    if "retarget" in sel:
        n = sum(len(s["retarget_projects"]) for s in sols)
        d.p(f"{n} project(s) retarget to .NET Framework {idx['retarget_to']}" + (" (target UNKNOWN until decided)." if idx["retarget_to"] == "unknown" else ". This is a build-level change, not a code change."))
        d.bullets([f"Automated regression tests: {ans(it, 'regression_tests')}."])
    else:
        d.p("Framework retarget is not selected for the dev team in this estimate.")

    # 6 ------------------------------------------------------------------
    chosen = it.get("devops_mechanism") if it.get("devops_mechanism") in ("mgn", "rebuild", "both") else "mgn"
    assumed_mech = it.get("devops_mechanism") not in ("mgn", "rebuild", "both")
    d.h1("6. Migration approach")
    d.p("Option A — AWS Application Migration Service (MGN)", bold=True)
    d.p("Fastest possible exit. It carries every undocumented IIS setting, scheduled task, registry entry and codec, and it does not depend on fixing the build first.")
    d.p("Option B — Rebuild on fresh AMI (deploy from CI onto a clean Windows image)", bold=True)
    d.p("Launch a fresh AWS-provided Windows Server AMI, install IIS and dependencies from a scripted definition, and deploy the application. "
        "Produces a known-clean, reproducible server. Depends on the Section 5 prerequisites being complete and on a reproducible build.")
    d.p("Selected mechanism per workload", bold=True)
    d.p(f"Source operating systems: {ans(it, 'windows_versions')}. MGN support for these versions is checked against the current MGN support matrix.")
    mech_name = {"mgn": "Option A — MGN block-level replication", "rebuild": "Option B — rebuild on fresh AMI", "both": "Option A first, Option B later"}[chosen]
    d.table([["Workload", "Mechanism", "Rationale"],
             ["All workloads", mech_name + (" (INFERRED: assumed for planning)" if assumed_mech else ""),
              "Lowest change and fastest exit; no dependency on the build." if chosen != "rebuild" else "Known-clean reproducible server; needs the Section 5 prerequisites first."]], [22, 44, 34])

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
             ["Connectivity", f"{ans(it, 'aws_connectivity')} to the {len(conns)} internal servers in Section 5.3 until they move; security groups per workload."],
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
    steps_mgn = ["Prerequisites for cutover: build passes (5.1), configuration values and secrets staged (5.2, 5.3).",
                 "MGN agents installed on the source servers; replication reaches the continuous state.",
                 "Test launch (non-disruptive): right-sized instances launched in an isolated security group; the application starts, configuration and connection values are verified.",
                 "Cutover is a DNS event in a maintenance window; the source server stays untouched and running as the rollback target.",
                 f"Post-cutover: {ans(it, 'hypercare_days')} days of CloudWatch observation, then instance-size confirmation; MGN agents removed and replication stopped."]
    steps_rebuild = ["Prerequisites: build passes (5.1), pipeline per solution in place, configuration values and secrets staged.",
                     "Launch a fresh Windows Server AMI; install IIS and dependencies from the scripted definition; deploy the artifact.",
                     "Test launch in an isolated security group; the application starts, configuration and connection values are verified.",
                     "Cutover is a DNS event in a maintenance window; the source server stays untouched and running as the rollback target.",
                     f"Post-cutover: {ans(it, 'hypercare_days')} days of observation, then instance-size confirmation."]
    steps = steps_rebuild if chosen == "rebuild" else steps_mgn
    d.h2(f"8.1 Web deployables ({web})")
    d.bullets((steps + [f"Artifact form: {ans(it, 'artifact_format')}." if "build_artifacts" in sel else "Artifacts: not selected."]) if web else ["No web deployables."])
    d.h2(f"8.2 Windows services and jobs ({ndep - web})")
    d.bullets((steps + [f"Scheduled jobs and services in the test launch: {ans(it, 'job_schedules')}."]) if ndep - web else ["No Windows services or jobs."])
    d.h2("8.3 Sequencing dependency between the workloads")
    shared = sorted(((k, v) for k, v in conns.items() if len(v) > 1), key=lambda x: -len(x[1]))[:5]
    d.p(("The database never moves in Phase 1, so no solution has a hard ordering constraint on another. " if it.get("database_location") == "stay" else
         f"Database location: {ans(it, 'database_location')}; the order of the database move against the applications is to be agreed. ") + "Solutions that connect to the same internal server cut over in the same or consecutive waves, "
        "and the first wave proves the connectivity before anything else cuts over."
        + (" Shared internal servers (VERIFIED): " + "; ".join(f"{k[0]} ({len(v)} solutions)" for k, v in shared) + "." if shared else ""))

    # 9 ------------------------------------------------------------------
    d.h1("9. Wave plan and cutover")
    d.p("Wave rule: " + {"rehearsal_batches": f"a rehearsal wave on the smallest solution, then batches of at most {per_wave} workloads ordered by fewest internal connections",
                         "by_environment": "lower environments first, production last", "single": "one cutover for everything",
                         "other": ans(it, "wave_detail")}.get(strategy, "UNKNOWN")
        + ("" if given(it, "wave_strategy") else " (INFERRED: proposed, not confirmed)") + f". Cutover restrictions: {ans(it, 'maintenance_windows')}.")
    rows = [["Wave", "Content", "Entry criteria", "Exit criteria", "Rollback"],
            ["0 — Foundations", "Connectivity, access and approvals; secrets staged; build verified (5.1).", f"Landing zone: {ans(it, 'aws_landing_zone')}; network approvals in place.",
             f"Every internal endpoint in 5.3 reachable from AWS ({ans(it, 'aws_connectivity')}); secrets staged.", "N/A"]]
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
    d.p("Application Effort Estimates", bold=True)
    lines = {}
    for e in est["solutions"]:
        for x in e["lines"]:
            m = lines.setdefault(x["id"], {"label": x["label"], "unit": x["unit"], "n": 0, "low": 0, "high": 0, "basis": x["basis"], "item": x["work_item"]})
            m["n"] += x["count"]
            m["low"] += x["low"]
            m["high"] += x["high"]
    rows = [["App-side work", "Hours"]]
    for m in lines.values():
        rows.append([f"{m['label']} ({m['n']} {m['unit']}{'' if m['n'] == 1 else 's'})" + (" — INFERRED" if m["basis"] == "inferred" else ""), rng(round(m["low"], 1), round(m["high"], 1))])
    rows.append([f"Contingency buffer (~{est['contingency_pct']}%)", rng(est["contingency"]["low"], est["contingency"]["high"])])
    rows.append([f"**Total (incl. buffer) ≈ {rng(tot['low'], tot['high'])} hours", f"**(~{rng(est['days_low'], est['days_high'])} dev-days)"])
    d.table(rows, [78, 22])
    d.p("Solution-wise breakdown (before buffer)", bold=True)
    ests = {s["id"]: s for s in est["solutions"]}
    rows = [["Solution", "Hours"]]
    for s in sorted(sols, key=lambda x: -ests[x["id"]]["high"]):
        rows.append([lab[s["id"]], rng(round(ests[s["id"]]["low"], 1), round(ests[s["id"]]["high"], 1))])
    cut = rows[:CAP + 1] + [["**All solutions", f"**{rng(est['subtotal']['low'], est['subtotal']['high'])}"]]
    d.table(cut, [78, 22])
    if len(rows) > CAP + 1:
        d.p(f"The {CAP} largest of {len(sols)} solutions are shown; the rest are in the workbook, sheet Solutions.")

    # 11 -----------------------------------------------------------------
    d.h1(f"11. Validation and testing — executed by {(it.get('testing_by') or '').strip() or 'UNKNOWN'}")
    d.lead("Responsibility split:", "functional, integration and acceptance testing and the sign-off are executed by the party named above. "
           "The dev team provides the build, the artifacts and the configuration values, and supports defect triage where the cause is migration-side (connectivity, secrets, DNS, instance configuration). "
           "No application code changes in this phase.")
    decisions(d, it, [("Isolated test environment", "test_environment"), ("Smoke or acceptance test scripts", "smoke_tests"), ("Dev team availability during a cutover", "cutover_support_hours")])
    d.bullets([f"{len(wl)} workload(s) test-launched on AWS in an isolated security group; each starts without errors.",
               "Per deployable: one read path and one write path work against the AWS database.",
               "Every internal endpoint in Section 5.3 resolves and connects.",
               "Each re-keyed third-party integration is called once and succeeds."])

    os.makedirs(os.path.join(OUT, "documents"), exist_ok=True)
    base = os.path.join(OUT, "documents", slug(client) + "-lift-and-shift-assessment")
    d.save(base + ".docx")

    sheets = [_xlsx.auto("Solutions", [["Solution", "Repository", "Projects", "Deployables", "Workloads", "Environments", "Env vars", "Config files", "Internal endpoints", "Static build", "Low (h)", "High (h)"]] +
                         [[lab[s["id"]], s["repo"], len(s["projects"]), len(s["deployables"]), len(s["workloads"]), ", ".join(s["environments"]) or "UNKNOWN",
                           len(s["env_vars"]), len(s["config_files"]), len(s["endpoints"]), bc.get(s["id"], {}).get("static", {}).get("status", ""),
                           round(ests[s["id"]]["low"], 1), round(ests[s["id"]]["high"], 1)] for s in sols]),
              _xlsx.auto("Projects", [["Solution", "Project", "Type", "Framework", "Deployable", "Retarget", "Lines of code"]] +
                         [[lab[s["id"]], p["name"], p.get("type") or "", ", ".join(p.get("frameworks") or []), "yes" if p["deployable"] else "",
                           "yes" if p["name"] in s["retarget_projects"] else "", p["loc"]] for s in sols for p in s["projects"]]),
              _xlsx.auto("Workloads", [["Workload", "Solution", "Deployable", "Environment"]] + [[wid, lab[s["id"]], w["deployable"], w["environment"]] for wid, s, w in wl]),
              _xlsx.auto("Settings", [["Solution", "Kind", "Name"]] +
                         [[lab[s["id"]], "environment variable", v] for s in sols for v in s["env_vars"]] +
                         [[lab[s["id"]], "config file with hard-coded values", f] for s in sols for f in s["config_files"]]),
              _xlsx.auto("ThirdParty", [["Solution", "Component", "Kind", "Vendor", "Key or licence on AWS", "Evidence"]] +
                         [[lab[s["id"]], i["name"], i["kind"], i["vendor"], "Re-key" if i["rekey"] else "Confirm licence terms" if i["kind"] == "licensed component" else "Outbound access only", i["evidence"]]
                          for s in sols for i in tps[s["id"]]["licensed_and_integrations"]]),
              _xlsx.auto("Connections", [["Solution", "To", "What is there", "Projects"]] +
                         [[lab[s["id"]], c["to"], c["kind"], ", ".join(c["projects"])] for s in sols for c in tps[s["id"]]["server_to_server"]]),
              _xlsx.auto("Estimate", [["Solution", "Work item", "Line", "Count", "Per", "Low (h)", "High (h)", "Basis"]] +
                         [[lab[e["id"]], WORK_LABEL[x["work_item"]], x["label"], x["count"], x["unit"], round(x["low"], 2), round(x["high"], 2),
                           "Sample" if x["basis"] == "sample" else "INFERRED"] for e in est["solutions"] for x in e["lines"]])]
    _xlsx.write(base + ".xlsx", sheets)
    write_json(os.path.join(OUT, "documents", "built.json"), {"docx": base + ".docx", "xlsx": base + ".xlsx", "revision": meta["revision"], "total": tot,
                                                              "final": bool(final), "lines": [m["label"] for m in lines.values()]})
    print(f"built {base}.docx (revision {meta['revision']}, {'FINAL' if final else 'DRAFT'}) and {base}.xlsx")


if __name__ == "__main__":
    main()
