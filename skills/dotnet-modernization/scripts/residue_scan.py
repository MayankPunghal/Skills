"""Residue scan: what the port left behind that must not reach .NET 10 on Linux (run, do not read).

    python scripts/residue_scan.py <solution-or-repo-folder> [--db-target sqlserver|postgresql|dual]
                                   [--waivers waivers.json] [--out <dir>] [--gate] [--only linux]

Applies scripts/data/residue_rules.json to the ported code: .cs/.vb (code), .csproj/.vbproj (project),
.config/.json (config), file names (file), and SQL text inside string literals (sql). Rules with "when" apply only to
that database target. bin/, obj/, .git/, node_modules/, packages/ and the run folder itself are skipped.

Waivers (optional JSON list): {"rule": "WEB-FORMS-FILE", "path": "glob, e.g. legacy/**", "reason": "...", "by": "..."};
a waived hit stays in the report, marked waived, and does not fail the gate.

Writes <out>/residue.json and residue.md with its .html twin (default <out> = <folder>/.modernization).
--gate: exit 1 while any blocking hit is not waived (verify.py runs it this way).
"""
import argparse
import fnmatch
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mdhtml import write_pair  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP_DIRS = {"bin", "obj", ".git", ".vs", "node_modules", ".modernization", "TestResults", "wwwroot"}
KIND = {".cs": "code", ".vb": "code", ".csproj": "project", ".vbproj": "project", ".fsproj": "project",
        ".config": "config", ".json": "config"}
SQL_HINT = re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|EXEC(UTE)?\s|MERGE\s+INTO|FROM\s+\[?\w+)\b", re.I)
# C# regular, verbatim and interpolated literals; VB "..." literals ("" escapes)
LIT = re.compile(r'\$?@\$?"(?:[^"]|"")*"|\$?"(?:\\.|[^"\\\n])*"')


SECRET_RX = re.compile(r"(?i)\b(password|pwd|passwd|secret|apikey|api_key|accesskey|token|sharedkey|accountkey)(\w*\s*[=:]\s*[\"']?)[^;,\"'\s<>]+")


def mask(text):
    """Never copy a secret value into a report: keep the key, replace the value."""
    return SECRET_RX.sub(lambda m: m.group(1) + m.group(2) + "***", text)


def rules(db_target, only=None):
    out = []
    for r in json.load(open(os.path.join(HERE, "data", "residue_rules.json"), encoding="utf-8"))["rules"]:
        when = r.get("when", "always")
        if when != "always" and db_target not in when.split("|"):
            continue
        if only and only not in r.get("group", ["port"]):
            continue
        out.append({**r, "rx": re.compile(r["pattern"], re.I if r["where"] == "sql" else 0)})
    return out


def nuget_folder(path):
    """A "packages" folder is skipped only when it is a NuGet restore folder (.nupkg inside); source folders named
    Packages (a product area, a feature) are scanned."""
    try:
        for e in os.scandir(path):
            if e.name.lower().endswith(".nupkg"):
                return True
            if e.is_dir() and any(n.lower().endswith(".nupkg") for n in os.listdir(e.path)):
                return True
    except OSError:
        return False
    return False


def files(root):
    for d, ds, fs in os.walk(root):
        ds[:] = [x for x in ds if x not in SKIP_DIRS and not x.startswith(".")
                 and not (x.lower() == "packages" and nuget_folder(os.path.join(d, x)))]
        for f in fs:
            yield os.path.join(d, f)


def strip_comment(line, vb):
    s = line.lstrip()
    if s.startswith("//") or s.startswith("*") or s.startswith("/*") or (vb and s.startswith("'")):
        return ""
    return line


def waived(hit, waivers):
    for w in waivers:
        if w.get("rule") in (hit["rule"], "*") and fnmatch.fnmatch(hit["file"], w.get("path", "*")):
            return w
    return None


def scan(root, db_target="sqlserver", waivers=(), only=None):
    rs = rules(db_target, only)
    by_where = defaultdict(list)
    for r in rs:
        by_where[r["where"]].append(r)
    hits = []
    for p in files(root):
        rel = os.path.relpath(p, root).replace("\\", "/")
        for r in by_where["file"]:
            if r["rx"].search(rel):
                hits.append({"rule": r["id"], "level": r["level"], "file": rel, "line": 0, "text": os.path.basename(rel)})
        ext = os.path.splitext(p)[1].lower()
        kind = KIND.get(ext)
        if not kind or (kind == "config" and ext == ".json" and not os.path.basename(p).lower().startswith("appsettings")):
            continue
        try:
            text = open(p, encoding="utf-8-sig", errors="replace").read()
        except OSError:
            continue
        vb = ext == ".vb"
        for n, line in enumerate(text.splitlines(), 1):
            src = strip_comment(line, vb) if kind == "code" else line
            if not src.strip():
                continue
            for r in by_where[kind]:
                if r["rx"].search(src):
                    hits.append({"rule": r["id"], "level": r["level"], "file": rel, "line": n, "text": mask(src.strip())[:160]})
            if kind == "code" and by_where["sql"]:
                lits = [m.group(0) for m in LIT.finditer(src)]
                sqlish = [x for x in lits if SQL_HINT.search(x) or re.search(r"\bdbo\b|@@|NOLOCK|\bWHERE\b", x, re.I)]
                seen = set()
                for r in by_where["sql"]:
                    for target in ([src] if sqlish else []) if r.get("scope") == "line" else sqlish:
                        if r["id"] not in seen and r["rx"].search(target):
                            seen.add(r["id"])
                            hits.append({"rule": r["id"], "level": r["level"], "file": rel, "line": n, "text": mask(target.strip())[:160]})
    for h in hits:
        w = waived(h, waivers)
        h["waived"] = bool(w)
        if w:
            h["waiver"] = w.get("reason", "")
    meta = {r["id"]: {k: r[k] for k in ("message", "playbook", "kb", "level", "where")} for r in rs}
    open_block = [h for h in hits if h["level"] == "block" and not h["waived"]]
    return {"root": os.path.abspath(root), "db_target": db_target, "only": only, "rules": meta, "hits": hits,
            "summary": {"block_open": len(open_block), "block_waived": sum(1 for h in hits if h["level"] == "block" and h["waived"]),
                        "warn": sum(1 for h in hits if h["level"] == "warn"), "info": sum(1 for h in hits if h["level"] == "info"),
                        "by_rule": dict(Counter(h["rule"] for h in hits).most_common())},
            "passed": not open_block}


def render(res):
    s = res["summary"]
    L = ["# Residue scan", "",
         f"Folder `{res['root']}`, database target {res['db_target']}{', Linux readiness rules only' if res.get('only') == 'linux' else ''}. "
         f"**{'PASS' if res['passed'] else 'FAIL'}**: {s['block_open']} blocking open, {s['block_waived']} waived, {s['warn']} to review, {s['info']} for information.", "",
         "| Rule | Level | Hits | Files | What | Playbook | DevTx KB |", "|---|---|---|---|---|---|---|"]
    per = defaultdict(list)
    for h in res["hits"]:
        per[h["rule"]].append(h)
    order = {"block": 0, "warn": 1, "info": 2}
    for rid in sorted(per, key=lambda r: (order[res["rules"][r]["level"]], -len(per[r]))):
        m, hs = res["rules"][rid], per[rid]
        L.append(f"| {rid} | {m['level']} | {len(hs)} | {len({h['file'] for h in hs})} | {m['message']} | {m['playbook']} | {', '.join(m['kb']) or '-'} |")
    for rid in sorted(per, key=lambda r: (order[res["rules"][r]["level"]], r)):
        if res["rules"][rid]["level"] == "info":
            continue
        L += ["", f"## {rid}", "", res["rules"][rid]["message"], ""]
        for h in per[rid][:40]:
            loc = f"{h['file']}:{h['line']}" if h["line"] else h["file"]
            L.append(f"- `{loc}` {'(waived: ' + h['waiver'] + ') ' if h['waived'] else ''}`{h['text'].replace('`', chr(39))[:120]}`")
        if len(per[rid]) > 40:
            L.append(f"- ... {len(per[rid]) - 40} more in residue.json")
    if not per:
        L += ["", "Nothing found."]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root")
    ap.add_argument("--db-target", choices=["sqlserver", "postgresql", "dual"], default="sqlserver")
    ap.add_argument("--waivers")
    ap.add_argument("--out")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--only", choices=["port", "linux"], help="one rule group: linux = Linux readiness only (application already on modern .NET)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    wv = json.load(open(a.waivers, encoding="utf-8")) if a.waivers else []
    res = scan(a.root, a.db_target, wv, a.only)
    out = a.out or os.path.join(a.root, ".modernization")
    os.makedirs(out, exist_ok=True)
    json.dump(res, open(os.path.join(out, "residue.json"), "w", encoding="utf-8"), indent=1)
    hp = write_pair(os.path.join(out, "residue.md"), render(res))
    s = res["summary"]
    print(f"residue: {'PASS' if res['passed'] else 'FAIL'} block {s['block_open']} open / {s['block_waived']} waived, warn {s['warn']}, info {s['info']} -> {hp}")
    sys.exit(1 if a.gate and not res["passed"] else 0)


if __name__ == "__main__":
    main()
