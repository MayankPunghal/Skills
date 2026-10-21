"""Self-test for linux_readiness.py (run, do not read): builds two throwaway fixtures and checks the scanner end to end.

    python scripts/selftest.py [--keep <dir>]

1. A small clean .NET 10 solution (web API with a worker, Razor layout, Dockerfile with USER $APP_UID, .dockerignore,
   .gitattributes): must PASS with no blocking hit, also in --dockerfile-only mode.
2. A legacy .NET Framework 4.8 Web Forms app with fake secrets (web.config, code, Dockerfile ENV): must FAIL on the
   expected checks, and no fake secret value may appear in linux-readiness.json, .md or .html.
3. Waivers: a waiver without a reason is ignored; an expired one is ignored; a valid one turns a blocking hit to waived.
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

    code, msg = run("--explain", "LNX-CTR-USER-MISSING")
    check(code == 0 and "Fix:" in msg, "--explain describes a check")
    print(f"\n{'PASS' if not fails else 'FAIL'}: {len(fails)} failed. Fixtures: {base}{'' if a.keep else ' (deleted)'}")
    if not a.keep:
        shutil.rmtree(base, ignore_errors=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
