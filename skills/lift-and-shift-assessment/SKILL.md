---
name: lift-and-shift-assessment
description: "Produces a draft AWS lift-and-shift (Windows to Windows, EC2) assessment for a .NET estate of any size: one Word document for the whole project, a small companion workbook, and an estimate in developer working hours, solution by solution. Inventories solutions, projects, deployables and workloads, finds the environment variables, hard-coded addresses, third-party and licensed components and server-to-server connections the dev team must handle, checks that each solution builds, and prices only the work items the user selects. Use when a client's .NET applications move to AWS EC2 as they are (rehost, no C# change) and a dev-hours estimate is needed. Not for modernisation, Linux or native AWS services (use modernization-assessment)."
metadata:
  version: 1.1.1
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
- **The real build always runs.** After the static check, run `build_check.py --run --approve-downloads` on a copy of every solution; the downloads it needs are covered by the user's standing approval and are never asked again: NuGet packages, nuget.exe, and the reference-assembly packages for the old .NET Framework versions (4.0 to 4.6.2) that current Visual Studio no longer ships. They go to the tool cache (`%LOCALAPPDATA%\lift-and-shift-assessment`, delete the folder to remove them), not into Visual Studio. Installing Visual Studio Build Tools itself is still asked first. Report the real result, never a guess.
- **No C# change.** Out of scope: modernisation, Linux, native AWS services, DevOps and database work. The waves, target architecture and execution steps are still ours to propose for planning: they are written into the document as an assumption, labelled INFERRED, and replaced by DevOps answers when given. They are never left blank.
- **Check the branch before trusting the scan.** A default branch can be years stale (one repository here: 2017) while the live line is another branch. `branch_evidence.py` (read-only, needs the VPN) lists the branches that receive merged requests, the release tags, protected branches, CI files and how far the newest branch is ahead. The suggested branch is the protected one that receives the merged requests, usually an integration branch; the newest branch by date can be unmerged work and is flagged. The user confirms the branch per repository (with the client or DevOps); the document records the branch and its last commit date (workbook sheet Branches). Re-clone chosen branches into a scratch folder (single branch, shallow); never switch the user's own clones.
- **Estimate groups of work, never single items.** One task per solution or deployable. Environment-specific configuration is one task whose hours follow a continuous curve of its size (config files, secret-like settings, environment variables, distinct private IPs, 2 per third-party key); never hours per variable, per key or per address. Before showing any number, audit every line for results that cannot be right (hundreds of hours for address replacement, an hour per setting, the same activity counted per project and per solution) and fix the model, not the number.
- **"Missing" must be missing everywhere.** Before telling the client a file is missing, search for it by name in the sibling library checkout and on its other branches. Libraries get reorganised (folders renamed), so most "missing" DLLs are path mismatches, not absent files. `stage_library.py` finds them by name and stages them under the expected paths (the checkout is never changed); the build then says which old path was pointed where. Only what is found nowhere is a client question.
- **Facts we hold are not UNKNOWN.** The DevOps server list gives operating systems, hypervisors, sizes, Jenkins servers and their installed build tools: import it with `map_infra.py --servers <file>` (it keeps the full Application column) and use it. UNKNOWN is for what only people can say.
- **Say what each address is.** `address_roles.py` types every internal address (private IP, public IP, internal host name, company domain) and infers its likely role (Redis, SQL Server, proxy, file share ...) from setting names and ports, never values. Public IPs matter (outbound proxies and allow-listed addresses change with the egress address). The confidence of each guess is for the conversation with the user; it is not printed in the document or the workbook.
- **The returned mapping workbook is checked, not trusted.** `check_mapping.py` finds contradictions between the client's answers, the DevOps list and the code; every finding goes back as a question.
- **Questions stay short and answerable.** Do not ask what the code or the GitLab history answers; close a question when it is answered and say so in the question list.
- **Skill owner log.** Log every script failure, false result or workaround in `SKILL-ISSUES.md` as it happens.
- **Teams are separate.** The dev team owns application code and configuration only. DevOps owns servers, network, VPN, AD, server images, pipelines and migration tooling; the DB team owns the databases. Their work is never a dev-team risk or cost: it goes in a short hand-off list. Do not ask the user questions that belong to another team; record them as that team's open item.
- **Never guess where an application runs.** Which application runs on which server comes from the client's mapping workbook (`build_mapping_sheet.py`, then `check_mapping.py`), never from server names. Group or label applications only from what the code shows (controllers, assemblies, READMEs) and say which labels rest on names alone.
- **Every decision is logged.** A scope or approach decision from a call goes in with `intake.py --decision "<text>" --source "<who, date>"` (and `--client-update` for the 1.1 table) before anything is re-run. Never act on a decision by moving or deleting results: keep them and re-run.
- **Every Markdown deliverable has an HTML twin** (offline, light and dark, branded when `docx_template` is set). The generators write both.
- **Nothing is hand-edited.** Every setting has a flag (`setup_assessment.py`, `intake.py`); every deliverable has a script. If something needs a manual step, add the flag or script to the skill and log it in `SKILL-ISSUES.md`.

## Workflow

Scripts live in `<skill-base-dir>/scripts/` and run from the workspace folder (the one holding `assessment.json`). Start every session with `context.py`: it prints the state and the NEXT step. A bare `/lift-and-shift-assessment` (or `help`) shows that state and the step menu and starts nothing.

```
Progress:
- [ ] 0. New machine? Check the prerequisites below once
- [ ] 1. context.py (state, NEXT)
- [ ] 2. setup_assessment.py --client "<name>" [--gitlab-url URL --gitlab-token-env NAME] [--docx-template FILE]   (new workspace outside the repos)
- [ ] 2b. No clones yet: gitlab_projects.py [filters] (read-only list; share the .xlsx), then clone_repos.py --dest <folder outside the workspace> [--only-dotnet] --set-roots
- [ ] 3. discover_estate.py
- [ ] 4. Intake questionnaire (ask, then intake.py --answers)
- [ ] 5. branch_evidence.py (VPN, read-only): confirm the branch per repository; re-clone the chosen ones if they differ
- [ ] 5b. scan_repo.py --all, then map_infra.py --servers <DevOps list> --all
- [ ] 6. solutions.py, then third_party.py, then address_roles.py
- [ ] 7. build_check.py (static); stage_library.py when a library moved; build_check.py --run --approve-downloads (always)
- [ ] 8. config_template.py (only when CI/CD + Secrets Manager is selected)
- [ ] 9. estimate_hours.py
- [ ] 10. build_doc.py, then verify_doc.py
- [ ] 10b. build_mapping_sheet.py (client fills it in), build_open_questions.py (full list, short list, client email), build_estimate_explainer.py
- [ ] 11. Upload the .docx and workbook to Google Drive; give the links (setup_assessment.py --workbook-url <link>, rebuild)
- [ ] 12. Review with the user; record call answers (intake.py --client-update / --decision / --release-step); revise; finalise only when told
- [ ] 13. Mapping workbook back: check_mapping.py --workbook <file>; confirmed facts in through intake.py; rebuild
```

**New machine, new account: prerequisites.** The skill folder is all you need; nothing from an earlier session is assumed.
- Python 3.10+ (`py` on Windows), standard library only; git on PATH (with `core.longpaths` on Windows).
- For the real build: Visual Studio Build Tools with MSBuild and the web development build tools (`dotnet build` cannot build web projects), and the .NET SDKs the solutions target. `build_check.py --toolchain` says what is there; installing Build Tools is asked first. NuGet packages, nuget.exe and old reference-assembly packs are standing-approved downloads (see Principles).
- GitLab: the host reachable (often a VPN) and a read-only token in an environment variable; give its NAME with `--gitlab-token-env` (never the value). The API is used with GET only.
- Branded document (optional): the company .docx template outside the skill, given with `--docx-template`. Page numbers in its table of contents come from Word (Windows, Word installed) plus `pip install pymupdf`; without them Word fills them in when the file is opened.
- The DevOps server list (.xlsx) when there is one: `map_infra.py --servers <file>`.
- Sharing: the Google Drive connector, for the upload step.

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

- Read the build findings: a missing reference DLL or an installer project is a real blocker the dev team must resolve before artifacts; say which. A build that reads another repository's bin folder (build order across repositories) is a pipeline dependency, not a missing file.
- Read the UNKNOWN list in the finished document and ask which ones a fact we already hold can fill (server list, builds, GitLab); leave only what people must answer.
- Run `verify_doc.py`; if the prose-length gate fails, shorten sentences, do not drop facts.
- Decide with the user whether a licensed component with no key in the code needs a new licence on the new servers; the document lists it as UNKNOWN.
- Check the environments with the user, and say how many workloads that makes (solution x environment: one environment is one workload, its deployables sit inside it).
- Review the proposed waves and architecture with the user; they are rough assumptions and can be changed.
- Name the INFERRED share of the hours and offer to replace it once the dev lead gives real figures (change `scripts/data/hours.json`).
- If a client uses a licensed vendor that is missing from `scripts/data/commercial_packages.json`, add it.

## Maintaining this skill

Follow CONVENTIONS.md of the Skills repository: description under 1,024 characters, body under 500 lines, reference files over 100 lines start with a Contents list, forward slashes in paths. Run the repository's skill validator (in the Skills repository root) before every commit. The acceptance test is the reference benchmark: the `sample` lines must total close to the manager's 72-108 h ([evals](evals/evals.md)). Changes to rates go in `scripts/data/hours.json`, with the reason in the commit message. Bump the third digit of the version for small changes.
