> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Linux readiness catalogue research

agent a9d4869c863ed92fd

Linux readiness catalogue written: <scratchpad>\research\linux-readiness-catalogue.md

- Checks: 240 across 19 categories. 111 are already covered by an existing rule, 29 are partial, 100 are gaps. Severity: 130 block, 91 warn, 19 info.
- Gap 1, case sensitivity: FILE-CASE-MISMATCH is named in migration-assessment/references/linux-pitfalls.md but exists in neither rules.json nor any script. Razor view names, static URLs, embedded resources, assembly names and appsettings.{env}.json are unchecked.
- Gap 2, container image: port 80 vs 8080, non-root USER, read-only root filesystem (only a state-scale rule exists), ICU/tzdata/invariant mode in base images, libgdiplus, fonts, arm64 vs amd64, .dockerignore, and secrets copied into the image.
- Gap 3, time zones and culture: IANA IDs used on Windows, tzdata-less images, culture-sensitive comparisons and sorting, missing ICU, and invariant-mode switches.
- Gap 4, Windows-only plumbing: named-pipe ACLs, sockets, DNS, LocalDB, SQL CE, named instances, collation, .dll suffix probing in DllImport, and wchar_t/long marshalling.
- Under-rated: WIN-CNG-CSP is rated medium but should be high. ASP.NET Data Protection key persistence and private-CA trust have no rule.
- Host and CI: Topshelf, ALB forwarded headers, msbuild.exe/vstest/powershell.exe steps, docker --platform, .gitattributes, and script exec bits.
- AWS Transform: checks through a Linux readiness CSV and NextSteps.md. It transforms APIs, packages, config, IIS and WCF, and leaves manual Linux items, Win32 DLLs without core-compatible libraries, and web site projects without project files. The AWS docs describe no container-specific checks. Porting Assistant closed to new customers in November 2025.
- DevTx KB 19 (19-linux-containerization.md): no Linux readiness content. Defects: HEALTHCHECK uses curl, which may not exist in the image; sample passwords are hard-coded; a PFX password is set in ENV; no USER is set despite the troubleshooting advice; DOTNET_ENVIRONMENT and ASPNETCORE_ENVIRONMENT are mixed; migrations run in the entrypoint.
- Caveats: about 25 items are marked [K] (engineering knowledge, not fetched) and need verifying before any rule ships. The Microsoft time-zone page returned 404. AWS Microservice Extractor was not researched. The lift-and-shift and nonnet scan skills contain no Linux content.
- Not done: I did not create the .html companion that the user's memory rule asks for, because the task specified one file. It can be generated on request.
