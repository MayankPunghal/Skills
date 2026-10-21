# Playbooks

Claude's clean-up after the porting engine, one playbook per kind of change. `residue_scan.py` and `linux_readiness.py` name the playbook for every hit; the modernization-assessment execution plan groups the clean-up the same way. Apply one playbook per commit, rebuild after each, rerun the scans.

| Playbook | Covers | Residue rules | DevTx KB | AWS Transform |
|---|---|---|---|---|
| [build-and-packages](build-and-packages.md) | SDK-style projects, TFMs, packages, HintPaths, web targets | PROJ-* | 00, 01, 06, 24, 27 | yes |
| [systemweb-residue](systemweb-residue.md) | `HttpContext.Current`, `Server.MapPath`, `HttpRuntime.Cache`, System.Web in shared libraries (adapters, pass-the-values) | WEB-SYSTEMWEB-NS, WEB-HTTPCONTEXT-CURRENT, FILE-MAPPATH | 02 | most, in the web project |
| [http-handlers-and-modules](http-handlers-and-modules.md) | `.ashx`, `IHttpHandler`/`IHttpAsyncHandler`, `IHttpModule` → endpoints and middleware | WEB-HANDLER-IFACE | 14 | partly |
| [webforms-ui](webforms-ui.md) | `.aspx`/`.ascx`/`.master` with code-behind and script → Blazor or Razor Pages, page by page | WEB-FORMS-FILE | 25, 26 | Blazor Server, with an unsupported list |
| [asmx-and-soap-clients](asmx-and-soap-clients.md) | ASMX services, Web References, SOAP clients | WEB-SOAP-PROXY | — | some clients |
| [wcf-services](wcf-services.md) | WCF services (CoreWCF) and clients (svcutil), wire compatibility | — | 20 | yes |
| [startup-and-middleware](startup-and-middleware.md) | Global.asax → Program.cs, DI, middleware order, ALB forwarded headers, session and state | CFG-WEBCONFIG-APP | 05, 10, 13, 14 | yes |
| [config-and-secrets](config-and-secrets.md) | web.config → appsettings, protected sections, secrets to Secrets Manager / Parameter Store | CFG-* | 11 | partly |
| [auth](auth.md) | Forms auth, machineKey, data protection keys, Windows auth, AD, impersonation | API-WINDOWS-IDENTITY | 08 | partly |
| [ambient-context-and-remoting](ambient-context-and-remoting.md) | CallContext → AsyncLocal, Remoting, BinaryFormatter | API-CALLCONTEXT, API-BINARYFORMATTER | 28 | no |
| [windows-only-apis](windows-only-apis.md) | Registry, COM, COM+, P/Invoke, PerformanceCounter, WMI, System.Drawing, DPAPI, weak crypto, named kernel objects; desktop apps | API-* | 21, 22 | flags CA1416 |
| [background-work](background-work.md) | Windows services, Task Scheduler, timers, `QueueBackgroundWorkItem`, SIGTERM | — | — | no |
| [time-and-culture](time-and-culture.md) | UTC containers, zone IDs, ICU vs NLS, encodings, line endings | TZ-* | — | no |
| [logging](logging.md) | stdout JSON, `ILogger`, EventLog, file appenders, hosted log services, OpenTelemetry | API-EVENTLOG, SVC-HOSTED-LOG | 12 | no |
| [linux-and-containers](linux-and-containers.md) | Letter case, paths, processes, environment, the Dockerfile (non-root, 8080, health, no secrets) | FILE-DRIVE, FILE-BACKSLASH-JOIN, HOST-MACHINE-NAME | 19 (fix its samples) | Next Steps list only |
| [aws-managed-services](aws-managed-services.md) | Redis, Memcached, Aerospike, SMTP, SFTP/file shares, MSMQ, MongoDB, hosted logging → AWS services | SVC-*, API-MSMQ, FILE-UNC | — | no |
| [raw-sql-and-data-access](raw-sql-and-data-access.md) | SQL Server → PostgreSQL in the code: seams, contract, refcursors, multi-result sets, OUTPUT, TVPs, bulk copy, transactions, errors, types | DB-*, SQL-* | 07, 16, 17, 18 (SQL Server only) | no (DB porting agent or Claude with the DB porting skills) |

Each playbook has the same shape: **Rules** (what sends you here), **Engines** (what the engine already did), the steps, **Gotchas**, **Done when**. A playbook that says a change needs a decision (retire a feature, change a contract external callers use, move users to a new sign-in) stops for the user.
