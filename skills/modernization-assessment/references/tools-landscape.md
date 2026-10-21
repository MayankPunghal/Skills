# Modernization tool landscape (status October 2026)

What exists, what is deprecated, and how this skill relates to each tool. Re-check the "Status" column at engagement start ([sources.md](sources.md)).

| Tool | Status | What it gives you | How this skill uses it |
| --- | --- | --- | --- |
| **AWS Transform for .NET** (successor to Porting Assistant and the Amazon Q Developer .NET transformation) | GA (May 2025). Expanded Dec 2025: .NET 10 and .NET Standard targets, Web Forms → Blazor UI porting, EF porting | Agentic port from .NET Framework 3.5+ / .NET Core 3.1+ to .NET 8 / 10 / .NET Standard. Its own assessment report and plan. Runs as a web app, a Visual Studio extension, and an MCP server for AI assistants. Needs source connectors (GitHub, GitLab, Bitbucket, Azure Repos); private NuGet packages must be uploaded | **Execution tool.** Plans name it for the mechanical port. Limitations become findings (`INV-WEBSITE-PROJECT`, private packages, Win32 DLLs) |
| **AWS Transform custom** | GA | Non-.NET-to-.NET changes, e.g. Web Forms → React | An option in Web Forms plans |
| **Porting Assistant for .NET**, **AWS App2Container**, **AWS Toolkit for .NET Refactoring**, **AWS Microservice Extractor for .NET** | Closed to new customers since 7 Nov 2025 (existing projects can finish) | Compatibility analysis, containerisation, refactoring | **Not recommended for new work.** The package map and rules emulate the compatibility analysis |
| **GitHub Copilot app modernization (for .NET)** | Microsoft's recommended upgrade path (2026) | AI-assisted assessment, plan and upgrade inside Visual Studio / VS Code; Azure-oriented cloud steps | Alternative execution tool; its assessment complements ours |
| **.NET Upgrade Assistant** | **Deprecated**, no longer developed | Project conversion to SDK-style, TFM changes | Fallback only when Copilot / AWS Transform cannot be used |
| **API Portability Analyzer (ApiPort)** | Retired (superseded by Upgrade Assistant analysis, itself deprecated) | API compatibility | Emulated by the rule catalogue; CA1416 after retargeting |
| **.NET platform compatibility analyzer (CA1416)** | Built into the .NET SDK | Compile-time warnings for platform-specific API calls | `validate_linux_build.py --run` on SDK-style net5+ projects |
| **CAST Highlight** (incl. Portfolio Advisor for AWS Transform) / **CAST Imaging** | Commercial | Portfolio cloud-readiness scoring, blockers, AWS service suggestions, architecture visualisation | Optional. The tooling table explains what it adds. graphify provides the free architecture map |
| **graphify** | In use | AST code graph, communities, hubs, query/explain/path/affected, exports, cross-repo merge | `map_graphs.py`; the reviewer queries the graph for reachability and blast radius |
| **codebase-documenter** (sibling skill) | In use | Prerequisites, graph naming, full BA-grade documentation of an application | Prerequisite installer; optional deep documentation of high-risk apps |
| **AWS DMS / DMS Schema Conversion / AWS SCT** | GA | Data migration; schema conversion to PostgreSQL | Named in database plans |
| **AWS Application Migration Service (MGN)** | GA | Agent-based VM replication from any hypervisor (VMware, Hyper-V, Proxmox, physical) | Rehost path for retained apps |
| **AWS Optimization and Licensing Assessment (OLA)** / Migration Evaluator | Free programme | Utilisation-based right-sizing and licence modelling | Cost section: numbers come from here, not from code |
| **AWS DevTx** | Not a product: AWS's Developer Transformation specialist team | Engagement support around AWS Transform and AI-driven development | Mention under engagement support, not as a tool |
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
