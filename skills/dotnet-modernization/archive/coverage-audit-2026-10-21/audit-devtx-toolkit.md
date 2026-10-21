> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Audit DevTx toolkit coverage

agent a7ed4131791acd33b

READ-ONLY coverage audit. Nothing was edited, created or deleted in either repo or the skills. Scratch extracts are in the scratchpad only. Three parallel agents read the files; I spot-checked the four highest-impact claims in the repos.

Roots: TK = <toolkit> (note the double nesting). SK = skills/dotnet-modernization. MA = ...\skills\modernization-assessment.

Correction to the premise: the KB has 29 numbered files (00 to 28), not 28. The skill README and SKILL.md say 28. The skill's reference/kb copy is byte-identical to TK\transformer\common\migration-knowledge\dotnet\ except 07, 11, 17 and 19, which the skill has redacted (sample passwords only). The zip holds the same 30 entries and adds nothing. The skill copy also has LICENSE-Apache-2.0.txt.

1) KB files not covered
- Not cited anywhere (index link only): 03 MVC, 04 Web API 2, 23 Swagger/Swashbuckle.
- Topic only, no file cite: 09 bundling (only webforms-ui.md:41), 15 views/static files.
- Cited but thin: 24 test stack (one line in build-and-packages.md:22), 28 remoting (playbook about 40 lines against a 50 KB KB file), 07 EF6 to EF Core (one table row), 18 NHibernate (table cell).

2) Gaps (tag | topic | source | skill file to hold it)
HIGH
- Client remote write. Skill says "never push to a client remote" (SK workflow.md:19, SKILL.md:35). DevTx pushes <branch>-itr-N and opens PRs (TK backend/src/job_complete.ts:243-294). Verified. Skill should require a sandbox remote. engines.md, workflow.md.
- Data egress. Kiro may process data outside the Region; the Bedrock summary runs in us-east-1 (TK docs plan-deployment/security.mdx; transformer/common/upgrade-report-generator/report-generator.ts). engines.md, SKILL.md principles.
- Unsupported DevTx types: WinForms, WPF, WF (TK docs introduction/supported-transformation-types.mdx). engines.md "Choosing".
- Solution selection. Docs say a blank field uses the first .sln; the code scans the tree and upgrades every csproj/vbproj (dotnet-q and upgrade-assistant perform-upgrade.sh). engines.md, verify.py.
- MA rules conflict with KB 27 and KB 06 on blocking status: Microsoft.AspNet.Mvc/WebApi/Razor marked Info/replace; EF6 Low; System.Data.SqlClient Low; WCF High with no residue rule. MA data/package_map.json, rules.json.
- Residue scanner never reads markup (.cshtml, .razor, .aspx, .ascx, .master, .asmx, .svc) or wwwroot (dotnet-modernization scripts/residue_scan.py). Residue catalogue scripts/data/residue_rules.json.
- Residue misses: bare "using System.Web" and HttpContextBase/HttpUtility (KB 02, 25); EF6 System.Data.Entity (KB 16); WCF server attributes and system.serviceModel config (KB 20); bare System.Drawing (KB 21). residue_rules.json.
- Depth gaps: 04 Web API 2 (none), 03 MVC (none), 23 Swagger (none), 28 remoting (thin), 16 EF6 baseline, 17 Dapper and Encrypt defaults, 22 PBKDF2/RSA CSP. Target playbooks: webforms-ui, startup-and-middleware, a new web-api playbook, raw-sql-and-data-access, windows-only-apis, ambient-context-and-remoting.
- Uncorrected KB sample errors that would mislead a port: 16:151 ([Index] called unsupported in EF Core; it is supported). 07 Database.SqlQuery mapping (needs SqlQueryRaw). 02:304 abstract ExceptionFilterAttribute. 03:143 AreaRegistration discovery. 10:10 IStartupFilter for filters. 06:14 "dotnet migrate packages.config" is not a CLI command. 28:221/712 Uri as MarshalByRefObject. 19:87 SA_PASSWORD "Pass123" fails complexity. 26:53 async expression-bodied assignment. 01:221 treats Upgrade Assistant as current (it is deprecated per 28:674 and engines.md). Target: the relevant playbook, or a "KB errata" section in SKILL.md.
MED
- Build flag. Both engines build and test with -p:WarningLevel=0 (TK transformer/dotnet-q/perform-upgrade.sh:255-297, dotnet-upgrade-assistant:198), so NU and CA warnings are hidden. Verified. verification.md, verify.py.
- No-test gate. A repo with no test project exits 0, which counts as pass. verification.md says "not run" never passes. verification.md.
- Initial build. engines.md says it is skipped for .NET Framework. True only for DOTNET_Q (dotnet-q L459-461). The upgrade-assistant engine runs it unconditionally (L372-399) and stops on failure. Read from code, not run. engines.md step 3.
- Container claim. engines.md says DevTx yields a Linux container. The toolkit prompt and gates are build and test only; no Dockerfile is generated. engines.md table.
- TFM. verify.py build gate is net10-only, so a net8 port fails; KB 00 says 8 or 10. The toolkit maps 6/7/8/10 and silently maps any other value to net8. verify.py, engines.md.
- Autonomy. The Q system prompt says never ask, pick the safest option, and record it in summary.md. The skill says decisions stop for the user. Skill should say DevTx decisions appear only in summary.md and the diff. engines.md, SKILL.md.
- Supported sources. Docs list .NET Core 1.0-3.1 and 5-7 as DevTx sources; skill says already-on-.NET-5+ gets a manual TFM upgrade. workflow.md.
- Prerequisites and deployment (Node 22, Yarn 4, CDK >= 2.190, bootstrap, EIPs, Cognito, Kiro licence and Region). TK docs deployment/prerequisites.mdx, setup.mdx, plan-deployment/quotas.mdx. engines.md, install_prerequisites.py.
- Iteration artifacts (iteration-N/code-upgrade.log, kiro-output.log, summary.md, report.json, initial-build.log, post-upgrade-verification.log). TK dotnet-q perform-upgrade.sh L870-884. engines.md, report.py.
- Confidence score (40% verification, 30% size, 20% files, 10% deps) scores a skipped build and a no-test run as success. TK transformer/common/upgrade-report-generator/confidence-calculator.ts. verification.md: not evidence.
- Private NuGet feeds: nuget.config is commented out of the DevTx image. TK transformer/dotnet-q/Dockerfile. engines.md.
- Remaining residue/rules gaps: Swashbuckle and Rhino.Mocks symbols (KB 23, 24); Trace output lost in containers (KB 12); ImageSharp 4 licence key and SkiaSharp API (KB 21, 22); CS/MSB/CA/NU build codes from the toolkit README table have no log parser; NU1701/1605/1608 not gated.
- Catalogue conflicts for one fix: time zones (TZ-WINDOWS-ID warn vs LNX block), EventLog (block vs Medium), MSDTC (Medium vs block), bundling (block in KB 09, warn in LNX), System.Drawing (warn vs block vs High). Reconcile severities in residue_rules.json, linux_readiness.json and rules.json.
- Kiro credential fail-fast and .sqlite3 upload (TK transformer/common/run.sh; docs manage-system-admin.mdx). engines.md.
LOW
- Cost (Kiro about $177/month vs AWS Transform about $308), throughput, comparator scope (PackageReference only, first TFM), pins (claude-sonnet-4.6; upgrade-assistant 1.0.518 vs unpinned install), WCF (toolkit prompt says REST or gRPC; KB 20 says CoreWCF), commented-out code hygiene (transform-code.mdx), source-control auto-tracking polling (gitwatcher.ts), and duplicate copies of linux_readiness.json and .py in both skills (drift risk).
- Toolkit hygiene: the toolkit KB copy still holds sample passwords (07, 11, 17, 19); the skill copy has them redacted.

3) Contradictions with the toolkit
- Remote push (see HIGH). Solution default (see HIGH). Initial build (see MED).
- Library targets: skill says multi-target libraries; DevTx forces targetVersion on all projects, and the netstandard2.0 helper in common.sh has no callers. verify.py accepts netstandard2.x, which DevTx never produces.
- Parity: verification.md says parity catches XML declaration and encoding; parity.py compares status and parsed body only.
- Migrate-off-log4net: KB 12 says migrate; logging.md says the logger can stay. KB 01 says libraries are netstandard2.0; build-and-packages.md says net10.0.

Covered (not listed): most toolkit workflow steps, validation loop, build-fix loop, residue and linux-readiness rule types (all implemented; 240 Linux rules and 44 residue rules compile with no empty matches), and the KB topics whose cites are present.
