"""Linux readiness check: what works on Windows today but breaks or behaves differently in a Linux container (run, do not read).

    python scripts/linux_readiness.py <repo-or-solution-folder> [--out <dir>] [--waivers waivers.json]
                                      [--level block|warn|info] [--gate] [--title NAME]
    python scripts/linux_readiness.py --all    (in an assessment workspace: every inventoried repository,
                                                output to assessment/linux/<repo>/)

Applies scripts/data/linux_readiness.json (240 checks in 19 areas: build and packaging, file system and paths, time
zones, culture, encodings and line endings, processes and shell, environment, crypto and certificates, auth, databases,
networking, IPC, Windows-only APIs, IIS hosting, container images, configuration, logging and runtime, scheduling and
messaging, CI). Each automated check is a regex over the file types it names (code, project, config, markup, Dockerfile,
CI, scripts) or over file paths; the rest are listed as a review checklist.
Works for .NET Framework code before a port, for ported code, and for applications already on modern .NET (the
"Linux readiness only" path). Same file in the migration-assessment and dotnet-modernization skills.
Writes <out>/linux-readiness.json and linux-readiness.md with its .html twin (default <out> = <folder>/.modernization).
--gate: exit 1 while a blocking hit is not waived. Waivers: [{"rule": "LNX-...", "path": "glob", "reason": "...", "by": "..."}].
Standard library only.
"""
import argparse
import fnmatch
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _mdhtml import write_pair  # noqa: E402

SKIP_DIRS = {"bin", "obj", ".git", ".vs", "node_modules", ".modernization", "TestResults", "assessment"}
TEXT_EXT = {".cs", ".vb", ".csproj", ".vbproj", ".fsproj", ".props", ".targets", ".config", ".json", ".cshtml", ".razor", ".aspx",
            ".ascx", ".master", ".sql", ".yml", ".yaml", ".pubxml", ".ps1", ".sh", ".bat", ".cmd", ".js", ".xml", ".resx", ".html",
            ".htm", ".css", ".gitattributes", ".dockerfile", ".asax", ".ashx", ".asmx", ".svc", ".settings", ".txt"}
TEXT_NAMES = {"dockerfile", "jenkinsfile", "nuget.config", ".gitattributes", ".dockerignore"}
CODE_EXT = {".cs", ".vb"}
MAX_BYTES = 2_000_000


SECRET_RX = re.compile(r"(?i)\b(password|pwd|passwd|secret|apikey|api_key|accesskey|token|sharedkey|accountkey)(\w*\s*[=:]\s*[\"']?)[^;,\"'\s<>]+")


def mask(text):
    """Never copy a secret value into a report: keep the key, replace the value."""
    return SECRET_RX.sub(lambda m: m.group(1) + m.group(2) + "***", text)


def load_rules(level="info"):
    d = json.load(open(os.path.join(HERE, "data", "linux_readiness.json"), encoding="utf-8"))
    order = {"block": 0, "warn": 1, "info": 2}
    rules = [r for r in d["rules"] if order[r["level"]] <= order[level]]
    for r in rules:
        for k in ("context", "unless_in_file", "unless_in_line"):
            if r.get(k):
                r["_" + k] = re.compile(r[k], re.M)
        for k in ("when_path", "absent_path"):
            if r.get(k):
                r["_" + k] = re.compile(r[k], re.I)
        for p in r["patterns"]:
            # file paths compare case-insensitively, except a rule that is about letter case itself (inline (?i:...))
            ci = any(k in ("df", "yml", "ps1", "sh", "bat") for k in p.get("kinds", [])) or (p["files"] == ["@path"] and "(?i:" not in p["regex"])
            p["rx"] = re.compile(p["regex"], re.I if ci else 0)
    return d, rules


def matches_file(globs, rel):
    name = os.path.basename(rel)
    low = name.lower()
    for g in globs or []:
        if g == "*":
            return True
        if g.startswith("."):
            if low.endswith(g.lower()):
                return True
        elif fnmatch.fnmatch(low, g.lower()):
            return True
    return False


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


def walk(root):
    for d, ds, fs in os.walk(root):
        ds[:] = [x for x in ds if x not in SKIP_DIRS and not (x.startswith(".") and x not in (".github",))
              and not (x.lower() == "packages" and nuget_folder(os.path.join(d, x)))]
        for f in fs:
            yield os.path.join(d, f)


def is_text(path):
    n = os.path.basename(path).lower()
    return os.path.splitext(n)[1] in TEXT_EXT or n in TEXT_NAMES or n.startswith("dockerfile")


def comment(line, ext):
    s = line.lstrip()
    if ext in CODE_EXT:
        return s.startswith("//") or s.startswith("/*") or s.startswith("*") or (ext == ".vb" and s.startswith("'"))
    return False


def case_mismatch(root, path, ref, index):
    """True when ref names a file that exists only with different letter case (works on Windows, not on Linux)."""
    ref = ref.replace("\\", "/").lstrip("~").lstrip("/")
    if not ref or ref.startswith(("http:", "https:")) or "{" in ref or "@" in ref:
        return False
    base = os.path.dirname(path)
    for cand in (os.path.normpath(os.path.join(base, ref)), os.path.normpath(os.path.join(root, ref))):
        rel = os.path.relpath(cand, root).replace("\\", "/")
        if rel.startswith(".."):
            continue
        actual = index.get(rel.lower())
        if actual is not None:
            return rel not in actual
    name = os.path.basename(ref)
    same = index.get("#" + name.lower())  # referenced by file name only (resolved at run time from a configured folder)
    return bool(same) and name not in same


def build_index(root):
    idx = defaultdict(set)
    for p in walk(root):
        rel = os.path.relpath(p, root).replace("\\", "/")
        idx[rel.lower()].add(rel)
        idx["#" + os.path.basename(rel).lower()].add(os.path.basename(rel))
    return idx


def scan(root, level="info", waivers=()):
    d, rules = load_rules(level)
    index = build_index(root)
    gac = [r for r in rules if r.get("check") == "reference_without_hintpath"]
    path_rules = [(r, p) for r in rules if r["automated"] and not r.get("check") for p in r["patterns"] if p["files"] == ["@path"]]
    whole_file = ("file_lacks", "crlf", "last_from_sdk")  # judged on the whole file, not line by line
    absent = [r for r in rules if r["automated"] and r.get("check") == "absent"]
    text_rules = [(r, p) for r in rules if r["automated"] and r.get("check") not in whole_file + ("absent", "reference_without_hintpath")
                  for p in r["patterns"] if p["files"] and p["files"] != ["@path"]]
    file_rules = [(r, p) for r in rules if r["automated"] and r.get("check") in whole_file for p in r["patterns"] if p["files"]]
    hits = []
    rels = []
    files = 0
    for path in walk(root):
        rel = os.path.relpath(path, root).replace("\\", "/")
        rels.append(rel)
        for r, p in path_rules:
            if p["rx"].search(rel):
                hits.append({"rule": r["id"], "file": rel, "line": 0, "text": rel})
        if not is_text(path) or os.path.getsize(path) > MAX_BYTES or rel.lower().endswith("properties/launchsettings.json"):
            continue  # launchSettings.json is local-debug only, never deployed
        mine = [(r, p) for r, p in text_rules if matches_file(p["files"], rel)]
        whole = [(r, p) for r, p in file_rules if matches_file(p["files"], rel)]
        if not mine and not whole and not (gac and rel.lower().endswith(("proj"))):
            continue
        files += 1
        try:
            raw = open(path, encoding="utf-8-sig", errors="replace", newline="").read()
        except OSError:
            continue
        lines = raw.splitlines()
        mine = [(r, p) for r, p in mine if not (r.get("unless_in_file") and r["_unless_in_file"].search(raw))]
        for r, p in whole:
            if r.get("unless_in_file") and r["_unless_in_file"].search(raw):
                continue
            if r["check"] == "crlf":
                if "\r\n" in raw:
                    hits.append({"rule": r["id"], "file": rel, "line": raw[:raw.index("\r\n")].count("\n") + 1, "text": "CRLF line endings"})
            elif r["check"] == "file_lacks":
                if not any(p["rx"].search(x) for x in lines):
                    hits.append({"rule": r["id"], "file": rel, "line": 0, "text": f"no line matches {p['regex']}"})
            elif r["check"] == "last_from_sdk":
                froms = [(n, x) for n, x in enumerate(lines, 1) if p["rx"].search(x)]
                if froms and re.search(r"dotnet/(core/)?sdk\b", froms[-1][1], re.I):
                    hits.append({"rule": r["id"], "file": rel, "line": froms[-1][0], "text": mask(froms[-1][1].strip())[:160]})
        ext = os.path.splitext(rel)[1].lower()
        for n, line in enumerate(lines, 1):
            if not line.strip() or comment(line, ext):
                continue
            seen = set()
            for r, p in mine:
                if r["id"] in seen:
                    continue
                m = p["rx"].search(line)
                if not m:
                    continue
                if r.get("unless_in_line") and r["_unless_in_line"].search(line):
                    continue
                if r.get("context") and not r["_context"].search("\n".join(lines[max(0, n - 16):n + 15])):
                    continue
                if r.get("check") == "case_exact" and not case_mismatch(root, path, m.group(1) if m.groups() else m.group(0), index):
                    continue
                seen.add(r["id"])
                hits.append({"rule": r["id"], "file": rel, "line": n, "text": mask(line.strip())[:160]})
        if ext in (".csproj", ".vbproj"):
            for r in gac:
                for m in re.finditer(r"<Reference\s+Include=\"([^\"]+)\"\s*(/>|>(.*?)</Reference>)", "\n".join(lines), re.S):
                    if "<HintPath>" not in (m.group(3) or "") and not re.match(r"(System|Microsoft|mscorlib|WindowsBase|PresentationCore)\b", m.group(1)):
                        n = "\n".join(lines)[:m.start()].count("\n") + 1
                        hits.append({"rule": r["id"], "file": rel, "line": n, "text": mask(m.group(0).splitlines()[0])[:160]})
    for r in absent:  # e.g. a Dockerfile with no .dockerignore anywhere in the repository
        when = [x for x in rels if r["_when_path"].search(x)]
        if when and not any(r["_absent_path"].search(x) for x in rels):
            hits.append({"rule": r["id"], "file": when[0], "line": 0, "text": f"{len(when)} file(s) like {when[0]}; nothing matches {r['absent_path']}"})
    for h in hits:
        w = next((w for w in waivers if w.get("rule") in (h["rule"], "*") and fnmatch.fnmatch(h["file"], w.get("path", "*"))), None)
        h["waived"] = bool(w)
        if w:
            h["waiver"] = w.get("reason", "")
    byid = {r["id"]: r for r in rules}
    open_block = [h for h in hits if byid[h["rule"]]["level"] == "block" and not h["waived"]]
    return {"root": os.path.abspath(root), "files_scanned": files, "level": level, "sources": d.get("sources", {}),
            "rules": {r["id"]: {k: r[k] for k in ("area", "level", "what", "fix", "sources", "automated", "detect")} for r in rules},
            "hits": hits, "passed": not open_block,
            "summary": {"block_open": len(open_block), "block_waived": sum(1 for h in hits if byid[h["rule"]]["level"] == "block" and h["waived"]),
                        "warn": sum(1 for h in hits if byid[h["rule"]]["level"] == "warn"), "info": sum(1 for h in hits if byid[h["rule"]]["level"] == "info"),
                        "rules_hit": len({h["rule"] for h in hits}), "rules_checked": sum(1 for r in rules if r["automated"]),
                        "checklist_items": sum(1 for r in rules if not r["automated"])}}


def render(res, title=None):
    s = res["summary"]
    R = res["rules"]
    per = defaultdict(list)
    for h in res["hits"]:
        per[h["rule"]].append(h)
    L = [f"# Linux readiness: {title or os.path.basename(res['root'].rstrip(os.sep))}", "",
         f"**{'PASS' if res['passed'] else 'FAIL'}**: {s['block_open']} blocking hits open ({s['block_waived']} waived), {s['warn']} to review, "
         f"{s['info']} for information. {s['rules_hit']} of {s['rules_checked']} automated checks hit, over {res['files_scanned']} files; "
         f"{s['checklist_items']} checks need a person (list at the end).", "",
         "Block = fails the build, startup or a common path on Linux. Warn = behaves differently or fails on some paths. Info = verify.", "",
         "## Summary by area", "", "| Area | Block | Warn | Info | Checks hit |", "|---|---|---|---|---|"]
    areas = defaultdict(Counter)
    for rid, hs in per.items():
        areas[R[rid]["area"]][R[rid]["level"]] += len(hs)
        areas[R[rid]["area"]]["rules"] += 1
    for a, c in sorted(areas.items(), key=lambda x: (-x[1]["block"], -x[1]["warn"])):
        L.append(f"| {a} | {c['block']} | {c['warn']} | {c['info']} | {c['rules']} |")
    order = {"block": 0, "warn": 1, "info": 2}
    L += ["", "## Checks that hit", "", "| Check | Level | Hits | Files | What breaks | Fix |", "|---|---|---|---|---|---|"]
    ids = sorted(per, key=lambda r: (order[R[r]["level"]], -len(per[r])))
    for rid in ids:
        L.append(f"| {rid} | {R[rid]['level']} | {len(per[rid])} | {len({h['file'] for h in per[rid]})} | {R[rid]['what'].replace('|', '/')} | {R[rid]['fix'].replace('|', '/')} |")
    for rid in ids:
        if R[rid]["level"] == "info":
            continue
        L += ["", f"### {rid}", "", f"{R[rid]['what']} **Fix:** {R[rid]['fix']} (sources: {', '.join(R[rid]['sources']) or '-'})", ""]
        for h in per[rid][:25]:
            loc = f"{h['file']}:{h['line']}" if h["line"] else h["file"]
            L.append(f"- `{loc}` {'(waived: ' + h['waiver'] + ') ' if h['waived'] else ''}`{h['text'].replace('`', chr(39))[:110]}`")
        if len(per[rid]) > 25:
            L.append(f"- ... {len(per[rid]) - 25} more in linux-readiness.json")
    manual = [r for r in R.values() if not r["automated"]]
    if manual:
        L += ["", "## Checklist: checks a person confirms", "", "| Check | Level | What breaks | How to check |", "|---|---|---|---|"]
        for rid, r in R.items():
            if not r["automated"]:
                L.append(f"| {rid} | {r['level']} | {r['what'].replace('|', '/')} | {r['detect'].replace('|', '/')} |")
    if res.get("sources"):
        L += ["", "## Sources", ""] + [f"- {k}: {v}" for k, v in res["sources"].items()]
    return "\n".join(L) + "\n"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", help="repository or solution folder (omit with --all)")
    ap.add_argument("--all", action="store_true", help="assessment workspace: every repository in assessment/inventory, output to assessment/linux/<repo>/")
    ap.add_argument("--out")
    ap.add_argument("--waivers")
    ap.add_argument("--level", choices=["block", "warn", "info"], default="info")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--title")
    a = ap.parse_args()
    wv = json.load(open(a.waivers, encoding="utf-8")) if a.waivers else []
    if a.all:
        jobs = []
        for f in sorted(os.listdir(os.path.join("assessment", "inventory"))):
            inv = json.load(open(os.path.join("assessment", "inventory", f), encoding="utf-8")) if f.endswith(".json") else {}
            if inv.get("repo") and inv.get("root"):
                jobs.append((inv["root"], os.path.join("assessment", "linux", inv["repo"]), inv["repo"]))
        if not jobs:
            sys.exit("no repositories in assessment/inventory: run discover_estate.py first, or pass a folder")
    elif a.root:
        jobs = [(a.root, a.out or os.path.join(a.root, ".modernization"), a.title)]
    else:
        ap.error("give a folder, or --all in an assessment workspace")
    failed = False
    for root, out, title in jobs:
        res = scan(root, a.level, wv)
        os.makedirs(out, exist_ok=True)
        json.dump(res, open(os.path.join(out, "linux-readiness.json"), "w", encoding="utf-8"), indent=1)
        hp = write_pair(os.path.join(out, "linux-readiness.md"), render(res, title))
        s = res["summary"]
        failed |= not res["passed"]
        print(f"linux readiness{' ' + title if a.all else ''}: {'PASS' if res['passed'] else 'FAIL'} block {s['block_open']} open / {s['block_waived']} waived, "
              f"warn {s['warn']}, info {s['info']}; {s['rules_hit']}/{s['rules_checked']} checks hit, {s['checklist_items']} manual -> {hp}")
    sys.exit(1 if a.gate and failed else 0)


if __name__ == "__main__":
    main()
