# Linux readiness

What works on Windows today but breaks, or behaves differently, in a Linux container on AWS (ECS/EKS, Fargate or EC2). One check, `scripts/linux_readiness.py`, with one catalogue, `scripts/data/linux_readiness.json`. The same two files ship in the migration-assessment and dotnet-modernization skills: change both together.

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
```

- Writes `linux-readiness.json`, `linux-readiness.md` and its `.html` twin (default folder `<repo>/.modernization`; in an assessment pass `--out assessment/linux/<repo>`).
- Standard library only; reads files, never changes them. Client repositories stay read-only.
- Secret values are masked in every hit (`password=<masked>`). Never copy hit text from the raw files into chat or reports.
- Waivers: `[{"rule": "LNX-...", "path": "glob", "reason": "...", "by": "..."}]`. A waived hit still shows, marked as waived.
- Skipped: `bin`, `obj`, `packages`, `node_modules`, hidden folders, files over 2 MB, and `Properties/launchSettings.json` (local debugging only).

## What it checks

240 checks in 19 areas: 130 block, 91 warn, 19 info. 221 are automated; 19 need a person and are listed as a checklist at the end of the report.

| Area | Checks | Automated | Examples |
|---|---|---|---|
| Build, project and packaging | 20 | 15 | Legacy (non-SDK) csproj, WebApplication.targets, GAC references without HintPath, CA1416 |
| File system and paths | 24 | 19 | Letter case of literals against the files on disk, backslashes, drive letters, UNC paths, writes to the app folder |
| Time zones | 7 | 7 | Windows time-zone IDs, `DateTime.Now`, display names, tzdata missing from the image |
| Globalization and culture | 11 | 11 | ICU vs NLS, implicit culture compares, invariant mode, ICU missing from the image |
| Encodings, line endings and text | 9 | 6 | Code pages without the provider, CRLF scripts, `Encoding.Default` |
| Processes, shell, console and signals | 11 | 10 | `cmd.exe`, `.exe` launches, `UseShellExecute`, no host lifetime (SIGTERM) |
| Environment, identity and user | 7 | 6 | `MachineName`, `%VARS%`, `:` in environment variable names |
| Cryptography and certificates | 12 | 11 | DPAPI, CNG, certificate store, Data Protection key persistence, DES/RC2 |
| Authentication and identity | 12 | 12 | Windows authentication, Kerberos/NTLM, AD lookups, impersonation |
| Databases | 20 | 20 | Integrated security, LocalDB, OLE DB, MSDTC, named instances, error numbers |
| Networking | 15 | 15 | localhost dependencies, WinHttpHandler, proxies, port 80 vs 8080, forwarded headers |
| Interprocess communication | 5 | 5 | Named pipes, named mutexes and semaphores, memory-mapped files |
| Windows-only APIs | 25 | 24 | Registry, WMI, COM, EventLog, PerformanceCounter, System.Drawing, remoting, COM+ |
| Web platform and IIS hosting | 22 | 21 | System.Web, `HttpContext.Current`, Global.asax, in-process session, web.config modules |
| Containers and images | 12 | 11 | No `USER`, SDK in the final stage, no `.dockerignore`, libgdiplus, fonts, `--platform` |
| Configuration and secrets | 5 | 5 | Hard-coded secrets, protected config sections, config transforms |
| Logging, performance, GC and runtime | 8 | 8 | Log paths on disk, GC settings under container limits |
| Scheduling, messaging, serialization | 7 | 7 | MSMQ, Windows Task Scheduler, BinaryFormatter |
| CI/CD and tests | 8 | 8 | msbuild.exe / vstest / powershell.exe steps, no `.gitattributes` |

About 90 checks rest on engineering knowledge rather than a fetched source (`K` in the rule's sources). Treat their hits as leads and verify before reporting them as fact.

## Check types

Each rule in the JSON has `patterns` (regex + file types) and optionally a `check` type and filters:

| Field | Meaning |
|---|---|
| (none) | A regex over the lines of the named file types; comments are skipped |
| `files: ["@path"]` | The regex runs over the file's path, case-insensitively unless the regex has `(?i:...)` (a rule about letter case) |
| `context` | The hit counts only if this regex is within 15 lines of it |
| `unless_in_file` | No hit in a file that contains this regex (e.g. `AddDataProtection` with `PersistKeysTo` in the same file) |
| `unless_in_line` | No hit when the same line also matches (e.g. `string.Compare` with `StringComparison`) |
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
- In the assessment, hits feed the Linux work in the estimate; in execution, each hit maps to a playbook (`linux-and-containers`, `windows-only-apis`, `config-and-secrets`, `startup-and-middleware`, `time-and-culture`).

## What AWS Transform and DevTx do and do not cover

**AWS Transform for .NET**
- Produces a Linux readiness report of Windows-specific items it could not fix at build time; in Visual Studio it exports as CSV (project, file, description, issue, recommendation). A "Linux porting status" column marks code groups that still need manual changes. It builds remotely and runs unit tests.
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
- Copy the script and the JSON to the other skill.

## Sources

Microsoft Learn: platform compatibility analyzer and CA1416; porting overview; .NET Framework technologies unavailable on .NET; Windows Compatibility Pack; System.Drawing.Common Windows-only; ASP.NET Core default port 8080; globalization and ICU; globalization config (invariant mode, NLS); cross-platform cryptography; ProtectedData; `UseShellExecute`; `Path.GetInvalidFileNameChars`; `Environment.GetFolderPath`; CodePagesEncodingProvider; FileSystemWatcher; Windows services as BackgroundService; GC config; BinaryFormatter removal (.NET 9); Windows authentication in ASP.NET Core.

AWS: AWS Transform user guide (Visual Studio, how it works, .NET capabilities and limitations); prescriptive guidance "Re-architecting as a Linux container"; Porting Assistant for .NET (retired in favour of AWS Transform).

Community: rootless .NET containers (`USER $APP_UID`, UID 1654); ICU and tzdata in Alpine/chiseled images (dotnet-docker discussions); cross-platform time zones with .NET Core; case-sensitivity write-ups.

Local: DevTx KB `19-linux-containerization.md`; the migration-assessment rule catalogue (`rules.json`) and `linux-pitfalls.md`; the dotnet-modernization residue catalogue (`residue_rules.json`).

URLs for every source are in the `sources` block of `data/linux_readiness.json`.
