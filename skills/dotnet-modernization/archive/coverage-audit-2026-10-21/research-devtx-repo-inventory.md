> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Inventory DevTx version-upgrade repo

agent ab79d0ad16a2c0d90

READ-ONLY inventory of the DevTX / version-upgrade-toolkit repo. No files were created, edited, or deleted. No secret values were printed (the Kiro key is only referenced by variable name).

PATH NOTE
- The path given (<toolkit-outer>) is an outer folder that contains only one subfolder. The real repo root (with LICENSE, README.md, backend/, transformer/, etc.) is:
  <toolkit>
- Git branch there: fix/optimize-sln-detection. Relative paths below are from that root (call it R).
- Notable absences: no .kiro/ folder (only a .gitignore entry for it), no steering files, no *.prompt.md, no buildspec*.yml (CI triggers an external CodeBuild project from .github/workflows/ci.yml), no build.sh-style KB manifest, no SQL/PostgreSQL conversion tooling. build.sh, deploy.sh, check-licenses.sh do exist at root (also build.ps1, deploy.ps1, deployment-ec2-setup.sh).

1. SOURCE SUMMARY
- What it is: Apache-2.0 "Version Upgrade Toolkit on AWS" (Amazon copyright). A web app that runs code-upgrade jobs for Java and .NET modules inside Docker containers, using Kiro CLI (formerly Amazon Q Developer CLI) as the AI engine, plus Microsoft .NET Upgrade Assistant and OpenRewrite/QCT/ATX for Java. Results are committed to a per-iteration git branch and turned into a PR.
- Top-level layout:
  - backend/ : Node/TypeScript Express API. Product code. Orchestrates Docker transformer jobs (transform.ts, preparer.ts, job_complete.ts). Has jest tests in backend/test/.
  - frontend/ : React + Cloudscape UI (product code). Includes in-app help pages (pages/help/{en,ja,kr}) and i18n strings. Not read in detail.
  - infra/ : AWS CDK (TypeScript) stack that deploys the toolkit itself to AWS (infra-stack.ts, vpc.ts, capacity-limits.ts). Deployment tooling, not migration logic.
  - transformer/ : the transformation engines (Docker images) and their knowledge base. Migration-related. Sub-folders: common/ (shared scripts, Kiro system prompt, KB, report generator), dotnet-q/ (AI .NET engine), dotnet-upgrade-assistant/ (non-AI .NET engine), openrewrite-q/ (Java AI+OpenRewrite), qct/ (Java QCT), atx/ (Java AWS Transform custom CLI), preparer/ (pre-run repo analysis, Node/TS), prompts/ (two prompt txt files, see section 2).
  - docs/ : Astro/Starlight docs site (en, jp, ko), openapi.yaml, Postman collection, architecture drawio. Product docs; several pages are relevant to .NET scope.
  - scripts/ : check-licenses.mjs and translate.ts.
  - build/ : Dockerfile for the build container. build.sh runs it.
  - .github/ : CI (ci.yml -> CodeBuild), deploy.yml, translate-docs.yml, issue templates.
  - .vs/ : Visual Studio IDE state (sqlite, vsidx). Noise, exclude.
  - Root: CHANGELOG.md (1.0.0 to 1.1.0; 1.1.0 "replace q dev cli with kiro cli", "add atx engine", "add gradle wrapper"), README.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, LICENSE, NOTICE, LicenseHeader.txt, yarn.lock, package.json.
- Classification: backend, frontend, infra = product code. transformer/, docs/ (migration pages), and the knowledge bases = migration-related.

2. FILE LIST (relevance tags: dotnet / linux-container / sql-server-postgres / aws / general-workflow)

Prompts and system prompts
- transformer/common/q-system-prompt.txt | prompt (system) | Kiro system prompt for all AI engines: must reach zero compile errors for .NET 8/10 and Java; non-interactive rules; coding guardrails | dotnet, general-workflow. Used by dotnet-q, openrewrite-q (copied to /app/q-system-prompt.txt).
- transformer/transformers.hcl: not a prompt, see section 2 Scripts.
- transformer/dotnet-q/perform-upgrade.sh (lines ~19-55, ~540-650, ~690-705, ~826): prompts are inline heredocs, not separate files. Main migration prompt (steps 0-8, KB file list injection, build-until-zero-errors, warnings policy), report prompt (executive summary.md, 6 sections), and report.json estimated_time_saved prompt. | prompt | dotnet, linux-container (mentions containerisation only in KB list).
- transformer/prompts/dotnet-upgrade-prompt.txt | prompt | .NET system guidance (Web.config to appsettings.json, IConfiguration, ILogger, DI, async, build and test after changes) | dotnet. NOT referenced by any Dockerfile, script, or backend code (orphan; no file references it by name).
- transformer/prompts/spring-boot-upgrade-prompt.txt | prompt | Java/Spring Boot upgrade guidance | general. Not read by any script found; openrewrite-q/Dockerfile copies the whole prompts/ folder into /app/prompts, but openrewrite-q/perform-upgrade.sh does not reference "prompts" (verified by grep).
- Per-iteration additional prompt: free-text from the UI/API, written as additional-prompt-iteration-N.txt by backend/src/transform.ts (setupAdditionalPrompts) and run with kiro-cli --resume.

Knowledge bases
- transformer/common/migration-knowledge/dotnet/ (29 .md + README.md + DevTx-Modernisation-dotnet-knowledgefiles.zip) | kb | dotnet (see section 4 for the per-file list).
- transformer/common/migration-knowledge/java/ (26 .md numbered 00-26 + README.md) | kb | general (Java). Titles: 00 prebuild cleanup, 01 build systems, 02-05 JDK 8->11->17->21->25, 06 javax->jakarta, 07 Spring Boot 3, 08 Spring Security 6, 09 Spring Data JPA, 10 Hibernate 6, 11 dependencies, 12 configuration, 13 logging, 14 testing, 15 Gradle, 16 Maven, 17 containerization (includes postgres docker-compose sample), 18 Springfox->Springdoc, 19 latest Spring Boot, 20 Micrometer tracing, 21 build error playbook, 22 HTTP clients, 23 WAR/servlet, 24 non-Boot Spring 5.3 (javax), 25 version targets, 26 JMockit->Mockito. None are .NET.

Scripts and pipeline (ordered by run)
- transformer/common/run.sh | script (container entry, invoked via start.sh) | general-workflow. Fetches Kiro key (Secrets Manager on AWS, env on-prem), tests kiro-cli whoami, fails fast if ENABLE_Q_CLI and credentials invalid, indexes /app/knowledge as a Kiro KB, sets status RUNNING, runs perform-upgrade.sh, sets COMPLETED/FAILED, POSTs completion to backend.
- transformer/common/start.sh | script | general-workflow. Tiny wrapper that tees run.sh output to iteration job.log.
- transformer/common/common.sh | script (shared library, ~33 KB) | general-workflow. Progress JSON helpers, git stats, credit usage (parses "Credits:" from kiro-output.log), environment setup, Java helpers, snapshot and report file lists, initial_build, post_upgrade_tasks, detect_source_version, determine_target_framework (FORCE_LIBRARY_TARGET / FORCE_APP_TARGET overrides; not called in the .NET script as far as read).
- transformer/dotnet-q/perform-upgrade.sh (~41 KB) | script | dotnet, general-workflow. Main .NET AI engine. Detailed in section 3.
- transformer/dotnet-q/Dockerfile | Docker | dotnet, linux-container. AmazonLinux 2023; .NET SDKs 5, 6, 7, 8 and 10 (no 9); upgrade-assistant 1.0.518; Kiro CLI 2.14.2; default model claude-sonnet-4.6; copies KB to /app/knowledge (includes the zip file too); nuget.config.
- transformer/dotnet-q/nuget.config | config | dotnet.
- transformer/dotnet-upgrade-assistant/perform-upgrade.sh + Dockerfile | script/Docker | dotnet. Non-AI .NET engine (no Kiro). Same structure: upgrade-assistant upgrade per project, dotnet build, dotnet test --no-build, report generator. Image transformer-dotnet.
- transformer/openrewrite-q/perform-upgrade.sh + Dockerfile | script/Docker | general-workflow (Java). OpenRewrite + Kiro. Copies rewrite recipes and prompts folder.
- transformer/openrewrite-q/test/soap-guardrail.test.sh, spring-detection.test.sh | validation | general-workflow (Java SOAP guardrail; Spring detection). Only shell tests in the repo.
- transformer/qct/perform-upgrade.sh, Dockerfile, configuration.ini, aws-cli.config | script/Docker/config | general-workflow (Java, Amazon Q Code Transformation).
- transformer/atx/perform-upgrade.sh + Dockerfile | script/Docker | general-workflow (Java). Runs "atx custom def exec --transformation-name AWS/java-version-upgrade" (AWS Transform custom CLI) with Kiro summary afterwards. Installs JDK 8/11/17/21/25 and Maven/Gradle.
- transformer/preparer/run.sh, start.sh, Dockerfile, package.json, src/ (index.ts, prepare_code_repo.ts, git_utils.ts, types.ts, const.ts) | script/code | general-workflow. Analysis container; see section 3 step P.
- transformer/preparer/src/code-analyzers/language_analyzers/csharp.ts | code | dotnet. Parses PackageReference and packages.config.
- transformer/preparer/src/code-analyzers/utils/version_detector.ts | code | dotnet. Reads TargetFramework, TargetFrameworks, TargetFrameworkVersion (legacy), global.json; maps net4x/netcoreapp/net5-9 to labels.
- transformer/preparer/src/code-analyzers/utils/nuget_client.ts, github_advisory_client.ts, vulnerability_checker/nuget_vulnerability_database.ts, vulnerability_checker.ts | code | dotnet. NuGet and GitHub-advisory vulnerability checks.
- transformer/preparer/src/code-analyzers/code_analyzer.ts, types.ts, utils/dependency_resolver.ts, utils/metrics.ts | code | general-workflow.
- transformer/common/upgrade-report-generator/*.ts (report-generator.ts, dotnet-proj-comparer.ts, confidence-calculator.ts, time-calculator.ts, types.ts, pom-comparer.ts, gradle-comparer.ts) | code | dotnet (dotnet-proj-comparer), general-workflow (confidence and time metrics). Builds report.json per iteration.
- transformer/common/init.gradle, rewrite.yml, q-credentials/Placeholder.txt | config | general-workflow / Java. Placeholder only, no real credentials in repo.
- transformer/transformers.hcl | build config (docker buildx bake) | general-workflow. Targets: openwrite-q (sic), dotnet, dotnet-q, qct, preparer, atx; group "all" omits qct.
- build.sh, build.ps1, build/Dockerfile | build | general-workflow. build.sh runs a builder container with docker.sock.
- deploy.sh, deploy.ps1, deployment-ec2-setup.sh | deploy | aws (deploys the toolkit with CDK).
- check-licenses.sh, scripts/check-licenses.mjs | licence check | general-workflow. Section 5.
- backend/src/transform.ts (722 lines) | product code, orchestrator | general-workflow, dotnet. startTransform, getImageName, cancelTransform, docker run with env vars, getFile.
- backend/src/preparer.ts | product code | general-workflow. Launches the preparer container (INIT_REPO flag).
- backend/src/job_complete.ts | product code | general-workflow. Completion callback, branch push, PR creation, DONE status.
- backend/src/module.ts, const.ts (engine list), types.ts, utils.ts, security.ts, data_access.ts, source_control_integration.ts, gitwatcher.ts, project.ts, admin.ts, api.ts, main.ts | product code | general-workflow.
- backend/test/transform.test.ts, preparer.test.ts, job_complete.test.ts, module.test.ts, others | validation (unit tests of the orchestrator) | general-workflow.
- infra/lib/infra-stack.ts, vpc.ts, capacity-limits.ts, set-callback-lambda/index.js, infra/test/infra.test.ts | product/aws (deploying the toolkit). infra/cdk.json has rds feature flags only; no RDS, no DMS, no PostgreSQL resources in infra code.
- frontend/src/... (pages, components incl. ConfidenceChart, CodeChangeChart, DependencyCompatibilityChart, VulnerabilityChart, ReportViewer, IterationsTable, PromptMetadata, ModuleDetailContainer) | product UI | general-workflow (shows reports and prompt metadata).

Docs (migration-relevant)
- docs/src/content/docs/en/introduction/supported-transformation-types.mdx | doc | dotnet. .NET scope: .NET Framework 4.5+, .NET Core 1.0-3.1, .NET 5.0-7.0 as current; targets .NET 8 or 10. Unsupported: WinForms, WPF, WF. Project types: ASP.NET MVC, Web API, Web Forms, console, libraries.
- docs/src/content/docs/en/introduction/concepts.md | doc | general-workflow (project, module, iteration definitions).
- docs/src/content/docs/en/userguide/transform-code.mdx, view-iterations.mdx, view-code-analysis-report.mdx, manage-modules.mdx, manage-projects.mdx, configure-source-control.mdx, logging.mdx | doc | general-workflow. Not read in detail.
- docs/src/content/docs/en/deployment/*, plan-deployment/security.mdx, cost.mdx, quotas.mdx, architecture/home.mdx | doc | aws. Not read in detail; quotas and security mention Kiro/Secrets Manager/limits (grep hits).
- docs/openapi.yaml, docs/VersionUpgradeAPI.postman_collection.json, docs/architecture-diagram-ec2.drawio | doc/api | general-workflow.
- README.md | doc | general-workflow. Build, deploy, local dev, on-premises (docker up) instructions.
- CHANGELOG.md, CONTRIBUTING.md | doc | general-workflow.
- .husky/commit-msg, .husky/pre-commit, commitlint.config.js | rules | general-workflow (commit message conventions).
- .github/workflows/ci.yml, deploy.yml, translate-docs.yml | CI | aws (ci.yml starts an AWS CodeBuild project and waits for SUCCEEDED).
- .gitignore | config | general-workflow (ignores .kiro).

Steering, Kiro agents, buildspec, rules: none found in this repo. Kiro is only used through the CLI invoked by shell scripts.

3. DEVTX WORKFLOW (DOTNET path, transformEngine DOTNET_UPGRADE_ASSISTANT_WITH_Q; the non-AI variant is noted where it differs)

Inputs
- Module config (saved by backend, read as $DATA_DIR/configuration.json): targetVersion (.NET: 6, 7, 8 or 10; anything else silently becomes net8.0), modulePath (repo subfolder), customBuildScript and customBuildArguments (optional), framework (.NET or JAVA), transformEngine, upgradeBranchName, gitCommitTitleTemplate.
- Source code: a git repo cloned by the backend into the module data dir (source_control_integration.ts; repo providers per docs). Solution file resolved by resolve_solution_file in the script.
- Env passed by backend/src/transform.ts docker run: MODULE_ID, ITERATION, UPGRADE_BRANCH_NAME, TRANSFORM_ENGINE, DISABLE_AI, FRAMEWORK, Q_CLI_CREDENTIALS_ARN, ENABLE_Q_CLI (true only for *_WITH_Q engines), GIT_COMMIT_TITLE, JOB_STATUS_ENDPOINT, optional Q_ADDITIONAL_PROMPT_FILE, KIRO_API_KEY (on-premises only, from settings; on AWS fetched from Secrets Manager by run.sh). Optional BUILD_CONFIGURATION (default Release).
- Optional per-iteration additional prompt text from the UI/API.
- Container limits: JOB_MEM_LIMIT, JOB_CPU_LIMIT (default -1 = none); MAX_NUM_JOBS (default -1 = unlimited concurrency).
- Migration knowledge: /app/knowledge (the dotnet KB, copied at image build time).

Ordered steps
- A. Start (backend, transform.ts startTransform): allowed only when module status is READY, FAILED, DONE or CANCELLED (not CREATING, PREPARING, PREPARED, NOT_INIT, and not while refreshing). Sets PENDING, increments iteration, creates $DATA_DIR/iteration-N, removes job.id, picks image by framework and engine (dotnet: transformer-dotnet for DOTNET_UPGRADE_ASSISTANT, transformer-dotnet-q for ..._WITH_Q; DISABLE_AI forces transformer-dotnet even for the WITH_Q engine), runs docker with the env above. Sets RUNNING via run.sh.
- B. Entry (common/run.sh): fetch or read Kiro key, kiro-cli whoami check, fail fast if Kiro required and invalid, add /app/knowledge as Kiro KB named "application modernisation knowledge" (index-type Best), verify with /knowledge show, set status RUNNING, job id, then run perform-upgrade.sh.
- C. Setup (dotnet-q perform-upgrade.sh main): check jq, dotnet, upgrade-assistant, node present; configuration.json and code dir present; read targetVersion, modulePath, custom build script; create iteration dir; setup_iteration_prompt copies /app/q-system-prompt.txt to iteration q-prompt.txt; cd to code/modulePath; dotnet nuget list source; setup_environment; initialise progress.json; resolve solution file; detect .csproj projects; save original project files to original-projects/.
- D. Initial build (skipped if any project is .NET Framework style, since it cannot build on Linux): run custom build script or run_scoped_dotnet_build; progress.json "initial_build".
- E. Map target: TARGET_VERSION 6/7/8/10 to net6.0/net7.0/net8.0/net10.0; default net8.0.
- F. Deterministic upgrade (Microsoft .NET Upgrade Assistant 1.0.518): for each .csproj, upgrade-assistant upgrade --targetFramework <tfm> --non-interactive --operation Inplace, logged to code-upgrade.log. Failure sets UPGRADE_EXIT=1 but the script does NOT stop; Kiro still runs.
- G. AI repair (Kiro CLI, claude-sonnet-4.6 default, one non-interactive chat session with --trust-all-tools): system prompt q-system-prompt.txt plus the inline migration prompt. The session is told to: run pre-build cleanup (00), build, fix errors using the KB (README error-code map, all KB files listed by generate_kb_file_list), convert to SDK-style projects, replace packages (06), System.Web (02), MVC/WebAPI (03/04), EF6 (16), auth (08), Global.asax/config (10/11), WCF/System.Drawing/crypto/Swagger/test stack/WebForms/Remoting (20-26, 28), build integrity (27), and iterate with dotnet build until zero errors. Output tee'd to code-upgrade.log and kiro-output.log.
- H. Additional prompt (optional): if a per-iteration additional prompt file exists, kiro-cli chat --resume runs it.
- I. Executive summary: kiro-cli --resume writes iteration summary.md (6 sections incl. "Next steps"); line endings post-processed.
- J. Post-upgrade verification (the real gate): build (custom script or dotnet build of the solution or each project), then if build passes dotnet test --no-build (solution or each project; "No test is available" counts as pass). progress.json "post_verification".
- K. Git: git checkout -B <UPGRADE_BRANCH_NAME>-itr-N; git add (excluding bin and obj); git commit with GIT_COMMIT_TITLE (|| true, so an empty commit does not fail); git reset --hard; export git stats; checkout the upgrade branch at the end.
- L. Reporting: report-generator.js compares original vs current .csproj lists (dotnet-proj-comparer) and writes report.json; a second Kiro call asks it to set estimated_time_saved (minutes) in report.json; PROMPT_SOURCE and PROMPT_FILE metadata added; KB copied to iteration knowledge-base/; export_credit_usage sums "Credits:" lines from kiro-output.log into report.json.
- M. Exit: perform-upgrade.sh exits with EXIT_CODE (1 if upgrade or post verification failed). run.sh sets COMPLETED on exit 0, otherwise FAILED; clear job id; POST to backend /modules/:id/:iteration/complete.
- N. Completion (backend job_complete.ts): valid only when status is COMPLETED (transform). Pushes <upgradeBranch>-itr-N to origin and opens a PR into the upgrade branch with summary.md as body; updates pull-request progress; status DONE. On FAILED no PR is created (status check returns 400), per my reading.
- Cancel: backend sets CANCELLED first, then docker stop -t 5.
- Preparer (separate job, preparer container; INIT_REPO=1 gives job type init and status PREPARED, otherwise prepare and status COMPLETED): analyses the repo (csharp analyzer, version_detector, NuGet/GitHub vulnerability checks) and writes project/dependency analysis. No AI, no build.
- Non-AI variant (DOTNET_UPGRADE_ASSISTANT): same steps C-F, D, J-N, minus the Kiro steps G-I and the Kiro-based summary/time estimate.

Iteration loop
- Outer loop is human-driven: each run is a new container and a new iteration number. The next iteration starts when a user (or API caller) presses start again after reviewing the PR and summary.md. Each run reads the repo state and any additional prompt, not an automated retry feed.
- Inner loop is inside the single Kiro session: the prompt says to run dotnet build repeatedly and fix each error, "DO NOT STOP OR SUMMARIZE UNTIL THE BUILD IS ERROR-FREE". No iteration cap, timeout, or retry counter appears in the scripts; termination depends on the model finishing, Kiro itself, or a cancel from the backend, plus container limits (JOB_MEM_LIMIT, JOB_CPU_LIMIT).
- Unresolved items: the prompt tells Kiro to write them to "Next steps" in summary.md and keep going. Humans review them and feed them to the next iteration (via additional prompt).
- Kiro's exit status is not checked (its pipeline ends with tee). The only automatic gate is step J.

Done criteria
- Kiro's own target (prompt): dotnet build <solution> or each upgraded project exits 0 with zero errors; warnings reduced on a best-effort basis.
- Script gate (J): build exit 0, and then dotnet test --no-build exit 0 for the solution or each project. Any failure gives EXIT_CODE 1, FAILED status, and no PR.
- Not gates: DUA failure, Kiro failure or non-zero exit, missing summary.md, report failures (all log warnings only).

Outputs
- Repo: branch <UPGRADE_BRANCH_NAME>-itr-N (commit) and the upgrade branch (PR merge target). Commit title from GIT_COMMIT_TITLE template.
- Per iteration, under $DATA_DIR/iteration-N/ (DATA_DIR=/data in the container): q-prompt.txt, progress.json, initial-build.log, original-projects/, code-upgrade.log, kiro-output.log, post-upgrade-verification.log, summary.md, report.json, knowledge-base/, additional-prompt.txt (if used).
- Module status file $DATA_DIR/status.json (status, jobId, iteration). Backend APIs expose these (getStatus, getIterationFile).

Guardrails and rules (condensed from q-system-prompt.txt and the inline prompt)
- Work until the solution builds with zero compile errors; do not stop after converting project files.
- Consult the KB first (README error-code map); but KB is not a gate: the model may fix errors with its own judgment.
- Do not drastically change patterns before iterating on existing ones; prefer simple solutions; avoid duplication; keep the codebase clean; touch only code related to the task; no new pattern or technology until existing options are exhausted, then remove the old one.
- Do not write one-off scripts into files; mock data only in tests, never in dev or prod code; environment-aware (dev, test, prod).
- Non-interactive: never ask questions; choose the safest option; write assumptions and risks in summary.md "Next steps"; if a referenced file is missing, skip it and note it.
- Java-specific rules (javax namespace guardrail, no java -jar runs) exist in the same prompt but are not .NET.
- Risk note: --trust-all-tools lets Kiro run any shell tool in the container with no approval.
- Unused: transformer/prompts/dotnet-upgrade-prompt.txt (Web.config -> appsettings, IConfiguration, ILogger, DI, "maintain existing database schemas") is not wired into any engine.

Models and tools per step
- LLM: Kiro CLI 2.14.2 with default model claude-sonnet-4.6 (set in dotnet-q/Dockerfile via kiro-cli settings; telemetry off; thinking on; KB indexing on, *.md, *.txt, *.cs, *.csproj, *.config). Also used for the summary.md and time-estimate calls.
- Tools: .NET SDKs 5, 6, 7, 8, 10; dotnet-upgrade-assistant 1.0.518; dotnet CLI build and test; git; jq; node (report generator); AWS CLI (Secrets Manager fetch on AWS).
- Non-AI engine uses the same SDK and upgrade-assistant without Kiro.

SQL Server, stored procedures, PostgreSQL, and database conversion
- No database conversion step, no SQL Server to PostgreSQL schema or data conversion, no stored-procedure translation, no sqlcmd or psql or DMS or SSMA usage in any script or backend code. Explicit: none.
- Content in the dotnet KB only: 16 section 11 keeps EXEC stored procedures through EF Core FromSqlRaw and ExecuteSqlRaw (no conversion); 07 has a SQL Server Compact section; 17 Dapper example uses a SQL Server connection string; 18 NHibernate sets a SQL Server dialect or a PostgreSQL dialect and driver (Npgsql) as configuration options only; 19 has a docker-compose sample with the mssql/server:2022 image. No T-SQL-to-PostgreSQL mapping content.
- Java KB (not in scope) has PostgreSQL samples. The repo's AI prompt mentions maintaining existing database schemas (unwired prompt only).

AWS migration
- The toolkit is deployed to AWS with CDK (infra/) and CodeBuild CI. It does not generate AWS target infrastructure for the migrated application. 19-linux-containerization.md has deployment options (ECS/Fargate, push to ECR, ALB, etc.) and 05 mentions ECS/Kubernetes. 28 has AWS hosting notes (ALB + gRPC on ECS/EKS, SQS replacement for remoting). 21 mentions Lambda as a hosting option. No CDK or ECS templates are generated for the target app.

4. ALREADY-COPIED CHECK
- transformer/common/migration-knowledge/dotnet/ (30 files as zip members; the folder has 29 .md + README.md + the zip). I byte-compared all 30 zip members against the on-disk files: all identical.
  - 00-prebuild-cleanup-and-bulk-fixes.md: pre-build cleanup (remove [Index]/[AllowHtml], System.Web and EF namespace bulk fixes).
  - 01-project-file-migration.md: csproj to SDK-style.
  - 02-systemweb-migration.md: System.Web to ASP.NET Core.
  - 03-mvc-migration.md: MVC 5 to ASP.NET Core MVC.
  - 04-webapi-migration.md: Web API 2 to ASP.NET Core Web API.
  - 05-hosting-deployment-migration.md: IIS/hosting to Kestrel, deployment options.
  - 06-package-migrations.md: NuGet replacements and version mappings.
  - 07-data-access-migration.md: data-access overview (EF6, Dapper, NHibernate), SQL Server Compact.
  - 08-auth-security-migration.md: Identity, auth filters, security.
  - 09-bundling-minification.md: bundles to static-asset tooling.
  - 10-global-asax-migration.md: Global.asax to Program.cs.
  - 11-configuration-migration.md: web.config to appsettings.json.
  - 12-logging-migration.md: log4net and others to ILogger.
  - 13-dependency-injection-migration.md: Autofac and others to built-in DI.
  - 14-middleware-migration.md: OWIN to ASP.NET Core middleware.
  - 15-views-static-files-migration.md: Razor views and static files.
  - 16-ef6-to-efcore-migration.md: EF6 to EF Core, including raw SQL and stored procedures.
  - 17-dapper-migration.md: Dapper on .NET 8/10.
  - 18-nhibernate-migration.md: NHibernate, SQL Server and PostgreSQL dialects.
  - 19-linux-containerization.md: Dockerfile, compose, health checks, deployment options, SmartStore notes.
  - 20-wcf-to-corewcf-migration.md: WCF to CoreWCF.
  - 21-system-drawing-migration.md: System.Drawing to SkiaSharp or ImageSharp.
  - 22-crypto-migration.md: BouncyCastle rename, CryptoServiceProvider APIs.
  - 23-swagger-swashbuckle-migration.md: Swashbuckle 5 to AspNetCore.
  - 24-test-stack-migration.md: MSTest, NUnit, xUnit, Moq, RhinoMocks.
  - 25-webforms-to-razor-migration.md: Web Forms to Razor Pages or MVC.
  - 26-webforms-to-blazor-migration.md: Web Forms to Blazor.
  - 27-blocked-packages-and-build-integrity.md: NU1701, NU1605/1608, NU1902/1903.
  - 28-dotnet-remoting-migration.md: .NET Remoting to gRPC, SQS or queues; AppDomain and BinaryFormatter removal (49.8 KB, largest).
  - README.md: master index, target rules (net8.0 or net10.0 placeholders), precedence rules, error-code map, 12-step workflow, time estimates (4-7 h for the core set).
  - DevTx-Modernisation-dotnet-knowledgefiles.zip: archive of the same 30 files (no extra content). Note it is copied into the image too.
- Other .NET, SQL, or AWS knowledge outside that folder: none as KB. Only code and config: preparer csharp analyzer and version_detector; upgrade-report-generator dotnet-proj-comparer; dotnet-q and dotnet-upgrade-assistant scripts; docs supported-transformation-types.mdx and 19-like deployment docs; infra CDK. The dotnet-upgrade-prompt.txt (unwired) is the only other .NET prompt. No SQL Server or PostgreSQL knowledge file exists outside the dotnet KB (Java KB has Postgres samples).

5. LICENCE
- Licence: Apache-2.0. LICENSE is the full Apache License 2.0 text. package.json files (root, backend, frontend, transformer, upgrade-report-generator) declare "license": "Apache-2.0".
- NOTICE: a single line "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved." No third-party attributions listed.
- Third-party notice requirement: Apache-2.0 section 4 applies when redistributing. Nothing in the repo lists third-party notices beyond the licence check. check-licenses.sh runs "yarn licenses --production" on backend, frontend and transformer/upgrade-report-generator, and scripts/check-licenses.mjs fails on any licence outside an allowlist (MIT, Apache-2.0, BSD-2/3, ISC, Zlib, Unlicense, WTFPL, CC-BY-4.0, and a few compound forms) plus a named approved-package list. It does not cover the transformer/preparer package, the Python/Node Docker tools, or the Java/.NET tools installed in the images (Kiro CLI, upgrade-assistant, AWS Transform CLI are downloaded binaries and not covered).
- LicenseHeader.txt: a /* */ block: "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved." followed by the standard Apache-2.0 "Licensed under the Apache License, Version 2.0 ..." text and the URL http://www.apache.org/licenses/LICENSE-2.0. Shell and Dockerfile-style files use the same text with # comments. 191 source files (ts, tsx, sh, js, mjs, gradle, hcl) contain it. Not on: the .md KB files, the .txt prompt files, the .hcl and .json configs, the .yml workflows.
- Implication for the KB: the dotnet and java .md files carry no licence or provenance header. Their licence status follows the repo LICENSE only. The zip name "DevTx-Modernisation-..." suggests an internal origin; provenance is not stated in the repo.

Unverified or partial: I read the core engine scripts, backend orchestrator, KB README and headings, and the licence files in full. I did not read every docs page, frontend page, or the Java KB content, nor the full dotnet KB bodies beyond the headings and the sections cited.
