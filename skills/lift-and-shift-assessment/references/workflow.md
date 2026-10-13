# Workflow details

Run from the workspace folder. `python` is `py` on Windows. Every script prints what it did; none edits the client repositories.

## Contents

- [1 to 3: workspace and discovery](#1-to-3-workspace-and-discovery)
- [4: intake](#4-intake)
- [5: branch check, scan](#5-branch-check-and-scan)
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

## 5: branch check and scan

- `branch_evidence.py [--repos a,b] [--months 12]` (read-only GET and HEAD requests; VPN; read token in the environment variable named by `assessment.json` -> `gitlab.token_env`, never printed). Writes `assessment/branches/evidence.json` and `summary.md`: per repository the default and checked-out branch, the branches that received merged requests in the last N months, protected branches, newest tags (release markers), CI / Jenkins files on the key branches and the newest branch's distance from the suggested one. Reading the result: a protected branch that receives most merged requests and carries the release tags is the live line; `master` is often years stale; a newest branch that never received a merged request is unmerged work. Confirm each choice with the user. Pipelines that exist only on the Jenkins servers leave no files here, so "no CI files" means exactly that.
- If the chosen branch differs from the checkout, clone it single-branch and shallow into a scratch folder that keeps the group layout (`<scratch>/repos/<group>/<repo>`), never switch the user's clones, and put the new folders in a copy of `assessment.json` (`estate_roots`) in a new workspace. Compare totals with the first run (the estimate moved about 2% in the first re-run).
- Record why each branch was chosen in `assessment.json` -> `branch_notes` (key: folder name in lower case). `build_doc.py` writes the workbook sheet Branches (branch assessed, last commit date, why) and one sentence in 1.1.


- `scan_repo.py --all [--offline]` reads each repository: line rules for what changes on AWS, packages, network endpoints, scheduled jobs.
- `map_infra.py --servers <DevOps list.xlsx> --all` imports the server list (names, environments, operating systems, hypervisors, installed applications) first and maps servers and services each project connects to, the config settings holding addresses, paths and credentials, and the network destinations.
- Only the findings that serve a lift-and-shift matter here (the rule ids named in the intake `when_found` lists and the counts in solutions.py). Package-health and security findings are not part of this assessment.

## 6: solutions and third party

- After both, `address_roles.py` writes `assessment/infra/address_roles.json`: for every internal address its type, likely role, setting names and ports (never values), and how many servers of that kind the DevOps list has; public IPs found in the scans are included with their role (proxy, allow-listed address, metrics server, supplier endpoint). Section 5.3 and the workbook sheet Connections show type and likely role, without the confidence.

- `solutions.py` builds `assessment/solutions/index.json`: per solution the projects, deployables, workloads (solution x environment), environment variables read in code, config files with hard-coded values, distinct internal endpoints, projects to retarget.
- `third_party.py` writes `assessment/solutions/third_party.json`: licensed components (vendor list and NuGet licence text), integrations (SDK packages, vendor-named variables, external hosts called from server code) and server-to-server connections. An item needs a re-key when there is evidence of a key; otherwise it only needs outbound access and adds no hours.

## 7: build check

- `build_check.py` reads the solution and project files: missing project files, reference DLLs not in the repository, installer projects, web build targets. Status READY / PREREQUISITES / BLOCKED.
- `stage_library.py --library <shared library checkout> [--prefer net472] [--apply]`: lists every "reference DLL not found" file by name in the library checkout and says where it is now; with `--apply` builds a staging folder (junctions plus copies under the old paths; the checkout is untouched), writes `aliases.json` and sets `assessment.json` -> `library_stage`. `build_check.py` then treats those references as found and writes the aliased path into the prerequisites. A DLL found only by name can be another version: the build shows it compiles, not that it is the production version. A file found nowhere stays missing.
- A failed build gets a plain reason, what is needed and who provides it (`_buildwhy.py`): missing DLLs or project files (the client), output path on a fixed drive or Office interop (build agent), a project reading another repository's bin folder (pipeline build order).
- `build_check.py --toolchain` shows MSBuild, dotnet and targeting packs on this machine.
- `build_check.py --run --approve-downloads [--solution ID]` copies the repository to `assessment/build/work/<repo>/` and runs `msbuild -restore -t:Build -p:Configuration=Release` on the copy. `--approve-downloads` covers every download the build needs, so it is not asked again: NuGet packages, nuget.exe (into the tool cache when it is not on PATH) and, for .NET Framework 4.0 to 4.6.2 solutions (also Web Site projects, which need 4.0), the `Microsoft.NETFramework.ReferenceAssemblies.*` NuGet packages that stand in for the targeting packs current Visual Studio no longer ships; they live in `%LOCALAPPDATA%\lift-and-shift-assessment\netfx-packs` and are passed as `TargetFrameworkRootPath` (delete the folder to remove them). A solution that still cannot find a framework is NOT RUN, never FAIL. The real build must pass before artifacts are produced. If MSBuild is missing the result is NOT RUN and nothing is installed.
- The copies under `assessment/build/work/` can be deleted by the user once the build results are recorded.

## 8 to 10: tokenised config, estimate, document

- `config_template.py` (only with CI/CD + Secrets Manager): tokenised copies of the config files, the CI variable list and `render-config.ps1`. Values are never printed.
- `estimate_hours.py` applies `scripts/data/hours.json` to the counts; only the selected work items. Output `assessment/estimate.json`.
- `build_doc.py` writes the single .docx (a clone of the reference layout, see [document-layout.md](document-layout.md)) and the workbook; `verify_doc.py` checks them.

## When the client returns the mapping workbook

`check_mapping.py --workbook <filled xlsx>` compares the client's answers with the DevOps server list, the code and the inferred address roles, and writes `assessment/infra/mapping-check.md`: unknown server names (with the closest names), a server under the wrong environment, a .NET Framework app on a Linux server, invalid or duplicated addresses, an address the code uses as one thing on a server whose name says another (ROLE CONTRADICTION) or the same thing (ROLE CONFIRMED), and the private IPs still not mapped. These are questions back to the client or DevOps, never corrections. Confirmed facts then go in through the intake (`intake.py --solution ID --environments ...`) and the address roles can be shown as confirmed.

## Revising

Everything can change until the user says final. After a change in answers or rates: rerun the steps downstream of it (`context.py` says which), `build_doc.py`, `verify_doc.py`. Each build increments the draft number in the document control table.
