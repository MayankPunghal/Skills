"""Draft a 7R recommendation and AWS target for every application, with rationale and options (deterministic).

    python <skill>/scripts/classify_apps.py

Reads inventory, findings (+ reviews) and data/decision_rules.json; writes assessment/classification.json.
The reviewer then confirms or overrides each application in assessment/decisions.json:
    {"<app id>": {"r7": "Refactor", "target": "...", "rationale": ["..."], "by": "name", "date": "YYYY-MM-DD"}}
and reruns this script; decisions always win over rules (marked decision_source = "review").
Rules implemented (see references/seven-rs.md):
  - modern .NET, no Windows-bound findings            -> Replatform to Linux containers (upgrade TFM if out of support)
  - .NET Framework web/service, portable               -> Replatform (port to .NET 10 on Linux)
  - Web Forms UI                                       -> Refactor (UI rewrite) when small, else Retain on .NET Framework
                                                          + hybrid (.NET Standard 2.0 shared libraries) - the hybrid pattern
  - Windows-bound blockers (COM, Win32, Office, Crystal, WF, Remoting, MSMQ, unsupported WCF bindings)
                                                       -> Rehost on Windows now, Refactor the blocking component later
  - desktop (WinForms/WPF)                              -> Retain (client), upgrade to .NET 10 Windows Desktop
  - possible duplicates / dormant                       -> flagged as Retire candidates for the client to confirm
"""
import datetime
import os
import re
from collections import Counter, defaultdict

from _common import OUT, data, load_config, mark_step, read_json, utf8_stdout, write_json
import _findings as F


def app_findings(findings, app_id):
    return [f for f in findings if app_id in f.get("apps", [])]


def classify(app, inv, fs, rules, cfg, shared_users, name_counts):
    target_fw = cfg.get("target_dotnet", "net10.0").replace("net", ".NET ").replace(".0", "")
    t = rules["targets"]
    typ = app["type"]
    ids = {f["rule"].split(":")[0] for f in fs}
    pkg_blockers = [f for f in fs if f["rule"].startswith("PKG-") and f.get("severity") in ("Blocker", "High") and "blocker" in f["rule"].lower() or
                    (f.get("category") == "packages" and f.get("severity") in ("Blocker",))]
    bound = sorted({f["rule"].split(":")[0] for f in fs if f["rule"].split(":")[0] in rules["windows_bound_rules"] and f["severity"] in ("Blocker", "High")} |
                   ({"PKG-BLOCKER"} if pkg_blockers else set()))
    ui = [f for f in fs if f["rule"] in rules["ui_rewrite_rules"]] if typ in ("aspnet-webforms", "website") else []  # a few Web Forms controls inside an MVC app are a finding, not the app's path
    sev = Counter(f["severity"] for f in fs)
    linux_issues = [f for f in fs if f["category"] in ("linux-readiness", "api-portability") and f["severity"] in ("Blocker", "High")]
    fam = app.get("framework_family", "")
    tfms = app.get("target_frameworks", [])
    proj = next((p for p in inv["projects"] if p["path"] == app["entry"]), {})
    tfm_status = {x["status"] for x in proj.get("tfm_support", [])}
    pages = sum(v for p in inv["projects"] if p["path"] in app["projects"] for k, v in (p.get("files_by_ext") or {}).items() if k in (".aspx", ".ascx", ".master"))
    kloc = round(app.get("loc", 0) / 1000.0, 1)
    rationale, options, hybrid = [], [], None
    if typ == "database":
        return {"r7": "Replatform", "target": t["database"], "rationale": ["SQL Server database project: see the database assessment."], "options": []}
    if typ in rules["desktop_types"]:
        r7, target = "Retain", t["windows-desktop"]
        rationale.append(f"{typ.upper()} desktop client: runs only on Windows, even on .NET 10.")
        if "netfx" in fam:
            rationale.append(f"Upgrade from {', '.join(tfms) or '.NET Framework'} to {target_fw} Windows Desktop when the back end moves (back-end endpoints change).")
        options.append("Refactor to a web front end if the business wants browser access (large).")
    elif "netcore" in fam and not any(x.endswith("-windows") for x in tfms) and not bound and not linux_issues:
        r7 = "Replatform"
        target = t["linux-batch" if typ in ("console", "netcore-console") else "linux-worker" if typ in ("windows-service", "netcore-worker")
                   else "linux-container"].format(target=target_fw)
        rationale.append("Already on cross-platform .NET with no Windows-only blockers found: move to Linux hosting directly.")
        if "out-of-support" in tfm_status or "ending-soon" in tfm_status:
            rationale.append(f"Target framework {', '.join(tfms)} is out of (or ending) support: retarget to {target_fw} in the same step.")
        if "netfx" in fam:
            rationale.append("Still targets .NET Framework (ASP.NET Core on Framework): retarget first.")
    elif (bound and len(bound) >= rules["large_blocker_count_for_rehost"] or ("PKG-BLOCKER" in bound and len(bound) > 1)) and             len({fl for f in fs if f["rule"].split(":")[0] in rules["windows_bound_rules"] and f["severity"] in ("Blocker", "High") for fl in f.get("files", [])}) > rules.get("windows_bound_max_files_to_replace", 10):
        r7 = "Rehost"
        target = t["windows-retain"]
        rationale.append(f"Windows-bound dependencies ({', '.join(bound)}) need replacement before Linux; rehost on Windows now and refactor them as a follow-up.")
        options.append(f"Refactor: replace {', '.join(bound)} and replatform to {target_fw} on Linux (higher effort, removes Windows licensing).")
    elif ui:
        big = kloc >= rules["webforms_retain_thresholds"]["kloc"] or pages >= rules["webforms_retain_thresholds"]["pages"]
        if big:
            r7, target = "Retain", t["windows-retain"]
            rationale.append(f"ASP.NET Web Forms ({pages} pages, {kloc} KLOC) is tightly coupled to System.Web.UI, which has no ASP.NET Core equivalent; a full UI rewrite is not proportionate as a first step.")
            rationale.append("Retain this app on .NET Framework 4.8.1 (Windows), move shared libraries to netstandard2.0 so modernized apps can reference them (hybrid).")
            options.append(f"Refactor: rewrite the UI in Blazor/Razor Pages ({target_fw}); AWS Transform can port Web Forms UI to Blazor; incremental route-by-route with YARP + System.Web adapters.")
        else:
            r7, target = "Refactor", t["linux-container"].format(target=target_fw)
            rationale.append(f"Web Forms UI ({pages} pages, {kloc} KLOC) is small enough to rewrite (Blazor / Razor Pages) during the port.")
            options.append("Retain on .NET Framework (Windows) with hybrid shared libraries if the rewrite budget is not approved.")
        hybrid = True
    elif typ == "wcf-service":
        r7, target = "Replatform", t["linux-container"].format(target=target_fw)
        rationale.append("WCF service: port to CoreWCF (keeps the SOAP contract for existing callers) on Linux; or re-expose as REST/gRPC if callers can change.")
        options.append("Refactor to REST/gRPC (contract change for all callers).")
    elif typ == "windows-service":
        r7, target = "Replatform", t["linux-worker"].format(target=target_fw)
        rationale.append("Windows service becomes a .NET Worker Service (BackgroundService) on Linux.")
    elif typ in ("console", "netcore-console"):
        r7, target = "Replatform", t["linux-batch"].format(target=target_fw)
        rationale.append("Console/batch application: port and run as a scheduled container task.")
    elif typ == "netcore-worker":
        r7, target = "Replatform", t["linux-worker"].format(target=target_fw)
        rationale.append("Worker Service on modern .NET: retarget and run as a long-running container service.")
    elif typ == "website":
        r7, target = "Rehost", t["windows-retain"]
        rationale.append("Web Site project without a project file: convert to a Web Application project before any port (AWS Transform requirement).")
        options.append("Replatform after conversion.")
    else:
        r7, target = "Replatform", t["linux-container"].format(target=target_fw)
        rationale.append(f"{typ} on {', '.join(tfms) or fam}: portable to {target_fw} on Linux; findings below are code changes, not architectural blockers.")
    if bound and r7 in ("Replatform", "Refactor"):
        rationale.append(f"Windows-bound items to replace during the port: {', '.join(bound)}.")
    # hybrid / shared libraries
    shared = [s for s in inv.get("shared_libraries", []) if app["entry"] in [p for p in app["projects"][:1]] and s["path"] in app["projects"]]
    if shared:
        hybrid = True
    notes = []
    if name_counts.get(app["name"], 0) > 1:
        notes.append(f"Another application named '{app['name']}' exists in this estate: confirm whether one is a duplicate/variant to Retire.")
    g = inv.get("git", {})
    if g.get("git") and g.get("last_commit"):
        try:
            age = (datetime.date.today() - datetime.date.fromisoformat(g["last_commit"])).days
            if age > 3 * 365:
                notes.append(f"Repository last changed {g['last_commit']} ({age // 365} years ago): confirm the application is still in use (Retire candidate).")
        except ValueError:
            pass
    risk = "High" if sev["Blocker"] or len(bound) >= 2 else ("Medium" if sev["High"] >= 3 else "Low")
    needs = sum(1 for f in fs if f.get("confidence") == "Needs verification")
    confidence = "High" if needs <= 2 and sev["Blocker"] == 0 else ("Medium" if needs <= 8 else "Low")
    return {"r7": r7, "target": target, "rationale": rationale, "options": options, "windows_bound": bound, "web_forms_pages": pages,
            "kloc": kloc, "risk": risk, "confidence": confidence, "notes": notes, "hybrid": bool(hybrid),
            "findings_by_severity": dict(sev), "linux_ready": not bound and not ui and typ not in rules["desktop_types"] and not linux_issues}


def main():
    utf8_stdout()
    root, cfg = load_config()
    os.chdir(root)
    rules = data("decision_rules.json")
    decisions = read_json(os.path.join(OUT, "decisions.json"), {}) or {}
    result = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "applications": [], "hybrid": []}
    all_apps = []
    for repo in F.repos(root):
        inv = F.load_inventory(root, repo)
        if inv:
            all_apps += [(repo, inv, a) for a in inv["applications"]]
    name_counts = Counter(a["name"] for _, _, a in all_apps)
    for repo in F.repos(root):
        inv = F.load_inventory(root, repo)
        if not inv:
            continue
        fs = F.assign_apps(F.load(root, repo), inv)
        users = defaultdict(list)
        for a in inv["applications"]:
            for p in a["projects"][1:]:
                users[p].append(a)
        apps_out = []
        for a in inv["applications"]:
            c = classify(a, inv, app_findings(fs, a["id"]), rules, cfg, users, name_counts)
            entry = {"id": a["id"], "repo": repo, "name": a["name"], "type": a["type"], "entry": a["entry"], "framework_family": a["framework_family"],
                     "target_frameworks": a["target_frameworks"], "loc": a["loc"], "projects": a["projects"], **c, "decision_source": "rules"}
            d = decisions.get(a["id"])
            if d:
                entry.update({k: v for k, v in d.items() if k in ("r7", "target", "rationale", "options", "risk", "confidence", "notes")})
                entry["decision_source"] = "review"
                entry["decided_by"] = d.get("by")
            apps_out.append(entry)
        result["applications"] += apps_out
        # hybrid analysis: shared libraries used by both retained (.NET Framework) and modernized apps
        by_id = {x["id"]: x for x in apps_out}
        for s in inv.get("shared_libraries", []):
            users_s = [x for x in apps_out if s["path"] in x["projects"][1:]]
            retained = [x["name"] for x in users_s if x["r7"] in ("Retain", "Rehost") and x["type"] not in rules["desktop_types"]]
            moving = [x["name"] for x in users_s if x["r7"] in ("Replatform", "Refactor")]
            desk = [x["name"] for x in users_s if x["type"] in rules["desktop_types"]]
            lib_f = [f for f in fs if s["path"] in f.get("projects_in_scope", [])]
            sysweb = any(f["rule"] in ("WEB-SYSTEMWEB", "WEB-HTTPCONTEXT-CURRENT") for f in lib_f)
            fx_now = [x["name"] for x in users_s if "netfx" in x.get("framework_family", "")]
            if (retained or desk) and moving:
                plan = "netstandard2.0 (permanent while .NET Framework consumers remain)"
            elif moving and fx_now:
                plan = f"netstandard2.0 (or multi-target net48;{cfg.get('target_dotnet', 'net10.0')}) during the transition, then {cfg.get('target_dotnet', 'net10.0')} once every consumer has moved"
            else:
                plan = f"retarget to {cfg.get('target_dotnet', 'net10.0')} with its consumers"
            result["hybrid"].append({"repo": repo, "library": s["name"], "path": s["path"], "used_by": s["used_by"], "retained_consumers": retained + desk,
                                     "modernized_consumers": moving, "current": s["target_frameworks"], "plan": plan, "uses_system_web": sysweb,
                                     "note": ("Uses System.Web: target netstandard2.0 with Microsoft.AspNetCore.SystemWebAdapters, or move the System.Web code back into the web apps."
                                              if sysweb else "Pure library: netstandard2.0 lets .NET Framework 4.6.2+ and .NET 10 apps share one build.")})
            _ = by_id
    write_json(os.path.join(OUT, "classification.json"), result)
    mark_step(root, "classify")
    c = Counter(a["r7"] for a in result["applications"])
    print(f"{len(result['applications'])} applications: " + ", ".join(f"{k} {v}" for k, v in c.most_common()) +
          f"; {len(result['hybrid'])} shared libraries analysed for hybrid; {sum(1 for a in result['applications'] if a['decision_source'] == 'review')} reviewer decisions applied")
    for a in result["applications"]:
        print(f"  {a['r7']:<10} {a['name']:<28} {a['type']:<16} risk {a['risk']:<6} -> {a['target'][:90]}")


if __name__ == "__main__":
    main()
