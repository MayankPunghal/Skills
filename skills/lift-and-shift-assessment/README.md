# lift-and-shift-assessment

A Claude Code skill that prices an AWS lift-and-shift (Windows to Windows, EC2, no C# change) of a .NET estate in **developer working hours**, solution by solution, and writes it up as **one Word document** plus a **small workbook**.

It is the narrow sibling of `modernization-assessment`: that skill assesses a real migration (Linux, native AWS services, modernisation); this one covers only the dev team's work when the applications move as they are.


## Changed in 1.1.4

Fixes from five modernization-assessment field runs that apply here too:
- **Credentials written in code are masked (_common.py).** `GetBytes("user:password")`, `"Basic <base64>"` / `"Bearer <token>"`, `NetworkCredential("user", "password")` and `AuthenticationHeaderValue("Basic", "...")` show `***` in evidence, and `verify_doc.py` fails if one reaches the document or the workbook. `password = new ...` / `null` is no longer masked as if it were a value. `_scope.py` masks its coupling snippets.
- **Fewer false findings (scan_repo.py, network_endpoints.py).** Minified bundles are not scanned; one- and two-letter host names are ignored; CFG-HARDCODED-SECRET skips DOM ids and key names (`"#txtPassword"`, `"client_secret"`).

## Changed in 1.1.3

- **Branch check without GitLab (branch_evidence.py).** With no token, no GitLab origin or a GitLab error, the branch check reads the local clone's git history instead (branches, tags, recent merges) and says so, rather than leaving the repository without branch evidence. Same file as modernization-assessment.
- **Client-neutral defaults (same files as modernization-assessment).** The server roles are the generic set (`partner-api`, `xml-api`); a client's own host-name patterns go in the workspace's `assessment.json` as `server_roles_extra`. The company-domain guess reads only the folders nearest the repositories.

## Changed in 1.1.2

- **No false internal hosts from backslashes (network_endpoints.py).** A UNC path (`\\server\share`) must start a value. A `\u017F` inside a regex character range, a drive path such as `C:\temp` and sample paths in publish scripts are no longer reported as servers named `u017F`, `temp` or `full`.
- **Header secrets masked in evidence (_common.py).** A request header compared with a value written in the code (`Headers["X"] == "value"`) shows `***` instead of the value.
- **No temp leftovers (`_docx_brand.py`).** The Word helper scripts in the temp folder and the `.toc-check.pdf` next to the document are removed even when Word fails or times out.

## Changed in 1.1.1

- **Network endpoints name the store, not the port guess (network_endpoints.py).** MongoDB connection strings are MongoDB on 27017 (they also say Server=...), Memcached and Aerospike have their own roles and ports (11211, 3000) instead of Redis on 6379, and a host in a store's own config file (redis.config, memcached.config) takes that store's role.
- **Hosts in service references are SOAP services.** A host found in a WSDL, discovery file or generated Reference.cs is labelled SOAP / WCF, whatever its operation names suggest (no more payment gateway or message broker guesses).
- **Config map ports (_config.py).** A connection string for MongoDB, Memcached, Aerospike or Redis gets that store's default port, not SQL Server's 1433.

## What it does

- Inventories solutions, projects, deployables and workloads (solution x environment).
- Counts what the dev team must handle: environment variables and secrets, config files with hard-coded values, internal addresses, third-party keys and licensed components, server-to-server connections.
- Checks that each solution builds (static readiness; a real MSBuild run on a copy after approval), with a plain reason for every failure and a staging step for shared libraries that were reorganised (`stage_library.py`).
- Checks which branch of each repository is the live line from GitLab history, read-only (`branch_evidence.py`), and records the branch assessed in the workbook (sheet Branches).
- Cross-checks the client's filled application-to-server workbook for contradictions (`check_mapping.py`).
- Types every internal and public address and infers its likely role from setting names and ports (`address_roles.py`).
- Prices only the work items the user selects: build check + artifacts, CI/CD + Secrets Manager, framework retarget, validation + cutover support.
- Writes one DRAFT `.docx` for the whole project (solutions as table rows) and a workbook with the project-level detail (17 sheets: solutions, projects, outbound and inbound calls, connections, settings, third parties, packages, Windows-only findings, build, data stores, branches, client answers, release process and more).
- Lists the GitLab projects read-only and makes shallow, push-disabled clones (`gitlab_projects.py`, `clone_repos.py`).
- Writes the companion files, each as `.md` plus `.html`: the application-to-server sheet for the client (`build_mapping_sheet.py`), the open questions in full, short and as a client email (`build_open_questions.py`), and an explanation of every hour (`build_estimate_explainer.py`).
- Records call answers, release steps, branch choices and decisions with flags (`intake.py --client-update / --release-step / --branch-note / --decision`), so nothing is edited by hand.

Nothing is final until the user says so; every rate can be changed in `scripts/data/hours.json`.

## Use

Open Claude Code in an empty folder outside the client repositories and say: *"Assess the lift-and-shift of the .NET code in D:\clients\acme\repos"*, or `/lift-and-shift-assessment`.

The deterministic part runs from the command line too:

```bash
python scripts/setup_assessment.py --client "Acme" --gitlab-url https://gitlab.acme.example --gitlab-token-env GITLAB_TOKEN
python scripts/gitlab_projects.py --active-months 12      # read-only project list (.xlsx to share)
python scripts/clone_repos.py --dest D:/clients/acme/repos --only-dotnet --set-roots
python scripts/discover_estate.py
python scripts/branch_evidence.py            # needs the VPN and a read token; read-only
python scripts/intake.py --questions          # the agent asks these, then: intake.py --answers '<json>'
python scripts/scan_repo.py --all
python scripts/map_infra.py --servers <DevOps server list.xlsx> --all
python scripts/solutions.py
python scripts/third_party.py
python scripts/address_roles.py
python scripts/check_mapping.py --workbook <filled mapping xlsx>   # when the client returns it
python scripts/stage_library.py --library <shared library checkout>   # only when references moved; add --apply
python scripts/build_check.py
python scripts/estimate_hours.py
python scripts/build_doc.py
python scripts/verify_doc.py
python scripts/build_mapping_sheet.py
python scripts/build_open_questions.py
python scripts/build_estimate_explainer.py
```

Requires Python 3.10+ (standard library only) and git. The real build needs Visual Studio Build Tools (MSBuild). Optional: a company .docx template (`--docx-template`), and Word plus `pip install pymupdf` for page numbers in its table of contents. Package licence lookups use api.nuget.org unless `--offline`. SKILL.md lists the prerequisites for a new machine.

## Outputs

`assessment/documents/<client>-lift-and-shift-assessment.docx` and `.xlsx`; `assessment/estimate.json`; `assessment/solutions/`; `assessment/build/`; `assessment/branches/`; `assessment/infra/address_roles.json`.

## Hours

Rates marked `sample` reproduce the manager's reference estimate (72-108 h) from counts measured in the reference code; rates marked `inferred` are the skill's own. See `references/estimate-model.md`.

## Changes in 1.1.0

Minor version: a new capability (the skill now covers the whole engagement on its own, from the GitLab project list to the client follow-ups), not a small fix.

- New: `gitlab_projects.py`, `clone_repos.py`, `build_mapping_sheet.py`, `build_open_questions.py`, `build_estimate_explainer.py`, `_mdhtml.py` (HTML twin of every Markdown file, branded when a template is set).
- `intake.py`: `--client-update`, `--remove-client-update`, `--release-step`, `--clear-release-steps`, `--branch-note`, `--decision` (decision log). `setup_assessment.py`: `--gitlab-url`, `--gitlab-token-env`, `--docx-template`, `--workbook-url`.
- The GitLab token is also read from the Windows user environment (`_common.gitlab_token`).
- `check_mapping.py` reads any `<Environment> server(s)` column, not only four fixed ones.
- `context.py` points to the new steps; SKILL.md has the new-machine prerequisites and the rules learned on the first engagement (separate teams, never guess where an application runs, log every decision, nothing hand-edited).
- Branded document: TOC page numbers read from Word's own PDF export; front-end line counts (JS, TS, CSS, HTML) and copied-library lines in the workbook.

## Changes in 1.0.1

- Estimate by groups of work (configuration hours follow a continuous curve of the solution's weight), audited for implausible lines; 20% buffer unchanged.
- `branch_evidence.py`, `stage_library.py`, `address_roles.py`; Branches sheet; address type and likely role in Section 5.3 and sheet Connections.
- Build: plain failure reasons, build-order dependencies, packages installed into local folders, Library staging.
- `check_mapping.py` for the returned mapping workbook.
- The DevOps server list keeps the full Application column; known facts (operating systems, hypervisors, build tools, Jenkins servers) fill answers that used to be UNKNOWN.
