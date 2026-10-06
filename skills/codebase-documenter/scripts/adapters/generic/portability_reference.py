"""Windows-to-Linux portability checks (.NET), reusing the migration-assessment skill's rule file.

Writes docs/reference/platform-portability.md (anchors port-…) and docs/agent/portability.json:
  summary     occurrences by category and severity, per project
  rules       every rule that matched: severity, why it breaks on Linux / modern .NET, the suggested fix
  sites       per rule, every file:line (with the enclosing method when the method map knows it)
  packages    the Windows-only packages found by generic-deps (docs/agent/dependencies.json)
Only the portability categories run (default: linux-readiness, web-platform, wcf-desktop, hosting, api-portability,
file-handling, time-culture; option "categories"), not the rest of the assessment. System.Web / Web Forms, WCF / WPF /
WinForms and IIS-bound hosting are the largest Windows-only items in most legacy apps, so a page that left them out would
read as "nothing Windows-only here" for exactly the apps that have the most. Findings are flags and suggestions, never enforced.
Rule file lookup: env DOCS_ASSESSMENT_RULES, option "rules", the sibling skill folder
(<skills>/migration-assessment/scripts/data/rules.json), then ~/.claude/skills/…; skipped when none is found.
Matching follows the assessment scanner: a rule applies to its file types; "requires" must match somewhere in the
file, "not" excludes a line; comment lines and block comments are ignored.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

from _scan import BACK, DOCS, Methods, esc, options, project_of, read, slug, walk, write_page

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from code_text import code_match  # noqa: E402  (same string-literal rule as migration-assessment's scan)
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

OPT = options("generic-portability")
CATEGORIES = OPT.get("categories", ["linux-readiness", "web-platform", "wcf-desktop", "hosting", "api-portability",
                                    "file-handling", "time-culture"])
CAT_LABEL = {"linux-readiness": "Windows-only API", "web-platform": "ASP.NET on System.Web (Web Forms, MVC 5, Web API 2)",
             "wcf-desktop": "WCF / ASMX services, WPF, Windows Forms", "hosting": "IIS-bound hosting and Windows containers",
             "api-portability": "API removed from modern .NET", "file-handling": "Paths and files",
             "time-culture": "Time zones and culture"}
MAX_SITES = OPT.get("max_sites_per_rule", 300)
MAX_BYTES = 2_500_000
# same file types as the assessment scanner (scan_repo.py TYPE_BY_EXT)
TYPE_BY_EXT = {".cs": "cs", ".vb": "vb", ".aspx": "markup", ".ascx": "markup", ".master": "markup", ".asax": "markup", ".ashx": "markup",
               ".asmx": "markup", ".svc": "markup", ".cshtml": "markup", ".vbhtml": "markup", ".razor": "markup", ".config": "config",
               ".sql": "sql", ".csproj": "proj", ".vbproj": "proj", ".fsproj": "proj", ".targets": "proj", ".props": "proj",
               ".ps1": "script", ".psm1": "script", ".bat": "script", ".cmd": "script", ".vbs": "script", ".reg": "script",
               ".js": "js", ".xslt": "xml", ".xsl": "xml", ".pubxml": "xml"}
COMMENT_LINE = {"cs": re.compile(r"^\s*(//|/\*|\*)"), "vb": re.compile(r"^\s*('|REM\s)", re.I), "sql": re.compile(r"^\s*--"),
                "script": re.compile(r"^\s*(#|REM\s|::)", re.I), "js": re.compile(r"^\s*(//|/\*|\*)")}
BLOCK_COMMENT = {"cs": re.compile(r"/\*.*?\*/", re.S), "js": re.compile(r"/\*.*?\*/", re.S), "sql": re.compile(r"/\*.*?\*/", re.S),
                 "config": re.compile(r"<!--.*?-->", re.S), "proj": re.compile(r"<!--.*?-->", re.S),
                 "markup": re.compile(r"<%--.*?--%>|<!--.*?-->|@\*.*?\*@", re.S), "xml": re.compile(r"<!--.*?-->", re.S)}
# a secret-like name given a literal value ("Password=…;", apiKey = "…", <add key="Token" value="…">): the snippet is hidden.
# A bare word (RegistryKey key = Registry.LocalMachine…, GetToken()) is ordinary evidence and stays visible.
SECRETISH = re.compile(r"(?i)\b\w*(password|passwd|pwd|secret|token|api_?key|accountkey|sharedaccesskey|credential)\w*\s*[=:]\s*[\"'@]"
                       r"|(password|pwd)\s*=\s*[^;\"'\s]+;|key\s*=\s*\"[^\"]*(pass|pwd|secret|token|key|credential)[^\"]*\"\s+value\s*=")
SEV_ORDER = {"Blocker": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
# the usual skip list, but designer files stay in: WinForms designers name Windows fonts and System.Drawing types
SKIP = re.compile(r"(^|/)(\.git|\.vs|\.idea|bin|obj|node_modules|dist|build|out|target|vendor|packages|\.venv|venv|__pycache__|"
                  r"wwwroot/lib|coverage)(/|$)|\.min\.js$", re.I)
M = Methods()


def rules_path():
    here = os.path.dirname(os.path.abspath(__file__))
    skills = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here))))  # <skills>/codebase-documenter/scripts/adapters/generic
    for p in (os.environ.get("DOCS_ASSESSMENT_RULES"), OPT.get("rules"),
              os.path.join(skills, "migration-assessment", "scripts", "data", "rules.json"),
              os.path.join(os.path.expanduser("~"), ".claude", "skills", "migration-assessment", "scripts", "data", "rules.json")):
        if p and os.path.isfile(p):
            return p
    return None


def file_type(name):
    low = name.lower()
    if re.search(r"(?i)^(?!launchsettings)[\w.-]*(settings|secrets)[\w.-]*\.json$", low):
        return "config"
    return TYPE_BY_EXT.get(os.path.splitext(low)[1])


def load_rules(path):
    rules = []
    for r in json.load(open(path, encoding="utf-8"))["rules"]:
        if r.get("cat") not in CATEGORIES:
            continue
        r = dict(r)
        r["_any"] = re.compile("|".join(f"(?i:{p[4:]})" if p.startswith("(?i)") else f"(?:{p})" for p in r["pat"]), re.M)
        r["_req"] = re.compile(r["requires"], re.M) if r.get("requires") else None
        r["_not"] = re.compile(r["not"]) if r.get("not") else None
        r["_types"] = set(r["types"])
        rules.append(r)
    return rules


def blank_comments(text, ftype):
    rx = BLOCK_COMMENT.get(ftype)
    return rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text) if rx else text


def snippet(line):
    s = line.strip()
    return "(line holds a secret-like setting; open the file)" if SECRETISH.search(s) else (s[:140] + "…" if len(s) > 140 else s)


def main():
    path = rules_path()
    if not path:
        print("platform-portability: skipped (migration-assessment rules.json not found; set DOCS_ASSESSMENT_RULES or "
              "adapter_options.generic-portability.rules)")
        return
    rules = load_rules(path)
    hits = defaultdict(list)          # rule id -> [site]
    files_by_type = Counter()
    for rp, ap in walk(exts=set(TYPE_BY_EXT), names=re.compile(r"(?i)^appsettings[\w.-]*\.json$"), skip=SKIP):
        ftype = file_type(os.path.basename(rp))
        if not ftype or ftype == "js" and re.search(r"(?i)\.min\.js$", rp):
            continue
        try:
            if os.path.getsize(ap) > MAX_BYTES:
                continue
        except OSError:
            continue
        text = blank_comments(read(ap), ftype)
        files_by_type[ftype] += 1
        lines = None
        cl = COMMENT_LINE.get(ftype)
        for r in rules:
            if ftype not in r["_types"] and "any" not in r["_types"]:
                continue
            if not r["_any"].search(text) or (r["_req"] and not r["_req"].search(text)):
                continue
            lines = lines if lines is not None else text.splitlines()
            for i, line in enumerate(lines, 1):
                if cl and cl.match(line):
                    continue
                if r["_any"].search(line) and not (r["_not"] and r["_not"].search(line)):
                    if ftype in ("cs", "vb") and not r.get("in_strings") and not code_match(r["_any"], line, ftype == "vb"):
                        continue  # only inside a string literal (a message or a test title): not a use of the API
                    hits[r["id"]].append({"file": rp, "line": i, "project": project_of(rp), "text": snippet(line),
                                          "method": M.enclosing(rp, i)})
    by_id = {r["id"]: r for r in rules}
    matched = sorted(hits, key=lambda k: (SEV_ORDER.get(by_id[k]["sev"], 9), by_id[k]["cat"], k))
    deps = os.path.join(DOCS, "agent", "dependencies.json")
    win_pkgs = []
    if os.path.exists(deps):
        info = json.load(open(deps, encoding="utf-8")).get("package_info", {})
        win_pkgs = sorted((n, v) for n, vs in info.items() for v, i in vs.items() if i and i.get("windows_only"))

    total = sum(len(v) for v in hits.values())
    sev = Counter()
    for k in matched:
        sev[by_id[k]["sev"]] += len(hits[k])
    out = ["# Platform portability (Windows to Linux)", "",
           "Code that works on Windows / .NET Framework but breaks, or behaves differently, on Linux or modern .NET: "
           "Windows-only APIs, System.Web / Web Forms, WCF and desktop UI, IIS-bound hosting, APIs removed from .NET, Windows "
           "paths and files, Windows time-zone IDs and culture assumptions. Each row is a flag with a suggested fix, not a verdict: check the code before changing it (a branch "
           "on `OperatingSystem.IsWindows()` or a Windows-only deployment may make a site harmless).", "",
           f"Checks: {len(rules)} rules in {len(CATEGORIES)} categories, taken from the migration-assessment rule set "
           f"(`rules.json`, portability categories only). Comment lines and commented-out blocks are ignored.", "",
           '<a id="index"></a>', "",
           "- [Summary](#port-summary)", "- [Rules that matched](#port-rules)", "- [By project](#port-projects)",
           "- [Windows-only packages](#port-packages)", "- [Occurrences per rule](#port-sites)", "",
           '<a id="port-summary"></a>', "", "## Summary", "", BACK, "",
           f"{total} occurrences of {len(matched)} rules in {len({s['file'] for v in hits.values() for s in v})} files "
           f"(files checked: {sum(files_by_type.values())}; " + ", ".join(f"{t} {n}" for t, n in files_by_type.most_common()) + ").", "",
           "| Severity | Occurrences |", "| --- | --- |"]
    out += [f"| {s} | {sev[s]} |" for s in sorted(sev, key=lambda s: SEV_ORDER.get(s, 9))]
    out += ["", "| Category | What it covers | Rules matched | Occurrences |", "| --- | --- | --- | --- |"]
    for c in CATEGORIES:
        ks = [k for k in matched if by_id[k]["cat"] == c]
        out.append(f"| {esc(c)} | {CAT_LABEL.get(c, '')} | {len(ks)} of {sum(1 for r in rules if r['cat'] == c)} | {sum(len(hits[k]) for k in ks)} |")

    out += ["", '<a id="port-rules"></a>', "", "## Rules that matched", "", BACK, "",
            "| Severity | Rule | Category | Occurrences | Files | Why it breaks | Suggested fix |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for k in matched:
        r = by_id[k]
        out.append(f"| {r['sev']} | [{esc(r['title'])}](#{slug('port', k)}) (`{k}`) | {esc(r['cat'])} | {len(hits[k])} | "
                   f"{len({s['file'] for s in hits[k]})} | {esc(r.get('why', ''))} | {esc(r.get('fix', ''))} |")
    if not matched:
        out.append("| — | No portability rule matched | | | | | |")

    proj = defaultdict(Counter)
    for k in matched:
        for s in hits[k]:
            proj[s["project"]][by_id[k]["sev"]] += 1
    out += ["", '<a id="port-projects"></a>', "", "## By project", "", BACK, "",
            "| Project | Blocker | High | Medium | Low | Info | Rules |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for p in sorted(proj, key=lambda p: (-sum(proj[p].values()), p)):
        ks = sorted({k for k in matched for s in hits[k] if s["project"] == p})
        out.append(f"| `{esc(p)}` | " + " | ".join(str(proj[p][s] or "") for s in ("Blocker", "High", "Medium", "Low", "Info"))
                   + " | " + ", ".join(f"[{k}](#{slug('port', k)})" for k in ks) + " |")

    out += ["", '<a id="port-packages"></a>', "", "## Windows-only packages", "", BACK, ""]
    if not os.path.exists(deps):
        out.append("Not checked: add the `generic-deps` adapter (it reads licence and platform from the restored NuGet packages).")
    elif not win_pkgs:
        out.append("None found among the packages restored on this machine (packages not in the local NuGet cache are not checked; "
                   "see [dependencies](dependencies.md)).")
    else:
        out += ["Package versions that ship native binaries only for Windows or build only for `net*-windows` "
                "(details in [dependencies](dependencies.md)).", "", "| Package | Version |", "| --- | --- |"]
        out += [f"| [{esc(n)}](dependencies.md#{slug('pkg', n)}) | {esc(v)} |" for n, v in win_pkgs]

    out += ["", '<a id="port-sites"></a>', "", "## Occurrences per rule", "", BACK]
    for k in matched:
        r = by_id[k]
        out += ["", f'<a id="{slug("port", k)}"></a>', "", f"### {esc(r['title'])} (`{k}`)", "", BACK, "",
                f"- **Severity:** {r['sev']} ({r.get('conf', '')})", f"- **Why:** {r.get('why', '')}", f"- **Suggested fix:** {r.get('fix', '')}"]
        if r.get("alt"):
            out.append(f"- **Replacement:** {r['alt']}")
        out += ["", "| Where | Method | Code |", "| --- | --- | --- |"]
        for s in hits[k][:MAX_SITES]:
            out.append(f"| `{esc(s['file'])}:{s['line']}` | {M.link(s['method']) or '—'} | `{esc(s['text'])}` |")
        if len(hits[k]) > MAX_SITES:
            out.append(f"| +{len(hits[k]) - MAX_SITES} more (full list in `agent/portability.json`) | | |")
    write_page("platform-portability.md", out)

    agent = os.path.join(DOCS, "agent")
    os.makedirs(agent, exist_ok=True)
    data = {"categories": CATEGORIES, "rules_checked": len(rules), "files_checked": dict(files_by_type),
            "rules": [{"id": k, "title": by_id[k]["title"], "category": by_id[k]["cat"], "severity": by_id[k]["sev"],
                       "confidence": by_id[k].get("conf"), "why": by_id[k].get("why", ""), "fix": by_id[k].get("fix", ""),
                       "alt": by_id[k].get("alt", ""), "anchor": slug("port", k), "sites": hits[k]} for k in matched],
            "windows_only_packages": [{"name": n, "version": v} for n, v in win_pkgs]}
    open(os.path.join(agent, "portability.json"), "w", encoding="utf-8", newline="\n").write(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    stat("portability", occurrences=total, rules_matched=len(matched), rules=len(rules))
    print(f"platform-portability: {total} occurrences of {len(matched)}/{len(rules)} rules "
          f"({', '.join(f'{s} {n}' for s, n in sorted(sev.items(), key=lambda x: SEV_ORDER.get(x[0], 9)))}), "
          f"{len(win_pkgs)} Windows-only package versions")


if __name__ == "__main__":
    main()
