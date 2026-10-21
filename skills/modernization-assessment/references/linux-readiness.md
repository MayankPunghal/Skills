# Linux readiness

What works on Windows today but breaks, or behaves differently, in a Linux container on AWS (ECS/EKS, Fargate or EC2). One check, `scripts/linux_readiness.py`, with one catalogue, `scripts/data/linux_readiness.json`. The same files (with `_mdhtml.py`) ship in the modernization-assessment, dotnet-modernization and linux-readiness skills: change all three together.

## Contents

- [When to run it](#when-to-run-it)
- [How to run it](#how-to-run-it)
- [What it checks](#what-it-checks)
- [Check types](#check-types)
- [Reading the result](#reading-the-result)
- [What AWS Transform and DevTx do and do not cover](#what-aws-transform-and-devtx-do-and-do-not-cover)
- [Keeping the catalogue current](#keeping-the-catalogue-current)
- [Sources](#sources)

## When to run it

| Situation | Run | Why |
|---|---|---|
| Assessment of .NET Framework code | Once per repository, next to the main scan | Sizes the Linux work separately from the framework port |
| Application already on .NET 5+ | **Only this check** (no porting engine) | The port is done; Linux is the remaining risk |
| After the porting engine and the Claude clean-up | `verify.py` runs it as the `linux` gate | Catches what the engine left and what the port introduced |
| Before the first container build | With `--gate` | Exit 1 while a blocking hit is open |

## How to run it

```bash
python scripts/linux_readiness.py <repo-or-solution-folder> [--out <dir>] [--waivers waivers.json] [--level block|warn|info] [--gate] [--title NAME]
python scripts/linux_readiness.py <folder-or-Dockerfile> --dockerfile-only [--out <dir>] [--gate]
python scripts/linux_readiness.py --explain [LNX-ID | id prefix | words]
```

- Writes `linux-readiness.json`, `linux-readiness.md` and its `.html` twin (default folder `<repo>/.modernization`; in an assessment pass `--out assessment/linux/<repo>`).
- Standard library only; reads files, never changes them. Client repositories stay read-only.
- Secret values are masked in every hit (`Password=***`, `<add key="ApiSecret" value="***"/>`, `ENV DB_PASSWORD=***`). Never copy hit text from the raw files into chat or reports.
- `--dockerfile-only`: only the checks that read Dockerfiles and entrypoint scripts, the "no `.dockerignore`" check and the Dockerfile checklist items; over a folder, or one Dockerfile (then `.dockerignore` is looked for from its folder up to the repository root, the folder with `.git`). Writes `linux-readiness-dockerfile.*`.
- `--explain`: no scan; prints a check's level, what breaks, regex, filters, fix and resolved source URL. A prefix (`LNX-CTR`) or words (`time zone`) list the matching checks.
- Waivers: `[{"rule": "LNX-...", "path": "glob", "reason": "...", "by": "...", "expires": "YYYY-MM-DD"}]`. A waived hit still shows, marked as waived. A waiver without a reason, or past its expiry date, is ignored; the report lists ignored waivers and waivers that match no hit under "Waivers to tidy".
- Skipped: `bin`, `obj`, `packages`, `node_modules`, hidden folders, files over 2 MB, and `Properties/launchSettings.json` (local debugging only).

## What it checks

337 checks in 19 areas: 147 block, 144 warn, 46 info. 317 are automated; 20 need a person and are listed as a checklist at the end of the report.

| Area | Checks | Automated | Examples |
|---|---|---|---|
| Build, project and packaging | 26 | 21 | Legacy (non-SDK) csproj, Web Site projects, WebApplication.targets, GAC references without HintPath, private feeds, CA1416, `PlatformTarget x86` (no 32-bit runtime on Linux) |
| File system and paths | 35 | 30 | Letter case of literals against the files on disk, backslashes (also in assembly and native paths), drive letters, UNC paths, writes to the app folder, MyDocuments on Linux, upper-case `GetFiles` search patterns, EFS `File.Encrypt`, directory listing order, creation time, drive-letter root logic |
| Time zones | 7 | 7 | Windows time-zone IDs, `DateTime.Now`, display names, tzdata missing from the image |
| Globalization and culture | 14 | 14 | ICU vs NLS, implicit culture compares, invariant mode, ICU missing from the image, renamed ICU override variable, web.config `<globalization>` |
| Encodings, line endings and text | 12 | 9 | Code pages without the provider, `GetEncoding(0)`, CRLF scripts, `Encoding.Default`, zip entry names, splitting on `Environment.NewLine` |
| Processes, shell, console and signals | 15 | 14 | `cmd.exe`, `.exe` launches, `UseShellExecute`, no host lifetime or SIGTERM handler, Windows-only console members, exit codes outside 0-255 |
| Environment, identity and user | 10 | 9 | `MachineName`, `%VARS%`, `:` in environment variable names, `DOTNET_` variables overriding runtimeconfig, `UserDomainName` |
| Cryptography and certificates | 18 | 17 | DPAPI, CNG, certificate store, Data Protection key persistence, DES/RC2, OpenSSL 1.1.1 on old bases, dev certificates in images, Rijndael-256 blocks |
| Authentication and identity | 15 | 15 | Windows authentication, Kerberos/NTLM, AD lookups, impersonation, SPN ports, native LDAP library for DirectoryServices.Protocols, OWIN sign-in and ADAL |
| Databases | 22 | 22 | Integrated security, LocalDB, OLE DB, MSDTC, named instances, error numbers, SqlClient `Encrypt` default and `TrustServerCertificate`, ODBC without unixODBC or with Windows DSNs |
| Networking | 20 | 20 | localhost dependencies, WinHttpHandler, proxies, port 80 vs 8080, ping payloads, long-lived HttpClient without `PooledConnectionLifetime`, ECS bridge mode and IMDS, WCF services hosted by IIS/WAS, network interface members that throw |
| Interprocess communication | 6 | 6 | Named pipes (and members that throw on Linux), named mutexes and semaphores, memory-mapped files |
| Windows-only APIs | 32 | 30 | Registry, WMI, COM, EventLog, PerformanceCounter, System.Drawing, remoting, COM+, zlib P/Invoke, bare `using System.Drawing`, Office interop, ReportViewer and Crystal Reports, VB `CreateObject`/`Shell`, bundled Windows tools (wkhtmltopdf, Ghostscript) |
| Web platform and IIS hosting | 45 | 45 | System.Web, `HttpContext.Current`, Global.asax, in-process session, forwarded headers, `WebHost` ports, `ASPNETCORE_URLS` vs `HTTP_PORTS`, Kestrel bound to localhost, IIS configuration Kestrel does not read (URL authorization, custom headers, IP restrictions, request filtering and limits, timeouts, static content, compression, error pages, modules and handlers), server variables, virtual directories, out-of-process session, request validation |
| Containers and images | 23 | 22 | No `USER`, SDK in the final stage, no `.dockerignore`, Debian tags on .NET 10, chiseled images with `apt-get`, Alpine missing libraries, `app` user clash, task definitions without `initProcessEnabled` |
| Configuration and secrets | 7 | 7 | Hard-coded secrets, protected config sections, config transforms, `<system.net>` sections, `configSource` / `file=` paths |
| Logging, performance, GC and runtime | 13 | 12 | Log paths on disk, GC settings under container limits, Server GC in small tasks, `Trace` output with no listener, Application Insights for System.Web, ETW sessions |
| Scheduling, messaging, serialization | 7 | 7 | MSMQ, Windows Task Scheduler, BinaryFormatter |
| CI/CD and tests | 10 | 10 | msbuild.exe / vstest / powershell.exe steps, no `.gitattributes`, `PublishContainer` without a registry |

123 checks rest on engineering knowledge rather than a fetched source (`K` in the rule's sources; a `[K: ...]` note in the text names a page read once and not re-verified). Treat their hits as leads and verify before reporting them as fact.

The catalogue was checked for completeness on 2026-10-21 against the AWS Transform for .NET user guide (limitations, dependency resolution, Next Steps), the Microsoft Learn porting pages, the .NET 5-10 breaking-change pages that differ on Linux, and the .NET container pages (images, chiseled, publish configuration, HTTPS, health checks, GC). AWS Transform's own Linux readiness report and `NextSteps.md` list what it could not fix; its pages do not describe their columns in detail, so this scan stays the gate. Re-check those pages when a new .NET version ships.

A second pass on the same day added IIS configuration that Kestrel does not read (each `system.web` and `system.webServer` section an IIS-hosted site typically uses), the kinds of finding in a lift-and-shift Windows-only inventory that the catalogue lacked (WCF hosting, modules and handlers, report viewers, Office interop, ODBC, out-of-process session, Application Insights for System.Web, OWIN/ADAL sign-in), and Windows-only behaviour from the Microsoft Learn API pages (EFS, listing order, creation time, `Environment.NewLine`, network interface members, Rijndael block sizes, no x86 runtime on Linux). Run on real legacy code, it was tuned to skip the default web.config template lines.

## Check types

Each rule in the JSON has `patterns` (regex + file types) and optionally a `check` type and filters:

| Field | Meaning |
|---|---|
| (none) | A regex over the lines of the named file types; comments are skipped |
| `files: ["@path"]` | The regex runs over the file's path, case-insensitively unless the regex has `(?i:...)` (a rule about letter case) |
| `context` | The hit counts only if this regex is within 15 lines of it |
| `unless_in_file` | No hit in a file that contains this regex (e.g. `AddDataProtection` with `PersistKeysTo` in the same file) |
| `unless_in_line` | No hit when the same line also matches (e.g. `string.Compare` with `StringComparison`) |
| `only_path` | The rule applies only to files whose repository-relative path matches (e.g. test projects) |
| `check: case_exact` | The captured file reference exists on disk only with different letter case |
| `check: reference_without_hintpath` | A `<Reference>` in a project file with no `<HintPath>` (resolved from the GAC) |
| `check: file_lacks` | The file has no line that matches (a Dockerfile with no `USER`) |
| `check: crlf` | The file has Windows line endings (shell scripts, entrypoints, Dockerfiles) |
| `check: last_from_sdk` | The last `FROM` of a Dockerfile is an SDK image |
| `check: absent` | A path matches `when_path` but nothing in the repository matches `absent_path` (a Dockerfile with no `.dockerignore`) |

## Reading the result

- **PASS** means no open blocking hit. Warn and info hits are reviewed, not gated.
- **Block**: fails the build, startup or a common path on Linux. **Warn**: behaves differently or fails on some paths. **Info**: verify.
- The report lists the areas, the checks that hit (what breaks and the fix), up to 25 locations per check, and the checklist of checks a person confirms.
- In the assessment, the full report for each repository is written to `assessment/linux/<repo>/`; the assessment report itself shows only each repository's blocking and to-review counts, in the per-application Linux verdict (the estimate does not read the hits). In execution, each hit maps to a playbook (`linux-and-containers`, `windows-only-apis`, `config-and-secrets`, `startup-and-middleware`, `time-and-culture`).

## What AWS Transform and DevTx do and do not cover

**AWS Transform for .NET**
- Produces a Linux readiness report of Windows-specific items it could not fix at build time; in Visual Studio it exports as CSV (project, file, description, issue, recommendation). That column detail comes from the predecessor Amazon Q pages; the current user guide names a `NextSteps.md` with "changes needed for Linux compatibility" and, in the web assessment, a per-repository Linux readiness rating. A "Linux porting status" column marks code groups that still need manual changes. It builds remotely and runs unit tests.
- It does not port `.svc`, `.ashx`, `.asmx`, web references or third-party UI controls. Its report is a starting list, not a gate: run this check after it.

**DevTx Version Upgrade Toolkit (KB 19, Linux containerization)**
- Covers a multi-stage Dockerfile, port 8080, `__` environment overrides, logs to stdout, a mounted PFX for HTTPS, a health endpoint and deployment targets.
- Has no Linux readiness content: nothing on letter case, path separators, ICU or invariant mode, tzdata, fonts or libgdiplus, culture, encodings, CRLF, exec bit, shell calls, Windows-only APIs, DPAPI, Data Protection keys, Windows auth, integrated security, certificate store, named pipes, Topshelf or IIS-to-Kestrel mapping. Its only automatic gate is `dotnet build` + `dotnet test`.
- Do not copy its samples as they are:
  - `HEALTHCHECK CMD curl` assumes curl is in the image (it is not in the .NET runtime images);
  - the Dockerfile sets no `USER` (use `USER $APP_UID`);
  - the sample connection string has a password and the PFX password is set in an `ENV` line: both end up in the image;
  - it pushes to Docker Hub, not ECR, and runs database migrations in the entrypoint, which races with several ECS tasks (use a one-off task).

## Keeping the catalogue current

- One rule per row in `data/linux_readiness.json`: `id` (`LNX-<AREA>-<NAME>`), `area`, `level`, `what`, `detect`, `fix`, `sources`, `patterns`, `automated`, optional `check` and filters. `tuned: true` marks rules refined against real code.
- After a change: run on a known-good modern app (it must PASS with no false blocking hits) and on a legacy repository, then spot-check the ten busiest rules.
- Copy the script, `_mdhtml.py` and the JSON to the other two skills. The linux-readiness skill's `selftest.py` must pass (the other two skills ship the same self-test under the name selftest_linux_readiness). It also checks that every rule with file types is marked automated, so a pattern without file types cannot silently turn a rule off.

## Sources

Microsoft Learn: platform compatibility analyzer and CA1416; porting overview; .NET Framework technologies unavailable on .NET; Windows Compatibility Pack; System.Drawing.Common Windows-only; ASP.NET Core default port 8080; globalization and ICU; globalization config (invariant mode, NLS); cross-platform cryptography; ProtectedData; `UseShellExecute`; `Path.GetInvalidFileNameChars`; `Environment.GetFolderPath`; CodePagesEncodingProvider; FileSystemWatcher; Windows services as BackgroundService; GC config; BinaryFormatter removal (.NET 9); Windows authentication in ASP.NET Core; native library loading; Kestrel endpoints; HttpClient guidelines; `EnumerationOptions.MatchCasing`; System.DirectoryServices.Protocols; logging and tracing; Kestrel options and limits; static files; response compression; HTTP modules to middleware; `IServerVariablesFeature`; proxies and load balancers (path base); session state; cross-site scripting; `Environment.NewLine`; `Directory.GetFiles`; `File.Encrypt`; `FileSystemInfo.CreationTime`; `Path.VolumeSeparatorChar`; `IPv4InterfaceProperties.IsDhcpEnabled`; `RijndaelManaged.BlockSize`; `Interaction.CreateObject`; `SmtpClient`; `Environment.UserName`; ReportViewer controls; the ODBC driver on Linux; Application Insights for ASP.NET Core; MSAL migration; IIS configuration reference (URL authorization, custom headers, IP security, request filtering, static content, application initialization); server-side automation of Office; .NET 10 supported OS.

AWS: AWS Transform user guide (Visual Studio, how it works, .NET capabilities and limitations); prescriptive guidance "Re-architecting as a Linux container"; Porting Assistant for .NET (retired in favour of AWS Transform). Amazon EC2 instance metadata (hop limit for containers); ECS task definition parameters (`initProcessEnabled`). Application Load Balancer idle timeout; AWS Distro for OpenTelemetry (.NET).

Community: rootless .NET containers (`USER $APP_UID`, UID 1654); ICU and tzdata in Alpine/chiseled images (dotnet-docker discussions); cross-platform time zones with .NET Core; case-sensitivity write-ups; Microsoft.Data.SqlClient 4.0 release notes (`Encrypt` default). CoreWCF project.

Local: DevTx KB `19-linux-containerization.md`; the modernization-assessment rule catalogue (`rules.json`) and `linux-pitfalls.md`; the dotnet-modernization residue catalogue (`residue_rules.json`). The kinds of finding in a lift-and-shift Windows-only inventory (finding types only, no client material).

URLs for every source are in the `sources` block of `data/linux_readiness.json`.
