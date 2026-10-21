> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Skill coverage fixes

Merged from the 10 audit reports written on 2026-10-21. Duplicates are merged. Applied on 2026-10-21 in the publisher clone and the source repo, except the held items; nothing is committed. Where each source is covered: [SKILL-COVERAGE-MAP.md](SKILL-COVERAGE-MAP.md). [Reports used](#reports-used) lists all 19 reports in the folder and what each was used for.

Skills: **DM** = dotnet-modernization, **MA** = modernization-assessment, **CD** = codebase-documenter.

Source tags:
- **V**: the audit checked it on a Microsoft, AWS, Npgsql or PostgreSQL page.
- **C**: read from code (DevTx toolkit, our scripts, the internal DB porting skills).
- **U**: unverified. I check it on the web before adding it, and leave it out or mark it "verify" if I can't confirm it.

Totals: 28 corrections, 1 KB errata file, 21 engine items, 23 playbook items, 8 gate items, 13 rule items, 6 SQL to PostgreSQL items, 2 AWS service items, 4 housekeeping items.

## Contents
- [Decisions for you](#decisions-for-you)
- [A. Corrections: wrong or out of date in the skills](#a-corrections-wrong-or-out-of-date-in-the-skills)
- [B. KB errata](#b-kb-errata)
- [C. Porting engines](#c-porting-engines)
- [D. Port playbooks](#d-port-playbooks)
- [E. Verification gates](#e-verification-gates)
- [F. Detection rules](#f-detection-rules)
- [G. SQL Server to PostgreSQL](#g-sql-server-to-postgresql)
- [H. AWS services](#h-aws-services)
- [I. Housekeeping](#i-housekeeping)
- [Reports used](#reports-used)

## Progress

Decisions 4 and 5 are done. Decisions 1, 2, 3 and 6 are on hold. Everything else is applied in the publisher clone and copied to the source repo (only where the source copy matched before; otherwise the same edit was made there). Nothing is committed.

| Area | Status |
|---|---|
| A | All done. A6 reworded instead of implemented; A13 already fixed; A16's premise was wrong (FILE-CASE-MISMATCH exists), page now cites both. |
| B | On hold (decision 1). |
| C | Done except C10 (decision 2). Interim: ask before every DevTx run. Pricing corrected: $0.035/min is the custom agent only. |
| D | All done (D6-D8, D12, D14-D23 in this pass); unconfirmed claims marked "(verify)". |
| E | Done. E6: vulnerable-package gate added, performance and SAST manual. E7: database gate manual, shown as a "not run" row. |
| F | Done; F9 as 9 new Linux checks (296 total), F1-F8 as 25 new residue rules (69 total), F10/F11 as 11 rules and 9 package entries. F10 partly: AWS-native and infrastructure data rows left. F12 partly: LNX-WEB-BUNDLING warn vs residue block left. |
| G | G2, G4, G5, G6 done; G1 on hold (decision 3); G3 open. |
| H | Done. |
| I | I2 and I3 done; I1 partly (selftest checks the catalogue, not drift between copies). |
| AWS docs sweep | Applied: limits, pricing, data handling, other AWS Transform agents, reports and outputs, Lambda dates, Babelfish, cost examples (sources S26-S38 in the assessment). |
| Linux readiness session | Ported: 287-check scanner, standalone linux-readiness skill, selftest with an ECS-wiring fixture and a check that no rule is switched off silently. |

| Item | Status |
|---|---|
| D1 web-api.md (with D3 Swagger/OpenAPI), D2 mvc.md, D4 signalr.md, D5 reporting.md, D13 reference/breaking-changes.md | Written in dotnet-modernization (publisher clone and source repo). Linked from SKILL.md and the playbook index. The assessment's tool_coverage.json now routes WEB-WEBAPI2 → web-api, WEB-CHILD-ACTION and WEB-DI-RESOLVER → mvc, WEB-SIGNALR-LEGACY → signalr, and WEB-REPORTVIEWER, INT-CRYSTAL and INT-SSRS-CLIENT → reporting. |
| Raw reports | Archived in each skill under `archive/coverage-audit-2026-10-21/`, with local paths, client names and internal names replaced. Four private-workspace inventories are held back. The validator treats `archive/` like `samples/` (not style-linted, still secret-scanned). |

### Web check of the U items

| Item | Result | Now tagged |
|---|---|---|
| A8 Dapper `= ANY(@ids)` | Confirmed from Dapper's source (FeatureSupport.cs, SqlMapper.cs). On an `NpgsqlConnection`, Dapper passes a list as one array parameter, so `= ANY(@ids)` is right and `IN @ids` is not expanded. A wrapped connection (a profiler, for example) has a different type name and falls back to list expansion. | V |
| D7 Distributed transactions | Confirmed. On .NET 7+ the `TransactionManager.ImplicitDistributedTransactions` setter is Windows-only (MSDTC), so Linux has none. Redesign with an outbox or saga. | V |
| D8 Thread.Abort | Confirmed. It throws PlatformNotSupportedException and is obsolete (SYSLIB0006) from .NET 5. Use a CancellationToken. AppDomains and CAS were already confirmed. | V |
| D11 NHibernate | Not confirmed: the dialect and driver class names, and 5.4 on .NET 8+. NHibernate.Extensions.Npgsql 8.x targets net8.0 with NHibernate ≥ 5.5.2. Write the guidance without version pins. | verify |
| D22 ClickOnce | Confirmed: Visual Studio 2019 16.8+ publishes .NET Core 3.1 / .NET 5+ desktop apps with ClickOnce. That the ApplicationDeployment API is missing comes only from the legacy samples page. | V (path), verify (API) |
| D23 ImageSharp 4 / SkiaSharp | ImageSharp.Web 4 needs a Six Labors licence at build time (official docs). SixLabors.Licensing fails the build without a key. Core 4.x is reported to fail Release builds without one. `SKFilterQuality` overloads are obsolete in favour of `SKSamplingOptions` (Microsoft's SkiaSharp API docs), but no version number was confirmed, so drop the "v4" claim. | V, version dropped |
| F9 IMDS hop limit (bridge mode) | Containers need hop limit 2. AL2023 defaults to 2 for container workloads (AWS docs). Limit 1 blocks IMDSv2 from bridge-mode containers. | V |
| F9 initProcessEnabled on Fargate | Works on Fargate (AWS blog sample task definition). | V |
| F9 libldap for System.DirectoryServices.Protocols | No Microsoft statement found. | verify (keep as warn) |
| F10 AppConfig feature flags | The AppConfig feature-flag profile type is confirmed (AWS docs). A .NET configuration provider for it is not. | V (service), verify (.NET provider) |
| G4 TransactionScope default | Serializable, per Microsoft's archived blog on learn.microsoft.com. The API page doesn't state it. | V |
| Crystal Reports on .NET 8+ | No SAP statement of support found. reporting.md says .NET Framework on Windows until SAP confirms. | verify |
| ReportViewer on .NET 8+ | No Microsoft port. Microsoft Q&A (2025) and the community ReportViewerCore package say so. | V |

## Decisions for you

| # | Decision | My recommendation |
|---|---|---|
| 1 | The KB has errors that mislead a port. `reference/kb/` is a licensed verbatim copy. | Leave kb/ unchanged and add `reference/kb-errata.md` (B1). |
| 2 | DevTx pushes branches and opens PRs on the repo's remote, but the skill says never push to a client remote. | Require a sandbox remote (a mirror) for DevTx runs (C10). |
| 3 | PostgreSQL-only mode (no dual provider; data migration in scope) is missing. | Add it as a second mode in the raw-SQL playbook (G1). |
| 4 | Five new playbooks: web-api, mvc, signalr, reporting, and a .NET 10 breaking-changes reference. | Add all five (D1 to D5, D13). |
| 5 | Items tagged U. | Check each on the web first. Drop it or mark it "verify" if it can't be confirmed. |
| 6 | Still open: rewrite the public repo's history to drop the old names from 5a53e5b (needs a force push). | Your call. |

## A. Corrections: wrong or out of date in the skills

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| A1 | High | "Integer AVG truncates in both" is wrong. SQL Server AVG(int) returns int; PostgreSQL avg(int) returns numeric. Cast or trunc to match. | DM raw-sql playbook | C |
| A2 | High | "verify.py --db-target dual builds and tests both engines" is false. It only passes the flag to the residue scan. Say the DB gate is manual, or add the gate (E7). | DM verification.md, raw-sql "Done when" | C |
| A3 | Med | `NpgsqlException.SqlState` should be `PostgresException.SqlState`. | DM raw-sql playbook | V |
| A4 | Med | TOP n → LIMIT is invalid for UPDATE/DELETE. Use a key subquery or ctid. | DM raw-sql playbook | C |
| A5 | Med | MERGE exists in PG 15+ and WHEN NOT MATCHED BY SOURCE in PG 17. Make it version-gated (the default target is 16). | DM raw-sql playbook | V |
| A6 | Med | engines.md says the assessment adds Claude-path hours when db_tool is claude. estimate_effort.py never reads db_tool. Implement it or drop the claim. | DM engines.md, MA estimate_effort.py | C |
| A7 | Med | AWS SCT C# code conversion is Oracle-only, and DMS Schema Conversion converts schema only. Neither converts .NET code from SQL Server. | MA database-assessment.md, estimate notes | V |
| A8 | Med | Dapper `= ANY(@ids)` vs Dapper's IN-list expansion. Check, then document both forms. | DM raw-sql playbook | U |
| A9 | Med | Npgsql 6+ DateTime rules are incomplete: UTC to a timestamp column is rejected, and a DateTimeOffset with a non-zero offset is rejected. | DM raw-sql playbook | V |
| A10 | Med | LNX-CTR-LIBGDIPLUS: EnableUnixSupport was removed in .NET 7, so libgdiplus is no fix. Say replace with SkiaSharp or ImageSharp. | linux_readiness.json (both skills) | V |
| A11 | Med | LNX-CUL-INVARIANT-MODE wording is wrong (invariant mode restricts culture creation). Also scan ECS task-definition JSON. | linux_readiness.json | V |
| A12 | Med | LNX-HOST-PORT-80 never fires (automated false, no file types). Add Dockerfile, yml and task JSON. | linux_readiness.json | C |
| A13 | Low | LNX-PROC-NO-HOST-LIFETIME flags any `while (true)`. Implement the stated "Program.cs with no IHost" condition. | linux_readiness.json/.py | C |
| A14 | Low | LNX-API-DLLIMPORT-DLL-SUFFIX: cite the Microsoft native-library-loading page instead of the KB. | linux_readiness.json | V |
| A15 | Med | Alpine and chiseled images both lack ICU and tzdata. Only the -extra variants have them. | DM time-and-culture.md | V |
| A16 | Low | linux-pitfalls.md cites FILE-CASE-MISMATCH, which doesn't exist. Point to LNX-FS-CASE-*. | MA linux-pitfalls.md | C |
| A17 | Low | LNX-FS-CRLF-SCRIPTS glob `entrypoint*` is unreachable, because files with no extension are skipped. | linux_readiness.py | C |
| A18 | Med | AWS Transform's "Linux readiness CSV" is not in its docs. Remove it. | DM engines.md | V |
| A19 | Med | DevTx "Linux container and health check: yes" is wrong. The toolkit builds and tests only; it writes no Dockerfile. | DM engines.md table | C |
| A20 | Med | "Initial build skipped for .NET Framework" holds only for the Kiro engine. The Upgrade Assistant engine runs the initial build and stops on failure. | DM engines.md step 3 | C |
| A21 | Low | ApiPort is deprecated and its backend is shut down. The successors are the Copilot agent and the Platform Compatibility Analyzer. | MA tools-landscape.md | V |
| A22 | Med | KB 20 pins CoreWCF 1.6.0. Use 1.9, which targets .NET 10; 1.8 reaches end of support on 24 Oct 2026. Say so in the playbook. | DM wcf-services.md | V |
| A23 | Med | WSHttp with WS-Security, duplex and the certificate store are not documented for CoreWCF. Mark them "test first". | DM wcf-services.md | V |
| A24 | Low | "AppStream 2.0" should be "Amazon WorkSpaces Applications (formerly AppStream 2.0)". | MA seven-rs.md | V |
| A25 | Low | The KB has 29 files (00 to 28), not 28. | DM SKILL.md, README | C |
| A26 | Med | verification.md says parity catches the XML declaration and encoding. parity.py compares status and parsed body only. Add raw-byte checks or reword. | DM verification.md, parity.py | C |
| A27 | Low | rules.json `db` field: the _doc says blocker/limited/ok, but the data holds rework/redesign. | MA rules.json | C |
| A28 | Low | package_map.json: one broad ok line swallows NUnit, Moq, xunit, MSTest and Portable.BouncyCastle, and Microsoft.AspNet.Web.Optimization matches two lines. | MA package_map.json | C |

## B. KB errata

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| B1 | High | New `reference/kb-errata.md`, linked from SKILL.md, listing each KB claim with the correct guidance:<br>• [Index] called unsupported (00, 07, 16; EF Core has IndexAttribute)<br>• Database.SqlQuery mapping (07:16; use SqlQueryRaw)<br>• `new ExceptionFilterAttribute()` (02:304; abstract)<br>• IHostingEnvironment CS0104 (02:60)<br>• AreaRegistration "discovered by convention" (03:143; needs an explicit area route)<br>• `dotnet migrate packages.config` (06:14; no such command)<br>• Antiforgery token read from the cookie (08:252; security)<br>• MapStaticAssets is .NET 9, and the content-hash claim (09)<br>• IStartupFilter for MVC filters (10:10)<br>• SA_PASSWORD fails complexity (19:87)<br>• CoreWCF "officially supported" and the 161 vs 181 contradiction (20)<br>• Async expression body that doesn't compile (26:53)<br>• Uri as MarshalByRefObject and the 141 contradiction (28)<br>• Upgrade Assistant shown as current (01:221)<br>Cross-file conflicts: library TFM (KB 01 vs build-and-packages), log4net (KB 12 vs logging.md), migrations in the entrypoint (KB 19).<br>Also list the unchecked version pins. | DM new reference/kb-errata.md | C/V |

## C. Porting engines

**Other engines**

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| C1 | High | Add GitHub Copilot app modernization as an engine option. It covers WinForms, WPF, Web Forms and Blazor (WCF and ASMX are not listed) and needs VS 2026 or VS 2022 17.14.16+. | DM engines.md, MA tools-landscape.md | V |

**AWS Transform**

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| C2 | High | AWS Transform CLI for .NET went GA on 2026-09-09 (inside AWS Transform custom, 8 Regions, scriptable in pipelines). Kiro Power is another way in. | DM engines.md, MA tools-landscape.md | V |
| C3 | High | Quota: 1M lines of code per Region per month (adjustable); 5 concurrent web jobs, 10 VS-extension jobs. Check the estate total against it. | DM engines.md, MA plan | V |
| C4 | High | Pricing: 50,000 agent minutes a month free (no carry-over), then $0.035 per minute. | DM engines.md, MA estimate notes | V |
| C5 | High | Add the AWS Transform SQL Server → Aurora PostgreSQL agent and the full-stack Windows agent. They overlap the DB porting agent, so one engine per project. | DM engines.md Choosing + DB section, MA tools-landscape.md | V |
| C6 | Med | Preview labels: WinForms, WPF, Xamarin, VB.NET. Windows services and worker services are not listed. | DM engines.md | V |
| C7 | Med | The new .NET agent is not in the web console. Use the IDE for medium or higher complexity. | DM engines.md | V |
| C8 | Med | Label each exclusion-list item as documented or inferred (ViewState, MongoDB driver and ASMX-in-UI are not in the docs). | DM engines.md | V |
| C9 | Low | Add: Azure-to-AWS conversion, local build check before the remote build, ported unit tests in the report, S3 upload as a source, private packages local for the IDE. | DM engines.md | V |

**DevTx toolkit**

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| C10 | High | DevTx pushes `<branch>-itr-N` and opens PRs on the repo's remote. Require a sandbox remote. | DM engines.md, workflow.md | C |
| C11 | High | Data egress: Kiro may process data outside the Region, and the Bedrock summary runs in us-east-1. Tell the client. | DM engines.md, SKILL.md principles | C |
| C12 | High | DevTx doesn't support WinForms, WPF or WF. | DM engines.md Choosing | C |
| C13 | High | Solution selection: the docs say a blank field uses the first .sln, but the code upgrades every csproj/vbproj in the tree. Only a root-level .sln is accepted. A custom build script replaces the build and skips tests. | DM engines.md, verify.py target_of | C |
| C14 | Med | Deployment prerequisites: Node 22, Yarn 4, CDK ≥ 2.190, bootstrap, 2 EIPs + 1 VPC, Cognito, Kiro Pro licence and Region. Kiro credential fail-fast; .sqlite3 upload. | DM engines.md, install_prerequisites.py | C |
| C15 | Med | DevTx never asks the user. Its decisions show only in summary.md and the diff, so review both. | DM engines.md | C |
| C16 | Med | DevTx sources include .NET Core 1.0 to 3.1 and .NET 5 to 7, but the skill sends those to a manual TFM bump. | DM workflow.md | C |
| C17 | Med | Iteration artifacts (iteration-N logs, summary.md, report.json) and the API to fetch them. The confidence score is not evidence: it scores a skipped build and a no-test run as success. | DM engines.md, report.py | C |
| C18 | Med | DevTx builds with WarningLevel=0, and no test project counts as a pass. Any TFM other than 6, 7, 8 or 10 silently becomes net8. It forces one TFM (no netstandard), and build arguments are never passed. | DM engines.md, verification.md | C |
| C19 | Med | Private NuGet feeds are commented out of the DevTx image. Main-branch auto-tracking re-runs jobs. | DM engines.md | C |
| C20 | Low | The DevTx prompt says WCF → REST or gRPC; the skill says CoreWCF or SoapCore. Review WCF output against the playbook. | DM engines.md, wcf-services.md | C |
| C21 | Low | Cost (Kiro about $177 a month vs AWS Transform about $308), throughput, comparator scope, pins (Upgrade Assistant 1.0.518; install_prerequisites installs it unpinned), and Upgrade Assistant's deprecation as a DevTx risk. | DM engines.md, install_prerequisites.py | C |

## D. Port playbooks

**New playbooks**

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| D1 | High | New web-api.md (Web API 2 → ASP.NET Core): ApiController, IHttpActionResult and HttpResponseMessage, RoutePrefix, DelegatingHandler, exception handlers and filters, CORS, formatters, OData, ReferenceLoopHandling. | DM new playbook | V |
| D2 | High | New mvc.md: areas need an explicit `{area:exists}` route. Also GlobalFilters → options.Filters, child actions and RenderAction → ViewComponents, HtmlHelpers, _ViewStart and _ViewImports. | DM new playbook | V |
| D3 | Med | Swagger: Swashbuckle.Core and Examples → Swashbuckle.AspNetCore or built-in OpenAPI. OpenAPI 3.1 is the .NET 10 default and WithOpenApi is deprecated. Client impact. | DM web-api.md | V |
| D4 | High | New signalr.md: no hub proxies, `@microsoft/signalr`, client JS changes, Redis backplane, ALB stickiness and WebSockets. | DM new playbook | V |
| D5 | High | New reporting.md: ReportViewer/RDLC has no Microsoft port (ReportViewerCore is community-only); Crystal has no .NET 10 statement. Options: keep on Windows, SSRS on EC2, or replace. Add a 7 Rs decision. | DM new playbook, MA seven-rs.md | V |
| D13 | Med | New .NET 10 breaking-changes reference: cookie auth returns 401/403 on API endpoints, OpenAPI 3.1, Razor runtime compilation obsolete, PipeReader JSON converters. | DM new reference/breaking-changes.md | V |

**Expanded playbooks**

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| D6 | High | Expand the remoting playbook: classification tree, MarshalByRefObject, BinaryFormatter DTO rework, AppDomain → AssemblyLoadContext or a process, channels → gRPC / named pipes / StreamJsonRpc, [OneWay] → SQS, [Synchronization], exception → status map. | DM ambient-context-and-remoting.md | C |
| D7 | High | Distributed transactions (MSDTC, TransactionScope across resources): treat as unsupported on Linux until tested; redesign with an outbox or saga. | DM wcf-services.md, ambient-context-and-remoting.md | U (leans unsupported) |
| D8 | Med | Fix paths for Thread.Abort, AppDomain and CAS. Check Thread.Abort separately. | DM background-work.md, ambient-context-and-remoting.md | V/U |
| D9 | High | EF6 → EF Core steps: options constructor, DbEntityEntry → EntityEntry, [Index] → HasIndex, SqlQueryRaw, __MigrationHistory baseline, keep index names, lazy loading, concurrency. Also the stay-on-EF6 6.5.2 option. | DM raw-sql-and-data-access.md | V |
| D10 | Med | Dapper patterns. Microsoft.Data.SqlClient 4+ defaults to Encrypt=true, which causes TLS failures on Linux. | DM raw-sql-and-data-access.md | C |
| D11 | Med | NHibernate: dialect and driver, session per request, FluentMigrator. | DM raw-sql-and-data-access.md | U (pins) |
| D12 | Med | Web Forms: add Microsoft's "keep on .NET Framework on Windows" route, a third-party control vendor inventory (Telerik, DevExpress, Infragistics, Syncfusion), and Blazor Server operations (sticky sessions, circuits, Data Protection keys). | DM webforms-ui.md | V |
| D14 | Med | Auth: choose the target (AWS Managed Microsoft AD, IAM Identity Center or Cognito). OWIN cookie and Identity 2 schema backfill, antiforgery, JWT, claims transformation. | DM auth.md | C |
| D15 | Med | OWIN host: IAppBuilder, UseWebApi, OwinMiddleware. | DM http-handlers-and-modules.md | C |
| D16 | Med | Crypto: Rfc2898DeriveBytes (PBKDF2), RSACryptoServiceProvider casts → GetRSAPrivateKey, the *Managed factories. | DM windows-only-apis.md | C |
| D17 | Med | Tests: NUnit 2 → 3 renames, RhinoMocks → Moq or NSubstitute, [ExpectedException]. | DM build-and-packages.md | C |
| D18 | Med | NuGet warnings NU1701, NU1605, NU1608 and NU1902: how to fix each. | DM build-and-packages.md | C |
| D19 | Med | Bundling and static assets: esbuild, asp-append-version, cache headers. | DM startup-and-middleware.md | C |
| D20 | Med | System.Web namespace map (Caching, Hosting, Security). IRegisteredObject → IHostedService, VirtualPathProvider → IFileProvider, Request.Files → IFormFile. | DM systemweb-residue.md, background-work.md | C |
| D21 | Med | WCF clients: WCF client packages ship for .NET 10 (only the server needs CoreWCF). The ClientBase endpoint-name constructor doesn't work without config. Upgrade Assistant adds CoreWCF to client projects. | DM wcf-services.md | V |
| D22 | Low | Desktop: ClickOnce has no confirmed path; installers (WiX, MSI, Authenticode), satellite resource assemblies, serial ports and named pipes. | DM windows-only-apis.md | U |
| D23 | Low | Build: NETSDK1022 duplicate Compile/Content and CS0579 AssemblyInfo. Trace output is lost in containers. ImageSharp 4 needs a licence key; SkiaSharp v4 API changes. | DM build-and-packages.md, logging.md, windows-only-apis.md | U (versions) |

## E. Verification gates

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| E1 | High | Add an output-diff gate for console apps, Windows services, workers and batch jobs (inputs → files or records, compared before and after). | DM verification.md, verify.py | C |
| E2 | High | Residue scan reads markup and wwwroot (.cshtml, .razor, .aspx, .ascx, .master, .asmx, .svc). | DM residue_scan.py | C |
| E3 | High | Gate on NU1701, NU1605 and NU1608. Add a build-log code parser (CS, MSB, CA, SYSLIB, NETSDK). | DM verify.py | C |
| E4 | Med | The TFM gate accepts the plan's target (net8 or net10), not net10 only. | DM verify.py | C |
| E5 | Med | Container and parity gates show "not run" when skipped instead of disappearing. | DM verify.py | C |
| E6 | Med | Optional performance gate (k6 or JMeter) and security gate (`dotnet list package --vulnerable`, SAST). | DM verification.md, verify.py | C |
| E7 | Med | DB gate: run the tests against both engines in dual mode, or state that it is manual (pairs with A2). | DM verify.py | C |
| E8 | Low | Reviewer check for commented-out code and TODO leftovers. | DM verification.md | C |

## F. Detection rules

**Residue rules (residue_rules.json)**

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| F1 | High | Bare `using System.Web;`, HttpContextBase, HttpRequestBase, HttpUtility, HttpPostedFileBase. | DM residue_rules.json | C |
| F2 | High | EF6 residue: System.Data.Entity, SetInitializer, Database.SqlQuery, DbEntityEntry, ObjectContext. | DM residue_rules.json | C |
| F3 | High | WCF server residue: [ServiceContract] / [OperationContract] without CoreWCF, and system.serviceModel config. | DM residue_rules.json | C |
| F4 | High | Bare `using System.Drawing;` plus Image or Color. | DM residue_rules.json, linux_readiness.json | C |
| F5 | High | Dual-mode seam: SqlConnection outside the factory, DbProviderFactories, provider conditionals. | DM residue_rules.json | C |
| F6 | High | T-SQL in strings: TOP(@n), OUTPUT DELETED, MERGE, #temp, lock hints, @@ROWCOUNT, sp_executesql. | DM residue_rules.json | C |
| F7 | High | Lints for refcursor disposal and PL/pgSQL parameter prefixes. | DM residue_rules.json or a script | C |
| F8 | Med | More residue rules:<br>• Swagger symbols, Rhino.Mocks, [ExpectedException]<br>• providerName System.Data.SqlClient, system.runtime.remoting<br>• Remoting symbols (TcpChannel, Activator.GetObject, [OneWay], [Synchronization], ISponsor)<br>• IHostingEnvironment, WebServiceHostFactory<br>• SHA256Managed, RNGCryptoServiceProvider<br>• SqlDependency, SqlException numbers in switch/case<br>• [UIHint], PreApplicationStartMethod<br>• Forward-slash drive paths | DM residue_rules.json | C |

**Linux readiness (linux_readiness.json)**

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| F9 | Med | New checks:<br>• Kestrel bound to loopback (block)<br>• HttpClient without PooledConnectionLifetime<br>• ECS bridge mode + IMDS hop limit<br>• No initProcessEnabled<br>• Upper-case GetFiles patterns<br>• libldap for LDAP<br>• Trace output<br>• SqlClient Encrypt/TrustServerCertificate<br>Partials: Environment.NewLine, Console I/O, health endpoint, local writes | linux_readiness.json (both skills) | V/U |

**Assessment rules (MA)**

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| F10 | High | New detections:<br>• AppFabric and NCache → ElastiCache<br>• Lucene.NET and SolrNet → OpenSearch<br>• Inbound mail (POP3/IMAP) → SES receiving<br>• MassTransit.AmazonSQS<br>• Microsoft.FeatureManagement and web.config toggles → AppConfig (verify)<br>• Low: Keyspaces, RavenDB, Couchbase, Neo4j | MA aws_native.json, rules.json | V/U |
| F11 | Med | Package map entries: NuGet.Core, System.Diagnostics.DiagnosticSource, Grpc.Core, Microsoft.AspNet.WebForms, Swashbuckle.Core/Examples, Rhino.Mocks, ImageSharp 4 licence, Portable.BouncyCastle rename. | MA package_map.json | C |
| F12 | High | Reconcile severities across the three catalogues: Microsoft.AspNet.Mvc/WebApi/Razor (Info, but they block), EF6 (Low), System.Data.SqlClient, WCF, time zones, EventLog, MSDTC, bundling, System.Drawing. | MA rules.json, package_map.json; DM residue_rules.json, linux_readiness.json | C |
| F13 | High | .NET 8 and .NET 9 both lose support on 10 Nov 2026. "Already modern" must check the support date. | MA seven-rs.md rule 3, rules; DM workflow.md | V |

## G. SQL Server to PostgreSQL

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| G1 | High | Add PostgreSQL-only mode: no provider switch, data migration in scope, and a cutover-complete check (no SqlClient refs, no SQL Server connection strings, no dbo, a data-migration artifact). | DM raw-sql playbook, engines.md; MA database-assessment.md | C |
| G2 | High | Table of conversions that change values: DATEADD and DATEDIFF boundaries, CONVERT style codes, FORMAT, ROUND on float, tinyint CHECK 0-255, CAST('' AS int). | DM raw-sql playbook | C |
| G3 | Med | Per-item summary of the 97-item checklist, in our own words. | DM new reference file | C |
| G4 | Med | Smaller points:<br>• char(n) padding and trailing spaces<br>• TransactionScope defaults to Serializable (verify)<br>• EnableLegacyTimestampBehavior and infinity conversions<br>• OUTPUT → RETURNING or a data-modifying CTE<br>• SqlDependency → LISTEN/NOTIFY or polling<br>• IDENTITY_INSERT → OVERRIDING SYSTEM VALUE + setval<br>• JSON functions by PG version (SQL/JSON from 17)<br>• EF Core HasColumnType/DefaultValueSql with SQL Server names<br>• TVP options (array + unnest, jsonb, temp table)<br>• Pool settings (No Reset On Close, PgBouncer) | DM raw-sql playbook | C/V |
| G5 | Med | Babelfish as a decision point, with its limits (Aurora only; no RDS Proxy or IAM auth; CHECKSUM differs; 63-byte identifiers). | MA database-assessment.md, DM engines.md | V |
| G6 | Low | pg_conversion.json entries: sp_getapplock, SCHEMA_NAME, ROUND, SET NOCOUNT, ANSI options. | CD pg_conversion.json | C |

## H. AWS services

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| H1 | Med | Playbook rows for the F10 services (AppFabric/NCache, Lucene/Solr, inbound mail, AppConfig, MassTransit on SQS). | DM aws-managed-services.md, config-and-secrets.md | V/U |
| H2 | Low | ALB affinity for in-process state, static egress IPs (NAT EIP) for partner allowlists, distributed locks, SignalR backplane. | DM linux-and-containers.md, aws-managed-services.md | C |

## I. Housekeeping

| # | Sev | Fix | Where | Src |
|---|---|---|---|---|
| I1 | Med | Keep the linux_readiness.json and .py copies identical in both skills; add a validator check for drift. | scripts/validate_skills.py | C |
| I2 | Low | Send the Linux readiness fixes (A10 to A14, A17, F4, F9) to the standalone linux-readiness skill session. | linux-readiness session | — |
| I3 | Low | Public text names no internal tool or client. The internal DB porting checklist is summarised, not copied. | all | — |
| I4 | Low | Toolkit-side only, not ours: the toolkit's KB copy still has sample passwords. | note | — |

## Reports used

The folder holds 19 reports from three batches.

| Batch | Reports | Used for |
|---|---|---|
| Coverage audits (this afternoon) | AWS services and Transform; Linux readiness; SQL Server to PostgreSQL; general .NET; DevTx toolkit; toolkit workflow vs non-KB docs; KB coverage; KB files 00-28; rule catalogues; tool status check (web) | Every item in this list. |
| KB extracts (inputs to the rule audit) | KB detectable items 00-09, 10-19, 20-28 | They list the 556 detectable items in the KB. The rule-catalogue audit tested each item against our regexes, and its misses are in F. They add no separate items. |
| Source research (this morning, used to build the skills) | DevTx repo inventory; DB porting tool inventory; skills/plugins/folders inventory; Linux readiness catalogue research; local skills sweep; 7 Rs research | They were already folded into the skills when the skills were built. The one gap list among them (xp_cmdshell, EXECUTE AS, T-SQL cursors, WHILE, error numbers 515/4060/8152, ASMX) is now covered: each term appears in the skills. |

## How I'll apply it

1. Check every U item on the web.
2. Make the fixes in `<skills-repo>`, one area at a time.
3. Rerun the validator, the rule-regex compile check, the scripts' `--help`, and the eShop sample.
4. Show you the diff summary.
5. Publish only on your yes: DM 1.1.0, MA 3.1.0, CD patch.
