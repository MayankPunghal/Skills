# Setup and prerequisites

| Need | Why | Install |
| --- | --- | --- |
| Python 3.10+ | All scripts (standard library only) | See codebase-documenter `reference/install-prerequisites.md` (winget / brew / apt, after asking the user) |
| **codebase-documenter** skill (sibling folder or `~/.claude/skills/codebase-documenter`) | Prerequisite installer, graph naming workflow, optional deep documentation of an application | `python install.py` in this skill installs both when packaged together |
| graphify | Code graph per repository (`map_graphs.py`) | `python <codebase-documenter>/scripts/install_prerequisites.py` (installs graphify with uv or pip --user) |
| git | Activity / merge-risk analysis | Usually present; otherwise parallel-dev is reported as not assessed |
| sqlglot | SQL parser fallback, PostgreSQL preview (`codebase-documenter/scripts/sql_parse.py`) | The codebase-documenter `install_prerequisites.py` (`pip install --user`) |
| .NET SDK 8+ | Microsoft's T-SQL parser (ScriptDom): database inventory, SQL inside C# strings, PostgreSQL conversion levels, the database layer of the graph; also `validate_linux_build.py --run --runner local` | The codebase-documenter `install_prerequisites.py` (Microsoft's `dotnet-install`, per user, ~250 MB): ask the user first. Without it SQL is parsed by sqlglot only and procedural T-SQL is partly unparsed (the report says so) |
| Docker or a WSL distro with .NET (optional) | Real Linux build validation | Only with the user's approval (image download) |
| Tool versions | The tools are installed at the versions the skills were tested with; `npx ... update` reports newer releases, never installs them | `install_prerequisites.py --check-updates` (report), `--update` (move to the tested versions); `context.py` shows the last report's `TOOLS:` line |
| Network to api.nuget.org (on by default) | Package frameworks / deprecation / advisories / licence history | Sends package IDs and versions, private ones too; disable with `--offline` (or `online_package_lookup: false`) for confidential estates |

## Workspace rules

- **Create the workspace outside the client repositories**, e.g. `D:/assessments/<client>`. The skill never writes inside client code.
- **Keep the client code read-only.** Clone or copy with the access the client gave you.
- **Never ask for passwords or keys in chat.** LLM keys for community naming come from environment variables only.
- **Treat the outputs as confidential.** They contain hosts, architecture and security findings.
