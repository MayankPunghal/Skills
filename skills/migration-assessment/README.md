# migration-assessment

A Claude Code skill that turns a client's legacy .NET code base (one repository or hundreds) into an evidence-backed **AWS Migration & Modernization Assessment Report**. It works out, from the code alone, what will break on AWS/Linux and .NET 10, how each application should move (7 Rs, including hybrid .NET Standard 2.0 paths), and how much effort it takes.

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
- `/migration-assessment assess-estate`.

Individual steps:
- `discover-estate`, `map-code-graph`, `scan-repos`;
- `review-findings`, `classify-applications`, `estimate-effort`;
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

The estimate covers what the client actually wants and compares the alternatives side by side. Choose with `setup_assessment.py --target-hosting ... --target-database ...`.

| Hosting (code side) | Meaning |
| --- | --- |
| `modernize` | Convert .NET Windows applications to .NET 10 on Linux, per-application 7R decisions |
| `windows-rehost` | Lift-and-shift Windows applications from on-premises to Windows EC2: no code port, only network, identity and configuration changes |

| Database (code side) | Meaning |
| --- | --- |
| `dual` | The app supports SQL Server and PostgreSQL. Adds provider abstraction and keeps every procedure for both engines |
| `postgresql` | PostgreSQL only: every table, view, procedure, function and trigger plus the data-access code. Uses the database inventory (sizes, T-SQL constructs, stored-procedure call sites, EF function imports) |
| `none` | SQL Server stays; no database code change |

Effort is **coding hours only** (no QA, DevOps, project management or contingency), with person-days, AI-assisted and the manual equivalent alongside. Hours are driven by lines of code, project type and a complexity factor (decision density, fan-in, large files); see [estimation-model.md](references/estimation-model.md). The factors are configurable in `scripts/data/estimation.json`. Optional modernizations (SMTP to SES/SNS, Kafka to SQS/SNS, files to S3 and more) are listed with their own hours and are never added to the total.

## What it produces

All in `assessment/report/`:
- **`<Client>-AWS-Migration-Assessment.html`** — the version for PMs, BAs and the client. It is one self-contained page that combines the report and every export:
  - sidebar navigation and global search;
  - KPI cards and charts;
  - findings explorer (filter by severity, category or application; click for evidence and fix);
  - sortable application, package, dependency, project and question tables with Download CSV;
  - Gantt timeline, glossary for non-technical readers, dark mode and print/PDF.
- **`<Client>-AWS-Migration-Assessment.md`**, with 11 sections:
  1. Executive summary
  2. Scope and method
  3. Application inventory
  4. Architecture and dependencies (Mermaid map, graphify insights, project interdependencies, workflow dependencies, database object dependencies)
  5. Findings by category (27 categories, each with evidence or "checked, none found")
  6. Database assessment (dual / PostgreSQL code conversion)
  7. Per-application plans (with the hybrid table)
  8. Effort (P10–P90 Monte Carlo range, P50 likely, P80 commitment), phased timeline and a coding sprint plan from the day of codebase access
  9. Risks and open questions
  10. Testing, QA and merge strategy
  11. Appendices: packages, projects, every Windows-API occurrence, raw outputs, sources
- **Exports:** `findings.csv/json`, `applications.csv`, `packages.csv`, `open-questions.csv` (with an empty answer column) and `endpoints.csv`.

## Structure

```
migration-assessment/
├── SKILL.md                 workflow, principles, command table
├── README.md, install.py
├── references/              checklist (section 5 extended), windows-api-catalog (generated), package-map (generated),
│                            seven-rs, target-platforms, database-assessment, tools-landscape, linux-pitfalls,
│                            estimation-model, review-findings, scale-and-subagents, write-report, report-template,
│                            style-guide, calibration, setup, sources
├── scripts/                 setup_assessment, discover_estate, map_graphs, scan_repo, review_queue, classify_apps,
│   │                        estimate_effort, validate_linux_build, build_report, verify_report, context,
│   │                        render_references, _common, _findings
│   └── data/                rules.json (131 evidence rules), package_map.json, categories.json, estimation.json,
│                            decision_rules.json   <- calibration lives here, not in code
├── calibration/             drop sample reports in samples/ (never packaged); gap-analysis template
├── templates/narrative/     stubs for the seven narratives
└── samples/eshop/           end-to-end sample on Microsoft's public eShopModernizing repo: report, exports, reviews, decisions, narratives
```

## Calibration

Drop your sample reports into `calibration/samples/` and ask for `calibrate-report`. `extract_sample.py` outlines each sample (DOCX, PPTX, XLSX, MD or HTML; PDFs are read directly), and `calibration/gap-analysis.md` records what to adopt. Samples are never packaged.

The report wording and structure live in `references/report-template.md` and `references/style-guide.md`. Effort numbers live in `scripts/data/estimation.json`, and 7R thresholds in `scripts/data/decision_rules.json`. Your sample reports and actuals are applied there; see `references/calibration.md`.

## Confidentiality

The skill never writes into client repositories, never copies secret values (the masking is verified by a gate), and sends package IDs (and versions) to api.nuget.org unless the scan runs `--offline` or `online_package_lookup` is false; private package IDs are sent too (they are simply not found), so use `--offline` for confidential estates. Reports contain architecture and security findings: share them privately.
