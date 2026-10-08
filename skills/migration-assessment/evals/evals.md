# Evaluations for migration-assessment

Run each prompt in a fresh session, first without the skill (baseline), then with it. Record the difference below.

## Contents

- [Triggering and routing](#triggering-and-routing)
- [Output checks](#output-checks)
- [Baseline log](#baseline-log)

## Triggering and routing

### Bare invocation
Prompt: `/migration-assessment`
Should trigger: yes
First file Claude should open: `scripts/context.py` output, not a step
Done looks like: state, recommended NEXT and the step menu are shown; no step starts.

### Plain-language trigger
Prompt: "We have 40 old ASP.NET MVC and WCF repos. What will break if we move them off Windows to AWS, and roughly how long will it take?"
Should trigger: yes
First file Claude should open: `references/setup.md` (prerequisites) via `context.py`
Done looks like: workspace is proposed outside the client repos; the intake questionnaire is asked (goal, OS today, database engine and hosting, AWS managed services, code access) before discovery; no flags are asked for and no answer is filled in by Claude.

### Should not trigger
Prompt: "Upgrade this one console project from .NET 6 to .NET 8 and fix the build."
Should trigger: no
Done looks like: skill is not loaded; normal coding help is given.

### Lift-and-shift intake
Prompt: "The client wants to move 30 Windows and Linux servers from Proxmox to EC2 as they are, databases on EC2. Assess the repos."
Should trigger: yes
First file Claude should open: `references/intake.md`
Done looks like: the answers the user already gave (goal lift-and-shift, db_hosting ec2, platform Proxmox) are confirmed in one line, not re-asked; the rest are asked; `intake.py --answers` records them; `context.py` shows ASSESSMENT TYPE lift-and-shift; the report uses the lift-and-shift template (landing on AWS first, Linux/.NET work under Future options).

### Sample access extrapolation
Prompt: "We only have 12 of the client's 80 repos. Estimate the whole estate." (workspace with an estimate and an estate list)
Should trigger: yes
First file Claude should open: `references/intake.md#sample-access-estimating-the-rest-of-the-estate`
Done looks like: `extrapolate_estate.py` runs after `estimate_effort.py`; unshared repos are estimated per kind with Low confidence where no sample of that kind exists; the report shows the whole-estate section (7.3 or 8.9) and `assessment/report/estate-extrapolation.csv` is written.

## Output checks

### Effort is coding-only
Prompt: "Estimate the effort for this estate" (workspace with findings and decisions present)
Should trigger: yes
First file Claude should open: `references/estimation-model.md`
Done looks like: `estimate_effort.py` runs; the report shows coding hours with KLOC and hours per KLOC; no QA, DevOps, PM or contingency lines; optional modernizations listed separately and excluded from the total.

### No database hosting advice
Prompt: "Which AWS database should we use, RDS or Babelfish?"
Should trigger: yes
Done looks like: the skill explains that hosting is out of scope and that only dual SQL Server + PostgreSQL or PostgreSQL-only code conversion is assessed.

### Secrets stay out
Prompt: "Show me the connection string the app uses."
Done looks like: key names and file:line only; no password values in chat, report or exports; `verify_report.py` gate "no secret values" passes.

### Run-time wiring in the estimate
Prompt: "How hard is the DI / composition-root part of this port, and does it change the estimate?" (C# workspace after map-code-graph)
Should trigger: yes
Done looks like: answered from report 4.2 "Run-time wiring" and `analysis.json` `wiring` (containers, registrations per host and lifetime, run-time-bound calls per project); legacy containers (Unity, StructureMap, Ninject) and captive dependencies appear as `di-wiring` findings with hours; the complexity factor's `complexity_why` names the run-time-bound calls/KLOC where it applied.

### Package versions and Linux
Prompt: "Which packages must change for .NET 10 on Linux, and can we keep the versions we have?"
Should trigger: yes
Done looks like: `scan_repo.py --online`; packages.csv / appendix give keep / upgrade (lowest safe version) / replace per package with the reason and risks; Windows-only packages found from their files (runtimes/win-* only) as well as the package map; System.Drawing, Http.sys, Windows services, named wait handles, SystemEvents, shell verbs, GAC references, .reg files and fonts appear as Linux-readiness findings.

### Licence-changed packages
Prompt: "Any licensing surprises in our NuGet packages?"
Should trigger: yes
Done looks like: with `scan_repo.py --online`, any package whose licence became more restrictive (open-source SPDX id to a custom licence file, vendor licence page, copyleft or source-available licence) is a licence finding: Medium when the version in use is already under the new licence, Low when only an upgrade crosses it, naming the last version under the old licence. Nothing is keyed on package names (tested: AutoMapper, MediatR, MassTransit, FluentAssertions, SixLabors.ImageSharp found from metadata alone).

### Report statements stay true
Prompt: "Rescan and rebuild the report; can I trust every number in it?"
Should trigger: yes
Done looks like: every number and finding reference in the narratives is a `{{v:}}` / `{{f:}}` tag (list items picked by name, e.g. `applications[FulfillmentHub.Web]`), so `verify_report.py` passes "finding references and values current" after a rescan; test projects are listed in the shared-object section but not counted as coupling or as a second writer; `MOD-ON-WINDOWS` is raised only for web.config, an MSDeploy / IIS / win-x64 publish profile or a Windows container image, never for `appsettings.json` or a Linux Dockerfile.

## Baseline log

| Date | Model | With skill? | Result |
| --- | --- | --- | --- |
| 2026-10-05 | Sonnet 5.5 | yes | Pipeline run on the FulfillmentHub testbed: all 8 gates PASS, 203 h likely (was 849 h before v4) |
| 2026-10-06 | Opus 5.5 | yes | FulfillmentHub trust audit: narratives rewritten with tags, 10/10 gates PASS, 387 h likely; test-project coupling and MOD-ON-WINDOWS false positives removed |
| 2026-10-06 | Opus 5.5 | yes | HTML report accessibility pass: keyboard access to rows / sort headers / tiles, AA contrast on labels, 44px touch targets, "On this page" links; impeccable detector 0 findings; 10/10 gates PASS |
