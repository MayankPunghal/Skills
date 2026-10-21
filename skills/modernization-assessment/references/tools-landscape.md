# Modernization tool landscape (status October 2026)

What exists, what is deprecated, and how this skill relates to each tool. Re-check the "Status" column at engagement start ([sources.md](sources.md)).

| Tool | Status | What it gives you | How this skill uses it |
| --- | --- | --- | --- |
| **AWS Transform for .NET** (successor to Porting Assistant and the Amazon Q Developer .NET transformation) | GA (May 2025). Expanded Dec 2025: .NET 10 and .NET Standard targets, Web Forms → Blazor UI porting, EF porting | Agentic port from .NET Framework 3.5+ / .NET Core 3.1+ to .NET 8 / 10 / .NET Standard. Its own assessment report and plan. Runs as a web app, a Visual Studio extension, the ATX CLI (`atx custom def exec -n AWS/dotnet-modernization`), a Kiro power, and an MCP server for AI assistants. Source: GitHub, GitLab, Bitbucket, Azure Repos / Azure DevOps through a connector (one per job, approved by the AWS admin), an S3 zip or a direct upload; private NuGet packages are uploaded or resolved with its helper script. Reports: Excel, HTML, Markdown, CSV and JSON assessment (complexity low to critical, a Linux readiness rating); an HTML transformation report and `NextSteps.md`. Quotas: 1M lines per Region per month, 5 web and 10 Visual Studio jobs at once. Price: 50,000 agent minutes a month included, no published rate above that ([sources.md](sources.md), S26-S28). The client must agree to its data handling first (service-improvement opt-out, Region and inference routing) | **Execution tool.** Plans name it for the mechanical port. Limitations become findings (`INV-WEBSITE-PROJECT`, private packages, Win32 DLLs) |
| **AWS Transform SQL Server modernization** | GA (2026) | SQL Server 2008 R2-2022 to Aurora PostgreSQL 15+: schema, T-SQL to PL/pgSQL, triggers, identity, the .NET data-access code (EF 6.3-6.5, EF Core, ADO.NET) and connection strings, with synthetic data and equivalence checks. Apps on .NET 6-10 only, no VB.NET, one account and Region per job, PostgreSQL only | An option in the database narrative for apps already on .NET 6+; the DB team owns the generated objects |
| **AWS Transform full-stack Windows / Azure to AWS / containers** | GA (2026; Cosmos DB to DynamoDB in preview) | One job across .NET code, SQL Server and deployment; Azure Functions, Blob, Queue and Cosmos DB code to Lambda, S3, SQS and DynamoDB; container images with ECS (Terraform) or EKS (Helm) deployment | Named where they fit; one engine per project still applies |
| **Babelfish for Aurora PostgreSQL** and **Babelfish Compass** | GA | SQL Server clients connect to Aurora PostgreSQL with T-SQL and the TDS protocol, with few code changes; Compass reports which T-SQL Babelfish supports. AWS DMS does full load only (no CDC) into a Babelfish target | An alternative the DB team may weigh; the skill's scenarios stay `dual`, `postgresql` and `none` ([database-assessment.md](database-assessment.md)) |
| **AWS Transform custom** | GA | Non-.NET-to-.NET changes, e.g. Web Forms → React | An option in Web Forms plans |
| **Porting Assistant for .NET**, **AWS App2Container**, **AWS Toolkit for .NET Refactoring**, **AWS Microservice Extractor for .NET** | Closed to new customers since 7 Nov 2025 (existing projects can finish) | Compatibility analysis, containerisation, refactoring | **Not recommended for new work.** Some AWS Prescriptive Guidance pages still recommend Porting Assistant and App2Container: ignore that part. The package map and rules emulate the compatibility analysis |
| **GitHub Copilot app modernization (for .NET)** | Microsoft's recommended upgrade path (2026). Needs Visual Studio 2026 or Visual Studio 2022 17.14.16 or later | AI-assisted assessment, plan and upgrade inside Visual Studio / VS Code; Azure-oriented cloud steps. Covers .NET Framework (any version) to .NET 8 or later, including .NET 10; WinForms, WPF, Web Forms and Blazor (Web Forms to Blazor) are covered. WCF and ASMX are not listed, so check them by hand | Alternative execution tool; its assessment complements ours |
| **.NET Upgrade Assistant** | **Deprecated**, no longer developed | Project conversion to SDK-style, TFM changes | Fallback only when Copilot / AWS Transform cannot be used |
| **API Portability Analyzer (ApiPort)** | Deprecated in favour of binary analysis (Upgrade Assistant); backend shut down, offline use only | API compatibility | Successors: GitHub Copilot app modernization (assessment and upgrade) and the .NET platform compatibility analyzer (CA1416) after retargeting. Emulated by the rule catalogue |
| **.NET platform compatibility analyzer (CA1416)** | Built into the .NET SDK | Compile-time warnings for platform-specific API calls | `validate_linux_build.py --run` on SDK-style net5+ projects |
| **CAST Highlight** (incl. Portfolio Advisor for AWS Transform) / **CAST Imaging** | Commercial | Portfolio cloud-readiness scoring, blockers, AWS service suggestions, architecture visualisation | Optional. The tooling table explains what it adds. graphify provides the free architecture map |
| **graphify** | In use | AST code graph, communities, hubs, query/explain/path/affected, exports, cross-repo merge | `map_graphs.py`; the reviewer queries the graph for reachability and blast radius |
| **codebase-documenter** (sibling skill) | In use | Prerequisites, graph naming, full BA-grade documentation of an application | Prerequisite installer; optional deep documentation of high-risk apps |
| **AWS DMS / DMS Schema Conversion / AWS SCT** | GA | Data migration; schema conversion to PostgreSQL | Named in database plans |
| **AWS Application Migration Service (MGN)** | GA | Agent-based VM replication from any hypervisor (VMware, Hyper-V, Proxmox, physical) | Rehost path for retained apps |
| **AWS Optimization and Licensing Assessment (OLA)** / Migration Evaluator | Free programme | Utilisation-based right-sizing and licence modelling | Cost section: numbers come from here, not from code |
| **AWS DevTx** | AWS's Developer Transformation specialist team; ships the **Version Upgrade Toolkit on AWS** (CDK-deployed web app) | Runs Microsoft Upgrade Assistant, then the Kiro CLI agent driven by a .NET migration knowledge base (project files, System.Web, Web Forms to Razor / Blazor, WCF to CoreWCF, remoting, crypto, config, logging, data access, Linux containers), in iterations with a build gate; AWS Transform custom (`atx`) recipes for Java | An execution option for the port, next to AWS Transform; its knowledge base does not cover AWS managed-service swaps (SES, ElastiCache, S3, OpenSearch) |
| **Microsoft.AspNetCore.SystemWebAdapters + YARP** | Supported | Incremental (strangler-fig) ASP.NET → ASP.NET Core migration; shared auth/session | Hybrid and incremental plans |
| **CoreWCF** | Supported (open source, .NET Foundation) | WCF server on .NET (BasicHttp, NetTcp, WSHttp, partial WS-*) | WCF plans |

## What tools find vs what needs people (report: tooling category)

**Tools find:**
- API and package incompatibilities;
- project-format problems;
- many configuration issues;
- architecture shape.

**People must decide:**
- whether a hit is reachable;
- the business meaning of integrations;
- direction of data flows;
- what lives on servers (scheduled tasks, IIS, certificates, firewall rules);
- licensing and Retire decisions;
- workflow-level testing.

The report says this explicitly, so the client understands why the open questions matter.
