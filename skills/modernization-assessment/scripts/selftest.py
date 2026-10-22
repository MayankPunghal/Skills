"""Self-test for the assessment pipeline (run, do not read): builds a throwaway three-repository estate and runs the
scripts end to end, then checks the cases field runs got wrong.

    python scripts/selftest.py [--keep <dir>]

1. Unit checks: mask() and CODE_CREDENTIALS (credentials written in code), the CFG-HARDCODED-SECRET "not" pattern
   (jQuery selectors and key names are not secrets), minified bundle detection, n_settings() (Web.config transforms
   count once), the claude port engine, and codebase-documenter's sql_paths() (T-SQL in .txt is sniffed, prose is not).
2. A mixed estate:
   - Storefront: a web project with no C# (static content): Replatform to S3 + CloudFront, the B13 static item and
     nothing ported, no workflow gate failure.
   - ChatDesk: Bot Builder v3 (rewrite package) -> Refactor; a project reference outside the repository ->
     DEP-OUTSIDE-REPO and an "excluded" line; AppFabric only in config -> Low; a minified bundle is skipped; a jQuery
     password selector is not a hard-coded secret; a credential in code never reaches any output; a manual finding takes
     its verdict by rule id and is priced in the phased estimate; an intake.py --open-question reaches the report;
     review_queue.py --decisions before classification gives guidance.
   - SqlScripts: T-SQL only (no .NET): out of scope; sql_estate.py inventories it, including a .txt script and
     xp_cmdshell.
3. A no-code estate (SqlScripts alone): the report, summary and tracker build, and verify_report's scope gate passes.
4. raw_sql.py on a folder with no C# exits with guidance, not a traceback.
Run it after changing a scanner rule, the package map, classification, estimation or report scripts. Exit 1 on any
failure. Fixtures go to a temporary folder (deleted unless --keep). Needs the sibling linux-readiness and
codebase-documenter skills; standard library only.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Fake values only: the test fails if any of them reaches an output.
FAKE_SECRETS = ("S3cr3tPw!x", "Hunter22pw", "dXNlcjpwYXNzd29yZA==")

STOREFRONT = {
    "Storefront.csproj": """<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <ProjectGuid>{11111111-2222-3333-4444-555555555555}</ProjectGuid>
    <ProjectTypeGuids>{349c5851-65df-11da-9384-00065b846f21};{fae04ec0-301f-11d3-bf4b-00c04f79efbc}</ProjectTypeGuids>
    <OutputType>Library</OutputType>
    <TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion>
  </PropertyGroup>
  <ItemGroup>
    <Content Include="index.html" />
    <Content Include="404.aspx" />
    <Content Include="js/site.js" />
    <Content Include="css/site.css" />
  </ItemGroup>
  <Import Project="$(VSToolsPath)\\WebApplications\\Microsoft.WebApplication.targets" />
</Project>
""",
    "index.html": "<!doctype html><html><head><link rel=\"stylesheet\" href=\"css/site.css\"></head><body><h1>Store</h1><script src=\"js/site.js\"></script></body></html>\n",
    "404.aspx": "<%@ Page Language=\"C#\" %>\n<html><body><asp:Label runat=\"server\" Text=\"Not found\" /></body></html>\n",
    "js/site.js": "document.addEventListener('DOMContentLoaded', function () { console.log('ready'); });\n",
    "css/site.css": "body { font-family: sans-serif; }\n",
    "Web.config": "<?xml version=\"1.0\"?>\n<configuration><system.web><compilation targetFramework=\"4.7.2\" /></system.web></configuration>\n",
}

CHATDESK = {
    "ChatDesk.sln": """Microsoft Visual Studio Solution File, Format Version 12.00
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "ChatDesk", "ChatDesk\\ChatDesk.csproj", "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"
EndProject
""",
    "ChatDesk/ChatDesk.csproj": """<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <ProjectGuid>{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}</ProjectGuid>
    <ProjectTypeGuids>{349c5851-65df-11da-9384-00065b846f21};{fae04ec0-301f-11d3-bf4b-00c04f79efbc}</ProjectTypeGuids>
    <OutputType>Library</OutputType>
    <RootNamespace>ChatDesk</RootNamespace>
    <TargetFrameworkVersion>v4.6.1</TargetFrameworkVersion>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="Microsoft.Bot.Builder, Version=3.15.3.0"><HintPath>..\\packages\\Microsoft.Bot.Builder.3.15.3\\lib\\net46\\Microsoft.Bot.Builder.dll</HintPath></Reference>
    <Reference Include="System.Web" />
  </ItemGroup>
  <ItemGroup>
    <Compile Include="Controllers\\MessagesController.cs" />
    <Compile Include="Services\\PartnerClient.cs" />
    <Content Include="Scripts\\login.js" />
    <Content Include="Scripts\\vendor.min.js" />
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="..\\..\\SharedLibs\\Contoso.Common\\Contoso.Common.csproj"><Name>Contoso.Common</Name></ProjectReference>
  </ItemGroup>
</Project>
""",
    "ChatDesk/packages.config": """<?xml version="1.0" encoding="utf-8"?>
<packages>
  <package id="Microsoft.Bot.Builder" version="3.15.3" targetFramework="net461" />
  <package id="Microsoft.Bot.Connector" version="3.15.3" targetFramework="net461" />
  <package id="Newtonsoft.Json" version="13.0.3" targetFramework="net461" />
</packages>
""",
    "ChatDesk/Controllers/MessagesController.cs": """using System.Net.Http;
using System.Threading.Tasks;
using System.Web.Http;
using Microsoft.Bot.Builder.Dialogs;
using Microsoft.Bot.Connector;

namespace ChatDesk.Controllers
{
    [BotAuthentication]
    public class MessagesController : ApiController
    {
        public async Task<HttpResponseMessage> Post([FromBody] Activity activity)
        {
            await Conversation.SendAsync(activity, () => new RootDialog());
            return Request.CreateResponse(System.Net.HttpStatusCode.OK);
        }
    }
}
""",
    "ChatDesk/Services/PartnerClient.cs": """using System;
using System.Net;
using System.Text;

namespace ChatDesk.Services
{
    public class PartnerClient
    {
        public string BasicHeader() => "Basic " + Convert.ToBase64String(Encoding.ASCII.GetBytes("apiuser:S3cr3tPw!x"));
        public string Fixed() => "Basic dXNlcjpwYXNzd29yZA==";
        public ICredentials Creds() => new NetworkCredential("svc", "Hunter22pw");
        public string Url() => "https://partner.example.com/api/orders";
    }
}
""",
    "ChatDesk/Scripts/login.js": "var passwordField = \"#txtPassword\";\nvar tokenInput = \".token-input\";\nfunction submit() { return $(passwordField).val(); }\n",
    "ChatDesk/Web.config": """<?xml version="1.0"?>
<configuration>
  <configSections>
    <section name="dataCacheClients" type="Microsoft.ApplicationServer.Caching.DataCacheClientsSection, Microsoft.ApplicationServer.Caching.Core" />
  </configSections>
  <dataCacheClients><dataCacheClient name="default"><hosts><host name="cachehost01" cachePort="22233" /></hosts></dataCacheClient></dataCacheClients>
  <appSettings>
    <add key="PartnerUrl" value="https://partner.example.com/api" />
    <add key="MicrosoftAppPassword" value="" />
  </appSettings>
  <system.web><compilation targetFramework="4.6.1" /></system.web>
</configuration>
""",
    "ChatDesk/Web.Release.config": """<?xml version="1.0"?>
<configuration xmlns:xdt="http://schemas.microsoft.com/XML-Document-Transform">
  <appSettings><add key="PartnerUrl" value="https://partner.example.com/api" xdt:Transform="SetAttributes" xdt:Locator="Match(key)" /></appSettings>
</configuration>
""",
}

SQLSCRIPTS = {
    "Tables/Orders.sql": "CREATE TABLE dbo.Orders (Id int IDENTITY(1,1) PRIMARY KEY, Total money NOT NULL);\nGO\n",
    "Procs/usp_GetOrders.sql": "CREATE PROCEDURE dbo.usp_GetOrders AS\nBEGIN\n  SELECT Id, Total FROM dbo.Orders;\nEND\nGO\n",
    "Procs/usp_Export.txt": "CREATE PROCEDURE dbo.usp_Export AS\nBEGIN\n  EXEC master..xp_cmdshell 'bcp dbo.Orders out c:\\\\exports\\\\orders.csv -T -c';\nEND\nGO\n",
    "README.txt": "These scripts create the order tables. Run them in order.\n",
}

MANUAL = [{
    "rule": "MAN-SESSION-AFFINITY",
    "category": "hosting",
    "title": "Dialog state kept in the bot's in-memory store needs sticky sessions",
    "severity": "Medium",
    "confidence": "Likely",
    "evidence": [{"file": "ChatDesk/Controllers/MessagesController.cs", "line": 13, "text": "await Conversation.SendAsync(activity, () => new RootDialog());"}],
    "why": "Bot Builder v3 keeps dialog state in memory unless a state store is configured.",
    "fix": "Move dialog state to a shared store.",
    "effort_key": "small-change",
}]


def write(root, files):
    for rel, text in files.items():
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)


def py(script, *args, cwd):
    r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(HERE, script), *args], cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8")
    return r.returncode, (r.stdout + r.stderr).strip()


def jload(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep", help="write the fixtures and outputs here and keep them")
    a = ap.parse_args()
    base = a.keep or tempfile.mkdtemp(prefix="ma-selftest-")
    fails = []

    def check(ok, what, detail=""):
        print(("ok    " if ok else "FAIL  ") + what + ("" if ok or not detail else f"\n      {detail[-1500:]}"))
        if not ok:
            fails.append(what)

    # 1. unit checks
    from _common import mask, CODE_CREDENTIALS, data
    code = CHATDESK["ChatDesk/Services/PartnerClient.cs"]
    m = "\n".join(mask(ln) for ln in code.splitlines())  # mask() works on one evidence line
    check(not [s for s in FAKE_SECRETS if s in m], "mask() hides credentials written in code (GetBytes user:pass, Basic header, NetworkCredential)")
    check("new NetworkCredential(" in m and "https://partner.example.com/api/orders" in m, "mask() keeps the code around the credential")
    check(mask('var x = "Basic authentication is used";') == 'var x = "Basic authentication is used";', "prose that mentions Basic is not masked")
    check(not any(rx.search(m) and rx.search(m).group(2) != "***" for rx in CODE_CREDENTIALS), "a masked line no longer matches CODE_CREDENTIALS")
    for keyword in ("new", "null", "this", "await"):
        s = f"password = {keyword} Foo();"
        check(keyword in mask(s), f"mask() leaves the keyword '{keyword}' after password =")

    rules = {r["id"]: r for r in data("rules.json")["rules"]}
    sec = rules["CFG-HARDCODED-SECRET"]
    not_rx = re.compile(sec["not"], re.I) if sec.get("not") else None
    for line in ('var passwordField = "#txtPassword";', 'tokenInput: ".token-input",', 'var secretKey = "client_secret";'):
        check(bool(not_rx and not_rx.search(line)), f"CFG-HARDCODED-SECRET 'not' excludes the DOM id / key name in {line}")
    check(not not_rx.search('var password = "Tr0ub4dor&3";'), "CFG-HARDCODED-SECRET 'not' keeps a real literal password")

    from scan_repo import minified
    check(minified("var a=1;" * 2000) and not minified("var a = 1;\n" * 2000), "minified() tells a bundle from source")

    from aws_native import n_settings
    try:
        cfg = [("Web.config", 3, "PartnerUrl"), ("Web.Release.config", 2, "PartnerUrl"), ("Web.Debug.config", 2, "PartnerUrl"),
               ("Web.config", 4, "Other")]  # (file, line, setting name)
        check(n_settings(cfg) == 2, f"n_settings() counts a key once across Web.config transforms (got {n_settings(cfg)})")
    except Exception as e:  # noqa: BLE001
        check(False, "n_settings() counts a key once across Web.config transforms", repr(e))

    import estimate_phases as EP
    inp = {"port_engine": {"value": "claude"}}
    check(EP.port_engine(inp) == "claude" and EP.owner("B1", "B", inp) == EP.ENGINES["claude"], "the claude port engine owns stage B items itself")
    check(EP.port_engine({"port_engine": {"value": "nonsense"}}) == "devtx", "an unknown port engine falls back to devtx")

    doc_dir = os.path.join(os.path.dirname(os.path.dirname(HERE)), "codebase-documenter", "scripts")
    sql_root = os.path.join(base, "sqlsniff")
    shutil.rmtree(sql_root, ignore_errors=True)
    write(sql_root, SQLSCRIPTS)
    with open(os.path.join(sql_root, "Procs", "utf16.prc"), "w", encoding="utf-16") as f:
        f.write("CREATE PROCEDURE dbo.usp_Wide AS SELECT 1\nGO\n")
    sys.path.insert(0, doc_dir)
    try:
        from sql_parse import sql_paths
        got = sorted(os.path.relpath(p, sql_root).replace("\\", "/") for p in sql_paths(sql_root))
        check(got == ["Procs/usp_Export.txt", "Procs/usp_GetOrders.sql", "Procs/utf16.prc", "Tables/Orders.sql"],
              f"sql_paths() sniffs T-SQL in .txt / UTF-16 .prc and skips prose (got {got})")
    except ImportError as e:
        check(False, "codebase-documenter sql_parse.py is importable", repr(e))

    # 2. the mixed estate
    repos = os.path.join(base, "repos")
    shutil.rmtree(repos, ignore_errors=True)
    write(os.path.join(repos, "Storefront"), STOREFRONT)
    write(os.path.join(repos, "ChatDesk"), CHATDESK)
    write(os.path.join(repos, "SqlScripts"), SQLSCRIPTS)
    with open(os.path.join(repos, "ChatDesk", "ChatDesk", "Scripts", "vendor.min.js"), "w", encoding="utf-8") as f:
        f.write("!function(){var u='https://cdn.vendor-example.net/track';" + "var a=1;" * 1200 + "}();")

    def estate(name, roots):
        ws = os.path.join(base, name)
        shutil.rmtree(ws, ignore_errors=True)
        os.makedirs(ws)
        steps = [("setup_assessment.py", "--client", "Fixture", "--roots", *roots, "--offline"),
                 ("intake.py", "--answers", json.dumps({"goal": "modernize", "os_today": "both", "db_engine": "dual", "db_hosting": "ec2", "aws_native": "now", "code_access": "all"})),
                 ("discover_estate.py",), ("atf_scan.py",), ("branch_evidence.py",), ("scan_repo.py", "--all", "--offline")]
        return ws, steps

    def run_steps(ws, steps, label):
        log = {}
        for s in steps:
            code_, out_ = py(s[0], *s[1:], cwd=ws)
            log[s[0]] = (code_, out_)
            if "Traceback" in out_:
                check(False, f"{label}: {s[0]} runs without a traceback", out_)
        return log

    ws, steps = estate("mixed", [os.path.join(repos, r) for r in ("Storefront", "ChatDesk", "SqlScripts")])
    log = run_steps(ws, steps, "mixed")
    inv = jload(os.path.join(ws, "assessment", "inventory", "estate.json"), {}) or {}
    st = jload(os.path.join(ws, "assessment", "state.json"), {}) or {}
    scope = {r: v.get("scope") for r, v in (st.get("repos") or {}).items()}
    check(scope.get("sqlscripts") == "out" and scope.get("chatdesk") != "out", f"a T-SQL-only repository is out of scope, the .NET ones in (scope: {scope})")
    os.makedirs(os.path.join(ws, "assessment", "reviews"), exist_ok=True)
    with open(os.path.join(ws, "assessment", "reviews", "chatdesk.manual.json"), "w", encoding="utf-8") as f:
        json.dump(MANUAL, f)
    with open(os.path.join(ws, "assessment", "reviews", "chatdesk.json"), "w", encoding="utf-8") as f:
        json.dump({"MAN-SESSION-AFFINITY": {"verdict": "confirmed", "note": "seen in review"}}, f)
    lower = "chatdesk"
    run_steps(ws, [("linux_readiness.py", lower), ("intake.py", "--open-question", "Which channel registrations does the bot have?", "Bot rewrite scope", "client")], "mixed")
    rq = py("review_queue.py", "--decisions", cwd=ws)[1]  # before classify_apps.py: guidance, not a traceback
    check("classify_apps.py first" in rq and "Traceback" not in rq, "review_queue.py --decisions before classification says to run classify_apps.py", rq)
    log.update(run_steps(ws, [("map_graphs.py", "--all", "--no-exports"), ("classify_apps.py",), ("estimate_effort.py",), ("effort_facts.py",),
                              ("estimate_phases.py", "--all"), ("plan_execution.py", "--port-engine", "claude"), ("sql_estate.py",),
                              ("build_report.py",), ("build_summary.py",), ("build_tracker.py",), ("reference.py",)], "mixed"))

    findings = jload(os.path.join(ws, "assessment", "report", "findings.json"), []) or []
    fl = findings if isinstance(findings, list) else findings.get("findings", [])
    by_rule = {}
    for f_ in fl:
        by_rule.setdefault(f_.get("rule"), []).append(f_)
    check("DEP-OUTSIDE-REPO" in by_rule, "a project reference outside the repository is reported as DEP-OUTSIDE-REPO")
    sec_hits = [e.get("file") for f_ in by_rule.get("CFG-HARDCODED-SECRET", []) for e in f_.get("evidence") or []]
    check(not any(str(x).endswith("login.js") for x in sec_hits), f"a jQuery password selector is not a hard-coded secret (hits: {sec_hits})")
    check(not any("vendor.min.js" in json.dumps(f_.get("evidence") or []) for f_ in fl), "a minified bundle is not scanned")
    app_fabric = by_rule.get("CACHE-APPFABRIC", [])
    check(app_fabric and all(f_.get("severity") == "Low" for f_ in app_fabric), f"AppFabric only in config is Low (got {[f_.get('severity') for f_ in app_fabric]})")
    man = [f_ for f_ in fl if f_.get("rule") == "MAN-SESSION-AFFINITY"]
    check(man and man[0].get("id") == "chatdesk:MAN-SESSION-AFFINITY" and man[0].get("confidence") == "Confirmed",
          f"a manual finding gets a stable id and takes its verdict by rule id (got {[(x.get('id'), x.get('confidence')) for x in man]})")

    cls = (jload(os.path.join(ws, "assessment", "classification.json"), {}) or {}).get("applications", [])
    apps = {x["repo"]: x for x in cls}
    sf, cd = apps.get("storefront", {}), apps.get("chatdesk", {})
    check(sf.get("content_only") and sf.get("r7") == "Replatform" and "S3" in str(sf.get("target")), f"a web project with no C# is static content on S3 (got {sf.get('r7')}, {sf.get('target')})")
    check(cd.get("r7") == "Refactor" and "Bot" in " ".join(cd.get("rationale") or []), f"Bot Builder v3 forces Refactor (got {cd.get('r7')})")
    check(all(isinstance(x.get(k), list) for x in cls for k in ("notes", "risks", "why_not", "then", "sign_off") if k in x), "decision list fields are lists")

    ph = (jload(os.path.join(ws, "assessment", "effort", "estimate-phases.json"), {}) or {}).get("repos", {})
    sfp, cdp = ph.get("storefront", {}), ph.get("chatdesk", {})
    sf_items = {i for p in sfp.get("phases", []) for i in p.get("items", [])}
    check("B13" in sf_items and not sf_items & {"B1", "B3", "B9"} and (sfp.get("total") or [99, 99])[1] <= 12,
          f"static content is priced as publishing only (items {sorted(sf_items)}, total {sfp.get('total')})")
    cd_what = [w for p in cdp.get("phases", []) for w in p.get("what", [])]
    check(any("sticky sessions" in w for w in cd_what), "a manual finding is priced in the phased estimate")
    check("SharedLibs" in str(cdp.get("excluded")) or "Contoso.Common" in str(cdp.get("excluded")), f"libraries outside the repository are listed as not estimated (excluded: {cdp.get('excluded')})")

    sql_inv = glob.glob(os.path.join(ws, "assessment", "sql", "sqlscripts", "db-inventory.json"))
    sqlj = jload(sql_inv[0], {}) if sql_inv else {}
    check(bool(sql_inv) and "xp_cmdshell" in json.dumps(sqlj) and "usp_Export" in json.dumps(sqlj),
          "sql_estate.py inventories the out-of-scope SQL repository, .txt scripts and xp_cmdshell included")

    oq = os.path.join(ws, "assessment", "report", "open-questions.csv")
    check(os.path.exists(oq) and "Which channel registrations does the bot have?" in open(oq, encoding="utf-8").read(),
          "an open question added with intake.py --open-question reaches the modernize report")

    code_, out_ = py("verify_report.py", "--allow-draft", cwd=ws)
    gate_fails = [ln for ln in out_.splitlines() if re.match(r"\s*(FAIL|✗)", ln) and "narrative" not in ln.lower()
                  and "not graphed" not in ln]  # graphify may not be installed where the self-test runs
    check(not gate_fails, "verify_report passes every gate but the narratives (mixed estate)", "\n".join(gate_fails) or out_)

    leaks = []
    for p in glob.glob(os.path.join(ws, "assessment", "**", "*"), recursive=True):
        if os.path.isfile(p) and os.path.splitext(p)[1].lower() in (".json", ".md", ".html", ".csv", ".txt"):
            t = open(p, encoding="utf-8", errors="replace").read()
            leaks += [f"{os.path.relpath(p, ws)}: {s}" for s in FAKE_SECRETS if s in t]
    check(not leaks, f"no fake credential reaches any output (leaks: {leaks[:5] or 'none'})")

    # 3. a no-code estate
    ws2, steps2 = estate("nocode", [os.path.join(repos, "SqlScripts")])
    run_steps(ws2, steps2 + [("classify_apps.py",), ("estimate_effort.py",), ("effort_facts.py",), ("estimate_phases.py", "--all"),
                             ("sql_estate.py",), ("build_report.py",), ("build_summary.py",), ("build_tracker.py",)], "no-code")
    rep = glob.glob(os.path.join(ws2, "assessment", "report", "*Modernization-Assessment.md"))
    check(bool(rep) and "no .NET" in open(rep[0], encoding="utf-8").read().replace("No .NET", "no .NET"), "a no-.NET estate gets a report that says so")
    summ = glob.glob(os.path.join(ws2, "assessment", "report", "*Modernization-Summary.md"))
    check(bool(summ) and "**SQL estate:**" in open(summ[0], encoding="utf-8").read(), "the no-.NET summary states the SQL estate")
    md = open(rep[0], encoding="utf-8").read() if rep else ""
    row = next((ln for ln in md.splitlines() if ln.startswith("| sqlscripts |")), "")
    check(".sql" in row and ".txt" in row, f"the out-of-scope table lists the file types (row: {row[:160]})")
    code_, out_ = py("verify_report.py", "--allow-draft", cwd=ws2)
    gate0 = [ln for ln in out_.splitlines() if re.search(r"gate\s*0|scope", ln, re.I) and re.match(r"\s*(FAIL|✗)", ln)]
    check(not gate0, "verify_report's scope gate passes a no-.NET estate", out_)

    # 4. raw_sql with no C#
    code_, out_ = py("raw_sql.py", "--root", os.path.join(repos, "SqlScripts"), "--out", os.path.join(base, "rawsql"), cwd=ws2)
    check("Traceback" not in out_ and code_ != 0 or "no .cs" in out_.lower(), "raw_sql.py with no C# exits with guidance", out_)

    print(f"\n{'PASS' if not fails else 'FAIL'}: {len(fails)} failed. Fixtures: {base}{'' if a.keep else ' (deleted)'}")
    if not a.keep:
        shutil.rmtree(base, ignore_errors=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
