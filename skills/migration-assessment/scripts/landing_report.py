"""Report blocks of the lift-and-shift report (standard library only; used by build_report.py when assessment_type is lift-and-shift).

A lift-and-shift report is written for the application team. It answers: what must change in our configuration and code so the same
applications run on Amazon EC2 with the same operating system, which values go into CI variables, what the servers need, and what other
teams (DevOps, DB team, security, vendors, the business) must do. Framework and package findings that only matter for modernization
sit in "Future options". Every block takes the report context `c` of build_report.py.
"""
import csv
import json
import os
import re
import shutil
from collections import Counter, OrderedDict, defaultdict

import _hours_report as H
import _landing as L
from _common import OUT, data, read_json

SEVS = ["Blocker", "High", "Medium", "Low", "Info"]
SEV_RANK = {s: i for i, s in enumerate(SEVS)}
OWNER_ORDER = ["dotnet", "devops", "dba", "security", "vendor", "business"]
TITLES = {"NET-ENDPOINT-INTERNAL": "Internal (on-premises) addresses in code and configuration", "NET-ENDPOINT-PUBLIC-IP": "Fixed public IP addresses",
          "NET-ENDPOINT-EXTERNAL": "External services called", "CFG-SECRET-SETTING": "Secrets stored in configuration files",
          "CFG-SECRET-PLACEHOLDER": "Secrets already supplied at deploy time", "CFG-PLAINTEXT-DB-PASSWORD": "Database password in clear text in configuration",
          "CFG-LOCAL-DB-PASSWORD": "Local database password in configuration", "CFG-DB-PASSWORD-PLACEHOLDER": "Database password supplied at deploy time"}
SOURCE_OF_QUESTIONS = "questions"


def esc(s):
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def table(cols, rows):
    if not rows:
        return "_None._"
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    out += ["| " + " | ".join(esc(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def rng(r, unit=""):
    return f"{round(r[0])}–{round(r[1])}{unit}"


def _titles():
    t = dict(TITLES)
    for r in data("rules.json")["rules"]:
        t.setdefault(r["id"], r["title"])
    return t


def move_groups(c):
    """The findings that matter for the move, one group per rule, in report order (area, then worst severity)."""
    titles = _titles()
    g = OrderedDict()
    for f in c.findings:
        if not L.moves(f):
            continue
        key = L.base_rule(f["rule"])
        e = g.setdefault(key, {"rule": key, "title": titles.get(key, f["title"]), "landing": f["landing"], "findings": [], "apps": set(), "repos": set()})
        e["findings"].append(f)
        e["apps"].update(c.apps[a]["name"] for a in f.get("apps", []) if a in c.apps)
        e["repos"].add(f["repo"])
    areas = list(L.table()["areas"])
    out = list(g.values())
    for e in out:
        e["severity"] = min((f["severity"] for f in e["findings"]), key=lambda s: SEV_RANK.get(s, 9))
        e["locations"] = sum(f.get("occurrences", 1) for f in e["findings"])
        e["refs"] = [f["ref"] for f in e["findings"]]
    out.sort(key=lambda e: (areas.index(e["landing"]["area"]) if e["landing"]["area"] in areas else 99, SEV_RANK.get(e["severity"], 9), e["rule"]))
    return out


def refs(e, n=3):
    r = e["refs"]
    return ", ".join(r[:n]) + (f" +{len(r) - n}" if len(r) > n else "")


def evidence(e, n=2):
    out = []
    for f in e["findings"]:
        for ev in f.get("evidence", []):
            tag = f"{f['repo']}/{ev['file']}:{ev['line']}"
            if tag not in out:
                out.append(tag)
        if len(out) >= n:
            break
    return "<br>".join(out[:n]) + (f"<br>(+{e['locations'] - n} more)" if e["locations"] > n else "")


def apps_text(e, limit=4):
    a = sorted(e["apps"])
    return ", ".join(a[:limit]) + (f" +{len(a) - limit}" if len(a) > limit else "") if a else ", ".join(sorted(e["repos"]))


def tpl(c):
    """Configuration template data of every repository (config_template.py)."""
    out = {"variables": [], "occurrences": [], "kept": [], "manual": [], "files": [], "token_format": c.cfg.get("config_token_format") or "${NAME}"}
    for r in c.repos:
        d = read_json(os.path.join(OUT, "configtpl", f"{r}.json"))
        if not d:
            continue
        out["token_format"] = d.get("token_format", out["token_format"])
        out["variables"] += [dict(v, repo=r) for v in d["variables"]]
        out["occurrences"] += [dict(o, repo=r) for o in d["occurrences"]]
        out["kept"] += [dict(k, repo=r) for k in d["kept"]]
        out["manual"] += [dict(m, repo=r) for m in d["manual"]]
        out["files"] += [{"repo": r, "file": f} for f in d["files"]]
    return out


def owner_counts(c):
    n = Counter()
    for e in move_groups(c):
        n[e["landing"]["owner"]] += 1
    return n


# ------------------------------------------------------------------ 1. summary page
def b_summary(c):
    t = c.est.get("totals", {})
    groups = move_groups(c)
    td = tpl(c)
    napps = len(c.cls["applications"])
    code = [e for e in groups if e["landing"]["owner"] == "dotnet" and e["landing"]["change"] == "code"]
    stop = [e for e in groups if e["severity"] == "Blocker" or e["landing"]["change"] == "decision"]
    kinds = Counter(v["kind"] for v in td["variables"])
    fw = sorted({tf for a in c.cls["applications"] for tf in a.get("target_frameworks", [])})
    loc = sum((c.inv[r] or {}).get("totals", {}).get("loc", 0) for r in c.repos)
    if stop:
        verdict = (f"**{napps} application(s) can move to EC2 with the same operating system and no code port, once {len(stop)} item(s) are settled** "
                   f"({'; '.join(e['title'] for e in stop[:4])}{'…' if len(stop) > 4 else ''}). Everything else is configuration, server setup and hand-offs.")
    else:
        verdict = f"**All {napps} application(s) can move to EC2 with the same operating system and no code port.** Nothing found stops the move; the work is configuration, server setup and hand-offs to other teams."
    rows = [("Applications", f"{napps} in {len(c.repos)} repository(ies), {', '.join(fw) or 'framework not detected'}, {loc:,} lines"),
            ("Configuration values to replace", f"{len(td['variables'])} CI variables in {len(td['files'])} configuration files "
             + (f"({', '.join(f'{n} × {k}' for k, n in kinds.most_common())})" if kinds else "") + " (section 4)"),
            ("Code changes", f"{len(code)} change(s) by the application team: " + ("; ".join(e["title"] for e in code) if code else "none")),
            ("Things that stop or break the move", f"{len(stop)} to settle first" if stop else "none found")]
    if H.is_hours(c.est):  # the hours calculator is the estimate of this track
        rows += H.headline_rows(c.est["hours"])
    elif t.get("total_days"):
        rows.append((".NET team effort (AI-assisted)", f"likely (P50) {t.get('likely_hours', '-')} h / {t['likely_days']} d; 80% range {rng(t['total_hours'], ' h')} ({t['total_days'][0]:g}–{t['total_days'][1]:g} d); commitment (P80) {t.get('p80_hours', '-')} h"))
        rows.append(("Same work done manually", rng(t["manual_equivalent_hours"], " h") if t.get("manual_equivalent_hours") else "-"))
        sp = c.est.get("sprints") or {}
        rows.append(("Duration", f"~{t.get('duration_weeks')} week{'' if t.get('duration_weeks') == 1 else 's'} at P50, ~{t.get('duration_weeks_p80')} at P80 with {c.est.get('engineers')} engineers"
                     + (f" (from {sp['start_date']})" if sp.get("start_date") else "")))
    else:
        rows.append((".NET team effort", "not estimated (run estimate_effort.py)"))
    n = owner_counts(c)
    rows.append(("Hand-offs to other teams", ", ".join(f"{L.owner_label(o)} {n[o]}" for o in OWNER_ORDER[1:] if n[o]) or "none"))
    out = [verdict, "", table(["Measure", "Value"], rows), ""]
    do = [f"1. **Replace {len(td['variables'])} values with CI variables** ({', '.join(sorted({v['kind'] for v in td['variables']})[:5])}): tokenised copies of every configuration file are generated, so nobody edits files by hand (section 4)."]
    if code:
        do.append(f"{len(do) + 1}. **Change code in {len(code)} place(s)**: " + "; ".join(f"{e['title']} ({refs(e)})" for e in code) + " (section 4.4).")
    do.append(f"{len(do) + 1}. **Smoke-test each application** on its EC2 host in every environment (section 11).")
    out += ["**What the .NET team does**", ""] + do + [""]
    brief = []
    for o in OWNER_ORDER[1:]:
        es = [e for e in groups if e["landing"]["owner"] == o]
        if es:
            top = sorted(es, key=lambda e: SEV_RANK.get(e["severity"], 9))[:3]
            brief.append((L.owner_label(o), len(es), "; ".join(e["title"] for e in top)))
    if brief:
        out += ["**What other teams must do before cut-over** (details in section 8)", "", table(["Team", "Items", "Most important"], brief), ""]
    if stop:
        out += ["**To settle first**", "", table(["Item", "Why", "Owner", "Ref"], [(e["title"], e["landing"]["action"], L.owner_label(e["landing"]["owner"]), refs(e)) for e in stop[:6]]), ""]
    return "\n".join(out).rstrip()


# ------------------------------------------------------------------ 3. applications
def b_applications(c):
    td = tpl(c)
    wp = c.wp
    rows = []
    for a in c.cls["applications"]:
        names = {p.split("/")[-1].rsplit(".", 1)[0] for p in a.get("projects", [])} | {a["name"]}
        nvars = len({o["name"] for o in td["occurrences"] if o["repo"] == a["repo"] and o["project"] in names})
        mine = [f for f in c.findings if a["id"] in f.get("apps", []) and L.moves(f)]
        rules = {L.base_rule(f["rule"]) for f in mine}
        worst = min((f["severity"] for f in mine), key=lambda s: SEV_RANK.get(s, 9), default="-")
        mine_others = len({L.base_rule(f["rule"]) for f in mine if f["landing"]["owner"] != "dotnet"})
        w = wp.get(a["id"], {})
        rows.append((a["name"], a["repo"], a["type"], ", ".join(a.get("target_frameworks", [])) or "-", nvars, len(rules), mine_others, worst,
                     f"{w.get('likely_hours', '-')} h" if w else "-"))
    if H.is_hours(c.est):  # effort is estimated per solution (effort section), not per application
        return table(["Application", "Repository", "Type", "Framework", "CI variables", "Landing checks hit", "of them for other teams", "Worst severity"], [r[:-1] for r in rows])
    return table(["Application", "Repository", "Type", "Framework", "CI variables", "Landing checks hit", "of them for other teams", "Worst severity", ".NET team effort (P50)"], rows)


# ------------------------------------------------------------------ 4. configuration
def b_config_howto(c):
    td = tpl(c)
    fmt = td["token_format"]
    ex = fmt.replace("NAME", "REDISCONNECTION")
    return (f"Each environment-specific value in a configuration file is replaced by a token such as `{ex}`. The tokenised copy of every file is in "
            f"`config-templates/templates/<repository>/<file>.tmpl`; the original files in the repository are not touched. In CI:\n\n"
            "1. Create one CI variable per name in section 4.2 for each environment (dev, test, production on AWS), scoped to that environment; mark secrets as masked and protected.\n"
            "2. Add a deploy step that runs `config-templates/ci/render-config.ps1 -TemplateRoot <templates folder> -OutputRoot <publish folder>`. It fills every token from the CI variables, escapes the value for XML or JSON, and stops without writing anything when a variable is missing.\n"
            "3. Deploy the rendered files with the application. `ci/variables.example.env` lists every variable with what it holds and who supplies it; `ci/gitlab-ci.example.yml` is a starting job.\n\n"
            "Variables are named after the setting; a setting that holds different values in different projects gets the project name as a prefix. "
            "Secret values are never read into this report or the templates. The same list is in `config-variables.csv`, and every replaced line in `config-placeholders.csv`.")


def b_config_values(c, limit=40):
    td = tpl(c)
    if not td["variables"]:
        return "_No environment-specific configuration values were found. Run `config_template.py` if configuration files exist._"
    out = []
    by = defaultdict(list)
    for v in td["variables"]:
        by[v["kind"]].append(v)
    for kind, vs in sorted(by.items(), key=lambda kv: (OWNER_ORDER.index(kv[1][0]["owner"]) if kv[1][0]["owner"] in OWNER_ORDER else 9, kv[0])):
        out.append(f"**{kind}** — {len(vs)} variable(s). Supplied by: {vs[0]['supplied_by']}.\n")
        rows = [(f"`{v['name']}`", v["setting"], f"{len(v['projects'])} project(s), {v['files']} file(s)", v["current_target"] or v["detail"] or "(value not shown)") for v in vs[:limit]]
        out.append(table(["Variable", "Setting in the file", "Used in", "Today's target (secrets never shown)"], rows))
        if len(vs) > limit:
            out.append(f"\n_{len(vs) - limit} more in config-variables.csv._")
        out.append("")
    return "\n".join(out).rstrip()


def b_config_files(c, limit=60):
    td = tpl(c)
    cnt = Counter((o["repo"], o["file"], o["project"]) for o in td["occurrences"])
    rows = [(r, f, p, n, f"config-templates/templates/{r}/{f}.tmpl") for (r, f, p), n in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))]
    note = f"\n\n_{len(rows) - limit} more files in config-placeholders.csv._" if len(rows) > limit else ""
    return table(["Repository", "File", "Project", "Values replaced", "Tokenised copy"], rows[:limit]) + note


def b_config_kept(c, limit=25):
    td = tpl(c)
    out = []
    kept = td["kept"]
    if kept:
        why = Counter("C:\\ folder" if k["reason"].startswith("C:") else ("public IP address" if k["reason"].startswith("public IP") else "public service URL") for k in kept)
        out.append("Values that look environment-related but need **no change** for a lift-and-shift: " + "; ".join(f"{n} × {w}" for w, n in why.most_common()) + ".\n")
        out.append(table(["Repository", "File:line", "Setting", "Why it stays"], [(k["repo"], f"{k['file']}:{k['line']}", k["setting"], k["reason"]) for k in kept[:limit]]))
        if len(kept) > limit:
            out.append(f"\n_{len(kept) - limit} more in config-kept.csv._")
    if td["manual"]:
        out.append("\n**To replace by hand** (the value could not be swapped automatically):\n")
        out.append(table(["Repository", "File:line", "Setting", "Why"], [(m["repo"], f"{m['file']}:{m['line']}", m["setting"], m["why"]) for m in td["manual"]]))
    return "\n".join(out) or "_Nothing else was found._"


def b_code_changes(c):
    gs = [e for e in move_groups(c) if e["landing"]["owner"] == "dotnet" and e["landing"]["change"] == "code"]
    if not gs:
        return "_No code change is needed: every change for the move is a configuration value (4.2)._"
    return table(["Ref", "Severity", "Change", "Where", "What to do", "Evidence"],
                 [(refs(e), e["severity"], e["title"], apps_text(e), e["landing"]["action"], evidence(e, 3)) for e in gs])


# ------------------------------------------------------------------ 5. what will not work the same on AWS
def b_landing_checks(c):
    gs = move_groups(c)
    if not gs:
        return "_No finding affects the move._"
    out = []
    cur = None
    cols = ["Ref", "Severity", "What", "Who", "Kind of change", "Where", "What to do", "Evidence"]
    rows = []

    def flush():
        if rows:
            out.append(f"#### {L.area_label(cur)}\n")
            out.append(table(cols, rows))
            out.append("")
    for e in gs:
        ld = e["landing"]
        if ld["area"] != cur:
            flush()
            cur, rows[:] = ld["area"], []
        rows.append((refs(e), e["severity"], e["title"] + (f" ({e['locations']} places)" if e["locations"] > 1 else ""), L.owner_label(ld["owner"]), L.change_label(ld["change"]), apps_text(e), ld["action"], evidence(e)))
    flush()
    return "\n".join(out).rstrip()


# ------------------------------------------------------------------ 6. server build sheet (DevOps)
def b_server_sheet(c):
    rows = []
    apps = c.cls["applications"]
    web = [a["name"] for a in apps if a["type"] in ("aspnet-webapi", "aspnet-mvc", "aspnet-webforms", "website", "wcf-service", "aspnet-core")]
    svc = [a["name"] for a in apps if a["type"] in ("windows-service", "service", "worker")]
    fw = sorted({tf for a in apps for tf in a.get("target_frameworks", [])})
    if web:
        rows.append(("Web applications", "Windows Server with IIS, ASP.NET and the .NET Framework " + (", ".join(fw) or "version of the project"), "The applications are IIS sites on Windows today (web.config, System.Web).", ", ".join(web[:6]) + (" …" if len(web) > 6 else ""), "-"))
    if svc:
        rows.append(("Windows services", "Install each service with its installer or sc.exe, with a service account and start type", "Windows service projects.", ", ".join(svc), "-"))
    for e in move_groups(c):
        ld = e["landing"]
        if ld["change"] in ("server", "identity") and ld["owner"] in ("devops", "dotnet"):
            rows.append((L.area_label(ld["area"]), ld["action"], e["title"], apps_text(e), evidence(e, 2)))
    td = tpl(c)
    for v in td["variables"]:
        if v["kind"] == "Certificate thumbprint":
            rows.append(("Certificates", f"Certificate for `{v['name']}` in the store the setting names", "A certificate is selected by thumbprint in configuration.", ", ".join(v["projects"][:3]), "-"))
    if not rows:
        return "_No server-side setup was found beyond a Windows Server with IIS._"
    return ("DevOps builds each EC2 host from this list. It comes from the code and configuration; the current servers may hold more (installed software, settings made by hand), so compare it with one live server before cut-over.\n\n"
            + table(["Area", "What the host needs", "Because the code has", "Applications", "Evidence"], rows))


# ------------------------------------------------------------------ 7. network and partners
def b_partner_allowlist(c):
    try:
        import _analysis as A
        nw = A.network(c)
    except Exception:  # network facts are optional
        return "_Network facts are not available._"
    rows = [(x["host"], x["port"], x["protocol"], x["applications"], x["kind"]) for x in nw["outbound"] if x["kind"] in ("external service", "public IP", "external")]
    if not rows:
        return "_No external destination was found._"
    return ("Outbound calls leave EC2 through a NAT gateway with a fixed Elastic IP. If a provider allow-lists the source IP of this client today, they must be given the new "
            "Elastic IP before cut-over, and the old one stays valid until the cut-over is done. The .NET team lists the destinations; DevOps owns the addresses and the requests.\n\n"
            + table(["Destination", "Port", "Protocol", "Applications", "Kind"], rows[:80]) + (f"\n\n_{len(rows) - 80} more in network-allowlist.csv._" if len(rows) > 80 else ""))


# ------------------------------------------------------------------ 8. database hand-off
def b_db_handoff(c):
    td = tpl(c)
    conns = [v for v in td["variables"] if v["kind"] == "Database connection string"]
    dbf = [e for e in move_groups(c) if e["landing"]["owner"] == "dba"]
    out = ["No database code change is estimated. The databases stay on SQL Server on EC2 and the DB team moves them; the applications only need the new connection strings, which are CI variables."]
    if conns:
        out.append("\n**Connection strings the applications read (section 4.2):**\n")
        out.append(table(["Variable", "Used in", "Engine and server today"], [(f"`{v['name']}`", ", ".join(v["projects"][:3]), v["detail"] or "-") for v in conns]))
    iv = read_json(os.path.join(OUT, "infra", "estate-infra.json")) or {}
    dbrows = [r for r in iv.get("rows", []) if re.search(r"(?i)sql|mongo|mysql|postgres|oracle", r.get("label", ""))]
    if dbrows:
        out.append("\n**Database servers named in code:**\n")
        out.append(table(["Type", "Repository", "Hosts in code", "How sure"], [(r["label"], r.get("repo", ""), r.get("hosts_in_code") or "none in code (set per environment)", r.get("strength", "")) for r in dbrows]))
    if dbf:
        out.append("\n**What the code expects from the databases:**\n")
        out.append(table(["Ref", "Severity", "What", "What the DB team should know", "Evidence"], [(refs(e), e["severity"], e["title"], e["landing"]["action"], evidence(e)) for e in dbf]))
    out.append("\n**Information the DB team can give us:** SQL Server version and edition, the database list per application, the login each application uses (Windows or SQL), and whether MongoDB moves to EC2 as well.")
    return "\n".join(out)


# ------------------------------------------------------------------ 9. hand-offs
def b_handoffs(c):
    groups = move_groups(c)
    td = tpl(c)
    out = []
    host = c.cfg.get("current_hosting")
    for o in OWNER_ORDER[1:]:
        rows = []
        if o == "devops":
            rows.append(("Get the servers to EC2", f"Current hosting: {host or 'not stated'}. Decide how the servers get there (image import, AWS Application Migration Service, or a rebuild from section 6) and who exports the machine keys and certificates.", "-"))
            internal = [v for v in td["variables"] if v["kind"].startswith(("Server address", "Company DNS", "File share"))]
            if internal:
                rows.append((f"Decide the new address of {len(internal)} internal servers or file shares", "For each CI variable in section 4.2 of the kinds 'Server address', 'Company DNS name' and 'File share': either the server moves to EC2 (new address) or stays and the EC2 subnet routes to it (VPN / Direct Connect).", "section 4.2"))
        if o == "security":
            secrets = [v for v in td["variables"] if v["kind"] in ("Password, key or token", "URL with credentials", "Machine key")]
            if secrets:
                rows.append((f"Provide {len(secrets)} secrets as CI variables", "New or existing values in the secret store; rotate anything that is written in source code (see the hard-coded credential findings).", "section 4.2"))
        for e in groups:
            if e["landing"]["owner"] == o:
                rows.append((e["title"] + (f" ({e['locations']} places)" if e["locations"] > 1 else ""), e["landing"]["action"], f"{refs(e)}; {apps_text(e)}"))
        if o == "dba":
            conns = [v for v in td["variables"] if v["kind"] == "Database connection string"]
            if conns:
                rows.append((f"Provide {len(conns)} connection strings for AWS", "Server or instance, database name and login for each connection string variable in section 4.2.", "section 4.2"))
        qs = [q for ow, q, r in questions_by_owner(c) if ow == o]
        if rows or qs:
            out.append(f"#### {L.owner_label(o)}\n")
        if rows:
            out.append(table(["What", "What is needed", "Ref / where"], rows))
            out.append("")
        if qs:
            out.append(f"Questions for {L.owner_label(o)}:\n")
            out += [f"- {q}" for q in qs]
            out.append("")
    return "\n".join(out).rstrip() or "_No hand-off was found._"


# ------------------------------------------------------------------ 10-11. effort, risks, questions
def b_ls_estimate(c):
    if H.is_hours(c.est):  # hours calculator (estimate_hours.py): total range, by work item, per solution, sample-calibrated vs inferred
        return (H.estimate_md(c.est["hours"]) + "\n\n**What is not in the estimate:** server build, network, domain, VM and database migration (DevOps and DB team), the client's own QA "
                "and business acceptance, project management, and any modernization: Linux and .NET findings and the optional AWS managed-service replacements are not in the hours. "
                "Rates are in `data/hours.json`; each can be revised and the estimate rerun.")
    rows = []
    totals = [0, 0, 0]
    for w in sorted(c.est.get("work_packages", []), key=lambda w: (w.get("kind") != "repository", -w["likely_hours"])):
        if w.get("mode") != "rehost":
            continue
        lines = w.get("conversion", [])
        cfgs = next((l["manual_hours"] for l in lines if l["item"].startswith("Review the generated")), None)
        vars_ = next((l for l in lines if l["item"].startswith("Set and check")), None)
        nv = re.search(r"Set and check (\d+)", vars_["item"]).group(1) if vars_ else "0"
        smoke = next((l["manual_hours"] for l in lines if l["item"].startswith("Smoke")), None)
        codeh = sum(f["hours"][1] for f in w.get("findings", []))
        name = w["name"].replace("repository-wide items", "configuration shared by all applications") if w.get("kind") == "repository" else w["name"]
        if w.get("kind") == "repository" and not (cfgs or vars_ or w.get("findings")):
            continue
        rows.append((name, rng(cfgs, " h") if cfgs else "-", f"{nv} ({rng(vars_['manual_hours'], ' h')})" if vars_ else "-", rng(smoke, " h") if smoke else "-",
                     f"{len(w.get('findings', []))} finding(s), up to {round(codeh)} h" if w.get("findings") else "-", f"{w['likely_hours']} h", rng(w["total_hours"], " h")))
        totals[0] += w["likely_hours"]
        totals[1] += w["total_hours"][0]
        totals[2] += w["total_hours"][1]
    t = c.est.get("totals", {})
    foot = (f"\n\n**Total (.NET team):** likely (P50) {t.get('likely_hours', totals[0])} h; 80% range {rng(t['total_hours'], ' h') if t.get('total_hours') else '-'}; commitment (P80) {t.get('p80_hours', '-')} h. "
            "Totals are a Monte Carlo roll-up, so the rows do not add up to the total range.")
    basis = ("\n\n**What is in the estimate:** the application team's work only. Once per repository: reviewing the generated templates and adding the render step to the pipeline, "
             "and setting and checking each unique CI variable in every environment (the applications of a repository share the same variables, so each is counted once). "
             "Per application: the written smoke test on its EC2 host. Plus the code changes listed in section 4.4. Hours are manual-equivalent hours; the AI-assistance factor reduces code work only. "
             "**What is not:** server build, network, domain, VM migration and database migration (DevOps and DB team), the client's own QA and business acceptance, project management and contingency, "
             "and **no modernization or migration work**: Linux and .NET findings and the optional AWS managed-service replacements (section 12) are not in the hours. "
             "The ranges come from `data/estimation.json` (`lift_and_shift_hours`).")
    return table(["Work", "Review templates and pipeline step", "CI variables (hours)", "Smoke test", "Code changes", "Likely (P50)", "Range (P10–P90)"], rows) + foot + basis


def b_ls_risks(c):
    rows = []
    for e in move_groups(c):
        if e["severity"] in ("Blocker", "High") or e["landing"]["change"] == "decision":
            rows.append((e["title"], e["severity"], L.owner_label(e["landing"]["owner"]), e["landing"]["action"], refs(e)))
    return table(["Risk", "Severity", "Owner", "Mitigation", "Ref"], rows)


# What the application team needs from other people, or a decision that changes its work. Questions that belong to another team (domain, VPN,
# server build, database administration, allow-lists, maintenance windows) are hand-offs in section 8, never open questions here.
# (owner, question, intake answer that settles it)
LS_QUESTIONS = [
    ("devops", "What address or host name will each internal server (database, cache, file server, mail, SFTP) have on AWS? The CI variables in section 4.2 need these values."),
    ("dotnet", "Which time zone do the current servers use? The EC2 hosts default to UTC and some code depends on local time."),
    ("security", "Where will secrets be kept for the CI variables (GitLab masked variables, AWS Secrets Manager, another vault), and which secrets are rotated at cut-over?"),
    ("dotnet", "Are there environments beyond development, test and production that need their own variable values (UAT, staging, DR)?", "environments"),
    ("dotnet", "How are settings changed on the servers today (by hand, transforms, a release tool)? The CI variables replace that.", "config_delivery")]


def questions_by_owner(c):
    """(owner key, question, raised by). A rule that raises the same question for many items (one per internal address) becomes one question;
    the infrastructure questions that only say "no server list was imported" become one DevOps question."""
    qs, seen = [], set()
    for e in move_groups(c):
        own = list({f["question"]: (f["ref"], f["question"]) for f in reversed(e["findings"]) if f.get("question") and f["question"] not in seen}.values())[::-1]
        seen.update(q for _, q in own)
        if len(own) > 2:
            qs.append((e["landing"]["owner"], f"{own[0][1]} (asked for {len(own)} items, {own[0][0]} to {own[-1][0]}; see section 5 and sections 4.2 and 7.3 for the list)", own[0][0]))
        else:
            qs += [(e["landing"]["owner"], q, r) for r, q in own]
    iv = read_json(os.path.join(OUT, "infra", "estate-infra.json")) or {}
    nolist = [q for q in iv.get("questions", []) if "No infrastructure list imported" in q["question"]]
    if nolist:
        qs.append(("devops", "Which server hosts each kind of server the code depends on (database, cache, message, mail, file transfer, file share, proxy; see section 7.4)? No infrastructure list was imported.", "infrastructure"))
    for q in iv.get("questions", []):
        if q not in nolist and q["question"] not in seen:
            seen.add(q["question"])
            qs.append(("devops", q["question"], q["repo"]))
    from intake import unanswered
    for q in unanswered(c.cfg):
        qs.append(("dotnet", q["ask"], "intake"))
    ans = c.cfg.get("intake") or {}
    if c.cfg.get("company_domains_auto"):
        qs.append(("dotnet", "Confirm the client's own web domains: " + ", ".join(c.cfg.get("company_domains", [])) + ". Names under them are treated as company DNS names (a CI variable each); a missing domain hides a value that must change, a wrong one adds a needless variable.", "detected"))
    for o, q, *key in LS_QUESTIONS:
        if key and ans.get(key[0]) not in (None, "", "unknown", "undecided"):
            continue
        if "time zone" in q.lower() and any("time zone" in x[1].lower() for x in qs):
            continue
        qs.append((o, q, "standard"))
    return qs


def open_questions(c):
    """All questions with the owning team's label (open-questions.csv)."""
    return [(L.owner_label(o), q, r) for o, q, r in questions_by_owner(c)]


def b_ls_questions(c):
    """Section 10.2: the application team's questions. Another team's questions are listed under that team in section 8."""
    mine = [(i, q, r) for i, (o, q, r) in enumerate((x for x in questions_by_owner(c) if x[0] == "dotnet"), 1)]
    other = sum(1 for x in questions_by_owner(c) if x[0] != "dotnet")
    note = f"\n\n_{other} question(s) belong to other teams (DevOps, DB team, security): they are listed under each team in section 8._" if other else ""
    return table(["#", "Question", "Raised by"], mine) + note


# ------------------------------------------------------------------ 12. future options
def b_future(c):
    rest = [f for f in c.findings if not L.moves(f)]
    if not rest:
        return "_No finding is limited to a future modernization._"
    segs = {s["id"]: s["title"] for s in data("categories.json")["segments"]}
    cat_seg = {x["id"]: x.get("segment", "") for x in data("categories.json")["categories"]}
    by = defaultdict(list)
    for f in rest:
        by[cat_seg.get(f["category"], "")].append(f)
    rows = []
    for sid, fs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        sev = Counter(f.get("severity_modern", f["severity"]) for f in fs)
        titles = list(dict.fromkeys(f["title"] for f in sorted(fs, key=lambda f: SEV_RANK.get(f.get("severity_modern", f["severity"]), 9))))
        rows.append((segs.get(sid, sid or "Other"), len(fs), ", ".join(f"{k} {sev[k]}" for k in SEVS if sev[k]), "; ".join(titles[:5])[:260]))
    return ("These findings do **not** stop the same applications running on Windows servers on EC2, so they are not in the estimate and not a task for the move. "
            "They matter only if the code is later moved to Linux or modern .NET, or to PostgreSQL: Web Forms and System.Web, Forms authentication, Web API 2 / OWIN, "
            "BinaryFormatter, XSLT scripting, PDF and imaging libraries, package replacements, PostgreSQL-incompatible SQL. Every one is in `findings.csv` (column `lift_relevance` = future).\n\n"
            + table(["Area", "Findings", "Severity (modernization view)", "Examples"], rows))


# ------------------------------------------------------------------ method and scope
def b_ls_method(c):
    rows = [("Inventory", "Solutions, projects, target frameworks, application types, lines of code, git activity."),
            ("Configuration scan", "Every configuration file (web.config, app.config, appsettings, memcached / redis config, XML settings): which settings hold an address, path, connection string, credential or certificate. Values are replaced by tokens; secret values are never read into any output."),
            ("Landing checks", f"{sum(1 for r in data('landing.json')['rules'])} rules that ask what stops working or behaves differently when the same application runs on EC2: addresses and names, identity and domain, files and drives, things tied to the machine (registry, certificates, COM, hardware ids), mail and file transfer, jobs and services, time zone, IIS setup. Each rule has an owner and a kind of change (`data/landing.json`)."),
            ("Network", "Every outbound destination and listener with its host, port, protocol and the application that uses it."),
            ("Servers", "Server types the code depends on (SQL Server, Redis, Memcached, MongoDB, SMTP, file shares …) tied to the client's server list where one was given."),
            ("Review", "Findings marked Needs verification were read in context by the assessor; verdicts are recorded with the evidence."),
            ("Estimate", ("Hours calculator: developer hours, AI-assisted, solution by solution, with a buffer; each line labelled calibrated to the sample or inferred. Not DevOps, DB or QA.")
             if H.is_hours(c.est) else
             "Application-team hours only: configuration work per application and per CI variable, smoke tests, and code changes. Not DevOps, DB, QA or contingency.")]
    return table(["Step", "What was done"], rows)


def b_ls_not_assessed(c):
    rows = [("Running servers", "Installed software, IIS settings, app-pool identities, scheduled tasks, certificates, registry values and firewall rules are not in the repositories. Section 6 lists what the code implies; DevOps should compare it with a live server."),
            ("Production values", "Real addresses and credentials are set outside the code; only the repository's configuration files were read and no value was copied."),
            ("Runtime behaviour", "No application was run; performance under the new network latency (for example a database or file share that stays on-premises) is not assessed."),
            ("Databases", "Database objects, sizes and the SQL Server host are the DB team's scope.")]
    for r in c.repos:
        s = c.scan[r]
        if s.get("skipped_large"):
            rows.append((f"{r}: large files", f"{len(s['skipped_large'])} files above the scan size limit were not scanned."))
        if (c.inv[r] or {}).get("git", {}).get("shallow"):
            rows.append((f"{r}: git history", "Shallow clone: commit activity is partial."))
    return table(["Area", "Why it could not be assessed from code"], rows)


# ------------------------------------------------------------------ exports
def exports(c, rdir):
    td = tpl(c)
    with open(os.path.join(rdir, "config-variables.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["variable", "token", "what_it_holds", "setting", "repositories", "projects", "files", "environments", "todays_target_non_secret", "supplied_by", "value_for_aws"])
        for v in td["variables"]:
            w.writerow([v["name"], v["token"], v["kind"], v["setting"], v["repo"], "; ".join(v["projects"]), v["files"], "; ".join(v["environments"]), v["current_target"], v["supplied_by"], ""])
    with open(os.path.join(rdir, "config-placeholders.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["repository", "project", "file", "line", "setting", "variable", "what_it_holds", "environment_file"])
        for o in td["occurrences"]:
            w.writerow([o["repo"], o["project"], o["file"], o["line"], o["setting"], o["name"], o["kind"], o["environment"]])
    with open(os.path.join(rdir, "config-kept.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["repository", "project", "file", "line", "setting", "why_it_stays"])
        for k in td["kept"]:
            w.writerow([k["repo"], k["project"], k["file"], k["line"], k["setting"], k["reason"]])
    with open(os.path.join(rdir, "hand-offs.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["team", "item", "severity", "kind_of_change", "what_is_needed", "applications", "refs", "evidence", "status"])
        for e in move_groups(c):
            ld = e["landing"]
            w.writerow([L.owner_label(ld["owner"]), e["title"], e["severity"], L.change_label(ld["change"]), ld["action"], apps_text(e, 20), "; ".join(e["refs"]),
                        " ; ".join(f"{f['repo']}/{ev['file']}:{ev['line']}" for f in e["findings"] for ev in f.get("evidence", [])[:3]), ""])
    src = os.path.join(OUT, "configtpl")
    dst = os.path.join(rdir, "config-templates")
    for sub in ("templates", "ci"):
        if os.path.isdir(os.path.join(src, sub)):
            shutil.rmtree(os.path.join(dst, sub), ignore_errors=True)
            shutil.copytree(os.path.join(src, sub), os.path.join(dst, sub))


BLOCKS = {"ls-summary": b_summary, "ls-applications": b_applications, "config-howto": b_config_howto, "config-values": b_config_values, "config-files": b_config_files,
          "config-kept": b_config_kept, "code-changes": b_code_changes, "landing-checks": b_landing_checks, "server-sheet": b_server_sheet,
          "partner-allowlist": b_partner_allowlist, "db-handoff": b_db_handoff, "handoffs": b_handoffs, "ls-estimate": b_ls_estimate, "ls-risks": b_ls_risks,
          "ls-questions": b_ls_questions, "ls-future": b_future, "ls-method": b_ls_method, "ls-not-assessed": b_ls_not_assessed}
