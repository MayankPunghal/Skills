# Windows-only and legacy API catalogue (generated)

Generated from `scripts/data/rules.json` by `render_references.py`. Do not edit by hand: change the JSON and re-render.
Every rule produces findings with `file:line` evidence. Severity is the default and the reviewer may adjust it. `baseline` means the effort is already
inside the project-conversion rate. Sources are listed in [sources.md](sources.md).

Microsoft's list of APIs that always throw on .NET (S2) is broader than these rules. The rules cover the members that occur in line-of-business code:
AppDomain creation, CodeDom compilation, ProtectedData, CNG/CSP key containers, Thread.Abort/Suspend, reflection-only loading, BinaryFormatter
(always throws from .NET 9), RSA/ECDsa XML import, X509 store and certificate import. Anything else surfaces through CA1416 when
`validate_linux_build.py --run` builds SDK-style projects.

## Contents

- Windows-only APIs (Linux readiness)
- File system and path handling
- Time zones and culture
- .NET Framework technologies unavailable on modern .NET
- ASP.NET (System.Web) dependencies
- WCF, WPF, WinForms and other rewrite candidates
- Connectivity and network dependencies
- Email, reporting, printing and other on-prem integrations
- Data access layer
- SQL Server features vs PostgreSQL (dual or PostgreSQL-only)
- Authentication and identity
- Configuration and secrets
- Security and compliance
- Hosting and IIS dependencies
- State and horizontal scaling
- Background processing and scheduling
- Logging, monitoring and health
- Hypervisor and machine-coupling (Proxmox, VMware, Hyper-V)
- Build and delivery
- Automated tests
- Front end
- Checks implemented in scanner code (not in rules.json)

## Windows-only APIs (Linux readiness)

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `WIN-REGISTRY` | Windows registry access | High / Confirmed | Microsoft.Win32.Registry throws PlatformNotSupportedException on Linux; there is no registry. | Move the values to configuration (appsettings / environment variables) backed by AWS Systems Manager Parameter Store. **Alt:** IConfiguration + Parameter Store / Secrets Manager | S2, S3 |
| `WIN-EVENTLOG` | Windows Event Log | Medium / Confirmed | The Windows Event Log does not exist on Linux (System.Diagnostics.EventLog is Windows-only). | Log through Microsoft.Extensions.Logging to stdout and ship to Amazon CloudWatch Logs. **Alt:** ILogger + CloudWatch Logs (Serilog/NLog sinks) | S3 |
| `WIN-WMI` | WMI (System.Management) | High / Confirmed | WMI is Windows-only; System.Management throws on Linux. | Replace with cross-platform APIs (System.Environment, /proc, EC2 instance metadata) or remove. **Alt:** Environment / RuntimeInformation / EC2 IMDS | S3 |
| `WIN-PERFCOUNTER` | Windows performance counters | Medium / Confirmed | Performance counters are Windows-only. | Use EventCounters / System.Diagnostics.Metrics with OpenTelemetry or CloudWatch metrics. **Alt:** System.Diagnostics.Metrics + CloudWatch / OpenTelemetry | S3 |
| `WIN-DRAWING` | System.Drawing / GDI+ imaging | High / Confirmed | System.Drawing.Common is Windows-only since .NET 6 (TypeInitializationException / PlatformNotSupportedException on Linux). | Port imaging code to SkiaSharp or ImageSharp; check fonts are installed in the Linux image. **Alt:** SkiaSharp (MIT) / ImageSharp (Six Labors licence) / Aspose.Drawing (commercial) | S6 |
| `WIN-COM-INTEROP` | COM interop | Blocker / Confirmed | COM does not exist on Linux; the component behind it must be replaced or kept on Windows. | Identify the COM server, find a managed cross-platform library or service, or isolate it behind an API on a Windows host. **Alt:** Managed library / service API; Windows EC2 sidecar as last resort | S2 |
| `WIN-PINVOKE-WIN32` | P/Invoke into Windows system DLLs | Blocker / Confirmed | Calls into Win32 system libraries cannot run on Linux. | Replace each call with a managed cross-platform API or remove the feature. **Alt:** Managed BCL equivalents | S17 |
| `WIN-PINVOKE-NATIVE` | P/Invoke into other native libraries | High / Needs verification | A native library must exist as a Linux .so build for the same API. | Confirm a Linux build of the native library exists (and its licence); otherwise replace. **Alt:** Vendor Linux build or managed replacement | S17 |
| `WIN-SERVICECONTROLLER` | ServiceController (controls Windows services) | Medium / Confirmed | Starting/stopping Windows services is Windows-only. | Replace with orchestration-level control (ECS service APIs) or remove. **Alt:** AWS SDK (ECS/Systems Manager) | S3 |
| `WIN-PROTECTEDDATA` | DPAPI (ProtectedData) | High / Confirmed | ProtectedData throws PlatformNotSupportedException on Linux, and data protected with machine DPAPI cannot be decrypted elsewhere. | Use ASP.NET Core Data Protection with a key ring in S3/Parameter Store protected by AWS KMS; plan re-encryption of stored data. **Alt:** Microsoft.AspNetCore.DataProtection + AWS KMS / Secrets Manager | S2 |
| `WIN-CNG-CSP` | CNG / CSP key containers | Medium / Confirmed | CNG and CSP key containers are Windows-only (PlatformNotSupportedException on Linux). | Use RSA.Create()/ECDsa.Create() with keys from AWS KMS, Secrets Manager or PEM files. **Alt:** RSA/ECDsa.Create + AWS KMS | S2 |
| `WIN-CERTSTORE` | Windows certificate store | Medium / Needs verification | Linux has no LocalMachine\My store; certificates must be loaded from files or a secret store. | Load certificates from AWS Secrets Manager / ACM-exported PEM or PFX files; terminate TLS at the ALB with ACM where possible. **Alt:** ACM at the load balancer; X509Certificate2 from Secrets Manager | S2 |
| `WIN-ACL` | Windows file ACLs | Medium / Confirmed | Windows ACL APIs are Windows-only. | Remove or replace with POSIX permissions / IAM policies on S3/EFS. **Alt:** IAM / S3 bucket policies / EFS access points | S3 |
| `WIN-SHELL-EXEC` | Runs Windows executables or shells | High / Likely | Windows executables, batch files and VBScript do not run on Linux. | Replace the external tool with a library or a Linux equivalent; PowerShell 7 (pwsh) scripts can run on Linux. **Alt:** Library call / pwsh / container sidecar | S3 |
| `WIN-SPEECH-UI` | Windows-only UI/OS libraries in server code | High / Confirmed | These libraries are Windows-only. | Remove from server code or replace. | S3 |

## File system and path handling

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `NET-UNC-SHARE` | UNC network share paths | High / Confirmed | SMB shares on the on-prem network are unreachable from AWS without VPN/Direct Connect, and Linux needs a mount instead of UNC paths. | Move the files to Amazon S3, Amazon EFS, or FSx for Windows File Server / FSx for NetApp ONTAP (SMB); use configuration, not literals. **Alt:** Amazon S3 / EFS / FSx | S10 |
| `FILE-DRIVE-LETTER` | Hard-coded drive-letter paths | High / Confirmed | Linux has no drive letters; these paths fail on Linux and on any new host. | Make paths configurable and root them in a mounted volume / S3. **Alt:** Configuration + EFS/S3 | S7 |
| `FILE-BACKSLASH` | Backslash path separators in literals | Medium / Likely | '\' is a valid file-name character on Linux, so these paths silently point to the wrong place. | Use Path.Combine / '/' separators. **Alt:** Path.Combine | S7 |
| `FILE-MAPPATH` | Server.MapPath / HostingEnvironment.MapPath | Medium / Confirmed | MapPath does not exist in ASP.NET Core; files under the site folder are lost when containers restart. | Use IWebHostEnvironment.ContentRootPath/WebRootPath for read-only assets; S3/EFS for writable data. **Alt:** IWebHostEnvironment + S3 _(baseline)_ | S9 |
| `FILE-WIN-FOLDERS` | Windows special folders / %VARIABLES% | Medium / Confirmed | These locations do not exist (or map to unexpected paths) on Linux/containers. | Use configured paths on mounted storage. **Alt:** Configuration + mounted volumes | S7 |
| `FILE-ENCODING` | Code-page encodings / Encoding.Default | Medium / Confirmed | Encoding.Default is UTF-8 on .NET (ANSI code page on .NET Framework); code pages need CodePagesEncodingProvider. | Name encodings explicitly; register CodePagesEncodingProvider where legacy code pages are needed. **Alt:** System.Text.Encoding.CodePages | S7 |
| `FILE-CRLF` | Hard-coded CRLF line endings | Low / Likely | Environment.NewLine is \n on Linux; parsers that split on \r\n or files compared byte-for-byte behave differently. | Decide per use: protocol-mandated CRLF (keep), file output (Environment.NewLine or explicit), parsing (accept both). | S7 |

## Time zones and culture

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `TZ-WINDOWS-ID` | Windows time-zone IDs | Medium / Confirmed | On Linux .NET resolves Windows IDs only through ICU; containers without ICU/tzdata or in invariant mode throw TimeZoneNotFoundException. | Store IANA IDs (or convert with TimeZoneInfo.TryConvertWindowsIdToIanaId); include tzdata and ICU in the image. **Alt:** IANA IDs; NodaTime | S7 |
| `TZ-LOCAL-TIME` | Server-local time (DateTime.Now / Today) | Medium / Likely | AWS hosts and containers run in UTC; logic that relied on the on-prem server's local time zone shifts (cut-offs, reports, schedules). | Decide the business time zone explicitly; use DateTime.UtcNow / TimeProvider and convert at the edges, or set TZ deliberately. **Alt:** TimeProvider + explicit business time zone | S7 |
| `TZ-SQL-LOCAL-TIME` | Database-server local time (GETDATE) | Medium / Likely | GETDATE() uses the server's local time; PostgreSQL servers default to UTC, so results shift. | Store UTC (GETUTCDATE/SYSUTCDATETIME, now() AT TIME ZONE 'UTC') and convert at the edge. **Alt:** UTC storage **DB impact:** pg: rework | S11 |
| `CULT-HARDCODED` | Culture handling | Low / Likely | Culture data comes from ICU on Linux (formats, sorting and comparisons can differ from Windows NLS); web.config globalization settings are not applied in ASP.NET Core. | Set RequestLocalization explicitly; test formatting/sorting; keep ICU in images. **Alt:** RequestLocalizationOptions | S7 |

## .NET Framework technologies unavailable on modern .NET

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `API-APPDOMAIN` | AppDomain creation / unloading | High / Confirmed | Creating or unloading AppDomains throws PlatformNotSupportedException on .NET. | Use AssemblyLoadContext for plug-in loading, or separate processes for isolation. **Alt:** AssemblyLoadContext / separate process | S1, S2 |
| `API-REMOTING` | .NET Remoting | Blocker / Confirmed | .NET Remoting is not supported on .NET 6+. | Replace with HTTP/gRPC APIs or StreamJsonRpc for IPC. **Alt:** gRPC / REST / StreamJsonRpc | S1 |
| `API-CAS` | Code Access Security / security transparency | Low / Confirmed | CAS and partial trust are not supported; the attributes are ignored or throw. | Remove CAS attributes and partial-trust configuration; rely on OS/container isolation. **Alt:** Container / IAM boundaries | S1, S2 |
| `API-ENTERPRISESERVICES` | System.EnterpriseServices (COM+) | Blocker / Confirmed | COM+ (EnterpriseServices) is not supported on .NET 6+. | Re-implement the component as a normal class/service; use explicit transactions. **Alt:** Plain services + explicit transactions | S1 |
| `API-WORKFLOW` | Windows Workflow Foundation | Blocker / Confirmed | Workflow Foundation is not supported on .NET 6+. | Port to CoreWF, Elsa Workflows or AWS Step Functions; or retain on .NET Framework. **Alt:** CoreWF / Elsa / AWS Step Functions | S1 |
| `API-BINARYFORMATTER` | BinaryFormatter and legacy formatters | High / Confirmed | BinaryFormatter always throws from .NET 9 and is a deserialization security risk; persisted binary blobs need a migration path. | Switch to System.Text.Json / DataContractSerializer / MessagePack; convert any persisted data. **Alt:** System.Text.Json / MessagePack / protobuf-net | S2 |
| `API-THREAD-ABORT` | Thread.Abort / Suspend / Resume | Medium / Likely | Thread.Abort/Suspend/Resume throw PlatformNotSupportedException on .NET. | Use cooperative cancellation (CancellationToken). **Alt:** CancellationToken | S2 |
| `API-CODEDOM` | Runtime compilation with CodeDom | High / Confirmed | CodeDomProvider.CompileAssemblyFrom* throws on .NET. | Use Roslyn (Microsoft.CodeAnalysis) scripting/compilation. **Alt:** Microsoft.CodeAnalysis.CSharp | S2 |
| `API-REFLECTION-ONLY` | Reflection-only load / Assembly.CodeBase | Medium / Confirmed | These APIs throw on .NET (CodeBase is obsolete and throws for single-file). | Use MetadataLoadContext / Assembly.Location / AppContext.BaseDirectory. **Alt:** MetadataLoadContext / AppContext.BaseDirectory | S2 |
| `API-XSLT-SCRIPT` | XSLT script blocks | High / Confirmed | XSLT script blocks are supported only on .NET Framework. | Move script logic into extension objects (XsltArgumentList.AddExtensionObject). **Alt:** XSLT extension objects | S1 |
| `API-WEBREQUEST` | Obsolete WebRequest / WebClient | Low / Confirmed | WebRequest/WebClient are obsolete (SYSLIB0014) on .NET and behave differently (no ServicePointManager tuning). | Move to IHttpClientFactory/HttpClient. **Alt:** IHttpClientFactory | S3 |

## ASP.NET (System.Web) dependencies

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `WEB-SYSTEMWEB` | System.Web dependency | High / Confirmed | System.Web does not exist on modern .NET; every file using it changes in an ASP.NET Core port. | Port to ASP.NET Core; use Microsoft.AspNetCore.SystemWebAdapters to keep shared libraries compiling during an incremental (strangler fig) migration. **Alt:** ASP.NET Core + System.Web adapters _(baseline)_ | S9 |
| `WEB-HTTPCONTEXT-CURRENT` | HttpContext.Current (ambient request context) | High / Confirmed | There is no static HttpContext.Current in ASP.NET Core; code deep in libraries that reaches for it must be re-plumbed. | Inject IHttpContextAccessor or pass values explicitly; System.Web adapters can bridge during migration. **Alt:** IHttpContextAccessor / SystemWebAdapters _(baseline)_ | S9 |
| `WEB-WEBFORMS-UI` | ASP.NET Web Forms (System.Web.UI) | Blocker / Confirmed | Web Forms does not exist on ASP.NET Core and has no direct equivalent; the UI layer must be rewritten (Blazor / Razor Pages / MVC / SPA) or the app retained on .NET Framework. | Choose per app: rewrite UI (AWS Transform can port Web Forms UI to Blazor), or retain on .NET Framework on Windows and move shared libraries to .NET Standard 2.0 (hybrid). **Alt:** Blazor / Razor Pages; retain + .NET Standard 2.0 shared libraries _(baseline)_ | S1, S9, S18 |
| `WEB-GLOBAL-ASAX` | Global.asax application events | Medium / Confirmed | Application/session events become Program.cs startup and middleware in ASP.NET Core. | Move logic to Program.cs, middleware and IHostApplicationLifetime. **Alt:** Middleware / hosted services _(baseline)_ | S9 |
| `WEB-MODULE-HANDLER` | Custom HTTP modules / handlers | High / Confirmed | IHttpModule/IHttpHandler do not exist in ASP.NET Core. | Rewrite as middleware or endpoints. **Alt:** ASP.NET Core middleware / minimal API endpoints _(baseline)_ | S9 |
| `WEB-OWIN` | OWIN / Katana pipeline | Medium / Confirmed | OWIN middleware (often authentication) must be rebuilt on the ASP.NET Core pipeline. | Replace Katana middleware with ASP.NET Core equivalents (authentication handlers, CORS, static files). **Alt:** ASP.NET Core authentication/middleware _(baseline)_ | S9 |
| `WEB-CHILD-ACTION` | MVC child actions | Medium / Confirmed | Child actions were removed in ASP.NET Core MVC. | Convert to View Components or partial views. **Alt:** View Components _(baseline)_ | S9 |

## WCF, WPF, WinForms and other rewrite candidates

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `WEB-ASMX` | ASMX web services | High / Confirmed | ASMX services are not supported on ASP.NET Core; callers depend on the SOAP contract. | Expose the same contract with CoreWCF (BasicHttpBinding) or move callers to REST. **Alt:** CoreWCF / Web API | S1, S17 |
| `WCF-SERVICE` | WCF service (server side) | High / Confirmed | WCF server is not part of .NET; CoreWCF supports a subset (BasicHttp, NetTcp, WSHttp and some WS-* features). | Port to CoreWCF when callers need the SOAP/NetTcp contract; otherwise re-expose as REST/gRPC. **Alt:** CoreWCF / gRPC / ASP.NET Core Web API _(baseline)_ | S1, S23 |
| `WCF-BINDING` | WCF bindings / features without CoreWCF support | Blocker / Likely | These bindings/duplex patterns are not (fully) supported by CoreWCF or have no Linux transport. | Redesign the transport (gRPC streaming, SignalR, SQS) or retain the service on .NET Framework. **Alt:** gRPC / SignalR / SQS | S23 |
| `DESK-WINFORMS` | Windows Forms | Blocker / Confirmed | WinForms runs on .NET 10 but only on Windows; it cannot run on Linux. | Retain on Windows (upgrade to .NET 10 Windows Desktop, or AppStream 2.0/WorkSpaces), or rewrite as a web front end. **Alt:** .NET 10 WinForms on Windows; web UI rewrite; Avalonia _(baseline)_ | S3 |
| `DESK-WPF` | WPF | Blocker / Confirmed | WPF runs on .NET 10 but only on Windows. | Retain on Windows (.NET 10 WPF) or rewrite (web / Avalonia). **Alt:** .NET 10 WPF on Windows; Avalonia _(baseline)_ | S3 |

## Connectivity and network dependencies

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `WCF-CLIENT` | WCF / SOAP client proxies | Medium / Confirmed | WCF clients work on .NET via System.ServiceModel.* packages, but generated proxies and client config must be regenerated and the endpoint must be reachable from AWS. | Regenerate proxies with dotnet-svcutil; move endpoint config to appsettings; confirm network path. **Alt:** System.ServiceModel.Http/NetTcp + dotnet-svcutil | S1 |
| `NET-PROXY` | Explicit HTTP proxy configuration | Medium / Confirmed | Corporate proxies are usually not reachable or not wanted from AWS. | Remove or make egress configurable (VPC endpoints / NAT). **Alt:** VPC endpoints / NAT gateway | S10 |

## Email, reporting, printing and other on-prem integrations

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `WEB-REPORTVIEWER` | ReportViewer control (SSRS/RDLC in Web Forms/WinForms) | High / Confirmed | The ReportViewer controls are .NET Framework only. | Render reports via the SSRS/PBIRS REST or URL access, or move RDLC rendering to a supported library. **Alt:** SSRS REST API; Bold Reports; Telerik Reporting; QuestPDF for code-built documents | S12 |
| `DB-DATABASE-MAIL` | Database Mail | Medium / Confirmed | Database Mail does not exist in PostgreSQL. | Send email from the application through Amazon SES. **Alt:** Amazon SES **DB impact:** pg: redesign | S11, S14 |
| `NET-SMTP` | SMTP email sending | Medium / Confirmed | On-prem SMTP relays are not reachable from AWS without a network path; EC2 throttles outbound port 25. | Send through Amazon SES (SMTP interface or API) with verified domains (SPF/DKIM/DMARC). **Alt:** Amazon SES; MailKit as client | S10 |
| `NET-FTP` | FTP/SFTP transfers | Medium / Confirmed | File-transfer partners usually allow-list source IPs; the egress IP changes on AWS. | Use fixed egress IPs (NAT gateway Elastic IPs) and notify partners; consider AWS Transfer Family for inbound. **Alt:** AWS Transfer Family; NAT gateway EIPs | S10 |
| `INT-PRINTING` | Printing | High / Confirmed | Windows printing APIs and on-prem printers are not available from Linux in AWS. | Generate PDFs and send them to a print service / on-prem print agent. **Alt:** PDF generation + on-prem print agent | S6 |
| `INT-FAX` | Fax | Blocker / Confirmed | Windows Fax Service (COM) is not available on Linux/AWS. | Use a cloud fax API. **Alt:** Cloud fax provider API | S2 |
| `INT-OFFICE-INTEROP` | Office interop automation | Blocker / Confirmed | Office automation needs Office installed on Windows (and is unsupported on servers). | Use Open XML-based libraries. **Alt:** Open XML SDK / ClosedXML / NPOI / EPPlus (commercial) | S2 |
| `INT-CRYSTAL` | Crystal Reports | Blocker / Confirmed | The Crystal Reports .NET runtime is Windows/.NET Framework only. | Re-implement reports (SSRS/PBIRS, a reporting library, or a BI tool); keep a Windows report host as an interim. **Alt:** SSRS / Power BI Report Server; Telerik / Stimulsoft / FastReport (commercial); QuestPDF | S12 |
| `INT-SSRS-CLIENT` | SSRS web-service clients | Medium / Confirmed | Calls an SSRS server, which depends on SQL Server; reports need a new home when SQL Server goes. | Decide where reports run; regenerate SOAP clients or use the REST API. **Alt:** Amazon QuickSight / paginated reporting / SSRS on EC2 | S12 |
| `INT-PDF-WINDOWS` | PDF/HTML rendering libraries with Windows or native dependencies | Medium / Needs verification | These need Windows binaries, native wkhtmltopdf builds, or have licence changes (iTextSharp 5 is AGPL/EOL). | Confirm the Linux story and licence; otherwise move to QuestPDF, PuppeteerSharp/Playwright (Chromium), or iText 8 (commercial/AGPL). **Alt:** QuestPDF / PuppeteerSharp / iText 8 | S6 |
| `INT-SHAREPOINT-EXCHANGE` | SharePoint server object model / Exchange EWS | Medium / Confirmed | The SharePoint server object model is on-prem/Windows only; EWS is being retired in favour of Microsoft Graph. | Use Microsoft Graph / CSOM REST APIs with app credentials. **Alt:** Microsoft Graph | S10 |

## Data access layer

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `DATA-EF6-EDMX` | Entity Framework 6 with EDMX model | Medium / Confirmed | EF6 (6.4+) runs on modern .NET, but the EDMX designer workflow is not supported in SDK-style projects and EF Core has no EDMX; metadata must be embedded or the model moved to code. | Short term: EF 6.5 on .NET 10 with embedded EDMX metadata. Long term: EF Core 10 (scaffold from database). **Alt:** EF 6.5 on .NET 10; EF Core 10 | S18 |
| `DATA-EF6` | Entity Framework 6 | Low / Confirmed | EF6 works on .NET 10 but is in maintenance; EF Core is the strategic ORM (and AWS Transform can port EF code). | Keep EF 6.5 for the first move; plan EF Core as a follow-up. **Alt:** EF Core 10 | S18 |
| `DATA-SYSTEM-SQLCLIENT` | System.Data.SqlClient | Low / Confirmed | System.Data.SqlClient is deprecated; Microsoft.Data.SqlClient is the supported provider (different TLS/Encrypt defaults). | Switch to Microsoft.Data.SqlClient and set Encrypt/TrustServerCertificate deliberately; PostgreSQL targets use Npgsql instead. **Alt:** Microsoft.Data.SqlClient | S11 |
| `DATA-OLEDB` | OLE DB / Jet / ACE (Access, Excel via OLE DB) | High / Confirmed | OLE DB is Windows-only; Jet/ACE drivers do not exist on Linux. | Use native ADO.NET providers (Microsoft.Data.SqlClient) or file libraries (ClosedXML/ExcelDataReader) instead of Jet/ACE. **Alt:** Microsoft.Data.SqlClient; ExcelDataReader / ClosedXML | S3 |
| `DATA-ODBC` | ODBC | Medium / Needs verification | ODBC works on Linux only if a Linux ODBC driver exists for the target database. | Confirm a Linux driver (unixODBC) or switch to a managed provider. **Alt:** Managed ADO.NET provider | S3 |
| `DATA-ORACLE-UNMANAGED` | Oracle unmanaged ODP.NET | High / Confirmed | Oracle.DataAccess (unmanaged) needs the Windows Oracle client. | Move to Oracle.ManagedDataAccess.Core. **Alt:** Oracle.ManagedDataAccess.Core | S3 |
| `DATA-DISTRIBUTED-TX` | TransactionScope / distributed transactions | Medium / Needs verification | Distributed (MSDTC) transactions are supported on .NET only on Windows; a TransactionScope spanning two connections/resources will fail on Linux. | Confirm each scope uses one connection; otherwise redesign (outbox pattern, sagas). **Alt:** Single-connection transactions / outbox | S3, S12 |
| `DATA-SQLDEPENDENCY` | SqlDependency / SqlCacheDependency | Medium / Confirmed | Query notifications need SQL Server Service Broker (no PostgreSQL equivalent); SqlCacheDependency is System.Web only. | Replace with explicit cache invalidation or events (ElastiCache, SNS). **Alt:** ElastiCache + explicit invalidation **DB impact:** pg: redesign | S14 |

## SQL Server features vs PostgreSQL (dual or PostgreSQL-only)

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `DB-CLR` | SQL CLR assemblies | Blocker / Confirmed | CLR assemblies run inside SQL Server; PostgreSQL has no CLR, so each routine is rewritten. | Rewrite CLR routines in PL/pgSQL, or move the logic to the application (preferred when it is not set-based). **Alt:** PL/pgSQL function / application code **DB impact:** pg: redesign | S12, S14 |
| `DB-LINKED-SERVER` | Linked servers / distributed queries | High / Confirmed | PostgreSQL has no linked servers; remote data needs postgres_fdw or application-level integration. | Inventory each linked server; replace with application-level integration or AWS DMS replication where possible. **Alt:** postgres_fdw / application integration / AWS DMS **DB impact:** pg: redesign | S12, S14 |
| `DB-XP-CMDSHELL` | xp_cmdshell / OLE automation / file-system extended procedures | Blocker / Confirmed | Extended stored procedures and OS access do not exist in PostgreSQL. | Move OS/file work into the application or a Lambda/ECS task; use S3 integration for files. **Alt:** Lambda / ECS task / S3 for files **DB impact:** pg: redesign | S12, S14 |
| `DB-FILESTREAM` | FILESTREAM / FileTable | Blocker / Confirmed | FILESTREAM and FileTables have no PostgreSQL equivalent. | Store blobs in Amazon S3 with keys in the database. **Alt:** Amazon S3 **DB impact:** pg: redesign | S12, S14 |
| `DB-SERVICE-BROKER` | Service Broker | High / Confirmed | Service Broker has no PostgreSQL equivalent (LISTEN/NOTIFY is not a durable queue). | Replace with Amazon SQS/SNS or an outbox table polled by a worker. **Alt:** Amazon SQS / outbox pattern **DB impact:** pg: redesign | S12, S14 |
| `DB-MSDTC` | Distributed transactions in T-SQL | High / Confirmed | MSDTC distributed transactions do not exist in PostgreSQL (two-phase commit is a different mechanism). | Avoid cross-server transactions; redesign with sagas/outbox. **Alt:** Outbox / saga **DB impact:** pg: redesign | S12, S14 |
| `DB-SQL-AGENT` | SQL Server Agent jobs | Medium / Confirmed | SQL Server Agent has no PostgreSQL equivalent (pg_cron covers simple schedules). | Move each job to EventBridge Scheduler + Lambda/ECS task, or pg_cron for pure SQL jobs. **Alt:** EventBridge Scheduler + Lambda / ECS **DB impact:** pg: rework | S11, S14 |
| `DB-CROSS-DATABASE` | Cross-database references (three-part names) | Medium / Needs verification | PostgreSQL cannot query across databases; three-part names fail. | Put the related data in schemas of one database, use postgres_fdw, or remove the coupling in the application. **Alt:** Schemas in one database / postgres_fdw **DB impact:** pg: rework | S12, S14 |
| `DB-BULK-FILE` | BULK INSERT / OPENROWSET(BULK) from server files | High / Confirmed | BULK INSERT and OPENROWSET(BULK) read server files; PostgreSQL uses COPY (client-side) or S3-based loads. | Load files through the application, COPY, or AWS Glue. **Alt:** COPY / aws_s3 import / AWS Glue **DB impact:** pg: rework | S11, S14 |
| `DB-FULLTEXT` | Full-text search | Medium / Confirmed | SQL Server full-text search is a different engine from PostgreSQL full-text search. | Move to PostgreSQL full-text (tsvector) or Amazon OpenSearch. **Alt:** Amazon OpenSearch Service **DB impact:** pg: rework | S14 |
| `DB-SERVER-CONFIG` | Server-level configuration / privileges | High / Confirmed | Server-level settings, triggers, endpoints and replication are SQL Server administration objects with no PostgreSQL counterpart. | Translate needed settings to PostgreSQL parameters; drop the server-level objects. **Alt:** PostgreSQL parameter groups **DB impact:** pg: rework | S12, S14 |

## Authentication and identity

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `WIN-DIRSERVICES` | System.DirectoryServices (Active Directory via ADSI) | High / Confirmed | System.DirectoryServices and AccountManagement are Windows-only; only System.DirectoryServices.Protocols (LDAP) is cross-platform. | Rewrite directory lookups with System.DirectoryServices.Protocols (LDAP) against AWS Managed Microsoft AD / on-prem AD over VPN, or move to OIDC claims. **Alt:** System.DirectoryServices.Protocols; Novell.Directory.Ldap.NETStandard; IdP claims | S8 |
| `DATA-INTEGRATED-SECURITY` | Windows-integrated database authentication | High / Confirmed | Windows authentication to SQL Server from Linux needs Kerberos (domain-joined host or keytab); PostgreSQL uses password/IAM auth instead. | Switch to SQL authentication with credentials in Secrets Manager (rotation), or set up Kerberos with AWS Managed Microsoft AD. **Alt:** SQL auth + Secrets Manager rotation; IAM database auth for PostgreSQL | S8, S11 |
| `AUTH-WINDOWS` | Windows authentication / impersonation in IIS | High / Confirmed | On Linux, Windows auth needs the Negotiate handler with Kerberos (keytab, SPNs, LDAP for roles); impersonation is Windows-only. | Move users to an OIDC identity provider (IAM Identity Center, Cognito, Entra ID via federation) or configure Negotiate/Kerberos with AWS Managed Microsoft AD. **Alt:** OIDC (Cognito / Entra ID / ADFS OIDC); Negotiate + keytab | S8 |
| `AUTH-IMPERSONATION` | Windows identity / impersonation in code | High / Confirmed | WindowsIdentity and impersonation are Windows-only. | Use claims from the identity provider; access resources with IAM roles instead of impersonated accounts. **Alt:** Claims + IAM roles | S8 |
| `AUTH-FORMS-MEMBERSHIP` | Forms authentication / Membership / Role manager | High / Confirmed | Forms auth tickets and Membership providers do not exist in ASP.NET Core; password hashes need a migration strategy. | Move to ASP.NET Core cookie authentication + ASP.NET Core Identity (or an external IdP); migrate users with a rehash-on-login strategy. **Alt:** ASP.NET Core Identity / Cognito _(baseline)_ | S9 |
| `AUTH-MACHINEKEY` | machineKey configuration | High / Confirmed | machineKey protects auth cookies, ViewState and anti-forgery tokens; ASP.NET Core uses the Data Protection key ring, and web farms need shared keys. | Store keys in Secrets Manager (never in config); share a Data Protection key ring (S3 + KMS) across instances; plan cookie compatibility during cut-over. **Alt:** Data Protection + S3/KMS key ring | S9 |
| `AUTH-WSFED` | WS-Federation / ADFS (WIF) | High / Confirmed | Windows Identity Foundation is .NET Framework only. | Use Microsoft.AspNetCore.Authentication.WsFederation or switch the relying party to OIDC. **Alt:** ASP.NET Core WsFederation / OIDC | S9 |
| `AUTH-IDENTITY2` | ASP.NET Identity 2 (OWIN) | Medium / Confirmed | ASP.NET Identity 2 must move to ASP.NET Core Identity (schema and hasher differ). | Migrate to ASP.NET Core Identity; keep the v2 password hasher compatibility mode during transition. **Alt:** ASP.NET Core Identity _(baseline)_ | S9 |
| `AUTH-DEFAULT-CREDENTIALS` | Outbound calls with Windows default credentials | Medium / Likely | On Linux the process has no Windows identity; integrated auth to on-prem services needs Kerberos configuration. | Use explicit service credentials from Secrets Manager or Kerberos keytabs. **Alt:** Secrets Manager credentials | S8 |
| `AUTH-EXTERNAL-IDP` | External identity provider (OpenID Connect / Azure AD / Entra ID) | Medium / Confirmed | Sign-in is delegated to an external IdP: the OWIN middleware must be replaced, and redirect URIs, client secrets and allowed origins must be registered for the new AWS host names. | Port to ASP.NET Core OpenID Connect (or Microsoft.Identity.Web); register AWS redirect URIs; move client secrets to Secrets Manager. **Alt:** Microsoft.AspNetCore.Authentication.OpenIdConnect / Microsoft.Identity.Web; Amazon Cognito federation | S9 |

## Configuration and secrets

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `API-CONFIGMANAGER` | System.Configuration (ConfigurationManager) | Medium / Confirmed | web.config/app.config do not drive ASP.NET Core; values must move to appsettings/environment and secrets to AWS stores. | Introduce IConfiguration/IOptions; source settings from appsettings + Parameter Store and secrets from Secrets Manager. **Alt:** IConfiguration + Amazon.Extensions.Configuration.SystemsManager _(baseline)_ | S9 |
| `CFG-HARDCODED-SECRET` | Hard-coded credential or key in source | High / Likely | Credentials in source code travel with every clone and cannot be rotated. | Move to AWS Secrets Manager; rotate the exposed credential. **Alt:** AWS Secrets Manager | S21 |
| `CFG-PROTECTED-SECTION` | DPAPI/RSA-protected configuration sections | High / Confirmed | Protected config sections are machine-bound and RsaProtectedConfigurationProvider throws on .NET. | Move the protected values to Secrets Manager / Parameter Store (SecureString). **Alt:** Secrets Manager | S2 |
| `CFG-TRANSFORMS` | web.config / app.config transforms | Low / Confirmed | Per-environment transforms become appsettings.{Environment}.json + environment variables. | Map each transform to environment configuration and Parameter Store paths. **Alt:** appsettings.{env}.json + Parameter Store _(baseline)_ | S9 |

## Security and compliance

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `SEC-OLD-TLS` | Legacy TLS/SSL protocol settings | High / Confirmed | Forcing TLS 1.0/1.1 fails against modern endpoints and compliance baselines; on .NET the OS (OpenSSL) negotiates TLS. | Remove protocol pinning and let the OS choose (TLS 1.2+); verify partners support TLS 1.2+. **Alt:** OS defaults (TLS 1.2/1.3) | S3 |
| `SEC-CERT-VALIDATION-OFF` | Certificate validation disabled | High / Likely | Bypassing certificate validation hides man-in-the-middle risk and usually masks a missing internal CA. | Install the internal CA in the image / trust store, remove the bypass. **Alt:** Trusted CA bundle | S3 |
| `SEC-WEAK-CRYPTO` | Weak hashes / ciphers | Medium / Confirmed | Weak algorithms fail common compliance baselines (PCI DSS, HIPAA guidance); some legacy types are obsolete on .NET. | Use SHA-256+ and AES-GCM; keep MD5/SHA1 only for non-security checksums. **Alt:** SHA256 / AesGcm | S3 |
| `SEC-CONFIG-HARDENING` | Insecure web.config settings | Low / Confirmed | Debug builds, detailed errors and disabled request validation weaken the production posture. | Disable in production configuration; review input encoding where validation is off. | S3 |

## Hosting and IIS dependencies

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `IIS-REWRITE` | IIS URL Rewrite rules | Medium / Confirmed | IIS URL Rewrite is an IIS module; rules must move to ASP.NET Core rewrite middleware or the load balancer. | Translate rules to UseRewriter (it can import IIS rules) or ALB listener rules / CloudFront functions. **Alt:** Microsoft.AspNetCore.Rewrite / ALB rules | S9 |
| `IIS-MODULES-HANDLERS` | IIS modules and handlers registered in config | Medium / Confirmed | Module/handler registrations configure IIS; each needs an ASP.NET Core equivalent. | Map each registered module/handler to middleware or remove. **Alt:** Middleware _(baseline)_ | S9 |
| `IIS-HTTPRUNTIME` | httpRuntime / request limits | Low / Confirmed | Upload size and timeouts move to Kestrel/ALB settings. | Set KestrelServerOptions/FormOptions limits and ALB idle timeout. **Alt:** Kestrel + ALB settings | S9 |
| `IIS-PUBLISH` | IIS / MSDeploy publishing | Info / Confirmed | Deployment targets IIS today. | Replace with container images (ECR) or Linux packages deployed by CodePipeline/GitHub Actions. **Alt:** ECR + ECS/EKS; CodeDeploy | S10 |
| `HOST-WINDOWS-CONTAINER` | Windows container images | Medium / Confirmed | Windows containers keep Windows licensing and run only on Windows nodes (ECS Windows / EKS Windows). | After porting, rebuild on Linux images (mcr.microsoft.com/dotnet/aspnet:10.0); otherwise run on ECS with Windows container instances. **Alt:** Linux .NET 10 images; ECS Windows as fallback | S10 |

## State and horizontal scaling

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `FILE-LOCAL-WRITE` | Writes to the local file system | Medium / Likely | Local disk is not shared between instances and is lost with containers; files written here break horizontal scaling. | Write durable files to Amazon S3 (or EFS when a file system is required); keep only temp files locally. **Alt:** Amazon S3 / EFS | S10 |
| `IIS-SESSION-STATE` | Session state mode | High / Confirmed | In-process session needs sticky sessions and is lost on restart; StateServer/SQLServer modes are System.Web features. | Use ASP.NET Core distributed session backed by ElastiCache (Redis/Valkey) or DynamoDB; reduce session usage. **Alt:** ElastiCache (Valkey/Redis) / DynamoDB | S9 |
| `STATE-APP-CACHE` | In-process application state / cache | Medium / Confirmed | Each instance gets its own copy; data diverges once the app runs on more than one server. | Use IDistributedCache on ElastiCache for shared data; keep IMemoryCache only for per-instance, rebuildable data. **Alt:** ElastiCache (Valkey/Redis) | S9 |
| `STATE-SESSION` | Session usage in code | Medium / Confirmed | Session values must be serializable and stored out of process to scale horizontally; ASP.NET Core session stores bytes/strings only. | Minimise session; store in distributed session (ElastiCache) with JSON serialization. **Alt:** Distributed session on ElastiCache _(baseline)_ | S9 |
| `STATE-STATIC-MUTABLE` | Static mutable collections (per-process state) | Low / Needs verification | Static collections act as per-instance caches/state; behaviour changes when scaled out. | Review each: keep if rebuildable per instance, otherwise move to a shared store. **Alt:** ElastiCache / database | S10 |

## Background processing and scheduling

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `WIN-MSMQ` | MSMQ (System.Messaging) | Blocker / Confirmed | MSMQ is Windows-only and System.Messaging is not available on modern .NET. | Move the queue to Amazon SQS (or Amazon MQ for broker semantics); replace producers and consumers. **Alt:** Amazon SQS / SNS / Amazon MQ; MassTransit or NServiceBus transports | S1 |
| `WIN-SERVICE` | Windows Service (ServiceBase) | High / Confirmed | Windows services do not exist on Linux. | Convert to a .NET Worker Service (BackgroundService) run as a systemd unit, an ECS service, or scheduled ECS task / Lambda. **Alt:** .NET Worker Service + ECS/Fargate or systemd; EventBridge Scheduler for timed work _(baseline)_ | S3 |
| `STATE-WEB-BACKGROUND` | Timers / background work inside web processes | Medium / Likely | In-process timers run once per instance after scale-out and stop when the app pool/container recycles. | Move scheduled work to a hosted worker with a distributed lock, or to EventBridge Scheduler + Lambda/ECS tasks. **Alt:** EventBridge Scheduler; BackgroundService + distributed lock | S10 |
| `BG-TASK-SCHEDULER` | Windows Task Scheduler | High / Confirmed | Task Scheduler is Windows-only; jobs scheduled on the server are often undocumented. | Move schedules to EventBridge Scheduler (cron) triggering ECS tasks/Lambda. **Alt:** Amazon EventBridge Scheduler | S10 |
| `BG-HANGFIRE-QUARTZ` | Hangfire / Quartz.NET job schedulers | Low / Confirmed | Both run on .NET 10; scaled-out instances need clustered/shared job storage and dashboard authorization. | Use persistent job storage (SQL/Redis) and clustering; secure the dashboard. **Alt:** Hangfire.AspNetCore / Quartz clustering | S10 |

## Logging, monitoring and health

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `LOG-FILE-TARGETS` | File-based logging targets | Medium / Confirmed | Log files on instance disks are lost with containers and are not centralised; Event Log targets fail on Linux. | Log to stdout in JSON and collect with CloudWatch Logs (awslogs / FireLens) or use CloudWatch sinks. **Alt:** CloudWatch Logs (AWS.Logger.*), FireLens | S10 |
| `LOG-ELMAH` | ELMAH error logging | Low / Confirmed | ELMAH classic is System.Web-based. | Use ASP.NET Core exception handling middleware + CloudWatch/X-Ray (or ElmahCore). **Alt:** Exception middleware + CloudWatch / X-Ray | S9 |
| `LOG-TRACE` | System.Diagnostics trace listeners | Low / Confirmed | Config-driven trace listeners are not loaded from config on .NET. | Replace with ILogger providers. **Alt:** Microsoft.Extensions.Logging | S3 |

## Hypervisor and machine-coupling (Proxmox, VMware, Hyper-V)

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `HV-HARDWARE-ID` | Hardware / MAC / BIOS identifiers | High / Needs verification | Licensing or identity tied to hardware/MAC/BIOS breaks when VMs move hypervisor or instances are replaced. | Find what the identifier is used for (often licensing); move to instance-independent identity or re-license. **Alt:** Instance-independent IDs / vendor cloud licences | S10 |
| `HV-MACHINE-NAME` | Logic keyed on machine name / host name | Medium / Likely | Host names change on AWS (auto scaling, containers); logic that switches on server name breaks. | Use explicit configuration/environment instead of host names. **Alt:** Environment configuration | S10 |
| `HV-LOCAL-DEVICE` | Local devices (serial/COM/LPT ports, dongles, scanners) | High / Likely | Physical devices attached to an on-prem host cannot follow the workload to AWS. | Move the device interaction to an edge component (e.g. on-prem agent, IoT Greengrass) or retire it. **Alt:** Edge agent / AWS IoT Greengrass | S10 |

## Build and delivery

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `BUILD-WEB-TARGETS` | Visual Studio web application build targets | High / Confirmed | These MSBuild targets ship with Visual Studio on Windows; the project cannot `dotnet build` on Linux as-is. | Convert to SDK-style (Microsoft.NET.Sdk.Web) during the port. **Alt:** SDK-style projects _(baseline)_ | S3 |
| `BUILD-EVENTS` | Pre/post-build events with Windows commands | Medium / Confirmed | Windows shell commands in build steps fail on Linux build agents. | Replace with MSBuild tasks (Copy, Delete) or cross-platform scripts. **Alt:** MSBuild Copy/Exec with pwsh | S3 |
| `BUILD-WINDOWS-CI` | Windows-only CI agents / steps | Medium / Confirmed | Pipelines build on Windows agents with Visual Studio tasks. | Move to `dotnet` CLI steps on Linux runners (CodeBuild / GitHub Actions ubuntu). **Alt:** AWS CodeBuild / GitHub Actions Linux runners | S10 |
| `BUILD-PRIVATE-FEED` | Private NuGet feeds | Medium / Confirmed | Private packages must be available to the new build system (and uploaded to AWS Transform when it is used). | Host private packages in AWS CodeArtifact; port private packages first. **Alt:** AWS CodeArtifact | S17 |

## Automated tests

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `TEST-CODED-UI` | Coded UI / MSTest v1 tests | Medium / Confirmed | Coded UI is deprecated and Windows-only; MSTest v1 needs conversion to MSTest.TestFramework. | Move UI tests to Playwright/Selenium; convert unit tests to MSTest v3/xUnit. **Alt:** Playwright / MSTest v3 | S3 |

## Front end

| Rule | Detects | Severity | Why it matters | Fix / alternative | Sources |
| --- | --- | --- | --- | --- | --- |
| `WEB-WEBFORMS-AJAX` | Web Forms AJAX / third-party Web Forms controls | High / Confirmed | Server-side AJAX controls and vendor Web Forms suites have no ASP.NET Core counterpart. | Rebuild the interaction in the target UI stack; check vendor licences for their Blazor/Core suites. **Alt:** Blazor components / vendor Core suites _(baseline)_ | S9 |
| `WEB-SIGNALR-LEGACY` | ASP.NET SignalR (legacy) | High / Confirmed | ASP.NET SignalR and ASP.NET Core SignalR use incompatible protocols; server and JavaScript client both change. | Port hubs to ASP.NET Core SignalR and update clients; use a Redis backplane (ElastiCache) when scaled out. **Alt:** ASP.NET Core SignalR + ElastiCache backplane | S9 |
| `FE-LEGACY-LIBS` | Outdated client libraries | Medium / Confirmed | Old jQuery (< 3.5) and AngularJS (EOL) carry known vulnerabilities and complicate the UI port. | Upgrade or replace during the UI work; serve from a bundler or CDN. **Alt:** jQuery 3.7+ / modern framework | S3 |
| `FE-BUNDLING` | System.Web.Optimization bundling | Low / Confirmed | Runtime bundling is not available in ASP.NET Core. | Bundle at build time (Vite/esbuild) or use WebOptimizer. **Alt:** Vite / esbuild / LigerShark.WebOptimizer _(baseline)_ | S9 |
| `FE-VIEWSTATE` | ViewState reliance | Medium / Confirmed | ViewState/postback state management has no equivalent outside Web Forms. | Redesign page state in the target UI. **Alt:** Component state (Blazor) / client state _(baseline)_ | S9 |

## Checks implemented in scanner code (not in rules.json)

| ID | Detects |
| --- | --- |
| `INV-LEGACY-PROJECT`, `INV-PACKAGES-CONFIG`, `INV-TFM-SUPPORT`, `INV-CORE-ON-FRAMEWORK`, `INV-WEBSITE-PROJECT` | Project format, package format, target-framework support status, ASP.NET Core on .NET Framework, Web Site projects |
| `PKG-<status>` / `SEC-VULN-<package>` | Package map + api.nuget.org metadata (blocker, replace, windows-only, licence, private; published advisories) |
| `NET-ENDPOINT-INTERNAL` / `-PUBLIC-IP` / `-EXTERNAL` | URLs, host names, IPs, connection-string servers classified on-prem vs external |
| `CFG-SECRET-SETTING`, `CFG-PLAINTEXT-DB-PASSWORD`, `CFG-DEV-DATABASE` | Secret-like appSettings (names only), passwords in connection strings (never copied), developer-only databases |
| `FILE-CASE-MISMATCH` | Path literals whose case differs from the file on disk |
| `DB-SSIS`, `DB-SSRS`, `DB-SSAS`, `INT-CRYSTAL-FILES`, `INT-RDLC-FILES`, `BUILD-SCRIPTS` | Artefact files |
| `TEST-LOW-COVERAGE`, `LOG-NO-HEALTHCHECK`, `MOD-ON-WINDOWS`, `DEV-ACTIVITY` | Test density, health endpoint, modern .NET on Windows hosting, repository activity |
