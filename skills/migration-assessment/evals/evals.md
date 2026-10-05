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
Done looks like: workspace is proposed outside the client repos; scenario question covers code side (modernize or windows-rehost) and database code (dual, PostgreSQL only, none).

### Should not trigger
Prompt: "Upgrade this one console project from .NET 6 to .NET 8 and fix the build."
Should trigger: no
Done looks like: skill is not loaded; normal coding help is given.

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

## Baseline log

| Date | Model | With skill? | Result |
| --- | --- | --- | --- |
| 2026-10-05 | Sonnet 5.5 | yes | Pipeline run on the FulfillmentHub testbed: all 8 gates PASS, 203 h likely (was 849 h before v4) |
