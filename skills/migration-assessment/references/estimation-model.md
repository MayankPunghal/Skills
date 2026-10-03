# Estimation model (v3: AI-assisted delivery, scenarios, hours and days)

`estimate_effort.py` is parametric and transparent:
- every number lives in `scripts/data/estimation.json` (`version`);
- the working unit is **hours**, with person-days = hours ÷ 8;
- ranges are low–high, and "likely" = low + 40 % of the range (effort is right-skewed).

## Why AI-assisted rates

Porting .NET Framework code is now largely tool-driven:
- AWS Transform for .NET (AWS cites up to 4× faster);
- GitHub Copilot app modernization;
- coding agents.

Engineers direct, review and fix the output. Testing, cut-over, infrastructure and coordination do not shrink at the same rate. So the model costs those separately instead of as percentages of code effort.

## Formula

For each work package (one per application, one for shared libraries per repository, one for repository-wide items, one estate foundation):

```
code_manual = Σ conversion(project) + Σ remediation(finding)          manual-equivalent hours
code        = code_manual × ai_assistance.code_factor (0.25–0.40)     AI-assisted (set enabled=false for manual)
              (+ fixed hours for Retain / Retire / Repurchase)
qa          = (qa.fixed + KLOC × qa.per_kloc) × (1 + no_tests_extra) × qa_factor (0.6–0.8); KLOC above 50 counts at 40 %
ops         = (scenario ops_per_app per deployable app; scenario foundation once) × ops_factor (0.7–0.85)
total       = (code + qa + ops) × (1 + drift + PM) × (1 + contingency by confidence)

conversion(project)  = fixed_hours[type] + hand-written KLOC × hours_per_kloc[type] + markup KLOC × markup_hours_per_kloc[type]
                       (generated code is excluded; a project shared by several apps is ported once)
remediation(finding) = min(fixed + per × (occurrences − 1), cap)       by the rule's effort key
```

- **Baseline findings** (System.Web usage, Global.asax, legacy project format …) describe work inside the conversion rate. They show in the report but add no hours.
- **Retain apps** only pay for hosting-relevant findings. **Desktop clients** pay for endpoint repointing and packaging only. **Retired apps** pay a decommissioning fixed cost.
- **Databases:**
  - each option gets a per-database base cost;
  - blocker findings add their full (AI-assisted) remediation hours, limited findings half;
  - the recommended option's figure goes into the total.
- **Manual equivalent:** every work package and the total also carry the hours without AI assistance. The report shows both, so the saving is explicit and auditable.
- **Timeline:**
  1. Mobilise and the AWS foundation run in parallel.
  2. Shared libraries.
  3. Waves of 3 applications (Replatform first, then Refactor, then Rehost/Retain; low risk first). A wave's length is its likely hours ÷ (engineers × 5 × 8 × efficiency), and waves overlap by about 30 %.
  4. Database migration alongside the last waves.
  5. Hypercare.

## Reference points (manual-equivalent hours per KLOC)

| Project type | hours/KLOC | Fixed hours | Notes |
| --- | --- | --- | --- |
| Class library | 2–6 | 2–6 | Mostly mechanical |
| ASP.NET MVC 5 / Web API 2 | 8–16 / 6–12 | 8–16 / 6–12 | Startup, DI, auth, filters, routing |
| ASP.NET Web Forms → Blazor/Razor | 24–48 | 16–32 | UI rewrite; AWS Transform gives a starting point |
| WCF → CoreWCF | 8–16 | 8–16 | Contract kept |
| Windows service → Worker | 4–10 | 2–6 | |
| Already ASP.NET Core / .NET 5+ | 0.5–3 | 2–6 | Retarget + package upgrades |

## Confidence and what changes the estimate

- **Application confidence:**
  - High: at most 2 Needs-verification findings and no Blockers;
  - Medium: up to 8 Needs-verification findings;
  - Low: otherwise.
- **What changes the estimate** (the report states these):
  - reviewer dismissals;
  - answers to open questions (hidden jobs, server-only integrations, data volumes);
  - the 7R decision (Retain vs Refactor for Web Forms is the largest swing);
  - team size and freeze windows;
  - the actual productivity of the tools on this code base. Measure it on the first wave and recalibrate `code_factor`.

## Calibration from actuals

After each engagement:
1. Compare actual hours per work package with the estimate.
2. Adjust these settings in `estimation.json`:
   - `conversion_hours_per_kloc` / `conversion_fixed_hours`;
   - `finding_hours`;
   - `ai_assistance`;
   - `qa_hours`;
   - `operations_hours`.
3. Bump `version`.
4. Log the change in [calibration.md](calibration.md).

## Why AI-assisted and manual differ by about 45-60 % (not more)

| Part | Manual | AI-assisted | Why it does not go further |
| --- | --- | --- | --- |
| Code port and remediation | 100 % | 25-40 % | Engineers still direct, review and fix the generated changes, and design the replacements (interop, auth, reporting) |
| QA | 100 % | 60-80 % | Generated tests help, but scenario design, data, UAT and sign-off are human |
| Operations / foundation | 100 % | 70-85 % | IaC is generated, but network, security and cut-over are coordinated with the client |
| Database conversion | 100 % | 35-50 % | DMS Schema Conversion and agents convert most T-SQL; semantics (transactions, collation, dates) need review and testing |
| PM, drift, contingency | % of the above | % of the above | Scale with the work |

Measure the real productivity on the first wave and recalibrate `ai_assistance`.

## Scenarios

`estimate_effort.py` computes the primary scenario (`assessment.json` scenario) in full and every hosting and database alternative as totals (`comparisons`). See [seven-rs.md](seven-rs.md) (hosting) and [database-assessment.md](database-assessment.md) (PostgreSQL / dual).
