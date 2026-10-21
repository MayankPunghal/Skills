# Research sources

Researched 2026-10-02; AWS Transform, pricing, Lambda and Prescriptive Guidance facts re-checked 2026-10-21. Source IDs (S1…) are cited by `scripts/data/rules.json` (`refs`) and by the references. When a source changes, update the affected rule, the reference page and the date below. The block between the `report:sources` markers is copied into report Appendix A5.

## Facts that drive the design (re-check at every engagement start)

| Fact | Source | Consequence in this skill |
| --- | --- | --- |
| **.NET 8 and .NET 9 support ends 10 Nov 2026.** .NET 10 is LTS (released 11 Nov 2025), supported to 14 Nov 2028. .NET 11 is due Nov 2026 (STS). STS is now 24 months. | S4 | Default target is `net10.0`. Apps on .NET 6/7/8/9 get an "out of / ending support" finding. |
| **.NET Framework 4.6.2 support ends 12 Jan 2027.** 4.7–4.8.1 follow the Windows OS lifecycle. 4.5.2–4.6.1 ended 2022. | S5 | The retained (hybrid) apps target 4.8.1. TFM support status is shown per project. |
| **.NET Upgrade Assistant is deprecated** in favour of GitHub Copilot app modernization. | S3 | Upgrade Assistant appears only as a fallback in the plans. |
| **Porting Assistant for .NET, App2Container, Toolkit for .NET Refactoring and Microservice Extractor are closed to new customers** (7 Nov 2025). Their features moved to **AWS Transform**. | S16 | The plans recommend AWS Transform for .NET. Porting Assistant is not recommended for new work. |
| **AWS Transform for .NET** transforms from .NET Framework 3.5+ to .NET 8 / .NET 10 / .NET Standard. It supports C# and VB.NET; class libraries, console, MVC, Web API, Web Forms, WCF, ASMX, unit tests, WinForms, WPF and Xamarin. The user guide history (15 Oct 2026) removed the preview label for VB.NET, WinForms, WPF and Xamarin; the FAQ still says preview, so confirm with AWS. It ports Web Forms UI to Blazor and EF code. It cannot transform Web Site projects without a project file, Win32 DLLs without core-compatible libraries, or repositories with no solution; a search snippet says it does not transform Blazor UI components (not on the fetched pages). Private NuGet packages are resolved by upload, a helper script or an Azure DevOps artifact connector. | S17, S18 | Rule `INV-WEBSITE-PROJECT`. Private-package findings. Web Forms options mention AWS Transform. |
| **AWS Transform limits and price.** 1,000,000 lines of .NET code per Region per month; 5 concurrent web jobs and 10 Visual Studio jobs; up to 5,000 repositories per web job. The .NET agent includes 50,000 agent minutes a month at no charge and no rate above that is published; **$0.035 per minute is the custom agent's rate, not the .NET agent's**. Minutes are billed in 1-minute increments while the agent works. | S26, S27 | Estimates quote the free quota and say any extra cost is to be confirmed with AWS; large estates are planned in monthly waves under the line quota. |
| **AWS Transform data handling.** Content may be used for service improvement, including model training, unless the account opts out (AWS Organizations AI services opt-out policy; an AWS Toolkit setting in Visual Studio). Source code is purged after the job. Data stays in the workspace's Region, but inference can be routed within the geography (from Mumbai, Seoul and Canada (Central) to any commercial Region). | S28 | The report's AWS Transform option lists these points as client decisions before the first job. |
| **AWS Transform has more agents than .NET:** SQL Server to Aurora PostgreSQL 15+ (apps on .NET 6-10 only, C# only, EF 6.3-6.5 / EF Core / ADO.NET; converts schema, procedures and the data-access code; PostgreSQL only); full-stack Windows (code, database and deployment in one job); Azure-to-AWS code conversion (Functions to Lambda, Blob to S3, Queue to SQS, Cosmos DB to DynamoDB in preview); containerization (ECS with Terraform or EKS with Helm). | S29 | The database narrative names the SQL Server agent as an option for apps already on .NET 6+; .NET Framework apps are ported first. |
| **Lambda .NET runtimes:** `dotnet8` deprecated 10 Nov 2026 (creating functions blocked 29 Jul 2027, updates 31 Aug 2027); `dotnet9` is container-image only and deprecated 10 Nov 2026; `dotnet10` supported to 14 Nov 2028. | S30 | Lambda targets use `dotnet10`; functions on `dotnet8` get an end-of-support finding. |
| **Windows vs Linux licence cost (AWS example):** m5.xlarge, us-east-1, on-demand: Windows licence included about $274.48 a month vs Linux about $140.16 (49% less). SQL Server Enterprise on EC2 about $2,835 a month vs Aurora PostgreSQL about $1,032 (r6i/r6g.2xlarge). These are AWS's published examples; vendor savings claims ("up to 70%", "5x faster") have no baseline and are labelled as vendor claims. | S31, S32 | The cost section quotes these only as examples with their source; real numbers come from OLA / Migration Evaluator. |
| **AWS App Runner is closed to new customers** (30 Apr 2026). AWS points to **Amazon ECS Express Mode**. | S19 | App Runner is never a recommended target. |
| **PostgreSQL has no CLR, Service Broker, hierarchyid or FILESTREAM equivalents**; T-SQL procedures become PL/pgSQL functions or procedures, and MERGE, temp tables, identity and error handling differ. **AWS DMS Schema Conversion** converts most tables and simple routines; complex routines need hand rewrite. | S11, S12 | Database rules and the dual / PostgreSQL scenario hours. |
| `System.Drawing.Common` is Windows-only since .NET 6. AppDomains, Remoting, CAS, EnterpriseServices and WF are unavailable. **BinaryFormatter always throws from .NET 9.** | S1, S2, S6 | Linux-readiness and API-portability rules. |
| On Linux, Windows auth needs Negotiate + Kerberos keytab + LDAP for roles. Impersonation is Windows-only. | S8 | Auth rules and open questions. |
| On Linux, ICU drives culture and time zones: Windows time-zone IDs resolve only with ICU, and invariant mode breaks them. | S7 | Time and culture rules; container image guidance. |
| MediatR 13+ and AutoMapper 15+ (2025) are dual-licensed RPL-1.5 / commercial; MassTransit 9+ is commercial. Upgrading these during a port is a licence decision. ASP.NET Core validates DI scopes in Development, so captive dependencies fail at startup. | S24, S25 | Online licence-history check (any package); offline package-map hint; di-wiring findings. |

<!-- report:sources -->
| ID | Source | Used for |
| --- | --- | --- |
| S1 | Microsoft Learn — .NET Framework technologies unavailable on .NET 6+ (learn.microsoft.com/dotnet/core/porting/net-framework-tech-unavailable) | AppDomains, Remoting, CAS, EnterpriseServices, WF, XSLT script, multi-module assemblies |
| S2 | Microsoft Learn — Unsupported APIs on .NET Core and .NET 5+ (learn.microsoft.com/dotnet/core/compatibility/unsupported-apis) | APIs that throw PlatformNotSupportedException (ProtectedData, CNG/CSP, Thread.Abort, CodeDom, BinaryFormatter …) |
| S3 | Microsoft Learn — Upgrade .NET apps overview (learn.microsoft.com/dotnet/core/porting/) | Upgrade paths; GitHub Copilot app modernization; Upgrade Assistant deprecated; Windows Compatibility Pack |
| S4 | Microsoft — .NET and .NET Core support policy (dotnet.microsoft.com/platform/support/policy/dotnet-core) | Support dates for .NET 6-11 |
| S5 | Microsoft — .NET Framework support policy (dotnet.microsoft.com/platform/support/policy/dotnet-framework) | Support dates for .NET Framework versions |
| S6 | Microsoft Learn — System.Drawing.Common only supported on Windows (.NET 6 breaking change) | Imaging alternatives: SkiaSharp, ImageSharp, Aspose.Drawing, Microsoft.Maui.Graphics |
| S7 | Microsoft Learn — Globalization and ICU (learn.microsoft.com/dotnet/core/extensions/globalization-icu) | Culture/sorting differences, time-zone ID conversion, invariant mode, ICU in containers |
| S8 | Microsoft Learn — Configure Windows Authentication in ASP.NET Core (aspnetcore-10.0) | Negotiate/Kerberos on Linux, keytab, LDAP roles, impersonation Windows-only |
| S9 | Microsoft Learn — Migrate from ASP.NET Framework to ASP.NET Core (incremental migration, System.Web adapters, YARP) | Incremental vs in-place migration; session/auth sharing |
| S10 | AWS Prescriptive Guidance — Migration strategies (the 7 Rs) (docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html) | 7R definitions |
| S11 | AWS DMS Schema Conversion user guide - converting SQL Server to PostgreSQL (supported objects, manual-action items) | Which T-SQL converts automatically and what needs hand rewrite |
| S12 | AWS Prescriptive Guidance - Migrate SQL Server databases to PostgreSQL (T-SQL to PL/pgSQL patterns) | Construct-by-construct conversion guidance |
| S13 | Npgsql and EF Core PostgreSQL provider documentation | Data-access changes (types, `DateTime` kinds, case sensitivity) |
| S14 | PostgreSQL documentation - differences from T-SQL (identity, MERGE, temp tables, transactions, procedures vs functions) | Rules for T-SQL constructs that need rework |
| S15 | EF Core documentation - supporting multiple providers (dual-database applications) | Dual-database abstraction approach |
| S16 | AWS — .NET Modernization Tools availability change (docs.aws.amazon.com/portingassistant/latest/userguide/dotnet-modernization-tools-availability-change.html) | Porting Assistant / A2C / Microservice Extractor closed to new customers 7 Nov 2025 |
| S17 | AWS Transform User Guide — Modernizing .NET with AWS Transform (docs.aws.amazon.com/transform/latest/userguide/dotnet.html) | Supported versions, project types, limitations |
| S18 | AWS What's New (Dec 2025) — AWS Transform expands .NET transformation capabilities (.NET 10, .NET Standard, Web Forms to Blazor, EF porting) | Web Forms and EF options |
| S19 | AWS App Runner Developer Guide — availability change (closed to new customers 30 Apr 2026; ECS Express Mode recommended) | Hosting targets |
| S20 | CAST Highlight documentation — Portfolio Advisor for AWS Transform; AWS Prescriptive Guidance pattern "Assess application readiness … using CAST Highlight" | Tooling comparison |
| S21 | AWS Optimization and Licensing Assessment (aws.amazon.com/optimization-and-licensing-assessment/) | Cost/licensing model input |
| S22 | AWS Prescriptive Guidance — Migration readiness assessment (MRA) and Assess phase | Report structure (current state, gaps, roadmap) |
| S23 | CoreWCF (github.com/CoreWCF/CoreWCF) and Microsoft .NET Blog "CoreWCF 1.0 has been released" | WCF server on .NET |
| S24 | Microsoft Learn — Dependency injection in ASP.NET Core (service lifetimes, scope validation, keyed services) (learn.microsoft.com/aspnet/core/fundamentals/dependency-injection) | Captive dependencies (scope validation throws in Development), composition root, keyed services replacing named registrations |
| S25 | Lucky Penny Software (MediatR / AutoMapper commercial licensing, July 2025) and MassTransit v9 announcement (massient / masstransit.io) | MediatR 13+ and AutoMapper 15+ dual RPL-1.5 / commercial; MassTransit 9+ commercial, v8 open source with support through 2026 |
| S26 | AWS Transform User Guide — limits (docs.aws.amazon.com/transform/latest/userguide/transform-limits.html) and the .NET web app page (dotnet-web-app.html) | Line, job and repository quotas |
| S27 | AWS Transform pricing (aws.amazon.com/transform/pricing/) | Free agent minutes, the custom agent's per-minute rate, billing increments |
| S28 | AWS Transform User Guide — service improvement, data protection, data encryption, cross-Region processing and Regions pages; AWS Transform FAQ (aws.amazon.com/transform/faq/) | Opt-out, retention, encryption, residency, ownership of ported code |
| S29 | AWS Transform User Guide — SQL Server modernization (sql-server-modernization.html), full-stack Windows (windows-full-stack.html), Azure to AWS (dotnet-azure-to-aws.html), containers (transform-containers.html) | The other AWS Transform agents and their limits |
| S30 | AWS Lambda Developer Guide — Lambda runtimes (docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html) | .NET runtime deprecation dates |
| S31 | AWS Prescriptive Guidance — Optimize costs for Microsoft workloads: refactor .NET to Linux (net-refactor-linux.html) and modernize SQL Server (modernize-sql-server.html) | Windows vs Linux and SQL Server vs Aurora PostgreSQL cost examples; Babelfish and Babelfish Compass; DMS full load only to Babelfish |
| S32 | AWS Transform for Windows product page (aws.amazon.com/transform/windows/) | Vendor marketing claims (label them as such) |
| S33 | Amazon ElastiCache User Guide (docs.aws.amazon.com/AmazonElastiCache/latest/dg/) | Distributed cache target for AppFabric and NCache (Valkey or Redis OSS) |
| S34 | Amazon OpenSearch Service Developer Guide (docs.aws.amazon.com/opensearch-service/latest/developerguide/) | Search target for Lucene.NET and SolrNet |
| S35 | Amazon SES Developer Guide — receiving email (docs.aws.amazon.com/ses/latest/dg/receiving-email.html) | Inbound mail (POP3/IMAP polling) to SES receiving; Region support to check |
| S36 | AWS AppConfig User Guide — feature flags (docs.aws.amazon.com/appconfig/latest/userguide/) | Feature-flag configuration profiles |
| S37 | MassTransit documentation — Amazon SQS transport (masstransit.io/documentation/transports/amazon-sqs) | MassTransit on SQS and SNS |
| S38 | AWS database services: Amazon Keyspaces, DocumentDB, Neptune developer guides (docs.aws.amazon.com) | Targets for Cassandra, document stores and graph databases |
<!-- /report:sources -->

## How to refresh

1. At the start of an engagement, re-check the rows in "Facts that drive the design": support dates, tool status and AWS service availability. Fetch only those pages.
2. If a fact changed, update `scripts/data/*.json` (rules, package map, decision targets), this page, and the affected reference. Then rerun `render_references.py`.
3. Record the date at the top of this page.
