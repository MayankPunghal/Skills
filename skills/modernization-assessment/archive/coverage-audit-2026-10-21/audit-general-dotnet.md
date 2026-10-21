> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Audit general .NET modernization coverage

agent aa09a3f1380e93880

READ-ONLY COVERAGE AUDIT. No files were created, edited or deleted. The research archive was not saved to, because that would have written a file.

Scope: dotnet-modernization (SKILL.md, reference/*.md, all 17 playbooks, KB headings and greps) and modernization-assessment (tools-landscape, target-platforms, modernisation-challenges, seven-rs, rule IDs in rules.json and residue_rules.json). Web claims were checked by a research subagent against Microsoft Learn, devblogs, GitHub, AWS and NuGet.

HIGH

1. Engine choice omits GitHub Copilot app modernization. dotnet-modernization/reference/engines.md lists only DevTx, AWS Transform and Claude, while tools-landscape.md calls Copilot Microsoft's recommended path. Its scope covers WinForms, WPF, Web Forms and Blazor, but WCF and ASMX are not listed. https://learn.microsoft.com/en-us/dotnet/core/porting/github-copilot-upgrade/overview
2. Reporting has no execution playbook. ReportViewer/RDLC and Crystal appear only as assessment rules (WEB-REPORTVIEWER, INT-CRYSTAL), with zero hits in dotnet-modernization. No Microsoft port exists; Microsoft.Reporting.WinForms is not compatible with .NET 8, and ReportViewerCore is community-only. Hold in: new playbook reporting.md, with a decision in seven-rs.md. https://www.nuget.org/packages/ReportViewerCore.NETCore/
3. Non-HTTP workloads have no verification gate. Gates in verification.md are build, tests, residue, container and HTTP parity. Console apps, Windows services/workers, class libraries and batch file outputs get no characterization or output-diff gate. Hold in: verification.md. (practice) https://learn.microsoft.com/en-us/dotnet/core/porting/
4. Distributed transactions have no playbook. DATA-DISTRIBUTED-TX (Medium) has no fix path, and KB 28 covers it only inside remoting. Microsoft has no Linux/MSDTC statement on Learn. Treat as unsupported until tested. Hold in: wcf-services.md and ambient-context-and-remoting.md. https://github.com/dotnet/runtime/issues/589 ; https://devblogs.microsoft.com/dotnet/corewcf-v1-released/
5. ASP.NET SignalR is uncovered. WEB-SIGNALR-LEGACY is High, but no playbook or KB file gives a fix. Hub proxies are gone and the client moves to @microsoft/signalr, so client JS must change. Hold in: webforms-ui.md or a new signalr.md. https://learn.microsoft.com/en-us/aspnet/core/signalr/version-differences

MED

6. Web Forms "keep on .NET Framework" option is missing from webforms-ui.md. Microsoft says Web Forms will not be ported and staying on Framework on Windows is fine. DotVVM is only a community suggestion. Hold in: webforms-ui.md route table. https://learn.microsoft.com/en-us/dotnet/architecture/blazor-for-web-forms-developers/introduction
7. MVC child actions, ViewComponent and HtmlHelper are absent. KB 03 has zero Html.Action, RenderAction or ChildActionOnly text, though WEB-CHILD-ACTION exists. kb/ is a licensed copy, so put the guidance in playbooks/. Hold in: a new MVC section in playbooks/. https://learn.microsoft.com/en-us/aspnet/core/mvc/views/view-components (not fetched)
8. Web API 2 gaps in kb/04: IHttpActionResult and HttpResponseMessage return types, DelegatingHandler message handlers, CORS, custom formatters, OData. Hold in: playbooks/ (kb copy stays unchanged). https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/
9. Thread.Abort, AppDomain and Code Access Security exist only as assessment rules (API-THREAD-ABORT, API-APPDOMAIN, API-CAS) with no fix path. AppDomains and CAS are confirmed on the unavailable-technologies page; Thread.Abort is not on that page and must be checked separately. Hold in: background-work.md and ambient-context-and-remoting.md. https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable
10. .NET 10 breaking changes are not listed anywhere. build-and-packages.md says "read its breaking changes", but the skill gives no list. Items that matter: cookie auth returns 401/403 on API endpoints instead of redirecting (affects auth.md); OpenAPI 3.1 default and WithOpenApi deprecated (affects kb/23 Swashbuckle); Razor runtime compilation obsolete. Hold in: a new reference/breaking-changes.md. https://learn.microsoft.com/en-us/aspnet/core/breaking-changes/10/overview
11. Support dates are not checked. .NET 8 and .NET 9 both reach end of support on 10 Nov 2026, three weeks away. seven-rs.md rule 3 treats any net5+ app as "already modern" with no end-of-support check. Hold in: seven-rs.md draft rules and workflow.md modern-app path. https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core
12. Third-party UI control licensing has one gotcha line. Telerik, DevExpress, Infragistics and Syncfusion have no inventory or per-vendor .NET 10 status step. Hold in: webforms-ui.md. (practice)
13. Desktop deployment: ClickOnce has no path. The Learn sample page calls the legacy deployment APIs unsupported on .NET 5+, and no current page confirms ClickOnce publishing for WinForms/WPF on .NET 8-10. BUILD-INSTALLER is a decision only. Hold in: windows-only-apis.md. https://learn.microsoft.com/en-us/visualstudio/deployment/clickonce-deployment-samples-and-walkthroughs?view=vs-2022
14. Performance and security gates are absent. No load or performance gate exists (no k6 or JMeter), and no SAST or dependency-vulnerability gate exists in verify.py. Hold in: verification.md.

LOW

15. Satellite resource assemblies: zero hits.
16. Serial ports and named pipes outside CoreWCF: zero hits in dotnet-modernization (NetNamedPipe appears only in wcf-services.md).
17. Code signing and installers (WiX, MSI, Authenticode): decision-only.

OUTDATED OR WRONG

A. tools-landscape.md row for API Portability Analyzer says "superseded by Upgrade Assistant analysis". Microsoft says ApiPort was deprecated in favour of binary analysis, with the Copilot agent and Platform Compatibility Analyzer as successors, and its backend is shut down (offline use only). https://learn.microsoft.com/en-us/dotnet/core/porting/porting-approaches
B. kb/20-wcf-to-corewcf-migration.md pins CoreWCF 1.6.0. CoreWCF 1.9 targets .NET 10, and 1.8 reaches end of support on 24 Oct 2026. https://dotnet.microsoft.com/en-us/platform/support/policy/corewcf
C. wcf-services.md implies WSHttp and WS-* security work on Linux ("WSHttp without WS-* features that need Windows"). Microsoft does not document WS-Security, certificate-store or duplex support for CoreWCF, so these must be marked unverified. https://devblogs.microsoft.com/dotnet/corewcf-v1-released/
D. DevTx's dependency on Upgrade Assistant (deprecated) is a risk that engines.md notes only in passing. install_prerequisites lists UA as required.
E. kb/01 recommends try-convert as option 1. Its current maintenance status was not checked.
F. AppStream naming is inconsistent: seven-rs.md says "AppStream 2.0", while windows-only-apis.md and tools-landscape.md say "Amazon WorkSpaces Applications (formerly AppStream 2.0)", which matches AWS. https://aws.amazon.com/appstream2/

Verified as correct (no change needed): Porting Assistant and App2Container closed 7 Nov 2025; App Runner closed; ECS Express Mode exists; AWS Transform Dec 2025 expansion (.NET 10, Web Forms to Blazor, EF porting); EF 6.5.2 supports .NET 10; System.Configuration.ConfigurationManager has a net10.0 group.
