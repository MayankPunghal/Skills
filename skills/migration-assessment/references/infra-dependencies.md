# Server dependencies, hosting evidence and scope

## Contents
- [What this adds](#what-this-adds)
- [Scope and non-.NET coupling](#scope-and-non-net-coupling)
- [Server dependencies](#server-dependencies)
- [Tying the code to the client's server list](#tying-the-code-to-the-clients-server-list)
- [Hosting evidence (Windows or Linux)](#hosting-evidence-windows-or-linux)
- [Configuration map and network access](#configuration-map-and-network-access)
- [Writing back to the repository inventory workbook](#writing-back-to-the-repository-inventory-workbook)
- [Outputs](#outputs)
- [Limits](#limits)

## What this adds
A lift-and-shift moves servers, so the question "what does this repository need around it?" matters as much as "what breaks in the code?". Step `map-infra` answers it per repository from the code, then ties the answer to the infrastructure list the client's DevOps team shares. Step `update-inventory` writes the new facts back into the client's repository-inventory workbook.

## Scope and non-.NET coupling
- The assessment covers .NET code only. `discover_estate.py` marks a repository **out of scope** when it has no .NET project or Web Site. State is `scope: out` in `assessment/state.json`; scan, graph, classify, estimate and report skip it. It stays listed (inventory, estate.json, the workbook sheet "Assessment scope").
- Inside a .NET repository, projects of other ecosystems are found by their manifest (`package.json`, `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile`, `pom.xml`, `build.gradle`, `go.mod`, `Gemfile`, `composer.json`, `Cargo.toml`) and written to `out_of_scope_projects` in the inventory. A file called `package.json` that is not an npm manifest (a request payload, for example) is ignored.
- Nothing in the client's repository is edited, moved or deleted. Folders of out-of-scope projects that hold no .NET project file are skipped by the scanner (`scope.skip_dirs`); a Node front end that sits in the same folder as a `.csproj` is not skipped.
- **Coupling** (`_scope.py`): for each Node project the skill looks for proof that the .NET side needs it. Levels, strongest first:

| Level | Evidence | Why it matters |
| --- | --- | --- |
| `runtime` | C# starts `node`/`npm`, NodeServices / Jering / SpaServices packages | Node must exist on the server that runs the .NET app |
| `build-drives-dotnet` | gulp / npm script runs `dotnet publish`, `gulp-dotnet-cli`, msbuild | the Node build is part of the .NET build and publish |
| `build-time` | the `.csproj` runs npm/gulp (`Exec`), compiles TypeScript (`Microsoft.TypeScript` targets, `TypeScriptCompile`), lists the Node files, or the Node build writes into a .NET project folder (`wwwroot`, themes, content) or into a folder outside the repository | rebuilding or republishing the .NET app needs the same Node version, and a sibling repository may have to sit next to it |
| `independent` | builds into a folder no .NET project includes | separate deployable: confirm how it is deployed |
| `none-found` | no link found | nothing to do; not proof that none exists |

  `runtime`, `build-drives-dotnet` and `build-time` raise finding `SCOPE-*` (category `dependencies`, kept in the lift-and-shift estimate) with the question "which Node.js and npm versions build it, on which machine, and where is the built output deployed from?". A build that writes outside the repository raises `SCOPE-CROSS-REPO-OUTPUT`.
- Whether the built output is committed (`built output is committed` / `is NOT in the repository`) is stated in the evidence: if it is not committed, the build machine needs Node.

## Server dependencies
- Catalogue: `scripts/data/infra_deps.json`. Each type lists NuGet package ids, code patterns, config key names, value patterns, docker-compose image names, the server roles that serve it, the AWS option for later, and what moves in a lift-and-shift. Add a type there and it appears in every output. Today: SQL Server, Redis, Memcached, Aerospike, Elasticsearch/OpenSearch, Kafka, RabbitMQ, SMTP, SFTP/FTP, SMB/UNC file share, LDAP/Active Directory, MongoDB, MySQL, PostgreSQL, Oracle, HTTP proxy, ASP.NET session/state server.
- Evidence kinds: `package` (project file / packages.config), `code` (.cs/.vb line), `config` (key name or value pattern), `connection-string` (parsed by `scan_repo.py`), `docker-compose` (image). Strength: confirmed (library plus use), likely, possible (key only, reported only when a host or value pattern backs it), local-dev only (compose file).
- **No values.** Evidence text is `config key: <name>` or a masked code line. Only host names, IPs and ports are kept, because they are what ties a dependency to a server. Tokens that look like keys, hashes, namespaces or file names are never kept as hosts.

## Tying the code to the client's server list
- `map_infra.py --servers <file.xlsx|csv>` imports the list (`_servers.py`): the largest sheet (or `--sheet`), header found by synonyms in `scripts/data/server_roles.json`. Every server gets **roles from its name or installed software** by editable rules (`app-biz`, `app-web`, `redis`, `elasticsearch`, `kafka`, `ftp`, `smtp`, `sql-server`, ...), shown with where the role came from. Edit `server_roles.json` to match the client's naming and rerun.
- Link status per repository and server type:

| Status | Meaning |
| --- | --- |
| named: server in the list | a host in the code equals a server name of the list (verified by name) |
| host in code is not a name in the list | an IP or alias: ask which server it is |
| no host in code (set per environment) | configuration lives outside git; candidates are the servers of that type in the list, by environment |
| no server of this type in the list | the code uses it but the list does not show it (a gap in the list or a missed server) |

- Candidates are never presented as the answer; each unresolved link becomes a question in the report ("Servers and hosting").
- `Server coverage` shows every role in the list against the repositories that depend on it, and the types the code uses that the list lacks. A role with no dependents only means no *assessed* repository uses it: with sample access that is expected.

## Hosting evidence (Windows or Linux)
`hosting_evidence()` collects signals from the repository and labels the result **inferred from code, unverified**:
- Windows: .NET Framework target, ASP.NET (System.Web) with `web.config`, Web Deploy / IIS publish profile, drive-letter publish folder, Windows service project, `sc create` / NSSM / `iisreset` / `appcmd` scripts, Windows container image, pipeline steps or agents that name Windows.
- Linux: systemd unit, Linux container image (`mcr.microsoft.com/dotnet/...`, Alpine, Ubuntu), `systemctl` / `apt` / `nginx` scripts, `linux-*` runtime identifier.
- Documentation hints (README, `.rtf`, `.txt`) count as indicative only. Result: `windows`, `linux`, `mixed` (decide per project) or `unknown`. The server OS and the repository-to-server mapping come from the client's DevOps team: the report asks.

## Configuration map and network access
`_config.py` (run by `map_infra.py`) answers two questions per project: **what must be edited when the servers move** and **what must be allowed through the network**.
- **Configuration map**: every setting in `appsettings*.json`, `web.config` / `app.config`, `*.xml`, `*.ini`, `*.properties`, `*.conf`, `*.env`, `*.settings`, `*.toml` and similar files whose value is an address or path: URL, IP, host name, UNC share (two backslashes, server, share), drive path (a drive letter and folders), unix path. Each row has the project, file, line, environment of the file (Development, Production...), setting name, what it holds, target host/port, kind, and the action for AWS. Values that look like secrets (password, key, token, secret, connection credentials) are skipped; only host, port and path are kept.
- **Kind** drives the action: private IP / internal host name / company domain (must resolve and be reachable in the VPC: DNS or a changed address), UNC share and local drive path (the share or folder must exist on the new server), public IP and external service (outbound only, or an allow-list on the supplier's side because the source IP changes), set at deploy time (placeholder such as `#{...}#` or `%ENV%`: the value lives in the deploy tool).
- **Where it lives**: configuration file versus hard-coded in code versus front end, so a change that needs a rebuild is separated from one that is only a file edit.
- **Network access**: the same destinations merged with the scan facts (`network` from codebase-documenter) into one list per project: destination, port, protocol, role (SQL Server, SMTP, SFTP...), and what must happen on AWS (security group or route to the VPC, DNS record, outbound internet rule, supplier allow-list of the new public IP). Linked to the DevOps server list when the destination is a name or IP in it.
- Outputs: `assessment/config/<repo>.json`, `assessment/infra/config-map.json`, `report/config-map.csv`, `report/network-access.csv`; report blocks `network-access` (4.2c) and `config-map` (4.2d); workbook sheets **Network access** and **Config map**.
- Limit: settings held outside git (IIS application settings, machine environment variables, a database, the deploy tool) are not visible. They are listed as questions, not guessed.

## Writing back to the repository inventory workbook
`update_inventory_xlsx.py --xlsx <workbook>` keeps every existing sheet and row (values; formatting is regenerated), makes `<name>.before-update.xlsx` once, and adds or replaces: **Assessment scope**, **Non-.NET coupling**, **Server dependencies**, **Server coverage**, **Network access**, **Config map**, **Servers (DevOps list)**, **Hosting evidence**, **Assessment additions**, plus rows in **About**. "Assessment additions" lists what the workbook did not have: server dependencies missing from its Dependencies sheet, internal hosts and hard-coded public IPs missing from Hosts referenced, build outputs that cross repositories, and Node.js "projects" that are not npm manifests. Close the workbook in Excel first. Run it again after each scan to refresh.

## Outputs
`assessment/infra/<repo>.json` (dependencies, hosting, questions), `assessment/infra/servers.json`, `assessment/infra/estate-infra.json` (the single view), `assessment/report/infra-dependencies.csv`, `infra-server-coverage.csv`, `hosting-evidence.csv`; report blocks `server-deps` (4.2a / 4.9) and `scope-coupling` (4.2b / 4.10); open questions area "Servers and hosting".

## Limits
- Code shows what an application is built to use, not what is deployed: hosts set in IIS, environment variables, deployment tools or a database are invisible. That is why unresolved links are questions.
- Name-based roles are leads: a server called `BIZ12` is a business-tier server only because the naming rule says so.
- Only `.cs` / `.vb`, project files, configuration and data files (`.json .config .xml .ini .properties .conf .env .settings .toml`), docker files and deployment scripts are read; other languages are never scanned.
