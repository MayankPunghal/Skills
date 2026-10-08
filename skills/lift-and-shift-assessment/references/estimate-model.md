# Estimate model

Hours are developer working hours with AI assistance, as a low-high range per line, plus a 20% buffer on the total. One dev day is 8 h. All rates are in `scripts/data/hours.json` and can be changed; nothing is final until the user says so.

## Contents

- [Counts and rates](#counts-and-rates)
- [How the sample was used](#how-the-sample-was-used)
- [What has no sample behind it](#what-has-no-sample-behind-it)
- [Rules](#rules)

## Counts and rates

| Work item | Line | Per | Low-high h | Basis |
|---|---|---|---|---|
| CI/CD + Secrets Manager | Environment variables and secrets to Secrets Manager | variable | 0.45-0.65 | sample |
| | Config files with hard-coded values | file | 0.3-0.5 | sample |
| | DNS names and connection values | internal address | 0.75-1.25 | sample |
| | Third-party keys and licences re-keyed | integration | 1.2-2.0 | sample |
| | Pipeline per solution | solution | 3-5 | inferred |
| | Pipeline job per deployable | deployable | 0.5-1 | inferred |
| Build check + artifacts | Restore and build check | project | 0.25-0.5 | inferred |
| | Clean-agent build | solution | 0.5-1 | inferred |
| | Artifact and hand-over notes | deployable | 0.5-1 | inferred |
| Framework retarget | Retarget and rebuild | project | 0.25-0.5 | inferred |
| | Regression pass | solution | 1-2 | inferred |
| Validation + cutover | Test-launch validation | workload | 1-1.5 | sample |
| | Cutover and defect support | workload | 0.75-1 | sample |

A workload is a deployable in one environment. Unknown environments count as one per deployable. The counts come from `solutions.py` and `third_party.py`.

## How the sample was used

The manager's reference estimate (two repositories, 16 deployables, 72-108 h) is the source of truth. Its lines: secrets mapping 20-30 h (34 environment variables, 14 service configs), DNS and connection values 6-10 h, third-party re-key 6-10 h (5 integrations), test-launch validation 16-24 h (16 deployables), cutover and defect support 12-16 h (3 waves), contingency 12-18 h. The rates marked sample reproduce those lines from counts measured in the reference code. The cutover line is priced per workload (0.75-1 h) instead of per wave because waves are a DevOps decision that is usually unknown at assessment time.

Acceptance test: the sample-basis lines of the reference benchmark run must total within a few hours of 72-108 h (see [evals](../evals/evals.md)).

## What has no sample behind it

Build check, artifacts, the CI/CD pipeline itself and the framework retarget are the skill's own estimates, labelled INFERRED in the document. Replace them with real figures from the dev lead when available.

## Rules

- Only the work items chosen in the intake are priced; the total includes exactly those.
- Per-project lines count a project shared by two solutions once, in the first solution that lists it; per-solution lines count in each solution.
- The buffer is applied once, on the total.
- No modernisation, migration or future-state work is ever priced.
