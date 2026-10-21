# Estimation model: validation against industry references (2026-10-06)

How `estimation.json` (v4) compares with published benchmarks and one real port of a codebase we also assessed. Read before changing a rate; log any change in [calibration.md](calibration.md).

## Contents

- [Verdict](#verdict)
- [Code conversion rates](#code-conversion-rates)
- [Real port: SmartStoreNET to Smartstore 5](#real-port-smartstorenet-to-smartstore-5)
- [AI-assistance factor](#ai-assistance-factor)
- [Database conversion](#database-conversion)
- [Gaps and suggested changes](#gaps-and-suggested-changes)
- [Sources](#sources)

## Verdict

| Part | Verdict |
| --- | --- |
| Mechanical port rates (class library 1–3, MVC 3–7 h/KLOC) | In line with the one published mechanical baseline (about 1.9 h/KLOC saved by AWS Transform on 143 KLOC) |
| Large code bases | Likely **too low**: the model is linear in KLOC, while COCOMO II and the Smartstore port both show a diseconomy of scale |
| AI-assistance factor 0.30–0.50 | At the **optimistic end**: it matches vendor case studies of mechanical transformation (47–70 % less effort), not independent trials on open-ended work |
| Database object / construct hours | Consistent with the AWS SCT complexity bands |
| Person-day = 8 h | Optimistic: about 6 focused hours a day is the usual planning figure |

## Code conversion rates

- **AWS Transform for .NET** (Caribbean Examinations Council): 143,000 lines ported in under two days, about 270 developer hours saved. That is about 1.9 manual h/KLOC for the mechanical part only.
- Other AWS case studies report the share of effort removed, not the baseline: Experian 47 % productivity gain on 687,600 lines; Grupo Tress 70 % fewer hours on 135,000 lines; Nol Universe 50 % less development effort on 1.5 M lines.
- **QSM** (more than 2,000 IT projects): conversion projects (< 5 % new function) have a median Productivity Index about 1.0 below new development. A modelled 375 FP conversion took more effort (39 vs 34 staff-months) and longer (15.5 vs 10.2 months) than a 500 FP new build. Conversions are not cheap per unit of function.
- **COCOMO II**: effort grows as Size^B with B ≈ 1.10 nominal. A 360 KLOC system costs about (36)^0.10 ≈ 1.4× more per KLOC than a 10 KLOC one. The reuse model prices adapted code by AAF = 0.4·DM + 0.3·CM + 0.3·IM, raised by software-understanding and unfamiliarity terms. That is why a team new to the code pays more.

## Real port: SmartStoreNET to Smartstore 5

The SmartStoreNET sample assessed here (ASP.NET MVC 5, 363 KLOC by our count) was ported by its owners to ASP.NET Core as Smartstore 5. From the GitHub API:
- the repository was created 15 Oct 2020;
- 5.0 beta shipped 29 Mar 2022, and 5.0.0 on 15 Aug 2022;
- three core developers were active for 76–92 of those ~95 weeks.

| | Hours |
| --- | --- |
| Real, all-in (3 devs × 76–92 weeks × 35–40 h) | ≈ 8,000–11,000 |
| Real, porting code only (assume 40–60 % of the above; the rest is testing, new features, v4 maintenance) | ≈ 3,200–6,600 |
| Model, manual likely, code only, no database work | 2,583 |

- The model's likely figure is below the real code-only band, by about 1.3–2.5×.
- The model's upper range reaches into that band.
- Caveats:
  - The original team knew the code, which lowers effort.
  - They also redesigned parts while porting, which raises it.
  - There was no AI assistance in 2020–22.

## AI-assistance factor

| Evidence | Effect |
| --- | --- |
| AWS Transform case studies (vendor) | 47–70 % less effort, up to 4× faster on mechanical porting |
| Google, internal migrations (ICSE SEIP 2025) | ≥ 50 % end-to-end time saved on narrow, repetitive migrations (int32→int64, JUnit3→4, Joda→java.time: about 89 %); reviewer capacity became the bottleneck |
| Amazon Java 8/11→17 upgrades | About 50 developer-days per application down to hours (4,500 developer-years claimed) |
| METR randomised trial (2025), experienced developers on their own large repositories | **19 % slower** with AI tools on open-ended tasks, while believing they were 20 % faster |

Reading: the 0.30–0.50 factor is fair for **mechanical conversion** (project files, API swaps, namespace moves). It is optimistic for **redesign work** (Web Forms UI, WCF contracts, CLR / Service Broker replacements, dual-database data rules), where no study shows large gains.

## Database conversion

- **AWS SCT** rates each action item Simple (< 2 h), Medium (2–6 h) or Significant (> 6 h). Our procedure hours (small 0.75–1.5, medium 2–4.5, large 5–12) and redesign constructs (up to 8–24 h) sit inside those bands.
- **Ora2Pg** (Oracle) prices one unit at about 5 minutes of an expert's time; procedures run 2–24 units. That is lower than ours, as expected: T-SQL conversion has more manual items than Oracle conversion with mature tooling.
- No public benchmark gives "procedures converted per day" for T-SQL to PL/pgSQL. Calibrate from the first wave.

## Gaps and suggested changes

Status (2026-10-06, owner's decision): 1, 2 and 3 **applied** in estimation v5; 4 rejected (a working day stays 8 hours); 5 stands.
1. **Size exponent (diseconomy of scale).** Multiply conversion hours by (repo KLOC / 10)^0.10, with a floor of 1.0. SmartStore would go from about 2,600 to about 3,700 manual h, inside the real band; small apps would not change.
2. **Split the AI factor by work type.**
   - Keep 0.30–0.50 for conversion and mechanical findings.
   - Use about 0.70–1.0 for redesign-level findings and constructs, and for the dual-database abstraction.
3. **Move "likely" towards the upper half** for large or unfamiliar code (for example 50 % of the range instead of 40 %), or tie it to the complexity factor.
4. **Productive hours per day of 6** for person-days and the timeline (or state 8 h days explicitly in the report).
5. **Calibrate from actuals.** The first migrated wave is still the only reliable rate. Record it in calibration.md.

## Sources

- AWS Transform for .NET case studies: aws.amazon.com/transform/net; Thomson Reuters, Nol Universe and Experian case studies (aws.amazon.com/solutions/case-studies).
- QSM, "Why are conversion projects less productive than development?" (qsm.com/blog/2025).
- COCOMO II Model Definition Manual (USC CSE): effort equation, scale factors, reuse model.
- Google, "How is Google using AI for internal code migrations?" (arXiv 2501.06972, ICSE SEIP 2025).
- METR, "Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity" (July 2025).
- Amazon Q Developer code transformation, Java upgrades (Andy Jassy, Aug 2024).
- AWS SCT user guide: assessment report complexity levels.
- Ora2Pg documentation: migration cost assessment.
- GitHub API: smartstore/Smartstore repository creation date, releases, contributor activity.
