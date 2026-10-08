"""Quality gates for the assessment (deterministic). Exit code 1 when any gate fails.

    python <skill>/scripts/verify_report.py [--allow-draft]

Gates
  1 evidence        every finding has file+line (or package) evidence, and every cited file exists with that many lines
  2 coverage        every category appears in the report with findings or "Checked, none found." (lift-and-shift: every
                    in-scope category in section 5, and section 8.2 for the out-of-scope modernization findings)
  3 review          every Blocker/High finding with confidence "Needs verification" has a reviewer verdict
  4 decisions       every application has a reviewed 7R decision in assessment/decisions.json (--allow-draft: warning only)
  5 narratives      no PENDING markers left in assessment/narrative/*.md and no missing narrative in the report
  6 secrets         no secret value from the client's config/code appears in the report or exports
  7 structure       report sections 1-11 present; estimate, open questions and an up-to-date HTML report present
  8 dependencies    sections 4.5-4.8 present; every inventoried project in the interdependency table; workflows traced for every application
                    (lift-and-shift: section 4.5 with every project; workflow tracing not required)
"""
import argparse
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

from _common import OUT, data, load_config, load_state, read_json, read_text, utf8_stdout
import _findings as F
import build_report as BR

SECRET_KEY = re.compile(r"(?i)pass|pwd|secret|token|apikey|api_key|accesskey|credential|privatekey|clientkey|sharedkey|decryptionkey|validationkey")
LITERAL = re.compile(r"(?i)\b\w*(password|passwd|pwd|secret|apikey|api_key|accesskey|clientsecret|token)\w*\s*(=|:)\s*@?\"([^\"\s]{6,})\"")


def secret_values(inv_root):
    vals = set()
    for d, dirs, files in os.walk(inv_root):
        dirs[:] = [x for x in dirs if x.lower() not in {"bin", "obj", "packages", "node_modules", ".git", ".vs"}]
        for fn in files:
            low = fn.lower()
            p = os.path.join(d, fn)
            try:
                if low.endswith(".config"):
                    root = ET.fromstring(read_text(p).encode("utf-8"))
                    for add in root.iter("add"):
                        if add.get("key") and SECRET_KEY.search(add.get("key")) and add.get("value"):
                            vals.add(add.get("value"))
                        cs = add.get("connectionString") or ""
                        vals.update(m.strip() for m in re.findall(r"(?i)(?:password|pwd)\s*=\s*([^;\"]+)", cs))
                    for mk in root.iter("machineKey"):
                        vals.update(v for k, v in mk.attrib.items() if k.lower().endswith("key"))
                elif low.endswith((".cs", ".vb")) and os.path.getsize(p) < 2_000_000:
                    for m in LITERAL.finditer(read_text(p)):  # a value equal to its own constant name (const string FooToken = "FooToken") is a key name, not a secret
                        if m.group(3).lower() != re.match(r"\w+", m.group(0)).group(0).lower():
                            vals.add(m.group(3))
                elif re.search(r"(?i)^(?!launchsettings)[\w.-]*(settings|secrets)[\w.-]*\.json$", low):
                    vals.update(re.findall(r'(?i)"[^"]*(?:password|secret|token|apikey|key)[^"]*"\s*:\s*"([^"]{6,})"', read_text(p)))
                    vals.update(m.strip() for m in re.findall(r"(?i)(?:password|pwd)\s*=\s*([^;\"]+)", read_text(p)))
            except (ET.ParseError, OSError, ValueError):
                continue
    return {v for v in vals if len(v) >= 6 and not re.fullmatch(r"(?i)(true|false|\d+|none|null|\*+|\$\(.*\)|#\{.*\}|__\w+__|\{.*\}|changeme|password|secret)", v)
            and not re.fullmatch(r"(?i)https?://[^?@\s]+(\?[^@\s]*=)?", v)}  # a plain endpoint URL is not a secret (credentials/query strings are)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-draft", action="store_true")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    results = []
    repos = F.repos(root)
    findings = []
    invs = {}
    for r in repos:
        inv = F.load_inventory(root, r)
        if inv:
            invs[r] = inv
            findings += F.assign_apps(F.load(root, r), inv)
    # 0 every repository analysed: scanned after its latest inventory, graphed, SQL parsed (a failed step must not leave a
    # report that silently reuses older or missing data)
    st = load_state(root)
    gaps0 = []
    for r in repos:
        sp = os.path.join(OUT, "scan", f"{r}.json")
        ip = os.path.join(OUT, "inventory", f"{r}.json")
        if not os.path.exists(sp) or not os.path.exists(os.path.join(OUT, "findings", f"{r}.json")):
            gaps0.append(f"{r}: never scanned")
            continue
        if os.path.exists(ip) and os.path.getmtime(sp) < os.path.getmtime(ip) - 1:
            gaps0.append(f"{r}: scan older than inventory (rerun scan_repo.py)")
        if st["repos"].get(r, {}).get("graph") != "done":
            gaps0.append(f"{r}: not graphed (map_graphs.py)")
        dbi = (read_json(sp, {}) or {}).get("db_inventory") or {}
        if dbi.get("note"):
            gaps0.append(f"{r}: SQL not parsed ({dbi['note'][:80]})")
    results.append(("every repository analysed", bool(repos) and not gaps0, f"{len(repos)} repositories" + (f"; {'; '.join(gaps0[:6])}" if gaps0 else "")))
    # 1 evidence
    bad, missing = [], []
    cache = {}
    for f in findings:
        if not F.has_evidence(f):
            bad.append(f["id"])
            continue
        base = invs.get(f["repo"], {}).get("root", "")
        for e in f.get("evidence", [])[:5]:
            fp = e.get("file")
            if not fp or fp in (".git",) or f["rule"].startswith(("PKG-", "SEC-VULN")):
                continue
            full = os.path.join(base, fp)
            if fp not in cache:
                cache[fp] = len(read_text(full).splitlines()) if os.path.isfile(full) else (-1 if not os.path.isdir(full) else 10 ** 9)
            n = cache[fp]
            if n < 0 or (e.get("line") and e["line"] > max(n, 1)):
                missing.append(f"{f['id']} -> {fp}:{e.get('line')}")
    results.append(("evidence on every finding", not bad and not missing, f"{len(findings)} findings; without evidence: {len(bad)}; unresolvable citations: {len(missing)}" +
                    (" (" + "; ".join((bad + missing)[:4]) + ")" if bad or missing else "")))
    # 2 coverage
    reports = [p for p in glob.glob(os.path.join(OUT, "report", "*.md"))]
    report = open(reports[0], encoding="utf-8").read() if reports else ""
    cats = data("categories.json")["categories"]
    is_lift = BR.lift(cfg)
    if is_lift:  # lift-and-shift report: section 5 holds the in-scope categories, 8.2 summarises the rest (Linux / .NET modernization)
        hs = data("estimation.json")["hosting_scenarios"].get((cfg.get("scenario") or {}).get("hosting") or "", {})
        keep = {"categories": set(hs.get("keep_categories", [])), "rules": set(hs.get("keep_rules", []))}
        future_ok = "### 8.2 " in report
        cats = [c for c in cats if c["id"] in keep["categories"] or any(f["category"] == c["id"] and BR.in_scope(f, keep) for f in findings)]
    gaps = [] if not is_lift or future_ok else ["8.2 future modernization findings (missing)"]
    for c in cats:
        m = re.search(rf"(?m)^### 5\.\d+ {re.escape(c['title'])}\s*$(.*?)(?=^### |^## |\Z)", report, re.S)
        if not m:
            gaps.append(f"{c['id']} (missing)")
        elif c["id"] != "tooling" and "Checked, none found." not in m.group(1) and "| Ref |" not in m.group(1):
            gaps.append(f"{c['id']} (no findings table / statement)")
    results.append(("every category reported", bool(report) and not gaps, f"{len(cats)} categories" + (f"; gaps: {', '.join(gaps)}" if gaps else "") + ("" if report else "; report not built")))
    # 3 review of uncertain high-impact findings
    unreviewed = [f["id"] for f in findings if f["severity"] in ("Blocker", "High") and f.get("confidence") == "Needs verification" and not f.get("review")]
    results.append(("uncertain Blocker/High findings reviewed", not unreviewed, f"{len(unreviewed)} unreviewed" + (f": {', '.join(unreviewed[:5])}" if unreviewed else "")))
    # 4 decisions
    cls = read_json(os.path.join(OUT, "classification.json"), {"applications": []})
    draft = [x["name"] for x in cls["applications"] if x.get("decision_source") != "review"]
    ok4 = not draft or a.allow_draft
    results.append(("7R decisions reviewed", ok4, f"{len(cls['applications'])} applications; draft (not reviewed): {len(draft)}" + (f" ({', '.join(draft[:6])})" if draft else "") + (" [allowed]" if draft and a.allow_draft else "")))
    # 5 narratives
    todo = [os.path.basename(p) for p in glob.glob(os.path.join(OUT, "narrative", "*.md")) if re.search(r"(?m)^(?:PENDING|TODO):", open(p, encoding="utf-8").read())]
    missing_n = re.findall(r"_Narrative '([\w-]+)' not written yet\._", report)
    results.append(("narratives written", not todo and not missing_n, f"PENDING in: {', '.join(todo) or 'none'}; missing: {', '.join(missing_n) or 'none'}"))
    # 5b finding references: F-numbers are positions in the sorted findings and move on every rescan; narratives cite {{f:RULE}} tags
    raw = []
    unresolved = re.findall(r"\*\*\[finding ([^\]]+) not found\]\*\*", report) + re.findall(r"\*\*\[value ([^\]]+?) (?:not found|is not a number or text)\]\*\*", report)
    for p in glob.glob(os.path.join(OUT, "narrative", "*.md")) + [os.path.join(OUT, "decisions.json")] + glob.glob(os.path.join(OUT, "reviews", "*.json")):
        if not os.path.exists(p):
            continue
        body = re.sub(r"(?s)<!--.*?-->", "", open(p, encoding="utf-8").read())
        if re.search(r"\bF-\d{3}\b", body):
            raw.append(os.path.basename(p))
    results.append(("finding references and values current", not raw and not unresolved,
                    f"raw F-numbers in: {', '.join(raw) or 'none'} (use {{{{f:RULE}}}} tags); unresolved {{{{f:}}}} / {{{{v:}}}} tags: {', '.join(sorted(set(unresolved))) or 'none'}"))
    # 6 secrets
    vals = set()
    for inv in invs.values():
        vals |= secret_values(inv["root"])
    htmls = glob.glob(os.path.join(OUT, "report", "*.html"))
    outputs = reports + htmls + glob.glob(os.path.join(OUT, "report", "*.csv")) + glob.glob(os.path.join(OUT, "report", "*.json")) + glob.glob(os.path.join(OUT, "findings", "*.json"))
    leaks = []
    for p in outputs:
        t = open(p, encoding="utf-8-sig", errors="ignore").read()
        for v in vals:
            # a plain short word (letters only) right after a slash or joined to other letters by a dot or hyphen (host label, URL path, hyphenated name) is a coincidence, not a leak;
            # anything longer or with digits/symbols must not appear at all as a standalone token
            word = v.isalpha() and len(v) <= 12
            pre = r"(?<![A-Za-z0-9_])" + (r"(?<![/])(?<![A-Za-z0-9_][.-])" if word else "")
            post = r"(?![A-Za-z0-9_])" + (r"(?![.-][A-Za-z0-9_])" if word else "")
            if v in t and re.search(pre + re.escape(v) + post, t):
                leaks.append(os.path.basename(p))
                break
    results.append(("no secret values in outputs", not leaks, f"checked {len(vals)} secret values from client config/code against {len(outputs)} files" + (f"; LEAK in {', '.join(sorted(set(leaks)))}" if leaks else "")))
    # 7 structure
    heads = [f"## {i}." for i in range(1, 12)]
    absent = [h for h in heads if h not in report]
    est = read_json(os.path.join(OUT, "estimate.json"), {})
    oq = os.path.join(OUT, "report", "open-questions.csv")
    stale = bool(htmls) and bool(reports) and os.path.getmtime(htmls[0]) < os.path.getmtime(reports[0]) - 1
    ok7 = not absent and bool(est.get("totals", {}).get("likely_days")) and os.path.exists(oq) and bool(htmls) and not stale
    results.append(("report structure", ok7, f"missing sections: {', '.join(absent) or 'none'}; estimate: {'yes' if est else 'no'}; open questions: {'yes' if os.path.exists(oq) else 'no'}; "
                    f"HTML report: {'stale (rerun build_html_report.py)' if stale else ('yes' if htmls else 'missing (run build_html_report.py)')}"))
    # 8 dependencies: project interdependencies and workflow tracing
    if is_lift:  # lift-and-shift layout: 4.5 is the project interdependency table (what must move together); no workflow sections
        miss_sec = [h for h in ("### 4.5 ",) if h not in report]
        sec45 = re.split(r"(?m)^## ", report.split("### 4.5 ", 1)[1], maxsplit=1)[0] if "### 4.5 " in report else ""
        sec46 = ""
    else:
        miss_sec = [h for h in ("### 4.5 ", "### 4.6 ", "### 4.7 ", "### 4.8 ") if h not in report]
        sec45 = report.split("### 4.5 ", 1)[1].split("### 4.6 ", 1)[0] if "### 4.5 " in report and "### 4.6 " in report else ""
        sec46 = report.split("### 4.6 ", 1)[1].split("### 4.7 ", 1)[0] if "### 4.6 " in report and "### 4.7 " in report else ""
    miss_proj = [p["name"] for inv in invs.values() for p in inv["projects"] if p["name"] not in sec45]
    apps = [x["name"] for x in cls["applications"] if x.get("r7") != "Retire"]
    npath = os.path.join(OUT, "narrative", "dependencies.md")
    ntext = read_text(npath) if os.path.exists(npath) else ""
    no_wf = [] if is_lift else [n for n in apps if "#### " + n + " " not in sec46 and n not in ntext]
    ok8 = not miss_sec and not miss_proj and not no_wf
    results.append(("dependencies mapped", ok8, f"missing sections: {', '.join(miss_sec) or 'none'}; projects not in 4.5: {len(miss_proj)}; applications without traced workflows: {', '.join(no_wf) or 'none'}"
                    + ("" if not no_wf else " (no entry points detected: describe the app's workflows manually in the dependencies narrative and mention the app by name)")))
    w = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{w}}  {detail}")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)


if __name__ == "__main__":
    main()
