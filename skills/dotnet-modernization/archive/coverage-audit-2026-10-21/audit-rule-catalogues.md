> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Audit detectable rule catalogues vs KB and toolkit

agent a434e5cfc45a9746f

READ-ONLY audit complete. No files edited. Scratch probes are in the scratchpad (probe.py, coverage.py, probe_out.txt).

A) Catalogue summary
- residue_rules.json (dotnet-modernization): 44 rules; where code 32, project 4, config 3, sql 3, file 2; levels block 25, warn 17, info 2. residue_scan.py implements every where/when/scope/group value. No unimplemented rule type. Gap: the scanner reads only .cs/.vb, project files, .config and appsettings*.json; markup (.cshtml, .razor, .aspx, .ascx, .master, .asmx, .svc) and wwwroot are never scanned. A documented when="linux" value is not implemented (no rule uses it).
- linux_readiness.json (dotnet-modernization, byte-identical to the modernization-assessment copy): 240 rules, 19 areas, 221 automated, 19 checklist. Check types case_exact, absent, reference_without_hintpath, crlf, file_lacks and last_from_sdk are all implemented, as are context, unless_in_file, unless_in_line, when_path and absent_path. tuned, coverage, already_in, severity_note and kinds are documentation only. All 240 regexes compile and none match the empty string.
- verify.py gates: build (dotnet build plus a net10-only TFM check), tests, residue, linux, container (only when --dockerfile is passed), parity (only with --goldens). Warnings are counted, never gated.
- modernization-assessment rules.json: 186 rules (Blocker 17, High 55, Medium 84, Low 28, Info 2). scan_repo.py reads pat, requires, not, in_strings, parsed, db_only, baseline, question and refs. The 12 parsed rules depend on the optional codebase-documenter sql_parse module. All regexes compile. The db field holds {"pg": rework|redesign }, but its _doc says blocker|limited|ok.
- package_map.json: first-match-wins (fullmatch). One broad "ok/Info" line captures NUnit, Moq, xunit, MSTest.TestAdapter and Portable.BouncyCastle. Microsoft.AspNet.Web.Optimization matches two lines.
- KB coverage: 556 detectable items were extracted from the 28 KB files (sub-agent passes) and each was probed as a literal sample against all catalogue regexes.

B) Missing detectable checks
[HIGH] | KB 02, 25 | Bare "using System.Web;" and root types HttpContextBase, HttpRequestBase, HttpUtility, HttpPostedFileBase: the residue WEB-SYSTEMWEB-NS regex needs a sub-namespace, so these pass the port gate | residue_rules.json
[HIGH] | KB 16 | EF6 in the port residue: "using System.Data.Entity", DbContext base("..."), Database.SetInitializer, Database.SqlQuery, DbEntityEntry, ObjectContext. No residue rule; rules.json DATA-EF6 is Low | residue_rules.json
[HIGH] | KB 20 | WCF server code and config: "using System.ServiceModel", [ServiceContract], [OperationContract], system.serviceModel, basicHttpBinding. Residue has only the .svc filename rule and the ASMX proxy rule | residue_rules.json (server only, so CoreWCF stays allowed)
[HIGH] | residue_scan.py KIND map | Markup is never scanned: "@using System.Web.Mvc" and "@HttpContext.Current" in .cshtml, and "<%@ Import Namespace=System.Web %>" in .aspx | residue_scan.py
[HIGH] | KB 27 | NU1701, NU1605, NU1608 are never parsed. verify.py counts warnings but does not gate them. NuGet.Core, System.Diagnostics.DiagnosticSource, Grpc.Core and Microsoft.AspNet.WebForms have no package_map entry | verify.py, package_map.json
[HIGH] | KB 21 | "using System.Drawing;" and bare Image or Color are missed by residue API-DRAWING and LNX-API-DRAWING (both need System.Drawing.Type) | residue_rules.json, linux_readiness.json
[MED] | KB 23 | Swagger and Web API 2 symbols: EnableSwagger, EnableSwaggerUi, SwaggerConfig, GlobalConfiguration.Configuration, IExamplesProvider (non-generic). Packages Swashbuckle.Core 5.6.0 and Swashbuckle.Examples have no entry; Swashbuckle.AspNetCore.Filters is ok | residue_rules.json, package_map.json
[MED] | KB 24 | Rhino.Mocks API (GenerateMock, Stub, AssertWasCalled) and [ExpectedException]: no rule, no package entry | residue_rules.json, package_map.json
[MED] | KB 12 | System.Diagnostics.Trace / Trace.WriteLine: output is lost in containers, no rule | linux_readiness.json
[MED] | KB 11, 20, 28 | providerName="System.Data.SqlClient" (KB says it is dropped in JSON conversion), system.runtime.remoting and system.serviceModel config sections | residue_rules.json
[MED] | KB 21, 22 | ImageSharp 4.x build-time license key (build fails without it); SkiaSharp SKFilterQuality removed in v4 | package_map.json, linux_readiness.json
[MED] | toolkit README error-code table | CS0234, CS0246, CS0117, CS0103, CS0616, CS0672, CS1069, CS1503, CS1739, CS0305, CS0104, CS0579, CS0618, MSB3825, CA2300-2330, SYSLIB0010-0051, ASPDEPR008, NETSDK1022: no build-log parser exists | verify.py build-log check
[LOW] | KB 00 | [Index], [UIHint], [assembly: PreApplicationStartMethod] | residue_rules.json
[LOW] | KB 22 | RNGCryptoServiceProvider and SHA256Managed (SYSLIB0021/0023); Portable.BouncyCastle rename | residue_rules.json, package_map.json
[LOW] | KB 28 | Activator.GetObject, RemotingServices, RealProxy, InitializeLifetimeService, [OneWay], [Synchronization] without a namespace import | residue_rules.json
[LOW] | KB 19 | Forward-slash drive paths ("C:/...") missed; FILE-DRIVE and LNX-FS-DRIVE-LETTER match backslash only | residue_rules.json, linux_readiness.json

Toolkit backend and prompt (step 3)
- perform-upgrade.sh:255,263 builds with -p:WarningLevel=0, so the toolkit's own verification hides NU and CA warnings.
- TFM mapping: 6, 7, 8, 10 map correctly; any other value (e.g. 9) silently becomes net8.0. The prompt and KB 00 expect no Dockerfile output; the container gate only runs an existing Dockerfile.
- backend/src/transform.ts has no .NET-specific detection; it only routes images (DOTNET vs DOTNET_Q).
- The prompt tells the agent to convert WCF to REST or gRPC; KB 20 says CoreWCF.

C) Contradictions
- EntityFramework: package_map ok/Low vs rules DATA-EF6 Low vs KB 06/08/16 (remove, blocking).
- System.Data.SqlClient: package_map replace/Low and rules DATA-SYSTEM-SQLCLIENT Low vs residue DB-SYSTEM-SQLCLIENT block (KB 06/18: blocking).
- System.Drawing: residue API-DRAWING warn vs LNX-API-DRAWING block vs rules WIN-DRAWING High vs package_map System.Drawing.Common windows-only High.
- Time zones: residue TZ-WINDOWS-ID warn ("works on .NET 6+") vs LNX-TZ-WINDOWS-ID block; residue TZ-LOCAL info vs LNX-TZ-LOCAL-NOW warn.
- Event log: residue API-EVENTLOG block and LNX-API-EVENTLOG block vs rules WIN-EVENTLOG Medium.
- Distributed TX: rules DATA-DISTRIBUTED-TX Medium vs LNX-DATA-MSDTC block.
- Machine name: residue HOST-MACHINE-NAME info vs LNX-ENV-MACHINE-NAME warn.
- Bundling: KB 09 (blocking) vs LNX-WEB-BUNDLING warn, rules FE-BUNDLING Low, package_map Microsoft.AspNet.Web.Optimization Low.
- Blocked packages: package_map Microsoft.AspNet.Mvc, WebApi, WebPages, Razor (replace/Info), Microsoft.Web.Infrastructure (remove/Info), Antlr and WebGrease (remove/Info), Autofac.Mvc5 and Autofac.WebApi2 (replace/Low), VS QualityTools (replace/Low) vs KB 27 (blocked, blocking).
- Test packages: package_map ok/Info for NUnit, Moq, xunit, MSTest.TestAdapter vs KB 24 (NUnit 2.6.4 and MSTest v1 adapter blocking).
- Swashbuckle.AspNetCore.Filters: ok/Info vs KB 27 (blocked without a net10 release).
- Portable.BouncyCastle: ok/Info vs KB 22 (deprecated, rename).
- WCF: rules WCF-SERVICE High, no residue rule, vs KB 20 (blocking).
- verify.py build gate requires net10.0 only, so a net8.0 port fails. KB 00 says ".NET 8 or .NET 10" and the toolkit maps 8 to net8.0.
- Copies: linux_readiness.json and linux_readiness.py are identical in both skills (drift risk). The four KB files that differ (07, 11, 17, 19) differ only in sample password text, not content.

D) Broken or empty patterns
- No invalid or empty-matching regex in residue_rules.json, linux_readiness.json or rules.json.
- LNX-CTR-DOCKERIGNORE and LNX-CI-GITATTRIBUTES have patterns: []. They are absent-type checks driven by when_path and absent_path, so they work, but the schema is inconsistent.
- LNX-FS-CRLF-SCRIPTS glob "entrypoint*": unreachable, because is_text() requires a file extension, so extensionless entrypoint scripts are skipped.
- verify.py: with no --dockerfile, the container gate is absent from the report (no "not run" row).
