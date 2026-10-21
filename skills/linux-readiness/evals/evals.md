# Evaluations for linux-readiness

Run each prompt in a fresh session, first without the skill (baseline), then with it. Record the difference in the baseline log.

## Contents

- [Triggering and routing](#triggering-and-routing)
- [Behaviour checks](#behaviour-checks)
- [Script checks](#script-checks)
- [Baseline log](#baseline-log)

## Triggering and routing

### Bare invocation
Prompt: `/linux-readiness`
Should trigger: yes
Done looks like: asks for (or detects) the folder, says whether a report exists in the output folder, recommends `scan`, shows the command table; nothing runs.

### Already on modern .NET
Prompt: "This API is on .NET 8. Will it run in a Linux container on ECS Fargate?"
Should trigger: yes
First file Claude should open: none before running `linux_readiness.py <folder> --out <dir>`
Done looks like: scan run with `--out` outside the repository; PASS/FAIL line quoted; block hits explained with the fix guide; no porting engine suggested.

### Before a port
Prompt: "We have a .NET Framework 4.8 Web Forms app. What would break on Linux?"
Should trigger: yes
Done looks like: scan run; System.Web and legacy csproj hits are called out as port work that disappears with the port; the rest (paths, case, time zones, auth, secrets) sized as Linux work; secret values masked in every quote.

### Dockerfile only
Prompt: "Can you check this Dockerfile for our .NET service?" (one Dockerfile path)
Should trigger: yes
Done looks like: `--dockerfile-only` on the file; findings on base image, `USER`, final stage, tags, `.dockerignore`, secrets in `ENV`, exec form; no full code scan unless asked.

### Explain a check
Prompt: "Why did LNX-CTR-USER-MISSING fire, and is it really a problem?"
Should trigger: yes
Done looks like: `--explain LNX-CTR-USER-MISSING` output summarised (what, regex, fix, source URL); a `USER $APP_UID` fix proposed.

### Gate with waivers
Prompt: "Make our pipeline fail when anything blocks Linux, but accept the registry read in the legacy startup for now."
Should trigger: yes
Done looks like: a `waivers.json` entry proposed with rule, path, reason, owner and expiry, for the user to approve; `--gate --waivers` command for the pipeline; explains that waivers without a reason or past expiry are ignored.

### Should not trigger (assessment)
Prompt: "Assess these 40 repositories and estimate the effort to move them to AWS."
Should trigger: no (migration-assessment does this)

### Should not trigger (port)
Prompt: "Port this .NET Framework solution to .NET 10 with AWS Transform."
Should trigger: no (dotnet-modernization does this)

### Should not trigger (small)
Prompt: "Fix this nullable warning in my .NET 8 project."
Should trigger: no

## Behaviour checks

| Check | Pass when |
|---|---|
| Read-only | No file in the scanned repository is changed; `--out` points outside it |
| Secrets | No secret value appears in chat, reports or commits; hits are quoted from the report, not from raw files |
| Evidence | Each claim names the check id and the file:line from the report; K-sourced hits are confirmed in the code first |
| Levels | Only block hits are called blockers; warn and info are "review" |
| Waivers | Proposed, never written without the user's approval; each has a reason and an owner |
| HTML twin | Every Markdown summary Claude writes has its `.html` |
| Windows Python | Commands use `py -X utf8` on Windows |

## Script checks

| Script | Fixture | Expected |
|---|---|---|
| `selftest.py` | Built-in clean .NET 10 and legacy .NET 4.8 fixtures | PASS: clean passes the gate with no block or warn hit (also `--dockerfile-only`); legacy fails with the 28 expected checks (including 8 added by the exhaustive-list pass); no fake secret in JSON, MD or HTML; waiver rules hold; `--explain` works |
| `linux_readiness.py` | Real `dotnet new webapi`, `mvc`, `worker`, `blazor`, `classlib`, `xunit` (net10.0) in one solution, each app with the sample Dockerfile (`USER $APP_UID`), plus `.dockerignore` and `.gitattributes` | PASS, no block hit; warns left: `LNX-TZ-LOCAL-NOW` (the templates' own `DateTime.Now`) and `LNX-HOST-FORWARDED-HEADERS` (the templates do not configure forwarded headers, which an ALB needs); info: `LNX-CTR-FLOATING-OS-TAG` |
| `linux_readiness.py` | A legacy repository (Web Forms or MVC 5 on .NET Framework) | FAIL with System.Web, legacy csproj; any secret masked (`Password=***`) |
| `linux_readiness.py --dockerfile-only` | One Dockerfile below the repository root, `.dockerignore` at the root | `.dockerignore` found (search goes up to the folder with `.git`) |
| `linux_readiness.py --explain LNX-CTR` | none | Lists the container checks, one line each |

## Baseline log

| Date | Prompt | Without the skill | With the skill |
|---|---|---|---|
| 2026-10-21 | Script checks above | — | `selftest.py` PASS (12/12). Real `dotnet new` .NET 10 solution (6 projects, 4 Dockerfiles): PASS, 0 block, 5 warn, 8 info. eShopLegacyWebForms FAIL (61 block), Bobs Bookstore classic FAIL (81 block), eShopModernizing FAIL (1,078 block). Two large legacy client repositories: FAIL; an independent re-read of every hit line found 0 secret values in the reports (the scanner before this release showed one config secret from a `<add key=... value=...>` line). |
