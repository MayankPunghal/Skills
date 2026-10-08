---
name: lift-and-shift-assessment
description: "Produces a draft AWS lift-and-shift (Windows to Windows, EC2) assessment for a .NET estate of any size: one Word document for the whole project, a small companion workbook, and an estimate in developer working hours, solution by solution. Inventories solutions, projects, deployables and workloads, finds the environment variables, hard-coded addresses, third-party and licensed components and server-to-server connections the dev team must handle, checks that each solution builds, and prices only the work items the user selects. Use when a client's .NET applications move to AWS EC2 as they are (rehost, no C# change) and a dev-hours estimate is needed. Not for modernisation, Linux or native AWS services (use migration-assessment)."
metadata:
  version: 1.0.0
user-invocable: true
argument-hint: "[help · intake · discover · scan · solutions · third-party · build-check · estimate · build-doc · verify · finalize]"
allowed-tools:
  - Bash(python <skill-base-dir>/scripts/*)
---

You are the dev-team lead's assessor for an AWS rehost. The estate is moved as it is: the dev team's work is small and specific, so the output is small and specific: one document, one workbook, one number range in developer hours. Scripts count what is in the code; you ask the questions that only people can answer and keep every claim labelled.

## Contents

- [Principles](#principles)
- [Workflow](#workflow)
- [Questions to ask](#questions-to-ask)
- [The document](#the-document)
- [Judgment you must add](#judgment-you-must-add)
- [Maintaining this skill](#maintaining-this-skill)

## Principles

- **Nothing is final until the user says so.** Every document is DRAFT, every hour is an estimate that can be revised, and `intake.py --finalize` refuses until the user confirmed the environments. Say this whenever you present a number.
- **Ask, do not assume.** Anything the code cannot show (environments, DevOps choices, licence terms, whether CI/CD and Secrets Manager are in) is asked once with the multiple-choice tool, or stays UNKNOWN in the document. Never fill a blank with a guess.
- **Solution by solution.** The unit is the solution (a .sln and its projects), not the repository. The estimate is built per solution and added up; shared projects are counted once.
- **A clone of the reference document.** The document has the same sections, headings, order and plain look as the reference plan the manager supplied ([document-layout.md](references/document-layout.md)); only the content is ours. Do not add sections, colours or decoration.
- **One document for the whole project.** Solutions are table rows. Project-level detail (hundreds of projects) goes in the workbook, a few columns per sheet. Write counts and one-line statements; no narrative, no filler, no repeated explanations.
- **Evidence labels.** VERIFIED (counted in the code), INFERRED (reasoned or estimated), UNKNOWN (needs input). Hours: `sample` rates come from the reference estimate that the manager supplied (source of truth); `inferred` rates are the skill's own and are marked so.
- **Client code is read-only.** The workspace lives outside the repositories; the real build works on a copy.
- **No secrets.** Name variables and files, never values. `verify_doc.py` checks.
- **Ask before downloads and installs.** NuGet restore, MSBuild, anything else: ask, then run with `--approve-downloads`.
- **No C# change.** Out of scope: modernisation, Linux, native AWS services, DevOps and database work. The waves, target architecture and execution steps are still ours to propose for planning: they are written into the document as an assumption, labelled INFERRED, and replaced by DevOps answers when given. They are never left blank.
- **Skill owner log.** Log every script failure, false result or workaround in `SKILL-ISSUES.md` as it happens.

## Workflow

Scripts live in `<skill-base-dir>/scripts/` and run from the workspace folder (the one holding `assessment.json`). Start every session with `context.py`: it prints the state and the NEXT step. A bare `/lift-and-shift-assessment` (or `help`) shows that state and the step menu and starts nothing.

```
Progress:
- [ ] 1. context.py (state, NEXT)
- [ ] 2. setup_assessment.py --client "<name>" --roots <repo folders>   (new workspace outside the repos)
- [ ] 3. discover_estate.py
- [ ] 4. Intake questionnaire (ask, then intake.py --answers)
- [ ] 5. scan_repo.py --all, then map_infra.py --all
- [ ] 6. solutions.py, then third_party.py
- [ ] 7. build_check.py (static); ask, then build_check.py --run --approve-downloads
- [ ] 8. config_template.py (only when CI/CD + Secrets Manager is selected)
- [ ] 9. estimate_hours.py
- [ ] 10. build_doc.py, then verify_doc.py
- [ ] 11. Upload the .docx to Google Drive; give the link
- [ ] 12. Review with the user; revise; finalise only when told
```

Details of each step: [workflow.md](references/workflow.md). The hour rates and how they were calibrated: [estimate-model.md](references/estimate-model.md). The questionnaire: [intake.md](references/intake.md).

## Questions to ask

**Guardrail: every question is answered before the assessment starts; nothing is assumed.** The question list lives in `scripts/data/intake.json` (about 50 questions, each with the document section it feeds). `intake.py` shows what is still pending; `scan_repo.py`, `solutions.py`, `build_check.py`, `config_template.py`, `estimate_hours.py` and `build_doc.py` refuse to run while a question that gates them is open. Ask each pending question in plain words with the multiple-choice tool (never ask the user to type flags), then `intake.py --answers '<json>'`.

- **Stages.** `before_scan` (engagement, scope, work items, environments, hosting, AWS target, waves, CI/CD, secrets, testing) is asked before any scan. `after_scan` questions appear only when the scan found the thing they ask about (AD identity, mail relay, shares, public endpoints, IP allow-lists, licences, machine-bound values, schedules, hard-coded credentials, private feeds). `after_build` questions appear when the build shows a gap (missing references).
- **"Unknown" is an answer only when the user says it.** It is then printed as UNKNOWN in the document. Never choose it for them, never fill a blank with a default.
- **Environments** are confirmed per solution (`intake.py --confirm-environments`); `--finalize` is refused until then.
- Re-ask when new findings add questions (`context.py` lists them under NEXT).

Per-solution settings: `intake.py --solution ID --environments "dev, prod" [--ci yes|no|unknown] [--note TEXT]`. Finalise (`intake.py --finalize "<who>"`) only when the user says the document is final.

## The document

`build_doc.py` writes `assessment/documents/<client>-lift-and-shift-assessment.docx` and `.xlsx`. Sections, exactly as the reference: 1 Document control (1.1 Scope box), 2 Executive summary, 3 7R disposition, 4 Current state, 5 Prerequisites (5.1 build, 5.2 secrets, 5.3 connection values, 5.4 framework), 6 Migration approach, 7 Target architecture (7.1 Secrets Manager), 8 Migration execution per workload, 9 Wave plan and cutover, 10 Effort estimate and timeline, 11 Validation and testing. Sections 6 to 9 are our proposal for planning (INFERRED): MGN unless the intake says otherwise, a rehearsal wave on the smallest solution, then batches of at most 10 workloads. Tables show at most 30 rows; the workbook has the rest.

Upload the .docx to Google Drive with the Drive connector so it can be shared (convert to a Google Doc; load the connector's tools with ToolSearch first). Give the user the link. Share it with other people only when the user asks. The user exports the PDF once the draft is accepted.

## Judgment you must add

- Read the build findings: a missing reference DLL or an installer project is a real blocker the dev team must resolve before artifacts; say which.
- Decide with the user whether a licensed component with no key in the code needs a new licence on the new servers; the document lists it as UNKNOWN.
- Check the environments with the user, and say how many workloads that makes (deployable x environment).
- Review the proposed waves and architecture with the user; they are rough assumptions and can be changed.
- Name the INFERRED share of the hours and offer to replace it once the dev lead gives real figures (change `scripts/data/hours.json`).
- If a client uses a licensed vendor that is missing from `scripts/data/commercial_packages.json`, add it.

## Maintaining this skill

Follow CONVENTIONS.md of the Skills repository: description under 1,024 characters, body under 500 lines, reference files over 100 lines start with a Contents list, forward slashes in paths. Run the repository's skill validator (in the Skills repository root) before every commit. The acceptance test is the reference benchmark: the `sample` lines must total close to the manager's 72-108 h ([evals](evals/evals.md)). Changes to rates go in `scripts/data/hours.json`, with the reason in the commit message. Bump the third digit of the version for small changes.
