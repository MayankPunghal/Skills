"""One consolidated, short report: the answer first, then only what needs action. Built from everything the other steps
wrote (classification, findings, Linux readiness, packages and DLLs, AWS managed services, the phased estimate, the
AWS Transform scanner cross-check). Every number comes from those files; nothing is typed in here.

    py -X utf8 build_summary.py [--max-rows 12]

Writes assessment/report/<Client>-Modernization-Summary.md and .html. Sections with nothing to say are left out. The
full assessment report, the per-repository effort inputs, estimates, Linux readiness and AWS service reports stay as the
detail behind it; the last section links them.
"""
import argparse
import math
import os
import re
from collections import Counter, defaultdict

from _common import OUT, load_config, read_json, slug, utf8_stdout
from _mdhtml import write_pair
import _analysis as A
import build_report as BR

SEV = ["Blocker", "High", "Medium", "Low", "Info"]
ACTION_PKG = {"blocker", "replace", "windows-only", "private", "licence", "deprecated", "upgrade"}


def cell(x, n=140):
    s = re.sub(r"\s+", " ", str(x if x not in (None, "") else "-")).strip().replace("|", "/")
    return s if len(s) <= n else s[: n - 1] + "…"


def table(head, rows):
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]


def h(lo, hi):
    return f"{lo:,.0f}-{hi:,.0f} h"


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--max-rows", type=int, default=12)
    a = ap.parse_args()
    root, cfg = load_config()
    c = BR.Ctx(root, cfg)
    N = a.max_rows
    client = cfg.get("client") or "Estate"
    est = read_json(os.path.join(OUT, "effort", "estimate-phases.json"), {}) or {}
    reps = est.get("repos", {})
    apps = c.cls["applications"]
    lin = {r["id"]: r for r in A.linux_readiness(c)}
    atf = {r: read_json(os.path.join(OUT, "atf", r, "atf.json")) for r in c.repos}
    aws = {r: read_json(os.path.join(OUT, "effort", r, "aws-native.json")) for r in c.repos}
    loc_exec = sum(((x or {}).get("radnet") or {}).get("loc_exec", {}).get("total", 0) for x in atf.values())
    loc = loc_exec or sum((c.inv[r] or {}).get("totals", {}).get("loc", 0) for r in c.repos)
    sev = Counter(f["severity"] for f in c.findings)

    L = [f"# {client}: modernization summary", "",
         f"{len(c.repos)} repositor{'y' if len(c.repos) == 1 else 'ies'}, {len(apps)} application{'' if len(apps) == 1 else 's'}, {loc:,} lines of code"
         + (" (executable lines, AWS Transform convention)" if loc_exec else " (non-blank)") + f"; target {cfg.get('target_dotnet', 'net10.0')} on Linux containers on AWS. "
         f"{sum(sev.values())} findings ({', '.join(f'{s} {sev[s]}' for s in SEV if sev[s])}).", ""]

    # ---- bottom line
    L += ["## Bottom line", ""]
    if reps:
        tot = est.get("total", [0, 0])
        hpd = next(iter(reps.values())).get("hours_per_day", 6)
        eng = c.est.get("engineers") or 2  # the same team size as the report's at-a-glance duration
        weeks2 = [max(1, math.ceil(tot[0] / (eng * hpd * 5))), max(1, math.ceil(tot[1] / (eng * hpd * 5)))]
        engines = sorted({v["engine"] for v in reps.values()})
        L.append(f"- **Effort: {h(*tot)}** (planning grade, +-25%, buffer included): about {weeks2[0]}-{weeks2[1]} weeks for a team of {eng}. "
                 f"Port by {', '.join(engines)}; Claude cleans up what the engine leaves; {next(iter(reps.values()))['db_tool']} adds the PostgreSQL path.")
    elif c.est.get("totals"):
        t = c.est["totals"]
        L.append(f"- **Effort: {t.get('total_days', ['?', '?'])[0]}-{t.get('total_days', ['?', '?'])[1]} person-days** (estimate_effort.py; run effort_facts.py and estimate_phases.py for the phased hours).")
    r7 = Counter(x["r7"] for x in apps)
    L.append("- **Path:** " + ", ".join(f"{k} {v}" for k, v in r7.most_common()) + ".")
    lv = Counter(r["level"] for r in lin.values())
    if lin:
        L.append(f"- **Linux:** {lv.get('ready', 0)} ready, {lv.get('port', 0)} ready after the port, {lv.get('blocked', 0)} blocked until redesigned, "
                 f"{lv.get('windows', 0)} Windows-only.")
    bins = [b for r in c.repos for b in c.scan[r].get("binary_references", []) if not str(b.get("runs_on_linux", "")).startswith("yes")]
    pkgs = [p for r in c.repos for p in c.scan[r].get("packages", []) if p.get("status") in ACTION_PKG - {"upgrade"}]
    if bins or pkgs:
        L.append(f"- **Dependencies:** {len({p['id'] for p in pkgs})} package(s) and {len({b['assembly'] for b in bins})} DLL(s) have no build that runs on Linux as used today.")
    unknown = sorted({k for v in reps.values() for k in v.get("open", [])})
    if unknown:
        L.append(f"- **Waiting on the client:** {len(unknown)} decision(s) change the estimate (see Decisions and open questions).")
    L.append("")

    # ---- applications
    L += ["## Applications", ""]
    rows, shown = [], set()
    for x in sorted(apps, key=lambda x: (x["repo"], x["name"])):
        r = lin.get(x["id"], {})
        rp = reps.get(x["repo"])
        eff = "-" if not rp else (h(*rp["total"]) + f" (whole {x['repo']})" if x["repo"] not in shown else "in the line above")
        shown.add(x["repo"])
        rows.append([x["name"], x["repo"], x["type"], f"{x['r7']}: {x.get('target', '')}", r.get("status", "-"), r.get("summary", "-"), eff])
    L += table(["Application", "Repository", "Type", "Path", "Linux", "What stands in the way", "Effort"], rows) + [""]

    # ---- migration order: pilot, waves, every project (class libraries included) with its own 7R
    pm = BR.project_model(c)
    if pm["projects"]:
        L += ["## Migration order", ""]
        if pm.get("pilot"):
            p = pm["pilot"]
            L.append(f"**Pilot: {p['name']}** ({p['repo']}). {p['why']}" + (f" Port first: {', '.join(p['needs_first'])}." if p["needs_first"] else ""))
            L.append("")
        L += [f"- **Wave {w['wave']}** ({w['summary'].lower()}): {', '.join(w['projects'][:N])}" + (f" +{len(w['projects']) - N} more" if len(w["projects"]) > N else "") for w in pm["waves"]] + [""]
        L += table(["#", "Wave", "Project", "Kind", "Difficulty", "7R", "Port first", "Blast radius"],
                   [[x["order"], x["wave"], x["name"] + (" (deployable)" if x["deployable"] else ""), x["kind"], x["difficulty"], x["r7"],
                     cell(", ".join(x["needs_first"]) or "-", 100), f"{x['blast']['level']} ({x['blast']['transitive']} project{'' if x['blast']['transitive'] == 1 else 's'})"] for x in pm["projects"][:N * 2]]) + [""]
        if len(pm["projects"]) > N * 2:
            L += [f"{len(pm['projects']) - N * 2} more projects in the full report (Migration order) and the tracker (Projects sheet).", ""]

    # ---- sign-in and access per application, with the AWS replacement
    auth = BR.auth_rows(c, pm)
    if auth:
        L += ["## Sign-in and access", ""]
        L += table(["Application", "Who signs in", "Today", "Recommended on AWS", "Worst"],
                   [[x["app"], x["who"], cell(", ".join(x["authn"]) or "no sign-in found in code", 120), cell(x["aws"], 160), x["worst"] or "-"] for x in auth]) + [""]

    # ---- what must change: Blocker / High grouped by rule
    by = defaultdict(lambda: {"n": 0, "apps": set(), "f": None})
    for f in c.findings:
        if f["severity"] in ("Blocker", "High") and not f.get("dismissed"):
            b = by[f["rule"].split(":")[0] if f.get("source") != "linux-readiness" else f["rule"]]
            b["n"] += f.get("occurrences") or 1
            b["apps"] |= {c.apps[i]["name"] for i in f.get("apps", []) if i in c.apps}
            b["f"] = b["f"] or f
    top = sorted(by.values(), key=lambda b: (SEV.index(b["f"]["severity"]), -len(b["apps"]), -b["n"]))
    if top:
        L += ["## What must change (Blocker and High)", "",
              f"{len(top)} issue types; the {min(N, len(top))} with the widest reach. Every finding with evidence is in the full report.", ""]
        L += table(["Severity", "Issue", "Applications", "Occurrences", "Fix"],
                   [[b["f"]["severity"], b["f"]["title"], ", ".join(sorted(b["apps"])) or "repository-wide", b["n"], cell(b["f"].get("fix"), 160)] for b in top[:N]]) + [""]

    # ---- packages and DLLs needing action
    rows = []
    for r in c.repos:
        for p in c.scan[r].get("packages", []):
            if p.get("status") in ACTION_PKG and not str(p.get("replacement", "")).startswith("None"):
                rows.append([p["id"] + " " + ", ".join(p.get("versions") or []), "NuGet", p.get("runs_on_linux"), p.get("replacement"), len(p.get("projects", []))])
        for b in c.scan[r].get("binary_references", []):
            if not str(b.get("runs_on_linux", "")).startswith("yes") or "PackageReference" in b.get("action", ""):
                rows.append([b["assembly"], "DLL (" + b.get("built_for", "") + ")", b.get("runs_on_linux"), b.get("action"), 1])
    if rows:
        merged = {}
        for x in rows:
            k = (x[0], x[1])
            merged[k] = merged.get(k, x[:4] + [0])
            merged[k][4] += x[4]
        L += ["## Packages and DLLs that need action", "",
              "Looked up on nuget.org (frameworks, deprecation, advisories, Windows-only builds, a cross-platform alternative); "
              "packages that run on Linux as they are are left out.", ""]
        L += table(["Package / DLL", "Kind", "Runs on Linux", "Action", "Projects"], sorted(merged.values(), key=lambda x: str(x[2]))) + [""]

    # ---- AWS managed services
    rows = []
    for r, d in aws.items():
        for s in (d or {}).get("services", []):
            o = next((x for x in s["options"] if x.get("chosen")), s["options"][0])
            inc = (reps.get(r) and any(i["id"].startswith("S") for p in reps[r]["phases"] if p["id"] == "P5" for i in [{"id": z} for z in p["items"]]))
            rows.append([s["label"], r, s.get("client_code"), f"{o['aws']} ({o['change']})", h(*o["hours"]), "yes" if inc else "no (later)"])
    if rows:
        L += ["## Server-hosted services to AWS managed services", ""]
        L += table(["Service", "Repository", "Client code", "AWS target", "Effort", "In the total"], rows) + [""]

    # ---- estimate by phase
    if reps:
        ph = defaultdict(lambda: {"who": set(), "lo": 0.0, "hi": 0.0, "title": ""})
        for v in reps.values():
            for p in v["phases"]:
                x = ph[p["id"]]
                x["title"], x["lo"], x["hi"] = p["title"], x["lo"] + p["low"], x["hi"] + p["high"]
                x["who"].add(p["who"])
        sub = [sum(v["subtotal"][0] for v in reps.values()), sum(v["subtotal"][1] for v in reps.values())]
        L += ["## Estimate by phase", ""]
        L += table(["Phase", "Who", "Hours"], [[f"{k} {x['title']}", ", ".join(sorted(x["who"])), h(x["lo"], x["hi"])] for k, x in sorted(ph.items())]
                   + [["Buffer", "", h(est["total"][0] - sub[0], est["total"][1] - sub[1])], ["**Total**", "", f"**{h(*est['total'])}**"]])
        if len(reps) > 1:
            L += ["", "By repository: " + "; ".join(f"{r} {h(*v['total'])}" for r, v in sorted(reps.items(), key=lambda kv: -kv[1]["total"][1])) + "."]
        scen = [(r, s) for r, v in reps.items() for s in v.get("scenarios", [])]
        if scen:
            L += ["", "What the open questions change: " + "; ".join(f"{s['name']} ({r}) {s['delta'][0]:+d} to {s['delta'][1]:+d} h" for r, s in scen) + "."]
        L.append("")

    # ---- decisions and open questions
    qs = []
    for r, v in reps.items():
        inp = read_json(os.path.join(OUT, "effort", r, "estimate-inputs.json"), {}) or {}
        for k in v.get("open", []):
            q = (inp.get(k) or {}).get("question") or (inp.get(k) or {}).get("note", "")
            if q:
                qs.append(("Estimate", q, r))
    seen = set()
    for f in c.findings:
        if f["severity"] in ("Blocker", "High") and f.get("question") and f["question"] not in seen:
            seen.add(f["question"])
            qs.append((f.get("ref", f["rule"]), f["question"], f["repo"]))
    if qs:
        L += ["## Decisions and open questions", ""]
        merged = {}
        for k, q, r in qs:
            merged.setdefault((k, q), []).append(r)
        L += [f"{i}. **{k}**: {q} ({', '.join(sorted(set(rs)))})" for i, ((k, q), rs) in enumerate(list(merged.items())[: N - 2], 1)]
        if len(merged) > N - 2:
            L.append(f"\n{len(merged) - (N - 2)} more in the full report (section 9) and in open-questions.csv.")
        L.append("")

    # ---- cross-checks
    rows = []
    for r in c.repos:
        x = atf.get(r)
        if not x:
            rows.append([r, "AWS Transform scanner not run (atf_scan.py)", "-"])
            continue
        rn, rq = x.get("radnet"), x.get("rasql")
        rows.append([r, (f"RadNet: {rn['loc_exec']['total']:,} executable lines; DLLs only ATF found: {len(rn['local_dlls']['atf_only'])}; "
                         f"packages only ATF found: {len(rn['nuget']['atf_only'])}" if rn else "RadNet: no rows"),
                     (f"RaSQL: inline {rq['inline_sql']['matched']}/{rq['inline_sql']['atf']}, execute {rq['execute_calls']['matched']}/{rq['execute_calls']['atf']} matched; "
                      f"{sum(1 for e in rq['inline_sql']['rows'] + rq['execute_calls']['rows'] if e['reason'] == 'not matched: review')} to review"
                      if rq else "RaSQL: no rows")])
    L += ["## Cross-check with AWS Transform", ""] + table(["Repository", "RadNet", "RaSQL"], rows) + [""]

    # ---- detail
    rep = [os.path.basename(p) for p in sorted(os.listdir(os.path.join(OUT, "report"))) if p.endswith("-Assessment.html")] if os.path.isdir(os.path.join(OUT, "report")) else []
    L += ["## Detail", ""]
    if rep:
        L.append(f"- Full assessment report: `{OUT}/report/{rep[0]}` (every finding with evidence, 7R reasoning, dependencies, database).")
    for r in c.repos:
        parts = [f"`{OUT}/effort/{r}/estimate.html`" if os.path.exists(os.path.join(OUT, "effort", r, "estimate.html")) else None,
                 f"`{OUT}/effort/{r}/effort-inputs.html`" if os.path.exists(os.path.join(OUT, "effort", r, "effort-inputs.html")) else None,
                 f"`{OUT}/linux/{r}/linux-readiness.html`" if os.path.exists(os.path.join(OUT, "linux", r, "linux-readiness.html")) else None,
                 f"`{OUT}/effort/{r}/aws-native.html`" if os.path.exists(os.path.join(OUT, "effort", r, "aws-native.html")) else None,
                 f"`{OUT}/atf/{r}/atf.html`" if os.path.exists(os.path.join(OUT, "atf", r, "atf.html")) else None]
        if any(parts):
            L.append(f"- {r}: " + ", ".join(p for p in parts if p) + ".")
    out = os.path.join(OUT, "report", f"{slug(client).title().replace('-', '')}-Modernization-Summary.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    write_pair(out, "\n".join(L) + "\n", title=f"{client}: modernization summary")
    print(f"summary: {out} ({len(L)} lines) + .html")


if __name__ == "__main__":
    main()
