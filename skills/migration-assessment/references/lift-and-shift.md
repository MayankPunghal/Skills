# Lift-and-shift track

A lift-and-shift assessment answers one question for the application (.NET) team: **what must change so the same applications run on Amazon EC2 with the same operating system, and who does it?** It is not the modernization report with parts removed. It has its own rule map, its own tool, its own report template, estimate and gates. `intake.py` selects it (`assessment_type: lift-and-shift`).

## Contents

- [Who owns what](#who-owns-what)
- [The rule map: landing.json](#the-rule-map-landingjson)
- [Configuration templates: config_template.py](#configuration-templates-config_templatepy)
- [What the report contains](#what-the-report-contains)
- [The estimate](#the-estimate)
- [The hours calculator](#the-hours-calculator)
- [Re-runs and the inventory workbook](#re-runs-and-the-inventory-workbook)
- [Checklist for a new run](#checklist-for-a-new-run)

## Who owns what

| Team | Owns | In the report |
| --- | --- | --- |
| .NET team (the reader) | Application code and configuration | Sections 3 to 5, costed in section 9 |
| DevOps | Servers, network, VPN, domain, DNS, VM export or rebuild, CI runners | Section 6 server build sheet, section 7 network, section 8 hand-offs. Not costed, not an application-team risk |
| DB team | Databases, their migration and logins | Hand-off rows only. No database section unless a database code change is needed |
| Security | Secrets, certificates, key export | Hand-off rows |
| Vendors, business owner | Third parties, allow-lists, maintenance windows, decisions | Hand-off rows and questions |

Never ask the user a question one of the other teams owns, and never list their work as the application team's risk. Technical defaults (such as the token style) are chosen by the skill.

## The rule map: landing.json

`scripts/data/landing.json` maps each scan rule to `[area, owner, change, severity, action]`.

- **area**: addresses and names; identity, domain and accounts; secrets and protected configuration; files, paths and storage; tied to the machine; mail, file transfer and other servers; jobs, services and scheduling; time zone and clock; IIS and hosting setup; database connections and server features; printing, reporting, Office and other on-premises integrations.
- **owner**: `dotnet`, `devops`, `dba`, `security`, `vendor`, `business`.
- **change**: `config` (a value becomes a CI variable), `code`, `server` (setup on the host), `network` (network and DNS), `identity` (identity and domain), `verify` (check after the move), `decision`.
- **severity**: what the finding does to the move (not to a Linux or .NET 10 port).
- **action**: one sentence for the reader.

A rule that is **not listed** is relevance `future`: it does not stop the same code running on Windows on EC2 (Forms authentication, Web API 2, BinaryFormatter, PDF libraries, packages, XSLT script, PostgreSQL-incompatible SQL). It never reaches sections 4 and 5; it is summarised in section 12 and stays in `findings.csv`. Only rules owned by `dotnet` with change `code` are costed per finding; configuration is costed per CI variable.

`_findings.load()` applies the map (`_landing.annotate`) so every consumer sees the lift-and-shift severity (`severity_modern` keeps the modernization one). A manual finding may carry its own `landing` block. To add a rule, add it to `rules.json` (the pattern) and to `landing.json` (the map), then run `validate_skills.py`.

## Configuration templates: config_template.py

Run after `map_infra.py`. For every configuration file of the repository it:

1. classifies each value (database connection string, password or token, URL with credentials, internal IP or host name, company DNS name, UNC path, folder on another drive, certificate thumbprint, machine key); public URLs, `C:\` folders and public IPs are **kept** and listed in section 4.5 with the reason;
2. replaces each value to change with a token (`${NAME}` by default; `--token-format` accepts `#{NAME}#`, `{{NAME}}`, `__NAME__`, `%NAME%`) and writes the tokenised copy under `assessment/configtpl/templates/<repo>/<path>.tmpl`. The client's files are never touched;
3. names the variables after the setting (a generic name gets a file or project prefix; a project holding a different value from the majority gets a project-prefixed name);
4. writes `configtpl/<repo>.json`, `configtpl/ci/render-config.ps1` (fills tokens from CI variables, escapes for XML or JSON, writes nothing when a variable is missing), `variables.example.env` and `gitlab-ci.example.yml`.

Which names count as the company's own DNS names comes from `company_domains` in `assessment.json` (the intake question, or detected from the hosts in the code and stored with `company_domains_auto`, then listed as a question to confirm; internal names such as `.local` are handled as internal host names). Secret values are never stored or printed; a hash in memory only detects two secrets that share one value. The report copies the templates and CI helpers to `report/config-templates/` and the variable list to `config-variables.csv` and `config-placeholders.csv`. `verify_report.py` checks that every replaced setting has a template file and that no secret value appears in `configtpl/` or the report.

## What the report contains

Template `references/report-template-lift-and-shift.md`, HTML layout `references/html-layout-lift-and-shift.json`, narrative stubs `templates/narrative-lift-and-shift/`:

1. Summary (verdict, numbers, what the .NET team does, what other teams must do) 2. Scope and method 3. Applications 4. Configuration changes (4.1 CI steps, 4.2 values to replace, 4.3 files, 4.4 code changes, 4.5 values that stay) 5. What will not work the same on AWS (by area) 6. Server build sheet 7. Network and integrations 8. Hand-offs by team 9. Effort and timeline 10. Risks and open questions 11. Testing and cut-over 12. Future options 13. Appendices.

Section 10.2 lists only the application team's questions. A rule that asks the same question for many items becomes one question, and the questions that belong to DevOps, the DB team or security are listed under that team in section 8 and in `open-questions.csv`. Open questions are the application team's: what it needs from other teams (the new address of each internal server, the secret store) and decisions that change its work. Questions the intake already answered are dropped.

## The estimate

**The headline estimate of this track is the hours calculator (next section).** The engineer-days model described here is still computed (it feeds the scenario comparison and `work_packages`) but is not the headline when the intake goal is lift-and-shift.

`estimation.json` scenario `lift-and-shift` has `"landing": true` and `lift_and_shift_hours`. Shared work is counted once per repository, never once per application: reviewing the generated templates and adding the render step to the pipeline (`per_repository`), and setting and checking each UNIQUE CI variable in every environment (`per_variable`, capped per repository; the applications of a repository share the variables). Per application: the smoke test (`smoke_test`). Code changes are costed per place (`code_per_place`: move a hard-coded value to configuration, read the forwarded client address). Nothing from modernization, migration or the future options is included. Hours are manual-equivalent, reduced by the AI-assistance factor for code work only, rolled up by Monte Carlo (P10 to P90, P50, P80). Server, network, database, QA, project management and contingency are excluded and stated as such.

## The hours calculator

Effort is **developer working hours, AI-assisted, 8 h per dev day, low-high range per unit plus a 20% buffer, solution by solution**. It adopts the calculator of the sibling skill `lift-and-shift-assessment` because it matches the manager's estimate.

| Script | What it does | Output |
| --- | --- | --- |
| `solutions.py` | Solution-wise inventory: solutions, projects, deployables, workloads (deployable × environment), environment variables read in code, config files with hard-coded values, internal endpoints, projects to retarget. Honours `scope_exclusions` and the environment lists | `assessment/solutions/index.json` |
| `third_party.py` | Licensed components, integrations (SDK packages, vendor-named variables, external hosts called from server code) and server-to-server connections; an item needs a re-key only when there is evidence of a key | `assessment/solutions/third_party.json` |
| `estimate_hours.py` | Counts × `data/hours.json` for the work items the intake selected; 20% buffer; labels each line `sample` (calibrated to the manager's sample) or `inferred` | `assessment/estimate_hours.json` |
| `build_check.py` | Static readiness of each solution on a clean agent (missing reference DLLs, installer projects, web build targets, `packages.config`); `--run --approve-downloads` builds a **copy** with MSBuild after the user approves the NuGet restore | `assessment/build/index.json` |

`estimate_effort.py` runs the first three itself for this track and merges the result into `estimate.json` (`basis: "hours"`); `build_check.py` is run on demand and its findings feed the *Build check + deployable artifacts* work item. The report (sections 1.1, 7.1, 7.2, 7.4, 7.6, the HTML effort tab and `landing_report.py`'s summary and estimate blocks) shows the total range, the split by work item, the split by solution, every line, and the sample-versus-inferred share. Rates, evidence labels and the reference benchmark: [estimation-model.md](estimation-model.md#hours-calculator-lift-and-shift-track).

Intake questions that feed it (asked only when the goal is lift-and-shift): `scope_confirm`, `scope_exclusions`, `work_items`, `retarget_to`, `regression_tests`, `estimate_basis`, `environments`, `environments_differ` (then `intake.py --solution ID --environments "..."`), `pipeline_scope`, `pipeline_solutions`. `intake.require_hours()` stops `solutions.py`, `estimate_hours.py` and `build_check.py` while one that applies has no answer; `unknown` is accepted only when the user says it.

## Re-runs and the inventory workbook

`update_inventory_xlsx.py` merges into the client's workbook (module `_xlsx_merge.py`):

- a row is matched by identity (repository, project, item), so the same finding is one row; a new finding is added with First seen; a changed one is marked "changed since previous run";
- a row the run no longer finds is **kept** and marked "not found in the latest run (date)"; delete it by hand once agreed;
- rows of repositories the run did not assess are left exactly as they were; an assessed repository never goes back to "not assessed yet"; columns a person added are kept;
- estate-wide sheets (Server coverage) are rebuilt only by a run that covers every in-scope repository;
- every run appends to **Assessment run log** (added, changed, unchanged, not found, kept) and copies the workbook first (five timestamped copies; the very first copy is never removed);
- `--dry-run` prints the effect and writes nothing. Run it first on a workbook the client edits.

## Checklist for a new run

1. `intake.py --questions`, ask them with the multiple-choice tool, `intake.py --answers`.
2. discover, scan, map-infra (it detects the client's web domains), `config_template.py`, review, classify, estimate (`estimate_effort.py` runs the hours calculator for this track), optionally `build_check.py`.
3. Write the narratives (config-plan first: the settings the templates cannot hold, encrypted sections, files outside the repository).
4. `build_report.py`, `build_html_report.py`, `verify_report.py` (all gates PASS), then `update_inventory_xlsx.py --dry-run` and the real run.
