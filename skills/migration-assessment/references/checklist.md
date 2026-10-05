# Assessment checklist (engagement section 5, extended by research)

Every row is covered by a scanner (automated, with evidence), by reviewer reading (judgment, with evidence), or by a client question (when code cannot decide). **★** marks items added by the October 2026 research.

Rule IDs refer to `scripts/data/rules.json`. Synthetic IDs are produced by the scanner code: `INV-*`, `PKG-*`, `SEC-VULN-*`, `NET-ENDPOINT-*`, `CFG-*`, `DEV-ACTIVITY`, `TEST-LOW-COVERAGE`, `MOD-ON-WINDOWS`, `FILE-CASE-MISMATCH`, `LOG-NO-HEALTHCHECK`, `DB-SSIS/SSRS/SSAS`.

## A. Questions asked on every engagement (5.1)

| # | Check | Automated (evidence) | Reviewer judgment | Client question |
| --- | --- | --- | --- | --- |
| 1 | Linux readiness of each app | `WIN-*`, `API-*`, `WEB-*`, `DESK-*`, `INV-*`; `validate_linux_build.py` (CA1416, build errors) | Confirm each Blocker/High is reachable code (graphify `affected`) and not dead code | — |
| 2 | Third-party services/libraries that may break on AWS (IP allow-lists, VPN, hard-coded hosts) | `NET-ENDPOINT-INTERNAL/PUBLIC-IP/EXTERNAL`, `NET-UNC-SHARE`, `NET-SMTP`, `NET-FTP`, `NET-PROXY`, `WCF-CLIENT`, packages | Identify what each host is (from names, config keys, code around the call) | Who owns each on-prem host; which partners allow-list IPs |
| 3 | DB libraries that may not work with PostgreSQL | `DATA-*`, `DB-*`, packages (`Microsoft.SqlServer.Types`, `Oracle.DataAccess`, `System.Data.SQLite`) | Map data access per app (EF6/EDMX, ADO.NET, Dapper, stored procedures) | Database sizes, HA needs, SQL Server edition and version |
| 4 | Auth compatibility (Windows auth/NTLM/Kerberos, AD, ADFS, Forms, Identity, cookies, machine keys) | `AUTH-*`, `WIN-DIRSERVICES`, `DATA-INTEGRATED-SECURITY`, `AUTH-EXTERNAL-IDP` ★ | Trace the sign-in flow and role checks | IdP, domain, SSO plans |
| 5 | Moving from Proxmox / VMware / Hyper-V | `HV-*`, internal IPs | Look for licensing/hardware coupling | Hypervisor, VM sizes, static IPs, VLANs, attached devices; MGN replication path (agent-based, source-agnostic) |
| 6 | WCF / WPF needing rewrite | `WCF-SERVICE`, `WCF-BINDING`, `WCF-CLIENT`, `WEB-ASMX`, `DESK-WINFORMS`, `DESK-WPF` | CoreWCF fit per binding; desktop app's role | Who calls the services; desktop users count |
| 7 | Tooling: what CAST etc. find vs manual review | Tooling table in report (category `tooling`) | Fill gaps the tools cannot see | Whether CAST Highlight/Imaging licences exist |
| 8 | File handling: paths, `\` vs `/`, drive letters, case, long paths, UNC | `FILE-*`, `NET-UNC-SHARE`, `FILE-CASE-MISMATCH` (literals checked against disk) ★ | Where uploaded/generated files live | Size and owners of file shares |
| 9 | Run on Linux / WSL as validation | `validate_linux_build.py` (plan → run) | Interpret failures | Approval for container/NuGet downloads |
| 10 | Modern .NET still on Windows | `MOD-ON-WINDOWS`, `INV-TFM-SUPPORT` (.NET 8/9 end 10 Nov 2026 ★) | Why it is on Windows | Hosting today |
| 11 | Upstream/downstream dependencies | Dependency table (endpoints, connection strings, WCF endpoints, SMTP, shares) | Direction of each integration (who calls whom) | Systems outside the repositories |
| 12 | 7R per application | `classify_apps.py` (draft) | **Required:** confirm/override every app in `decisions.json` | Retire candidates; business criticality |

## B. Areas added in the brief (5.2), extended

| Area | Automated | Judgment / question |
| --- | --- | --- |
| Inventory | Solutions (.sln and .slnx ★), project format, TFMs and their **support status** ★, project types (from type GUIDs, SDK, references, files), packages.config vs PackageReference, languages, LOC, Web Site projects ★, ASP.NET Core on .NET Framework ★ | Business purpose of each app |
| Windows-only APIs | Registry, Event Log, WMI, perf counters, System.Drawing (file-level `System.Drawing` + imaging types), COM, Win32 P/Invoke, other native P/Invoke ★, DirectoryServices, MSMQ, ServiceBase, **DPAPI ProtectedData** ★, **CNG/CSP** ★, **certificate store** ★, ACLs ★, shelling out to .exe/.bat ★, Crystal, Office interop, System.Web, HttpContext.Current, AppDomain, Remoting, CAS, BinaryFormatter, **XSLT script blocks** ★, **CodeDom compile** ★, **Thread.Abort** ★, **reflection-only load** ★ | Reachability |
| API portability | Rule catalogue mirrors MS "unsupported APIs" (S2) and "technologies unavailable" (S1); CA1416 via validate_linux_build.py | Run AWS Transform / Copilot modernization assessment for the full API diff when available |
| NuGet packages | Package map (status, replacement, licence, known-vulnerable floors) + api.nuget.org (frameworks of latest, deprecation, **published advisories per version** ★, licence expression) | Commercial licence renewals; private packages (source availability ★) |
| Data layer | EF6/EDMX ★, System.Data.SqlClient ★, OLE DB/Jet ★, ODBC, unmanaged Oracle ★, TransactionScope/MSDTC (distributed tx are Windows-only on .NET ★), SqlDependency ★; T-SQL: CLR, linked servers, xp_cmdshell, FILESTREAM/FileTable, Service Broker, distributed tx, Agent jobs, cross-db, BULK INSERT ★, full-text, T-SQL needing PostgreSQL rework ★, server config/TRUSTWORTHY/replication ★, Database Mail ★, GETDATE vs UTC ★; SSIS/SSRS/SSAS artefacts (SSIS/SSRS/SSAS are bound to SQL Server ★) | Dual vs PostgreSQL-only; DMS Schema Conversion on a schema export |
| Config and secrets | Transforms, ConfigurationManager, connection strings (server, db, auth mode, password present: never the value), secret-like appSettings, hard-coded secret literals, protected config sections ★, dev-only LocalDB strings ★ | Where production config lives |
| Hosting | IIS rewrite, modules/handlers, httpRuntime limits, session state, publish profiles, Windows container images ★ | App-pool identities, IIS features in use |
| State and scale | Session usage, Application/Cache/MemoryCache, static collections, in-process timers / QueueBackgroundWorkItem ★, local file writes | Load-balancer stickiness today |
| Background | Windows services, Task Scheduler (code and scripts ★), Hangfire/Quartz, MSMQ | Full list of scheduled tasks/jobs on servers |
| Storage | UNC, drive letters, local writes, encodings/code pages ★, CRLF ★ | Data volumes |
| Logging | File targets, Event Log targets, ELMAH, trace listeners, missing health endpoint ★ | Monitoring tools in use |
| Email/reporting/printing/fax | SMTP, printing, fax, Office, Crystal, ReportViewer/RDLC ★, SSRS clients ★, PDF engines with native deps ★, SharePoint/EWS ★ | Printers, relays |
| Time zones and culture | Windows TZ IDs, DateTime.Now/Today (AWS hosts run UTC ★), GETDATE in SQL ★, hard-coded cultures, web.config globalization ★ | Server time zone today |
| Security and compliance | Old TLS pinning, certificate-validation bypass ★, weak crypto, insecure web.config, vulnerable packages, outdated client libs, hard-coded credentials | Compliance regime, residency |
| Build and delivery | Legacy csproj, packages.config, WebApplication.targets ★, build events, Windows CI agents/tasks, private feeds, scripts | CI/CD platform, release cadence |
| Tests | Test projects, frameworks, test-method counts, tests/KLOC, Coded UI/MSTest v1 ★ | QA availability |
| Front end | jQuery/Bootstrap/AngularJS/Modernizr versions, bundling, Web Forms AJAX/vendor suites ★, ViewState, legacy SignalR ★ | UX change appetite |
| Cost | Licensing effect table (apps leaving Windows, databases leaving SQL Server) | Licences, utilisation → AWS OLA |
| Parallel development | Commits/week, authors, hot files, branches, shallow-clone warning | Branching model, freeze windows |

## C. What the scanner deliberately does not decide

- **Business value and Retire decisions.** It flags duplicates and dormant repositories, but the client decides.
- **Exact remediation for Needs-verification findings.** The reviewer reads the code (see [review-findings.md](review-findings.md)).
- **Anything only visible on servers.** That means scheduled tasks, IIS settings, certificates and firewall rules; they are always open questions.
- **Prices.** The licensing effect is computed; the money comes from client data and AWS OLA.
