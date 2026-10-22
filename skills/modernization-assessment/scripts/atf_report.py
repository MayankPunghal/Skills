"""Readable HTML reports from the AWS Transform codebase scanner CSVs: one page for RadNet, one for RaSQL.

    py -X utf8 atf_report.py [--radnet <results .zip|.csv>] [--rasql <results .zip|.csv>]

atf_scan.py runs this after every scan, import or reconcile; run it alone to rebuild the pages. Without arguments it
uses the latest results in assessment/atf/. The scanner's CSV is one row per finding with a raw code snippet, which is
hard to read; these pages group the rows into what a reader needs (projects, packages, DLLs, framework assemblies;
database code per file, inline SQL, execute calls, parameters), say what each group means for a .NET 10 / Linux /
PostgreSQL move, and join the cross-check with this skill's own scan (assessment/atf/<repo>/atf.json) when it exists.

Writes (self-contained, no network, light and dark, every table filterable and sortable):
  assessment/atf/radnet-report.html
  assessment/atf/rasql-report.html

Snippets are masked with _common.mask (secret values never appear). Standard library only.
"""
import argparse
import datetime
import html
import json
import os
import re
from collections import Counter, defaultdict

from _common import OUT, load_config, mask, read_json, utf8_stdout
from atf_scan import ATF, latest, load_rows

# Framework (GAC) assemblies that do not exist, or work only on Windows, on .NET 10
GAC_NOTES = {
    "System.Web": "Not on .NET 10: ASP.NET (System.Web) is replaced by ASP.NET Core",
    "System.Web.Extensions": "Not on .NET 10 (ASP.NET AJAX, JavaScriptSerializer): use System.Text.Json / ASP.NET Core",
    "System.Web.Services": "Not on .NET 10 (ASMX): regenerate clients with dotnet-svcutil, host services as ASP.NET Core / CoreWCF",
    "System.Web.Mvc": "ASP.NET MVC 5: becomes ASP.NET Core MVC",
    "System.Web.Http": "ASP.NET Web API 2: becomes ASP.NET Core controllers",
    "System.Web.DynamicData": "Not on .NET 10",
    "System.Web.Entity": "Not on .NET 10",
    "System.Web.ApplicationServices": "Not on .NET 10",
    "System.Web.Abstractions": "Not on .NET 10",
    "System.Web.Routing": "Not on .NET 10: ASP.NET Core routing",
    "System.EnterpriseServices": "Not on .NET 10 (COM+ / distributed transactions): use TransactionScope or remove",
    "System.Runtime.Remoting": "Not on .NET 10: use gRPC, HTTP or named pipes",
    "System.ServiceModel": "WCF client: System.ServiceModel.* packages; WCF hosting: CoreWCF",
    "System.ServiceModel.Web": "Not on .NET 10 (WCF REST): ASP.NET Core controllers",
    "System.Messaging": "Not on .NET 10 (MSMQ): Amazon SQS",
    "System.Data.Linq": "Not on .NET 10 (LINQ to SQL): EF Core or Dapper",
    "System.Management": "Windows only (WMI)",
    "System.DirectoryServices": "Windows only (Active Directory): LDAP library or AWS Directory Service",
    "System.Drawing": "Windows only on .NET 6+: SkiaSharp or ImageSharp",
    "System.Windows.Forms": "Windows only",
    "PresentationFramework": "Windows only (WPF)",
    "System.Configuration": "Package System.Configuration.ConfigurationManager; move settings to appsettings.json",
    "System.Configuration.Install": "Not on .NET 10 (installers)",
    "System.ServiceProcess": "Windows services: package System.ServiceProcess.ServiceController, or a Worker Service",
    "Microsoft.VisualBasic": "Mostly available; check the members used",
    "System.Data.OracleClient": "Not on .NET 10: Oracle.ManagedDataAccess.Core",
    "System.Transactions": "Available; distributed (MSDTC) transactions are not on Linux",
}
# Visual Studio project type GUIDs (ProjectTypeGuids)
PROJECT_TYPES = {
    "349c5851-65df-11da-9384-00065b846f21": "ASP.NET Web Application", "e24c65dc-7377-472b-9aba-bc803b73c61a": "ASP.NET Web Site",
    "603c0e0b-db56-11dc-be95-000d561079b0": "ASP.NET MVC 1", "f85e285d-a4e0-4152-9332-ab1d724d3325": "ASP.NET MVC 2",
    "e53f8fea-eae0-44a6-8774-ffd645390401": "ASP.NET MVC 3", "e3e379df-f4c6-4180-9b81-6769533abe47": "ASP.NET MVC 4",
    "349c5853-65df-11da-9384-00065b846f21": "ASP.NET MVC 5", "3d9ad99f-2412-4246-b90b-4eaa41c64699": "WCF service",
    "60dc8134-eba5-43b8-bcc9-bb4bc16c2548": "WPF", "3ac096d0-a1c2-e12c-1390-a8335801fdab": "Test",
    "786c830f-07a1-408b-bd7f-6ee04809d6db": "Portable library", "a1591282-1198-4647-a2b1-27e5ff5f6f3b": "Silverlight",
    "fae04ec0-301f-11d3-bf4b-00c04f79efbc": "C#", "f184b08f-c81c-45f6-a57f-5abd9991f28f": "VB.NET", "9a19103f-16f7-4668-be54-9a1e7a4f7556": "C# (SDK-style)",
}


def project_type(s):
    g = re.findall(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", s or "")
    return " + ".join(PROJECT_TYPES.get(x.lower(), x) for x in g) if g else (s or "")


def framework(s):
    m = re.fullmatch(r"v(\d+(?:\.\d+)*)", (s or "").strip())
    return f".NET Framework {m.group(1)}" if m else (s or "")


SQL_EXEC = ("ExecuteReader", "ExecuteNonQuery", "ExecuteScalar", "ExecuteXmlReader", "DataAdapter", "Fill", "CommandText")

CSS = """:root{--bg:#fbfaf8;--fg:#1d1d1f;--mut:#6b6b70;--line:#e3e1dc;--card:#fff;--acc:#2f5d8a;--bad:#a8322d;--warn:#9a6a00;--ok:#2d7a46;--code:#f3f1ec}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#17181a;--fg:#e8e6e1;--mut:#9a9893;--line:#2e2f33;--card:#1f2023;--acc:#8fb4dd;--bad:#e2847d;--warn:#d9b45c;--ok:#7cc495;--code:#26272b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 80px}h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:38px 0 6px;padding-top:8px;border-top:1px solid var(--line)}
.sub{color:var(--mut);margin:0 0 18px}.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}.card b{display:block;font-size:22px}.card span{color:var(--mut);font-size:13px}
nav{display:flex;flex-wrap:wrap;gap:6px 14px;margin:10px 0 0;font-size:14px}nav a{color:var(--acc);text-decoration:none}
ul.means{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px 12px 34px;margin:12px 0}ul.means li{margin:4px 0}
.intro{color:var(--mut);margin:0 0 8px;max-width:900px}.tools{display:flex;gap:10px;align-items:center;margin:6px 0}
.tools input{flex:0 1 320px;padding:6px 9px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}.tools small{color:var(--mut)}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}table{border-collapse:collapse;width:100%;font-size:13.5px}
th{position:sticky;top:0;background:var(--card);text-align:left;font-weight:600;cursor:pointer;white-space:nowrap;border-bottom:1px solid var(--line);padding:7px 9px}
td{border-top:1px solid var(--line);padding:6px 9px;vertical-align:top}td.n{text-align:right;font-variant-numeric:tabular-nums}
code{font:12.5px ui-monospace,Consolas,monospace;background:var(--code);padding:1px 4px;border-radius:4px;white-space:pre-wrap;word-break:break-word}
.bad{color:var(--bad);font-weight:600}.warn{color:var(--warn);font-weight:600}.ok{color:var(--ok)}.none{color:var(--mut);font-style:italic}
footer{margin-top:40px;color:var(--mut);font-size:13px}@media print{.tools{display:none}th{position:static}}"""

JS = """document.querySelectorAll('[data-filter]').forEach(function(inp){var t=document.getElementById(inp.dataset.filter),c=inp.nextElementSibling;
inp.addEventListener('input',function(){var q=inp.value.toLowerCase(),n=0;t.querySelectorAll('tbody tr').forEach(function(r){var s=r.textContent.toLowerCase().indexOf(q)>-1;r.style.display=s?'':'none';n+=s});c.textContent=n+' shown'})});
document.querySelectorAll('th').forEach(function(th){th.addEventListener('click',function(){var tb=th.closest('table').tBodies[0],i=[].indexOf.call(th.parentNode.children,th),d=th.dataset.d==='1'?-1:1;th.dataset.d=d===1?'1':'0';
[].slice.call(tb.rows).sort(function(a,b){var x=a.cells[i].dataset.v||a.cells[i].textContent,y=b.cells[i].dataset.v||b.cells[i].textContent,nx=parseFloat(x),ny=parseFloat(y);
return(!isNaN(nx)&&!isNaN(ny)?nx-ny:x.localeCompare(y))*d}).forEach(function(r){tb.appendChild(r)})})});"""


def esc(x):
    return html.escape(str(x if x is not None else ""))


def snip(s, n=240):
    return re.sub(r"\s+", " ", mask(s or ""))[:n]


def norm(p):
    return (p or "").replace("\\", "/")


def attr(s, name):
    m = re.search(name + r'\s*=\s*"([^"]*)"', s or "", re.I)
    return m.group(1) if m else ""


class Page:
    def __init__(self, title, sub):
        self.title, self.sub, self.cards, self.means, self.secs, self.n = title, sub, [], [], [], 0

    def card(self, value, label):
        self.cards.append(f'<div class="card"><b>{esc(f"{value:,}" if isinstance(value, int) else value)}</b><span>{esc(label)}</span></div>')

    def table(self, sid, title, intro, cols, rows, code_cols=(), cls=None, empty="None found."):
        self.n += 1
        tid = f"t{self.n}"
        if not rows:
            self.secs.append((sid, title, f'<h2 id="{sid}">{esc(title)}</h2><p class="intro">{intro}</p><p class="none">{esc(empty)}</p>'))
            return
        num = [all(isinstance(r[i], (int, float)) or r[i] in ("", None) for r in rows) for i in range(len(cols))]
        body = []
        for r in rows:
            tds = []
            for i, v in enumerate(r):
                c = (cls(i, v, r) if cls else "") or ""
                if num[i]:
                    tds.append(f'<td class="n {c}" data-v="{esc(v)}">{esc(f"{v:,}" if isinstance(v, int) else v)}</td>')
                elif i in code_cols and v:
                    tds.append(f'<td class="{c}"><code>{esc(v)}</code></td>')
                else:
                    tds.append(f'<td class="{c}">{esc(v)}</td>')
            body.append("<tr>" + "".join(tds) + "</tr>")
        tools = (f'<div class="tools"><input placeholder="Filter these {len(rows)} rows" data-filter="{tid}"><small>{len(rows)} shown</small></div>'
                 if len(rows) > 8 else "")
        self.secs.append((sid, title, f'<h2 id="{sid}">{esc(title)}</h2><p class="intro">{intro}</p>{tools}<div class="wrap"><table id="{tid}"><thead><tr>'
                          + "".join(f"<th>{esc(c)}</th>" for c in cols) + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"))

    def write(self, path, source):
        nav = "".join(f'<a href="#{sid}">{esc(t)}</a>' for sid, t, _ in self.secs)
        doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
               f"<title>{esc(self.title)}</title><style>{CSS}</style></head><body><main><h1>{esc(self.title)}</h1><p class=\"sub\">{self.sub}</p>"
               f'<div class="cards">{"".join(self.cards)}</div>'
               + (f'<h2 id="means">What this means</h2><ul class="means">{"".join(f"<li>{m}</li>" for m in self.means)}</ul>' if self.means else "")
               + f"<nav>{nav}</nav>" + "".join(h for _, _, h in self.secs)
               + f"<footer>Source: {esc(os.path.basename(source))} (AWS Transform codebase scanner). Generated {datetime.datetime.now():%Y-%m-%d %H:%M} by "
               f"atf_report.py. Code snippets are masked; secret values never appear.</footer></main><script>{JS}</script></body></html>")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(doc)
        return path


def cross_checks():
    out = {}
    if os.path.isdir(ATF):
        for d in os.listdir(ATF):
            j = read_json(os.path.join(ATF, d, "atf.json"))
            if isinstance(j, dict) and j.get("repo"):
                out[j["repo"].lower()] = j
    return out


def facts_dlls():
    m = {}
    eff = os.path.join(OUT, "effort")
    if os.path.isdir(eff):
        for r in os.listdir(eff):
            for b in (read_json(os.path.join(eff, r, "facts.json"), {}) or {}).get("binary_references", []):
                m[(r.lower(), b.get("assembly", "").lower())] = b
    return m


def radnet(path, out):
    rows = load_rows(path)
    apps = sorted({r["app_name"] for r in rows}, key=str.lower)
    proj = defaultdict(lambda: {"app": "", "attrs": {}, "refs": 0})
    loc_file, nuget, local, gac, com, dll, edmx = [], {}, [], defaultdict(set), [], [], defaultdict(Counter)
    sln = set()
    for r in rows:
        a, t, st, p, s = r["app_name"], r["finding_type"], r["finding_subtype"], norm(r["relative_path"]), r.get("snippet") or ""
        if t == "Lines of Code":
            loc_file.append((a, p, (r.get("file_extension") or os.path.splitext(p)[1]).lower().lstrip("."), int(r.get("line_count") or 0)))
        elif t == "Solution":
            sln.add((a, p))
        elif t == "Project":
            proj[(a, p)]["app"] = a
            if st == "ProjectReference":
                proj[(a, p)]["refs"] += 1
            else:
                proj[(a, p)]["attrs"][st] = re.sub(r"<[^>]+>", "", s).strip()
        elif t == "NuGet Reference":
            pid = attr(s, r"\bid") or attr(s, "Include")
            if pid:
                d = nuget.setdefault(pid.lower(), {"id": pid, "versions": set(), "apps": set(), "projects": set(), "refs": 0})
                if attr(s, "version") or attr(s, "Version"):
                    d["versions"].add(attr(s, "version") or attr(s, "Version"))
                d["apps"].add(a)
                d["projects"].add(p)
                d["refs"] += 1
        elif t == "Assembly Reference":
            name = attr(s, "Include").split(",")[0].strip()
            if st == "LocalDll":
                hp = re.search(r"<HintPath>([^<]*)</HintPath>", s)
                local.append((a, p, name, norm(hp.group(1)) if hp else ""))
            elif name:
                gac[name].add((a, p))
        elif t == "DllImport":
            m = re.search(r'DllImport\(\s*"([^"]+)"', s)
            fn = re.search(r"extern\s+[\w<>\[\],.?]+\s+(\w+)", s)
            dll.append((a, f"{p}:{r.get('line_number') or ''}", m.group(1) if m else "", fn.group(1) if fn else "", snip(s, 160)))
        elif t.startswith("COM"):
            com.append((a, t, st, f"{p}:{r.get('line_number') or ''}", snip(s, 160)))
        elif t == "EDMX":
            edmx[(a, p)][st] += 1

    pdirs = sorted(((a, p, os.path.dirname(p)) for a, p in proj), key=lambda x: -len(x[2]))

    def owner(a, f):
        return next((p for pa, p, d in pdirs if pa == a and (not d or f.startswith(d + "/"))), "(outside a project)")

    loc_proj, loc_ext = Counter(), Counter()
    for a, f, e, n in loc_file:
        loc_proj[(a, owner(a, f))] += n
        loc_ext[e or "(none)"] += n
    total = sum(n for *_, n in loc_file)
    xc, fdl = cross_checks(), facts_dlls()

    pg = Page("AWS Transform RadNet scan", f"Code inventory from the AWS Transform codebase scanner (RadNet preset): {len(apps)} application"
              f"{'s' if len(apps) != 1 else ''} ({esc(', '.join(apps))}), {len(rows):,} scanner rows, grouped for reading.")
    for v, l in ((len(apps), "applications"), (len(sln), "solutions"), (len(proj), "projects"), (total, "executable lines (ATF count)"),
                 (len(nuget), "NuGet packages"), (len(local), "local DLL references"), (len(gac), "framework (GAC) assemblies"),
                 (len(com), "COM rows"), (len(dll), "DllImport rows"), (len(edmx), "EDMX models")):
        pg.card(v, l)

    fws = Counter(framework(x["attrs"].get("TargetFramework", "?")) for x in proj.values())
    blocked = sorted(n for n in gac if n in GAC_NOTES and GAC_NOTES[n].startswith(("Not on", "Windows only")))
    pg.means.append(f"<b>{len(proj)} project{'s' if len(proj) != 1 else ''}</b> on " + ", ".join(f"{esc(k)} ({v})" for k, v in fws.items())
                    + ": every one is ported to .NET 10 (SDK-style project, PackageReference).")
    pg.means.append(f"<b>{total:,} executable lines</b> (ATF convention: no blank lines, comments or lone braces). AWS Transform prices by this count.")
    if local:
        names = sorted({x[2] for x in local}, key=str.lower)
        pg.means.append(f"<b>{len(names)} DLLs are referenced by file path</b> ({esc(', '.join(names))}). Each needs a NuGet package that runs on .NET 10, "
                        "the source code to rebuild it, or a replacement; see the Local DLLs table.")
    if blocked:
        pg.means.append(f"<b>{len(blocked)} framework assemblies do not exist or are Windows-only on .NET 10</b>: " + ", ".join(f"<code>{esc(b)}</code>" for b in blocked)
                        + ". The code that uses them is rewritten during the port.")
    pg.means.append(("<b>No COM or P/Invoke</b>: nothing native ties the code to Windows." if not com and not dll else
                     f"<b>{len(com)} COM and {len(dll)} DllImport rows</b>: native Windows code; each needs a managed replacement for Linux."))
    pg.means.append("<b>No Entity Framework EDMX models</b>." if not edmx else f"<b>{len(edmx)} EDMX models</b>: move to EF Core (code-first or reverse-engineered).")

    prow = []
    for (a, p), x in sorted(proj.items(), key=lambda k: (k[0][0].lower(), k[0][1])):
        at = x["attrs"]
        prow.append([a, p, project_type(at.get("ProjectType", "")), framework(at.get("TargetFramework", "")), at.get("OutputType", ""), at.get("AssemblyName", ""), x["refs"], loc_proj.get((a, p), 0)])
    pg.table("projects", "Projects", "One row per project file. Project type is what the scanner read from the ProjectTypeGuids (Web Forms, MVC, library ...).",
             ["Application", "Project", "Project type", "Target framework", "Output", "Assembly", "Project refs", "Executable lines"], prow)
    pg.table("loc", "Executable lines by file type", "Where the code is. UI markup (aspx, ascx, master, cshtml) is rewritten when the UI changes framework.",
             ["File type", "Executable lines", "Share %"], [[e, n, round(100 * n / total, 1) if total else 0] for e, n in loc_ext.most_common()])
    pg.table("largest", "Largest files", "The 30 biggest files by executable lines: the ones to review first.",
             ["Application", "File", "Project", "Executable lines"], [[a, f, owner(a, f), n] for a, f, e, n in sorted(loc_file, key=lambda x: -x[3])[:30]])

    pk = {}
    pkcsv = os.path.join(OUT, "report", "packages.csv")
    if os.path.exists(pkcsv):
        import csv
        with open(pkcsv, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                pk[r["package"].lower()] = r
    nrows = []
    for k, d in sorted(nuget.items()):
        m = pk.get(k, {})
        nrows.append([d["id"], ", ".join(sorted(d["versions"])) or "-", len(d["projects"]), ", ".join(sorted(d["apps"], key=str.lower)),
                      m.get("status", ""), m.get("recommendation", ""), m.get("recommendation_why", "") or m.get("note", "")])
    pg.table("nuget", "NuGet packages", "From packages.config / PackageReference. The last three columns come from this skill's package check (report/packages.csv) "
             "when it has run: whether the package works on .NET 10 and what to do with it.",
             ["Package", "Versions", "Projects", "Applications", ".NET 10 status", "Action", "Why"], nrows,
             cls=lambda i, v, r: ("bad" if v in ("blocked", "replace", "incompatible") else "ok" if v in ("ok", "keep") else "") if i in (4, 5) else "")
    lrows = []
    for a, p, name, hp in sorted(local, key=lambda x: (x[0].lower(), x[2].lower())):
        b = fdl.get((a.lower(), name.lower()), {})
        lrows.append([a, p, name, hp, b.get("built_for", ""), b.get("runs_on_linux", ""), b.get("source", ""), b.get("action", "")])
    pg.table("dlls", "Local DLLs (referenced by file path)", "Binaries checked into or copied next to the code. Each must be replaced by a .NET 10-compatible NuGet "
             "package, rebuilt from source, or rewritten. The last four columns come from this skill's DLL check (effort/&lt;repo&gt;/facts.json) when it has run.",
             ["Application", "Project", "Assembly", "Path", "Built for", "Runs on Linux", "Source code", "Action"], lrows,
             cls=lambda i, v, r: ("bad" if i == 5 and str(v).startswith("no") else "ok" if i == 5 and str(v).startswith("yes") else ""))
    grows = [[n, len(v), ", ".join(sorted({x[0] for x in v}, key=str.lower)), GAC_NOTES.get(n, "Available on .NET 10 (in the runtime or as a package)")]
             for n, v in sorted(gac.items(), key=lambda k: k[0].lower())]
    pg.table("gac", "Framework (GAC) assemblies", "References to .NET Framework assemblies. Most exist on .NET 10; the ones marked are missing or Windows-only.",
             ["Assembly", "Projects", "Applications", "On .NET 10"], grows,
             cls=lambda i, v, r: ("bad" if i == 3 and str(v).startswith(("Not on", "Windows only")) else ""))
    pg.table("com", "COM", "COM components and interop: Windows-only.", ["Application", "Type", "Subtype", "File:line", "Code"], com, code_cols=(4,))
    pg.table("dllimport", "P/Invoke (DllImport)", "Calls into native DLLs: Windows-only unless a Linux library exists.",
             ["Application", "File:line", "Library", "Function", "Code"], dll, code_cols=(4,))
    pg.table("edmx", "Entity Framework EDMX models", "Database-first EF6 models: EF Core does not read EDMX.",
             ["Application", "File", "Entities", "Providers"], [[a, p, c.get("Entity", 0), c.get("Provider", 0)] for (a, p), c in sorted(edmx.items())])

    xrows = []
    for a in apps:
        rn = (xc.get(a.lower()) or {}).get("radnet")
        if rn:
            lo = rn["loc_exec"]
            def diff(x, y):
                if not isinstance(y, int):
                    return "not counted by this skill"
                return "same" if x == y else f"{y - x:+,} ({100 * (y - x) / x:+.1f}%)" if x else f"{y - x:+,}"
            xrows += [[a, "Executable lines", lo["total"], lo.get("ours_loc_exec", ""), diff(lo["total"], lo.get("ours_loc_exec"))],
                      [a, "Local DLLs", len(rn["local_dlls"]["atf"]), len(rn["local_dlls"]["atf"]) - len(rn["local_dlls"]["atf_only"]) + len(rn["local_dlls"]["ours_only"]),
                       "; ".join(filter(None, [f"only ATF: {', '.join(rn['local_dlls']['atf_only'])}" if rn["local_dlls"]["atf_only"] else "",
                                               f"only this skill: {', '.join(rn['local_dlls']['ours_only'])}" if rn["local_dlls"]["ours_only"] else ""])) or "same"],
                      [a, "NuGet references", rn["nuget"]["atf"], rn["nuget"]["ours"],
                       "; ".join(filter(None, [f"only ATF: {', '.join(rn['nuget']['atf_only'])}" if rn["nuget"]["atf_only"] else "",
                                               f"only this skill: {', '.join(rn['nuget']['ours_only'])}" if rn["nuget"]["ours_only"] else ""])) or "same"],
                      [a, "COM occurrences", rn["com"]["atf"], rn["com"]["ours_occurrences"], diff(rn["com"]["atf"], rn["com"]["ours_occurrences"])],
                      [a, "DllImport occurrences", rn["dllimport"]["atf"], rn["dllimport"]["ours_occurrences"], diff(rn["dllimport"]["atf"], rn["dllimport"]["ours_occurrences"])]]
    pg.table("crosscheck", "Cross-check with this skill's scan", "The same facts counted by both tools. Differences are listed; none means the two agree.",
             ["Application", "Fact", "AWS Transform", "This skill", "Differences"], xrows, empty="Not cross-checked yet: run atf_scan.py --reconcile-only after scan_repo.py.")
    return pg.write(out, path)


def rasql(path, out):
    rows = load_rows(path)
    apps = sorted({r["app_name"] for r in rows}, key=str.lower)
    xc = cross_checks()
    status = {}
    for a in apps:
        rq = (xc.get(a.lower()) or {}).get("rasql") or {}
        for e in (rq.get("inline_sql") or {}).get("rows", []) + (rq.get("execute_calls") or {}).get("rows", []):
            status[(norm(e["file"]).lower(), int(e["line"]))] = "matched" if e["matched"] else e.get("reason") or "not matched"
    per_file = defaultdict(Counter)
    inline, execs, params, other = [], [], defaultdict(list), []
    for r in rows:
        a, t, st, f, ln = r["app_name"], r["finding_type"], r["finding_subtype"], norm(r["relative_path"]), int(r.get("line_number") or 0)
        s = r.get("snippet") or ""
        key = "Inline SQL" if t.lower().startswith("inline") else st
        per_file[(a, f)][key] += 1
        chk = status.get((f.lower(), ln), "")
        if t.lower().startswith("inline"):
            inline.append([a, f"{f}:{ln}", st, snip(s, 400), chk])
        elif st == "Parameter":
            nm = re.search(r'"(@?\w+)"', s) or re.search(r"(@\w+)", s)
            params[(a, f)].append(nm.group(1) if nm else "?")
        elif st in SQL_EXEC:
            execs.append([a, f"{f}:{ln}", st, snip(s, 240), chk])
        else:
            other.append([a, t, st, f"{f}:{ln}", snip(s, 240)])
    sub = Counter((r["finding_type"], r["finding_subtype"]) for r in rows)
    n_exec = sum(1 for e in execs if e[2] != "CommandText")
    dist = [o for o in other if "Distributed" in o[1]]
    real = lambda chk: not chk or chk == "matched" or chk.startswith("not matched")   # not a comment, log text, LINQ or the wrapper itself
    real_inline = [i for i in inline if real(i[4])]
    real_exec = [e for e in execs if e[2] != "CommandText" and real(e[4])]
    procs = defaultdict(list)
    for a, loc, kind, s, chk in execs:
        m = re.search(r'(?:Execute\w*|SqlCommand|SqlDataAdapter)\s*\(\s*"([\w.\[\]]+)"\s*,\s*(?:System\.Data\.)?CommandType\.StoredProcedure', s) \
            or re.search(r'(?:Execute\w*|SqlCommand)\s*\(\s*"([\w.\[\]]+)"', s)
        if m and not re.search(r"\s", m.group(1)):
            procs[(a, m.group(1))].append(loc)

    pg = Page("AWS Transform RaSQL scan", f"Database access found by the AWS Transform codebase scanner (RaSQL preset): {len(apps)} application"
              f"{'s' if len(apps) != 1 else ''} ({esc(', '.join(apps))}), {len(rows):,} scanner rows, grouped for reading.")
    for v, l in ((len(per_file), "files with database code"), (len({p for _, p in procs}), "stored procedures called"),
                 (len(real_inline), f"inline SQL statements ({len(inline)} rows)"), (len(real_exec), f"execute / adapter call sites ({n_exec} rows)"),
                 (sum(len(v) for v in params.values()), "command parameters"), (sub.get(("ADO.NET", "DataAdapter"), 0), "DataAdapter rows"),
                 (len(dist), "distributed transactions"), (len(rows), "scanner rows")):
        pg.card(v, l)
    kinds = sorted({k for c in per_file.values() for k in c})
    orm = any(re.search(r"(?i)entity|dbcontext|linq|dapper|nhibernate", f"{r['finding_type']} {r['finding_subtype']}") for r in rows)
    pg.means.append(("<b>Data access is plain ADO.NET</b> (connections, commands, readers, adapters); the scanner found no ORM. "
                     "Moving to PostgreSQL means swapping SqlClient for Npgsql in the data layer and porting the stored procedures the code calls."
                     if not orm else "<b>An ORM is in use</b>: see the rows below; its provider changes for PostgreSQL."))
    pg.means.append(f"<b>{len(real_inline)} inline SQL statement{'s' if len(real_inline) != 1 else ''}</b> in C# strings"
                    + (f" ({len(inline) - len(real_inline)} more rows are not SQL: comments, log text or C# LINQ)" if len(inline) > len(real_inline) else "")
                    + ": each is checked for T-SQL that PostgreSQL does not accept (TOP, square brackets, GETDATE(), ISNULL, + for strings, three-part "
                    "db.dbo.table names).")
    pg.means.append(f"<b>{len({p for _, p in procs})} stored procedures</b> are called by name: most of the SQL lives in them, so the PostgreSQL port is "
                    "mainly a procedure port (DB team / DB porting agent), with the C# side changing provider and parameter types.")
    pg.means.append(f"<b>{len(real_exec)} execute or adapter call sites</b> in {len(per_file)} files"
                    + (f" ({n_exec - len(real_exec)} more rows are the data-access wrapper itself or a domain object's own Fill method)" if n_exec > len(real_exec) else "")
                    + ": where results are read; reader column types and output parameters are checked after the provider change.")
    if dist:
        pg.means.append(f"<b>{len(dist)} distributed transaction</b> (System.EnterpriseServices / COM+): not available on .NET 10 or Linux. "
                        "Replace with a local TransactionScope or remove it.")
    pg.means.append("The cross-check column says whether this skill's own SQL scan (raw_sql.py) found the same row, or why the row is not SQL "
                    "(a comment, log text, the data-access wrapper itself).")

    frows = [[a, f] + [c.get(k, 0) for k in kinds] + [sum(c.values())] for (a, f), c in sorted(per_file.items(), key=lambda x: -sum(x[1].values()))]
    pg.table("files", "Database code by file", "Every file with database access and what kind. The data-access layer is usually a handful of files; that is where the "
             "provider change happens.", ["Application", "File"] + kinds + ["Total"], frows)
    pg.table("procs", "Stored procedures called", "Procedure names read from the execute calls (the first string argument with CommandType.StoredProcedure). "
             "Each one is ported to PostgreSQL (function or procedure) and its call sites retested.",
             ["Application", "Procedure", "Call sites", "Where"], [[a, p, len(v), ", ".join(v)] for (a, p), v in sorted(procs.items(), key=lambda k: k[0][1].lower())])
    ok = lambda i, v, r: ("ok" if v == "matched" else "warn" if v and v.startswith("not matched") else "") if i == 4 else ""
    pg.table("inline", "Inline SQL", "SQL written in C# strings. Review each for SQL Server-only syntax.",
             ["Application", "File:line", "Statement", "Code", "Cross-check"], inline, code_cols=(3,), cls=ok)
    pg.table("execute", "Execute calls and adapters", "ExecuteReader / ExecuteNonQuery / ExecuteXmlReader / DataAdapter / CommandText rows. ExecuteXmlReader "
             "(SQL Server FOR XML) has no Npgsql equivalent and is rewritten.",
             ["Application", "File:line", "Kind", "Code", "Cross-check"], execs, code_cols=(3,),
             cls=lambda i, v, r: ("bad" if i == 2 and v == "ExecuteXmlReader" else ok(i, v, r)))
    prow = [[a, f, len(v), ", ".join(sorted(set(v), key=str.lower))[:600]] for (a, f), v in sorted(params.items(), key=lambda x: -len(x[1]))]
    pg.table("params", "Command parameters by file", "Parameters added to commands, grouped by file (the scanner has one row each). Names show what the "
             "procedures take; SqlDbType values map to NpgsqlDbType.", ["Application", "File", "Parameters", "Names"], prow)
    pg.table("other", "Connections and transactions", "Connection handling and transaction rows.",
             ["Application", "Type", "Subtype", "File:line", "Code"], other, code_cols=(4,),
             cls=lambda i, v, r: "bad" if i == 1 and "Distributed" in str(v) else "")
    xrows = []
    for a in apps:
        rq = (xc.get(a.lower()) or {}).get("rasql")
        if rq:
            xrows += [[a, "Inline SQL rows", rq["inline_sql"]["atf"], rq["inline_sql"]["matched"], "; ".join(f"{k}: {v}" for k, v in rq["inline_sql"]["atf_only_by_reason"].items())],
                      [a, "Execute rows", rq["execute_calls"]["atf"], rq["execute_calls"]["matched"], "; ".join(f"{k}: {v}" for k, v in rq["execute_calls"]["atf_only_by_reason"].items())]]
            for s in rq["ours_only"]["procedure_call_sites"]:
                xrows.append([a, "Found only by this skill", "", "", f"procedure {s['name']} at {s['file']}:{s['line']}"])
            for s in rq["ours_only"]["statements"]:
                xrows.append([a, "Found only by this skill", "", "", f"SQL at {s['file']}:{s['line']}"])
            o = rq["ours"]
            xrows.append([a, "This skill's SQL scan", "", "", f"{o['statements']} statements, {o['fragments']} fragments, {o['procedure_call_sites']} procedure "
                          f"call sites ({o['distinct_procedures']} distinct procedures)"])
    pg.table("crosscheck", "Cross-check with this skill's SQL scan", "AWS Transform rows against raw_sql.py, matched by file and line (within 3 lines). Unmatched "
             "rows carry the reason.", ["Application", "Fact", "AWS Transform rows", "Matched", "Notes"], xrows,
             empty="Not cross-checked yet: run atf_scan.py --reconcile-only after scan_repo.py.")
    return pg.write(out, path)


def build(radnet_src=None, rasql_src=None):
    done = []
    for name, src, fn in (("radnet", radnet_src or latest("radnet"), radnet), ("rasql", rasql_src or latest("rasql"), rasql)):
        if src and os.path.exists(src):
            done.append(fn(src, os.path.join(ATF, f"{name}-report.html")))
    return done


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--radnet")
    ap.add_argument("--rasql")
    a = ap.parse_args()
    root, _ = load_config()
    os.chdir(root)
    for p in build(a.radnet, a.rasql) or []:
        print(f"wrote {p} ({os.path.getsize(p) // 1024} KB)")
    if not (latest("radnet") or latest("rasql") or a.radnet or a.rasql):
        print("no AWS Transform scanner results in assessment/atf/: run atf_scan.py first")


if __name__ == "__main__":
    main()
