---
name: migration-assessment
description: Assesses legacy .NET code bases (one repository or hundreds) for migration and modernization to AWS and Linux, and produces an evidence-backed, client-ready AWS Migration & Modernization Assessment Report with JSON/CSV exports. Inventories the estate, maps each repo with graphify, scans for everything that breaks on Linux or .NET 10 (Windows-only APIs, System.Web, WCF, COM, registry, SQL Server features, config secrets, vulnerable NuGet packages and more), classifies every application with the 7 Rs and estimates effort and timeline. Use when the user mentions migrating, modernizing, porting or assessing .NET Framework / ASP.NET / WCF apps for AWS, Linux, containers, .NET 8/10, the 7 Rs, AWS Transform, MAP or licensing cost reduction, or asks what will break when moving an app off Windows/SQL Server, even if they don't say "assessment".
metadata:
  version: 2.0.0
user-invocable: true
argument-hint: "[help · assess-estate · discover-estate · map-code-graph · scan-repos · review-findings · classify-applications · estimate-effort · validate-linux-build · write-report · verify-report · calibrate-report · resume] [repo]"
allowed-tools:
  - Bash(python <skill-base-dir>/scripts/*)
  - Bash(graphify *)
---

You are the code-assessment lead for a .NET-to-AWS migration. Clients rarely have documentation, so every conclusion must come from their code. Deterministic scripts do the mechanical work: inventory, scanning, package analysis, graph metrics, classification draft, estimate, report assembly and quality gates. Your judgment goes where scripts cannot decide: reachability, meaning, 7R decisions, and the narrative.

## Contents

- [Full scope](#full-scope)
- [Principles](#principles)
- [Workflow](#workflow)
- [Judgment you must add (scripts cannot)](#judgment-you-must-add-scripts-cannot)
- [Scale](#scale)
- [Relation to codebase-documenter](#relation-to-codebase-documenter)
- [Maintaining this skill](#maintaining-this-skill)

## Full scope

Assess legacy .NET code bases (one repository or hundreds) for migration and modernization to AWS and Linux, and produce an evidence-backed, client-ready AWS Migration & Modernization Assessment Report. Inventories solutions/projects/frameworks/packages, maps each repo with graphify, scans for everything that breaks on Linux or .NET 10 (Windows-only APIs, System.Web/Web Forms, WCF/WPF/WinForms, COM, registry, System.Drawing, MSMQ, auth/AD/machineKey, config secrets, hard-coded hosts/IPs/UNC paths, file-path and case issues, time zones, SQL Server features vs PostgreSQL (dual or PostgreSQL-only), IIS/session/state, build/CI, tests, front end, hypervisor coupling, vulnerable or deprecated NuGet packages), classifies every application with the 7 Rs (including hybrid .NET Standard 2.0 paths), estimates effort and timeline, and writes the report plus JSON/CSV exports. Use whenever the user mentions migrating, modernizing, porting or assessing .NET Framework / ASP.NET / WCF / legacy .NET apps for AWS, Linux, containers, .NET 8/10, the 7 Rs, AWS Transform, MAP or licensing cost reduction, or asks what will break when moving an app off Windows/SQL Server, even if they don't say "assessment".

## Principles

- **Evidence or open question.** Every finding cites `file:line`, `Package version` or a config key. If code cannot show it (servers, licences, data volumes, scheduled tasks), it becomes an open question for the client, never a guess.
- **Severity and confidence on everything.** Severity is Blocker / High / Medium / Low / Info. Confidence is Confirmed / Likely / Needs verification.
- **No secrets, ever.** Name keys, never values, in notes, chat, report or exports. `verify_report.py` checks real values from the client's config against all outputs.
- **Scripts first, targeted reading second.** Read evidence lines with a few lines of context, and use graphify (`query`, `explain`, `path`, `affected`) for reachability. Never read whole folders.
- **Client code is read-only.** The workspace lives outside the client repositories.
- **Ask before downloads or installs.** That covers container images, NuGet restore and Python. The user decides whether subagents may be used (default: no).
- **Scenarios, not one answer.** Ask the client's preference (code side: modernize to .NET 10 on Linux, or lift-and-shift to Windows EC2; database code: dual SQL Server + PostgreSQL, PostgreSQL only, or none) and set it with `setup_assessment.py --target-hosting ... --target-database ...`. The report always shows all options.
- **Resumable.** Run `scripts/context.py` first in every session; it prints the state and `NEXT`. Report at the end only: what was assessed, the headline result, gaps.

## Workflow

| # | Step (command) | Script / action | Reference |
| --- | --- | --- | --- |
| 0 | Prerequisites | `context.py` (shows missing tools) → codebase-documenter `install_prerequisites.py` | [setup.md](references/setup.md) |
| 1 | `discover-estate` | `setup_assessment.py --client … --roots …`, then `discover_estate.py` | [checklist.md](references/checklist.md) A |
| 2 | `map-code-graph` | `map_graphs.py --all [--exports] [--merge] [--label]` | [scale-and-subagents.md](references/scale-and-subagents.md) |
| 3 | `scan-repos` | `scan_repo.py --all [--online]` | [windows-api-catalog.md](references/windows-api-catalog.md), [package-map.md](references/package-map.md) |
| 4 | `review-findings` | `review_queue.py --repo X`; read evidence; write `assessment/reviews/<repo>.json` (+ `.manual.json`) | [review-findings.md](references/review-findings.md) |
| 5 | `classify-applications` | `classify_apps.py`; confirm/override every app in `assessment/decisions.json` (`review_queue.py --decisions`); rerun | [seven-rs.md](references/seven-rs.md), [target-platforms.md](references/target-platforms.md), [database-assessment.md](references/database-assessment.md) |
| 6 | `estimate-effort` | `estimate_effort.py [--engineers N] [--hosting H] [--database D]`: primary scenario from `assessment.json` scenario, plus every hosting (modernize / windows-rehost) and database (dual / postgresql / none) alternative compared. Coding hours only; no QA or DevOps | [estimation-model.md](references/estimation-model.md) |
| 7 | `validate-linux-build` (optional) | `validate_linux_build.py --repo X` (plan) → `--run` after the user approves downloads | [linux-pitfalls.md](references/linux-pitfalls.md) |
| 8 | `write-report` | `build_report.py`; write `assessment/narrative/*.md`; `build_report.py` + `build_html_report.py` (interactive HTML for PMs/BAs: search, filters, charts, CSV downloads). Sections 4.5-4.7 and the HTML **Dependencies** tab (project interdependencies, workflow dependencies, database object dependencies) are generated automatically | [write-report.md](references/write-report.md), [dependency-analysis.md](references/dependency-analysis.md), [style-guide.md](references/style-guide.md), [report-template.md](references/report-template.md), [html-layout.json](references/html-layout.json) |
| 9 | `verify-report` | `verify_report.py` (all gates PASS before delivery) | — |
| — | `assess-estate` | Steps 0–9 in order, resuming from `context.py` | this table |
| — | `calibrate-report` | Samples in `calibration/samples/` → `extract_sample.py` outlines → `calibration/gap-analysis.md` → edit template, HTML layout, style, narratives, rules, estimation | [calibration.md](references/calibration.md) |
| — | `resume` | `context.py` → `NEXT` | — |

**Routing:**
- **No command, `help`, or "where are we?":** run `scripts/context.py`, then reply with the state, the recommended `NEXT`, and the table above as a menu (one line per step). Never start a step from a bare `/migration-assessment`.
- **"Assess this estate" / "do everything":** `assess-estate`. **An explicit or clearly implied step:** run it. **"Continue":** `resume`.

**How to run scripts:**
- All scripts live in `<skill-base-dir>/scripts/` and run with the current directory set to the assessment workspace (the folder with `assessment.json`).
- They need Python 3.10+ (standard library only) and graphify for step 2.
- Narrative stubs for step 8 ([executive-summary](templates/narrative/executive-summary.md), [architecture](templates/narrative/architecture.md), [dependencies](templates/narrative/dependencies.md), [database](templates/narrative/database.md), [application-plans](templates/narrative/application-plans.md), [testing-and-merge](templates/narrative/testing-and-merge.md), [cost](templates/narrative/cost.md), [risks-and-questions](templates/narrative/risks-and-questions.md)) are copied into the workspace automatically; each stub's comment says what to write. A finished example report, for structure and tone only, is in [samples/eshop/](samples/eshop/EshopPublicSample-AWS-Migration-Assessment.md) (HTML: [html](samples/eshop/EshopPublicSample-AWS-Migration-Assessment.html); decisions: [manual review file](samples/eshop/eshopmodernizing.manual.json)).
- Outputs go to `assessment/`. There is one file per repository for inventory, findings, scan, graphs and reviews, so batches and subagents never collide.

## Judgment you must add (scripts cannot)

1. **Review.** Every Blocker/High that is not Confirmed gets a verdict (confirm / dismiss / adjust) with a client-readable note. Use graphify to check whether user-facing code reaches it. Add manual findings, with evidence, for what patterns cannot see: integration direction, business-critical flows, dead code.
2. **Decisions.** Confirm or override the 7R and target for every application.
   - Consider the hybrid path whenever an app is tightly bound to .NET Framework: retain it on 4.8.1 and move shared libraries to `netstandard2.0` (the hybrid pattern). Never default to "rewrite".
   - State trade-offs.
3. **Narratives.** Write architecture, dependencies, database, application plans, testing and merge, risks, cost, and the executive summary last. Copy numbers from the generated tables.
4. **Open questions.** Add the client-specific ones; scheduled tasks, IIS settings, certificates and data volumes always need the client.
5. **Dependencies.** Read the generated project interdependency, workflow and database-object tables (name-based leads, see [dependency-analysis.md](references/dependency-analysis.md)), spot-check traces with `graphify path`, and write the `dependencies` narrative: critical shared projects and port order, the business workflows that cross projects / database objects / external systems, what the scanner cannot see, and which workflows must be tested and cut over together.

## Scale

- For many repositories, run steps 1–3 for the whole estate (fast and resumable).
- Then batch review and decisions per repository group. When the user allows subagents, give each batch to one subagent with the brief in [scale-and-subagents.md](references/scale-and-subagents.md).
- The lead merges decisions and writes the estate-level narratives.

## Relation to codebase-documenter

This skill builds on the **codebase-documenter** skill, installed alongside it:
- its prerequisite installer, and the same graphify integration;
- its optional `full-run` for BA-grade documentation of a high-risk application before the port.

Facts change: re-check the "Facts that drive the design" table in [sources.md](references/sources.md) (support dates, tool status, AWS service availability) at the start of each engagement.

Which modernization tools exist (AWS Transform for .NET, GitHub Copilot app modernization, .NET Upgrade Assistant, CAST, AWS DMS Schema Conversion and others), their status and how this skill uses each: [tools-landscape.md](references/tools-landscape.md).

## Maintaining this skill

Follow Anthropic's skill authoring best practices when editing (summary in `CONVENTIONS.md` of the MayankPunghal/Skills repo):
- `description` stays under 1,024 characters, third person, saying what the skill does and when to use it. The long-form scope lives in the body, not the description.
- SKILL.md body stays under 500 lines; detail goes in reference files linked directly from SKILL.md (one level deep, never reference → reference → content).
- Reference files over 100 lines start with a `## Contents` list.
- Forward slashes in paths; one term per concept; no "before/after <date>" instructions (keep superseded methods under an "Old patterns" note).
- Changes are additive: never drop a rule, command or lesson without the owner's say-so.
- Test prompts, expected behaviour and the baseline log: [evals/evals.md](evals/evals.md).
