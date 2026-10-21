# Engines: who does which part of the work

One porting engine per project, one database tool per repository, Claude for everything the engine does not cover. This file says what each tool does, when to pick it, how to run it and what it leaves behind.

## Contents

- [Choosing](#choosing)
- [DevTx Version Upgrade Toolkit](#devtx-version-upgrade-toolkit)
- [AWS Transform for .NET](#aws-transform-for-net)
  - [Limits and cost](#limits-and-cost)
  - [Data handling](#data-handling)
  - [Other AWS Transform agents](#other-aws-transform-agents)
- [GitHub Copilot app modernization](#github-copilot-app-modernization)
- [Claude as the porting engine](#claude-as-the-porting-engine)
- [DB porting agent](#db-porting-agent)
- [Claude with the DB porting skills](#claude-with-the-db-porting-skills)
- [What every engine leaves to Claude](#what-every-engine-leaves-to-claude)
- [Prerequisites](#prerequisites)

## Choosing

| Job | Pick one | Default | Pick the other when |
|---|---|---|---|
| Port the projects to .NET 10 | DevTx toolkit **or** AWS Transform | DevTx | AWS Transform: the client has it approved, the estate is large, Web Forms UI should go to Blazor Server automatically, or the projects are WinForms, WPF or WF (DevTx does not support them) |
| Same, the client standardises on Microsoft tooling | GitHub Copilot app modernization | — | Desktop (WinForms, WPF), Web Forms or Blazor work inside Visual Studio; not for WCF or ASMX ([below](#github-copilot-app-modernization)) |
| Same, neither available | Claude, using the DevTx knowledge base (`kb/`) as its rules | — | — |
| SQL Server → PostgreSQL code path | The DB porting agent **or** Claude with the DB porting skills | The DB porting agent (dual database) | Claude: the agent is not approved, has no budget, or the repository is too complex for its phases |
| SQL Server → Aurora PostgreSQL, schema and code in one job, PostgreSQL only | AWS Transform SQL Server modernization | — | Only when the app is already on .NET 6, 7, 8 or 10, is C#, targets Aurora PostgreSQL 15+, and the DB team accepts the generated schema and procedures ([other agents](#other-aws-transform-agents)) |
| Azure SDK code (Functions, Blob, Queue, Cosmos DB) | AWS Transform's Azure-to-AWS conversion **or** Claude | Claude ([playbooks/aws-managed-services.md](playbooks/aws-managed-services.md)) | AWS Transform: it is already the port engine for that project |
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
| Linux container and health check | **no**: the toolkit builds and tests only and writes no Dockerfile; KB 19 has samples Claude can use after fixing them (see below) | **no** in the .NET agent (a separate containerization feature exists, see [other agents](#other-aws-transform-agents)) |
| HTTP handlers, ASMX entry points, SOAP clients, Windows-only APIs, config and secrets | Claude | Claude |

## DevTx Version Upgrade Toolkit

**What it is.** An AWS-hosted web app (Apache-2.0, AWS sample) that runs one upgrade per container: Microsoft .NET Upgrade Assistant for the mechanical step, then Kiro CLI (default model Claude Sonnet) with the 29-file .NET knowledge base (00-28) copied in [kb/](kb/README.md), told to build and fix until the build has zero errors. Sources it supports: .NET Framework 4.5+, .NET Core 1.0-3.1 and .NET 5-7; targets .NET 8 or 10. It does **not** support WinForms, WPF or Windows Workflow Foundation. It never asks the user anything: every decision it takes shows only in `summary.md` and the diff, so review both.

**Run steps (per iteration):**
1. Module config: `targetVersion` (6, 7, 8 or 10; anything else silently becomes net8.0, so always set 10), `modulePath`, optional custom build script, `transformEngine` = `DOTNET_UPGRADE_ASSISTANT_WITH_Q` (AI) or `DOTNET_UPGRADE_ASSISTANT` (no AI).
   - Solution: only a root-level `.sln` name is accepted (paths are rejected). The docs say a blank field uses the first `.sln`, but the scripts upgrade every `.csproj` / `.vbproj` under the module path either way: set `modulePath` narrowly.
   - A custom build script replaces the toolkit's build, and its tests are then skipped. Build arguments from the config are never passed to `dotnet build`.
   - It forces one target framework per project: no multi-targeting, so a library that must stay `netstandard2.0` for .NET Framework callers needs Claude afterwards.
2. Start: the backend clones the repository, creates `iteration-N`, starts the transformer container.
3. Setup: saves the original project files, resolves the solution, runs an initial build. The AI engine (`DOTNET_UPGRADE_ASSISTANT_WITH_Q`) skips it when any project is .NET Framework style (they cannot build on Linux); the Upgrade Assistant-only engine always runs it and **stops** when it fails.
4. Upgrade Assistant per project (`upgrade --targetFramework net10.0 --non-interactive --operation Inplace`; version 1.0.518 is pinned in the image). A failure is logged and **does not stop** the run.
5. Kiro repair loop: pre-build clean-up (KB 00), build, fix by the KB's error-code map, SDK-style projects, packages, System.Web, MVC/Web API, EF6, auth, Global.asax and config, WCF, System.Drawing, crypto, Web Forms, remoting; repeat until zero errors. There is **no iteration cap or timeout**.
6. Optional additional prompt (`kiro-cli chat --resume`), then `summary.md` with "Next steps".
7. The only automatic gate: `dotnet build`, then `dotnet test --no-build` ("no test available" counts as a pass). Both run with `-p:WarningLevel=0`, which hides NU and CA warnings: the skill's own build gate runs without it ([verification.md](verification.md)).
8. Commit to `<branch>-itr-N`, report.json (project comparison, credits, estimated time saved), and on success a PR into the upgrade branch.
9. Artifacts per iteration: the iteration-N logs, `summary.md` and `report.json`, shown in the toolkit's web app and fetched through its API. Its **confidence score** (40% verification, 30% change size, 20% files, 10% dependencies) rates a skipped build and a run with no tests as success: it is not evidence, and the execution report never quotes it as such. Its project comparison reads `PackageReference` items and the first target framework only.

**Outer loop.** Human-driven: review the PR and `summary.md`, then start the next iteration with an additional prompt for what is left.

**Watch out:**
- It pushes `<branch>-itr-N` and opens PRs on the repository's remote. Never point it at a client remote: ask the user which remote to use before every DevTx run.
- Kiro runs with `--trust-all-tools` inside the container: keep the container away from client secrets and networks.
- Kiro's exit status is not checked; a run can "complete" with a half-finished build only because the gate catches it.
- No database work at all (no SQL conversion, no procedure translation).
- **Data egress:** per the toolkit's security notes, Kiro may process code outside the deployment's Region, and the Bedrock call that writes the summary runs in us-east-1. Tell the client before the first run, next to the AWS Transform points in [data handling](#data-handling).
- Private NuGet feeds: the `nuget.config` lines are commented out of the transformer image, so private packages fail to restore until the image is changed. Main-branch auto-tracking re-runs jobs when the branch moves: switch it off for a port.
- WCF: the toolkit's prompt steers WCF to REST or gRPC, while this skill keeps contracts with CoreWCF or SoapCore. Review its WCF output against [playbooks/wcf-services.md](playbooks/wcf-services.md).
- Deploying the toolkit: Node 22, Yarn 4, AWS CDK 2.190 or later with the account bootstrapped, Docker, 2 Elastic IPs and 1 VPC of quota, Cognito for sign-in, a Kiro Pro licence, and a Region Kiro supports. The transformer stops at once when the Kiro credential is missing; Kiro's `.sqlite3` session store is uploaded with the run.
- Cost and risk: the audit's estimate was about $177 a month for Kiro against about $308 for an AWS Transform set-up of the same size (check current prices). Upgrade Assistant, which the toolkit's first step depends on, is deprecated by Microsoft; `install_prerequisites.py` installs it unpinned, while the toolkit pins 1.0.518.
- KB 19's container samples need fixing before use: no `USER`, curl health check, secrets in `ENV` ([linux-readiness.md](linux-readiness.md#what-aws-transform-and-devtx-do-and-do-not-cover)).

Log it: `report.py log --step port --engine devtx --status done --note "itr N, build green, summary next steps: ..."`.

## AWS Transform for .NET

**What it is.** AWS's managed agentic porting service: .NET Framework 3.5+, .NET Core 3.1 and .NET 5-10 to .NET 8 or 10 (or .NET Standard for libraries), C# and VB.NET. Project types: class libraries, console, MVC, Web API, Web Forms, WCF, ASMX, unit tests, WinForms/WPF, Xamarin. The user guide's history (15 October 2026) says the preview label was removed for VB.NET, WinForms, WPF and Xamarin; the FAQ still calls them preview, so confirm with AWS before promising them to a client. It can also convert Azure SDK code to AWS equivalents, and it validates with a local build and the unit tests.

**Surfaces:** web app, Visual Studio extension, the ATX CLI (`atx custom def exec -n AWS/dotnet-modernization -p <path>`; options `-q`, `-x`, `-t`), a Kiro power, and an MCP server. The unit of work is the repository in the web app (up to 5,000 repositories per job) and one solution at a time in Visual Studio and the CLI. The best-practices page says the newest .NET agent is not in the web console; the web pages were rewritten in September 2026, so check which surface has it before planning.

**Run steps:**
1. Connect the repository (Azure Repos / Azure DevOps, Bitbucket, GitHub, GitLab) through an AWS CodeConnections connector, a personal access token kept in Secrets Manager, an S3 zip or a direct zip upload; or open the solution in Visual Studio. One source connector per job, and creating a connector needs approval from the AWS account admin.
2. Assess: it builds a plan; review and edit it (which projects, target, Web Forms UI porting on or off).
   - The assessment report comes as Excel (package compatibility), HTML, Markdown, CSV and JSON. It rates each project's complexity (low, medium, high, critical) and its Linux readiness, and looks at framework version, public vs private NuGet, database connections and ORM patterns.
   - The web plan has the repository topology (waves), a feature and package migration map, and a transformation strategy with risks. Steering documents can set choices such as System.Text.Json, log4net handling or .NET Standard 2.0 for class libraries.
3. Resolve private NuGet packages it cannot find: its PowerShell helper script, a `.nupkg` or zip upload, or an Azure DevOps artifact connector. The `.nuspec` must sit at the package root, and the target is read from `<dependencies><group targetFramework="net8.0" />`. "Ignore the missing package dependencies" falls back to assembly references and can break related projects: avoid it.
4. Transform: it ports, builds in its remote build environment and runs unit tests. Unit tests it generates in Visual Studio are not validated by it: treat them as drafts, review them, and do not count them as parity evidence ([verification.md](verification.md)).
5. Review and accept the changes. The web app writes them to a new branch; an S3 source gets `transformed-code.zip` with a `diff.txt`; Visual Studio and the CLI change the files in place, so run them on a branch of the copy.
6. Read its interactive HTML transformation report (per solution and project: NuGet changes, build errors, unit test results), `NextSteps.md` and the zip of original and transformed code, including the **Linux readiness report** (CSV in Visual Studio: project, file, description, issue, recommendation; these columns were seen in Visual Studio and are not described on the AWS pages). Every item becomes Claude clean-up.

**Does not handle:** `.svc`, `.ashx` and service/web references (`reference.map`, `.cs`, `.wsdl`) in UI porting (the AWS list; `.asmx` pages are not on it and ASMX is a supported project type, but check every SOAP contract yourself); mixed `.aspx` and `.cshtml`; third-party UI controls; Web Site projects without a project file; Win32 DLLs without a core-compatible build; ViewState and page JavaScript behaviour (undocumented: test every page); MongoDB driver upgrades (undocumented). Web Forms to React is out of scope (AWS Transform custom).

Log it: `report.py log --step port --engine aws-transform --status done --note "job <id>, N projects accepted, next-steps items: ..."`.

### Limits and cost

Check the limits and pricing pages before quoting; these are the values on 21 October 2026.
- Quotas: 1,000,000 lines of .NET code per Region per month (web and IDE together); 5 concurrent .NET web jobs; 10 concurrent Visual Studio jobs; 100 workspaces per Region. The job's Region is the workspace's; it is not a per-job option.
- Price: the .NET agent includes 50,000 agent minutes a month at no charge, and the pricing page states no rate above that. The $0.035 per minute rate is for the **custom** transformation agent, not the .NET agent.
- Minutes are billed in 1-minute increments, only while the agent plans, reasons, analyses or changes code (not idle time, CLI file operations or local builds and tests). Agents working in parallel can bill more minutes than wall-clock time. A paused transformation stops after 24 hours.
- AWS's own examples: about 50,000 lines take about 2,800 minutes; about 500,000 lines about 25,000 minutes. AWS resources the outputs create are billed at normal prices. Set an AWS Budgets alert.

### Data handling

Tell the client before the first job, and get the answer in writing when the code is sensitive:
- **Service improvement:** content such as questions, responses and generated code may be used to improve the service, including model training, unless the account opts out: an AWS Organizations AI services opt-out policy (web app), and in Visual Studio the AWS Toolkit setting that shares Amazon Q content with AWS.
- **Retention:** source code is kept only for the duration of the job and purged after it (Windows FAQ).
- **Encryption:** TLS 1.2 or later in transit; at rest with AWS-owned keys, plus an optional customer managed KMS key (its key policy must allow `CreateGrant`; KMS charges apply).
- **Residency:** data is stored in the Region of the workspace, but inference can be routed to other Regions in the same geography, and from Mumbai, Seoul and Canada (Central) to any commercial Region. A client with residency rules must approve this.
- **Regions** enabled by default for AWS Transform include US East (N. Virginia), Mumbai, Seoul, Sydney, Tokyo, Canada (Central), Frankfurt and London; the SQL Server modernization page lists a different set. Check the Regions page for the agent you use.
- The client owns the ported code (Windows FAQ). Keep the account hygiene AWS asks for: MFA, CloudTrail, least-privilege IAM, no sensitive data in tags or names.

### Other AWS Transform agents

Still one engine per project: if one of these is used, record it as the engine for the work it does.
- **SQL Server modernization** (to Aurora PostgreSQL): targets Aurora PostgreSQL 15+ only (not RDS for PostgreSQL); SQL Server 2008 R2 to 2022; apps on .NET 6, 7, 8 or 10 only (port .NET Framework first); EF 6.3-6.5, EF Core 1.0-10.0 and ADO.NET; no VB.NET. It converts the schema, T-SQL procedures to PL/pgSQL, triggers and identity columns, switches the provider to Npgsql and updates connection strings, generates synthetic data and runs functional-equivalence checks in a container, and reports the share of schema converted. Limits: one AWS account and Region per job; it does not create the Aurora cluster; cross-database dependencies and code coupled to another repository's database need people; private NuGet must be set up first. It is PostgreSQL only, with no dual-database switch, and it writes database objects, which the DB team owns: agree that before using it ([playbooks/raw-sql-and-data-access.md](playbooks/raw-sql-and-data-access.md)).
- **Full-stack Windows modernization:** one job across the .NET code, SQL Server and deployment. Same rules as the two agents above.
- **Azure to AWS:** Azure Functions to Lambda, Blob Storage to S3 (`Azure.Storage.Blobs` to the `Amazon.S3` SDK), Queue Storage to SQS, Cosmos DB to DynamoDB (preview). It can be switched off. Check the result against [playbooks/aws-managed-services.md](playbooks/aws-managed-services.md).
- **Containerization** (the containers page): generates container images and deployment code for ECS (Terraform) or EKS (Helm), as part of a migration job; check the page for the current scope. Its Dockerfiles still go through [linux-readiness.md](linux-readiness.md) and the container gate.

## GitHub Copilot app modernization

Microsoft's recommended upgrade path (it replaces the deprecated Upgrade Assistant): AI-assisted assessment, plan and upgrade inside Visual Studio 2026 or Visual Studio 2022 17.14.16 or later. It covers WinForms, WPF, Web Forms and Blazor; WCF and ASMX are not on its list. Its cloud steps point at Azure, so the AWS swaps stay Claude's ([playbooks/aws-managed-services.md](playbooks/aws-managed-services.md)). Use it only when the client has it approved; it is still one engine per project, and its output goes through the same residue scan, Linux readiness scan and gates.

Log it: `report.py log --step port --engine copilot --status done --note "..."`.

## Claude as the porting engine

Only when neither DevTx nor AWS Transform is available. Claude follows the DevTx loop itself, on a branch of the copy:
1. Read [kb/README.md](kb/README.md) (error-code map), KB 00 (pre-build clean-up) and [kb-errata.md](kb-errata.md) (where the KB is wrong).
2. Convert the projects to SDK-style and set the target framework (libraries first, see [workflow.md](workflow.md)).
3. Build; for each error, find the KB file and the playbook that covers it, fix, rebuild. Commit after each project builds.
4. Stop and ask when a fix needs a decision (retire a feature, change a contract external callers use).
5. Then the normal clean-up, residue scan and gates.

Ask before installing anything (SDKs, Upgrade Assistant). Upgrade Assistant is deprecated by Microsoft; use it only as an optional first mechanical pass.

## DB porting agent

**What it is.** A porting agent for SQL Server → PostgreSQL in the application code: dual database (both engines behind one provider switch) or PostgreSQL only. It has **no T-SQL transpiler**: the model converts, guided by references and trigger regexes; deterministic scripts inventory the code, build the database contract, lint the result and score it ("scripts decide, the model judges"). It never connects to a database and runs no tests.

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
- Decide every item of [db-porting-checklist.md](db-porting-checklist.md) and record it (done, not applicable, or flagged with options).
- The approval step stays human: show the contract and the plan, wait for a yes.
- Costs more hours than the agent. The assessment's estimate does not yet change with `db_tool`, so when it is `claude`, add the difference to the plan by hand and say so.

Log it with `--engine claude` and the note "DB porting skills".

## What every engine leaves to Claude

Whatever the engine, Claude:
1. runs `residue_scan.py` and `linux_readiness.py` on the engine's output and works through the hits playbook by playbook ([playbooks/README.md](playbooks/README.md));
2. does the AWS managed-service swaps ([playbooks/aws-managed-services.md](playbooks/aws-managed-services.md));
3. writes the Dockerfile, health endpoint and stdout logging when the engine did not;
4. runs `verify.py target` until every gate passes or every remaining hit has a written waiver.

## Prerequisites

`python scripts/install_prerequisites.py --check` lists what is installed: Python, git, the .NET 10 SDK, Docker (container gate), MSBuild (baseline of .NET Framework code), the .NET tools, the AWS CLI, the AWS Transform CLI (`atx`, for AWS Transform custom), Node.js (DB porting agent scripts) and Kiro CLI (local DevTx-style runs). It installs nothing without asking.
