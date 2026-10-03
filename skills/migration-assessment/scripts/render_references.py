"""Render the human-readable catalogues from the data files (single source of truth: scripts/data/*.json).

    python <skill>/scripts/render_references.py

Writes references/windows-api-catalog.md (every rule by category: what it detects, why it matters on Linux / .NET 10 /
AWS, the fix and alternatives, severity, sources) and references/package-map.md. Run after editing rules.json or
package_map.json. Needs no workspace.
"""
import os
from collections import defaultdict

from _common import SKILL_DIR, data, utf8_stdout, write_text


def esc(s):
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def main():
    utf8_stdout()
    cats = {c["id"]: c for c in data("categories.json")["categories"]}
    rules = data("rules.json")["rules"]
    by = defaultdict(list)
    for r in rules:
        by[r["cat"]].append(r)
    out = ["# Windows-only and legacy API catalogue (generated)", "",
           "Generated from `scripts/data/rules.json` by `render_references.py`. Do not edit by hand: change the JSON and re-render.",
           "Every rule produces findings with `file:line` evidence. Severity is the default and the reviewer may adjust it. `baseline` means the effort is already",
           "inside the project-conversion rate. Sources are listed in [sources.md](sources.md).", "",
           "Microsoft's list of APIs that always throw on .NET (S2) is broader than these rules. The rules cover the members that occur in line-of-business code:",
           "AppDomain creation, CodeDom compilation, ProtectedData, CNG/CSP key containers, Thread.Abort/Suspend, reflection-only loading, BinaryFormatter",
           "(always throws from .NET 9), RSA/ECDsa XML import, X509 store and certificate import. Anything else surfaces through CA1416 when",
           "`validate_linux_build.py --run` builds SDK-style projects.", ""]
    # Contents list: files over 100 lines start with one (skill authoring best practice) so partial reads see the full scope
    out += ["## Contents", ""] + [f"- {cat['title']}" for cid, cat in cats.items() if by.get(cid)] + ["- Checks implemented in scanner code (not in rules.json)", ""]
    for cid, cat in cats.items():
        rs = by.get(cid)
        if not rs:
            continue
        out += [f"## {cat['title']}", "", "| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |", "| --- | --- | --- | --- | --- | --- |"]
        for r in rs:
            fix = esc(r.get("fix")) + (f" **Alt:** {esc(r['alt'])}" if r.get("alt") else "") + (" _(baseline)_" if r.get("baseline") else "")
            db = r.get("db")
            if db:
                fix += " **DB impact:** " + ", ".join(f"{k}: {v}" for k, v in db.items())
            out.append(f"| `{r['id']}` | {esc(r['title'])} | {r['sev']} / {r['conf']} | {esc(r.get('why'))} | {fix} | {', '.join(r.get('refs', []))} |")
        out.append("")
    out += ["## Checks implemented in scanner code (not in rules.json)", "",
            "| ID | Detects |", "| --- | --- |",
            "| `INV-LEGACY-PROJECT`, `INV-PACKAGES-CONFIG`, `INV-TFM-SUPPORT`, `INV-CORE-ON-FRAMEWORK`, `INV-WEBSITE-PROJECT` | Project format, package format, target-framework support status, ASP.NET Core on .NET Framework, Web Site projects |",
            "| `PKG-<status>` / `SEC-VULN-<package>` | Package map + api.nuget.org metadata (blocker, replace, windows-only, licence, private; published advisories) |",
            "| `NET-ENDPOINT-INTERNAL` / `-PUBLIC-IP` / `-EXTERNAL` | URLs, host names, IPs, connection-string servers classified on-prem vs external |",
            "| `CFG-SECRET-SETTING`, `CFG-PLAINTEXT-DB-PASSWORD`, `CFG-DEV-DATABASE` | Secret-like appSettings (names only), passwords in connection strings (never copied), developer-only databases |",
            "| `FILE-CASE-MISMATCH` | Path literals whose case differs from the file on disk |",
            "| `DB-SSIS`, `DB-SSRS`, `DB-SSAS`, `INT-CRYSTAL-FILES`, `INT-RDLC-FILES`, `BUILD-SCRIPTS` | Artefact files |",
            "| `TEST-LOW-COVERAGE`, `LOG-NO-HEALTHCHECK`, `MOD-ON-WINDOWS`, `DEV-ACTIVITY` | Test density, health endpoint, modern .NET on Windows hosting, repository activity |", ""]
    write_text(os.path.join(SKILL_DIR, "references", "windows-api-catalog.md"), "\n".join(out))
    pm = data("package_map.json")["packages"]
    out = ["# NuGet package map (generated)", "", "Generated from `scripts/data/package_map.json`. Matching is case-insensitive on the package id (regex, anchored), first match wins.",
           "With `online_package_lookup` the scanner also reads api.nuget.org: the latest version's target frameworks, deprecation (with alternative), published",
           "advisories for the versions in use, and the licence expression. Unknown packages that support .NET Standard / .NET in their latest version are marked ok.", "",
           "| Package id (regex) | Status | Severity | Note | Replacement | Known-vulnerable below |", "| --- | --- | --- | --- | --- | --- |"]
    for p in pm:
        vb = ", ".join(f"{k} < {v}" for k, v in (p.get("vulnerable_below") or {}).items())
        out.append(f"| `{esc(p['match'])}` | {p['status']} | {p['sev']} | {esc(p['note'])} | {esc(p['replacement'])} | {vb} |")
    write_text(os.path.join(SKILL_DIR, "references", "package-map.md"), "\n".join(out) + "\n")
    print(f"rendered {len(rules)} rules and {len(pm)} package entries")


if __name__ == "__main__":
    main()
