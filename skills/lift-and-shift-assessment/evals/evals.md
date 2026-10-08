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
Should trigger: no (migration-assessment or normal coding help).

## Acceptance test: reference benchmark

Code: the reference estate (two repositories, 16 deployables). Intake: all four work items, retarget to 4.8.1, environments empty.

Expected from the data: 2 solutions, 17 projects, 15 deployables, 35 environment variables, 19 config files with hard-coded values, 6 re-key items.
Expected hours: the lines marked sample total 72.5-109 h with the buffer, against the manager's 72-108 h. The inferred lines (build check, artifacts, pipeline, retarget) are shown separately and add 39-76 h.
Also expected: the static build check reports BLOCKED for the update services (SmartThreadPool.dll not in the repository) and the real build is NOT RUN until the user approves the downloads.

## Output checks

- One .docx and one .xlsx for the whole project, not one per solution.
- `verify_doc.py` passes all gates.
- DRAFT status and the environment warning are present until the environments are confirmed.
- Sections 6 to 9 carry a proposal labelled INFERRED when DevOps gave no answer; they are never blank.
- The headings match the reference document in text and order.
- Prose outside tables stays under 1,500 words.
- Sections of work items that were not selected are absent or marked "No" in section 6.
- No secret value anywhere in the document, the workbook or the chat.

## Baseline log

| Date | Version | Prompt | Without skill | With skill |
|---|---|---|---|---|
| 2026-10-08 | 0.1.0 | reference benchmark | not run | sample lines 72.5-109 h; total 111.5-184.5 h with inferred lines; 7 gates pass |
| 2026-10-08 | 1.0.0 | reference benchmark, intake guardrail | not run | same totals; 8 gates pass; real build: web app PASS, services blocked by a missing DLL |
