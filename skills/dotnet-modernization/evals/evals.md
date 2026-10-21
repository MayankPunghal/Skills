# Evaluations for dotnet-modernization

Run each prompt in a fresh session, first without the skill (baseline), then with it. Record the difference in the baseline log.

## Contents

- [Triggering and routing](#triggering-and-routing)
- [Behaviour checks](#behaviour-checks)
- [Script checks](#script-checks)
- [Baseline log](#baseline-log)

## Triggering and routing

### Bare invocation
Prompt: `/dotnet-modernization`
Should trigger: yes
Done looks like: the state from `.modernization/run-log.jsonl` (or "no run yet"), the next step and the command table; nothing starts.

### Package from a plan
Prompt: "Here is the execution plan from the assessment. Modernize the OrderService package." (workspace with `assessment/execution-plan.json`, a copy of the repository)
Should trigger: yes
First file Claude should open: `reference/workflow.md`
Done looks like: engine and database tool read from the plan and confirmed in one line; a branch on the copy; `verify.py baseline` before any change; one engine only; the run log has an entry per step.

### After AWS Transform
Prompt: "AWS Transform finished porting this solution. Clean up whatever it left so it runs on Linux."
Should trigger: yes
Done looks like: no second engine is run; `residue_scan.py` and `linux_readiness.py` run first; work proceeds one playbook per commit, including the Transform gaps (CallContext, container, `.ashx`/`.asmx`); the Next Steps / Linux readiness CSV items are folded in.

### Already modern
Prompt: "This API is already on .NET 8. Is it ready for Linux containers on ECS?"
Should trigger: yes
Done looks like: no porting engine; `linux_readiness.py` on the folder; fixes by playbook; `verify.py target --linux-only`.

### Should not trigger
Prompt: "Assess these 40 repositories and estimate how long moving to AWS would take."
Should trigger: no (migration-assessment does this)
Done looks like: the assessment skill is used instead.

### Should not trigger (small)
Prompt: "Fix this one nullable warning in my .NET 8 project."
Should trigger: no

## Behaviour checks

| Check | Pass when |
|---|---|
| One engine | Never runs DevTx and AWS Transform on the same project; asks when the plan names none |
| Libraries first | A shared library with no project references is ported before the apps using it; multi-target or adapters while .NET Framework callers remain |
| HttpContext in libraries | Prefers pass-the-values or System.Web adapters over converting every use in every caller |
| Web Forms | Page by page with goldens; retire or rewrite is put to the user, never assumed |
| Database | Code follows the DB contract; no database objects authored; refcursor count matches result sets; error numbers mapped to SQLSTATE |
| Secrets | No secret value appears in chat, commits, reports or the image |
| Decisions | Stops for: retiring a feature, contract change for external callers, new sign-in, cross-database queries, desktop apps |
| Gates | "Done" only after `verify.py target` passes or every remaining hit has a written waiver |
| HTML twin | Every Markdown output has its `.html` |

## Script checks

| Script | Fixture | Expected |
|---|---|---|
| `linux_readiness.py` | A clean .NET 10 web app with a Dockerfile using `USER $APP_UID` and a `.gitattributes` | PASS, no blocking hits, no hits for `LNX-CTR-USER-MISSING` or `LNX-CI-GITATTRIBUTES` |
| `linux_readiness.py` | A .NET Framework Web Forms app | FAIL with System.Web, legacy csproj, drive-letter paths; secret values masked (`password=<masked>`) |
| `linux_readiness.py` | `Site.css` on disk, `site.css` referenced | `LNX-FS-CASE-STATIC-URL` or `LNX-FS-CASE-LITERAL` hit |
| `residue_scan.py --gate` | The same Web Forms app before the port | Exit 1; hits grouped by playbook with DevTx KB files |
| `verify.py target --dockerfile Dockerfile` | The clean app | All gates pass, container answers `/health` |
| `parity.py replay` | Goldens with one changed field | The difference is reported unless masked |

## Baseline log

| Date | Prompt | Without the skill | With the skill |
|---|---|---|---|
| 2026-10-21 | Script checks above (vsample .NET 10 app, a legacy Web Forms repository) | — | `linux_readiness.py`: vsample PASS (2 warn: no USER, no .gitattributes, both true); legacy repo FAIL, 28 checks hit, 0 unmasked secrets. `verify.py` all gates on vsample (earlier run). |
