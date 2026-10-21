"""Coding-effort estimate (v4): developer hours for code and SQL work only, from lines of code, project type, complexity and findings.

    python <skill>/scripts/estimate_effort.py [--engineers 3] [--manual] [--hosting H] [--database D] [--explain]

Not estimated, on purpose: QA, DevOps / infrastructure, project management, parallel-development drift, contingency, data migration.

Code-side scenarios (assessment.json scenario.hosting, estimation.json hosting_scenarios):
  modernize        convert the .NET Windows applications to .NET 10 on Linux, per-application 7R decisions       (default)
  windows-rehost   lift-and-shift the Windows applications to EC2 Windows: only code / configuration that must change
  lift-and-shift   every server to EC2 with the same OS (Windows to Windows, Linux to Linux): only what must change to
                   land on AWS (keep_categories + keep_rules); chosen by intake.py when the client wants no code port
Database code scenarios (scenario.database):
  dual | postgresql | none   SQL Server + PostgreSQL | PostgreSQL only | keep SQL Server (no database code change)

Per project:   conversion = (fixed + hand-written KLOC x rate[type] + markup KLOC x markup rate) x complexity factor
               complexity factor = decision density band + fan-in + big files + run-time indirection band + reflection,
               clamped (estimation.json "complexity"; indirection from assessment/graphs/<repo>/analysis.json "wiring")
Per finding:   remediation = min(fixed + per x (occurrences - 1), cap) by effort key; baseline findings add nothing
Per package:   hours = (conversion + remediation) x ai.code_factor   (manual-equivalent kept beside it)
Database:      object conversion (kind and size) + parsed T-SQL constructs priced by PostgreSQL conversion level
               (data/pg_conversion.json: auto / rewrite / redesign) + data-access code (parsed embedded SQL, API usage)
               + redesign findings, x ai.db_factor. Findings flagged db_only are priced here only, never in app packages;
               dual adds a provider-neutral data layer per data-using application.
Writes assessment/estimate.json: the selected scenario in full, a comparison of every scenario, and optional modernizations
(shown beside the estimate, never in its total). --explain prints the per-project arithmetic.
"""
import argparse
import datetime
import math
import os

from _common import OUT, data, load_config, mark_step, read_json, utf8_stdout, write_json
import _dbinventory as DBI
import _findings as F
import _montecarlo as MC
import _optional as O


OPTIONAL_CACHE = {}


def lk(r, pos=0.4):
    return r[0] + pos * (r[1] - r[0])


def add(a, b, k=1.0):
    return [a[0] + b[0] * k, a[1] + b[1] * k]


def mul(a, f):
    return [a[0] * f[0], a[1] * f[1]]


def scale(a, k):
    return [a[0] * k, a[1] * k]


def r1(x):
    return [round(x[0], 1), round(x[1], 1)]


def finding_hours(f, est):
    if f.get("baseline") or f.get("severity") == "Info":
        return [0.0, 0.0]
    m = est["finding_hours"].get(f.get("effort_key"), est["finding_hours"]["small-change"])
    n = max(int(f.get("occurrences") or 1), 1)
    return [min(m["fixed"][i] + m["per"][i] * (n - 1), max(m["cap"][i], m["fixed"][i])) for i in (0, 1)]


def complexity_factor(p, fan_in, est, wire=None):
    """Multiplier from decision density, fan-in, big files and run-time indirection; 1.0 when the project is too small to measure."""
    c = est["complexity"]
    cx = p.get("complexity") or {}
    kloc = (p.get("loc_handwritten") or 0) / 1000.0
    if kloc < c["min_kloc"] or not cx:
        return 1.0, "too small to measure"
    dens = cx.get("decisions_per_kloc", 0)
    base = next(f for lim, f in c["decisions_per_kloc_bands"] if dens <= lim)
    extra = min(cx.get("big_files", 0) * c["big_file_extra"], c["big_file_cap"]) + (c["fan_in_extra"] if fan_in >= c["fan_in_threshold"] else 0)
    wire = wire or {}
    ind = round((wire.get("indirect", 0) + wire.get("locators", 0)) / kloc, 1)
    ind_extra = next((f for lim, f in c.get("indirection_per_kloc_bands", []) if ind <= lim), 0.0)
    refl_extra = min(wire.get("reflection", 0) * c.get("reflection_extra", 0), c.get("reflection_cap", 0))
    f = max(c["min"], min(c["max"], base + extra + ind_extra + refl_extra))
    why = f"{dens:g} decisions/KLOC" + (f", {cx['big_files']} big file(s)" if cx.get("big_files") else "") + (f", {fan_in} dependents" if fan_in >= c["fan_in_threshold"] else "") \
        + (f", {ind:g} run-time-bound calls/KLOC" if ind_extra else "") + (f", {wire['reflection']} reflection site(s)" if refl_extra else "")
    return round(f, 2), why


def conversion_hours(p, fan_in, est, wire=None):
    t = p.get("type", "unknown")
    rate = est["conversion_hours_per_kloc"].get(t, est["conversion_hours_per_kloc"]["unknown"])
    fixed = est["conversion_fixed_hours"].get(t, est["conversion_fixed_hours"]["default"])
    mr = est.get("markup_hours_per_kloc", {})
    mrate = mr.get(t, mr.get("default", rate))
    code_k = (p.get("loc_handwritten", p.get("loc_code")) or 0) / 1000.0
    mark_k = (p.get("loc_markup") or 0) / 1000.0
    cf, why = complexity_factor(p, fan_in, est, wire)
    base = [fixed[i] + rate[i] * code_k + mrate[i] * mark_k for i in (0, 1)]
    return scale(base, cf), cf, why, code_k


def postgres_hours(dbi, findings, n_apps_with_data, est, db_f, dual=False, red_f=None, collect=None, pkg=None, pos=0.4):
    """Manual-equivalent and AI-assisted hours to convert one database group (and its data-access code) to PostgreSQL.
    collect (a list) receives the three-point items for the Monte Carlo roll-up, under package id pkg."""
    pg = est["postgres"]
    red_f = red_f or db_f
    objs, cons, code, fnd, fnd_red = [0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]
    redesign, rework = [], []
    items = collect if collect is not None else []

    def item(h, kind, n=1, k=1.0):
        if h[1] > 0:
            items.append({"pkg": pkg, "lo": h[0] * k, "hi": h[1] * k, "kind": kind, "pos": pos, "n": n})
    groups = {}
    for o in dbi.get("objects", []):
        oh = pg["object_hours"].get(o["kind"], [0.25, 0.75])
        band = None
        if isinstance(oh, dict):
            band = "small" if o["lines"] <= 50 else ("medium" if o["lines"] <= 200 else "large")
            oh = oh[band]
        objs = add(objs, oh)
        g = groups.setdefault((o["kind"], band), [oh, 0])
        g[1] += 1
    for oh, n in groups.values():  # objects of one kind and size: independent items priced together
        item(oh, "db", n)
    levels = {"auto": [0.0, 0.0], "rewrite": [0.0, 0.0], "redesign": [0.0, 0.0]}
    for k, n in (dbi.get("constructs") or {}).items():  # parsed construct census, priced by its PostgreSQL conversion level
        c = DBI.conversion(k)
        h = c.get("hours") or pg["construct_hours"].get(k, [0, 0])
        cons = add(cons, h, n)
        levels[c["level"]] = add(levels[c["level"]], h, n)
        item(h, "red" if c["level"] == "redesign" else "db", k=n)  # one construct repeated: the same fix, fully correlated
    for k, n in (dbi.get("code_constructs") or {}).items():  # embedded SQL: statement rewrite is in code_hours; add what has no equivalent
        c = DBI.conversion(k)
        if c["level"] == "redesign":
            cons = add(cons, c["hours"], n)
            levels["redesign"] = add(levels["redesign"], c["hours"], n)
            item(c["hours"], "red", k=n)
    facts = dict(dbi.get("code") or {})
    facts["edmx_function_imports"] = dbi.get("edmx_function_imports", 0)
    for k, n in facts.items():
        code = add(code, pg["code_hours"].get(k, [0, 0]), n)
        item(pg["code_hours"].get(k, [0, 0]), "db", k=n)
    for f in findings:
        impact = (f.get("db") or {}).get("pg")
        if impact in ("redesign", "rework"):
            (redesign if impact == "redesign" else rework).append(f["rule"])
            if (f.get("db") or {}).get("priced_by_inventory"):  # already in the construct hours above
                continue
            fh = finding_hours(dict(f, baseline=False, severity="Medium"), est)
            fnd = add(fnd, fh, 1.0 if impact == "redesign" else 0.5)
            item(fh, "red" if impact == "redesign" else "db", k=1.0 if impact == "redesign" else 0.5)
            if impact == "redesign":
                fnd_red = add(fnd_red, fh)
    extra = [pg["dual"]["abstraction_per_app"][i] * max(n_apps_with_data, 1) for i in (0, 1)] if dual else [0.0, 0.0]
    item(extra, "red")
    manual = add(add(add(objs, cons), add(code, fnd)), extra)
    red = add(add(levels["redesign"], fnd_red), extra)  # no mechanical path: the redesign AI factor applies
    mech = [max(manual[i] - red[i], 0.0) for i in (0, 1)]
    hours = add(mul(mech, db_f), mul(red, red_f))
    return {"objects": r1(objs), "constructs": r1(cons), "construct_levels": {k: r1(v) for k, v in levels.items()},
            "code": r1(code), "findings": r1(fnd), "dual_extra": r1(extra), "manual": r1(manual), "manual_redesign": r1(red),
            "hours": r1(hours), "redesign": sorted(set(redesign)), "rework": sorted(set(rework))}


RANGE_LABEL = "P10-P90"


def db_work_items(d):
    """The selected database option split into plannable parts, in build order, sharing its P50 by manual-hours weight."""
    o = d["options"][d["selected"]]
    b = o.get("breakdown_manual_hours") or {}
    inv = d.get("inventory") or {}
    n_obj = sum((inv.get("kinds") or {}).values())
    lv = b.get("construct_levels") or {}
    parts = [("dual_extra", "provider-neutral data layer for the applications (dual database)"),
             ("objects", f"convert {n_obj} database objects (tables, views, routines, triggers, types)" if n_obj else "convert database objects"),
             ("constructs", "rewrite / redesign T-SQL constructs PostgreSQL cannot run as written"
                            + (f" ({lk(lv.get('redesign', [0, 0]), 0.5):.0f} h of redesign at manual rates)" if lk(lv.get("redesign", [0, 0]), 0.5) else "")),
             ("code", "data-access code: embedded SQL, stored-procedure calls and provider APIs in C#"),
             ("findings", "database findings (redesign / rework)")]
    weights = [(label, lk(b.get(k) or [0, 0], 0.5)) for k, label in parts]
    tot = sum(w for _, w in weights)
    if not tot:
        return [(f"{d['repo']}: database code ({d['selected']})", o["likely_hours"])]
    return [(f"{d['repo']}: {label}", o["likely_hours"] * w / tot) for label, w in weights if w > 0]


def sprint_plan(app_queue, db_work, engineers, est, start_date=None, p80_ratio=1.0):
    """Coding sprints from the day of codebase access. app_queue: [(name, P50 hours)] in dependency order; db_work: [(name, hours)]
    run in its own lane (estimation.json sprints.db_engineers) when there are 2+ engineers, else after the application work.
    Leftover capacity of a finished lane flows to the other one. Planned at P50; sprints_p80 says how many sprints P80 needs."""
    sp, team, HPD = est.get("sprints") or {}, est["team"], est["hours_per_day"]
    weeks = int(sp.get("length_weeks", 2))
    per_eng = team["days_per_week"] * weeks * HPD * team["efficiency"]
    db_eng = min(int(sp.get("db_engineers", 1)), max(engineers - 1, 0)) if db_work else 0
    onboard_h = sp.get("onboarding_days", 0) * HPD * team["efficiency"]
    apps = [[n, float(h)] for n, h in app_queue if h > 0]
    dbs = [[n, float(h)] for n, h in db_work if h > 0]
    if not db_eng:
        apps, dbs = apps + dbs, []
    totals = {n: h for n, h in apps + dbs}
    done = {n: 0.0 for n in totals}
    start = None
    if start_date:
        try:
            start = datetime.date.fromisoformat(str(start_date))
        except ValueError:
            start = None
    plan, k, ob_left = [], 0, onboard_h
    while (apps or dbs) and k < 200:
        k += 1
        ob = min(ob_left, per_eng)  # onboarding: clone, restore, baseline build, existing tests (spills over if longer than a sprint)
        ob_left -= ob
        cap_eng = per_eng - ob
        cap_db = min(db_eng * cap_eng, sum(h for _, h in dbs)) if dbs else 0.0
        cap_app = engineers * cap_eng - cap_db
        rows = []

        def take(queue, cap, lane):
            while queue and cap > 1e-6:
                n, h = queue[0]
                use = min(h, cap)
                cap -= use
                queue[0][1] -= use
                done[n] += use
                rows.append({"lane": lane, "work": n, "hours": round(use), "status": "complete" if queue[0][1] <= 1e-6 else
                             f"{int(100 * done[n] / totals[n])}% done"})
                if queue[0][1] <= 1e-6:
                    queue.pop(0)
            return cap
        left = take(apps, cap_app, "application")
        left = take(dbs, left + cap_db, "database") if dbs else left
        if left > 1e-6 and apps:
            take(apps, left, "application")
        s = {"sprint": k, "weeks": f"{(k - 1) * weeks + 1}-{k * weeks}", "capacity_hours": round(engineers * cap_eng),
             "planned_hours": sum(r["hours"] for r in rows), "items": rows}
        if ob:
            s["onboarding"] = f"{sp.get('onboarding_days')} day(s): codebase access, clone, restore, baseline build and existing tests on the current stack"
        if start:
            s["start"] = (start + datetime.timedelta(weeks=(k - 1) * weeks)).isoformat()
            s["end"] = (start + datetime.timedelta(weeks=k * weeks, days=-1)).isoformat()
        plan.append(s)
    cap_all = engineers * per_eng
    last = plan[-1] if plan else None
    w50 = (len(plan) - 1) * weeks + max(1, math.ceil(weeks * last["planned_hours"] / max(last["capacity_hours"], 1))) if last else 0
    w80 = max(w50, math.ceil(w50 * p80_ratio))  # the same plan with every package at its P80
    n80 = max(len(plan), math.ceil(w80 / weeks))
    out = {"length_weeks": weeks, "engineers": engineers, "db_engineers": db_eng, "capacity_per_sprint_hours": round(cap_all),
           "onboarding_days": sp.get("onboarding_days", 0), "start_date": start.isoformat() if start else None, "planned_at": "P50",
           "sprints_p50": len(plan), "sprints_p80": n80, "weeks_p50": w50, "weeks_p80": w80, "plan": plan}
    if start:
        out["end_p50"] = (start + datetime.timedelta(weeks=len(plan) * weeks, days=-1)).isoformat()
        out["end_p80"] = (start + datetime.timedelta(weeks=n80 * weeks, days=-1)).isoformat()
    return out


def rollup(items, packages, db_packages, est, factors):
    """Replace the sum-of-lows / sum-of-highs ranges with Monte Carlo percentiles (P10-P90 range, P50 likely, P80 commitment).
    The sums stay as bounds_hours (extremes nobody should plan on). Returns (AI-assisted total, manual total, samples by package)."""
    cfg = est.get("rollup") or {}
    HPD = est["hours_per_day"]
    one = [1.0, 1.0]
    sim = MC.simulate(items, factors, cfg)
    man = MC.simulate(items, {"code": one, "red": one, "db": one}, cfg)
    empty = {"p10": 0.0, "p50": 0.0, "p80": 0.0, "p90": 0.0, "mean": 0.0}

    def stats(samples, pkg):
        return MC.summary(samples[pkg]) if pkg in samples else empty
    for p in packages:
        a, m = stats(sim, p["id"]), stats(man, p["id"])
        p["bounds_hours"], p["manual_bounds_hours"] = p["total_hours"], p["manual_hours"]
        p.update({"total_hours": [round(a["p10"]), round(a["p90"])], "likely_hours": round(a["p50"]), "p80_hours": round(a["p80"]),
                  "manual_hours": [round(m["p10"]), round(m["p90"])], "manual_likely_hours": round(m["p50"]),
                  "total_days": r1([a["p10"] / HPD, a["p90"] / HPD]), "likely_days": round(a["p50"] / HPD, 1),
                  "manual_days": r1([m["p10"] / HPD, m["p90"] / HPD])})
        p["complexity"] = next(b for b, lim in sorted(((k, v) for k, v in est["complexity_bands"].items() if k != "_doc"), key=lambda x: x[1])
                               if a["p50"] / HPD <= lim)
    for d in db_packages:
        for o in d["options"].values():
            a, m = stats(sim, o["pkg"]), stats(man, o["pkg"])
            o["bounds_hours"], o["manual_bounds_hours"] = o["hours"], o["manual_hours"]
            o.update({"hours": [round(a["p10"]), round(a["p90"])], "days": r1([a["p10"] / HPD, a["p90"] / HPD]), "likely_hours": round(a["p50"]),
                      "likely": round(a["p50"] / HPD, 1), "p80_hours": round(a["p80"]), "manual_hours": [round(m["p10"]), round(m["p90"])],
                      "manual_likely_hours": round(m["p50"])})
    chosen = [p["id"] for p in packages] + [d["options"][d["selected"]]["pkg"] for d in db_packages if d["selected"] != "none"]
    ai_s, man_s = MC.total(sim, chosen), MC.total(man, chosen)
    return (MC.summary(ai_s) if ai_s else empty), (MC.summary(man_s) if man_s else empty), sim


def compute(root, cfg, est, rules, cls, hosting, database, ai_on, engineers, explain=False, start_date=None):
    HPD = est["hours_per_day"]
    pos = est["likely_position"]
    ai = est["ai_assistance"]
    one = [1.0, 1.0]
    code_f, db_f = (ai["code_factor"], ai["db_factor"]) if ai_on else (one, one)
    red_f = ai.get("redesign_factor", code_f) if ai_on else one
    red_keys, red_types = set(ai.get("redesign_effort_keys", [])), set(ai.get("redesign_project_types", []))
    sc = est.get("scale") or {}
    pos_by_repo, scale_by_repo = {}, {}
    hs = est["hosting_scenarios"][hosting]
    apps = {x["id"]: x for x in cls["applications"]}
    packages, costed, db_packages, optional = [], set(), [], []
    converted = set()
    notes, explain_rows = [], []
    items = []  # three-point items for the Monte Carlo roll-up (_montecarlo.py)
    for repo in F.repos(root):
        inv = F.load_inventory(root, repo)
        if not inv:
            continue
        scan = read_json(os.path.join(OUT, "scan", f"{repo}.json"), {}) or {}
        fs = sorted(F.assign_apps(F.load(root, repo), inv), key=F.sort_key)
        by_path = {p["path"]: p for p in inv["projects"]}
        shared_paths = {s["path"] for s in inv.get("shared_libraries", [])}
        fan_in = {p["path"]: 0 for p in inv["projects"]}
        wiring = ((read_json(os.path.join(OUT, "graphs", repo, "analysis.json"), {}) or {}).get("wiring") or {}).get("per_project", {})
        norm = {k.replace("\\", "/").lower(): k for k in by_path}
        for p in inv["projects"]:
            if p.get("type") == "test":
                continue  # a test project referencing a library does not make it a shared dependency
            for ref in p.get("project_references", []):
                t = norm.get(ref.replace("\\", "/").lower())
                if t:
                    fan_in[t] += 1
        repo_apps = [x for x in cls["applications"] if x["repo"] == repo]
        repo_kloc = sum((p.get("loc_handwritten") or 0) for p in inv["projects"] if p.get("type") not in ("test", "database")) / 1000.0
        rscale = max(1.0, (repo_kloc / sc["reference_kloc"]) ** sc["exponent"]) if sc and repo_kloc else 1.0
        rpos = est.get("likely_position_large", pos) if sc and repo_kloc >= sc.get("large_kloc", 10 ** 9) else pos
        scale_by_repo[repo], pos_by_repo[repo] = round(rscale, 3), rpos
        if rscale > 1.0:
            notes.append(f"{repo}: {repo_kloc:,.0f} KLOC, so project conversion hours are scaled by {rscale:.2f} (diseconomy of scale, COCOMO II)"
                         + (f" and 'likely' sits {int(rpos * 100)}% of the way from low to high." if rpos != pos else "."))
        if repo not in OPTIONAL_CACHE:  # the scan does not depend on the scenario; compute() runs once per scenario
            OPTIONAL_CACHE[repo] = O.scan_repo(inv["root"], inv)
        optional += [dict(o, repo=repo) for o in OPTIONAL_CACHE[repo]]

        def skip(f, mode, desktop):
            cat = f["category"]
            if mode in ("retire", "repurchase"):
                return True
            if mode == "retain":
                return cat not in rules["retain_relevant_categories"] or (desktop and cat in ("file-handling", "time-culture", "hypervisor", "packages", "build-delivery"))
            if mode == "rehost":
                return cat not in hs.get("keep_categories", rules["retain_relevant_categories"]) and f["rule"].split(":")[0] not in hs.get("keep_rules", [])
            return cat in hs.get("skip_categories", [])

        def work_package(wp_id, name, kind, app=None, proj_list=(), findings=(), mode="port", desktop=False):
            code_manual, lines, fl, excluded = [0.0, 0.0], [], [], []
            red_manual = [0.0, 0.0]  # part of code_manual with no mechanical path (redesign AI factor)
            for pp in proj_list:
                p = by_path.get(pp)
                if not p or p["type"] == "database" or pp in converted:
                    continue
                converted.add(pp)  # a project referenced by several applications is ported once
                h, cf, why, kloc = conversion_hours(p, fan_in.get(pp, 0), est, wiring.get(pp))
                h = scale(h, rscale)
                code_manual = add(code_manual, h)
                items.append({"pkg": wp_id, "lo": h[0], "hi": h[1], "kind": "red" if p["type"] in red_types else "code", "pos": rpos})
                if p["type"] in red_types:
                    red_manual = add(red_manual, h)
                lines.append({"item": f"Port {p['name']} ({p['type']}, {p.get('loc_code', 0):,} lines) to {cfg.get('target_dotnet')}", "manual_hours": r1(h),
                              "kloc": round(kloc, 2), "markup_kloc": round((p.get("loc_markup") or 0) / 1000.0, 2), "complexity_factor": cf,
                              "complexity_why": why, "size_factor": round(rscale, 3)})
                explain_rows.append((name, p["name"], p["type"], round(kloc, 2), cf, why, r1(h)))
            fixed_other = [0.0, 0.0]
            if mode in ("retain", "retire", "repurchase", "rehost"):
                key = {"retain": "retain_desktop" if desktop else "retain_server", "rehost": "retain_server", "retire": "retire", "repurchase": "repurchase"}[mode]
                fixed_other = list(est["other_r_hours"][key])
                items.append({"pkg": wp_id, "lo": fixed_other[0], "hi": fixed_other[1], "kind": "fixed", "pos": rpos})
                lines.append({"item": {"retain_desktop": "Repoint service endpoints in the desktop client",
                                       "retain_server": "Repoint connection strings, endpoints and identity settings for the new network (code and configuration only)",
                                       "retire": "Remove the application (code, configuration, references)",
                                       "repurchase": "Write the integration code for the replacement product (selection and licences excluded)"}[key], "manual_hours": fixed_other})
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
                is_red = f.get("effort_key") in red_keys or (f.get("db") or {}).get("pg") == "redesign"
                if is_red:
                    red_manual = add(red_manual, h)
                items.append({"pkg": wp_id, "lo": h[0], "hi": h[1], "kind": "red" if is_red else "code", "pos": rpos})
                fl.append({"id": f["id"], "rule": f["rule"], "title": f["title"], "severity": f["severity"], "occurrences": f.get("occurrences", 1),
                           "manual_hours": r1(h), "hours": r1(mul(h, red_f if is_red else code_f)), "redesign": is_red})
            manual = add(code_manual, fixed_other)
            mech_manual = [max(code_manual[i] - red_manual[i], 0.0) for i in (0, 1)]
            code = add(add(mul(mech_manual, code_f), mul(red_manual, red_f)), fixed_other)  # fixed config work is not accelerated
            likely_h = lk(code, rpos)
            band = next(b for b, lim in sorted(((k, v) for k, v in est["complexity_bands"].items() if k != "_doc"), key=lambda x: x[1]) if likely_h / HPD <= lim)
            return {"id": wp_id, "name": name, "kind": kind, "repo": repo, "r7": (app or {}).get("r7"), "mode": mode,
                    "breakdown_hours": {"code": r1(code), "code_manual_equivalent": r1(manual)},
                    "total_hours": [round(x) for x in code], "likely_hours": round(likely_h), "manual_hours": [round(x) for x in manual],
                    "manual_likely_hours": round(lk(manual, rpos)), "redesign_manual_hours": [round(x) for x in red_manual],
                    "total_days": r1([x / HPD for x in code]), "likely_days": round(likely_h / HPD, 1), "manual_days": r1([x / HPD for x in manual]),
                    "complexity": band, "confidence": (app or {}).get("confidence", "Medium"),
                    "conversion": lines, "findings": sorted(fl, key=lambda x: -x["hours"][1]), "excluded_findings": excluded,
                    "drivers": [x["title"] for x in sorted(fl, key=lambda x: -x["hours"][1])[:5]]}

        def app_mode(x):
            desktop = x["type"] in rules["desktop_types"]
            base = {"Retire": "retire", "Repurchase": "repurchase", "Retain": "retain", "Rehost": "retain", "Relocate": "retain"}.get(x["r7"], "port")
            if base in ("retire", "repurchase") or desktop:
                return base if not desktop or base in ("retire", "repurchase") else "retain"
            return "rehost" if hs["mode"] == "rehost" else base

        modes = {x["id"]: app_mode(x) for x in repo_apps}
        sl = [s["path"] for s in inv.get("shared_libraries", [])]
        if sl and any(m == "port" for m in modes.values()):
            sf = [f for f in fs if set(f.get("projects_in_scope", [])) & set(sl)]
            packages.append(work_package(f"{repo}-shared-libraries", f"{repo}: shared libraries", "shared", None, sl, sf))
        for x in repo_apps:
            own = [p for p in x["projects"] if p not in shared_paths]
            af = [f for f in fs if x["id"] in f.get("apps", []) and f["category"] != "database" and not f.get("db_only")]
            mode = modes[x["id"]]
            packages.append(work_package(x["id"], x["name"], "application", x, own if mode == "port" else [], af, mode, x["type"] in rules["desktop_types"]))
        rest = [f for f in fs if f["id"] not in costed and f["category"] != "database" and not f.get("db_only")]
        if rest:
            packages.append(work_package(f"{repo}-repository", f"{repo}: repository-wide items", "repository", None, [], rest, "rehost" if hs["mode"] == "rehost" else "port"))
        # database code: every scenario, then the selected one
        dbf = [f for f in fs if f["category"] == "database" or f.get("db")]
        dbs = [p for p in inv["projects"] if p["type"] == "database"]
        conns = {(c.get("host"), c.get("database")) for c in scan.get("connection_strings", []) if c.get("database") and not c.get("localdb")}
        names = [p["name"] for p in dbs] or sorted({d for _, d in conns}) or (["(databases referenced by the code)"] if dbf else [])
        if not names:
            continue
        dbi = scan.get("db_inventory") or {}
        n_data_apps = sum(1 for x in repo_apps if x["r7"] != "Retire" and x["type"] not in rules["desktop_types"])
        opts = {}
        for target, dual in (("postgresql", False), ("dual", True)):
            pgh = postgres_hours(dbi, dbf, n_data_apps, est, db_f, dual, red_f, items, f"db:{repo}:{target}", rpos)
            h = pgh["hours"]
            opts[target] = {"pkg": f"db:{repo}:{target}", "hours": [round(v) for v in h], "days": r1([v / HPD for v in h]), "likely_hours": round(lk(h, rpos)), "likely": round(lk(h, rpos) / HPD, 1),
                            "manual_likely_hours": round(lk(pgh["manual"], rpos)),
                            "manual_hours": [round(v) for v in pgh["manual"]], "redesign": pgh["redesign"], "rework": pgh["rework"], "breakdown_manual_hours": pgh}
        chosen = database if database in ("postgresql", "dual", "none") else "dual"
        note = {"postgresql": "PostgreSQL only: every object and SQL statement is converted (AWS DMS Schema Conversion + review) and SQL Server is removed.",
                "dual": est["postgres"]["dual"]["note"], "none": "SQL Server stays: no database code change is estimated."}[chosen]
        db_packages.append({"repo": repo, "databases": names, "connections": sorted(f"{h}/{d}" for h, d in conns), "options": opts,
                            "recommended": "dual", "selected": chosen, "note": note, "finding_ids": [f["id"] for f in dbf],
                            "inventory": {"kinds": dbi.get("kinds", {}), "routine_sizes": dbi.get("routine_sizes", {}), "sql_lines": dbi.get("sql_lines", 0),
                                          "constructs": dbi.get("constructs", {}), "code": dbi.get("code", {}), "edmx_function_imports": dbi.get("edmx_function_imports", 0),
                                          "engine": dbi.get("engine"), "conversion": dbi.get("conversion", {}), "code_constructs": dbi.get("code_constructs", {}),
                                          "redesign_items": dbi.get("redesign_items", []), "parse_errors": dbi.get("parse_errors", []),
                                          "code_sql_stats": dbi.get("code_sql_stats", {}), "note": dbi.get("note")}})
    ai_t, man_t, sim = rollup(items, packages, db_packages, est, {"code": code_f, "red": red_f, "db": db_f})
    team = est["team"]
    tot_h = [sum(p["bounds_hours"][i] for p in packages) for i in (0, 1)]
    man_h = [sum(p["manual_bounds_hours"][i] for p in packages) for i in (0, 1)]

    def sel(d, key, default):
        return d["options"][d["selected"]][key] if d["selected"] != "none" else default
    db_h = [sum(sel(d, "bounds_hours", [0, 0])[i] for d in db_packages) for i in (0, 1)]
    db_man = [sum(sel(d, "manual_bounds_hours", [0, 0])[i] for d in db_packages) for i in (0, 1)]
    grand_h, grand_man = add(tot_h, db_h), add(man_h, db_man)  # every low added / every high added: extremes, not a forecast
    db_likely = sum(sel(d, "likely_hours", 0) for d in db_packages)
    likely_h, manual_likely = ai_t["p50"], man_t["p50"]
    per_week_h = engineers * team["days_per_week"] * team["efficiency"] * HPD
    tl = est["timeline"]
    phases, week = [], 0
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
        what = "port and fix" if any(p["mode"] == "port" for p in wave) else "repoint"
        phases.append({"phase": f"Wave {i // size + 1}: " + ", ".join(p["name"] for p in wave) + f" ({what})", "start": week, "weeks": w})
        week += max(1, math.ceil(w * (1 - tl["wave_overlap"])))
    if any(d["selected"] != "none" for d in db_packages) and db_likely > 0:
        w = max(1, math.ceil(db_likely / per_week_h))
        sel_names = ", ".join(sorted({d["selected"] for d in db_packages if d["selected"] != "none"}))
        phases.append({"phase": f"Database code conversion ({sel_names})", "start": max(0, week - w), "weeks": w})
        week = max(week, max(0, week - w) + w)
    repo_wide = [p for p in packages if p["kind"] == "repository"]
    if repo_wide and sum(p["likely_hours"] for p in repo_wide):
        phases.append({"phase": "Repository-wide items (configuration, build, cross-cutting findings)", "start": 0,
                       "weeks": max(1, math.ceil(sum(p["likely_hours"] for p in repo_wide) / per_week_h))})
    if retired:
        phases.append({"phase": "Remove: " + ", ".join(p["name"] for p in retired) + " (after client confirmation)", "start": 0, "weeks": 1})
    queue = [(p["name"], p["likely_hours"]) for p in shared + repo_wide + apps_wp + retired]
    db_work = [w for d in db_packages if d["selected"] != "none" for w in db_work_items(d)]
    sprints = sprint_plan(queue, db_work, engineers, est, start_date, ai_t["p80"] / likely_h if likely_h else 1.0)
    end = sprints["weeks_p50"] if sprints["plan"] else max([p["start"] + p["weeks"] for p in phases] or [0])
    kloc_all = sum((p.get("loc_code") or 0) for r in F.repos(root) for p in (F.load_inventory(root, r) or {"projects": []})["projects"]) / 1000.0
    opt_rows = []
    for o in optional:
        manual, assisted = O.hours(o, code_f)
        opt_rows.append(dict(o, manual_hours=r1(manual), hours=r1(assisted), likely_hours=round(lk(assisted, pos), 1)))
    opt_tot = [round(sum(o["hours"][i] for o in opt_rows)) for i in (0, 1)]
    rng_h, rng_man = [ai_t["p10"], ai_t["p90"]], [man_t["p10"], man_t["p90"]]
    opt_in = (cfg.get("intake") or {}).get("aws_native") == "now"  # intake: replace servers with AWS managed services in this engagement
    if opt_in and opt_rows:
        opt_likely = sum(o["likely_hours"] for o in opt_rows)
        rng_h = [rng_h[0] + opt_tot[0], rng_h[1] + opt_tot[1]]
        likely_h += opt_likely
        ai_t = dict(ai_t, p80=ai_t["p80"] + lk(opt_tot, 0.8))
        grand_h = add(grand_h, opt_tot)
        notes.append(f"AWS managed-service replacements are in scope (intake): {opt_tot[0]}-{opt_tot[1]} h added to the total "
                     f"(likely {round(opt_likely)} h); the sprint plan does not include them yet.")
    app_t = MC.summary(MC.total(sim, [p["id"] for p in packages]) or [0.0])
    db_t = MC.summary(MC.total(sim, [d["options"][d["selected"]]["pkg"] for d in db_packages if d["selected"] != "none"]) or [0.0])
    totals = {"total_hours": [round(x) for x in rng_h], "likely_hours": round(likely_h), "total_days": [round(x / HPD, 1) for x in rng_h],
              "likely_days": round(likely_h / HPD, 1), "p80_hours": round(ai_t["p80"]), "p80_days": round(ai_t["p80"] / HPD, 1),
              "range_method": RANGE_LABEL, "bounds_hours": [round(x) for x in grand_h], "bounds_days": [round(x / HPD, 1) for x in grand_h],
              "manual_equivalent_hours": [round(x) for x in rng_man], "manual_equivalent_days": [round(x / HPD, 1) for x in rng_man],
              "manual_bounds_hours": [round(x) for x in grand_man], "manual_likely_hours": round(manual_likely),
              "applications_days": [round(app_t["p10"] / HPD, 1), round(app_t["p90"] / HPD, 1)],
              "databases_days": [round(db_t["p10"] / HPD, 1), round(db_t["p90"] / HPD, 1)],
              "duration_weeks": end, "duration_weeks_p80": sprints.get("weeks_p80", end),
              "person_months_likely": round(likely_h / HPD / 20.0, 1),
              "kloc": round(kloc_all, 1), "likely_hours_per_kloc": round(likely_h / kloc_all, 2) if kloc_all else 0,
              "optional_hours": opt_tot, "optional_in_scope": bool(opt_in and opt_rows)}
    return {"packages": packages, "databases": db_packages, "totals": totals, "timeline": phases, "sprints": sprints, "notes": notes, "optional": opt_rows,
            "factors": {"code": code_f, "db": db_f, "redesign": red_f}, "scale": scale_by_repo, "likely_position": pos_by_repo, "explain": explain_rows}


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--engineers", type=int)
    ap.add_argument("--manual", action="store_true", help="ignore AI assistance (manual estimate)")
    ap.add_argument("--hosting", help="modernize | windows-rehost | lift-and-shift (default: assessment.json scenario.hosting)")
    ap.add_argument("--database", help="dual | postgresql | none (default: assessment.json scenario.database)")
    ap.add_argument("--explain", action="store_true", help="print the per-project arithmetic")
    ap.add_argument("--start-date", help="day the team gets codebase access, YYYY-MM-DD (default: assessment.json scenario.start_date)")
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
    database = a.database or sc.get("database") or "dual"
    if database == "auto":  # setup_assessment.py's placeholder when no database scenario was chosen
        database = "dual"
    if hosting not in est["hosting_scenarios"] or hosting.startswith("_"):
        raise SystemExit(f"unknown hosting scenario '{hosting}': use {', '.join(k for k in est['hosting_scenarios'] if not k.startswith('_'))} (assessment.json scenario.hosting)")
    if database not in ("dual", "postgresql", "none"):
        raise SystemExit(f"unknown database scenario '{database}': use dual, postgresql or none (assessment.json scenario.database)")
    ai_on = est["ai_assistance"].get("enabled", True) and not a.manual
    engineers = a.engineers or sc.get("engineers") or est["team"]["engineers"]
    HPD = est["hours_per_day"]
    start_date = a.start_date or sc.get("start_date")
    main_r = compute(root, cfg, est, rules, cls, hosting, database, ai_on, engineers, start_date=start_date)
    keys = ("total_hours", "likely_hours", "total_days", "likely_days", "manual_likely_hours", "duration_weeks")
    comparisons = []
    for h in [k for k in est["hosting_scenarios"] if not k.startswith("_")]:
        r = main_r if h == hosting else compute(root, cfg, est, rules, cls, h, database, ai_on, engineers)
        comparisons.append({"kind": "hosting", "id": h, "label": est["hosting_scenarios"][h]["label"], "selected": h == hosting, **{k: r["totals"][k] for k in keys}, "notes": r["notes"]})
    for d in ("dual", "postgresql", "none"):
        r = main_r if d == database else compute(root, cfg, est, rules, cls, hosting, d, ai_on, engineers)
        db_only = [sum((x["options"][d]["hours"][i] if d != "none" else 0) for x in r["databases"]) for i in (0, 1)]
        comparisons.append({"kind": "database", "id": d, "label": est["database_scenarios"][d], "selected": d == database, "database_hours": [round(x) for x in db_only],
                            **{k: r["totals"][k] for k in keys}, "notes": r["notes"]})
    f = main_r["factors"]
    out = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "model_version": est.get("version"), "engineers": engineers,
           "ai_assisted": ai_on, "ai_code_factor": f["code"], "ai_factors": f, "hours_per_day": HPD, "scope": "coding only",
           "scenario": {"hosting": hosting, "hosting_label": est["hosting_scenarios"][hosting]["label"], "database": database, "database_label": est["database_scenarios"][database]},
           "work_packages": main_r["packages"], "databases": main_r["databases"], "totals": main_r["totals"], "timeline": main_r["timeline"], "sprints": main_r["sprints"],
           "scenario_notes": main_r["notes"], "comparisons": comparisons, "optional": main_r["optional"],
           "scale": main_r["scale"], "likely_position": main_r["likely_position"],
           "assumptions": [f"Scenario: {est['hosting_scenarios'][hosting]['label']}; database: {est['database_scenarios'][database]}.",
                           "Scope: coding effort only (code and SQL conversion, fixing findings, unit tests written with the code). QA and regression testing, DevOps and infrastructure, project management, parallel-development drift, contingency and data migration are not included.",
                           (f"AI-assisted delivery: code work at {int(f['code'][0] * 100)}-{int(f['code'][1] * 100)}% of manual effort (AWS Transform for .NET / GitHub Copilot app modernization / coding agents; "
                            f"AWS cites up to 4x on mechanical porting), database conversion at {int(f['db'][0] * 100)}-{int(f['db'][1] * 100)}% (AWS DMS Schema Conversion + review); "
                            f"redesign work with no mechanical path (Web Forms UI, medium / large findings, constructs with no PostgreSQL equivalent, the dual-database abstraction) at {int(f['redesign'][0] * 100)}-{int(f['redesign'][1] * 100)}%. "
                            "The manual-equivalent figure is shown beside every total.") if ai_on else "Manual delivery (no AI assistance).",
                           "Project hours = (fixed + hand-written KLOC x rate for the project type) x a complexity factor from decision density, fan-in, file size and run-time indirection (calls bound by DI, overrides, messages, events or delegates, found by the C# resolver) x a size factor for large repositories (COCOMO II diseconomy of scale); generated code is excluded and a project shared by several applications is ported once.",
                           f"Team of {engineers} engineers at {int(est['team']['efficiency'] * 100)}% efficiency; 1 day = {HPD} hours.",
                           f"Ranges are {RANGE_LABEL} (80% confidence) from a Monte Carlo roll-up of every item's three-point estimate ({est['rollup']['iterations']} iterations, "
                           f"correlation {est['rollup']['correlation']} between items, AI factors drawn once per iteration for all items); 'likely' is P50 and the commitment figure is P80. "
                           f"Each item's mode sits {int(est['likely_position'] * 100)}% of the way from its low to its high ({int(est.get('likely_position_large', est['likely_position']) * 100)}% in repositories of "
                           f"{(est.get('scale') or {}).get('large_kloc', '-')} KLOC or more). Adding every low and every high gives {main_r['totals']['bounds_hours'][0]}-{main_r['totals']['bounds_hours'][1]} h: "
                           "extremes that need every item at the same end at once, not a planning range.",
                           (f"Sprint plan: {est['sprints']['length_weeks']}-week sprints from the day of codebase access ({main_r['sprints']['start_date'] or 'Week 1'}); "
                            f"{main_r['sprints']['sprints_p50']} sprint(s) at P50, {main_r['sprints']['sprints_p80']} at P80; the first {est['sprints']['onboarding_days']} day(s) "
                            "go to access, clone, restore, baseline build and existing tests (calendar time, not in the estimate).") if main_r["sprints"]["plan"] else "No sprint plan (nothing to code).",
                           "Needs-verification findings are assumed real until reviewed. Optional modernizations are listed separately and are not in the total."] + main_r["notes"]}
    write_json(os.path.join(OUT, "estimate.json"), out)
    mark_step(root, "estimate")
    t = out["totals"]
    print(f"estimate [{hosting} / {database}] ({'AI-assisted' if ai_on else 'manual'}, coding only): {RANGE_LABEL} {t['total_hours'][0]}-{t['total_hours'][1]} h = {t['total_days'][0]}-{t['total_days'][1]} d, "
          f"P80 {t['p80_hours']} h, sum of extremes {t['bounds_hours'][0]}-{t['bounds_hours'][1]} h "
          f"(likely {t['likely_hours']} h / {t['likely_days']} d; manual likely {t['manual_likely_hours']} h); {t['kloc']} KLOC, {t['likely_hours_per_kloc']} likely h/KLOC; "
          f"~{t['duration_weeks']} weeks with {engineers} engineers; optional modernizations {t['optional_hours'][0]}-{t['optional_hours'][1]} h ({'included: intake aws_native = now' if t.get('optional_in_scope') else 'not included'})")
    for c in comparisons:
        print(f"  {'*' if c['selected'] else ' '} {c['kind']:<8} {c['id']:<15} likely {c['likely_hours']:>6} h ({c['likely_days']:>6} d), manual {c['manual_likely_hours']:>6} h, ~{c['duration_weeks']} wk" +
              (f", db part {c['database_hours'][0]}-{c['database_hours'][1]} h" if c.get("database_hours") else ""))
    if a.explain:
        print("\nper project (application, project, type, KLOC, complexity factor, why, manual hours low-high):")
        for row in main_r["explain"]:
            print("  ", " | ".join(str(x) for x in row))


if __name__ == "__main__":
    main()
