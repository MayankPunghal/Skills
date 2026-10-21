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
- **No clones yet (2b).** `setup_assessment.py --gitlab-url <url> --gitlab-token-env <NAME>` records the host and the NAME of the variable holding a read-only token (`_common.gitlab_token` also reads the Windows user environment, so a `setx` made after the session started works). `gitlab_projects.py [--exclude-groups a,b] [--exclude-name-pattern REGEX] [--active-months 12] [--include-personal] [--include-archived]` lists every project the token sees (GET only) with languages and a .NET flag, and writes `assessment/gitlab/projects.json` and `assessment/documents/<client>-gitlab-projects.xlsx` (the list to share with the client, with a Source line that states every filter). `clone_repos.py --dest <folder outside the workspace> [--only-dotnet] [--projects a,b] [--branch project=branch] [--depth 1] [--set-roots]` makes shallow clones in `<dest>/<group>/<repo>`: the token travels only in the child process environment, the push URL is disabled, half-finished clones are redone, and `_clone-report.json` lists the result. `--branch` is also the way to re-clone a chosen branch (step 5). Projects with no .NET code stay out of scope and are named as such in the document; nothing is moved or deleted.
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
- A failed build is retried after workarounds in the copy (`_buildfix.py`; the client repository is never changed): a recreated `Properties\AssemblyInfo.cs` stub, a project listed in the .sln but missing removed from the solution, a placeholder for a missing content file, a `DocumentationFile` on a fixed drive pointed at `bin\`, the property `Deterministic=false` for a wildcard assembly version, another repository's `bin\Debug` output copied from its build copy (solutions that need it are built last), and an Office COM reference replaced by the NuGet primary interop assembly. Each is recorded in `real.workarounds`. A solution that passes only with workarounds is a contingent pass: sheet Build says `PASS with workaround` and its column "Missing or different, and what we did" lists what was missing and what was done. Anything else stays FAIL.
- The copies go to `assessment/build/work/`, except when the workspace path is long (over 60 characters on Windows): MSBuild tools such as SGEN still fail on paths over 260 characters, so the copies then go to `%LOCALAPPDATA%/lsa/<id>`. `setup_assessment.py --build-work-dir <folder>` overrides both; `build/index.json` -> `work_dir` records the folder used. The copies can be deleted by the user once the build results are recorded.

## 8 to 10: tokenised config, estimate, document

- `config_template.py` (only with CI/CD + Secrets Manager): tokenised copies of the config files, the CI variable list and `render-config.ps1`. Values are never printed.
- `estimate_hours.py` applies `scripts/data/hours.json` to the counts; only the selected work items. Output `assessment/estimate.json`.
- `build_doc.py` writes the single .docx (a clone of the reference layout, see [document-layout.md](document-layout.md)) and the workbook; `verify_doc.py` checks them.

## 10b: the companion deliverables

Run after `build_doc.py` (they read the draft number it writes in `assessment/documents/meta.json`); each writes a `.md` and an `.html` twin, in the company look when `docx_template` is set (`_mdhtml.py --brand` renders any other Markdown the same way).

- `build_mapping_sheet.py [--out PATH]` writes `<Client>-Application-Server-Mapping.xlsx`: one row per solution with what the code shows (repository, deployables, .NET version, type), one `<Environment> server(s)` column per environment in the server list (else the intake environments), the Servers sheet (IP column pre-filled only when the list has it) and an Other projects sheet. Server columns are never pre-filled. `check_mapping.py` reads exactly these headers.
- `build_open_questions.py [--out DIR]` writes `<client>-open-questions.md` (every open item: what it changes, who answers it, the evidence), `-open-questions-short.md` and `-questions-for-client-email.md` from the intake, the build, third-party, address and mapping results. Items answered on a call (`intake.py --client-update`) show as closed. Extra items the user adds: `assessment.json` -> `open_questions_extra` (`question`, `why`, `who`, `status`).
- `build_estimate_explainer.py [--out DIR]` writes `<client>-effort-estimate-explained.md`: every estimate line with its count, rate, basis (sample or inferred) and formula, the per-solution inputs, what one more environment adds and how to change a rate. It checks that its lines add up to `estimate.json` and keeps `estimate-history.json` for the "changes since the previous draft" section.

## Recording what was said on a call

- `intake.py --client-update "<topic>" "<answer>" "<effect on this plan>"` (the 1.1 table and sheet ClientAnswers; the same topic replaces its row; `--remove-client-update <topic>`).
- `intake.py --decision "<text>" --source "<who, date>"` appends to `assessment/documents/decision-log.md`.
- `intake.py --release-step "<step>" "<what happens>"` (in order; `--clear-release-steps`) for how releases are built and deployed today (section 7, sheet ReleaseToday).
- `intake.py --branch-note <repo> "<why>"` for the branch chosen per repository.
- `setup_assessment.py --workbook-url <link>` after the workbook is uploaded, then `build_doc.py`.

## When the client returns the mapping workbook

`check_mapping.py --workbook <filled xlsx>` compares the client's answers with the DevOps server list, the code and the inferred address roles, and writes `assessment/infra/mapping-check.md`: unknown server names (with the closest names), a server under the wrong environment, a .NET Framework app on a Linux server, invalid or duplicated addresses, an address the code uses as one thing on a server whose name says another (ROLE CONTRADICTION) or the same thing (ROLE CONFIRMED), and the private IPs still not mapped. These are questions back to the client or DevOps, never corrections. Confirmed facts then go in through the intake (`intake.py --solution ID --environments ...`) and the address roles can be shown as confirmed.

## Revising

Everything can change until the user says final. After a change in answers or rates: rerun the steps downstream of it (`context.py` says which), `build_doc.py`, `verify_doc.py`. Each build increments the draft number in the document control table.

- **Company-branded document.** Set `docx_template` with `setup_assessment.py --docx-template <file>` to a finished company .docx (cover, welcome page, table of contents, header, footer, fonts). `build_doc.py` then writes the document in that look (`_docx_brand.py`): the cover gets the version, date and author, the table of contents is generated (page numbers are read from Word when it is installed; otherwise Word updates the table when the file is opened), headings become a green "Section N" line plus the title, and tables get the template's green header. Keep the template out of the repository: it holds logos and fonts. Without `docx_template` the plain writer is used.
