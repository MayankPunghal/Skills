> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Audit KB files 00-05 vs skill

agent abbfb059740ba1653

AUDIT REPORT (read-only; no files written)

SCOPE NOTE: The brief's file list was empty, and the KB has 29 numbered files (00-28, including 16 and 17), not 28. I audited all 29. KB base: ...\migration-knowledge\dotnet\ ; skill base: ...\dotnet-modernization\. Every KB file is named in SKILL.md:96 (a link list only), so each is REFERENCED by name. "Topic gap" below means the subject has no guidance in the playbooks. Secret values in the KB were not repeated.

00 | REFERENCED | engines.md:82, playbooks/README.md (build row), SKILL.md:96
  GAPS: [MED] namespace map (System.Web.Caching/Hosting/Security) and IRegisteredObject→IHostedService, VirtualPathProvider→IFileProvider: systemweb-residue.md, background-work.md
  ERRORS: L23/L31 "[Index] not supported in modern .NET": EF Core has IndexAttribute (CS0616 usually means a missing using). Skill: not repeated. L51 blanket System.Data.Entity→Microsoft.EntityFrameworkCore misleads. Skill auth.md:11 partly corrects the Security mapping.
  RULES: System.Data.Entity/EF6 not in residue_rules.json (DATA-EF6 only in assessment rules.json)

01 | REFERENCED | build-and-packages.md:5, engines.md:31
  GAPS: [MED] NETSDK1022 duplicate Compile/Content fix, CS0579 AssemblyInfo fix: build-and-packages.md
  ERRORS: L221 Upgrade Assistant presented as current, no deprecation note; KB28:674 and engines.md:88 say deprecated (cross-file contradiction). L10/L82 libraries always netstandard2.0; build-and-packages.md:10-11 says net10.0 unless shared with .NET Framework.
  RULES: NETSDK1022 pattern: none (LOW)

02 | REFERENCED | systemweb-residue.md:4
  GAPS: [MED] Request.Files→IFormFile; GlobalFilters.Filters.Add→AddControllersWithViews(o=>o.Filters...): systemweb-residue.md, startup-and-middleware.md
  ERRORS: L60 IHostingEnvironment "ambiguous CS0104" with IHostEnvironment: names differ, likely wrong. L304 `new ExceptionFilterAttribute()`: abstract class, CS0144 compile error. L75 unsanitised file.FileName in Path.Combine (LOW). Skill: not repeated.
  RULES: IHostingEnvironment: none (LOW-MED)

03 | REFERENCED (SKILL.md:96 only) | topic NOT COVERED
  GAPS: [HIGH] no MVC/areas/filters guidance. Area routes need an explicit {area:exists} route; nothing is discovered by convention: startup-and-middleware.md (new MVC section)
  ERRORS: L143 AreaRegistration "No action required, discovered by convention": wrong. L49 ActionResult/IActionResult "interchangeable": loose. L124 [Authorize(Roles=…)]→[Authorize] "same syntax" is confusing; namespace change missing.
  RULES: area registration: none specific (System.Web namespace rule catches it)

04 | REFERENCED (SKILL.md:96 only) | topic NOT COVERED
  GAPS: [HIGH] Web API 2→Core: ApiController/IHttpActionResult, RoutePrefix, DelegatingHandler, ExceptionHandler/filters: no playbook. [MED] Newtonsoft ReferenceLoopHandling via AddNewtonsoftJson: build-and-packages.md
  ERRORS: L14 Microsoft.AspNetCore.Mvc.Core package is unnecessary with the Web SDK (LOW)
  RULES: WEB-WEBAPI2 and ApiController present in rules.json. OK

05 | REFERENCED | startup-and-middleware.md:4
  GAPS: none significant
  ERRORS: L40 ASPDEPR008 ID unverified. Two "Step 10" headings (L179, L191). L186 calls IVirtualPathProvider "obsolete" when these are System.Web types that do not exist in Core (LOW)
  RULES: none

06 | REFERENCED | build-and-packages.md:5, engines.md:34
  GAPS: [MED] EF/Dapper/NHibernate version guidance: raw-sql-and-data-access.md. [LOW] HtmlSanitizer↔AngleSharp conflict (§7): build-and-packages.md
  ERRORS: L14 `dotnet migrate packages.config`: no such CLI command (retired tool). L190 WebOptimizer.Core: likely wrong ID (assessment package-map uses LigerShark.WebOptimizer.Core). L86 NHibernate "supports .NET 10": unverified.
  RULES: none new

07 | REFERENCED | raw-sql-and-data-access.md:4
  GAPS: [HIGH] EF6→EF Core steps absent (DbContext(DbContextOptions) ctor, DbEntityEntry→EntityEntry, [Index]→HasIndex, SqlServerCe removal, NuGet.Core #if false). Only one table row (raw-sql-and-data-access.md:50). [MED] Dapper: DI connection, type handlers, async, Microsoft.Data.SqlClient swap
  ERRORS: L16 Database.SqlQuery<T>→FromSqlRaw/FromSqlInterpolated: those need entity or keyless types; non-entity results use Database.SqlQueryRaw<T> (EF Core 7+). L122-141 [Index] claim as in 00. L29 class AppContext shadows System.AppContext (LOW)
  RULES: System.Data.Entity, DbEntityEntry, [Index] missing from residue_rules.json [MED]

08 | REFERENCED | auth.md:4
  GAPS: [MED] OWIN→Core cookie and Identity wiring, Identity 2 schema (NormalizedUserName backfill, LockoutEnd): auth.md. [MED] antiforgery migration, JWT bearer, IClaimsTransformation: auth.md. [LOW] SAML2 (Sustainsys)
  ERRORS: L252 "read the token from the antiforgery cookie and send it in the header": wrong (the request token comes from IAntiforgery.GetAndStoreTokens; the cookie holds the cookie token). Security-relevant; skill not repeated. L23 Microsoft.AspNetCore.Authentication.Cookies pinned at 8.0.10: unverified (shared-framework package). L356 X509CertificateLoader (.NET 9+) in sample (LOW)
  RULES: AUTH-* present in rules.json

09 | REFERENCED (SKILL.md:96 only) | topic only in assessment package-map
  GAPS: [MED] no bundling or static-asset playbook (esbuild build step, asp-append-version, cache headers): webforms-ui.md:41 is the only mention
  ERRORS: L122-131 MapStaticAssets called a .NET 10 feature; it shipped in .NET 9 (works on 10). L109-111 says "immutable" for .bundle. files, but the L85 esbuild command emits no content hash: contradictory, risks stale assets. L18 BundlerMinifier "removed from templates": unverified.
  RULES: none (LOW)

10 | REFERENCED | startup-and-middleware.md:4
  GAPS: [MED] GlobalFilterCollection→options.Filters: startup-and-middleware.md
  ERRORS: L10 IStartupFilter for global MVC filters: wrong (it configures the middleware pipeline)
  RULES: GlobalFilterCollection: none (namespace rule covers)

11 | REFERENCED | config-and-secrets.md:5
  GAPS: [LOW] dotnet user-secrets for dev
  ERRORS: L45 says Program.cs picks the environment file; the host does (LOW). L72 user-secrets sample contains a sample password (noted, not repeated).
  RULES: none

12 | REFERENCED | logging.md:4
  GAPS: none
  ERRORS: L6 KB says migrate log4net/NLog off entirely (preferred); logging.md:9 says they "can stay as the provider". Contradiction; KB12 claims to own this decision.
  RULES: none

13 | REFERENCED | startup-and-middleware.md:4
  GAPS: [LOW] Autofac modules→Microsoft DI (package_map covers the IDs)
  ERRORS: L13 AddSingleton<ICache, MemoryCache>: MemoryCache does not implement an app ICache (LOW). L36 "Unity direct mapping": unverified
  RULES: Autofac covered in package_map

14 | REFERENCED | http-handlers-and-modules.md:4, startup-and-middleware.md:4
  GAPS: [MED] OWIN host (IAppBuilder, UseWebApi, OwinMiddleware, UseCors(CorsOptions)): no text (WEB-OWIN rule only)
  ERRORS: L14 IAppBuilder↔WebApplication: loose (LOW)
  RULES: none

15 | REFERENCED (SKILL.md:96 only)
  GAPS: [LOW] Razor helpers, _ViewStart/_ViewImports, Html.Partial/RenderAction: none
  ERRORS: none found
  RULES: none

16 | REFERENCED | raw-sql-and-data-access.md:4
  GAPS: [HIGH] see 07. [MED] keep index names (HasDatabaseName), EF6 __MigrationHistory baseline, lazy-loading proxies, concurrency changes
  ERRORS: L144 `migrations add --ignore-changes`: unverified. L151 "EF Core avoids non-supported attributes" implies [Index] unsupported: wrong (as 00). L201-204 keyless DTO via Set<Dto>().FromSqlRaw: outdated (SqlQueryRaw)
  RULES: none new

17 | REFERENCED | raw-sql-and-data-access.md:4
  GAPS: [MED] Dapper patterns (DI factory, type handlers, async, transactions): no text. [MED] Microsoft.Data.SqlClient 4+ defaults Encrypt=true: Linux TLS/certificate connection failures unless trusted. No text and no rule.
  ERRORS: L148 `docker run -e …Password=…` with a sample password, putting a secret in ENV (contrary to skill linux rule). L126-139 LoggingConnection skeleton incomplete (LOW)
  RULES: Encrypt/TrustServerCertificate detection missing in linux_readiness.json [MED]

18 | REFERENCED | raw-sql-and-data-access.md:4
  GAPS: [MED] NHibernate: no playbook guidance (only a table cell and DATA-NHIBERNATE-DIALECT in rules.json). Config (dialect/driver), session-per-request, FluentMigrator.
  ERRORS: L40/L55/L77 MicrosoftDataSqlClientDriver and PostgreSQL83Dialect: unverified or outdated. L169 LogProvider.SetCurrentLogProvider contradicts L165 (MS logging integration): unverified. L94 async "5.3" vs L206 "5.4" (LOW)
  RULES: none

19 | REFERENCED | linux-and-containers.md:4, workflow.md:76, linux-readiness.md:96
  GAPS: none significant (container rules cover it)
  ERRORS: L136 HEALTHCHECK curl (no curl in runtime images): skill corrects (linux-and-containers.md:42). L60/L80/L122-123 passwords in ENV/compose/image: skill corrects (L44). L230-235 migrate --apply in entrypoint: skill corrects (migrations not in entrypoint). L185 "set USER" but no USER in any sample: skill corrects. L87 SA_PASSWORD "Pass123" fails SQL Server complexity (container will not start): not corrected. L217-237 SmartStore-specific; ExcludeFromSingleFile applies only to single-file publish (LOW).
  RULES: HEALTHCHECK, curl, USER, ENV secrets present in linux_readiness.json

20 | REFERENCED | wcf-services.md:4, asmx-and-soap-clients.md:4
  GAPS: [MED] client ClientBase string-name ctor gap (config-file endpoints unsupported in System.ServiceModel.* clients): wcf-services.md Clients. [MED] Upgrade Assistant adds CoreWCF to client projects: wcf-services.md
  ERRORS: L4 "officially supported by Microsoft": unverified (community project). L161 "source code does not change" contradicts L181 (constructor change needed). L40 CoreWCF 1.6.0 and L171 System.ServiceModel.Primitives 8.1.0: unverified
  RULES: ClientBase, ChannelFactory, ServiceModel present. WebServiceHostFactory missing (LOW)

21 | REFERENCED | windows-only-apis.md:4
  GAPS: [LOW] image API mapping (ImageFormat→encoders)
  ERRORS: L36 SkiaSharp 4.150.1 and L71 "SKFilterQuality removed in v4": unverified. L50 ImageSharp 4.0 licence-key claim: unverified
  RULES: System.Drawing and SkiaSharp/ImageSharp present

22 | REFERENCED | windows-only-apis.md:4
  GAPS: [MED] Rfc2898DeriveBytes/PBKDF2 (password-based key derivation): no text. [MED] X509 PrivateKey casts (RSACryptoServiceProvider)→GetRSAPrivateKey(): no text. [LOW] SHA256Managed/AesManaged factory mapping
  ERRORS: L36/L139 SYSLIB0021/0023 IDs: unverified. L104-107 PasswordHasher<string> with null user: misleading (LOW)
  RULES: SHA256Managed, AesManaged missing from residue_rules.json (LOW-MED)

23 | REFERENCED (SKILL.md:96 only) | topic NOT COVERED (no Swagger text in skill)
  GAPS: [MED] Swashbuckle.Core/Examples→AspNetCore.* (SwaggerConfig, IExamplesProvider<T>, int status codes, jsonConverter removal). [MED] Swagger 2.0→OpenAPI 3 client impact.
  ERRORS: L24-26 package pins (8.0.10, 8.0.2): unverified
  RULES: Swashbuckle, SwaggerConfig, EnableSwagger, IExamplesProvider missing (package_map.json has a Swashbuckle row) [MED]

24 | REFERENCED | build-and-packages.md:22 (one line only)
  GAPS: [MED] NUnit 2→3 renames ([TestFixtureSetUp]→[OneTimeSetUp]) and RhinoMocks→Moq/NSubstitute rewrite (Stub/Return/AssertWasCalled→Setup/Returns/Verify): no text
  ERRORS: L33/L38 NUnit 4.0-4.4 classic-assert claim and 4.5.0 pin: unverified. L106 Moq SponsorLink version history: unverified
  RULES: RhinoMocks, ExpectedException, NUnit missing (LOW)

25 | REFERENCED | webforms-ui.md:4
  GAPS: [LOW] Razor Pages mapping lives only in KB25 (pointer, acceptable)
  ERRORS: none found
  RULES: none

26 | REFERENCED | webforms-ui.md:4
  GAPS: [MED] Blazor Server operations: sticky sessions/WebSocket on the ALB, circuit memory, Data Protection keys. No text in playbooks.
  ERRORS: L53-54 `protected override async Task OnInitializedAsync() => _orders = await …;` likely does not compile (a List assigned in a Task-returning expression body, CS1997/CS0029)
  RULES: sticky rule present

27 | REFERENCED | build-and-packages.md:15
  GAPS: [MED] NU1701/NU1608/NU1605/NU1902 restore/build warnings: no text in playbooks or references (only KB pointer). Needs remove-legacy-first, direct pin, Newtonsoft ≥13.0.1.
  ERRORS: none found
  RULES: build-log only; no catalogue rule (LOW)

28 | REFERENCED | ambient-context-and-remoting.md:4-5
  GAPS: [HIGH] playbook is about 40 lines. Missing: classification tree (A-H), MarshalByRefObject removal, DTO rework (BinaryFormatter→System.Text.Json, [OnDeserialized] silent break, private-field loss), AppDomain→ALC/process, channel→gRPC/named-pipe/StreamJsonRpc templates, [OneWay]→SQS, [Synchronization] silent race, TransactionScope silent non-distribution, exception→gRPC status map, phased interface-first plan, ALB gRPC constraints. [MED] internet-exposed remoting endpoint = security finding (CVE claims unverified).
  ERRORS: L221 and L712 list Uri as an in-box MarshalByRefObject descendant: likely wrong. L141 "only three artifacts survive" vs a table of ~8: contradiction. L674 Upgrade Assistant "officially deprecated" vs KB01 recommending it (skill engines.md:88 agrees with KB28). L459 NamedPipesConnectionFactory is an undefined sample class (LOW). L600 CVE/KEV status and L123 flag: unverified.
  RULES: API-REMOTING, API-APPDOMAIN, BinaryFormatter present. Missing: TcpChannel/IpcChannel/ChannelServices, Activator.GetObject, [OneWay], [Synchronization], ISponsor/ILease, [OnDeserialized]/[OnSerializing] [MED]

CROSS-FILE CONTRADICTIONS: Upgrade Assistant (KB01 vs KB28 and engines.md); library TFM (KB01 netstandard2.0 vs build-and-packages net10.0); log4net/NLog (KB12 vs logging.md); migrations in entrypoint (KB19 vs linux-and-containers.md).

TOP PRIORITY: (1) No Web API 2 / MVC / Swagger guidance (04, 03, 23). (2) EF6 and Dapper/NHibernate specifics missing from skill (07, 16, 17, 18). (3) Remoting playbook too thin (28). (4) Wrong or misleading KB claims that the skill does not correct: [Index] (00, 07, 16), antiforgery cookie (08:252), ExceptionFilterAttribute (02:304), Area convention (03:143), SqlQuery (07:16), MapStaticAssets version (09:122), SA_PASSWORD (19:87).
