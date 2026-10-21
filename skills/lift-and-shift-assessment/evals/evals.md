# Evaluations for lift-and-shift-assessment

Run each prompt in a fresh session, first without the skill (baseline), then with it. Record the difference below.

## Contents

- [Triggering and routing](#triggering-and-routing)
- [Acceptance test: reference benchmark](#acceptance-test-reference-benchmark)
- [Output checks](#output-checks)
- [Baseline log](#baseline-log)

## Triggering and routing

### Bare invocation
Prompt: `/lift-and-shift-assessment`
Should trigger: yes
First command: `context.py`
Done looks like: state and NEXT shown; nothing started.

### Plain-language trigger
Prompt: "We are moving 30 .NET Framework apps from our data centre to EC2 as they are. How many dev hours is that?"
Should trigger: yes
Done looks like: the workspace is proposed outside the repositories; the questionnaire is asked before any estimate; the work items are optional and chosen by the user; nothing is assumed.

### Intake guardrail
Prompt: "Run the estimate now, I will tell you the details later."
Should trigger: yes
Done looks like: scan_repo.py, solutions.py and the other gated tools refuse while questions are pending; every pending question is asked; unknown is recorded only when the user says it; after-scan and after-build questions are asked when the findings call for them.

### Should not trigger
Prompt: "Port this WCF service to ASP.NET Core on Linux containers."
Should trigger: no (modernization-assessment or normal coding help).

## Acceptance test: reference benchmark

Code: the reference estate (two repositories, 16 deployables). Intake: all four work items, retarget to 4.8.1, environments empty.

Expected from the data: 2 solutions, 17 projects, 15 deployables, 35 environment variables, 19 config files with hard-coded values, 6 re-key items.
Expected hours: the lines marked sample total 72.5-109 h with the buffer, against the manager's 72-108 h. The inferred lines (build check, artifacts, pipeline, retarget) are shown separately and add 39-76 h.
Also expected: the static build check reports BLOCKED for the update services (SmartThreadPool.dll not in the repository) and the real build is NOT RUN until the user approves the downloads.

### Branch check
Prompt: "Re-run the assessment; we may have analysed stale branches."
Should trigger: yes
Done looks like: `branch_evidence.py` runs read-only (no clone, no change); the suggested branch per repository is the protected one that receives merged requests; a newest branch that never received a merged request is flagged as unmerged; the user confirms before any re-clone; the re-run uses a new workspace and the old documents are kept under a clear name.

### Missing files
Prompt: "The build says Library DLLs are missing, send the list to the client."
Done looks like: `stage_library.py` is run first; only files found nowhere (any branch, any folder) go to the client; the rest is reported as a path mismatch.

### Returned mapping workbook
Prompt: "The client sent the filled mapping Excel; is it right?"
Done looks like: `check_mapping.py` is run; contradictions (unknown server, wrong environment, .NET Framework app on Linux, duplicate or invalid address, role contradiction) are listed as questions, not silently corrected; confirmed roles are named.

### Fresh machine, no clones
Prompt (new account, empty folder): "Assess the lift-and-shift of Acme's .NET apps on gitlab.acme.example; the token is in ACME_TOKEN."
Should trigger: yes
Done looks like: setup with `--gitlab-url` and `--gitlab-token-env` (the name, never the value); `gitlab_projects.py` lists projects read-only and the .xlsx is offered to share; `clone_repos.py` makes shallow, push-disabled clones outside the workspace and sets the roots; no file is edited by hand at any step.

### Call answers and decisions
Prompt: "On the call the client said only .NET is in scope and there is no MGN; log it."
Done looks like: `intake.py --decision ... --source "client call, <date>"` and `--client-update` rows; nothing is moved or deleted; the next build shows them in 1.1 and sheet ClientAnswers.

### Companion files
Prompt: "Send the client the questions and the mapping sheet, and explain the hours to my manager."
Done looks like: `build_mapping_sheet.py` (no server pre-filled), `build_open_questions.py` (full, short, email; answered items closed), `build_estimate_explainer.py` (self-check passes; numbers equal estimate.json); each Markdown file has an HTML twin.

## Output checks

- One .docx and one .xlsx for the whole project, not one per solution.
- `verify_doc.py` passes all gates.
- DRAFT status and the environment warning are present until the environments are confirmed.
- Sections 6 to 9 carry a proposal labelled INFERRED when DevOps gave no answer; they are never blank.
- The headings match the reference document in text and order.
- Prose outside tables stays within the `verify_doc.py` limit (it grows with the solution count).
- No UNKNOWN that the DevOps server list, the builds or the GitLab history can answer; no confidence column for address roles; no per-item hours lines.
- Sections of work items that were not selected are absent or marked "No" in section 6.
- No secret value anywhere in the document, the workbook or the chat.

## Baseline log

| Date | Version | Prompt | Without skill | With skill |
|---|---|---|---|---|
| 2026-10-08 | 0.1.0 | reference benchmark | not run | sample lines 72.5-109 h; total 111.5-184.5 h with inferred lines; 7 gates pass |
| 2026-10-13 | 1.0.1 | a 26-repository estate, re-run on the live branches (27 solutions) | not run | 458-758 h; 19 of 27 builds pass; 8 gates pass; 24 UNKNOWN (45 before the server list and builds were used) |
| 2026-10-08 | 1.0.0 | reference benchmark, intake guardrail | not run | same totals; 8 gates pass; real build: web app PASS, services blocked by a missing DLL |
