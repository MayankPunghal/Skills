"""Linux readiness check: what works on Windows today but breaks or behaves differently in a Linux container (run, do not read).

    python scripts/linux_readiness.py <repo-or-solution-folder> [--out <dir>] [--waivers waivers.json]
                                      [--level block|warn|info] [--gate] [--title NAME]
    python scripts/linux_readiness.py --all    (in an assessment workspace: every inventoried repository,
                                                output to assessment/linux/<repo>/)
    python scripts/linux_readiness.py <folder-or-Dockerfile> --dockerfile-only [--out <dir>] [--gate]
    python scripts/linux_readiness.py --explain [LNX-ID | id prefix | words]   (no scan: what a check looks for and why)

Applies scripts/data/linux_readiness.json (337 checks in 19 areas: build and packaging, file system and paths, time
zones, culture, encodings and line endings, processes and shell, environment, crypto and certificates, auth, databases,
networking, IPC, Windows-only APIs, IIS hosting, container images, configuration, logging and runtime, scheduling and
messaging, CI). Each automated check is a regex over the file types it names (code, project, config, markup, Dockerfile,
CI, scripts) or over file paths; the rest are listed as a review checklist.
Works for .NET Framework code before a port, for ported code, and for applications already on modern .NET (the
"Linux readiness only" path). The modernization-assessment and dotnet-modernization skills run this file through a thin
entry point of the same name (one copy of the scanner and its catalogue).
Writes <out>/linux-readiness.json and linux-readiness.md with its .html twin (default <out> = <folder>/.modernization).
--dockerfile-only: only the checks that read Dockerfiles and entrypoint scripts (plus "no .dockerignore"), over a folder or
one Dockerfile; writes linux-readiness-dockerfile.* instead.
--gate: exit 1 while a blocking hit is not waived. Waivers: [{"rule": "LNX-...", "path": "glob", "reason": "...", "by": "...",
"expires": "YYYY-MM-DD"}]; a waiver without a reason, or past its expiry date, is ignored (and reported).
Standard library only.
"""
import argparse
import datetime
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
            ".htm", ".css", ".gitattributes", ".dockerfile", ".asax", ".ashx", ".asmx", ".svc", ".settings", ".txt",
            ".sln", ".pem", ".crt", ".cer"}
TEXT_NAMES = {"dockerfile", "jenkinsfile", "nuget.config", ".gitattributes", ".dockerignore"}
CODE_EXT = {".cs", ".vb"}
MAX_BYTES = 2_000_000
DOCKER_FILES = {"Dockerfile*", "*.dockerfile", "entrypoint*"}  # the file globs --dockerfile-only keeps


SECRET_WORDS = r"password|passwd|pwd|secret|apikey|api_key|accesskey|access_key|token|sharedkey|accountkey|privatekey|private_key|credential"
# key=value, key: value, "key": "value" (the secret word may sit inside a longer name: DB_PASSWORD, ApiSecret, ClientSecret)
SECRET_RX = re.compile(r"(?i)(\w*(?:" + SECRET_WORDS + r")\w*[\"']?\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^;,\"'\s<>]+)")
# <add key="ApiSecret" value="..."/>: the secret word is in the key attribute, the value in the next one
SECRET_ATTR_RX = re.compile(r"(?i)(key\s*=\s*[\"'][^\"']*(?:" + SECRET_WORDS + r")[^\"']*[\"']\s+value\s*=\s*[\"'])[^\"']*")
# credentials written as literals in code: GetBytes("user:password") for a Basic header, "Basic <base64>" / "Bearer <token>",
# new NetworkCredential("user", "password"), AuthenticationHeaderValue("Basic", "<base64>"): (prefix)(value)(suffix)
CODE_CREDENTIALS = [
    re.compile(r'((?:GetBytes|ToBase64String|Encode)\s*\(\s*@?")([^":\s]{1,64}:(?!\*\*\*")[^"\s]{1,128})(")'),
    re.compile(r"""(?i)(["']\s*(?:Basic|Bearer)\s+)((?!\*\*\*)(?=[A-Za-z0-9+/=._-]*[0-9+/=])[A-Za-z0-9+/=._-]{8,})()"""),
    re.compile(r'(NetworkCredential\s*\(\s*(?:@?"[^"]*"|[\w.]+)\s*,\s*@?")((?!\*\*\*")[^"]+)(")'),
    re.compile(r'(AuthenticationHeaderValue\s*\(\s*"\w+"\s*,\s*@?")((?!\*\*\*")[^"]+)(")'),
]


def mask(text):
    """Never copy a secret value into a report: keep the key, replace the value."""
    text = SECRET_ATTR_RX.sub(lambda m: m.group(1) + "***", text)
    for rx in CODE_CREDENTIALS:
        text = rx.sub(lambda m: m.group(1) + "***" + m.group(3), text)
    return SECRET_RX.sub(lambda m: m.group(1) + (m.group(2)[0] + "***" + m.group(2)[0] if m.group(2)[:1] in "\"'" else "***"), text)


def load_rules(level="info"):
    d = json.load(open(os.path.join(HERE, "data", "linux_readiness.json"), encoding="utf-8"))
    order = {"block": 0, "warn": 1, "info": 2}
    rules = [r for r in d["rules"] if order[r["level"]] <= order[level]]
    for r in rules:
        for k in ("context", "unless_in_file", "unless_in_line"):
            if r.get(k):
                r["_" + k] = re.compile(r[k], re.M)
        for k in ("when_path", "absent_path", "only_path"):
            if r.get(k):
                r["_" + k] = re.compile(r[k], re.I)
        for p in r["patterns"]:
            # file paths compare case-insensitively, except a rule that is about letter case itself (inline (?i:...))
            ci = any(k in ("df", "yml", "ps1", "sh", "bat") for k in p.get("kinds", [])) or (p["files"] == ["@path"] and "(?i:" not in p["regex"])
            p["rx"] = re.compile(p["regex"], re.I if ci else 0)
    return d, rules


def docker_only(rules):
    """--dockerfile-only: keep the patterns that read Dockerfiles or entrypoints, the "absent" checks keyed on a
    Dockerfile, and the checklist items a person confirms in the Dockerfile (kind df)."""
    keep = []
    for r in rules:
        if r.get("check") == "absent":
            if "ockerfile" in r.get("when_path", ""):
                keep.append(r)
        elif not r["automated"]:
            if any("df" in p.get("kinds", []) for p in r["patterns"]):
                keep.append(r)
        else:
            pats = [dict(p, files=[g for g in p["files"] if g in DOCKER_FILES]) for p in r["patterns"]
                    if any(g in DOCKER_FILES for g in p["files"] or [])]
            if pats:
                keep.append(dict(r, patterns=pats))
    return keep


def valid_waivers(waivers, today=None):
    """A waiver must say why (reason) and, when it has an expiry date, still be in date. Returns (usable, ignored)."""
    today = today or datetime.date.today().isoformat()
    ok, bad = [], []
    for w in waivers:
        why = "no reason" if not str(w.get("reason", "")).strip() else "expired" if w.get("expires") and str(w["expires"]) < today else ""
        (bad if why else ok).append(dict(w, ignored=why) if why else w)
    return ok, bad


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
    return os.path.splitext(n)[1] in TEXT_EXT or n in TEXT_NAMES or n.startswith("dockerfile") or "entrypoint" in n


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


def scan(root, level="info", waivers=(), dockerfile_only=False):
    d, rules = load_rules(level)
    if dockerfile_only:
        rules = docker_only(rules)
    waivers, ignored = valid_waivers(waivers)
    single = os.path.isfile(root)  # one Dockerfile: scan it alone, look for .dockerignore beside it
    paths = [root] if single else None
    if single:
        root = os.path.dirname(os.path.abspath(root))
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
    if single:  # the build context is usually this folder or a parent: look up to the repository root (.git)
        up, rels = root, []
        for _ in range(8):
            rels += [x for x in os.listdir(up) if os.path.isfile(os.path.join(up, x))]
            if os.path.exists(os.path.join(up, ".git")) or os.path.dirname(up) == up:
                break
            up = os.path.dirname(up)
    for path in paths or walk(root):
        rel = os.path.relpath(path, root).replace("\\", "/")
        if not single:
            rels.append(rel)
        for r, p in path_rules:
            if p["rx"].search(rel):
                hits.append({"rule": r["id"], "file": rel, "line": 0, "text": rel})
        if not is_text(path) or os.path.getsize(path) > MAX_BYTES or rel.lower().endswith("properties/launchsettings.json"):
            continue  # launchSettings.json is local-debug only, never deployed
        mine = [(r, p) for r, p in text_rules if matches_file(p["files"], rel) and not (r.get("only_path") and not r["_only_path"].search(rel))]
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
    used = set()
    for h in hits:
        i, w = next(((i, w) for i, w in enumerate(waivers) if w.get("rule") in (h["rule"], "*") and fnmatch.fnmatch(h["file"], w.get("path", "*"))), (None, None))
        h["waived"] = bool(w)
        if w:
            h["waiver"] = w.get("reason", "")
            used.add(i)
    byid = {r["id"]: r for r in rules}
    open_block = [h for h in hits if byid[h["rule"]]["level"] == "block" and not h["waived"]]
    return {"root": os.path.abspath(root), "files_scanned": files, "level": level, "sources": d.get("sources", {}),
            "mode": "dockerfile" if dockerfile_only else "full",
            "waivers_ignored": ignored, "waivers_unused": [w for i, w in enumerate(waivers) if i not in used],
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
    L = [f"# Linux readiness{' (Dockerfile only)' if res.get('mode') == 'dockerfile' else ''}: {title or os.path.basename(res['root'].rstrip(os.sep))}", "",
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
    if res.get("waivers_ignored") or res.get("waivers_unused"):
        L += ["", "## Waivers to tidy", "", "| Rule | Path | Problem |", "|---|---|---|"]
        L += [f"| {w.get('rule', '')} | {w.get('path', '*')} | ignored: {w['ignored']} |" for w in res.get("waivers_ignored", [])]
        L += [f"| {w.get('rule', '')} | {w.get('path', '*')} | matches no hit (fixed? remove it) |" for w in res.get("waivers_unused", [])]
    manual = [r for r in R.values() if not r["automated"]]
    if manual:
        L += ["", "## Checklist: checks a person confirms", "", "| Check | Level | What breaks | How to check |", "|---|---|---|---|"]
        for rid, r in R.items():
            if not r["automated"]:
                L.append(f"| {rid} | {r['level']} | {r['what'].replace('|', '/')} | {r['detect'].replace('|', '/')} |")
    if res.get("sources"):
        L += ["", "## Sources", ""] + [f"- {k}: {v}" for k, v in res["sources"].items()]
    return "\n".join(L) + "\n"


def explain(query):
    """Print what a check looks for, its level, fix and sources; a prefix or words list the matching checks."""
    d, rules = load_rules("info")
    q = (query or "").strip()
    one = [r for r in rules if r["id"].lower() == q.lower()]
    found = one or [r for r in rules if r["id"].lower().startswith(q.lower())] or \
        [r for r in rules if all(re.search(r"\b" + re.escape(w), (r["id"] + " " + r["area"] + " " + r["what"] + " " + r["fix"]).lower()) for w in q.lower().split())]
    if not found:
        sys.exit(f"no check matches '{q}': try an id prefix (LNX-CTR, LNX-TZ) or a word (dockerfile, registry)")
    if len(found) > 1:
        for r in found:
            print(f"{r['id']:<34} {r['level']:<5} {'auto' if r['automated'] else 'manual':<6} {r['area']}: {r['what']}")
        print(f"\n{len(found)} checks; --explain <id> for one")
        return
    r = found[0]
    print(f"{r['id']}  [{r['level']}, {'automated' if r['automated'] else 'checklist: a person confirms'}{', ' + r['check'] if r.get('check') else ''}]")
    print(f"Area:    {r['area']}\nBreaks:  {r['what']}\nFix:     {r['fix']}\nDetect:  {r['detect']}")
    for p in r["patterns"]:
        print(f"Pattern: {p['regex']}  in {', '.join(p['files'] or ['(manual)'])}")
    for k in ("context", "unless_in_file", "unless_in_line", "only_path", "when_path", "absent_path"):
        if r.get(k):
            print(f"{k}: {r[k]}")
    for s in r["sources"]:
        print(f"Source:  {s} = {d['sources'].get(s, 'engineering knowledge, not a cited page: verify before reporting as fact')}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", help="repository or solution folder, or one Dockerfile with --dockerfile-only (omit with --all)")
    ap.add_argument("--dockerfile-only", action="store_true", help="only the Dockerfile / entrypoint checks; writes linux-readiness-dockerfile.*")
    ap.add_argument("--explain", nargs="?", const="", metavar="QUERY", help="describe a check (id), or list checks (prefix, words, nothing = all)")
    ap.add_argument("--all", action="store_true", help="assessment workspace: every repository in assessment/inventory, output to assessment/linux/<repo>/")
    ap.add_argument("--out")
    ap.add_argument("--waivers")
    ap.add_argument("--level", choices=["block", "warn", "info"], default="info")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--title")
    a = ap.parse_args()
    if a.explain is not None:
        return explain(a.explain)
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
        if not os.path.exists(a.root):
            sys.exit(f"{a.root} does not exist: give a repository folder, or a Dockerfile with --dockerfile-only")
        if os.path.isfile(a.root) and not a.dockerfile_only:
            ap.error("a single file is scanned only with --dockerfile-only; give the repository folder for the full check")
        folder = os.path.dirname(os.path.abspath(a.root)) if os.path.isfile(a.root) else a.root
        jobs = [(a.root, a.out or os.path.join(folder, ".modernization"), a.title)]
    else:
        ap.error("give a folder, or --all in an assessment workspace, or --explain <check>")
    name = "linux-readiness-dockerfile" if a.dockerfile_only else "linux-readiness"
    failed = False
    for root, out, title in jobs:
        res = scan(root, a.level, wv, a.dockerfile_only)
        os.makedirs(out, exist_ok=True)
        json.dump(res, open(os.path.join(out, name + ".json"), "w", encoding="utf-8"), indent=1)
        hp = write_pair(os.path.join(out, name + ".md"), render(res, title))
        s = res["summary"]
        failed |= not res["passed"]
        tidy = len(res["waivers_ignored"]) + len(res["waivers_unused"])
        print(f"linux readiness{' ' + title if a.all else ''}{' (Dockerfile only)' if a.dockerfile_only else ''}: {'PASS' if res['passed'] else 'FAIL'} "
              f"block {s['block_open']} open / {s['block_waived']} waived, warn {s['warn']}, info {s['info']}; {s['rules_hit']}/{s['rules_checked']} automated checks hit, "
              f"{s['checklist_items']} manual{f'; {tidy} waivers to tidy' if tidy else ''} -> {hp}")
    sys.exit(1 if a.gate and failed else 0)


if __name__ == "__main__":
    main()
