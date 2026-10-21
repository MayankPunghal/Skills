> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Verify .NET migration tool status and docs

agent ace79d1a134db09dd

1. VERIFIED - Learn says Upgrade Assistant is "officially deprecated"; no date on page, and "no longer developed" is not stated. - https://learn.microsoft.com/en-us/dotnet/core/porting/upgrade-assistant-overview

2. VERIFIED (scope) / UNCLEAR (WCF, ASMX) - Assess, plan, execute; .NET Framework (any) to .NET 8+ incl. 10; WinForms, WPF, Web Forms, WebForms-to-Blazor covered; WCF and ASMX not listed. Needs VS 2026 or VS 2022 17.14.16+. - https://learn.microsoft.com/en-us/dotnet/core/porting/github-copilot-upgrade/overview

3. VERIFIED - ApiPort "deprecated in favor of binary analysis" with Upgrade Assistant; backend shut down, offline use only. Current successor is the Copilot agent; Platform Compatibility Analyzer after porting. - https://learn.microsoft.com/en-us/dotnet/core/porting/porting-approaches

4. VERIFIED (YARP approach, remote session and remote auth documented), UNCLEAR (.NET 10 support) - Incremental guide uses a YARP proxy in front of the Framework app. Adapters README lists only net6.0, netstandard2.0, net472; no .NET 10 statement. - https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/start ; https://github.com/dotnet/systemweb-adapters

5. VERIFIED (client changes needed), UNCLEAR (dedicated migration guide) - Differences page: ASP.NET Core SignalR "isn't compatible with clients or servers for ASP.NET SignalR"; hub proxies gone; $connection replaced by HubConnectionBuilder; npm package @microsoft/signalr. No step-by-step migration guide found. - https://learn.microsoft.com/en-us/aspnet/core/signalr/version-differences

6. VERIFIED for .NET 10; UNCLEAR for .NET 6-9 (not checked) - .NET 10 items relevant to MVC/Web API: Razor runtime compilation obsolete; cookie auth returns 401/403 for known API endpoints instead of redirect; PipeReader JSON parsing can break custom JsonConverters; OpenAPI 3.1 default; WithOpenApi deprecated. - https://learn.microsoft.com/en-us/aspnet/core/breaking-changes/10/overview ; https://learn.microsoft.com/en-us/dotnet/core/compatibility/10

7. VERIFIED (versions), UNCLEAR (current feature list) - CoreWCF 1.9 targets .NET 10 (EOS Nov 14, 2028); 1.8 also targets .NET 10 (EOS Oct 24, 2026); .NET Framework 4.6.2+ supported. Only 1.0-era gaps listed: other transports, message security beyond Transport, distributed transactions, MSMQ. WS-AtomicTransaction, duplex, NetNamedPipe, cert-store support not documented. - https://dotnet.microsoft.com/en-us/platform/support/policy/corewcf ; https://devblogs.microsoft.com/dotnet/corewcf-v1-released/

8. UNCLEAR, leaning unsupported - No Microsoft Learn statement on MSDTC or Linux found. dotnet/runtime #589 (closed 2020) reports "This platform does not support distributed transactions" for TransactionScope; Linux support not confirmed. - https://github.com/dotnet/runtime/issues/589

9. VERIFIED (AppDomains, Remoting, CAS/security transparency, EnterpriseServices, WF, XSLT script blocks) - Page says "6+", not "5+". CONTRADICTED for WCF client: the page covers only the CoreWCF server, while WCF client packages (System.ServiceModel.Http/NetTcp/Primitives) ship for net10.0. Thread.Abort is not on this page (UNCLEAR). - https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable

10. UNCLEAR - No current Learn page found confirming ClickOnce publishing for WinForms/WPF on .NET 8/9/10. Legacy sample page says ApplicationDeployment / System.Deployment.Application APIs are unsupported on .NET Core and 5+. - https://learn.microsoft.com/en-us/visualstudio/deployment/clickonce-deployment-samples-and-walkthroughs?view=vs-2022

11. UNCLEAR (likely no official path) - No Microsoft port of ReportViewer/RDLC; a June 2025 Microsoft Q&A says Microsoft.Reporting.WinForms is not compatible with .NET 8. Community ReportViewerCore.NETCore 15.1.33 (net10.0 target) is "not supported/developed by Microsoft". Crystal Reports: no .NET 8/10 statement found. - https://www.nuget.org/packages/ReportViewerCore.NETCore/

12. VERIFIED (EF6 6.5.2 .NET 10 compatibility), UNCLEAR ("no active development" wording) - EF 6.5.2 released April 2026 with a .NET 10 fix; EF6 still supported; EF Core is the modern path with a Microsoft porting guide. - https://learn.microsoft.com/en-us/ef/ef6/what-is-new/

13. VERIFIED (announcement), UNCLEAR (CoreWCF output) - Dec 1, 2025 GA: .NET 10 and .NET Standard targets; Web Forms to Blazor UI porting; EF ORM porting (EF versions unspecified). Current docs list WCF, ASMX, WinForms, WPF, Web Forms as supported; CoreWCF output not mentioned. - https://aws.amazon.com/about-aws/whats-new/2025/12/transform-net-transformation-developer-experience ; https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html

14. VERIFIED - Porting Assistant, App2Container, Toolkit for .NET Refactoring and Microservice Extractor stopped accepting new customers starting Nov 7, 2025; existing users continue; AWS Transform is the successor. - https://docs.aws.amazon.com/app2container/latest/UserGuide/dotnet-modernization-tools-availability-change.html

15. VERIFIED - App Runner is "no longer open to new customers" and AWS recommends ECS Express Mode. The April 30, 2026 date comes from AWS wording in a search snippet, not the fetched text. Express Mode announced June 14, 2026; custom task definitions added July 1, 2026. - https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html ; https://www.amazonaws.cn/en/new/2026/announcing-amazon-ecs-express-mode/

16. VERIFIED (name), date UNCLEAR at AWS source - AWS page reads "Amazon WorkSpaces applications (formerly AppStream 2.0)". A third-party post gives an effective date of Nov 6, 2025. - https://aws.amazon.com/appstream2/ ; https://dev.classmethod.jp/articles/amazon-appstream2-rename-to-amazon-workspaces-applications/

17. VERIFIED (still the Windows-only path) - Learn: about 20,000 APIs incl. Configuration and Drawing; use Platform Compatibility Analyzer for Linux. NuGet package has a net10.0 group and no deprecation notice. Learn page dated 2023. - https://learn.microsoft.com/en-us/dotnet/core/porting/windows-compat-pack ; https://www.nuget.org/packages/Microsoft.Windows.Compatibility

18. VERIFIED - Learn Blazor-for-Web-Forms intro: Web Forms "won't be ported to .NET Core or .NET 8"; staying on .NET Framework on Windows is fine. Blazor is the named successor; Razor Pages and DotVVM are community suggestions only. - https://learn.microsoft.com/en-us/dotnet/architecture/blazor-for-web-forms-developers/introduction

19. VERIFIED (via search excerpt; page not fetched) - Learn Newtonsoft migration guide exists with a feature table; STJ is case-sensitive by default; NaN/Infinity need opt-in; heavily attributed code is harder to migrate. - https://learn.microsoft.com/en-us/dotnet/standard/serialization/system-text-json/migrate-from-newtonsoft

20. VERIFIED - NuGet 10.0.13 (Oct 13, 2026) has a net10.0 group; not marked deprecated; description says it is for porting older code and recommends Microsoft.Extensions.Configuration for new work. - https://www.nuget.org/packages/System.Configuration.ConfigurationManager

Surprises
- .NET 8 and .NET 9 both reach end of support Nov 10, 2026, about three weeks away. .NET 9 has not already ended, contrary to my earlier assumption. - https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core
- CoreWCF 1.8 (targets .NET 10) ends Oct 24, 2026, three days away; use 1.9.
- WCF client packages ship for .NET 10, so "WCF unavailable" applies only to the server side.
- AWS Transform lists WCF and ASMX as supported; the Copilot upgrade agent does not list them.
