# Engines: who does which part of the work

One porting engine per project, one database tool per repository, Claude for everything the engine does not cover. This file says what each tool does, when to pick it, how to run it and what it leaves behind.

## Contents

- [Choosing](#choosing)
- [DevTx Version Upgrade Toolkit](#devtx-version-upgrade-toolkit)
- [AWS Transform for .NET](#aws-transform-for-net)
- [Claude as the porting engine](#claude-as-the-porting-engine)
- [DB porting agent](#db-porting-agent)
- [Claude with the DB porting skills](#claude-with-the-db-porting-skills)
- [What every engine leaves to Claude](#what-every-engine-leaves-to-claude)
- [Prerequisites](#prerequisites)

## Choosing

| Job | Pick one | Default | Pick the other when |
|---|---|---|---|
| Port the projects to .NET 10 | DevTx toolkit **or** AWS Transform | DevTx | AWS Transform: the client has it approved, the estate is large, or Web Forms UI should go to Blazor Server automatically |
| Same, neither available | Claude, using the DevTx knowledge base (`kb/`) as its rules | — | — |
| SQL Server → PostgreSQL code path | The DB porting agent **or** Claude with the DB porting skills | The DB porting agent (dual database) | Claude: the agent is not approved, has no budget, or the repository is too complex for its phases |
| Already on .NET 5+ | No engine: Linux readiness only | — | — |

Never run two engines on one project: their changes overlap, and nobody can tell which change came from where. The choice is recorded in `execution-plan.json` (`port_engine`, `db_tool`) and in every run-log entry.

Work each engine carries out, in the assessment's work-item terms (the rest is Claude clean-up):

| Work item | DevTx | AWS Transform |
|---|---|---|
| SDK-style projects, Linux CI build | yes (KB 01, 27) | yes |
| Engine run and review | yes | yes |
| CallContext / remoting ambient context | yes (KB 28) | **no** |
| Packages | yes (KB 06) | yes |
| Web Forms UI | partly (KB 25, 26: guidance, the model rewrites) | yes, to Blazor Server, with an unsupported list |
| Linux container and health check | yes (KB 19; fix its samples, see below) | **no** |
| HTTP handlers, ASMX entry points, SOAP clients, Windows-only APIs, config and secrets | Claude | Claude |

## DevTx Version Upgrade Toolkit

**What it is.** An AWS-hosted web app (Apache-2.0, AWS sample) that runs one upgrade per container: Microsoft .NET Upgrade Assistant for the mechanical step, then Kiro CLI (default model Claude Sonnet) with the 28-file .NET knowledge base copied in [kb/](kb/README.md), told to build and fix until the build has zero errors.

**Run steps (per iteration):**
1. Module config: `targetVersion` (6, 7, 8 or 10; anything else silently becomes net8.0, so always set 10), `modulePath`, optional custom build script, `transformEngine` = `DOTNET_UPGRADE_ASSISTANT_WITH_Q` (AI) or `DOTNET_UPGRADE_ASSISTANT` (no AI).
2. Start: the backend clones the repository, creates `iteration-N`, starts the transformer container.
3. Setup: saves the original project files, resolves the solution, runs an initial build (skipped for .NET Framework projects, which cannot build on Linux).
4. Upgrade Assistant per project (`upgrade --targetFramework net10.0 --non-interactive --operation Inplace`). A failure is logged and **does not stop** the run.
5. Kiro repair loop: pre-build clean-up (KB 00), build, fix by the KB's error-code map, SDK-style projects, packages, System.Web, MVC/Web API, EF6, auth, Global.asax and config, WCF, System.Drawing, crypto, Web Forms, remoting; repeat until zero errors. There is **no iteration cap or timeout**.
6. Optional additional prompt (`kiro-cli chat --resume`), then `summary.md` with "Next steps".
7. The only automatic gate: `dotnet build`, then `dotnet test --no-build` ("no test available" counts as a pass).
8. Commit to `<branch>-itr-N`, report.json (project comparison, credits, estimated time saved), and on success a PR into the upgrade branch.

**Outer loop.** Human-driven: review the PR and `summary.md`, then start the next iteration with an additional prompt for what is left.

**Watch out:**
- Kiro runs with `--trust-all-tools` inside the container: keep the container away from client secrets and networks.
- Kiro's exit status is not checked; a run can "complete" with a half-finished build only because the gate catches it.
- No database work at all (no SQL conversion, no procedure translation).
- KB 19's container samples need fixing before use: no `USER`, curl health check, secrets in `ENV` ([linux-readiness.md](linux-readiness.md#what-aws-transform-and-devtx-do-and-do-not-cover)).

Log it: `report.py log --step port --engine devtx --status done --note "itr N, build green, summary next steps: ..."`.

## AWS Transform for .NET

**What it is.** AWS's managed agentic porting service: .NET Framework 3.5+, .NET Core 3.1 and .NET 5-10 to .NET 8 or 10 (or .NET Standard for libraries), C# and VB.NET. Project types: class libraries, console, MVC, Web API, Web Forms, WCF, ASMX, unit tests, WinForms/WPF, Xamarin. Surfaces: web app, Visual Studio extension, MCP server.

**Run steps:**
1. Connect the repository (Azure Repos, Bitbucket, GitHub, GitLab) through a connector, or open the solution in Visual Studio.
2. Assess: it builds a plan; review and edit it (which projects, target, Web Forms UI porting on or off).
3. Upload any private NuGet packages it cannot resolve.
4. Transform: it ports, builds in its remote build environment and runs unit tests.
5. Review and accept the changes on a new branch.
6. Read its report and the **Next Steps** document, including the **Linux readiness report** (CSV in Visual Studio: project, file, description, issue, recommendation). Every item becomes Claude clean-up.

**Does not handle:** `.svc`, `.ashx`, `.asmx` and service/web references in UI porting; mixed `.aspx` and `.cshtml`; third-party UI controls; Web Site projects without a project file; Win32 DLLs without a core-compatible build; ViewState and page JavaScript behaviour (undocumented: test every page); MongoDB driver upgrades (undocumented). Web Forms to React is out of scope (AWS Transform custom).

Log it: `report.py log --step port --engine aws-transform --status done --note "job <id>, N projects accepted, next-steps items: ..."`.

## Claude as the porting engine

Only when neither DevTx nor AWS Transform is available. Claude follows the DevTx loop itself, on a branch of the copy:
1. Read [kb/README.md](kb/README.md) (error-code map) and KB 00 (pre-build clean-up).
2. Convert the projects to SDK-style and set the target framework (libraries first, see [workflow.md](workflow.md)).
3. Build; for each error, find the KB file and the playbook that covers it, fix, rebuild. Commit after each project builds.
4. Stop and ask when a fix needs a decision (retire a feature, change a contract external callers use).
5. Then the normal clean-up, residue scan and gates.

Ask before installing anything (SDKs, Upgrade Assistant). Upgrade Assistant is deprecated by Microsoft; use it only as an optional first mechanical pass.

## DB porting agent

**What it is.** SourceFuse's porting agent for SQL Server → PostgreSQL in the application code: dual database (both engines behind one provider switch) or PostgreSQL only. It has **no T-SQL transpiler**: the model converts, guided by references and trigger regexes; deterministic scripts inventory the code, build the database contract, lint the result and score it ("scripts decide, the model judges"). It never connects to a database and runs no tests.

**Phases:**

| Phase | What happens | Output |
|---|---|---|
| 0 Initialize | Run settings: provider switch key (default `Data:Provider`), PostgreSQL version (default 16), identifier style (default `preserve`), schema changes allowed (default no) | run-config.json |
| 1 Analyze (read-only) | Classifies every file: data access, config, schema, unaffected; finds the triggers | analysis.json |
| 2 Plan (read-only) | The **database contract**: for every database object its PostgreSQL name, kind (procedure, table function, scalar function, refcursor function), call form and argument order | plan.md, db-contract.json |
| 3 Approval (human) | Approve, reject, or amend and re-plan | — |
| 4 Execute | The only phase that edits code; batches in dependency order, build after every 8 files | change log |
| 5 Validate | Build, lints (PostgreSQL calls against the contract, refcursor disposal, parameter prefixes, SQL resource parity), the 97-item checklist and its score | port report, DB objects inventory |
| Iterate | Fixable failures go back to Execute, at most 2 passes | — |
| 6 Branch and PR | Commit, push, PR | PR |

**Guardrails worth keeping in mind:** SQL Server behaviour unchanged; no logic changes; no lossy type without a flag; no secrets; provider branches only inside the seams; no renames beyond the mandated ones; database objects are never authored by the agent (the DB team owns them); every PostgreSQL call matches the contract exactly; SqlBulkCopy becomes a bulk-insert seam over COPY.

A high checklist score is not proof the application works on PostgreSQL: QA tests both engines.

Log it: `report.py log --step db --engine db-agent --status done --note "score N, open items: ..."`.

## Claude with the DB porting skills

When the DB porting agent is not approved, has no budget, or the repository is too complex for its phases. Claude runs the same phases by hand with the same artefacts, so the result is reviewed the same way:
- The agent's phase skills (`dual-db-port`: initialize, analyze, plan, approval, execute, validate, git; `pg-only-port` for PostgreSQL only) live in the agent's own repository (its `skills/` folder). Install or open them from there; this skill does not copy them (their licence is being confirmed).
- The code-side rules are summarised in [playbooks/raw-sql-and-data-access.md](playbooks/raw-sql-and-data-access.md): the seams, the contract, refcursors, multi-result sets, OUTPUT and return values, TVPs, bulk copy, identity, transactions, error numbers, dates, identifiers, and the checklist groups.
- The approval step stays human: show the contract and the plan, wait for a yes.
- Costs more hours than the agent (the assessment adds them when `db_tool` is `claude`).

Log it with `--engine claude` and the note "DB porting skills".

## What every engine leaves to Claude

Whatever the engine, Claude:
1. runs `residue_scan.py` and `linux_readiness.py` on the engine's output and works through the hits playbook by playbook ([playbooks/README.md](playbooks/README.md));
2. does the AWS managed-service swaps ([playbooks/aws-managed-services.md](playbooks/aws-managed-services.md));
3. writes the Dockerfile, health endpoint and stdout logging when the engine did not;
4. runs `verify.py target` until every gate passes or every remaining hit has a written waiver.

## Prerequisites

`python scripts/install_prerequisites.py --check` lists what is installed: Python, git, the .NET 10 SDK, Docker (container gate), MSBuild (baseline of .NET Framework code), the .NET tools, the AWS CLI, the AWS Transform CLI (`atx`, for AWS Transform custom), Node.js (DB porting agent scripts) and Kiro CLI (local DevTx-style runs). It installs nothing without asking.
