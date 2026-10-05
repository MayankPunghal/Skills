# Setup and prerequisites

| Need | Why | Install |
| --- | --- | --- |
| Python 3.10+ | All scripts (standard library only) | See codebase-documenter `reference/install-prerequisites.md` (winget / brew / apt, after asking the user) |
| **codebase-documenter** skill (sibling folder or `~/.claude/skills/codebase-documenter`) | Prerequisite installer, graph naming workflow, optional deep documentation of an application | `python install.py` in this skill installs both when packaged together |
| graphify | Code graph per repository (`map_graphs.py`) | `python <codebase-documenter>/scripts/install_prerequisites.py` (installs graphify with uv or pip --user) |
| git | Activity / merge-risk analysis | Usually present; otherwise parallel-dev is reported as not assessed |
| .NET SDK (optional) | `validate_linux_build.py --run --runner local` (CA1416 analysis) | Only with the user's approval |
| Docker or a WSL distro with .NET (optional) | Real Linux build validation | Only with the user's approval (image download) |
| Network to api.nuget.org (optional) | Package frameworks / deprecation / advisories (`--online`) | Sends public package IDs only; disable with `--offline` for confidential estates |

## Workspace rules

- **Create the workspace outside the client repositories**, e.g. `D:/assessments/<client>`. The skill never writes inside client code.
- **Keep the client code read-only.** Clone or copy with the access the client gave you.
- **Never ask for passwords or keys in chat.** LLM keys for community naming come from environment variables only.
- **Treat the outputs as confidential.** They contain hosts, architecture and security findings.
