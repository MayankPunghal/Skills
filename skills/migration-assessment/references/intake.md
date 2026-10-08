# Intake questionnaire

The first step of every new assessment. The answers decide what kind of assessment this is, so the user never passes flags such as `--target-hosting`. `context.py` shows `NEXT: intake questionnaire` until the answers are recorded.

## Contents

- [How to run it](#how-to-run-it)
- [The questions](#the-questions)
- [What each answer changes](#what-each-answer-changes)
- [Assessment types](#assessment-types)
- [Sample access: estimating the rest of the estate](#sample-access-estimating-the-rest-of-the-estate)

## How to run it

1. **Read the questions.** Run `python <skill>/scripts/intake.py --questions`.
2. **Ask them in plain words.** Use the multiple-choice tool when one is available; options carry a one-line explanation. Skip a question whose `when` condition does not hold. Do not explain the skill's internals (scenarios, keep_categories): ask about the client's situation.
3. **Never fill in an answer yourself.**
   - If the user does not know, record `"unknown"`; it becomes an open question in the report.
   - Answers the user already gave earlier in the conversation count. Confirm them in one line instead of asking again.
4. **Record the answers.** Run `python <skill>/scripts/intake.py --answers '<json>'`. It accepts a JSON string or a file path, validates option values, saves the answers to `assessment.json` and prints what was set.
5. **Change an answer.** Rerun step 4 with the full set. Then rerun `estimate_effort.py` and the report builders.

## The questions

The questions live in `scripts/data/intake.json`; edit wording there, not in code.

| Id | Question (short) | Answers |
| --- | --- | --- |
| `goal` | What does the client want from the move? | `lift-and-shift` (move as it is), `modernize`, `compare` (not decided) |
| `os_today` | Server operating systems today | `windows`, `linux`, `both`, `unknown` |
| `platform` | Where the servers run and who manages them | free text (e.g. "Proxmox, vendor-managed") |
| `db_engine` | What happens to the database engine | `keep`, `postgresql`, `dual`, `later` |
| `db_hosting` | Where the databases run on AWS | `ec2`, `rds`, `undecided`, `none` |
| `aws_native` | Replace servers with AWS managed services | `no`, `later` (future options, not costed), `now` (costed) |
| `code_access` | How much code we can see | `all`, `sample` |
| `estate_total` | Repositories in the whole estate (only for `sample`) | number |
| `estate_list` | Path to a list of all repositories (only for `sample`) | path to `.csv`, `.json` or `.xlsx` |
| `compliance` | Compliance rules or data-location limits (optional) | free text |
| `team` | Engineers and start date (optional) | free text such as "3 engineers from 2026-11-02" |

## What each answer changes

| Answer | Sets in `assessment.json` | Effect |
| --- | --- | --- |
| `goal` | `assessment_type`, `scenario.hosting` (`lift-and-shift` or `modernize`) | Report template and HTML layout, the cost scope, the headline and key risks |
| `db_engine` | `scenario.database` (`keep` and `later` become `none`) | Database code cost. The report always compares every database option |
| `db_hosting` | `scenario.db_hosting` | Database narrative: on EC2, SQL Server features that RDS lacks keep working; on RDS they are flagged |
| `platform` | `current_hosting` | Report header and the hypervisor section |
| `aws_native` | `intake.aws_native` | `later`: section "Future options". `now`: the optional AWS-service hours are added to the estimate total |
| `code_access` = `sample` | `intake.estate_total`, `intake.estate_list` | `context.py` asks for `extrapolate_estate.py` after the estimate |
| `compliance` | `compliance` | Security findings and questions |
| `team` | `scenario.engineers`, `scenario.start_date` | Timeline and sprint plan |

## Assessment types

| Type | Who it is for | What the report focuses on | What is costed |
| --- | --- | --- | --- |
| `lift-and-shift` | The client moves the same servers to EC2 (Windows to Windows, Linux to Linux) without changing code | Landing on AWS: IP allow-lists, DNS, SMTP port 25, file shares, identity / domain, licences, broadcast and multicast, co-located services, network allow-list, scheduled jobs. Linux and .NET findings are summarised in "Future options" | Fixed repoint work per application, plus findings in the `lift-and-shift` scenario's `keep_categories` and `keep_rules` (`estimation.json`) |
| `modernize` | The client wants the code on Linux / modern .NET | Everything (the original report) | Per-application 7R decisions |
| `compare` | Not decided | The modernization report, with lift-and-shift costed beside it in the scenario comparison | Modernization; lift-and-shift shown for comparison |

`windows-rehost` is still accepted by `setup_assessment.py --target-hosting` for older workspaces. `lift-and-shift` supersedes it because it also covers Linux servers and the AWS landing checks.

Lift-and-shift needs the same scan, review and classification as any assessment, because 7R decisions feed the estimate. In the draft, `classify_apps.py` puts every server application on Rehost to EC2 with the same OS, and keeps the modernization path as `modernization_r7` / `modernization_target` for the "Future options" section. Desktop applications and databases keep their own paths. The draft does not change the path on its own: when a Blocker stops the move or the client will retire an application, the reviewer records that in `assessment/decisions.json`, and reviewer decisions always win.

Unanswered required questions (left empty or `"unknown"`) appear in the report's open questions as "Engagement scope".

## Sample access: estimating the rest of the estate

When only some repositories are shared:

1. **Assess the shared repositories fully** (steps 1–6).
2. **Estimate the rest.** `extrapolate_estate.py` reads the estate list and estimates every other repository from the assessed ones of the same kind:
   - **Kinds:** web on .NET Framework, web on modern .NET, service / worker, console / batch, desktop, library.
   - **With a known size:** hours per KLOC of that kind.
   - **Without a size:** the hours range of that kind.
   - **With no assessed repository of that kind:** the whole-sample range, widened, marked Low confidence.
   - **Counted in the estate size but not listed:** the widened whole-sample range per repository.
3. **The report shows it.** The result is in report section 7.3 (lift-and-shift) or 8.9 (modernize), and in `assessment/report/estate-extrapolation.csv`.

To improve the estimate, ask the client to share at least one repository of each kind that appears in the list.
