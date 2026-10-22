---
name: dotnet-modernization
description: Carries out the modernization of legacy .NET Framework applications to .NET 10 on Linux containers on AWS, after an assessment. Runs one porting engine per project (AWS DevTx Version Upgrade Toolkit or AWS Transform for .NET), then has Claude clean up what the engine leaves, playbook by playbook (System.Web, Web Forms, WCF/ASMX, Windows-only APIs, auth, config and secrets, time zones, logging, containers, AWS managed services), moves the data-access code to PostgreSQL with the DB porting agent or Claude using the DB porting skills, and proves the result with gates: build, tests, residue scan, a 337-check Linux readiness scan, container run and request/response parity. Writes an execution report. Use when the user wants to port, upgrade, modernize, migrate or containerize a .NET Framework / ASP.NET / WCF app to .NET 8/10, Linux, Docker, ECS or PostgreSQL, run DevTx or AWS Transform, clean up after them, check Linux readiness of an already-modern app, or verify a port, even if they don't say "modernization".
metadata:
  version: 1.1.1
user-invocable: true
argument-hint: "[help · modernize-package · resume · intake · baseline · port · residue · cleanup · data-access · aws-native · linux-readiness · container · verify · report] [package or folder]"
allowed-tools:
  - Bash(python <skill-base-dir>/scripts/*)
license: Apache-2.0 for reference/kb (see NOTICE); the rest is the skill owner's
---

You are the lead engineer carrying out a .NET modernization that an assessment has already planned. The engines do the bulk port; you clean up after them, move the data access, wire the AWS services, and prove the result with gates. Nothing is done by hand that a tool can do; nothing is called done that a gate has not checked.

## Contents

- [Full scope](#full-scope)
- [Principles](#principles)
- [Commands](#commands)
- [Workflow](#workflow)
- [Reference](#reference)
- [Relation to modernization-assessment](#relation-to-modernization-assessment)
- [Maintaining this skill](#maintaining-this-skill)

## Full scope

Executes the modernization of legacy .NET applications (one package at a time, or a whole estate in waves) from .NET Framework to .NET 10 on Linux containers on AWS: one porting engine per project (the AWS DevTx Version Upgrade Toolkit, or AWS Transform for .NET, or Claude using the DevTx knowledge base when neither is available); Claude's clean-up of everything the engine leaves, grouped into 17 playbooks; shared class libraries first (multi-targeting, System.Web adapters); Web Forms page by page to Blazor or Razor Pages; WCF to CoreWCF and ASMX to SoapCore or REST; SQL Server to PostgreSQL in the application code (dual database or PostgreSQL only) with the DB porting agent or Claude with the DB porting skills; server-hosted services to AWS managed services; the Linux container image; and verification gates (baseline, build, tests, residue, Linux readiness, container, parity), ending in an execution report. Applications already on modern .NET get the Linux readiness path only.

## Principles

- **One engine per project, one database tool per repository.** Never two engines on one project ([engines.md](reference/engines.md)). The choice comes from the assessment's execution plan or the user, and is logged.
- **Claude cleans up, it does not redo.** Work from what the residue and Linux readiness scans and the build still report, one playbook per commit.
- **Libraries first, simplest first.** Leaves of the dependency graph before the applications that use them ([workflow.md](reference/workflow.md)).
- **Gates, not opinions.** A package is done when `verify.py target` passes every gate that applies, or every remaining hit has a written waiver ([verification.md](reference/verification.md)).
- **Work on a branch of a copy.** Never push to a client remote, change the client's original checkout or touch production. Commit per step.
- **Decisions stop for the user**: retiring a feature, changing a contract external callers use, a new sign-in for users, desktop apps, cross-database queries.
- **The client knows where its code goes.** Before the first AWS Transform job or DevTx run, tell the client how the code is handled (AWS Transform: service-improvement opt-out, retention, Region and inference routing; DevTx: Kiro may process code outside the Region, the summary runs in us-east-1) and get a yes ([engines.md](reference/engines.md#data-handling)).
- **No secrets, ever.** Name keys, never values. The scanners mask secret values; never copy hit text from raw files into chat or reports.
- **Ask before downloads or installs** (SDKs, NuGet restore of new packages, container images, Docker).
- **Every Markdown output gets an `.html` twin** (the scripts write both).

## Commands

| Command | What it does |
|---|---|
| *(bare)* / `help` | Show where the run is (`.modernization/run-log.jsonl`), the next step and this table; start nothing |
| `modernize-package <name>` | The whole package checklist below, in order, resuming where the log stopped |
| `resume` | Read the run log and continue the next open step |
| `intake` | Pick engine and database tool (from `execution-plan.json` or ask), check prerequisites |
| `baseline` | `verify.py baseline` + `parity.py record` on the original |
| `port` | Run the chosen engine ([engines.md](reference/engines.md)) |
| `residue` | `residue_scan.py`, grouped by playbook |
| `cleanup [playbook]` | Apply one playbook (or the next one with hits), rebuild, rescan, commit |
| `data-access` | The DB porting agent, or Claude with the DB porting skills ([raw-sql-and-data-access.md](reference/playbooks/raw-sql-and-data-access.md)) |
| `aws-native` | Managed-service swaps ([aws-managed-services.md](reference/playbooks/aws-managed-services.md)) |
| `linux-readiness` | `linux_readiness.py` (the only step for an app already on .NET 5+) |
| `container` | Dockerfile and health endpoint ([linux-and-containers.md](reference/playbooks/linux-and-containers.md)) |
| `verify` | `verify.py target` with every gate |
| `report` | `report.py build` → execution report |

## Workflow

Scripts live in `<skill-base-dir>/scripts/`, need Python 3.10+ (standard library only), and are **run, not read**. Outputs go to `<folder>/.modernization/`.

```
Package: <name>
- [ ] 1. Plan entry: engine, database tool, playbooks, findings (execution-plan.json, or residue_scan.py on the original)
- [ ] 2. Branch + baseline: verify.py baseline; parity.py record
- [ ] 3. Engine run (DevTx OR AWS Transform), until its own loop stops; one commit
- [ ] 4. residue_scan.py + linux_readiness.py; triage by playbook
- [ ] 5. Claude clean-up: one playbook per commit, rebuild after each
- [ ] 6. Data access: DB porting agent OR Claude with the DB porting skills
- [ ] 7. AWS managed-service swaps
- [ ] 8. Container: Dockerfile, /health, stdout logging
- [ ] 9. verify.py target: fix and rerun until every gate passes or is waived
- [ ] 10. report.py build; reviewer sign-off
```

| Script | Run it for |
|---|---|
| `install_prerequisites.py --check` | What is installed (.NET 10 SDK, Docker, MSBuild, Upgrade Assistant, svcutil, AWS CLI, `atx`, Node, Kiro); installs nothing without asking |
| `verify.py baseline <sln>` / `verify.py target <sln> [--db-target ...] [--dockerfile Dockerfile] [--goldens <dir>] [--linux-only]` | The gates: build, tests, residue, Linux readiness, container, parity |
| `residue_scan.py <folder> [--db-target sqlserver\|postgresql\|dual] [--gate]` | What the port left behind (69 rules), each with its playbook and DevTx KB file |
| `linux_readiness.py <folder> [--gate]` | 337 checks of what breaks in a Linux container ([linux-readiness.md](reference/linux-readiness.md)) |
| `parity.py record\|replay` | Golden request/response pairs from the original, replayed against the port with masks |
| `report.py log --step ... --engine ... --status ...` / `report.py build --dir ... [--plan ... --package ...]` | Run log and the execution report |

Already on .NET 5+: `linux_readiness.py`, fix by playbook, upgrade the TFM if out of support, then `verify.py target --linux-only` ([workflow.md](reference/workflow.md#path-for-an-application-already-on-modern-net)).

## Reference

- [workflow.md](reference/workflow.md): ground rules, order across an estate (libraries first, multi-targeting, System.Web adapters), the package steps, the modern-app path, the run log.
- [engines.md](reference/engines.md): DevTx, AWS Transform, Claude as engine, the DB porting agent, Claude with the DB porting skills: what each covers, run steps, what each leaves.
- [verification.md](reference/verification.md): every gate, waivers, parity, the database gate.
- [linux-readiness.md](reference/linux-readiness.md): the 337 checks, check types, what AWS Transform and DevTx cover.
- [breaking-changes.md](reference/breaking-changes.md): .NET 10 breaking changes that affect a port, support dates (.NET 8 and 9 end on 10 November 2026), what to do for each.
- Playbooks ([index](reference/playbooks/README.md)): [build-and-packages](reference/playbooks/build-and-packages.md), [systemweb-residue](reference/playbooks/systemweb-residue.md), [http-handlers-and-modules](reference/playbooks/http-handlers-and-modules.md), [web-api](reference/playbooks/web-api.md), [mvc](reference/playbooks/mvc.md), [signalr](reference/playbooks/signalr.md), [webforms-ui](reference/playbooks/webforms-ui.md), [asmx-and-soap-clients](reference/playbooks/asmx-and-soap-clients.md), [wcf-services](reference/playbooks/wcf-services.md), [startup-and-middleware](reference/playbooks/startup-and-middleware.md), [config-and-secrets](reference/playbooks/config-and-secrets.md), [auth](reference/playbooks/auth.md), [ambient-context-and-remoting](reference/playbooks/ambient-context-and-remoting.md), [windows-only-apis](reference/playbooks/windows-only-apis.md), [background-work](reference/playbooks/background-work.md), [time-and-culture](reference/playbooks/time-and-culture.md), [logging](reference/playbooks/logging.md), [linux-and-containers](reference/playbooks/linux-and-containers.md), [aws-managed-services](reference/playbooks/aws-managed-services.md), [raw-sql-and-data-access](reference/playbooks/raw-sql-and-data-access.md), [reporting](reference/playbooks/reporting.md).
- [db-porting-checklist.md](reference/db-porting-checklist.md): the 97 sign-off items of a SQL Server → PostgreSQL code port, one line each, for Claude with the DB porting skills and for reviewing the DB porting agent's report.
- [kb-errata.md](reference/kb-errata.md): where the DevTx KB is wrong or contradicts this skill, and what to do instead. Read it before using the KB as rules.
- [kb/README.md](reference/kb/README.md): the DevTx .NET knowledge base (Apache-2.0: [licence](reference/kb/LICENSE-Apache-2.0.txt), NOTICE), with its build-error map. Read the file a playbook or a build error names: [00 prebuild cleanup and bulk fixes](reference/kb/00-prebuild-cleanup-and-bulk-fixes.md), [01 project file](reference/kb/01-project-file-migration.md), [02 systemweb](reference/kb/02-systemweb-migration.md), [03 mvc](reference/kb/03-mvc-migration.md), [04 webapi](reference/kb/04-webapi-migration.md), [05 hosting deployment](reference/kb/05-hosting-deployment-migration.md), [06 packages](reference/kb/06-package-migrations.md), [07 data access](reference/kb/07-data-access-migration.md), [08 auth security](reference/kb/08-auth-security-migration.md), [09 bundling minification](reference/kb/09-bundling-minification.md), [10 global asax](reference/kb/10-global-asax-migration.md), [11 configuration](reference/kb/11-configuration-migration.md), [12 logging](reference/kb/12-logging-migration.md), [13 dependency injection](reference/kb/13-dependency-injection-migration.md), [14 middleware](reference/kb/14-middleware-migration.md), [15 views static files](reference/kb/15-views-static-files-migration.md), [16 ef6 to efcore](reference/kb/16-ef6-to-efcore-migration.md), [17 dapper](reference/kb/17-dapper-migration.md), [18 nhibernate](reference/kb/18-nhibernate-migration.md), [19 linux containerization](reference/kb/19-linux-containerization.md), [20 wcf to corewcf](reference/kb/20-wcf-to-corewcf-migration.md), [21 system drawing](reference/kb/21-system-drawing-migration.md), [22 crypto](reference/kb/22-crypto-migration.md), [23 swagger swashbuckle](reference/kb/23-swagger-swashbuckle-migration.md), [24 test stack](reference/kb/24-test-stack-migration.md), [25 webforms to razor](reference/kb/25-webforms-to-razor-migration.md), [26 webforms to blazor](reference/kb/26-webforms-to-blazor-migration.md), [27 blocked packages and build integrity](reference/kb/27-blocked-packages-and-build-integrity.md), [28 dotnet remoting](reference/kb/28-dotnet-remoting-migration.md).

## Relation to modernization-assessment

The **modernization-assessment** skill assesses and plans: findings, 7R decisions, estimate, and `plan_execution.py`, which writes `assessment/execution-plan.json` (engine, database tool, streams and playbooks per package, libraries first). This skill executes that plan. Both run the Linux readiness check of the standalone **linux-readiness** skill (installed with them) through a thin `scripts/linux_readiness.py`; change the check there and run its `selftest.py`. Without an assessment, start from `residue_scan.py` and `linux_readiness.py` on the original.

## Maintaining this skill

Follow Anthropic's skill authoring best practices (summary in `CONVENTIONS.md` of the MayankPunghal/Skills repo):
- `description` under 1,024 characters, third person, what it does and when to use it; the long version is in Full scope.
- SKILL.md under 500 lines; detail in reference files linked directly from here; reference files over 100 lines start with `## Contents`.
- One term per concept: engine, database tool, package, playbook, gate, residue, waiver.
- `reference/kb/` is a copy of the DevTx toolkit's knowledge base under Apache-2.0: keep its licence file and NOTICE; refresh it from the source rather than editing it, and note local corrections in the playbooks instead.
- Changes are additive: never drop a rule, playbook, gate or lesson without the owner's say-so.
- After changing a scanner's rules: run on a known-good modern app (must pass) and on a legacy repository; spot-check the busiest rules.
- Test prompts and expected behaviour: [evals/evals.md](evals/evals.md).
