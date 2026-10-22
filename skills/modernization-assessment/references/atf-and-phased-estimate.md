# AWS Transform scanner, phased estimate and the summary report

Four steps that run with the rest of the assessment. The first runs AWS's own codebase scanner before this skill's scans. The second and third turn the scan into the quantities and hours of a tool-run port. The fourth writes one short report a reader can act on.

## Contents

- [AWS Transform codebase scanner (step 1.5)](#aws-transform-codebase-scanner-step-15)
- [Effort facts (step 6.1)](#effort-facts-step-61)
- [Phased estimate (step 6.1)](#phased-estimate-step-61)
- [Summary report (step 8.1)](#summary-report-step-81)
- [Packages and DLLs on nuget.org](#packages-and-dlls-on-nugetorg)

## AWS Transform codebase scanner (step 1.5)

```bash
py -X utf8 scripts/atf_scan.py                      # RadNet then RaSQL over every inventoried repository
py -X utf8 scripts/atf_scan.py --import <results.zip> ...   # results from a run elsewhere
py -X utf8 scripts/atf_scan.py --reconcile-only     # after scan_repo.py: compare again
```

- **The scanner is AWS's** (`Invoke-CodebaseScanner.ps1`, the AWS Transform codebase scanner); it is not shipped here.
  - Set `atf_scanner_dir` in `assessment.json` (or `ATF_SCANNER_DIR`) to its folder.
  - It needs PowerShell 7.2+ (`pwsh`) and the `powershell-yaml` module. Ask before installing either.
  - It scans locally and uploads nothing.
  - Without it the step prints SKIP; the summary says the scanner did not run and nothing else changes.
- **When to run it:** right after `discover_estate.py`, before `scan_repo.py`.
  - It writes `assessment/atf/apps.yaml`: one group named after the client, one application per repository, with the app name = repository key.
  - It runs `-RadNet` and `-RaSQL` (the scanner accepts one preset per run).
  - Results go to `assessment/atf/<preset>-scanner-results-*.zip`, logs to `assessment/atf/<preset>.log`.
  - A first RadNet run over 26 repositories took about 9 minutes; later runs use the scanner's cache.
- **Output per repository:** `assessment/atf/<repo>/atf.json` and `.md`/`.html`.
  - **RadNet:**
    - executable lines of code (the ATF convention: no blanks, comments or lone brackets), per project and in total, next to this skill's `loc_exec` (same convention, `_loc.py`) and its non-blank count;
    - local DLL, GAC and NuGet references, compared with this skill's DLL and package tables (what each side found that the other did not);
    - COM and DllImport rows against this skill's findings.
  - **RaSQL:**
    - every inline-SQL and ADO.NET execute row matched to `raw_sql.py`'s statements and stored-procedure call sites by file and line (±3 lines);
    - unmatched rows explained (comment, log text, LINQ, wrapper definition, a domain object's own Fill/Update);
    - rows left "to review";
    - what `raw_sql.py` found that RaSQL did not.
- **Lines of code.** The summary quotes the executable count when RadNet ran, because that is the number AWS tooling shows the client. The estimate keeps its own basis (`estimate_phases.py` reviews hand-written plus markup lines).

## Effort facts (step 6.1)

```bash
py -X utf8 scripts/effort_facts.py [--repo X]
```

- **Reads:**
  - this assessment's inventory, scan, findings, `atf.json` and `build/index.json`;
  - `raw_sql.py`'s inventory;
  - the code itself: the Web Forms census, handlers and services, SOAP/WCF service references with the operations called, the web.config surface, request/response contracts, ambient-context uses (CallContext and the class that wraps it, through its static `Current`), ConfigurationManager reads, and git activity.
- **AWS managed services:** it runs `aws_native.py` with the source of the libraries the repository references. That source is found through the scan's DLL table, in the estate or in `source_search_roots`.
- **Writes** `assessment/effort/<repo>/`:
  - `facts.json`;
  - `effort-inputs.md`, the quantities and evidence behind every work item with no hours: shape of the code, port items B1-B12, data-access items A1-A10, the packages and DLLs tables, configuration, network, every finding;
  - `aws-native.*`.

## Phased estimate (step 6.1)

```bash
py -X utf8 scripts/estimate_phases.py [--repo X] [--compare '{"earlier estimate": [low, high]}']
```

- **What it is:** a bottom-up estimate of developer hours per repository for a tool-run port, with no hand-coding:
  - **one** porting engine (AWS Transform for .NET, or the AWS DevTx Version Upgrade Toolkit) ports the code;
  - Claude with the dotnet-modernization skill cleans up what the engine leaves and swaps the AWS managed services;
  - the DB porting agent, or Claude with the DB porting skills, adds the PostgreSQL path beside SQL Server.
  - The hours are engineer time: running the tools, approving plans, reviewing, fixing what the gates reject, deciding designs and signing off.
- **How a line is built:** quantity from `facts.json` × a rate range per unit (`RATES`, each with its basis) + a fixed part. A 15% buffer goes on the subtotal. Planning grade, ±25%.
- **Phases:**

  | Phase | Who | Items |
  |---|---|---|
  | P1 Prepare: baseline build, golden request/response files, page smoke tests | Claude | B2 |
  | P1s Static content: publish to S3 + CloudFront (a project with no C#: nothing to port) | Claude + DevOps | B13 |
  | P2 Port with the engine | the engine | what the engine covers of B1-B11 |
  | P3 Clean-up of what the engine leaves | Claude | the rest of B |
  | P4 Data access: PostgreSQL path beside SQL Server | the DB tool | A1-A8 |
  | P5 Server-hosted services to AWS managed services | Claude | S (from `aws-native.json`) |
  | P6 Verify and cut over | engineers + DevOps | A9, A10, B12 |

- **Engines:** `port_engine` in the inputs is `devtx` (default), `aws-transform` or `claude`. With `claude`, Claude ports and cleans up every stage B item itself, so P2 and P3 are one owner; an unknown value falls back to `devtx`.
- **Items that are not there:** a line whose every quantity is 0 is left out (no solutions or packages to port in a static repository, no database stage when the code has no SQL). The database stage runs only when the scenario moves the database **and** the code has data access (SQL connections, procedure calls, raw statements or data-access API use); otherwise the estimate says "No database code change is planned."
- **Manual findings:** each finding in `assessment/reviews/<repo>.manual.json` becomes an item M1, M2 ... priced from its `effort_key` (finding hours in `data/estimation.json` × the AI-assisted factor), unless an `extra_items` entry names it (`finding`, `id` or `rule`).
- **Not in this estimate:** `excluded` lists what the hours leave out, starting with libraries referenced from outside the repository (`DEP-OUTSIDE-REPO`): they are assessed where their own repository is, or are an open question.
- **Inputs:** `assessment/effort/<repo>/estimate-inputs.json`, written on the first run.
  - Values the code shows are filled in and marked VERIFIED: ambient-context uses, configuration reads, SQL connections, DLLs that become a current package.
  - The intake answers set environments, AWS managed services now or later, and whether the database moves (scenario database `none` drops stage A).
  - The 7R per project comes from `classification.json`.
  - Everything else is a default marked ASSUMED or UNKNOWN.
  - The user edits the file and re-runs; edited values are kept and missing keys are added.
  - Each UNKNOWN carries the question for the client, and `scenarios` holds what-ifs.
- **Writes:**
  - `assessment/effort/<repo>/estimate.json` and `estimate.md`/`.html`: the plan by phase, the application profile, what the SQL Server → PostgreSQL move has to handle, the detail by line item, assumptions, calendar, and what the open questions change;
  - `assessment/effort/estimate-phases.json`, every repository's phases and totals for the summary.
- **Relation to `estimate_effort.py`:** that script stays the estate-level model (engineer days, waves, Monte Carlo, scenarios compared) and the lift-and-shift hours calculator. The phased estimate is the per-repository, tool-run view the summary leads with. When the two disagree by more than the ±25% band, say why in the estimate narrative.

## Summary report (step 8.1)

```bash
py -X utf8 scripts/build_summary.py [--max-rows 12]
```

`assessment/report/<Client>-Modernization-Summary.md` and `.html`. It gives the answer first, then only what needs action. Every number comes from the files above; sections with nothing to say are left out. The sections are:

1. Bottom line: effort and calendar, 7R mix, Linux, dependencies with no Linux build, and how many decisions are waiting.
2. Applications: path, Linux status, what stands in the way, and effort shown once per repository.
3. What must change: Blocker and High issue types with the widest reach.
4. Packages and DLLs that need action.
5. Server-hosted services to AWS managed services, and whether each is in the total.
6. Estimate by phase.
7. Decisions and open questions: the estimate's UNKNOWNs as questions, then the findings' questions.
8. Cross-check with AWS Transform.
9. Where the detail is.

The full assessment report stays the evidence behind it. Do not repeat its tables in the summary.

## Packages and DLLs on nuget.org

`scan_repo.py` (online by default) fills every package and DLL column; an empty cell would read as "checked, nothing to say".

- **Packages:**
  - the frameworks the latest version targets, from its dependency groups, or from its `lib/` folders when nuget.org lists none;
  - whether it runs on Linux: yes, no (.NET Framework builds only, Windows-only `-windows` builds or `win-*` native binaries), or verify (a portable class library only);
  - the replacement or action. For a package with no Linux build, a nuget.org search for a cross-platform fork of the same name is tried, the most downloaded first; for example EnyimMemcached → EnyimMemcachedCore.
- **DLLs referenced by HintPath** (`binary_references`):
  - the framework each was built for, read from the assembly;
  - other builds next to it;
  - the nuget.org package of the same name and its frameworks;
  - its source, found in the estate or in `source_search_roots`;
  - whether it runs on Linux and the action. One with no .NET Standard / .NET build and no source becomes finding `PKG-BINARY-REFERENCE`.
- **Offline run** (`--offline`): every cell says "not checked (offline run)".
