---
name: linux-readiness
description: Checks a .NET code base for everything that works on Windows but breaks or behaves differently in a Linux container on AWS (ECS, EKS, Fargate), and says how to fix each hit. Covers file name case, paths, time zones, ICU culture, encodings, shell calls, environment, DPAPI and certificates, Windows auth and integrated security, SQL Server and ODBC, registry, WMI, COM, System.Drawing, IIS hosting, Dockerfiles, secrets and CI. Works on .NET Framework code before a port, ported code and apps already on .NET 5+. Read-only and masks secrets; writes a JSON, Markdown and HTML report, gates a build with waivers, and has a Dockerfile-only mode. Use when the user asks whether a .NET app is ready for Linux, Docker, containers, ECS, EKS or Fargate, what will break on Linux, to check a .NET Dockerfile, to explain a Linux readiness check, or to gate a pipeline on Linux readiness.
metadata:
  version: 1.0.0
user-invocable: true
argument-hint: "[help · scan · gate · dockerfile · explain · waivers · selftest] [folder | Dockerfile | LNX-ID]"
allowed-tools:
  - Bash(python <skill-base-dir>/scripts/*)
  - Bash(py -X utf8 <skill-base-dir>/scripts/*)
---

# Linux readiness for .NET

One scanner, `scripts/linux_readiness.py`, with one catalogue, `scripts/data/linux_readiness.json`: 287 checks in 19 areas (266 automated, 21 for a person to confirm). It answers one question: what in this .NET code base works on Windows today but breaks, or behaves differently, in a Linux container on AWS?

## Contents
- Ground rules
- Commands
- Workflow
- Reading the report
- Fix guide by area
- Related reading
- Relation to the other skills
- Maintaining this skill

## Ground rules

- **Client repositories are read-only.** The scanner only reads. Always pass `--out` to a folder outside the client repository (for example `./linux-readiness/<repo>` in the working folder). The default, `<folder>/.modernization`, is meant for a working copy you own.
- **Never print secret values.** Hit text is masked (`Password=***`). Quote hits from the report, never from the raw files, and never paste a raw config line into chat, a commit or a report.
- **Run Python as `py -X utf8` on Windows** (`python3` elsewhere). Standard library only; Python 3.10+.
- **Every Markdown output has its `.html` twin.** The scanner writes both; write any summary you produce the same way.
- Checks whose source is `K` are engineering knowledge, not a cited page: treat their hits as leads and confirm in the code before calling them fact (`--explain <id>` shows the source).

## Commands

Bare `/linux-readiness` (or `help`): ask for, or detect, the folder; say whether a report already exists in the output folder (summary line), recommend the next command, show this table. Start nothing.

| Command | What runs | Example request |
|---|---|---|
| `scan <folder>` | `linux_readiness.py <folder> --out <dir> [--title NAME] [--level block\|warn\|info]` | "Is this app ready for Linux containers?" |
| `gate <folder>` | the same with `--gate [--waivers waivers.json]`: exit 1 while a blocking hit is open | "Fail the pipeline if anything blocks Linux" |
| `dockerfile <folder\|Dockerfile>` | `linux_readiness.py <folder-or-Dockerfile> --dockerfile-only --out <dir> [--gate]` (Dockerfile, entrypoint and `.dockerignore` checks only; writes `linux-readiness-dockerfile.*`) | "Check my Dockerfile for the .NET app" |
| `explain <LNX-ID\|prefix\|words>` | `linux_readiness.py --explain <query>`: level, what breaks, regex, filters, fix and source URL; a prefix (`LNX-CTR`) or words (`time zone`) list matching checks; no query lists all | "Why did LNX-CTR-USER-MISSING fire?" |
| `waivers` | Write or review `waivers.json` (format below), then rerun the scan with `--waivers` | "Accept the registry read until sprint 3" |
| `selftest` | `selftest.py`: clean .NET 10 fixture must pass, legacy fixture must fail with secrets masked, waiver rules hold | after changing a rule |

Scripts (run them, do not read them):

```bash
py -X utf8 scripts/linux_readiness.py <repo-or-solution-folder> --out <dir> [--waivers waivers.json] [--level block|warn|info] [--gate] [--title NAME]
py -X utf8 scripts/linux_readiness.py <folder-or-Dockerfile> --dockerfile-only --out <dir> [--gate]
py -X utf8 scripts/linux_readiness.py --explain [LNX-ID | prefix | words]
py -X utf8 scripts/linux_readiness.py --all          # in a migration-assessment workspace: every inventoried repository
py -X utf8 scripts/selftest.py [--keep <dir>]
```

**Waivers** (`waivers.json`, template in [templates/waivers.example.json](templates/waivers.example.json)):

```json
[{"rule": "LNX-API-REGISTRY", "path": "src/Legacy/*", "reason": "read once at start; replaced in sprint 3", "by": "jane.doe", "expires": "2026-12-31"}]
```

- `rule` is a check id (or `*`), `path` a glob over the repository-relative path.
- A waiver with no `reason`, or past `expires`, is ignored. The report lists ignored waivers and waivers that match no hit (fixed: remove them) under "Waivers to tidy".
- A waived hit still shows, marked as waived. Waivers are a decision by the application owner, not by Claude: propose them, do not write them on your own.

## Workflow

Copy this checklist and tick it off:

```
- [ ] 1. Folder confirmed; output folder outside the client repository
- [ ] 2. scan: read the summary line and the report (.md or .html)
- [ ] 3. Triage block hits first, then warn; spot-check K-sourced hits in the code
- [ ] 4. Fix by area (fix guide below; explain <id> for detail); on a copy, never the client original
- [ ] 5. Agree waivers for what stays, with a reason and an owner
- [ ] 6. gate: rerun with --gate --waivers until it passes
- [ ] 7. dockerfile: the Dockerfile passes too; the checklist items have an answer
```

- **Application already on .NET 5+:** this skill is the whole job. Fix, then build and run the image (non-root, port 8080, `/health` answers).
- **.NET Framework before a port:** scan once to size the Linux work separately from the framework port. Many hits (System.Web, legacy csproj) disappear with the port. Rerun after it.
- **After a porting engine (AWS Transform, DevTx):** run this scan as well. AWS Transform's Linux readiness report and `NextSteps.md` list what it could not fix; they are a starting list, not a gate.

## Reading the report

- **PASS**: no open blocking hit. Warn and info hits are reviewed, not gated.
- **Block**: fails the build, startup or a common path on Linux. **Warn**: behaves differently or fails on some paths. **Info**: verify.
- Sections: summary by area; checks that hit (what breaks, fix); up to 25 locations per check (all of them are in the JSON); waivers to tidy; the checklist of checks a person confirms; sources.
- Detail on check types, filters and what AWS Transform and DevTx do and do not cover: [reference/linux-readiness.md](reference/linux-readiness.md).

## Fix guide by area

One line per idea; the related playbooks have the detail.

**Build, project and packaging** (`LNX-BLD-*`)
- Convert to SDK-style projects (`dotnet build` on Linux); no `-windows` TFM, WinForms/WPF or Windows RID in projects that run in the container.
- Web Site projects (no project file) become Web Application projects first.
- Replace Windows-only packages; GAC references get a `PackageReference` or a `HintPath`; build events use `dotnet` or MSBuild tasks, not `xcopy`/`cmd`.
- Private feeds must be reachable from the Linux build with credentials (CodeArtifact); turn on CA1416 as an error.

**File system and paths** (`LNX-FS-*`)
- Letter case matters: make every reference match the file on disk; rename with `git mv`.
- `Path.Combine`/`Path.Join`, never `"\\"`; no drive letters, UNC paths or `%VARS%`: paths come from configuration.
- Nothing writes next to the binaries; writable paths are mounted volumes (EFS, S3 for shared files). Scripts: LF endings and the executable bit.

**Time zones** (`LNX-TZ-*`)
- The container clock is UTC: decide each `DateTime.Now`/`Today` (business zone conversion or `UtcNow`).
- Prefer IANA IDs; `TimeZoneInfo.TryConvertWindowsIdToIanaId` for stored Windows IDs; the image needs tzdata and ICU.

**Globalization and culture** (`LNX-CUL-*`)
- ICU, not NLS: ordinal comparisons for identifiers and keys, invariant culture for parsing and formatting, request culture for users.
- Invariant mode only for apps proven not to need culture or time-zone data; otherwise ICU in the image.

**Encodings, line endings and text** (`LNX-ENC-*`)
- Register `CodePagesEncodingProvider` before `GetEncoding(1252)`; explicit encodings, since `Encoding.Default` is UTF-8.
- Accept `\n` and `\r\n` on input; `.gitattributes` keeps hashed and signed files byte-stable.

**Processes, shell, console and signals** (`LNX-PROC-*`, `LNX-CON-*`)
- No `cmd.exe`, `powershell.exe`, `.exe` names or shell-opened documents: a library call, or a Linux tool installed in the image on purpose.
- Honour SIGTERM through the generic host and `CancellationToken`; exec-form `ENTRYPOINT`.

**Environment, identity and user** (`LNX-ENV-*`)
- Environment variable names are case-sensitive; hierarchical keys use `__`.
- No Windows variables, no logic keyed on machine name, no writes to `/root` or the home folder of a user that is not there.

**Cryptography and certificates** (`LNX-CRY-*`)
- DPAPI, CNG and CSP become ASP.NET Core Data Protection with keys persisted outside the container (SSM or S3 + KMS); `RSA.Create()`, `Aes.Create()`.
- Certificates from files or Secrets Manager, readable by UID 1654; private CAs added to the image trust store.

**Authentication and identity** (`LNX-AUTH-*`)
- Windows authentication becomes OIDC/SAML from an identity provider, or Negotiate with Kerberos (keytab, `krb5.conf`), or the app stays on Windows (a recorded decision).
- Integrated security to SQL becomes SQL or IAM authentication with the secret in Secrets Manager; AD lookups use `System.DirectoryServices.Protocols` with `libldap`.

**Databases** (`LNX-DATA-*`)
- No LocalDB, named instances, `.`/`(local)`, `AttachDbFilename`, Jet/ACE or unmanaged ODP.NET; server and driver names from configuration.
- MSDTC, SQL CLR, FILESTREAM, `xp_cmdshell` and server-side file paths need a redesign; check collation and error numbers if the database changes too.

**Networking** (`LNX-NET-*`)
- `HttpClient` via `IHttpClientFactory`, not `WinHttpHandler`/`ServicePointManager`; TLS 1.2+; certificate validation on.
- Proxies from `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`; no UDP broadcast discovery, hosts-file edits or port 25; WCF net.tcp needs CoreWCF or a redesign.

**Interprocess communication** (`LNX-IPC-*`)
- Named pipes, named mutexes and memory-mapped files across processes become in-process primitives, or a distributed lock or queue across tasks.

**Windows-only APIs** (`LNX-API-*`)
- Registry → configuration; EventLog → stdout logs; WMI → `/proc` or nothing; performance counters → `System.Diagnostics.Metrics`; System.Drawing → SkiaSharp or ImageSharp with fonts in the image.
- COM, COM+, MSMQ, remoting, WF and P/Invoke into Windows DLLs need a managed replacement or a decision.

**Web platform and IIS hosting** (`LNX-WEB-*`, `LNX-HOST-*`)
- System.Web residue ports to ASP.NET Core; IIS modules, URL rewrite and app pool identities move to middleware, the ALB and task roles.
- Kestrel listens on 8080; `UseForwardedHeaders` behind the ALB; Windows services become `BackgroundService` with the generic host.

**Containers and images** (`LNX-CTR-*`)
- Multi-stage build; final stage `aspnet`/`runtime` (never `sdk`), pinned tags, `USER $APP_UID`, a `.dockerignore`, no secrets or PFX in layers.
- Linux base images only; build for the ECS/EKS architecture (`--platform linux/amd64` or `linux/arm64`); fonts, ICU, tzdata as the app needs.

**Configuration and secrets** (`LNX-CFG-*`)
- Secrets to Secrets Manager or Parameter Store, read through `IConfiguration`; protected config sections and config transforms do not apply in containers.

**Logging, performance, GC and runtime** (`LNX-LOG-*`, `LNX-PERF-*`)
- Structured logs to stdout (CloudWatch through the awslogs driver); no Event Log or file paths.
- Set container memory and CPU limits; GC and thread pool follow them.

**Scheduling, messaging, serialization** (`LNX-SCH-*`, `LNX-MSG-*`, `LNX-SER-*`)
- Task Scheduler becomes EventBridge Scheduler or ECS scheduled tasks; MSMQ becomes SQS; timers in web processes run once per task.
- BinaryFormatter and other legacy formatters become System.Text.Json or a contract serializer; no `TypeNameHandling`.

**CI/CD and tests** (`LNX-CI-*`)
- Build and test on a Linux runner with `dotnet` and `pwsh`; `.gitattributes`; `docker buildx --platform`; tests free of drive letters and LocalDB.

## Related reading

Copied from the dotnet-modernization skill's playbooks; read the one for the area you are fixing:
- [reference/related/linux-and-containers.md](reference/related/linux-and-containers.md): file system, processes, environment, the image (sample Dockerfile, health check, native dependencies, architecture).
- [reference/related/time-and-culture.md](reference/related/time-and-culture.md): UTC containers, zone IDs, ICU culture, encodings and line endings.
- [reference/related/windows-only-apis.md](reference/related/windows-only-apis.md): the replacement table for Windows-only features, desktop app options.
- [reference/related/auth.md](reference/related/auth.md): Forms auth and machineKey, Windows authentication and AD, integrated security.
- [reference/linux-readiness.md](reference/linux-readiness.md): check types, area counts, what AWS Transform and DevTx cover, sources.

## Relation to the other skills

- **migration-assessment** runs this scanner per repository during an assessment (`--all`, output to `assessment/linux/<repo>`); hits feed the estimate.
- **dotnet-modernization** runs it as the `linux` gate of `verify.py` after a port and fixes hits by playbook.
- All three skills ship the **same** `linux_readiness.py`, `_mdhtml.py` and `data/linux_readiness.json`. A change to one is copied to the other two in the same commit.

## Maintaining this skill

- Changes are additive: never drop a check, rule detail or lesson without the owner's say-so.
- One rule per catalogue row: `id` (`LNX-<AREA>-<NAME>`), `area`, `level`, `what`, `detect`, `fix`, `sources`, `patterns`, `automated`, optional `check` and filters; `tuned: true` once refined against real code. A new check without a cited page gets source `K`.
- After a change: `selftest.py`; a real clean .NET 10 app (`dotnet new webapi`, `mvc`, `worker`, `blazor` plus the sample Dockerfile) must have no block or warn hit; a legacy repository must fail with secrets masked; spot-check the ten busiest rules. Then copy the files to the other two skills.
- Test prompts and expected behaviour: [evals/evals.md](evals/evals.md).
