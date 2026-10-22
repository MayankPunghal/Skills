"""Tracking workbook: every finding, Windows-only API use, Linux readiness hit, work item, package, DLL, AWS managed-service
swap, open question and application in one .xlsx, each row with Status / Owner / Notes columns for the team to fill in.

    py -X utf8 build_tracker.py [--out assessment/report/<client>-Modernization-Tracker.xlsx]

Run after build_report.py (reads assessment/report/findings.json and the CSV exports), linux_readiness.py and
estimate_phases.py. Standard library only (_xlsx.py). Values from client config are never written: findings carry the
masked evidence text the scan already stores.

Sheets: Summary, Findings, Windows-only APIs (Linux readiness and .NET modernization findings, one row per evidence
line), Linux readiness (every linux_readiness.py hit), Work items (phased estimate lines), Packages, DLLs, AWS services,
Open questions, Applications.
"""
import argparse
import csv
import glob
import json
import os
import re

from _common import OUT, data, load_config, load_state, read_json, utf8_stdout
import _xlsx

TRACK = ["Status", "Owner", "Notes"]
SEVS = ["Blocker", "High", "Medium", "Low", "Info"]


def csv_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


def ev_text(e):
    loc = f"{e.get('file')}:{e.get('line')}" if e.get("line") else str(e.get("file") or e.get("package") or "")
    return loc


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    st = load_state(root)
    repos = sorted(r for r in st["repos"] if st["repos"][r].get("scope") != "out")
    client = re.sub(r"[^\w.-]+", "-", cfg.get("client") or "Client").strip("-")
    out = a.out or os.path.join(OUT, "report", f"{client}-Modernization-Tracker.xlsx")

    fj = read_json(os.path.join(OUT, "report", "findings.json"), {}) or {}
    findings = fj["findings"] if isinstance(fj, dict) else fj
    if not findings:
        raise SystemExit("no assessment/report/findings.json: run build_report.py first")
    cats = {c["id"]: c for c in data("categories.json")["categories"]}
    cls = read_json(os.path.join(OUT, "classification.json"), {}) or {}
    app_name = {x["id"]: x["name"] for x in cls.get("applications", [])}
    key = lambda f: (SEVS.index(f["severity"]) if f["severity"] in SEVS else 9, f.get("ref", ""))
    findings = sorted(findings, key=key)

    # Findings: one row per finding
    rows = [["Ref", "Severity", "Confidence", "Area", "Category", "Rule", "Title", "Applications", "Project", "Occurrences",
             "Evidence (first 3)", "Why it matters", "Fix", "Alternative", "Source"] + TRACK]
    for f in findings:
        c = cats.get(f["category"], {})
        rows.append([f.get("ref"), f["severity"], f.get("confidence", ""), c.get("segment", ""), c.get("title", f["category"]), f["rule"],
                     f["title"], ", ".join(app_name.get(x, x) for x in f.get("apps") or []), f.get("project", ""), f.get("occurrences", 1),
                     "; ".join(ev_text(e) for e in (f.get("evidence") or [])[:3]), f.get("why", ""), f.get("fix", ""), f.get("alt", ""),
                     f.get("source", "scan"), "Open", "", ""])
    sheets = [_xlsx.auto("Findings", rows)]

    # Windows-only APIs: Linux readiness and .NET modernization findings, one row per evidence line
    rows = [["Ref", "Severity", "Rule", "API / issue", "File:line", "Code (masked)", "Fix"] + TRACK]
    for f in findings:
        if cats.get(f["category"], {}).get("segment") not in ("linux", "modernization"):
            continue
        for e in f.get("evidence") or []:
            rows.append([f.get("ref"), f["severity"], f["rule"], f["title"], ev_text(e), (e.get("text") or "")[:200], f.get("fix", ""), "Open", "", ""])
    sheets.append(_xlsx.auto("Windows-only APIs", rows))

    # Linux readiness: every hit from linux_readiness.py
    rows = [["Repository", "Check", "Level", "Area", "File", "Line", "Code (masked)", "What breaks", "Fix", "Waived"] + TRACK]
    for r in repos:
        lr = read_json(os.path.join(OUT, "linux", r, "linux-readiness.json"), {}) or {}
        rules = lr.get("rules") or {}
        for h in lr.get("hits", []):
            ru = rules.get(h["rule"], {}) if isinstance(rules, dict) else {}
            rows.append([r, h["rule"], ru.get("level", ""), ru.get("area", ""), h.get("file", ""), h.get("line", ""), (h.get("text") or "")[:200],
                         ru.get("what", ""), ru.get("fix", ""), "yes" if h.get("waived") else "", "Open", "", ""])
    rows[1:] = sorted(rows[1:], key=lambda x: ({"block": 0, "warn": 1, "info": 2}.get(x[2], 3), x[1], x[4], str(x[5])))
    sheets.append(_xlsx.auto("Linux readiness", rows))

    # Work items: the phased estimate lines
    rows = [["Repository", "Phase", "Item", "Work", "Who / tool", "Low h", "High h", "Quantities x rates", "Basis", "Assumption status"] + TRACK]
    for r in repos:
        est = read_json(os.path.join(OUT, "effort", r, "estimate.json"), {}) or {}
        pof = {i: p["id"] for p in est.get("phases", []) for i in p["items"]}
        for x in sorted(est.get("items", []), key=lambda x: (pof.get(x["id"], "P9"), x["id"])):
            rows.append([r, pof.get(x["id"], ""), x["id"], x["label"], x.get("tool", ""), x["low"], x["high"], "; ".join(x.get("drivers") or []),
                         x.get("basis", ""), x.get("status", ""), "Open", "", ""])
        if est.get("total"):
            rows.append([r, "", "TOTAL", f"subtotal {est['subtotal'][0]}-{est['subtotal'][1]} h + {int(est.get('buffer', 0) * 100)}% buffer "
                         f"({est.get('rate_profile', '')} rates)", "", est["total"][0], est["total"][1], "", "", "", "", "", ""])
    sheets.append(_xlsx.auto("Work items", rows))

    # Packages, open questions, applications: the report's own exports
    pk = csv_rows(os.path.join(OUT, "report", "packages.csv"))
    if pk:
        sheets.append(_xlsx.auto("Packages", [pk[0] + TRACK] + [r + ["Open", "", ""] for r in pk[1:]]))

    # DLLs (HintPath references, not NuGet)
    rows = [["Repository", "Project", "Assembly", "Version", "Path", "Built for", "Other builds", "NuGet match", "Runs on Linux", "Source", "Action"] + TRACK]
    for r in repos:
        facts = read_json(os.path.join(OUT, "effort", r, "facts.json"), {}) or {}
        for b in facts.get("binary_references", []):
            rows.append([r, b.get("project", ""), b.get("assembly", ""), b.get("version", ""), b.get("hint", ""), b.get("built_for", ""),
                         b.get("other_builds", ""), b.get("nuget", ""), b.get("runs_on_linux", ""), b.get("source", ""), b.get("action", ""), "Open", "", ""])
    if len(rows) > 1:
        sheets.append(_xlsx.auto("DLLs", rows))

    # AWS managed services: server-hosted services and the chosen AWS option
    rows = [["Repository", "Service", "Kind", "Chosen AWS option", "Change", "Hours (Claude-first)", "Manual-equivalent h", "Call sites", "Config entries", "Work"] + TRACK]
    for r in repos:
        aws = read_json(os.path.join(OUT, "effort", r, "aws-native.json"), {}) or {}
        inp = read_json(os.path.join(OUT, "effort", r, "estimate-inputs.json"), {}) or {}
        choices = (inp.get("aws_native_choices") or {}).get("value") or {}
        for s in aws.get("services", []):
            o = next((x for x in s["options"] if x["id"] == choices.get(s["id"])), None) or next((x for x in s["options"] if x.get("chosen")), s["options"][0])
            rows.append([r, s["label"], s.get("kind", ""), o["aws"], o["change"], f"{o['hours'][0]:g}-{o['hours'][1]:g}",
                         f"{o['manual_hours'][0]:g}-{o['manual_hours'][1]:g}", s.get("consumer_sites", 0), s.get("config_entries", 0), o.get("work", ""), "Open", "", ""])
    if len(rows) > 1:
        sheets.append(_xlsx.auto("AWS services", rows))

    oq = csv_rows(os.path.join(OUT, "report", "open-questions.csv"))
    if oq:
        sheets.append(_xlsx.auto("Open questions", [oq[0] + ["Owner", "Due", "Notes"]] + [r + ["", "", ""] for r in oq[1:]]))
    apps = csv_rows(os.path.join(OUT, "report", "applications.csv"))
    if apps:
        sheets.append(_xlsx.auto("Applications", apps))

    # Projects in migration order: every project (class libraries and tests included) with its own 7R, difficulty and blast radius
    pm = read_json(os.path.join(OUT, "report", "projects.json"), {}) or {}
    rows = [["#", "Wave", "Repository", "Project", "Path", "Kind", "Deployable", "Lines", "Difficulty", "Why this difficulty", "7R", "Target", "Port first",
             "Used by", "Blast radius", "Projects depending on it", "Deployables to retest", "Blocker / High findings"] + TRACK]
    for x in pm.get("projects", []):
        rows.append([x["order"], x["wave"], x["repo"], x["name"], x["path"], x["kind"], "yes" if x["deployable"] else "", x.get("loc", 0), x["difficulty"],
                     "; ".join(x.get("difficulty_why", [])), x["r7"], x.get("target", ""), ", ".join(x["needs_first"]), ", ".join(u["name"] for u in x["used_by"]),
                     x["blast"]["level"], x["blast"]["transitive"], ", ".join(x["blast"]["deployables"]), "; ".join(x.get("blockers", [])), "Open", "", ""])
    if len(rows) > 1:
        sheets.append(_xlsx.auto("Projects", rows))

    # Sign-in and access: one row per mechanism found, with the ASP.NET Core and AWS replacement
    auth = read_json(os.path.join(OUT, "report", "auth.json"), []) or []
    rows = [["Application", "Repository", "Who signs in", "Area", "Today", "Severity", "How it works now", "On ASP.NET Core", "AWS options (first = recommended)", "Where"] + TRACK]
    for a in auth:
        for m in a.get("mechanisms", []):
            rows.append([a["app"], a["repo"], a["who"], m["area"], m["label"], m.get("severity", ""), m["today"], m["core"], " | ".join(m["aws"]), "; ".join(m.get("where", [])[:3]), "Open", "", ""])
    if len(rows) > 1:
        sheets.append(_xlsx.auto("Sign-in and access", rows))

    # Summary first
    sev = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVS}
    summ = [["Item", "Value"], ["Client", cfg.get("client", "")], ["Repositories", ", ".join(repos)],
            ["Findings", f"{len(findings)} (" + ", ".join(f"{k} {v}" for k, v in sev.items()) + ")"]]
    for name, rows_, *_ in sheets:
        summ.append([f"Sheet: {name}", f"{len(rows_) - 1} rows"])
    summ.append(["How to use", "Every tracking sheet ends with Status / Owner / Notes. Status values: Open, In progress, Done, Won't do, Question. "
                 "Rebuilding this file from the scripts overwrites it: keep the team's copy under another name, or copy the columns across."])
    sheets.insert(0, _xlsx.auto("Summary", summ))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    _xlsx.write(out, sheets)
    print(f"tracker: {out} ({', '.join(f'{n} {len(r) - 1}' for n, r, *_ in sheets[1:])})")


if __name__ == "__main__":
    main()
