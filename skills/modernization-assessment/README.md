# modernization-assessment

A Claude Code skill that turns a client's legacy .NET code base (one repository or hundreds) into an evidence-backed **AWS Modernization Assessment Report**. It works out, from the code alone, what will break on AWS/Linux and .NET 10, how each application should move (7 Rs, including hybrid .NET Standard 2.0 paths), and how much effort it takes.

It builds on the **codebase-documenter** skill: the same structure, the same graphify integration, and its prerequisite installer. It can also call the documenter to fully document a high-risk application.

## Install

```bash
python install.py
```

```bash
python install.py --project /path/to/workspace
```

- The first command installs for all projects.
- The second installs for one workspace only.
- Either way, it installs this skill and the sibling `codebase-documenter` (when shipped together), then installs graphify and MkDocs at user level.
- Requires Python 3.10+.

## Use

Open Claude Code in an empty folder outside the client's repositories, then say:

- *"Assess the .NET code in D:\clients\acme\repos for AWS migration"*, or
- `/modernization-assessment assess-estate`.

Individual steps:
- `discover-estate`, `map-code-graph`, `scan-repos`;
- `review-findings`, `classify-applications`, `estimate-effort` (lift-and-shift: the hours calculator), `build-check` (lift-and-shift);
- `validate-linux-build`, `write-report`, `verify-report`;
- `calibrate-report`, `resume`.

The deterministic part runs from the command line too:

```bash
python scripts/setup_assessment.py --client "Acme" --roots D:/clients/acme/repos
python scripts/discover_estate.py
python scripts/map_graphs.py --all --exports
python scripts/scan_repo.py --all            # online package lookup is the default; --offline to keep package ids local
python scripts/classify_apps.py
python scripts/estimate_effort.py
python scripts/build_report.py
python scripts/build_html_report.py
python scripts/verify_report.py
```

Between `scan` and `build`, the assessor (Claude, or you) does the judgment work:
- reviews uncertain findings (`review_queue.py`, then `assessment/reviews/*.json`);
- confirms 7R decisions (`assessment/decisions.json`);
- writes the narratives (`assessment/narrative/*.md`).

`verify_report.py` refuses to pass until that work is done.

## Scenarios

The estimate covers what the client actually wants and compares the alternatives side by side. The intake questionnaire (`scripts/intake.py`, see [references/intake.md](references/intake.md)) asks the client's goal and sets the scenario; `setup_assessment.py --target-hosting ... --target-database ...` still works for older workspaces.

With access to only part of the estate, `extrapolate_estate.py` estimates the repositories that were not shared from the assessed ones of the same kind.

| Hosting (code side) | Meaning |
| --- | --- |
| `modernize` | Convert .NET Windows applications to .NET 10 on Linux, per-application 7R decisions |
| `lift-and-shift` | Move every server as it is to EC2 with the same operating system (Windows to Windows, Linux to Linux). No code port; costs the AWS landing work (IP allow-lists, DNS, SMTP port 25, file shares, identity, licences, broadcast/multicast) plus connectivity, configuration, integration and security findings. Uses its own report template |
| `windows-rehost` | Lift-and-shift Windows applications from on-premises to Windows EC2: no code port, only network, identity and configuration changes |

| Database (code side) | Meaning |
| --- | --- |
| `dual` | The app supports SQL Server and PostgreSQL. Adds provider abstraction and keeps every procedure for both engines |
| `postgresql` | PostgreSQL only: every table, view, procedure, function and trigger plus the data-access code. Uses the database inventory (sizes, T-SQL constructs, stored-procedure call sites, EF function imports) |
| `none` | SQL Server stays; no database code change |

**Lift-and-shift effort is different:** when the intake goal is lift-and-shift, `estimate_effort.py` runs the **hours calculator** (`solutions.py`, `third_party.py`, `estimate_hours.py`): developer working hours, AI-assisted, 8 h per day, a low-high range per unit counted solution by solution, plus a 20% buffer, with every line labelled calibrated to the sample or inferred (see "Hours calculator for lift-and-shift" below). The modernize path keeps the model described next.

Effort (modernize path) is **coding hours only** (no QA, DevOps, project management or contingency), with person-days, AI-assisted and the manual equivalent alongside. Hours are driven by lines of code, project type and a complexity factor (decision density, fan-in, large files); see [estimation-model.md](references/estimation-model.md). The factors are configurable in `scripts/data/estimation.json`. Optional modernizations (SMTP to SES/SNS, Kafka to SQS/SNS, files to S3 and more) are listed with their own hours and are never added to the total.

## What it produces

Start a new session at `assessment/reference/README.md` (the context pack, `reference.py`): where everything is, notes from earlier sessions, logs and inputs.


All in `assessment/report/`:
- **`<Client>-AWS-Modernization-Assessment.html`** — the version for PMs, BAs and the client. It is one self-contained page that combines the report and every export:
  - sidebar navigation and global search;
  - a key-facts ledger and severity charts (rows with no findings are listed once instead of drawn empty);
  - findings explorer (filter by severity, category or application; click for evidence and fix);
  - sortable application, package, dependency, project and question tables with Download CSV;
  - Gantt timeline, glossary for non-technical readers, dark mode and print/PDF.
- **`<Client>-AWS-Modernization-Assessment.md`**, with 11 sections:
  1. Executive summary
  2. Scope and method
  3. Application inventory
  4. Architecture and dependencies (Mermaid map, graphify insights, network allow-list with server roles such as SMTP, SFTP, file shares and report servers, scheduled and background jobs, project interdependencies, workflow dependencies, database object dependencies)
  5. Findings by category (27 categories, each with evidence or "checked, none found")
  6. Database assessment (dual / PostgreSQL code conversion)
  7. Per-application plans (with the hybrid table)
  8. Effort (P10–P90 Monte Carlo range, P50 likely, P80 commitment), phased timeline, a coding sprint plan from the day of codebase access, and a plain-language explanation of how the estimate was calculated (formulas with the run's numbers)
  9. Risks and open questions
  10. Testing, QA and merge strategy
  11. Appendices: packages, projects, every Windows-API occurrence, raw outputs, sources
- **Exports:** `findings.csv/json`, `applications.csv`, `packages.csv`, `open-questions.csv` (with an empty answer column), `endpoints.csv`, `network-allowlist.csv` (outbound destinations with ports and roles, and inbound listeners, for the AWS VPC allow-lists) and `scheduled-jobs.csv` (every scheduled or background job with its schedule and AWS equivalent).

## Structure

```
modernization-assessment/
├── SKILL.md                 workflow, principles, command table
├── README.md, install.py
├── references/              checklist (section 5 extended), windows-api-catalog (generated), package-map (generated),
│                            seven-rs, target-platforms, database-assessment, tools-landscape, linux-pitfalls,
│                            estimation-model, review-findings, scale-and-subagents, write-report, report-template,
│                            style-guide, calibration, setup, sources
├── scripts/                 setup_assessment, discover_estate, map_graphs, scan_repo, review_queue, classify_apps,
│   │                        estimate_effort, validate_linux_build, build_report, verify_report, context, reference,
│   │                        render_references, _common, _findings,
│   │                        solutions, third_party, estimate_hours, build_check, _hours_report (lift-and-shift hours calculator)
│   └── data/                rules.json (209 evidence rules), auth.json (sign-in mechanisms and AWS options), package_map.json, categories.json, estimation.json,
│                            decision_rules.json, hours.json, commercial_packages.json   <- calibration lives here, not in code
├── calibration/             drop sample reports in samples/ (never packaged); gap-analysis template
├── templates/narrative/     stubs for the seven narratives
└── samples/eshop/           end-to-end sample on Microsoft's public eShopModernizing repo: report, exports, reviews, decisions, narratives
```

## Calibration

Drop your sample reports into `calibration/samples/` and ask for `calibrate-report`. `extract_sample.py` outlines each sample (DOCX, PPTX, XLSX, MD or HTML; PDFs are read directly), and `calibration/gap-analysis.md` records what to adopt. Samples are never packaged.

The report wording and structure live in `references/report-template.md` and `references/style-guide.md`. Effort numbers live in `scripts/data/estimation.json`, and 7R thresholds in `scripts/data/decision_rules.json`. Your sample reports and actuals are applied there; see `references/calibration.md`.

## Confidentiality

The skill never writes into client repositories, never copies secret values (the masking is verified by a gate), and sends package IDs (and versions) to api.nuget.org unless the scan runs `--offline` or `online_package_lookup` is false; private package IDs are sent too (they are simply not found), so use `--offline` for confidential estates. Reports contain architecture and security findings: share them privately.

## Server dependencies, scope and the inventory workbook (2.12.0)

- `map_infra.py --all [--servers <client server list>]` reports, per repository, the kinds of server the code depends on (SQL Server, Redis, Memcached, Aerospike, AppFabric, NCache, Elasticsearch, Solr, Kafka, RabbitMQ, SMTP, POP3/IMAP, SFTP/FTP, LDAP, file shares, proxies, document and graph stores ...), the hosts named in code, the servers of the client's own infrastructure list that match, and the Windows/Linux hosting evidence. The single view is `assessment/infra/estate-infra.json` and `report/infra-dependencies.csv`.
- The same run writes the **configuration map** (each config file and setting holding a URL, IP, host, UNC share or drive path, with the line, environment and action for AWS; secrets skipped) and the **network access** list (what each project connects to, port, protocol, and what must be opened, routed, resolved or allow-listed on AWS). `.xml .ini .properties .conf .env .settings .toml` files are scanned as data.
- The assessment is .NET only: repositories with no .NET project are out of scope; non-.NET projects inside a .NET repository are listed, never edited or moved, and flagged when the .NET build or run time needs them (Node.js, gulp, Vite, TypeScript).
- `update_inventory_xlsx.py --xlsx <repository inventory>` writes scope, coupling, server dependencies, server coverage, hosting evidence and what the inventory missed back into the client's workbook.
- Detail and limits: [references/infra-dependencies.md](references/infra-dependencies.md).

## Hours calculator for lift-and-shift (2.13.0)

Changelog: **2.13.0** adopts the effort calculator of the sibling skill `lift-and-shift-assessment` for the lift-and-shift track and keeps the modernize path unchanged.

- **What changes for a lift-and-shift assessment.** `estimate_effort.py` routes the track (intake goal lift-and-shift) to `estimate_hours.py` and merges the result into `estimate.json` (`basis: "hours"`). The report, the HTML effort tab and `landing_report.py` show the total range, the split by work item, the split by solution, every line, and how much is calibrated to the manager's sample versus inferred. The engineer-days model is kept only in the scenario comparison. `--model days` or `--model hours` forces one model.
- **New scripts.** `solutions.py` (solution-wise inventory), `third_party.py` (licensed components, integrations, server-to-server), `estimate_hours.py` (+ `data/hours.json`), `build_check.py` (static build readiness, optional real MSBuild of a copy with `--run --approve-downloads`), `_hours_report.py` (report text). Data: `data/hours.json`, `data/commercial_packages.json`.
- **New intake questions** (lift-and-shift only): `scope_confirm`, `scope_exclusions`, `work_items`, `retarget_to`, `regression_tests`, `estimate_basis`, `environments`, `environments_differ`, `pipeline_scope`, `pipeline_solutions`; `intake.py --solution ID --environments "..."` and `--confirm-environments`. Nothing is assumed: unknown answers stay UNKNOWN and become open questions.
- **Findings.** Three landing rules added to `rules.json`: `LS-CERT-THUMBPRINT`, `LS-LOCAL-DB-FILE`, `LS-ODBC-DSN` (already mapped in `data/landing.json`). The generated `references/windows-api-catalog.md` was re-rendered.
- **Fixes found while wiring.** `_config.py` gained `detect_company_domains` / `ensure_company_domains`, which `config_template.py` already called; `map_infra.py` runs it for the lift-and-shift track so company DNS names are classified.
- **Gate 9** of `verify_report.py` (lift-and-shift track): `estimate.json` equals `estimate_hours.json`, the total is the sum of the lines plus the buffer, and the report states the same total.
- Details: [references/lift-and-shift.md](references/lift-and-shift.md#the-hours-calculator), [references/estimation-model.md](references/estimation-model.md#hours-calculator-lift-and-shift-track), [references/intake.md](references/intake.md).

## AWS managed services for server-hosted services (2.14.0)

`scripts/aws_native.py` finds the caches, search, mail, file-transfer, queue, MongoDB and hosted-logging services the code uses, tells whether the wrapper lives in the repository or in a shared library, and prices each AWS target option (config, client swap, rewrite, remove) from the wrapper files, call sites and settings. `estimate_effort.py` adds one row per service to the optional modernizations (in the total when intake `aws_native = now`). Details: [references/aws-native-services.md](references/aws-native-services.md). The tools landscape now describes the AWS DevTx Version Upgrade Toolkit.

### Assessment + plan: the hand-off to execution (2.14.0)

The skill now ends with a plan the **dotnet-modernization** skill executes. It assesses and plans; it does not change code.

- **`plan_execution.py`** writes `assessment/report/execution-plan.md` (+ .html, .json): **one** porting engine per project (`--port-engine devtx|aws-transform|claude`, default DevTx; never two engines on one project), Claude's clean-up grouped by playbook, **one** database tool (`--db-tool db-agent|claude`: the DB porting agent, or Claude with the DB porting skills), AWS managed-service swaps. Work is shown as a few streams per package (prepare, engine, Linux, Claude, database, AWS native, outside), shared class libraries first and simplest first; repeated findings are collapsed with counts; data access shows raw SQL, procedure calls, result-set and multi-result procedures.
- **Already-modern applications** (.NET 5+) get the Linux readiness check only, no engine run.
- **Linux readiness** (`linux_readiness.py`, step 3.2): 337 checks in 19 areas, including letter case of file references checked against the files on disk, container-image checks (no `USER`, SDK in the final stage, no `.dockerignore`, ICU/tzdata), CRLF scripts and secrets in config (masked). The report's Linux readiness table gains a "Linux checks (block / warn)" column, and a modern app with an open blocking hit is no longer "Linux-ready". Same script and rules as the dotnet-modernization skill. Details: [references/linux-readiness.md](references/linux-readiness.md).
- **7 Rs with justification:** every application carries why not the other Rs, what happens next ("Retire, then what?"), risks and who signs off (`data/decision_rules.json` `r7_guidance`), in the Markdown and HTML reports. A Web Forms project with a token UI (3 pages or fewer, markup under 5% of the code) is Replatform, not Refactor. [references/seven-rs.md](references/seven-rs.md) has the decision tree.
- **Challenges** ([references/modernisation-challenges.md](references/modernisation-challenges.md)): tightly coupled Web Forms page by page, System.Web.HttpContext across shared libraries (pass the values, System.Web adapters, `IHttpContextAccessor`), libraries first, WCF/ASMX wire compatibility, WPF/WinForms, MongoDB/DocumentDB, features with no counterpart, what each engine covers.

## Renamed to modernization-assessment (3.0.0)

The skill was called **migration-assessment** up to 2.14.0. The terms are now kept apart: **migration** is moving workloads to AWS as they are (lift-and-shift, the `lift-and-shift-assessment` skill and this skill's lift-and-shift track); **modernization** is moving them to .NET 10, Linux containers and AWS managed services, which is what this skill assesses and plans. The report is now the **AWS Modernization Assessment** (`<Client>-AWS-Modernization-Assessment.md` / `.html`; the lift-and-shift track keeps `<Client>-AWS-Migration-Assessment`). Nothing else changed: same commands, scripts, rules and workspace layout. The installer's `update` replaces an installed `migration-assessment` with this skill.

## Changed in 3.1.0

- Linux readiness: 337 checks (was 240), the same files as dotnet-modernization and the standalone linux-readiness skill, with a self-test (now the linux-readiness skill's `selftest.py`).
- .NET 8 and 9: a target turns from "ending soon" to "out of support" on its end-of-support date (10 November 2026), and the 7R rationale names the date. The duplicate rule BUILD-TFM-NET8-NET9 is gone (INV-TFM-SUPPORT covers it). Rules: 196 (was 186).
- New AWS-native and infrastructure detections with targets and hours: AppFabric and NCache (ElastiCache), Solr (OpenSearch), inbound mail (SES receiving), Cassandra (Keyspaces), RavenDB and Couchbase (DocumentDB or EC2), Neo4j (Neptune); AppConfig feature flags as an optional modernization; MassTransit on SQS as a service SDK.
- Sources S26-S38 (AWS Transform limits, pricing and data handling, Babelfish, Lambda dates and more).

## Changed in 3.3.2

- **The same fixes reach the sibling skills.** lift-and-shift-assessment, codebase-documenter and dotnet-modernization get the code-credential masking, the minified-bundle and short-host filters and the secret false-positive pattern where they have their own copy.
- **No minified bundles or one-letter hosts in the endpoint map (`network_endpoints.py`).** Also in lift-and-shift-assessment and codebase-documenter.
- **`verify_doc.py`** fails when a credential written in code reaches the .docx or the workbook unmasked.
- **`selftest.py` section 5** fails when a script shared with a sibling skill drifts, or when a sibling's own `mask()` misses a credential in code. The shared-copies list in SKILL.md is corrected: `_scope` is shared; `build_open_questions` and `verify_doc` differ only in the estimate file name.

## Changed in 3.3.1

Fixes from five field runs (a static content repository, a Bot Framework v3 app, two class-library repositories and a SQL scripts repository). `scripts/selftest.py` now rebuilds each case and fails if it comes back.
- **Static content.** A web project with no C# is Replatform to Amazon S3 + CloudFront, priced as publishing only (item B13, 1.5-4 h); nothing is ported and no database stage is added. Its Web Forms UI findings drop to Low.
- **Framework rewrites.** Bot Builder / Connector v3 is a rewrite package (`rewrite`, `only_below` in the package map): the application is drafted as Refactor, not Replatform.
- **Libraries outside the repository.** `..\` project references and HintPaths outside the repository become a High `DEP-OUTSIDE-REPO` finding, lower the confidence, and are listed under "Not in this estimate".
- **No-.NET estates.** A repository with only SQL scripts is out of scope, but `sql_estate.py` inventories its objects and the server features it uses (xp_cmdshell, linked servers, SQL Agent ...), and T-SQL in `.txt`/`.prc` files is read. An estate with no .NET gets a report, summary and tracker that say so; `verify_report.py`, `raw_sql.py`, `build_tracker.py`, `atf_scan.py` and `context.py` handle it.
- **Manual findings count.** Each `.manual.json` finding gets a stable id (`<repo>:<rule>`), takes a verdict by that id or its rule id, and is priced in the phased estimate (items M1 ...).
- **The claude port engine** is accepted by `estimate_phases.py` (it was silently replaced); a line whose quantities are all 0 is left out; the database stage needs data-access code.
- **Fewer false findings.** Minified bundles are not scanned; hosts shorter than 3 characters are ignored; CFG-HARDCODED-SECRET skips DOM ids and key names; AppFabric only in config is Low; ClientServices membership providers are not AUTH-FORMS-MEMBERSHIP; settings repeated in Web.config transforms count once.
- **Secrets.** Credentials written in code (`GetBytes("user:pass")`, `"Basic <base64>"`, `NetworkCredential`, `AuthenticationHeaderValue`) are masked everywhere, including `assessment/linux/`, and `verify_report.py` fails if one leaks.
- **Client-neutral defaults.** Client-specific server name patterns move to the workspace's `assessment.json` (`server_roles_extra`); the company-domain guess reads only the folders nearest the repositories, not the workstation path.
- **Branch check without GitLab** falls back to the local clone's history. `linux_readiness.py` accepts a repository name. `decisions.json` list fields accept a single string. `open_questions_extra` in `assessment.json` adds hand-written open questions.

## Changed in 3.3.0

- **A report a .NET developer can act on.** The HTML screens are regrouped: Start here (Overview with "What to do first", Migration order), Projects (Projects & 7R, Dependencies, Code graph), What to change (Work items, Sign-in & access, Packages, Linux, .NET modernization, integrations, data, hosting, delivery), Plan, Reference. The scans and the data are unchanged; only the display is.
- **Migration order by blast radius (`_projects.py`).** Every project, class libraries and tests included, gets a wave, a place in the order, what to port first, what uses it and a blast radius. The pilot is picked from it. Cross-repository DLLs count as dependencies. Markdown 1.3 and 4.13; HTML Migration order and Dependencies (project map by wave, filter by repository); `report/projects.json`; tracker sheet Projects; summary section.
- **7R and difficulty per project.** Class and shared libraries get their own 7R ([seven-rs.md](references/seven-rs.md#every-project-class-libraries-tests-and-difficulty)). Difficulty: APIs, class libraries, console and worker projects are Easy; Web Forms and desktop UIs Hard. Markdown 3.4; HTML Projects & 7R.
- **Authentication and authorization.** 13 new rules (custom login, credentials checked in the database, reversible passwords, fixed header secrets, API keys, IP checks, roles in config or code, JWT, OWIN OAuth, Basic auth, custom authorization code, ASP.NET Core auth). `_auth.py` says per application who signs in (people, other systems, Windows users) and recommends the ASP.NET Core and AWS replacement (Cognito, API Gateway, IAM Identity Center, Secrets Manager ...) with developer steps and client questions. Markdown 7.4; HTML Sign-in & access; `report/auth.json`; tracker and summary.
- **Packages on their own screen.** One action per package: upgrade for a security advisory, replace, remove, upgrade, get the source, check the licence, verify, keep. Markdown 7.5.
- **Work items.** Findings grouped by project in migration order, each with what to do, why and where.
- **Full graphify output by default.** `map_graphs.py` writes graph.html, the code tree, the wiki (also as HTML pages), call flows and GraphML (`--no-exports` skips them), then the **explorer** (`graph_ui.py`): blast radius, depends on, path, hubs, with text matches for the static calls graphify misses. `graph_ui.py --serve` adds graphify questions from the browser (local only). The report's Code graph screen and the reference pack link them.
- **Fixed: Web Forms false Blocker.** `WEB-WEBFORMS-UI` now needs System.Web, a page directive or ASP.NET markup in the same file; a class named `Page<T>` in a plain library no longer matches.
- **Fixed: false internal hosts.** A UNC path must start a value: `\u017F` in a regex range, `C:\temp` and sample paths in scripts are no longer read as servers (`network_endpoints.py`, also in lift-and-shift-assessment and codebase-documenter).
- **Header secrets masked.** `Headers["X"] == "value"` shows `***` in evidence (also in lift-and-shift-assessment).

## Changed in 3.2.6

- **Context pack (`reference.py`, step 8.16).** `assessment/reference/README.md` and `.html` are the place to start in a new session. They cover:
  - scope and assessment type;
  - each repository copy with its branch and commit;
  - the headline estimate and 7 Rs;
  - every deliverable, and every `assessment/` folder with what it holds;
  - the code graph and the exact `graphify query` command;
  - what lives outside `assessment/` and why: repository copies, build copies in the short-path folder, the AWS Transform scanner, and the shared tool caches;
  - tool versions.
- **Notes from chat (`reference.py --note`).** `notes/` keeps answers given in chat as dated Markdown and HTML, so they outlive the session transcript.
- **Logs and inputs copied.** `logs/` holds the run issues log and the workspace-root logs. `inputs/` holds `assessment.json` and the scanner settings, with secret values masked.
- **Pointers in context.py and checks in verify_report.py.** `context.py` prints where the pack is and when it is stale. `verify_report.py` checks every file in `reference/` for secret values.
- **No temp leftovers (`_docx_brand.py`).** The Word helper scripts in the temp folder and the `.toc-check.pdf` are removed even when Word fails or times out. The same fix is in lift-and-shift-assessment 1.1.2.

## Changed in 3.2.5

One sweep of the whole report for contradictions; every fix below ships together.

- **Timeline and sprint plan had no application work (`estimate_effort.py`).** A loop variable overwrote each work package's kind, so the applications dropped out of section 8.4 and the sprint plan (only the database lane was planned).
- **AWS managed-service swaps counted once and consistently.** Only the chosen server swaps go into the parametric total and the sprints (not every optional idea); both models read the same choices (`estimate-inputs.json` overrides assessment.json); the execution plan's swap stream has their hours; section 7.3 separates "swaps (in the estimate)" from "optional modernizations (not in it)".
- **One planning figure everywhere.** At a glance leads with the phased estimate (the figure in the summary and 8.1), then the parametric cross-check and the engineer-paced comparison; report, summary and at a glance use the same day length and team size. Narratives can use `{{v:phased.low}}`, `{{v:phased.high}}`, `{{v:phased.scenarios[<name>].low}}`, `{{v:phased.phases.P4.high}}` and more, so their numbers no longer go stale.
- **Key risks:** one row per issue (refs joined, projects named) instead of the same finding twice.
- **Section 4.9 in a modernization:** "On AWS in this plan" (the chosen AWS option, the database scenario) instead of lift-and-shift text; a store aws_native traced through its wrapper is "confirmed", not "use not traced".
- **Endpoints:** a database host is one row (not an endpoint row plus "host / -"); bare IPs in redis.config / memcached.config are named Redis / Memcached.
- **Packages:** a package whose nuget.org version list declares no frameworks falls back to its own frameworks, so a .NET Framework-only package is "replace", not "keep".
- **aws_native:** a method counts as a store's wrapper only when the client call is inside its body.
- **ATF RadNet page:** the cross-check shows each difference.
- **Titles:** "Landing on AWS (network, hosting and co-located services)"; 7.3 "AWS managed-service swaps and optional modernizations".
- Same `network_endpoints.py` / `_config.py` fixes ported to lift-and-shift-assessment 1.1.1 and codebase-documenter 1.16.1.

## Changed in 3.2.4

- **Readable AWS Transform scanner pages (`atf_report.py`).** `atf/radnet-report.html` (projects with decoded project types, executable lines by file type and largest files, NuGet packages joined with the package check, local DLLs joined with the DLL check, framework assemblies marked when missing or Windows-only on .NET 10, COM / P/Invoke / EDMX, cross-check) and `atf/rasql-report.html` (database code per file, stored procedures called, inline SQL and execute calls with the cross-check reason, parameters per file, transactions). Filterable, sortable, light and dark, masked snippets. `atf_scan.py` writes them on every run.
- **Fixed: two regexes held a literal backspace instead of `\b` (word boundary).** `atf_scan.py` never recognised C# LINQ query expressions as "not SQL", and `aws_native.py`'s whole-word type match never matched.
- **Tracking workbook (`build_tracker.py`, step 8.15).** One `<Client>-Modernization-Tracker.xlsx` with every finding, Windows-only API use (one row per evidence line), Linux readiness hit, phased work item, package, DLL, AWS managed-service swap, open question and application; every tracking sheet ends with Status / Owner / Notes.
- **Secret check covers .xlsx (`verify_report.py`).** Workbooks in the report folder are checked like the other outputs.
- **Review-found work in the estimate (`estimate_phases.py`).** `estimate-inputs.json` `extra_items` adds work that no quantity covers (for example a page that reads only from a store being removed) to the main estimate; scenarios can set it too.

## Changed in 3.2.3

- **Claude-first operating model is the default.** The porting engine or Claude writes every line of code and SQL; nothing is hand-written. Hours are engineer time to run the tools, read the diff where the risk is, run build and test loops, decide and sign off.
  - `estimate_phases.py`: two rate sets, `claude-first` (default) and `engineer-paced` (the reference plan's rates, kept as the scenario "Engineer-paced rates"); `estimate-inputs.json` `rate_profile` picks one. Finding rates have the same two sets.
  - `data/estimation.json` `ai_assistance`: code 0.10-0.20, db 0.15-0.30, redesign 0.25-0.45 of manual-equivalent; the old factors are kept under `engineer_paced` (`estimate_effort.py --factors engineer-paced`).
  - `effort_facts.py` passes the same factors to `aws_native.py`, so the managed-service swaps (stage S) follow the model too.
  - The Claude-first rates are INFERRED from the operating model: calibrate from the first repository's measured hours.

## Changed in 3.2.2

- **Web Forms projects priced by their UI share (`discover_estate.py`, `estimate_effort.py`, `data/estimation.json` `ui_split_types`).** The inventory now counts each project's Web Forms UI code (`loc_ui`: page, user control and master page code-behind and Page subclasses). Only that code and its markup take the Web Forms rewrite rate and the redesign AI factor; HTTP handlers, services, business logic and data access in the same project port at the `web-library` rate with the code AI factor. Before, a handler-only service typed `aspnet-webforms` was priced as a full UI rewrite.
- **Generated code no longer inflates complexity (`map_graphs.py`).** Run-time-bound calls in generated files (service-reference proxies, designers) are left out of the per-project indirection count, as generated lines already are out of the size.
- **Phased estimate leads (`build_report.py`, `build_html_report.py`, `report.js`).** When `estimate_phases.py` ran, section 8 and the HTML effort tab show its tool-run hours as the planning figure and the parametric model as the cross-check.
- **Application size (`discover_estate.py`, `classify_apps.py`, HTML).** The applications table shows each application's own lines, with lines in referenced projects apart.
- **Stores named in key=value connection strings (`scan_repo.py`, `network_endpoints.py`, `_config.py`, `_analysis.py`).** MongoDB, Memcached, Aerospike and Redis strings in the `Server=...;Database=...` shape get their own engine and default port instead of SQL Server on 1433; Memcached and Aerospike hosts are no longer labelled Redis; a host found in a service reference (WSDL, discovery file, generated proxy) is a SOAP service, not a guess from its operation names; one row per server, database and engine in 4.3.
- **SQL connections counted from config transforms (`estimate_phases.py`, `effort_facts.py`).** A SQL Server host named only in `Web.Release.config` / `Web.Debug.config` counts toward `sql_connections`.
- **Procedures called with no .sql in the repository (`build_report.py`).** Section 4.7 lists the stored procedures the code calls, with call sites, instead of "No database objects inventoried".
- **`address_roles.py` runs `solutions.py` itself** when the solution index is missing.
- **The scan uses this skill's own `network_endpoints.py`** (the documenter's copy is the fallback), so the store and SOAP role rules above reach section 4.4 and the allow-list.
- **NCache detection (`data/aws_native.json`).** The keyword matches NCache by its case and as a word, so method names such as `InsertInCache...` no longer count as NCache call sites.
- **One row per database in the dependency tables (`_analysis.py` `connection_rows`, `build_report.py`, `build_html_report.py`).** Read and read-write strings to the same server and database are one row, labelled with the engine.

## Changed in 3.2.1

- **7R of a shared project (`estimate_phases.py`).** When one application lists another application's project, that project keeps its owner's 7R; before, the last application processed overwrote it.
- **Verifier reads the main report (`verify_report.py`).** On Windows the folder listing put `execution-plan.md` first, so the coverage, structure and dependency gates failed on a correct report. It now picks the main report and checks its own `.html` twin for staleness.
- **File-level evidence counts (`_findings.py`).** A finding cited at line 0 (for example a repository with no `.gitattributes`) now passes the evidence gate.

## Changed in 3.2.0

- **One Linux-readiness scanner.** The check now loads the standalone **linux-readiness** skill (installed with this one); the copy in this skill is gone. Its hits that this skill's rules do not already cover become costed findings, with no double count, and the report has a Linux readiness section and a checklist appendix.
- **AWS Transform codebase scanner first (`atf_scan.py`, step 1.5).** It runs RadNet and RaSQL over every repository before this skill's scans, or imports their results, and reconciles them: executable lines of code, DLL / NuGet / COM / P/Invoke references, and every inline-SQL and execute row against `raw_sql.py`.
- **Phased estimate per repository (`effort_facts.py`, `estimate_phases.py`, step 6.1).** These are the quantities and evidence behind each work item, plus developer hours for a tool-run port in six phases. The inputs are written from what the code shows, and the client questions are marked UNKNOWN.
- **One short summary report (`build_summary.py`, step 8.1).** It gives the answer first, then only what needs action. Every number comes from the other steps' files.
- **Every package and DLL column filled from nuget.org.** Each package gets the frameworks of its latest version, whether it runs on Linux, and a cross-platform replacement or action. DLLs referenced by HintPath get a table of their own: the framework each was built for, other builds, the matching package, its source, and an action. A DLL with no Linux build and no source becomes finding `PKG-BINARY-REFERENCE`.
- **Lift-and-shift track at parity with lift-and-shift-assessment 1.1.0:**
  - GitLab project list and clones (`gitlab_projects.py`, `clone_repos.py`);
  - the branch check (`branch_evidence.py`, `branch_list.py`);
  - a staged intake with 40 more questions, asked only for this track (`--pending`, `--check`, `--stage`; after-scan questions only when the scan found their subject);
  - call records (`--client-update`, `--release-step`, `--branch-note`, `--open-question`, `--decision`) and a guarded `--finalize`;
  - the .docx and workbook (`build_doc.py`, `verify_doc.py`, optional company template);
  - the application-to-server mapping sheet and its check (`build_mapping_sheet.py`, `check_mapping.py`);
  - open questions and the client email (`build_open_questions.py`);
  - every hour explained and self-checked (`build_estimate_explainer.py`);
  - the newer hours rates (cutover split by solution size, pipeline scope, publish profiles left out of the configuration weight);
  - executable-line counting with copied front-end libraries counted apart;
  - the rest of its fixes.
- `context.py` names these steps in NEXT.
