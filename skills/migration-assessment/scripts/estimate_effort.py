"""Effort and timeline estimate (v3): AI-assisted delivery, hosting and database scenarios, hours and person-days.

    python <skill>/scripts/estimate_effort.py [--engineers 3] [--manual] [--hosting H] [--database D]

Hosting scenarios (estimation.json hosting_scenarios; default from assessment.json scenario.hosting):
  modernize       .NET 10 on Linux containers + managed services, per-application 7R decisions        (default)
  linux-lift      lift-and-shift to EC2 Linux: minimal port to .NET 10, same architecture; Windows-bound apps rehosted on EC2 Windows
  windows-rehost  rehost as-is on EC2 Windows, no code port
Database scenarios (scenario.database; default auto = recommended per database group):
  rds-sqlserver | babelfish | postgresql (full port) | dual (SQL Server + PostgreSQL) | ec2-sqlserver
Model per work package (unit hours; days = hours / 8):
  code  = (conversion + finding remediation) manual-equivalent x ai.code_factor   (+ fixed hours for rehost / retain / retire)
  qa    = (fixed + KLOC x rate) x (1 + extra without tests) x ai.qa_factor x scenario qa_scale
  ops   = per deployable app x ai.ops_factor;  foundation once per estate
  total = (code + qa + ops) x (1 + drift + PM) x (1 + contingency)
PostgreSQL / dual: object conversion (by kind and size + T-SQL constructs) + data-access code changes + tooling + data
migration, x ai.db_factor, + testing share (dual adds provider abstraction and a CI matrix).
Writes assessment/estimate.json: the primary scenario in full, plus a comparison of every hosting and database scenario.
"""
import argparse
import datetime
import math
import os

from _common import OUT, data, load_config, mark_step, read_json, utf8_stdout, write_json
import _findings as F


def lk(r):
    return r[0] + 0.4 * (r[1] - r[0])


def add(a, b, k=1.0):
    return [a[0] + b[0] * k, a[1] + b[1] * k]


def mul(a, f):
    return [a[0] * f[0], a[1] * f[1]]


def r1(x):
    return [round(x[0], 1), round(x[1], 1)]


def finding_hours(f, est):
    if f.get("baseline") or f.get("severity") == "Info":
        return [0.0, 0.0]
    m = est["finding_hours"].get(f.get("effort_key"), est["finding_hours"]["small-change"])
    n = max(int(f.get("occurrences") or 1), 1)
    return [min(m["fixed"][i] + m["per"][i] * (n - 1), max(m["cap"][i], m["fixed"][i])) for i in (0, 1)]


def conversion_hours(p, est):
    t = p.get("type", "unknown")
    rate = est["conversion_hours_per_kloc"].get(t, est["conversion_hours_per_kloc"]["unknown"])
    fixed = est["conversion_fixed_hours"].get(t, est["conversion_fixed_hours"]["default"])
    mr = est.get("markup_hours_per_kloc", {})
    mrate = mr.get(t, mr.get("default", rate))
    code_k = (p.get("loc_handwritten", p.get("loc_code")) or 0) / 1000.0
    mark_k = (p.get("loc_markup") or 0) / 1000.0
    return [fixed[0] + rate[0] * code_k + mrate[0] * mark_k, fixed[1] + rate[1] * code_k + mrate[1] * mark_k]


def qa_kloc(k, q):
    full = q.get("full_rate_kloc", 1e9)
    return min(k, full) + q.get("beyond_rate_factor", 1.0) * max(0.0, k - full)


def postgres_hours(dbi, n_dbs, n_apps_with_data, est, dual=False):
    """Manual-equivalent hours to port a database group (and its data-access code) to PostgreSQL, with a breakdown."""
    pg = est["postgres"]
    objs, cons = [0.0, 0.0], [0.0, 0.0]
    for o in dbi.get("objects", []):
        oh = pg["object_hours"].get(o["kind"], [0.5, 1])
        if isinstance(oh, dict):
            size = "small" if o["lines"] <= 50 else ("medium" if o["lines"] <= 200 else "large")
            oh = oh[size]
        objs = add(objs, oh)
    for k, n in (dbi.get("constructs") or {}).items():
        cons = add(cons, pg["construct_hours"].get(k, [0, 0]), n)
    code = [0.0, 0.0]
    facts = dict(dbi.get("code") or {})
    facts["edmx_function_imports"] = dbi.get("edmx_function_imports", 0)
    for k, n in facts.items():
        code = add(code, pg["code_hours"].get(k, [0, 0]), n)
    per_db = add(pg["per_database"]["tooling_setup"], pg["per_database"]["data_migration"])
    setup = [per_db[0] * n_dbs, per_db[1] * n_dbs]
    conv = add(add(objs, cons), code)
    share = pg["dual"]["testing_share"] if dual else pg["testing_share"]
    extra = [0.0, 0.0]
    if dual:
        extra = add([pg["dual"]["abstraction_per_app"][i] * max(n_apps_with_data, 1) for i in (0, 1)], pg["dual"]["ci_matrix"])
    return {"objects": r1(objs), "constructs": r1(cons), "code": r1(code), "setup_and_data": r1(setup), "dual_extra": r1(extra),
            "conversion": r1(add(conv, extra)), "testing_share": share}


def compute(root, cfg, est, rules, cls, hosting, database, ai_on, engineers):
    HPD = est["hours_per_day"]
    ai = est["ai_assistance"]
    one = [1.0, 1.0]
    code_f, qa_f, ops_f, db_f = (ai["code_factor"], ai["qa_factor"], ai["ops_factor"], ai["db_factor"]) if ai_on else (one, one, one, one)
    hs = est["hosting_scenarios"][hosting]
    mult = est["multipliers"]
    apps = {x["id"]: x for x in cls["applications"]}
    packages, costed, db_packages = [], set(), []
    converted = set()
    notes = []
    for repo in F.repos(root):
        inv = F.load_inventory(root, repo)
        if not inv:
            continue
        scan = read_json(os.path.join(OUT, "scan", f"{repo}.json"), {}) or {}
        fs = sorted(F.assign_apps(F.load(root, repo), inv), key=F.sort_key)
        by_path = {p["path"]: p for p in inv["projects"]}
        shared_paths = {s["path"] for s in inv.get("shared_libraries", [])}
        level = scan.get("activity_level", "quiet")
        drift = mult["parallel_dev_drift"].get(level, mult["parallel_dev_drift"]["quiet"])
        no_tests = (scan.get("tests_per_kloc") or 0) < 2
        repo_apps = [x for x in cls["applications"] if x["repo"] == repo]

        def skip(f, mode, desktop):
            cat = f["category"]
            if mode in ("retire", "repurchase"):
                return True
            if mode == "retain":
                return cat not in rules["retain_relevant_categories"] or (desktop and cat in ("file-handling", "time-culture", "hypervisor", "packages", "build-delivery"))
            if mode == "rehost":
                return cat not in hs.get("keep_categories", rules["retain_relevant_categories"])
            return cat in hs.get("skip_categories", [])

        def work_package(wp_id, name, kind, app=None, proj_list=(), findings=(), mode="port", desktop=False, deployable=False):
            code_manual, lines, fl, excluded, kloc = [0.0, 0.0], [], [], [], 0.0
            for pp in proj_list:
                p = by_path.get(pp)
                if not p or p["type"] == "database" or pp in converted:
                    continue
                converted.add(pp)  # a project referenced by several applications is ported once
                h = conversion_hours(p, est)
                kloc += (p.get("loc_handwritten", p.get("loc_code")) or 0) / 1000.0
                code_manual = add(code_manual, h)
                lines.append({"item": f"Port {p['name']} ({p['type']}, {p.get('loc_code', 0):,} lines) to {cfg.get('target_dotnet')}", "manual_hours": r1(h)})
            fixed_other = [0.0, 0.0]
            if mode in ("retain", "retire", "repurchase", "rehost"):
                key = {"retain": "retain_desktop" if desktop else "retain_server", "rehost": "retain_server", "retire": "retire", "repurchase": "repurchase"}[mode]
                fixed_other = list(est["other_r_hours"][key])
                lines.append({"item": {"retain_desktop": "Repoint service endpoints and repackage the desktop client",
                                       "retain_server": "Rehost as-is on EC2 Windows (IIS): build server, deploy, configuration and connectivity",
                                       "retire": "Decommission and archive (code, data, DNS, licences)",
                                       "repurchase": "Integrate the replacement product (selection and licences excluded)"}[key], "hours": fixed_other})
            for f in findings:
                if f["id"] in costed:
                    continue
                costed.add(f["id"])
                if skip(f, mode, desktop):
                    excluded.append(f["id"])
                    continue
                h = finding_hours(f, est)
                if h[1] <= 0:
                    continue
                code_manual = add(code_manual, h)
                fl.append({"id": f["id"], "rule": f["rule"], "title": f["title"], "severity": f["severity"], "occurrences": f.get("occurrences", 1),
                           "manual_hours": r1(h), "hours": r1(mul(h, code_f))})
            code = add(mul(code_manual, code_f), fixed_other)
            qa_manual = [0.0, 0.0]
            if mode == "port" and kind == "application":
                q = est["qa_hours"]
                qa_manual = [q["fixed"][i] + q["per_kloc"][i] * qa_kloc(kloc, q) for i in (0, 1)]
                if no_tests:
                    qa_manual = [qa_manual[i] * (1 + q["no_tests_extra"][i]) for i in (0, 1)]
                qa_manual = [x * hs.get("qa_scale", 1.0) for x in qa_manual]
            elif mode in ("retain", "rehost") and kind == "application":
                qa_manual = [2.0, 6.0] if desktop else [4.0 * hs.get("qa_scale", 1.0) * 2, 12.0 * hs.get("qa_scale", 1.0) * 2]
            elif kind == "shared":
                qa_manual = [2.0 * len(proj_list), 4.0 * len(proj_list)]
            qa = mul(qa_manual, qa_f)
            ops_manual = list(hs["ops_per_app"]) if deployable else [0.0, 0.0]
            ops = mul(ops_manual, ops_f)
            base = add(add(code, qa), ops)
            conf = (app or {}).get("confidence", "Medium")
            cont = mult["contingency_by_confidence"].get(conf, mult["contingency_by_confidence"]["Medium"])
            over = [drift[i] + mult["project_management"][i] for i in (0, 1)]
            total = [base[i] * (1 + over[i]) * (1 + cont[i]) for i in (0, 1)]
            manual_base = add(add(add(code_manual, fixed_other), qa_manual), ops_manual)
            manual_total = [manual_base[i] * (1 + over[i]) * (1 + cont[i]) for i in (0, 1)]
            likely_h = lk(total)
            band = next(b for b, lim in sorted(((k, v) for k, v in est["complexity_bands"].items() if k != "_doc"), key=lambda x: x[1]) if likely_h / HPD <= lim)
            return {"id": wp_id, "name": name, "kind": kind, "repo": repo, "r7": (app or {}).get("r7"), "mode": mode,
                    "breakdown_hours": {"code": r1(code), "code_manual_equivalent": r1(add(code_manual, fixed_other)), "qa": r1(qa), "operations": r1(ops)},
                    "total_hours": [round(x) for x in total], "likely_hours": round(likely_h), "manual_hours": [round(x) for x in manual_total],
                    "dev_days": r1([x / HPD for x in code]), "total_days": r1([x / HPD for x in total]), "likely_days": round(likely_h / HPD, 1),
                    "manual_days": r1([x / HPD for x in manual_total]), "complexity": band, "confidence": conf,
                    "conversion": lines, "findings": sorted(fl, key=lambda x: -x["hours"][1]), "excluded_findings": excluded,
                    "drivers": [x["title"] for x in sorted(fl, key=lambda x: -x["hours"][1])[:5]]}

        def app_mode(x):
            desktop = x["type"] in rules["desktop_types"]
            base = {"Retire": "retire", "Repurchase": "repurchase", "Retain": "retain", "Rehost": "retain", "Relocate": "retain"}.get(x["r7"], "port")
            if base in ("retire", "repurchase") or desktop:
                return base if not desktop or base in ("retire", "repurchase") else "retain"
            if hs["mode"] == "rehost":
                return "rehost"
            if hs["mode"] == "port":
                blocked = x["type"] in ("aspnet-webforms", "website") or (x["r7"] in ("Rehost", "Retain") and bool(x.get("windows_bound")))
                if blocked:
                    notes.append(f"{x['name']}: Windows-bound ({', '.join(x.get('windows_bound') or [x['type']])}), rehosted on EC2 Windows in this scenario.")
                    return "rehost"
                return "port"
            return base

        modes = {x["id"]: app_mode(x) for x in repo_apps}
        sl = [s["path"] for s in inv.get("shared_libraries", [])]
        if sl and any(m == "port" for m in modes.values()):
            sf = [f for f in fs if set(f.get("projects_in_scope", [])) & set(sl)]
            packages.append(work_package(f"{repo}-shared-libraries", f"{repo}: shared libraries", "shared", None, sl, sf))
        for x in repo_apps:
            own = [p for p in x["projects"] if p not in shared_paths]
            af = [f for f in fs if x["id"] in f.get("apps", []) and f["category"] != "database"]
            desktop = x["type"] in rules["desktop_types"]
            mode = modes[x["id"]]
            packages.append(work_package(x["id"], x["name"], "application", x, own if mode == "port" else [], af, mode, desktop,
                                         deployable=mode in ("port", "retain", "rehost") and not desktop))
        rest = [f for f in fs if f["id"] not in costed and f["category"] != "database"]
        if rest:
            packages.append(work_package(f"{repo}-repository", f"{repo}: repository-wide items", "repository", None, [], rest,
                                         "rehost" if hs["mode"] == "rehost" else "port"))
        # databases: every option, then the selected one
        dbf = [f for f in fs if f["category"] == "database" or f.get("db")]
        dbs = [p for p in inv["projects"] if p["type"] == "database"]
        conns = {(c.get("host"), c.get("database")) for c in scan.get("connection_strings", []) if c.get("database") and not c.get("localdb")}
        names = [p["name"] for p in dbs] or sorted({d for _, d in conns}) or (["(databases referenced by the code)"] if dbf else [])
        if not names:
            continue
        opts = {}
        for target, key in (("rds-sqlserver", "rds-sqlserver"), ("babelfish", "babelfish"), ("ec2-sqlserver", "ec2-sqlserver")):
            base = est["database_hours"][key]
            h = [base[0] * len(names), base[1] * len(names)]
            blockers, limited = [], []
            short = {"rds-sqlserver": "rds", "babelfish": "babelfish", "ec2-sqlserver": "ec2"}[target]
            for f in dbf:
                impact = (f.get("db") or {}).get(short, "ok" if short == "ec2" else None)
                if impact in ("blocker", "limited"):
                    fh = mul(finding_hours(dict(f, baseline=False, severity="Medium"), est), db_f)
                    h = add(h, fh, 1.0 if impact == "blocker" else est["database_hours"]["limited_factor"])
                    (blockers if impact == "blocker" else limited).append(f["rule"])
            opts[target] = {"hours": [round(v) for v in h], "days": r1([v / HPD for v in h]), "likely_hours": round(lk(h)), "likely": round(lk(h) / HPD, 1),
                            "blockers": sorted(set(blockers)), "limited": sorted(set(limited))}
        dbi = scan.get("db_inventory") or {}
        n_data_apps = sum(1 for x in repo_apps if x["r7"] != "Retire" and x["type"] not in rules["desktop_types"])
        for target, dual in (("postgresql", False), ("dual", True)):
            pgh = postgres_hours(dbi, len(names), n_data_apps, est, dual)
            conv = mul(pgh["conversion"], db_f)
            setup = pgh["setup_and_data"]
            test = [conv[i] * pgh["testing_share"][i] for i in (0, 1)]
            h = add(add(conv, setup), test)
            opts[target] = {"hours": [round(v) for v in h], "days": r1([v / HPD for v in h]), "likely_hours": round(lk(h)), "likely": round(lk(h) / HPD, 1),
                            "blockers": [], "limited": [], "breakdown_manual_hours": pgh, "manual_hours": [round(v) for v in add(add(pgh["conversion"], setup), [pgh["conversion"][i] * pgh["testing_share"][i] for i in (0, 1)])]}
        feasible = [t for t in ("babelfish", "rds-sqlserver") if not opts[t]["blockers"]]
        rec = "rds-sqlserver" if "rds-sqlserver" in feasible else "ec2-sqlserver"
        chosen = rec if database == "auto" else database
        note = {"rds-sqlserver": "RDS for SQL Server keeps T-SQL compatibility with the least change.",
                "ec2-sqlserver": "Features unsupported on RDS were found: SQL Server on EC2 (or remediation first).",
                "babelfish": "Babelfish keeps T-SQL and removes SQL Server licensing; validate with Babelfish Compass first.",
                "postgresql": "Full PostgreSQL port: every object and SQL statement is converted (AWS DMS Schema Conversion / SCT + review); removes SQL Server licensing.",
                "dual": est["postgres"]["dual"]["note"]}[chosen]
        if opts["babelfish"]["blockers"] and chosen == "babelfish":
            notes.append(f"{repo}: Babelfish blockers present ({', '.join(opts['babelfish']['blockers'])}); they must be remediated first.")
        db_packages.append({"repo": repo, "databases": names, "connections": sorted(f"{h}/{d}" for h, d in conns), "options": opts, "recommended": rec,
                            "selected": chosen, "note": note, "finding_ids": [f["id"] for f in dbf],
                            "inventory": {"kinds": dbi.get("kinds", {}), "routine_sizes": dbi.get("routine_sizes", {}), "sql_lines": dbi.get("sql_lines", 0),
                                          "constructs": dbi.get("constructs", {}), "code": dbi.get("code", {}), "edmx_function_imports": dbi.get("edmx_function_imports", 0)}})
    fnd_manual = list(hs["foundation"])
    fnd = mul(fnd_manual, ops_f)
    cm = mult["contingency_by_confidence"]["Medium"]
    found_total = [fnd[i] * (1 + mult["project_management"][i]) * (1 + cm[i]) for i in (0, 1)]
    found_manual = [fnd_manual[i] * (1 + mult["project_management"][i]) * (1 + cm[i]) for i in (0, 1)]
    packages.append({"id": "estate-foundation", "name": "AWS foundation: landing zone, networking, CI/CD, observability", "kind": "foundation", "repo": "", "r7": None, "mode": "foundation",
                     "breakdown_hours": {"code": [0, 0], "code_manual_equivalent": [0, 0], "qa": [0, 0], "operations": r1(fnd)}, "total_hours": [round(x) for x in found_total],
                     "likely_hours": round(lk(found_total)), "manual_hours": [round(x) for x in found_manual], "dev_days": [0, 0],
                     "total_days": r1([x / HPD for x in found_total]), "likely_days": round(lk(found_total) / HPD, 1), "manual_days": r1([x / HPD for x in found_manual]),
                     "complexity": "S", "confidence": "Medium", "conversion": [{"item": "Landing zone / accounts, VPC and VPN/Direct Connect, image/AMI or ECR, CI/CD templates, CloudWatch", "hours": r1(fnd)}],
                     "findings": [], "excluded_findings": [], "drivers": []})
    team = est["team"]
    tot_h = [sum(p["total_hours"][i] for p in packages) for i in (0, 1)]
    man_h = [sum(p["manual_hours"][i] for p in packages) for i in (0, 1)]
    db_h = [sum(d["options"][d["selected"]]["hours"][i] for d in db_packages) for i in (0, 1)]
    db_man = [sum(d["options"][d["selected"]].get("manual_hours", d["options"][d["selected"]]["hours"])[i] for d in db_packages) for i in (0, 1)]
    grand_h = add(tot_h, db_h)
    likely_h = lk(grand_h)
    per_week_h = engineers * team["days_per_week"] * team["efficiency"] * HPD
    tl = est["timeline"]
    phases = [{"phase": "Mobilise: access, environments, backlog, test strategy", "start": 0, "weeks": tl["mobilise"]},
              {"phase": "AWS foundation: landing zone, networking, CI/CD, observability", "start": 0, "weeks": tl["landing_zone_and_cicd"]}]
    week = tl["mobilise"]
    shared = [p for p in packages if p["kind"] == "shared"]
    if shared:
        w = max(1, math.ceil(sum(p["likely_hours"] for p in shared) / per_week_h))
        phases.append({"phase": "Shared libraries to netstandard2.0 / multi-target", "start": week, "weeks": w})
        week += w
    order = {"port": 0, "rehost": 1, "retain": 2}
    risk_o = {"Low": 0, "Medium": 1, "High": 2}
    retired = [p for p in packages if p["kind"] == "application" and p.get("mode") == "retire"]
    apps_wp = sorted([p for p in packages if p["kind"] == "application" and p.get("mode") != "retire"],
                     key=lambda p: (order.get(p["mode"], 3), risk_o.get(apps[p["id"]]["risk"], 1), p["likely_hours"]))
    size = tl["wave_size_apps"]
    for i in range(0, len(apps_wp), size):
        wave = apps_wp[i:i + size]
        w = max(1, math.ceil(sum(p["likely_hours"] for p in wave) / per_week_h))
        what = "port, QA, cut-over" if any(p["mode"] == "port" for p in wave) else "rehost / repoint, QA, cut-over"
        phases.append({"phase": f"Wave {i // size + 1}: " + ", ".join(p["name"] for p in wave) + f" ({what})", "start": week, "weeks": w})
        week += max(1, math.ceil(w * 0.7))
    if db_packages:
        w = max(1, math.ceil(lk(db_h) / per_week_h) + 1)
        sel = ", ".join(sorted({d["selected"] for d in db_packages}))
        phases.append({"phase": f"Database migration ({sel}), rehearsals, data cut-over", "start": max(tl["mobilise"], week - w), "weeks": w})
        week = max(week, max(tl["mobilise"], week - w) + w)
    if retired:
        phases.append({"phase": "Retire: " + ", ".join(p["name"] for p in retired) + " (after client confirmation)", "start": tl["mobilise"], "weeks": 1})
    phases.append({"phase": "Hypercare and decommissioning of on-prem servers", "start": week, "weeks": tl["hypercare"]})
    end = max(p["start"] + p["weeks"] for p in phases)
    totals = {"total_hours": [round(x) for x in grand_h], "likely_hours": round(likely_h), "total_days": [round(x / HPD, 1) for x in grand_h],
              "likely_days": round(likely_h / HPD, 1), "manual_equivalent_hours": [round(x) for x in add(man_h, db_man)],
              "manual_equivalent_days": [round(x / HPD, 1) for x in add(man_h, db_man)], "manual_likely_hours": round(lk(add(man_h, db_man))),
              "applications_days": [round(x / HPD, 1) for x in tot_h], "databases_days": [round(x / HPD, 1) for x in db_h],
              "duration_weeks": end, "person_months_likely": round(likely_h / HPD / 20.0, 1)}
    return {"packages": packages, "databases": db_packages, "totals": totals, "timeline": phases, "notes": notes,
            "factors": {"code": code_f, "qa": qa_f, "ops": ops_f, "db": db_f}}


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--engineers", type=int)
    ap.add_argument("--manual", action="store_true", help="ignore AI assistance (manual estimate)")
    ap.add_argument("--hosting", help="modernize | linux-lift | windows-rehost (default: assessment.json scenario.hosting)")
    ap.add_argument("--database", help="auto | rds-sqlserver | babelfish | postgresql | dual | ec2-sqlserver")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    est = data("estimation.json")
    rules = data("decision_rules.json")
    cls = read_json(os.path.join(OUT, "classification.json"))
    if not cls:
        raise SystemExit("run classify_apps.py first")
    sc = cfg.get("scenario") or {}
    hosting = a.hosting or sc.get("hosting") or "modernize"
    database = a.database or sc.get("database") or "auto"
    ai_on = est["ai_assistance"].get("enabled", True) and not a.manual
    engineers = a.engineers or est["team"]["engineers"]
    HPD = est["hours_per_day"]
    main_r = compute(root, cfg, est, rules, cls, hosting, database, ai_on, engineers)
    comparisons = []
    for h in [k for k in est["hosting_scenarios"] if not k.startswith("_")]:
        r = main_r if h == hosting else compute(root, cfg, est, rules, cls, h, database, ai_on, engineers)
        comparisons.append({"kind": "hosting", "id": h, "label": est["hosting_scenarios"][h]["label"], "selected": h == hosting, **{k: r["totals"][k] for k in ("total_hours", "likely_hours", "total_days", "likely_days", "manual_likely_hours", "duration_weeks")}, "notes": r["notes"]})
    for d in ("rds-sqlserver", "ec2-sqlserver", "babelfish", "postgresql", "dual"):
        r = compute(root, cfg, est, rules, cls, hosting, d, ai_on, engineers)
        db = {k: r["totals"][k] for k in ("total_hours", "likely_hours", "total_days", "likely_days", "manual_likely_hours", "duration_weeks")}
        db_only = [sum(x["options"][d]["hours"][i] for x in r["databases"]) for i in (0, 1)]
        comparisons.append({"kind": "database", "id": d, "label": est["database_scenarios"][d], "selected": d == database or (database == "auto" and all(x["selected"] == d for x in main_r["databases"]) and main_r["databases"]),
                            "database_hours": [round(x) for x in db_only], **db, "notes": r["notes"]})
    f = main_r["factors"]
    out = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "model_version": est.get("version"), "engineers": engineers,
           "ai_assisted": ai_on, "ai_code_factor": f["code"], "ai_factors": f, "hours_per_day": HPD,
           "scenario": {"hosting": hosting, "hosting_label": est["hosting_scenarios"][hosting]["label"], "database": database,
                        "database_label": est["database_scenarios"].get(database, "Recommended per database group")},
           "work_packages": main_r["packages"], "databases": main_r["databases"], "totals": main_r["totals"], "timeline": main_r["timeline"],
           "scenario_notes": main_r["notes"], "comparisons": comparisons,
           "assumptions": [f"Scenario: {est['hosting_scenarios'][hosting]['label']}; database: {est['database_scenarios'].get(database, 'recommended target per database group')}.",
                           (f"AI-assisted delivery: code work at {int(f['code'][0] * 100)}–{int(f['code'][1] * 100)}% of manual effort (AWS Transform for .NET / GitHub Copilot app modernization / coding agents), "
                            f"QA at {int(f['qa'][0] * 100)}–{int(f['qa'][1] * 100)}% (generated tests, automated regression; sign-off stays human), operations at {int(f['ops'][0] * 100)}–{int(f['ops'][1] * 100)}% (generated IaC/pipelines), "
                            f"database conversion at {int(f['db'][0] * 100)}–{int(f['db'][1] * 100)}% (AWS DMS Schema Conversion / SCT + agents).") if ai_on else "Manual delivery (no AI assistance).",
                           f"Team of {engineers} engineers at {int(est['team']['efficiency'] * 100)}% efficiency; 1 day = {HPD} hours.",
                           "Covers code and configuration work found in the repositories, QA per application, containers/hosting set-up and an AWS foundation; data volumes, licences and third-party vendor work are excluded unless listed.",
                           "Parallel development drift is priced from the repository's commit rate; Needs-verification findings are assumed real until reviewed."] + main_r["notes"]}
    write_json(os.path.join(OUT, "estimate.json"), out)
    mark_step(root, "estimate")
    t = out["totals"]
    print(f"estimate [{hosting} / {database}] ({'AI-assisted' if ai_on else 'manual'}): {t['total_hours'][0]}-{t['total_hours'][1]} h = {t['total_days'][0]}-{t['total_days'][1]} d "
          f"(likely {t['likely_hours']} h / {t['likely_days']} d; manual likely {t['manual_likely_hours']} h); ~{t['duration_weeks']} weeks with {engineers} engineers")
    for c in comparisons:
        print(f"  {'*' if c['selected'] else ' '} {c['kind']:<8} {c['id']:<15} likely {c['likely_hours']:>6} h ({c['likely_days']:>6} d), manual {c['manual_likely_hours']:>6} h, ~{c['duration_weeks']} wk" +
              (f", db part {c['database_hours'][0]}-{c['database_hours'][1]} h" if c.get("database_hours") else ""))


if __name__ == "__main__":
    main()
