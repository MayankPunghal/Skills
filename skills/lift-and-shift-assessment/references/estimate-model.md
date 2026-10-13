# Estimate model

Hours are developer working hours with AI assistance, as a low-high range per line, plus a 20% buffer on the total. One dev day is 8 h. All rates are in `scripts/data/hours.json` and can be changed; nothing is final until the user says so.

## Contents

- [Counts and rates](#counts-and-rates)
- [How the sample was used](#how-the-sample-was-used)
- [What has no sample behind it](#what-has-no-sample-behind-it)
- [Rules](#rules)

## Counts and rates

Lines are groups of work: one task per solution or per deployable. Nothing is priced per environment variable, per key, per address or per config file.

| Work item | Task | Per | Low-high h | Basis |
|---|---|---|---|---|
| Build check + artifacts | Clean-agent restore and build check | solution | 1-2 | inferred |
| | Deployable artifact and hand-over notes | deployable | 0.5-1 | inferred |
| CI/CD + configuration | Environment-specific configuration (config files tokenised, secrets and settings to Secrets Manager, addresses to DNS names, third-party keys) | solution, by size band | 1-48 | sample |
| | CI/CD pipeline (one shared template adapted per solution) | solution | 1.5-3 | inferred |
| | Extra pipeline work | solution with more than 5 deployables | 2-3 | inferred |
| Framework retarget | Target framework change and rebuild | project | 0.25-0.5 | inferred |
| | Regression pass | solution | 1-2 | inferred |
| Validation + cutover | Test-launch validation | deployable test launch | 1-1.5 | sample |
| | Cutover and defect support, one deployable | solution | 2-3 | inferred |
| | Cutover and defect support, several deployables | solution | 4-5.3 | sample |

**Size bands of the configuration task.** A solution's weight is its config files (publish profiles `.pubxml` excluded), plus secret-like settings, environment variables, distinct private IP addresses, and 2 for each third-party key. The weight only picks the band.

| Weight | Hours |
|---|---|
| 0-2 | 1-2 |
| 3-5 | 2-4 |
| 6-15 | 5-8 |
| 16-30 | 12-18 |
| 31-60 | 20-32 |
| over 60 | 32-48 |

A workload is one solution in one environment; unknown environments count as one per solution, and the document states that each extra environment adds about 160-230 h (test launches and cutover with the buffer). Counts come from `solutions.py`, `third_party.py` and the scans.

## How the sample was used

The manager's reference estimate (two repositories, 16 deployables, 72-108 h) is the source of truth. Its lines: secrets mapping 20-30 h (34 environment variables, 14 service configs), DNS and connection values 6-10 h, third-party re-key 6-10 h (5 integrations), test-launch validation 16-24 h (16 deployables), cutover and defect support 12-16 h (3 waves), contingency 12-18 h. The rates marked sample reproduce those lines from counts measured in the reference code. The SIA workloads are 3 (web app dev, web app prod and staging, update services), so cutover is priced per workload (4-5.3 h each) and validation per deployable launched in each environment (16 launches at 1-1.5 h).

Acceptance test: the sample-basis lines of the reference benchmark run must total within a few hours of 72-108 h (see [evals](../evals/evals.md)).

## What has no sample behind it

Build check, artifacts, the CI/CD pipeline itself and the framework retarget are the skill's own estimates, labelled INFERRED in the document. Replace them with real figures from the dev lead when available.

## Why the model changed (lessons from a 26-repository run)

The first model priced single items (about 286 address mentions at an hour each, every variable, every key) and produced hundreds of hours for work that is one configuration task per solution. A manager's sample showed five lines of 60-90 h for two apps. Checks that caught it, to repeat on every run: divide each line's hours by its count (an hour per address is not plausible when only 27 are distinct private IPs; host names and public domains need no replacement); look for the same activity priced twice (per project and per solution); check the count itself (config files included 18 publish profiles; third-party keys found only in environment variables; secret-like settings counted 43, not 5); and look at the share of the total each line holds. Rates were back-solved so the sample's two solutions land at 32-50 h together; this calibration is by construction, and it is not re-run as a benchmark when the intake gate blocks the old reference workspace.

## Rules

- Only the work items chosen in the intake are priced; the total includes exactly those.
- Per-project lines count a project shared by two solutions once, in the first solution that lists it; per-solution lines count in each solution.
- The buffer is applied once, on the total.
- No modernisation, migration or future-state work is ever priced.
