# dotnet-modernization

A Claude Code skill that carries out the modernization of legacy .NET Framework applications to .NET 10 on Linux containers on AWS, after the **modernization-assessment** skill has planned it (or from scratch on one repository).

- **One porting engine per project:** the AWS DevTx Version Upgrade Toolkit or AWS Transform for .NET (Claude with the DevTx knowledge base when neither is available).
- **Claude cleans up** what the engine leaves, with 17 playbooks: project files and packages, System.Web residue, HTTP handlers and modules, Web Forms UI, ASMX and SOAP clients, WCF, startup and middleware, config and secrets, auth, ambient context and remoting, Windows-only APIs, background work, time and culture, logging, Linux and containers, AWS managed services, raw SQL and data access.
- **One database tool:** the DB porting agent, or Claude with the DB porting skills, for SQL Server → PostgreSQL in the application code (dual database or PostgreSQL only).
- **Gates:** baseline, build, tests, residue scan (44 rules), Linux readiness (240 checks), container run with a health check, request/response parity. An execution report closes each package.
- Applications already on .NET 5+ get the Linux readiness path only.

## Install

Through the skills repository installer (`npx` / `node install.mjs`), or copy the folder to `~/.claude/skills/dotnet-modernization`. Then:

```bash
python ~/.claude/skills/dotnet-modernization/scripts/install_prerequisites.py --check
```

Needs Python 3.10+ (standard library only). The gates need the .NET 10 SDK and Docker; the engines need their own tools (DevTx toolkit or AWS Transform access, Kiro CLI, Node for the DB porting agent). Nothing is installed without asking.

## Use

Work on a branch of a copy of the client's repository, never the original. Say, for example:

- *"Modernize the OrderService package from the execution plan"*, or `/dotnet-modernization modernize-package OrderService`;
- *"AWS Transform finished; clean up what it left"* → residue scan, Linux readiness, playbooks;
- *"This app is already on .NET 8: is it ready for Linux containers?"* → `linux-readiness`;
- *"Verify the port"* → `verify.py target` with every gate.

Bare `/dotnet-modernization` shows where the run is and the next step.

## What it produces

In `<folder>/.modernization/`: `baseline.json`, `residue.md`, `linux-readiness.md`, `verify.md`, `parity.json`, `run-log.jsonl` and `execution-report.md`, each Markdown file with an `.html` twin.

## Structure

```
SKILL.md                    commands, workflow, principles
NOTICE                      Apache-2.0 notice for reference/kb
reference/workflow.md       order of work, package checklist, modern-app path
reference/engines.md        DevTx, AWS Transform, Claude, the DB porting agent, Claude with the DB porting skills
reference/verification.md   the gates
reference/linux-readiness.md  the 240 checks
reference/playbooks/        17 playbooks + index
reference/kb/               DevTx .NET knowledge base (28 files, Apache-2.0)
scripts/                    verify, residue_scan, linux_readiness, parity, report, install_prerequisites
evals/evals.md              test prompts and expected behaviour
```

## Licence

`reference/kb/` is Apache-2.0 (Amazon), see `NOTICE`. The rest belongs to the skill owner.
