# Workflow details

Run from the workspace folder. `python` is `py` on Windows. Every script prints what it did; none edits the client repositories.

## Contents

- [1 to 3: workspace and discovery](#1-to-3-workspace-and-discovery)
- [4: intake](#4-intake)
- [5: scan](#5-scan)
- [6: solutions and third party](#6-solutions-and-third-party)
- [7: build check](#7-build-check)
- [8 to 10: tokenised config, estimate, document](#8-to-10-tokenised-config-estimate-document)
- [Revising](#revising)

## 1 to 3: workspace and discovery

- `context.py` prints the state and the NEXT command; run it first in every session.
- `setup_assessment.py --client "<name>" --roots <folders with repositories> [--prepared-by] [--hosting] [--offline]`. Online package lookups (api.nuget.org) are the default and give licence and deprecation data; `--offline` keeps package ids on this machine and the vendor list in `scripts/data/commercial_packages.json` is used alone.
- `discover_estate.py` lists repositories, solutions, projects, applications. Repositories with no .NET project are out of scope and listed as such.

## 4: intake

`intake.py --questions` prints the questionnaire. Ask with the multiple-choice tool, then `intake.py --answers '<json>'`. See [intake.md](intake.md).

## 5: scan

- `scan_repo.py --all [--offline]` reads each repository: line rules for what changes on AWS, packages, network endpoints, scheduled jobs.
- `map_infra.py --all` maps servers and services each project connects to, the config settings holding addresses, paths and credentials, and the network destinations.
- Only the findings that serve a lift-and-shift matter here (the rule ids named in the intake `when_found` lists and the counts in solutions.py). Package-health and security findings are not part of this assessment.

## 6: solutions and third party

- `solutions.py` builds `assessment/solutions/index.json`: per solution the projects, deployables, workloads (deployable x environment), environment variables read in code, config files with hard-coded values, distinct internal endpoints, projects to retarget.
- `third_party.py` writes `assessment/solutions/third_party.json`: licensed components (vendor list and NuGet licence text), integrations (SDK packages, vendor-named variables, external hosts called from server code) and server-to-server connections. An item needs a re-key when there is evidence of a key; otherwise it only needs outbound access and adds no hours.

## 7: build check

- `build_check.py` reads the solution and project files: missing project files, reference DLLs not in the repository, installer projects, web build targets. Status READY / PREREQUISITES / BLOCKED.
- `build_check.py --toolchain` shows MSBuild, dotnet and targeting packs on this machine.
- `build_check.py --run --approve-downloads [--solution ID]` copies the repository to `assessment/build/work/<repo>/` and runs `msbuild -restore -t:Build -p:Configuration=Release` on the copy. Restore downloads NuGet packages, so the agent asks first. The real build must pass before artifacts are produced. If MSBuild is missing the result is NOT RUN and nothing is installed.
- The copies under `assessment/build/work/` can be deleted by the user once the build results are recorded.

## 8 to 10: tokenised config, estimate, document

- `config_template.py` (only with CI/CD + Secrets Manager): tokenised copies of the config files, the CI variable list and `render-config.ps1`. Values are never printed.
- `estimate_hours.py` applies `scripts/data/hours.json` to the counts; only the selected work items. Output `assessment/estimate.json`.
- `build_doc.py` writes the single .docx (a clone of the reference layout, see [document-layout.md](document-layout.md)) and the workbook; `verify_doc.py` checks them.

## Revising

Everything can change until the user says final. After a change in answers or rates: rerun the steps downstream of it (`context.py` says which), `build_doc.py`, `verify_doc.py`. Each build increments the draft number in the document control table.
