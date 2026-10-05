# NuGet package map (generated)

Generated from `scripts/data/package_map.json`. Matching is case-insensitive on the package id (regex, anchored), first match wins.
With `online_package_lookup` the scanner also reads api.nuget.org: the newest published version's target frameworks, deprecation (with alternative), published
advisories for the versions in use, and the licence expression. Unknown packages that support .NET Standard / .NET in their latest version are marked ok.

| Package id (regex) | Status | Severity | Note | Replacement | Known-vulnerable below |
| --- | --- | --- | --- | --- | --- |
| `Microsoft\.AspNet\.Mvc` | replace | Info | ASP.NET MVC 5 is .NET Framework only. | ASP.NET Core MVC (Microsoft.AspNetCore.App framework) |  |
| `Microsoft\.AspNet\.WebApi(\..*)?` | replace | Info | Web API 2 is .NET Framework only. | ASP.NET Core Web API (Microsoft.AspNetCore.Mvc.WebApiCompatShim is obsolete; port controllers) |  |
| `Microsoft\.AspNet\.(WebPages\|Razor)` | replace | Info | System.Web Razor. | ASP.NET Core Razor |  |
| `Microsoft\.AspNet\.Web\.Optimization(\..*)?` | replace | Low | System.Web bundling. | Build-time bundling (Vite/esbuild) or LigerShark.WebOptimizer.Core |  |
| `Microsoft\.AspNet\.Identity\..*` | replace | Medium | ASP.NET Identity 2 (OWIN). | Microsoft.AspNetCore.Identity.EntityFrameworkCore |  |
| `Microsoft\.AspNet\.SignalR(\..*)?` | replace | High | Protocol incompatible with ASP.NET Core SignalR; clients change too. | ASP.NET Core SignalR (+ Microsoft.AspNetCore.SignalR.StackExchangeRedis backplane) |  |
| `Microsoft\.AspNet\.(ScriptManager\|FriendlyUrls\|Web\.Optimization\.WebForms\|ScriptManager\..*)` | blocker | High | Web Forms infrastructure. | Part of the Web Forms UI rewrite |  |
| `Microsoft\.AspNet\.(TelemetryCorrelation\|Cors\|Providers\..*\|SessionState\..*\|OData\|WebApi\.OData)` | replace | Low | System.Web-specific helpers. | ASP.NET Core built-ins / Microsoft.AspNetCore.OData |  |
| `Microsoft\.Owin(\..*)?\|Owin` | replace | Medium | Katana/OWIN pipeline. | ASP.NET Core middleware and authentication handlers | Microsoft.Owin < 4.2.2 |
| `Microsoft\.Web\.Infrastructure` | remove | Info | System.Web infrastructure. | Not needed on ASP.NET Core |  |
| `Microsoft\.CodeDom\.Providers\.DotNetCompilerPlatform\|Microsoft\.Net\.Compilers(\.Toolset)?` | remove | Info | Roslyn for ASP.NET runtime compilation. | Not needed (SDK compiles); Razor runtime compilation package if required |  |
| `WebGrease\|Antlr\|Microsoft\.AspNet\.Web\.Optimization` | remove | Info | Bundling dependencies. | Not needed |  |
| `Microsoft\.Bcl(\.Build\|\.Async)?\|Microsoft\.Net\.Http\|System\.Net\.Http\|System\.ValueTuple\|System\.Buffers\|System\.Memory\|System\.Runtime\.CompilerServices\.Unsafe\|System\.Threading\.Tasks\.Extensions\|Microsoft\.Bcl\.AsyncInterfaces` | remove | Info | Polyfills for .NET Framework. | Part of .NET 10 |  |
| `Modernizr\|Respond\|jQuery(\..*)?\|bootstrap\|Microsoft\.jQuery\.Unobtrusive\..*\|knockoutjs\|AngularJS(\..*)?\|angularjs` | replace | Low | Client libraries delivered via NuGet (content packages). | npm / LibMan / CDN | jQuery < 3.5.0, bootstrap < 3.4.1 |
| `EntityFramework` | ok | Low | EF 6.4+ runs on .NET 10 (cross-platform); EDMX needs embedded metadata; maintenance mode. | EntityFramework 6.5.x now; Microsoft.EntityFrameworkCore.SqlServer 10 later |  |
| `System\.Data\.SqlClient` | replace | Low | Deprecated provider. | Microsoft.Data.SqlClient |  |
| `Microsoft\.SqlServer\.Types` | replace | Medium | Older versions ship Windows native assemblies (spatial types). | Microsoft.SqlServer.Types 160+ (check Linux support) or NetTopologySuite with EF Core |  |
| `Oracle\.DataAccess(\..*)?\|Oracle\.ManagedDataAccess$` | replace | Medium | Framework ODP.NET. | Oracle.ManagedDataAccess.Core |  |
| `System\.Data\.SQLite(\..*)?` | replace | Low | Native interop package. | Microsoft.Data.Sqlite |  |
| `Dapper(\..*)?\|Newtonsoft\.Json(\..*)?\|AutoMapper(\..*)?\|NLog\|Serilog(\..*)?\|Polly\|FluentValidation\|Humanizer(\..*)?\|HtmlAgilityPack\|CsvHelper\|MediatR\|Castle\.Core\|Moq\|NUnit\|xunit(\..*)?\|MSTest\..*\|FluentAssertions\|RestSharp\|StackExchange\.Redis\|AWSSDK\..*\|Twilio\|Stripe\.net\|SendGrid\|SharpZipLib\|MimeKit\|MailKit\|ClosedXML\|DocumentFormat\.OpenXml\|NPOI\|ExcelDataReader(\..*)?\|QuestPDF\|SkiaSharp(\..*)?\|Hangfire\.Core\|Quartz\|Autofac\|Unity\|Ninject\|SimpleInjector\|Microsoft\.Extensions\..*\|BouncyCastle(\..*)?\|Portable\.BouncyCastle\|BCrypt\.Net-Next\|Swashbuckle\.AspNetCore(\..*)?\|MySql\.Data\|MySqlConnector\|Npgsql(\..*)?\|MongoDB\.Driver\|Selenium\.WebDriver\|Microsoft\.Data\.SqlClient\|log4net` | ok | Info | Cross-platform on .NET 10 in current versions; upgrade to a current major (check breaking changes). | Current version | Newtonsoft.Json < 13.0.1, log4net < 2.0.10, RestSharp < 106.12.0, SharpZipLib < 1.3.3, Portable.BouncyCastle < 1.9.0, BouncyCastle < 1.8.9, MySql.Data < 8.0.33, System.Data.SqlClient < 4.8.6 |
| `Autofac\.(Mvc5\|WebApi2\|Integration\.Mvc\|Integration\.WebApi)(\..*)?\|Unity\.(Mvc\|Mvc5\|WebApi\|AspNet\.WebApi)\|Ninject\.(Web\..*\|MVC\d)\|SimpleInjector\.Integration\.(Web.*\|WebApi.*)\|StructureMap(\..*)?\|WebActivatorEx` | replace | Low | DI integrations for System.Web. | Microsoft.Extensions.DependencyInjection (or the container's ASP.NET Core integration; StructureMap -> Lamar) |  |
| `FluentValidation\.(Mvc\d\|WebApi)` | replace | Low | System.Web integration. | FluentValidation.DependencyInjectionExtensions |  |
| `Hangfire\.(AspNet\|SqlServer)?$\|Hangfire` | ok | Low | Runs on .NET 10; use Hangfire.AspNetCore. | Hangfire.AspNetCore |  |
| `Elmah(\..*)?` | replace | Low | System.Web module. | Exception middleware + CloudWatch / ElmahCore |  |
| `Glimpse(\..*)?` | remove | Low | Abandoned diagnostics tool. | OpenTelemetry / AWS X-Ray |  |
| `MiniProfiler(\.Mvc4\|\.EF6)?$` | replace | Low | System.Web integration. | MiniProfiler.AspNetCore.Mvc |  |
| `Microsoft\.ApplicationInsights\.(Web\|WindowsServer\|PerfCounterCollector\|DependencyCollector\|Agent\.Intercept)(\..*)?` | replace | Low | Azure monitoring for System.Web/Windows. | OpenTelemetry + CloudWatch / X-Ray (ADOT) |  |
| `iTextSharp(\..*)?\|itextsharp\.xmlworker` | licence | Medium | iText 5 is EOL and AGPL (commercial licence needed for closed source). | QuestPDF (community/commercial), PdfSharpCore, or iText 8 with a licence |  |
| `EPPlus` | licence | Medium | EPPlus 5+ is under the Polyform Noncommercial licence (commercial licence needed); 4.x is LGPL and old. | Commercial EPPlus licence, or ClosedXML (MIT) |  |
| `Aspose\..*\|Telerik\..*\|DevExpress\..*\|Infragistics\..*\|Syncfusion\..*\|ComponentOne\..*\|GrapeCity\..*\|Stimulsoft\..*\|FastReport(\..*)?` | licence | Medium | Commercial component suite: check that the licence covers the .NET 10 / Linux packages and that Web Forms/WinForms controls have equivalents. | Vendor's .NET Core / Blazor packages (licence review) |  |
| `AjaxControlToolkit\|Telerik\.UI\.for\.AspNet\.Ajax\|DevExpress\.Web(\..*)?\|Infragistics\.Web(\..*)?` | blocker | High | Web Forms control suite. | Blazor component suite (part of the UI rewrite) |  |
| `CrystalReports(\..*)?\|CrystalDecisions(\..*)?\|SAP\.CrystalReports(\..*)?` | blocker | Blocker | Crystal Reports runtime is .NET Framework/Windows only. | SSRS / PBIRS, Telerik Reporting, Stimulsoft, FastReport, QuestPDF |  |
| `Microsoft\.ReportViewer(\..*)?\|Microsoft\.ReportingServices\.ReportViewerControl\.(WebForms\|Winforms)` | blocker | High | ReportViewer controls are .NET Framework only. | SSRS REST/URL access; Bold Reports; ReportViewerCore.NETCore (community, Windows rendering limits) |  |
| `Microsoft\.Office\.Interop\..*\|Office` | blocker | Blocker | Requires Office on Windows. | DocumentFormat.OpenXml / ClosedXML / NPOI |  |
| `System\.Drawing\.Common` | windows-only | High | Windows-only since .NET 6. | SkiaSharp / ImageSharp |  |
| `System\.DirectoryServices(\.AccountManagement)?$` | windows-only | High | Windows-only (only System.DirectoryServices.Protocols is cross-platform). | System.DirectoryServices.Protocols |  |
| `System\.Management` | windows-only | High | WMI. | Cross-platform APIs |  |
| `System\.ServiceProcess\.ServiceController\|Microsoft\.Win32\.Registry\|System\.Diagnostics\.EventLog\|System\.Diagnostics\.PerformanceCounter\|Microsoft\.Windows\.Compatibility` | windows-only | Medium | Windows Compatibility Pack APIs (work on Windows only). | Cross-platform equivalents |  |
| `System\.Messaging\|Experimental\.System\.Messaging` | blocker | Blocker | MSMQ. | AWSSDK.SQS / MassTransit.AmazonSQS |  |
| `Microsoft\.Practices\.EnterpriseLibrary\..*\|EnterpriseLibrary\..*` | replace | High | Enterprise Library is retired and Windows/.NET Framework oriented. | Microsoft.Extensions.* (logging, caching, configuration), Polly, Microsoft.Data.SqlClient |  |
| `WindowsAzure\.Storage\|Microsoft\.WindowsAzure\.ConfigurationManager\|Microsoft\.Azure\.(KeyVault\|Storage\..*)` | replace | Medium | Azure services: decide the AWS equivalent. | AWSSDK.S3 / AWSSDK.SecretsManager |  |
| `DotNetZip\|Ionic\.Zip` | replace | Medium | Unmaintained, with a published path-traversal advisory. | System.IO.Compression |  |
| `Microsoft\.Exchange\.WebServices` | replace | Medium | EWS managed API is retired (Exchange Online EWS retirement). | Microsoft.Graph |  |
| `SpecFlow(\..*)?` | replace | Low | SpecFlow reached end of life (Dec 2024). | Reqnroll |  |
| `Microsoft\.VisualStudio\.QualityTools\.UnitTestFramework\|MSTest\.TestFramework\.v1` | replace | Low | MSTest v1. | MSTest (v3) |  |
| `Thinktecture\.IdentityModel(\..*)?\|IdentityServer3(\..*)?\|DotNetOpenAuth(\..*)?\|Microsoft\.IdentityModel\.(Protocol\.Extensions\|Clients\.ActiveDirectory)` | replace | Medium | Retired identity libraries. | Microsoft.AspNetCore.Authentication.OpenIdConnect / Duende IdentityServer (licence) / Cognito |  |
| `Rotativa(\..*)?\|TuesPechkin(\..*)?\|Pechkin(\..*)?\|wkhtmltopdf(\..*)?\|ABCpdf(\..*)?\|EvoPdf(\..*)?\|Winnovative(\..*)?\|Select\.HtmlToPdf(\..*)?` | replace | Medium | HTML-to-PDF engines with Windows or native-binary dependencies. | PuppeteerSharp / Microsoft.Playwright (Chromium) / QuestPDF |  |
| `Microsoft\.SharePoint(\.Client(\..*)?)?\|Microsoft\.SharePointOnline\.CSOM` | replace | Medium | Check whether on-prem SharePoint stays reachable; CSOM for .NET Standard exists for Online. | PnP.Core / Microsoft.Graph |  |
