> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Audit KB coverage in dotnet skill

agent ad7a1b83d1b167738

READ-ONLY audit complete. No files were written in the repos or the skill. The zip was extracted only to a fresh scratchpad folder.

SCOPE NOTE: 00..28 is 29 numbered KB files, not 28. The skill README and SKILL.md say "28 files", which is off by one. The first audit brief I sent had an empty file list, so the audit covered all 29 files. Its findings were spot-checked against the source files.

A) Coverage of the 29 KB files
R = REFERENCED (cited by file name or "KB NN" in a playbook or reference). Every file is also in the SKILL.md:96 link list. T = TOPIC-ONLY. N = NOT COVERED (index link only).
- 00 R: engines.md:82, playbooks/README build row
- 01 R: build-and-packages.md:5
- 02 R: systemweb-residue.md:4
- 03 N: MVC has no playbook text
- 04 N: Web API 2 has no playbook text
- 05 R: startup-and-middleware.md:4
- 06 R: build-and-packages.md:5, engines.md:34
- 07 R: raw-sql-and-data-access.md:4
- 08 R: auth.md:4
- 09 T: bundling only at webforms-ui.md:41
- 10 R: startup-and-middleware.md:4
- 11 R: config-and-secrets.md:5
- 12 R: logging.md:4
- 13 R: startup-and-middleware.md:4
- 14 R: http-handlers-and-modules.md:4
- 15 T: static files only in startup and webforms playbooks
- 16 R: raw-sql-and-data-access.md:4
- 17 R: raw-sql-and-data-access.md:4
- 18 R: raw-sql-and-data-access.md:4
- 19 R: linux-and-containers.md:4, workflow.md:76
- 20 R: wcf-services.md:4
- 21 R: windows-only-apis.md:4
- 22 R: windows-only-apis.md:4
- 23 N: no Swagger text
- 24 R: build-and-packages.md:22 (one line only)
- 25 R: webforms-ui.md:4
- 26 R: webforms-ui.md:4
- 27 R: build-and-packages.md:15
- 28 R: ambient-context-and-remoting.md:4-5 (playbook is about 40 lines)
Totals: 24 R, 2 T, 3 N (03, 04, 23).

B) Diff and zip
- Toolkit KB vs skill reference/kb: 25 of 29 byte-identical. Four differ only by redaction in the skill copy: 07 (line 110), 11 (line 72), 17 (line 148), 19 (lines 60, 80, 122). The skill copy replaces sample passwords with a placeholder. The toolkit copy still holds the sample passwords, which is a hygiene point for the toolkit.
- The skill copy also has LICENSE-Apache-2.0.txt, which the toolkit folder lacks.
- The zip has 30 entries (00-28 plus README) and no LICENSE. Every entry is byte-identical to the toolkit folder (cmp). It holds no files, versions or content beyond the folder. It has the toolkit versions of 07, 11, 17 and 19, not the redacted ones. Extracted copy: <scratchpad>\kbzip

C) Gaps
- [HIGH] 04 Web API 2 to Core (ApiController, IHttpActionResult, RoutePrefix, DelegatingHandler, exception filters) | none in skill | new section in systemweb-residue.md or a new playbook
- [HIGH] 03 MVC (areas, AreaRegistration, filters, explicit area routes) | none | startup-and-middleware.md
- [HIGH] 07 EF6 to EF Core (DbContext options ctor, DbEntityEntry to EntityEntry, [Index] to HasIndex, SqlServerCe removal) | one table row only | raw-sql-and-data-access.md
- [HIGH] 28 Remoting (classification tree, BinaryFormatter DTO rework, channels to gRPC or named pipes, [OneWay] to SQS, [Synchronization], TransactionScope) | thin playbook | ambient-context-and-remoting.md
- [HIGH] 23 Swagger/Swashbuckle to AspNetCore.Swagger, and Swagger 2 to OpenAPI 3 client impact | none | startup-and-middleware.md or a new playbook
- [MED] 16 EF6 baseline (__MigrationHistory), keep index names, lazy-loading proxies, concurrency | none | raw-sql-and-data-access.md
- [MED] 17 Dapper patterns; Microsoft.Data.SqlClient 4+ Encrypt=true defaults causing TLS failures on Linux | none | raw-sql-and-data-access.md, linux-readiness rule
- [MED] 18 NHibernate config, session per request, FluentMigrator | table cell only | raw-sql-and-data-access.md
- [MED] 08 OWIN to Core cookie and Identity 2 schema backfill, antiforgery, JWT | partial | auth.md
- [MED] 14 OWIN host (IAppBuilder, UseWebApi, OwinMiddleware) | rule only | http-handlers-and-modules.md
- [MED] 22 PBKDF2 (Rfc2898DeriveBytes), RSACryptoServiceProvider to GetRSAPrivateKey | none | windows-only-apis.md
- [MED] 24 NUnit 2 to 3 renames, RhinoMocks to Moq/NSubstitute | one line | build-and-packages.md
- [MED] 26 Blazor Server operations (sticky sessions, circuit memory, Data Protection keys) | none | webforms-ui.md
- [MED] 27 NU1701/NU1608/NU1605/NU1902 remediation | KB pointer only | build-and-packages.md
- [MED] 09 bundling and static assets (esbuild, cache headers) | webforms-ui.md:41 only | startup-and-middleware.md
- [MED] 02 Request.Files to IFormFile; GlobalFilters to options.Filters | none | systemweb-residue.md, startup-and-middleware.md
- [MED] 00 System.Web.Caching/Hosting/Security namespace map; IRegisteredObject to IHostedService; VirtualPathProvider to IFileProvider | none | systemweb-residue.md, background-work.md
- [MED] 20 ClientBase string-name constructor (config endpoints unsupported) | none | wcf-services.md
- [LOW] 01 NETSDK1022 duplicate Compile/Content; CS0579 AssemblyInfo | none | build-and-packages.md
- [LOW] 11 dotnet user-secrets for dev; 13 Autofac; 15 Razor helpers; 21 ImageFormat to encoders

D) KB sample errors (uncorrected unless noted)
- 00:23,31; 07:~122-141; 16:151 — claim [Index] is unsupported in EF Core. It is supported (IndexAttribute, EF Core 5+). Skill silent.
- 07:16 — Database.SqlQuery<T> to FromSqlRaw/FromSqlInterpolated. Non-entity results need SqlQueryRaw<T> (EF Core 7+). Skill silent.
- 16:201-204 — keyless DTO via Set<Dto>().FromSqlRaw is outdated. Skill silent.
- 02:60 — IHostingEnvironment vs IHostEnvironment "ambiguous CS0104": likely wrong. Skill silent.
- 02:304 — new ExceptionFilterAttribute(): abstract class, compile error. Skill silent.
- 03:143 — AreaRegistration "discovered by convention": wrong for Core. Skill silent (no MVC text).
- 10:10 — IStartupFilter for global MVC filters: wrong (it configures middleware). Skill silent.
- 09:122-131 — MapStaticAssets called a .NET 10 feature; it shipped in .NET 9. Skill silent. 09:109-111 says "immutable" while the esbuild step emits no content hash: internal contradiction.
- 19:87 — SA_PASSWORD "Pass123" fails SQL Server complexity, so the container will not start. Skill silent.
- 26:53-54 — expression-bodied async assignment (=> _orders = await ...) does not compile for Task return. Skill silent.
- 28:221 and 28:712 — list Uri as an in-box MarshalByRefObject descendant: wrong. 28:141 says "three artifacts survive" against a table of about eight: contradiction. Skill silent.
- 06:14 — "dotnet migrate packages.config" is not a CLI command. Skill silent.
- 06:190 — WebOptimizer.Core package ID is likely wrong (assessment package-map uses LigerShark.WebOptimizer.Core).
- 17:148 — docker run with password in ENV. Skill's linux-and-containers.md:44 corrects the principle; the bundled sample still shows ENV use (only the value was redacted).
- 19:136, 19:60/80/122, 19:185, 19:230-235 (HEALTHCHECK curl, secrets in ENV, no USER, migrate in entrypoint): corrected in linux-and-containers.md:42-44.
- 01:221 presents Upgrade Assistant as current; 28:674 and engines.md:88 say it is deprecated. Cross-file contradiction; skill's engines.md is the corrected view.
- 08:252 — antiforgery "read the token from the cookie" is unclear rather than clearly wrong; it depends on whether the cookie is a JS-readable request-token cookie. Verify before relying on it.
- Divergences (not corrected, skill chose differently): 12:6 says migrate off log4net/NLog, interim keep allowed; logging.md:9 says they can stay as the provider. 01 says libraries are netstandard2.0; build-and-packages.md:10-11 says net10.0.
- Unverified version and ID claims (not checked; do not rely on them): 18:40/55/77 (MicrosoftDataSqlClientDriver, PostgreSQL83Dialect); 20:4 "officially supported by Microsoft" for CoreWCF; 20:40/171 package versions; 21:36 SkiaSharp version; 23:24-26 pins; 24:33/38 NUnit 4.x claims; 28:600 CVE status.

E) Detectable patterns with no rule
- System.Data.Entity / DbEntityEntry / [Index] (KB 00, 07, 16) | residue_rules.json (assessment rules.json has only DATA-EF6)
- Encrypt / TrustServerCertificate on SqlClient (KB 17) | linux_readiness.json (0 hits; assessment rules.json has 1)
- Swashbuckle, SwaggerConfig, EnableSwagger, IExamplesProvider (KB 23) | residue_rules.json (only package_map.json has Swashbuckle)
- Rfc2898DeriveBytes, RSACryptoServiceProvider casts, SHA256Managed, AesManaged (KB 22) | residue_rules.json
- TcpChannel, IpcChannel, ChannelServices, Activator.GetObject, [OneWay], [Synchronization], ISponsor/ILease, [OnDeserialized] (KB 28) | residue_rules.json (API-REMOTING exists but is narrow)
- WebServiceHostFactory (KB 20) | residue_rules.json (LOW)
- IHostingEnvironment (KB 02) | residue_rules.json (LOW-MED)
- NU1701/NU1608 build-log warnings (KB 27) | no catalogue rule (LOW)

Counts for reference: residue_rules.json has 44 rules, linux_readiness.json has 240, assessment rules.json has 186.
