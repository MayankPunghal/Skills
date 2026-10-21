"""Self-test for linux_readiness.py (run, do not read): builds two throwaway fixtures and checks the scanner end to end.

    python scripts/selftest.py [--keep <dir>]

1. A small clean .NET 10 solution (web API with a worker, Razor layout, Dockerfile with USER $APP_UID, .dockerignore,
   .gitattributes): must PASS with no blocking hit, also in --dockerfile-only mode.
2. A legacy .NET Framework 4.8 Web Forms app with fake secrets (web.config, code, Dockerfile ENV): must FAIL on the
   expected checks, and no fake secret value may appear in linux-readiness.json, .md or .html.
3. Waivers: a waiver without a reason is ignored; an expired one is ignored; a valid one turns a blocking hit to waived.
4. A .NET 10 app wired wrongly for ECS (port 80, loopback binding, bridge mode, no init process, CRLF entrypoint and
   more): must hit the expected checks; appsettings.Development.json must not be reported.
5. A classic ASP.NET site whose web.config leans on IIS (authorization, headers, IP restrictions, request filtering and
   limits, StateServer session, globalization, system.net, modules) and Windows-only code: must hit the expected checks;
   an ASP.NET Core app's web.config must not count as modules and handlers.
6. Catalogue consistency: every rule's automated flag matches its patterns' file types, and every cited source exists.
Run it after every change to scripts/data/linux_readiness.json or linux_readiness.py. Exit 1 on any failure.
Fixtures go to a temporary folder (deleted unless --keep). Standard library only.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCANNER = os.path.join(HERE, "linux_readiness.py")

# Fake values only: the test fails if any of them reaches a report.
FAKE_SECRETS = ["Fake-Pa55w0rd-123", "FAKE_SECRET_VALUE_9876", "FAKE-API-KEY-abcdef123", "FakeDockerPw999", "FakeTokenXyz4567"]

CLEAN = {
    "Clean.sln": "Microsoft Visual Studio Solution File, Format Version 12.00\n",
    ".gitattributes": "* text=auto\n*.sh text eol=lf\nDockerfile text eol=lf\n",
    ".dockerignore": "**/bin/\n**/obj/\n**/.vs/\n.git\n*.user\n**/appsettings.Development.json\n",
    "src/Api/Api.csproj": """<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <InvariantGlobalization>false</InvariantGlobalization>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="AWSSDK.SecretsManager" Version="4.0.0" />
    <PackageReference Include="Amazon.AspNetCore.DataProtection.SSM" Version="4.0.0" />
  </ItemGroup>
</Project>
""",
    "src/Api/Program.cs": """using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.HttpOverrides;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddHealthChecks();
builder.Services.AddHttpClient();
builder.Services.AddRazorPages();
builder.Services.AddHostedService<Api.QueueWorker>();
builder.Services.AddDataProtection().PersistKeysToAWSSystemsManager("/clean/dataprotection");
builder.Services.Configure<ForwardedHeadersOptions>(o =>
    o.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto);

var app = builder.Build();
app.UseForwardedHeaders();
if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Home/Error");
}
app.UseStaticFiles();
app.MapHealthChecks("/health");
app.MapRazorPages();

var dataDir = Path.Combine(builder.Configuration["DataRoot"] ?? Path.GetTempPath(), "exports");
app.MapGet("/time", () => new { utc = DateTime.UtcNow, offset = DateTimeOffset.UtcNow });
app.MapGet("/zone", () => TimeZoneInfo.TryFindSystemTimeZoneById("America/New_York", out var tz) ? tz.Id : "UTC");
app.MapGet("/same/{a}/{b}", (string a, string b) => string.Equals(a, b, StringComparison.OrdinalIgnoreCase));
app.MapGet("/export", () => Path.Join(dataDir, "report.csv"));

app.Run();
""",
    "src/Api/QueueWorker.cs": """namespace Api;

public sealed class QueueWorker(ILogger<QueueWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            logger.LogInformation("Polling at {Time}", DateTimeOffset.UtcNow);
            await Task.Delay(TimeSpan.FromSeconds(30), stoppingToken);
        }
    }
}
""",
    "src/Api/Pages/Shared/_Layout.cshtml": """<!DOCTYPE html>
<html lang="en">
<head>
    <link rel="stylesheet" href="~/css/site.css" asp-append-version="true" />
</head>
<body>
    @RenderBody()
    <script src="~/js/site.js" asp-append-version="true"></script>
</body>
</html>
""",
    "src/Api/Pages/Index.cshtml": "@page\n<h1>Clean</h1>\n",
    "src/Api/wwwroot/css/site.css": "body { margin: 0; }\n",
    "src/Api/wwwroot/js/site.js": "// site\n",
    "src/Api/appsettings.json": """{
  "Logging": { "LogLevel": { "Default": "Information", "Microsoft.AspNetCore": "Warning" } },
  "AllowedHosts": "*",
  "ConnectionStrings": { "Main": "" },
  "DataRoot": "/data"
}
""",
    "src/Api/appsettings.Development.json": "{\n  \"Logging\": { \"LogLevel\": { \"Default\": \"Debug\" } }\n}\n",
    "src/Api/Properties/launchSettings.json": "{\n  \"profiles\": { \"http\": { \"commandName\": \"Project\", \"applicationUrl\": \"http://localhost:5080\" } }\n}\n",
    "src/Api/Dockerfile": """FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish src/Api/Api.csproj -c Release -o /app --no-self-contained

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /app .
USER $APP_UID
ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "Api.dll"]
""",
    "tests/Api.Tests/Api.Tests.csproj": """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <IsPackable>false</IsPackable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.14.0" />
    <PackageReference Include="xunit" Version="2.9.3" />
  </ItemGroup>
</Project>
""",
    "tests/Api.Tests/TimeTests.cs": """namespace Api.Tests;

public class TimeTests
{
    [Fact]
    public void UtcIsUtc() => Assert.Equal(DateTimeKind.Utc, DateTime.UtcNow.Kind);
}
""",
}

LEGACY = {
    "Legacy.sln": "Microsoft Visual Studio Solution File, Format Version 12.00\n"
                  "Project(\"{E24C65DC-7377-472B-9ABA-BC803B73C61A}\") = \"OldSite\", \"OldSite\\\", \"{11111111-2222-3333-4444-555555555555}\"\nEndProject\n",
    # a half-ported service: modern .NET, but still wrong for a Linux container
    "Ported/Dockerfile": """FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish Ported/Ported.csproj -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:10.0-bookworm-slim
RUN useradd -m app
ENV ASPNETCORE_URLS=http://+:80
ENV ASPNETCORE_HTTP_PORTS=8080
USER app
ENTRYPOINT ["dotnet", "Ported.dll"]
""",
    "Ported/Program.cs": """using System.Security.Cryptography;
using System.Text;

public static class Program
{
    public static void Main(string[] args)
    {
        var host = WebHost.CreateDefaultBuilder(args).Build();
        var enc = Encoding.GetEncoding(0);
        var docs = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
        using var rsa = RSA.Create();
        var cipher = rsa.EncryptValue(new byte[] { 1 });
        host.Run();
    }
}
""",
    "Legacy.Web/Legacy.Web.csproj": """<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="15.0" DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <TargetFrameworkVersion>v4.8</TargetFrameworkVersion>
    <OutputType>Library</OutputType>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="System.Web" />
    <Reference Include="Contoso.Licensing, Version=2.0.0.0, Culture=neutral, PublicKeyToken=abcdef0123456789" />
  </ItemGroup>
  <Import Project="$(VSToolsPath)\\WebApplications\\Microsoft.WebApplication.targets" />
  <PropertyGroup>
    <PostBuildEvent>xcopy /y "$(TargetDir)*.dll" "C:\\Deploy\\Legacy\\"</PostBuildEvent>
  </PropertyGroup>
</Project>
""",
    "Legacy.Web/Web.config": """<?xml version="1.0"?>
<configuration>
  <connectionStrings>
    <add name="Main" connectionString="Data Source=.\\SQLEXPRESS;Initial Catalog=Legacy;User ID=sa;Password=Fake-Pa55w0rd-123;" />
    <add name="Reports" connectionString="Server=REPORTS01\\BI;Database=Reports;Integrated Security=SSPI;" />
  </connectionStrings>
  <appSettings>
    <add key="ApiSecret" value="FAKE_SECRET_VALUE_9876" />
    <add key="ExportFolder" value="D:\\Exports\\Legacy" />
  </appSettings>
  <system.web>
    <authentication mode="Windows" />
    <sessionState mode="InProc" />
    <machineKey validationKey="AutoGenerate" decryptionKey="AutoGenerate" />
  </system.web>
</configuration>
""",
    "Legacy.Web/Global.asax.cs": """using System;
using System.Diagnostics;
using System.Runtime.Serialization.Formatters.Binary;
using System.Security.Cryptography;
using System.Web;
using Microsoft.Win32;

namespace Legacy.Web
{
    public class Global : HttpApplication
    {
        private const string ApiKey = "FAKE-API-KEY-abcdef123";
        private string token = "FakeTokenXyz4567";

        protected void Application_Start(object sender, EventArgs e)
        {
            var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\\Legacy");
            EventLog.WriteEntry("Legacy", "Started at " + DateTime.Now);
            var tz = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
            System.IO.File.AppendAllText(@"C:\\Logs\\legacy.log", "start");
            Process.Start("cmd.exe", "/c net use Z: \\\\fileserver\\share");
            var user = HttpContext.Current.User.Identity.Name;
            var blob = ProtectedData.Protect(new byte[] { 1 }, null, DataProtectionScope.LocalMachine);
            var bf = new BinaryFormatter();
        }
    }
}
""",
    "Legacy.Web/Site.Master": """<%@ Master Language="C#" %>
<html><head><link href="~/content/site.css" rel="stylesheet" /></head><body></body></html>
""",
    "Legacy.Web/Content/Site.css": "body { margin: 0; }\n",
    "Dockerfile": """FROM mcr.microsoft.com/dotnet/framework/aspnet:4.8-windowsservercore-ltsc2019
ENV DB_PASSWORD=FakeDockerPw999
COPY Legacy.Web/ /inetpub/wwwroot
CMD powershell -File C:\\start.ps1
""",
    "deploy.sh": "#!/bin/bash\r\necho deploying\r\n",
}

# A .NET 10 app that builds on Linux but is wired wrongly for ECS: each line trips one check.
ECS = {
    ".dockerignore": "**/bin/\n**/obj/\n",
    "Dockerfile": """FROM mcr.microsoft.com/dotnet/aspnet:10.0-noble
ENV ASPNETCORE_URLS=http://+:80
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
EXPOSE 80
USER $APP_UID
ENTRYPOINT ["dotnet", "App.dll"]
""",
    "docker-entrypoint": "#!/bin/sh\r\nexec dotnet App.dll\r\n",
    "deploy/app-taskdef.json": """{"family": "app", "networkMode": "bridge", "containerDefinitions": [{"name": "app", "environment": [
  {"name": "ASPNETCORE_URLS", "value": "http://localhost:8080"},
  {"name": "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT", "value": "true"}]}]}
""",
    "src/App/Program.cs": """var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://localhost:5000");
""",
    "src/App/appsettings.json": '{"Kestrel": {"Endpoints": {"Http": {"Url": "http://localhost:5000"}}}}\n',
    "src/App/appsettings.Development.json": '{"Kestrel": {"Endpoints": {"Http": {"Url": "http://localhost:5001"}}}}\n',
    "src/App/Images.cs": """using System;
using System.Diagnostics;
using System.DirectoryServices.Protocols;
using System.Drawing;
using System.Net.Http;

class Images
{
    static readonly HttpClient Http = new HttpClient();

    void Run()
    {
        var b = new Bitmap(10, 10);
        var files = System.IO.Directory.GetFiles("/data", "*.XML");
        Trace.TraceError("lost in a container");
        var ldap = new LdapConnection("ldap.example.internal");
        var cs = "Server=db;TrustServerCertificate=true";
    }
}
""",
}

# A classic ASP.NET site whose web.config leans on IIS: each section trips one IIS check.
# Core/web.config is an ASP.NET Core app's IIS shim and must not count as modules and handlers.
IIS = {
    "Site/web.config": """<?xml version="1.0"?>
<configuration>
  <system.web>
    <httpRuntime maxRequestLength="102400" executionTimeout="600" requestValidationMode="2.0" />
    <sessionState mode="StateServer" stateConnectionString="tcpip=127.0.0.1:42424" />
    <globalization culture="en-GB" uiCulture="en-GB" />
    <authorization><deny users="?" /></authorization>
    <httpModules><add name="Audit" type="Site.AuditModule" /></httpModules>
  </system.web>
  <system.net>
    <mailSettings><smtp from="noreply@example.com"><network host="smtp.example.internal" /></smtp></mailSettings>
  </system.net>
  <system.webServer>
    <httpProtocol><customHeaders><add name="X-Frame-Options" value="DENY" /></customHeaders></httpProtocol>
    <security>
      <ipSecurity allowUnlisted="false"><add ipAddress="10.0.0.0" subnetMask="255.0.0.0" allowed="true" /></ipSecurity>
      <requestFiltering><hiddenSegments><add segment="secret" /></hiddenSegments></requestFiltering>
    </security>
    <staticContent><mimeMap fileExtension=".webmanifest" mimeType="application/manifest+json" /></staticContent>
    <httpErrors errorMode="Custom" />
    <modules runAllManagedModulesForAllRequests="true"><add name="Audit2" type="Site.AuditModule" /></modules>
  </system.webServer>
</configuration>
""",
    "Site/Handlers.cs": """using System.IO;
using System.Web;

public class AuditModule : IHttpModule
{
    public void Init(HttpApplication app) { }
    public void Dispose() { }
    string Who(HttpRequest r) => r.ServerVariables["LOGON_USER"];
    string First() => Directory.GetFiles("/in").First();
    string[] Lines(string t) => t.Split(new[] { Environment.NewLine }, StringSplitOptions.None);
    void Lock(string p) => File.Encrypt(p);
}
""",
    "Site/Report.cs": "using Microsoft.Reporting.WebForms;\nusing Excel = Microsoft.Office.Interop.Excel;\n",
    "Site/Service.svc": '<%@ ServiceHost Language="C#" Service="Site.OrderService" %>\n',
    "Site/Site.csproj": "<Project><PropertyGroup><PlatformTarget>x86</PlatformTarget></PropertyGroup></Project>\n",
    "Core/web.config": """<?xml version="1.0"?>
<configuration><system.webServer>
  <handlers><add name="aspNetCore" path="*" verb="*" modules="AspNetCoreModuleV2" resourceType="Unspecified" /></handlers>
  <aspNetCore processPath="dotnet" arguments=".\\\\Core.dll" hostingModel="inprocess" />
</system.webServer></configuration>
""",
}


def write(root, files):
    for rel, text in files.items():
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)


def run(*args):
    r = subprocess.run([sys.executable, "-X", "utf8", SCANNER, *args], capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (r.stdout + r.stderr).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep", help="write the fixtures and outputs here and keep them")
    a = ap.parse_args()
    base = a.keep or tempfile.mkdtemp(prefix="lnx-selftest-")
    clean, legacy, out = (os.path.join(base, x) for x in ("clean-net10", "legacy-net48", "out"))
    for d in (clean, legacy):
        shutil.rmtree(d, ignore_errors=True)
    write(clean, CLEAN)
    write(legacy, LEGACY)
    os.makedirs(os.path.join(clean, ".git"), exist_ok=True)  # repository root marker for the single-Dockerfile mode
    fails = []

    def check(ok, what):
        print(("ok    " if ok else "FAIL  ") + what)
        if not ok:
            fails.append(what)

    code, msg = run(clean, "--out", os.path.join(out, "clean"), "--gate")
    res = json.load(open(os.path.join(out, "clean", "linux-readiness.json"), encoding="utf-8"))
    blocks = sorted({h["rule"] for h in res["hits"] if res["rules"][h["rule"]]["level"] == "block"})
    check(code == 0 and res["passed"], f"clean .NET 10 app passes the gate (blocking checks hit: {blocks or 'none'})")
    warns = sorted({h["rule"] for h in res["hits"] if res["rules"][h["rule"]]["level"] == "warn"})
    check(not warns, f"clean .NET 10 app has no warn hits either (hit: {warns or 'none'})")
    code, msg = run(os.path.join(clean, "src", "Api", "Dockerfile"), "--dockerfile-only", "--out", os.path.join(out, "clean-df"), "--gate")
    check(code == 0 and "PASS" in msg, "clean Dockerfile passes --dockerfile-only (single file, .dockerignore found at the repository root)")

    code, msg = run(legacy, "--out", os.path.join(out, "legacy"), "--gate")
    res = json.load(open(os.path.join(out, "legacy", "linux-readiness.json"), encoding="utf-8"))
    hit = {h["rule"] for h in res["hits"]}
    check(code == 1 and not res["passed"], "legacy app fails the gate")
    expected = ["LNX-BLD-LEGACY-CSPROJ", "LNX-BLD-WEB-TARGETS", "LNX-BLD-PREBUILD-WINDOWS-CMD", "LNX-CFG-HARDCODED-SECRET", "LNX-DATA-NAMED-INSTANCE",
                "LNX-AUTH-SQL-INTEGRATED", "LNX-AUTH-WINDOWS-AUTH-IIS", "LNX-API-REGISTRY", "LNX-API-EVENTLOG", "LNX-TZ-WINDOWS-ID", "LNX-FS-DRIVE-LETTER",
                "LNX-PROC-WINDOWS-TOOLS", "LNX-WEB-HTTPCONTEXT-CURRENT", "LNX-CRY-DPAPI", "LNX-SER-BINARYFORMATTER", "LNX-CTR-WINDOWS-BASE",
                "LNX-CTR-USER-MISSING", "LNX-FS-CRLF-SCRIPTS", "LNX-FS-CASE-STATIC-URL", "LNX-PROC-SHELL-FORM-ENTRYPOINT",
                # added by the 2026-10-21 exhaustive-list pass
                "LNX-BLD-WEBSITE-PROJECT", "LNX-CTR-DEBIAN-TAG-NET10", "LNX-CTR-APP-USER-EXISTS", "LNX-HOST-URLS-AND-HTTP-PORTS",
                "LNX-HOST-WEBHOST-OLD-PORTS", "LNX-CRY-RSA-ENCRYPTVALUE", "LNX-ENC-GETENCODING-ZERO", "LNX-FS-MYDOCUMENTS-XDG"]
    missing = [r for r in expected if r not in hit]
    check(not missing, f"legacy app hits the expected checks (missing: {missing or 'none'})")
    leaked = []
    for name in ("linux-readiness.json", "linux-readiness.md", "linux-readiness.html"):
        text = open(os.path.join(out, "legacy", name), encoding="utf-8").read()
        leaked += [f"{name}: {s[:4]}..." for s in FAKE_SECRETS if s in text]
    check(not leaked, f"no fake secret value in the legacy reports (leaks: {leaked or 'none'})")
    code, msg = run(legacy, "--dockerfile-only", "--out", os.path.join(out, "legacy-df"), "--gate")
    check(code == 1 and "FAIL" in msg, "legacy Dockerfile fails --dockerfile-only")
    text = open(os.path.join(out, "legacy-df", "linux-readiness-dockerfile.json"), encoding="utf-8").read()
    check("FakeDockerPw999" not in text, "Dockerfile-only report masks the ENV secret")

    wv = os.path.join(base, "waivers.json")
    json.dump([{"rule": "LNX-API-REGISTRY", "path": "Legacy.Web/*", "reason": "read once at start, replaced in sprint 3", "by": "selftest"},
               {"rule": "LNX-API-EVENTLOG", "path": "*", "reason": ""},
               {"rule": "LNX-CRY-DPAPI", "path": "*", "reason": "old", "expires": "2000-01-01"},
               {"rule": "LNX-API-WMI", "path": "*", "reason": "no WMI here"}], open(wv, "w", encoding="utf-8"))
    run(legacy, "--out", os.path.join(out, "legacy-w"), "--waivers", wv)
    res = json.load(open(os.path.join(out, "legacy-w", "linux-readiness.json"), encoding="utf-8"))
    st = {h["rule"]: h["waived"] for h in res["hits"]}
    check(st.get("LNX-API-REGISTRY") is True, "a waiver with a reason waives its hit")
    check(st.get("LNX-API-EVENTLOG") is False and st.get("LNX-CRY-DPAPI") is False, "waivers with no reason or past expiry are ignored")
    check(len(res["waivers_ignored"]) == 2 and len(res["waivers_unused"]) == 1, "ignored and unused waivers are reported")

    ecs = os.path.join(base, "ecs-net10")
    shutil.rmtree(ecs, ignore_errors=True)
    write(ecs, ECS)
    run(ecs, "--out", os.path.join(out, "ecs"))
    res = json.load(open(os.path.join(out, "ecs", "linux-readiness.json"), encoding="utf-8"))
    hit = {h["rule"] for h in res["hits"]}
    expected = ["LNX-HOST-PORT-80", "LNX-CUL-INVARIANT-MODE", "LNX-FS-CRLF-SCRIPTS", "LNX-API-DRAWING-USING", "LNX-HOST-KESTREL-LOOPBACK",
                "LNX-NET-HTTPCLIENT-NO-POOLED-LIFETIME", "LNX-NET-ECS-BRIDGE-IMDS", "LNX-CTR-INIT-PROCESS", "LNX-FS-SEARCH-PATTERN-CASE",
                "LNX-AUTH-LDAP-NATIVE-LIB", "LNX-LOG-TRACE-NO-LISTENER", "LNX-DATA-SQLCLIENT-ENCRYPT"]
    missing = [r for r in expected if r not in hit]
    check(not missing, f"ECS-wiring app hits the expected checks (missing: {missing or 'none'})")
    dev = [h for h in res["hits"] if h["rule"] == "LNX-HOST-KESTREL-LOOPBACK" and h["file"].endswith("appsettings.Development.json")]
    check(not dev, "appsettings.Development.json is not reported for localhost binding")
    inv = [h for h in res["hits"] if h["rule"] == "LNX-CUL-INVARIANT-MODE" and h["file"].endswith("taskdef.json")]
    check(bool(inv), "invariant globalization is found in an ECS task definition")

    iis = os.path.join(base, "iis-site")
    shutil.rmtree(iis, ignore_errors=True)
    write(iis, IIS)
    run(iis, "--out", os.path.join(out, "iis"))
    res = json.load(open(os.path.join(out, "iis", "linux-readiness.json"), encoding="utf-8"))
    hit = {h["rule"] for h in res["hits"]}
    expected = ["LNX-HOST-IIS-URL-AUTHORIZATION", "LNX-HOST-IIS-CUSTOM-HEADERS", "LNX-HOST-IIS-IP-SECURITY", "LNX-HOST-IIS-REQUEST-FILTERING",
                "LNX-HOST-IIS-REQUEST-LIMITS", "LNX-HOST-IIS-EXECUTION-TIMEOUT", "LNX-HOST-IIS-STATIC-CONTENT", "LNX-HOST-IIS-HTTP-ERRORS",
                "LNX-HOST-IIS-MODULES-HANDLERS", "LNX-HOST-IIS-WEBSERVER-REGISTRATIONS", "LNX-HOST-IIS-SERVER-VARIABLES", "LNX-WEB-SESSION-OUT-OF-PROC", "LNX-WEB-REQUEST-VALIDATION",
                "LNX-CUL-WEBCONFIG-GLOBALIZATION", "LNX-CFG-SYSTEM-NET-SECTION", "LNX-FS-ENUMERATION-ORDER", "LNX-ENC-ENVIRONMENT-NEWLINE",
                "LNX-FS-EFS-ENCRYPT", "LNX-API-REPORTING-WINDOWS", "LNX-API-OFFICE-INTEROP", "LNX-NET-WCF-SERVICE-HOST", "LNX-BLD-PLATFORM-X86"]
    missing = [r for r in expected if r not in hit]
    check(not missing, f"IIS-hosted site hits the expected IIS and Windows-only checks (missing: {missing or 'none'})")
    shim = [h for h in res["hits"] if h["rule"] in ("LNX-HOST-IIS-MODULES-HANDLERS", "LNX-HOST-IIS-WEBSERVER-REGISTRATIONS") and h["file"].startswith("Core")]
    check(not shim, "an ASP.NET Core app's web.config (AspNetCoreModule) is not reported as modules and handlers")

    # Catalogue consistency: a pattern without file types turns its whole rule into a checklist item that never runs
    # ("absent" checks match paths through when_path / absent_path instead).
    cat = json.load(open(os.path.join(HERE, "data", "linux_readiness.json"), encoding="utf-8"))
    bad = [r["id"] for r in cat["rules"] if r.get("check") != "absent" and r["automated"] != (bool(r["patterns"]) and all(p["files"] for p in r["patterns"]))]
    check(not bad, f"every rule's automated flag matches its patterns' file types (wrong: {bad or 'none'})")
    unknown = [r["id"] for r in cat["rules"] for s in r["sources"] if s != "K" and s not in cat["sources"]]
    check(not unknown, f"every cited source exists (unknown: {unknown or 'none'})")

    code, msg = run("--explain", "LNX-CTR-USER-MISSING")
    check(code == 0 and "Fix:" in msg, "--explain describes a check")
    print(f"\n{'PASS' if not fails else 'FAIL'}: {len(fails)} failed. Fixtures: {base}{'' if a.keep else ' (deleted)'}")
    if not a.keep:
        shutil.rmtree(base, ignore_errors=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
