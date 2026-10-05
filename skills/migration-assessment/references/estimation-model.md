# Estimation model (v4: coding effort only)

`estimate_effort.py` is parametric and transparent:
- every number lives in `scripts/data/estimation.json` (`version`);
- the working unit is **hours**, with person-days = hours ÷ 8;
- ranges are low–high, and "likely" = low + 40 % of the range (effort is right-skewed);
- **scope is developer hours for code and SQL only.** QA, DevOps, infrastructure, project management, parallel-development drift and contingency are not estimated.

## Contents

- [Why the numbers are lower than before](#why-the-numbers-are-lower-than-before)
- [Formula](#formula)
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
conversion(project) = (fixed[type] + hand-written KLOC × rate[type] + markup KLOC × markup_rate[type]) × complexity_factor
remediation(finding) = min(fixed + per × (occurrences − 1), cap)          by the rule's effort key
code_manual = Σ conversion + Σ remediation
code        = code_manual × ai_assistance.code_factor (0.30–0.50)         set enabled=false for manual-only
database    = Σ object, construct and data-access hours × db_factor (0.35–0.55)   only in a database scenario
```

- Generated code is excluded; a project shared by several apps is ported once.
- **Baseline findings** (System.Web usage, Global.asax, legacy project format …) describe work inside the conversion rate. They show in the report but add no hours.
- **Retain, Retire, Repurchase and desktop clients** pay small fixed code costs (`other_r_hours`): repointing connection strings and endpoints, integration code.
- **Manual equivalent:** every total also carries the hours without AI assistance, so the saving is explicit and auditable.
- **Timeline:** coding only. Shared libraries first, then waves of 3 applications (low risk first) with 30 % overlap, database code in parallel with the last waves. Wave length = likely hours ÷ (engineers × 5 × 8 × efficiency).

## Complexity factor

Multiplier on a project's conversion hours (findings already count the hard parts), computed by `_complexity.py` from the source:

| Signal | Effect |
| --- | --- |
| Decision density (branches, loops, `case`, `catch`, `&&`/`||` per KLOC): ≤ 40 / ≤ 90 / ≤ 150 / above | 0.85 / 1.0 / 1.2 / 1.4 |
| Fan-in: three or more projects depend on it | +0.10 |
| Each file over 800 lines | +0.05 (capped at +0.20) |
| Projects under 0.3 KLOC | not scaled (density of a few lines is noise) |

The result is clamped to 0.8–1.6.

## Reference points

Manual-equivalent hours per KLOC of hand-written code (`conversion_hours_per_kloc`):

| Project type | Hours/KLOC | Fixed hours |
| --- | --- | --- |
| Class library | 1–3 | 1–3 |
| Console | 1.5–4 | 1–3 |
| Test project | 0.5–1.5 | 0.5–1.5 |
| ASP.NET MVC 5 | 3–7 | 4–8 |
| ASP.NET Web API 2 | 2.5–6 | 3–6 |
| ASP.NET Web Forms → Razor/Blazor | 14–28 | 8–16 |
| WCF → CoreWCF | 4–9 | 4–8 |
| Windows service → Worker | 2–5 | 1–3 |
| Already ASP.NET Core / .NET 5+ | 0.3–1.2 | 1–3 |

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

After each engagement:
1. Compare actual coding hours per project with the estimate.
2. Adjust in `estimation.json`: `conversion_hours_per_kloc`, `conversion_fixed_hours`, `complexity`, `finding_hours`, `ai_assistance`, `postgres`.
3. Bump `version`.
4. Log the change in [calibration.md](calibration.md).
