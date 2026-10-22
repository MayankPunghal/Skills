"""Database scripts in repositories with no .NET project (a SQL-only repository: procedures, views, jobs, data loads).

    py -X utf8 scripts/sql_estate.py [--repo <name>]

discover_estate.py marks a repository with no .NET project out of scope, so scan_repo.py never reads its SQL. When such a
repository holds SQL scripts, run this to get the same database inventory scan_repo.py builds for .NET repositories
(_dbinventory.py: every CREATE / ALTER parsed by ScriptDom or sqlglot, construct census, PostgreSQL conversion levels,
redesign items). Scripts kept as .txt (and UTF-16) are read when they look like T-SQL; files over 2 MB (data loads) are
listed, not parsed. A raw-text census adds the server-level features that often sit inside dynamic SQL strings, which
the parser does not see (xp_cmdshell, OPENROWSET, BULK INSERT ...).
Writes assessment/sql/<repo>/db-inventory.json and db-inventory.md (+ .html); build_report.py shows the counts in
section 2.1. The estimate stays a database-team task: this script prices nothing.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import OUT, SOURCE_DIR_SKIP, load_config, load_state, read_json, read_text, utf8_stdout  # noqa: E402
import _dbinventory as DBI  # noqa: E402
import _findings as F  # noqa: E402
from _mdhtml import write_pair  # noqa: E402

# server-level features that block or complicate a move off SQL Server on Windows, counted in the raw text (strings included)
SERVER_FEATURES = {
    "xp_cmdshell": r"\bxp_cmdshell\b", "OLE automation (sp_OA*)": r"\bsp_OA(Create|Method|GetProperty|SetProperty)\b",
    "OPENROWSET": r"\bOPENROWSET\s*\(", "OPENQUERY": r"\bOPENQUERY\s*\(", "OPENDATASOURCE": r"\bOPENDATASOURCE\s*\(",
    "BULK INSERT": r"\bBULK\s+INSERT\b", "linked server (4-part name)": r"\[?\w+\]?\.\[?\w+\]?\.\[?dbo\]?\.\[?\w+\]?",
    "SQL Agent jobs": r"\bsp_add_job(step|schedule)?\b", "Database Mail": r"\bsp_send_dbmail\b", "CLR assemblies": r"\bCREATE\s+ASSEMBLY\b",
    "Service Broker": r"\b(CREATE\s+(QUEUE|SERVICE|CONTRACT)|SEND\s+ON\s+CONVERSATION)\b", "SSIS catalog": r"\bSSISDB\b|\bcatalog\.start_execution\b",
    "dynamic SQL (EXEC / sp_executesql)": r"\bsp_executesql\b|\bEXEC(UTE)?\s*\(\s*@",
}
FEATURE_RX = {k: re.compile(v, re.I) for k, v in SERVER_FEATURES.items()}


def census(root, sp, skip):
    hits, files = Counter(), Counter()
    for p in sp.sql_paths(root, skip, skipped=[]) if hasattr(sp, "sql_paths") else sp.walk(root, (".sql",), skip):
        try:
            text = read_text(p)
        except OSError:
            continue
        for k, rx in FEATURE_RX.items():
            n = len(rx.findall(text))
            if n:
                hits[k] += n
                files[k] += 1
    return {k: {"occurrences": hits[k], "files": files[k]} for k in SERVER_FEATURES if hits[k]}


def run(repo, inv):
    root = inv["root"]
    skip = sorted(SOURCE_DIR_SKIP | {s.lower() for s in (inv.get("scope") or {}).get("skip_dirs") or []})
    sp = DBI.sql_parser()
    if not sp:
        print(f"{repo}: no SQL parser (codebase-documenter missing): run its install_prerequisites.py")
        return None
    res = DBI.inventory(root, skip)
    if not res["objects"] and not res.get("skipped_sql_files") and not res.get("parse_errors"):
        print(f"{repo}: no SQL scripts found (.sql, or T-SQL kept as .txt and similar)")
        return None
    res["server_features"] = census(root, sp, skip)
    out = os.path.join(OUT, "sql", repo)
    os.makedirs(out, exist_ok=True)
    json.dump(res, open(os.path.join(out, "db-inventory.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    lv = (res.get("conversion") or {}).get("database") or {}
    L = [f"# Database scripts: {repo}", "",
         f"{len(res['objects'])} objects parsed ({res.get('engine')}), {res.get('sql_lines', 0):,} lines; "
         f"{len(res.get('parse_errors', []))} parse errors; {len(res.get('skipped_sql_files', []))} files skipped by size.", "",
         "## Objects", "", "| Kind | Count |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted((res.get("kinds") or {}).items(), key=lambda x: -x[1])]
    L += ["", "## PostgreSQL conversion (construct occurrences)", "", "| Level | Occurrences |", "|---|---|"] + [f"| {k} | {v} |" for k, v in lv.items()]
    if res.get("redesign_items"):
        L += ["", "## No PostgreSQL equivalent (redesign)", "", "| Construct | Object | Where | Approach |", "|---|---|---|---|"]
        for x in res["redesign_items"][:60]:
            L.append(f"| {x['construct']} | {x['object']} | `{x['file']}:{x['line']}` | {x['pg']} |")
    if res["server_features"]:
        L += ["", "## Server-level features (raw text, dynamic SQL strings included)", "", "| Feature | Occurrences | Files |", "|---|---|---|"]
        L += [f"| {k} | {v['occurrences']} | {v['files']} |" for k, v in res["server_features"].items()]
    if res.get("skipped_sql_files"):
        L += ["", f"## Not parsed ({len(res['skipped_sql_files'])} files over the size limit)", ""]
        L += [f"- `{x['file']}` ({x['reason']})" for x in res["skipped_sql_files"][:40]]
    write_pair(os.path.join(out, "db-inventory.md"), "\n".join(L) + "\n")
    print(f"{repo}: {len(res['objects'])} objects, conversion {lv}, {len(res.get('redesign_items', []))} redesign items, "
          f"{len(res.get('skipped_sql_files', []))} skipped -> {out}/db-inventory.md")
    return res


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    st = load_state(root)
    repos = [a.repo] if a.repo else sorted(r for r, v in st["repos"].items() if v.get("scope") == "out")
    done = 0
    for r in repos:
        inv = F.load_inventory(root, r)
        if not inv:
            print(f"{r}: no inventory: run discover_estate.py first")
            continue
        done += bool(run(r, inv))
    if not repos:
        print("no repository without a .NET project: scan_repo.py already inventories SQL in .NET repositories")
    return done


if __name__ == "__main__":
    main()
