# Research sources

Researched 2026-10-02. Source IDs (S1…) are cited by `scripts/data/rules.json` (`refs`) and by the references. When a source changes, update the affected rule, the reference page and the date below. The block between the `report:sources` markers is copied into report Appendix A5.

## Facts that drive the design (re-check at every engagement start)

| Fact | Source | Consequence in this skill |
| --- | --- | --- |
| **.NET 8 and .NET 9 support ends 10 Nov 2026.** .NET 10 is LTS (released 11 Nov 2025), supported to 14 Nov 2028. .NET 11 is due Nov 2026 (STS). STS is now 24 months. | S4 | Default target is `net10.0`. Apps on .NET 6/7/8/9 get an "out of / ending support" finding. |
| **.NET Framework 4.6.2 support ends 12 Jan 2027.** 4.7–4.8.1 follow the Windows OS lifecycle. 4.5.2–4.6.1 ended 2022. | S5 | The retained (hybrid) apps target 4.8.1. TFM support status is shown per project. |
| **.NET Upgrade Assistant is deprecated** in favour of GitHub Copilot app modernization. | S3 | Upgrade Assistant appears only as a fallback in the plans. |
| **Porting Assistant for .NET, App2Container, Toolkit for .NET Refactoring and Microservice Extractor are closed to new customers** (7 Nov 2025). Their features moved to **AWS Transform**. | S16 | The plans recommend AWS Transform for .NET. Porting Assistant is not recommended for new work. |
| **AWS Transform for .NET** transforms from .NET Framework 3.5+ to .NET 8 / .NET 10 / .NET Standard. It supports C#, VB.NET (preview), MVC, Web API, Web Forms, WCF and class libraries; WinForms/WPF/Xamarin/ASMX are in preview. It ports Web Forms UI to Blazor and EF code. It cannot transform Web Site projects without a project file, Win32 DLLs or Blazor. Private NuGet packages must be uploaded. | S17, S18 | Rule `INV-WEBSITE-PROJECT`. Private-package findings. Web Forms options mention AWS Transform. |
| **AWS App Runner is closed to new customers** (30 Apr 2026). AWS points to **Amazon ECS Express Mode**. | S19 | App Runner is never a recommended target. |
| **RDS for SQL Server has no CLR on 2017+**, and no FILESTREAM, xp_cmdshell, replication, server triggers or TRUSTWORTHY. **SSIS is not on SQL Server 2025.** SSAS is not on 2022+. **SQL 2025 reporting is Power BI Report Server.** | S11, S12 | Database rules and the RDS/Babelfish/EC2 matrix. |
| **Babelfish** does not support CLR, Service Broker, cross-database DDL, MERGE, full-text, hierarchyid, temporal tables, BULK INSERT, global temp tables, EXECUTE AS and more. **Babelfish Compass** is the official assessment tool. | S13, S14, S15 | Rule `DB-BABELFISH-SYNTAX` and others. A Compass run is always the next step before choosing Babelfish. |
| `System.Drawing.Common` is Windows-only since .NET 6. AppDomains, Remoting, CAS, EnterpriseServices and WF are unavailable. **BinaryFormatter always throws from .NET 9.** | S1, S2, S6 | Linux-readiness and API-portability rules. |
| On Linux, Windows auth needs Negotiate + Kerberos keytab + LDAP for roles. Impersonation is Windows-only. | S8 | Auth rules and open questions. |
| On Linux, ICU drives culture and time zones: Windows time-zone IDs resolve only with ICU, and invariant mode breaks them. | S7 | Time and culture rules; container image guidance. |

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
| S11 | Amazon RDS User Guide — Microsoft SQL Server on Amazon RDS (limitations, versions, time zone, licensing) | Database limits, max databases per instance, HIPAA support |
| S12 | Amazon RDS User Guide — Features not supported and features with limited support (SQL Server) | CLR, FILESTREAM, xp_cmdshell, linked servers, SSIS/SSAS by version |
| S13 | Amazon Aurora User Guide — Differences between Babelfish and SQL Server; T-SQL differences | Babelfish behaviour differences |
| S14 | Amazon Aurora User Guide — Unsupported functionalities in Babelfish | Unsupported T-SQL features (rule DB-BABELFISH-SYNTAX and DB rules) |
| S15 | Babelfish Compass (github.com/babelfish-for-postgresql/babelfish_compass) and AWS Database Blog "Deep dive into Babelfish Compass" | Assessment tool for Babelfish |
| S16 | AWS — .NET Modernization Tools availability change (docs.aws.amazon.com/portingassistant/latest/userguide/dotnet-modernization-tools-availability-change.html) | Porting Assistant / A2C / Microservice Extractor closed to new customers 7 Nov 2025 |
| S17 | AWS Transform User Guide — Modernizing .NET with AWS Transform (docs.aws.amazon.com/transform/latest/userguide/dotnet.html) | Supported versions, project types, limitations |
| S18 | AWS What's New (Dec 2025) — AWS Transform expands .NET transformation capabilities (.NET 10, .NET Standard, Web Forms to Blazor, EF porting) | Web Forms and EF options |
| S19 | AWS App Runner Developer Guide — availability change (closed to new customers 30 Apr 2026; ECS Express Mode recommended) | Hosting targets |
| S20 | CAST Highlight documentation — Portfolio Advisor for AWS Transform; AWS Prescriptive Guidance pattern "Assess application readiness … using CAST Highlight" | Tooling comparison |
| S21 | AWS Optimization and Licensing Assessment (aws.amazon.com/optimization-and-licensing-assessment/) | Cost/licensing model input |
| S22 | AWS Prescriptive Guidance — Migration readiness assessment (MRA) and Assess phase | Report structure (current state, gaps, roadmap) |
| S23 | CoreWCF (github.com/CoreWCF/CoreWCF) and Microsoft .NET Blog "CoreWCF 1.0 has been released" | WCF server on .NET |
<!-- /report:sources -->

## How to refresh

1. At the start of an engagement, re-check the rows in "Facts that drive the design": support dates, tool status and AWS service availability. Fetch only those pages.
2. If a fact changed, update `scripts/data/*.json` (rules, package map, decision targets), this page, and the affected reference. Then rerun `render_references.py`.
3. Record the date at the top of this page.
