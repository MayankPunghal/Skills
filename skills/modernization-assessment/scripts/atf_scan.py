"""AWS Transform codebase scanner (RadNet and RaSQL presets), run first, then cross-checked with this skill's own scan.

    py -X utf8 atf_scan.py [--presets radnet,rasql] [--repo X] [--dry-run]        run the scanner for the estate
    py -X utf8 atf_scan.py --import <radnet|rasql results .zip or .csv> ...        use results run elsewhere
    py -X utf8 atf_scan.py --reconcile-only                                        cross-check again (after scan_repo.py)

The scanner is AWS's (the AWS Transform codebase scanner, `Invoke-CodebaseScanner.ps1`); it is not shipped with this
skill. Point `atf_scanner_dir` in assessment.json (or ATF_SCANNER_DIR) at the folder that holds it. It needs PowerShell
7.2+ (`pwsh`) and the `powershell-yaml` module, scans locally and uploads nothing. Without it the step is skipped and
the report says so; nothing else depends on it.

Run it right after discover_estate.py, before scan_repo.py: it reads only the repositories. The cross-check needs
this skill's scan, so re-run with --reconcile-only after scan_repo.py (build_summary.py and context.py remind you).

Writes:
  assessment/atf/<preset>-scanner-results-*.zip    the scanner's own output (one CSV per group)
  assessment/atf/<repo>/atf.json                    per repository:
    radnet     executable lines of code (the ATF convention: no blanks, comments or lone brackets) per project and
               in total; project structure (target frameworks, output types); assembly references (GAC, local DLL),
               NuGet references, COM and DllImport rows; and how they compare with this skill's inventory and scan
               (DLLs, packages, COM / P/Invoke findings): what each side found that the other did not
    rasql      every inline-SQL and ADO.NET execute row matched to raw_sql.py's statements and stored-procedure call
               sites by file and line (+-3 lines); RaSQL rows not matched are explained (comment, log text, LINQ,
               wrapper definition); what raw_sql.py found that RaSQL did not
  assessment/atf/<repo>/atf.md (+ .html)            the same, for people
  assessment/atf/radnet-report.html, rasql-report.html   every scanner row grouped and explained (atf_report.py)
"""
import argparse
import csv
import glob
import io
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict

from _common import OUT, load_config, load_state, mark, read_json, slug, utf8_stdout, write_json
import _findings as F
from _mdhtml import write_pair

PRESETS = {"radnet": "-RadNet", "rasql": "-RaSQL"}
EXEC_SUBTYPES = {"ExecuteReader", "ExecuteNonQuery", "ExecuteScalar", "ExecuteXmlReader", "DataAdapter", "CommandText"}
ATF = os.path.join(OUT, "atf")


def scanner_dir(cfg):
    for d in (cfg.get("atf_scanner_dir"), os.environ.get("ATF_SCANNER_DIR")):
        if d and os.path.exists(os.path.join(d, "Invoke-CodebaseScanner.ps1")):
            return os.path.abspath(d)
    return None


def repos_in_scope(root, only=None):
    st = load_state(root)
    out = []
    for r, v in sorted(st["repos"].items()):
        if v.get("scope") == "out" or (only and r != only):
            continue
        inv = F.load_inventory(root, r)
        if inv:
            out.append((r, inv["root"]))
    return out


def apps_yaml(path, group, repos):
    q = lambda s: '"' + str(s).replace("\\", "/").replace('"', '\\"') + '"'
    lines = ['version: "1.0"', "groups:", f"  - group_name: {q(group)}", '    labels: { wave: "assessment" }', "    applications:"]
    for r, p in repos:
        lines += [f"      - app_name: {q(r)}", f"        local: {q(p)}"]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def run_scanner(sdir, preset, yaml_path, dry):
    os.makedirs(ATF, exist_ok=True)
    out = os.path.abspath(ATF)
    cmd = ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "Invoke-CodebaseScanner.ps1", "-Apps", os.path.abspath(yaml_path),
           PRESETS[preset], "-Silent", "-Output", out] + (["-DryRun"] if dry else [])
    log = os.path.join(ATF, f"{preset}.log")
    t0 = time.time()
    before = set(glob.glob(os.path.join(ATF, f"{preset}-scanner-results-*.zip")))
    with open(log, "w", encoding="utf-8") as fh:
        code = subprocess.run(cmd, cwd=sdir, stdout=fh, stderr=subprocess.STDOUT).returncode
    new = sorted(set(glob.glob(os.path.join(ATF, f"{preset}-scanner-results-*.zip"))) - before, key=os.path.getmtime)
    print(f"ATF {preset}: exit {code} in {time.time() - t0:.0f}s; log {log}" + (f"; results {new[-1]}" if new else ""))
    return new[-1] if new else None


def load_rows(path):
    if path.lower().endswith(".zip"):
        rows = []
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.lower().endswith(".csv"):
                    rows += list(csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8-sig")))
        return rows
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def preset_of(path, rows):
    b = os.path.basename(path).lower()
    if b.startswith("radnet"):
        return "radnet"
    if b.startswith("rasql"):
        return "rasql"
    return "radnet" if any(r.get("rule_id") == "dotnet-loc" for r in rows[:2000]) else "rasql"


def latest(preset):
    z = sorted(glob.glob(os.path.join(ATF, f"{preset}-scanner-results-*.zip")) + glob.glob(os.path.join(ATF, f"{preset}-imported-*.csv")), key=os.path.getmtime)
    return z[-1] if z else None


def norm(p):
    return (p or "").replace("\\", "/").lower()


# ---------------------------------------------------------------- RadNet: lines of code, structure, references
def radnet_summary(rows, inv, scan, findings):
    pidx = F.project_index(inv)
    loc = Counter()
    for r in rows:
        if r.get("rule_id") == "dotnet-loc":
            p = F.project_of_file(pidx, r["relative_path"]) or "(outside a project)"
            try:
                loc[p] += int(r.get("line_count") or 0)
            except ValueError:
                pass
    kinds = Counter((r["finding_category"], r["finding_type"], r["finding_subtype"]) for r in rows)
    ref = lambda r: (re.search(r'Include="([^",]+)', r.get("snippet", "")) or re.search(r'id="([^"]+)"', r.get("snippet", "")) or [None, None])[1]
    local_dlls = sorted({ref(r) for r in rows if r.get("finding_subtype") == "LocalDll" and ref(r)}, key=str.lower)
    gac = sorted({ref(r) for r in rows if r.get("finding_subtype") == "GAC" and ref(r)}, key=str.lower)
    nuget = sorted({ref(r) for r in rows if r.get("rule_id") == "nuget-references" and ref(r)}, key=str.lower)
    com = [r for r in rows if r.get("rule_id", "").startswith("com")]
    pinv = [r for r in rows if r.get("rule_id") == "dllimport"]
    ours_dll = {b["assembly"].lower() for b in scan.get("binary_references", [])}
    ours_pkg = {p["id"].lower() for p in scan.get("packages", [])}
    ours_com = sum(f.get("occurrences") or 0 for f in findings if f["rule"].startswith(("API-COM", "LNX-API-COM", "BUILD-COM")))
    ours_pinv = sum(f.get("occurrences") or 0 for f in findings if "PINVOKE" in f["rule"] or "DLLIMPORT" in f["rule"])
    inv_loc = sum(p.get("loc_exec") or 0 for p in inv["projects"])
    return {"rows": len(rows), "by_kind": {" / ".join(k): v for k, v in kinds.most_common()},
            "loc_exec": {"total": sum(loc.values()), "by_project": dict(loc.most_common()), "ours_loc_exec": inv_loc or None,
                         "ours_loc_code": sum(p.get("loc_code") or 0 for p in inv["projects"])},
            "projects": sorted({r["relative_path"] for r in rows if r.get("rule_id") == "dotnet-project"}),
            "target_frameworks": sorted({r.get("snippet", "") for r in rows if r.get("finding_subtype") == "TargetFramework"}),
            "local_dlls": {"atf": local_dlls, "atf_only": [d for d in local_dlls if d.lower() not in ours_dll],
                           "ours_only": sorted({b["assembly"] for b in scan.get("binary_references", []) if b["assembly"].lower() not in {x.lower() for x in local_dlls}})},
            "gac_references": gac,
            "nuget": {"atf": len(nuget), "ours": len(ours_pkg), "atf_only": [n for n in nuget if n.lower() not in ours_pkg],
                      "ours_only": sorted(p["id"] for p in scan.get("packages", []) if p["id"].lower() not in {x.lower() for x in nuget})},
            "com": {"atf": len(com), "ours_occurrences": ours_com}, "dllimport": {"atf": len(pinv), "ours_occurrences": ours_pinv}}


# ---------------------------------------------------------------- RaSQL: inline SQL and execute calls vs raw_sql.py
def why_not_sql(snippet):
    s = snippet.strip()
    if s.startswith(("#region", "#endregion", "//", "/*", "*")):
        return "comment / region"
    if re.search(r"\bfrom\s+\w+\s+in\b[\s\S]*\bselect\b", s):
        return "LINQ query expression (C#, not SQL)"
    if re.search(r"(Log\w*|Exception|Write(Line)?|Trace|Debug|Info|Error)\s*\(", s) and not re.search(r"Execute|CommandText|Sql", s):
        return "log / exception message text"
    if re.search(r"public|private|protected|internal", s) and re.search(r"Execute\w*\s*\(\s*string", s):
        return "data-access wrapper definition"
    if re.search(r"CommandText\s*=\s*[a-z_]\w*\s*;|return\s+(this\.)?(dbCmd|cmd|command|_?\w*[Cc]md)\.Execute\w*\(\s*\)|return\s+this\.Execute\w*\(", s):
        return "inside the data-access wrapper (its callers are counted)"
    if re.search(r"\.Fill\s*\(\s*(data)?[Rr]eader\s*\)|\.Update\s*\(\s*\w+\.Values\s*\)", s):
        return "domain object's own Fill / Update method (not SqlDataAdapter)"
    return "not matched: review"


def rasql_reconcile(rows, sqlinv):
    ours_stmt = [(norm(c["file"]), c["line"], c.get("end_line", c["line"]), c) for c in sqlinv["statements"] + sqlinv["fragments"]]
    ours_proc = [(norm(s["file"]), s["line"], p["name"]) for p in sqlinv["procedures"] for s in p["sites"]]

    def near(f, ln, span=3):
        return [x for x in ours_stmt if x[0] == f and x[1] - span <= ln <= x[2] + span]

    inline, execs, other = [], [], Counter()
    for r in rows:
        f, ln = norm(r["relative_path"]), int(r.get("line_number") or 0)
        if r["finding_category"].lower().startswith("inline"):
            m = near(f, ln)
            inline.append({"file": r["relative_path"], "line": ln, "subtype": r["finding_subtype"], "snippet": r["snippet"][:200],
                           "matched": bool(m), "reason": None if m else why_not_sql(r["snippet"])})
        elif r["finding_subtype"] in EXEC_SUBTYPES:
            m = ([x for x in ours_proc if x[0] == f and abs(x[1] - ln) <= 3] or near(f, ln)
                 or [x for x in ours_stmt if x[0] == f and 0 <= ln - x[2] <= 15 and re.search(r"(?i)\(\s*(sql|query|cmdText|command)\w*\s*,", r["snippet"])])
            execs.append({"file": r["relative_path"], "line": ln, "subtype": r["finding_subtype"], "snippet": r["snippet"][:160],
                          "matched": bool(m), "reason": None if m else why_not_sql(r["snippet"])})
        else:
            other[f"{r['finding_type']} / {r['finding_subtype']}"] += 1
    atf_lines = {(norm(r["relative_path"]), int(r.get("line_number") or 0)) for r in rows}
    ours_only_stmt = [c for f, l, e, c in ours_stmt if not any(af == f and l - 3 <= al <= e + 3 for af, al in atf_lines)]
    ours_only_proc = [(f, l, n) for f, l, n in ours_proc if not any(af == f and abs(al - l) <= 3 for af, al in atf_lines)]
    return {"rows": len(rows),
            "inline_sql": {"atf": len(inline), "matched": sum(i["matched"] for i in inline),
                           "atf_only_by_reason": dict(Counter(i["reason"] for i in inline if not i["matched"])), "rows": inline},
            "execute_calls": {"atf": len(execs), "matched": sum(e["matched"] for e in execs),
                              "atf_only_by_reason": dict(Counter(e["reason"] for e in execs if not e["matched"])), "rows": execs},
            "atf_other_counts": dict(other.most_common()),
            "ours_only": {"statements": [{"file": c["file"], "line": c["line"], "text": c["text"][:200], "source": c.get("source", "")} for c in ours_only_stmt],
                          "procedure_call_sites": [{"file": f, "line": l, "name": n} for f, l, n in ours_only_proc]},
            "ours": {"statements": len(sqlinv["statements"]), "fragments": len(sqlinv["fragments"]), "procedure_call_sites": len(ours_proc),
                     "distinct_procedures": sqlinv["summary"]["stored_procedures"]["distinct"]}}


def render(repo, res):
    L = [f"# AWS Transform scanner cross-check: {repo}", ""]
    rn, rq = res.get("radnet"), res.get("rasql")
    if rn:
        lo = rn["loc_exec"]
        L += ["## RadNet", "",
              f"- Executable lines of code (ATF convention): **{lo['total']:,}**"
              + (f" (this skill's count, same convention: {lo['ours_loc_exec']:,})" if lo.get("ours_loc_exec") else "")
              + f"; non-blank lines in this skill's inventory: {lo['ours_loc_code']:,}.",
              "- Per project: " + "; ".join(f"{p} {n:,}" for p, n in lo["by_project"].items()) + ".",
              f"- Local DLL references: {len(rn['local_dlls']['atf'])}; found only by ATF: {', '.join(rn['local_dlls']['atf_only']) or 'none'}; "
              f"only by this skill: {', '.join(rn['local_dlls']['ours_only']) or 'none'}.",
              f"- NuGet references: ATF {rn['nuget']['atf']}, this skill {rn['nuget']['ours']}; only ATF: {', '.join(rn['nuget']['atf_only']) or 'none'}; "
              f"only this skill: {', '.join(rn['nuget']['ours_only']) or 'none'}.",
              f"- GAC references: {len(rn['gac_references'])}. COM rows: ATF {rn['com']['atf']} / this skill {rn['com']['ours_occurrences']} occurrences. "
              f"DllImport rows: ATF {rn['dllimport']['atf']} / this skill {rn['dllimport']['ours_occurrences']}.", ""]
    if rq:
        L += ["## RaSQL", "",
              f"- Rows: {rq['rows']}. Inline SQL: ATF {rq['inline_sql']['atf']}, matched {rq['inline_sql']['matched']}"
              + (f"; unmatched because {rq['inline_sql']['atf_only_by_reason']}" if rq["inline_sql"]["atf_only_by_reason"] else "") + ".",
              f"- ADO.NET execute rows: ATF {rq['execute_calls']['atf']}, matched {rq['execute_calls']['matched']}"
              + (f"; unmatched because {rq['execute_calls']['atf_only_by_reason']}" if rq["execute_calls"]["atf_only_by_reason"] else "") + ".",
              f"- Found by this skill and not by RaSQL: {len(rq['ours_only']['statements'])} statements, {len(rq['ours_only']['procedure_call_sites'])} procedure call sites.",
              f"- This skill: {rq['ours']['statements']} raw SQL statements, {rq['ours']['fragments']} fragments, {rq['ours']['procedure_call_sites']} call sites "
              f"({rq['ours']['distinct_procedures']} distinct procedures).", ""]
        miss = [e for e in rq["execute_calls"]["rows"] + rq["inline_sql"]["rows"] if not e["matched"] and e["reason"] == "not matched: review"]
        if miss:
            L += ["Rows to review (ATF found them, this skill did not):", ""] + [f"- `{m['file']}:{m['line']}` {m['subtype']}" for m in miss[:40]] + [""]
    if rn or rq:
        L += ["Readable scanner reports (every row, grouped): " + ", ".join(f"[{p} report](../{p}-report.html)" for p, x in (("radnet", rn), ("rasql", rq)) if x) + ".", ""]
    if not rn and not rq:
        L += ["The scanner has not run for this repository.", ""]
    write_pair(os.path.join(ATF, repo, "atf.md"), "\n".join(L))


def reconcile(root, repos):
    import raw_sql
    rn_rows = load_rows(latest("radnet")) if latest("radnet") else []
    rq_rows = load_rows(latest("rasql")) if latest("rasql") else []
    by_app = defaultdict(lambda: {"radnet": [], "rasql": []})
    for r in rn_rows:
        by_app[r.get("app_name", "").lower()]["radnet"].append(r)
    for r in rq_rows:
        by_app[r.get("app_name", "").lower()]["rasql"].append(r)
    for repo, path in repos:
        inv = F.load_inventory(root, repo)
        scan = read_json(os.path.join(OUT, "scan", f"{repo}.json"), {}) or {}
        findings = read_json(os.path.join(OUT, "findings", f"{repo}.json"), []) or []
        rows = by_app.get(repo.lower(), {"radnet": [], "rasql": []})
        res = {"repo": repo, "sources": {"radnet": latest("radnet"), "rasql": latest("rasql")}, "scan_done": bool(scan)}
        if rows["radnet"]:
            res["radnet"] = radnet_summary(rows["radnet"], inv, scan, findings)
        if rows["rasql"] or rq_rows:
            res["rasql"] = rasql_reconcile(rows["rasql"], raw_sql.inventory(path, repo))
        write_json(os.path.join(ATF, repo, "atf.json"), res)
        render(repo, res)
        mark(root, repo, "atf", "done" if (rows["radnet"] or rows["rasql"]) else "no-rows")
        rn, rq = res.get("radnet"), res.get("rasql")
        print(f"{repo}: " + (f"RadNet {rn['rows']} rows, {rn['loc_exec']['total']:,} executable lines; " if rn else "RadNet none; ")
              + (f"RaSQL {rq['rows']} rows, inline {rq['inline_sql']['matched']}/{rq['inline_sql']['atf']} and execute "
                 f"{rq['execute_calls']['matched']}/{rq['execute_calls']['atf']} matched" if rq else "RaSQL none")
              + ("" if scan else " (scan_repo.py not run yet: re-run with --reconcile-only after it)"))
    import atf_report
    for p in atf_report.build():
        print(f"readable report: {p}")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--presets", default="radnet,rasql")
    ap.add_argument("--repo")
    ap.add_argument("--import", dest="imports", nargs="*", default=[])
    ap.add_argument("--reconcile-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    root, cfg = load_config()
    repos = repos_in_scope(root, a.repo)
    if not repos:
        st = read_json(os.path.join(OUT, "state.json"), {"repos": {}}) or {"repos": {}}
        out = [r for r, v in st["repos"].items() if v.get("scope") == "out"]
        sys.exit(f"nothing to scan: {len(out)} repositories have no .NET project (the AWS Transform scanner reads .NET code only)" if out
                 else "no inventoried repositories: run discover_estate.py first")
    os.makedirs(ATF, exist_ok=True)
    for p in a.imports:
        rows = load_rows(p)
        pr = preset_of(p, rows)
        dst = os.path.join(ATF, (os.path.basename(p) if p.lower().endswith(".zip") else f"{pr}-imported-{time.strftime('%Y%m%d_%H%M%S')}.csv"))
        if os.path.abspath(p) != os.path.abspath(dst):
            shutil.copyfile(p, dst)
        print(f"imported {pr}: {dst} ({len(rows)} rows)")
    if not a.imports and not a.reconcile_only:
        sdir = scanner_dir(cfg)
        if not sdir:
            print("SKIP: AWS Transform codebase scanner not found. Set atf_scanner_dir in assessment.json (or ATF_SCANNER_DIR) to the folder "
                  "with Invoke-CodebaseScanner.ps1, or pass --import <results zip>. The assessment continues without it; the report says it did not run.")
            return
        if not shutil.which("pwsh"):
            print("SKIP: PowerShell 7 (pwsh) is not installed; the ATF scanner needs it (and the powershell-yaml module). Ask before installing.")
            return
        yaml_path = os.path.join(ATF, "apps.yaml")
        apps_yaml(yaml_path, slug(cfg.get("client") or "estate"), repos)
        for pr in [x.strip() for x in a.presets.split(",") if x.strip() in PRESETS]:
            run_scanner(sdir, pr, yaml_path, a.dry_run)
        if a.dry_run:
            return
    reconcile(root, repos)


if __name__ == "__main__":
    main()
