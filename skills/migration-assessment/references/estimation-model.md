# Estimation model (v6: coding effort only)

`estimate_effort.py` is parametric and transparent:
- every number lives in `scripts/data/estimation.json` (`version`);
- the working unit is **hours**, with person-days = hours ÷ 8;
- every item is a three-point estimate: low, high, and a mode at low + 40 % of the range (effort is right-skewed), or 50 % in a repository of 100 KLOC or more;
- totals are rolled up by Monte Carlo: the range is **P10–P90** (80 % confidence), "likely" is **P50** and the commitment figure is **P80** (see [Range roll-up](#range-roll-up));
- **scope is developer hours for code and SQL only.** QA, DevOps, infrastructure, project management, parallel-development drift and contingency are not estimated.

## Contents

- [Why the numbers are lower than before](#why-the-numbers-are-lower-than-before)
- [Formula](#formula)
- [Range roll-up](#range-roll-up)
- [Sprint plan](#sprint-plan)
- [Complexity factor](#complexity-factor)
- [Reference points](#reference-points)
- [Scenarios](#scenarios)
- [Optional modernizations](#optional-modernizations)
- [What changes the estimate](#what-changes-the-estimate)
- [Calibration from actuals](#calibration-from-actuals)

## Why the numbers are lower than before

Earlier versions added QA, operations, project management, drift and contingency layers and a heavy database block. They inflated totals well beyond the code actually touched. v4 keeps only what scales with the code:
- project conversion, driven by hand-written lines and project type;
- finding remediation, driven by the rule's effort key and occurrence count;
- database code conversion, driven by object counts and sizes.

**Calibration anchor:** AWS reported 143,000 lines of .NET Framework ported with about 270 developer hours saved (AWS Transform for .NET case study), about 1.9 manual hours per KLOC for a mechanical port. Human-designed work (UI rewrite, auth, interop) is much slower, hence the higher rates for those project types. The report prints the resulting likely hours per KLOC so a reader can sanity-check it.

## Formula

```
conversion(project) = (fixed[type] + hand-written KLOC × rate[type] + markup KLOC × markup_rate[type]) × complexity_factor × size_factor
size_factor         = max(1, (repository hand-written KLOC / 10) ^ 0.10)   COCOMO II diseconomy of scale (360 KLOC → 1.4)
remediation(finding) = min(fixed + per × (occurrences − 1), cap)          by the rule's effort key
code_manual = Σ conversion + Σ remediation
code        = mechanical part × ai_assistance.code_factor (0.30–0.50)
            + redesign part   × ai_assistance.redesign_factor (0.70–1.0)   set enabled=false for manual-only
database    = mechanical part × db_factor (0.35–0.55) + redesign part × redesign_factor   only in a database scenario
```

- Generated code is excluded; a project shared by several apps is ported once.
- **Baseline findings** (System.Web usage, Global.asax, legacy project format …) describe work inside the conversion rate. They show in the report but add no hours.
- **Retain, Retire, Repurchase and desktop clients** pay small fixed code costs (`other_r_hours`): repointing connection strings and endpoints, integration code.
- **Redesign part** (no mechanical path, so AI tools help little): Web Forms projects, findings with effort `medium-change`, `large-change`, `db-object-large` or `package-blocker`, constructs and findings at the PostgreSQL `redesign` level, and the dual-database abstraction. Lists in `ai_assistance.redesign_*`.
- **Manual equivalent:** every total also carries the hours without AI assistance, so the saving is explicit and auditable.
- **Timeline:** coding only. Shared libraries first, then waves of 3 applications (low risk first) with 30 % overlap, database code in parallel with the last waves. Wave length = likely hours ÷ (engineers × 5 × 8 × efficiency). The headline duration comes from the [sprint plan](#sprint-plan).

## Range roll-up

v5 added every item's low to get the minimum and every item's high to get the maximum, then applied the AI factor at its low and high ends. That assumes all items (often a hundred or more) land at the same extreme together. The range grew with every item, and on FulfillmentHub it came out at 167–669 h (4× from end to end) around a likely of 369 h. Industry practice does not add ranges that way:
- **PERT / three-point estimating** sums the expectations and combines the spreads (σ = √Σσᵢ² for independent items), so the total range is narrower than the sum of its parts.
- **AACE RP 41R-08 (estimate ranging)** and the **GAO Cost Estimating Guide (GAO-20-195G)** replace point values with three-point distributions, add correlation between items, and read percentiles off a Monte Carlo simulation. GAO cites the DoD / NASA *Joint Agency Cost and Schedule Risk Handbook* default correlation of **0.3** when no data exist.
- **AACE 18R-97** expects a feasibility (Class 4) estimate within −15…−30 % / +20…+50 %, and a budget (Class 3) estimate within −10…−20 % / +10…+30 %, both at 80 % confidence. McConnell's cone of uncertainty gives 0.67×–1.5× once requirements are known. A code-level assessment sits around Class 3–4.

`_montecarlo.py` (settings in `estimation.json` `rollup`):
- Each item (project conversion, finding, database object group, construct, data-access fact, dual abstraction) is a triangular distribution between its low and high, with the mode at `likely_position`.
- Items share one driver with correlation `correlation` (0.3), using a Gaussian copula. Database objects of one kind and size are priced together as n independent items (normal approximation of their sum).
- The AI factors (code, redesign, database) are **systemic**: one draw per iteration for every item, triangular over their range with the mode at `factor_position`. This is where most of the remaining spread comes from.
- `iterations` (4,000) with a fixed `seed`, so reruns give the same numbers.
- Reported: P10–P90 range, P50 likely, P80 commitment, per work package and in total. `bounds_hours` keeps the old sum-of-lows / sum-of-highs as extremes, labelled as not a planning range.

Package ranges do not add up to the total range (independent items partly cancel); the report says so under the estimate table.

## Sprint plan

`sprint_plan()` in `estimate_effort.py` (settings in `estimation.json` `sprints`):
- Sprint 1 starts on the day the team gets codebase access (`--start-date` or `assessment.json` `scenario.start_date`, set by `setup_assessment.py --start-date`). Without a date the plan counts weeks.
- Sprints are `length_weeks` long (2). Capacity per sprint = engineers × days per week × length × hours per day × team efficiency.
- The first `onboarding_days` (2) of Sprint 1 go to access, clone, restore, the baseline build and the existing tests on the current stack. This is calendar time only, not in the estimate.
- Work is planned at P50 in dependency order: shared libraries, repository-wide items, then applications in wave order. Database code runs in its own lane (`db_engineers`, 1) from Sprint 1 when the scenario changes database code and the team has 2+ engineers. It is split into the provider-neutral data layer (dual), object conversion, T-SQL construct rewrites, data-access code and database findings. Spare lane capacity flows to the other lane.
- The output gives sprints at P50 and at P80 (the same plan with every package at its P80), with end dates when a start date is known. The report shows it in section 8.5 and on the HTML Effort tab.

## Complexity factor

Multiplier on a project's conversion hours (findings already count the hard parts), computed by `_complexity.py` from the source:

| Signal | Effect |
| --- | --- |
| Decision density (branches, loops, `case`, `catch`, `&&`/`||` per KLOC): ≤ 40 / ≤ 90 / ≤ 150 / above | 0.85 / 1.0 / 1.2 / 1.4 |
| Fan-in: three or more projects depend on it | +0.10 |
| Each file over 800 lines | +0.05 (capped at +0.20) |
| Run-time-bound calls per KLOC (`analysis.json` `wiring.per_project`: DI dispatch to a registered implementation, decorators, keyed services, overrides, MediatR / bus messages, events, method groups, stored delegates, dispatch tables, Hangfire / Quartz jobs, redirects, filters, plus service-locator calls): ≤ 5 / ≤ 15 / ≤ 40 / above | +0 / +0.05 / +0.10 / +0.15 |
| Each reflection site (`GetMethod`, `Activator.CreateInstance`, `Type.GetType` …) | +0.02 (capped at +0.10) |
| Projects under 0.3 KLOC | not scaled (density of a few lines is noise) |

The result is clamped to 0.8–1.6.

Why indirection counts: a call bound at run time cannot be followed by reading the code, so porting it means finding the registration, decorator, override or handler first, and testing it needs the composition root running. Calls through local variables that graphify missed are static and do not count. The registrations themselves (legacy container, captive dependencies, missing registrations) are costed as findings in category `di-wiring`, not through this factor. Without the codebase-documenter (no `csharp-resolve.json`), the indirection signals are 0 and the factor falls back to the first three rows.

## Reference points

Manual-equivalent hours per KLOC of hand-written code (`conversion_hours_per_kloc`):

| Project type | Hours/KLOC | Fixed hours |
| --- | --- | --- |
| Class library | 1–3 | 1–3 |
| Web library (references ASP.NET MVC / Web API, but no web.config, Global.asax or Web Application project type: framework extensions, base controllers, services with filters) | 3–7 | 2–4 |
| Console | 1.5–4 | 1–3 |
| Test project | 0.5–1.5 | 0.5–1.5 |
| ASP.NET MVC 5 | 3–7 | 4–8 |
| ASP.NET Web API 2 | 2.5–6 | 3–6 |
| ASP.NET Web Forms → Razor/Blazor | 14–28 | 8–16 |
| WCF → CoreWCF | 4–9 | 4–8 |
| Windows service → Worker | 2–5 | 1–3 |
| Already ASP.NET Core / .NET 5+ | 0.3–1.2 | 1–3 |

**What counts as an application.** A deployable project: a web application (Web Application project type, or a web.config / Global.asax beside the project file), a WCF service, a Windows service, a console / desktop executable, an ASP.NET Core project or a Web Site folder. A library that only references System.Web.Mvc is a *web library*: it is ported (inside every application that references it, once) at the web rate, but it is not an application of its own and gets no 7R decision. Two applications with the same project name (a legacy and a modernised copy) are told apart by the first folder that differs, e.g. `eShopWCFService (eShopLegacyNTier)`.

## Scenarios

`estimate_effort.py` computes the primary scenario (`assessment.json` scenario) in full and every alternative as totals (`comparisons`).

| Axis | Values |
| --- | --- |
| Hosting (code side) | `modernize` (port to .NET 10 for Linux), `windows-rehost` (lift-and-shift to Windows EC2; only network, identity and configuration changes) |
| Database (code side) | `dual` (SQL Server + PostgreSQL), `postgresql` (PostgreSQL only), `none` |

See [seven-rs.md](seven-rs.md) and [database-assessment.md](database-assessment.md).

## Optional modernizations

`_optional.py` scans for things the code does that a managed AWS service could replace (SMTP → SES/SNS, Kafka → SQS/SNS/EventBridge, local files → S3, in-process cache → ElastiCache, schedulers, authentication, logging, search). Catalog and hours: `scripts/data/optional_modernizations.json`. These are **never in the estimate total**; the report lists them in section 7.3 with their own hours so the client can opt in.

## What changes the estimate

The report states these:
- reviewer dismissals;
- answers to open questions (hidden jobs, server-only integrations);
- the 7R decision (Retain vs Refactor for Web Forms is the largest swing);
- team size;
- the real productivity of the tools on this code base. Measure it on the first wave and recalibrate `ai_assistance.code_factor`.

## Calibration from actuals

Before changing a rate, read [estimation-validation.md](estimation-validation.md): how the model compares with AWS, QSM, COCOMO II, Google and METR evidence and with the real Smartstore port, and the open suggested changes.


After each engagement:
1. Compare actual coding hours per project with the estimate.
2. Adjust in `estimation.json`: `conversion_hours_per_kloc`, `conversion_fixed_hours`, `complexity`, `finding_hours`, `ai_assistance`, `postgres`.
3. Bump `version`.
4. Log the change in [calibration.md](calibration.md).
