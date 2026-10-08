# lift-and-shift-assessment

A Claude Code skill that prices an AWS lift-and-shift (Windows to Windows, EC2, no C# change) of a .NET estate in **developer working hours**, solution by solution, and writes it up as **one Word document** plus a **small workbook**.

It is the narrow sibling of `migration-assessment`: that skill assesses a real migration (Linux, native AWS services, modernisation); this one covers only the dev team's work when the applications move as they are.

## What it does

- Inventories solutions, projects, deployables and workloads (deployable x environment).
- Counts what the dev team must handle: environment variables and secrets, config files with hard-coded values, internal addresses, third-party keys and licensed components, server-to-server connections.
- Checks that each solution builds (static readiness; a real MSBuild run on a copy after approval).
- Prices only the work items the user selects: build check + artifacts, CI/CD + Secrets Manager, framework retarget, validation + cutover support.
- Writes one DRAFT `.docx` for the whole project (solutions as table rows) and a workbook with the project-level detail.

Nothing is final until the user says so; every rate can be changed in `scripts/data/hours.json`.

## Use

Open Claude Code in an empty folder outside the client repositories and say: *"Assess the lift-and-shift of the .NET code in D:\clients\acme\repos"*, or `/lift-and-shift-assessment`.

The deterministic part runs from the command line too:

```bash
python scripts/setup_assessment.py --client "Acme" --roots D:/clients/acme/repos
python scripts/discover_estate.py
python scripts/intake.py --questions          # the agent asks these, then: intake.py --answers '<json>'
python scripts/scan_repo.py --all
python scripts/map_infra.py --all
python scripts/solutions.py
python scripts/third_party.py
python scripts/build_check.py
python scripts/estimate_hours.py
python scripts/build_doc.py
python scripts/verify_doc.py
```

Requires Python 3.10+ (standard library only). Package licence lookups use api.nuget.org unless `--offline`.

## Outputs

`assessment/documents/<client>-lift-and-shift-assessment.docx` and `.xlsx`; `assessment/estimate.json`; `assessment/solutions/`; `assessment/build/`.

## Hours

Rates marked `sample` reproduce the manager's reference estimate (72-108 h) from counts measured in the reference code; rates marked `inferred` are the skill's own. See `references/estimate-model.md`.
