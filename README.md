<div align="center">

# Skills

**Production-grade Agent Skills for Claude Code, Codex, Cursor and GitHub Copilot.**
<br>One command installs them, and Claude picks the right one on its own.

[![Skills](https://img.shields.io/badge/skills-3-6E56CF)](#skills)
[![Agents](https://img.shields.io/badge/agents-Claude%20Code%20·%20Codex%20·%20Cursor%20·%20Copilot-0A7EA4)](#supported-agents)
[![Node](https://img.shields.io/badge/node-%E2%89%A518-339933?logo=node.js&logoColor=white)](https://nodejs.org)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20·%20macOS%20·%20Linux-555)](#requirements)
[![Spec](https://img.shields.io/badge/spec-Agent%20Skills-D97757)](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)

```bash
npx -y github:MayankPunghal/Skills
```

</div>

---

## Contents

- [Skills](#skills)
- [Quick start](#quick-start)
- [Requirements](#requirements)
- [Installer reference](#installer-reference)
- [How it works](#how-it-works)
- [Supported agents](#supported-agents)
- [Claude app and phone](#claude-app-and-phone)
- [Publishing a skill](#publishing-a-skill)
- [Troubleshooting](#troubleshooting)
- [Repository layout](#repository-layout)
- [Contributing](#contributing)

## Skills

| Skill | What it does | Bundles |
|---|---|---|
| [**codebase-documenter**](skills/codebase-documenter/SKILL.md) | Documents an existing codebase end to end, in any language. It builds a knowledge graph, an exhaustive cross-linked reference and narrative docs (architecture with C4, workflows, data model, security findings), then an offline searchable MkDocs site and an agent layer (`AGENTS.md`, project skill, `llms.txt`). | 14 commands · Python scripts · templates · prerequisite installer |
| [**migration-assessment**](skills/migration-assessment/SKILL.md) | Assesses legacy .NET estates (one repo or hundreds) for AWS and Linux. It scans for everything that breaks on Linux or .NET 10, classifies apps with the 7 Rs, estimates effort, and writes a client-ready report (Markdown, interactive HTML, JSON/CSV). | 130+ detection rules · estimation model · report templates · worked sample |
| [**skill-publisher**](skills/skill-publisher/SKILL.md) | Takes any skill folder or zip, refactors it to the [conventions](CONVENTIONS.md) without dropping content, validates it, scans it for secrets, pushes it to this repo and installs it with its prerequisites. | Staging · secret scan · validator gate · git automation |

Every skill is **self-contained**: scripts, templates and data ship inside the skill folder, so it works on any machine where it's installed. Every skill is also **model-invocable**: Claude reads the descriptions and uses a skill when a request fits, or you call it by name (`/codebase-documenter`).

## Quick start

```bash
# 1. One-time, npm 12+ only: allow packages you name from GitHub (not their sub-dependencies)
npm config set allow-git root

# 2. Install
npx -y github:MayankPunghal/Skills
```

The installer walks through four choices:

```
Mayank's Skills installer  ·  3 skills

✔ Which skills? codebase-documenter, migration-assessment, skill-publisher
✔ Install where? Global
✔ For which agents? Claude Code, Codex / .agents (shared)
✔ Install prerequisites for codebase-documenter? Yes, install now

✔ codebase-documenter → ~/.claude/skills/codebase-documenter
…
Done — 6 skill install(s). Claude Code picks them up automatically (or run /reload-skills).
```

No restart is needed: Claude Code hot-reloads `~/.claude/skills`.

## Requirements

| | Version | Why |
|---|---|---|
| Node.js | 18+ | Runs the installer (`npx`) |
| Git | any recent | The installer keeps a managed clone so you always get the latest `main` |
| Python | 3.10+ | Skill scripts and prerequisite installers |
| npm | 12+ needs `allow-git` | npm 12 blocks GitHub-hosted packages by default ([changelog](https://github.blog/changelog/2026-06-09-upcoming-breaking-changes-for-npm-v12/)) |

## Installer reference

```bash
npx -y github:MayankPunghal/Skills [command] [options]
```

| Command | Description |
|---|---|
| *(none)* / `install` | Interactive install: choose skills, scope, agents, copy or link, prerequisites |
| `update` | Refresh every recorded install from the latest `main`, and offer skills added since then |
| `setup` | Install or repair prerequisites for installed skills (e.g. after upgrading Python) |
| `zips` | Rebuild the upload-ready zips for the Claude app and list the changed ones |
| `list` | Show what is installed, for which agent and where |
| `uninstall` | Remove installs (pick from a list, or all with `--yes`) |

| Option | Description |
|---|---|
| `--yes` | Accept defaults without prompts: all skills, global, Claude Code, prerequisites |
| `--skills=all\|a,b` | Choose skills |
| `--agents=claude,codex,cursor,copilot` | Choose agents |
| `--scope=global\|project` | User-wide or the current project only |
| `--dir=PATH` | Project folder for `--scope=project` (default: current folder) |
| `--link` | Link to the managed clone instead of copying (updates with every installer run) |
| `--no-setup` | Skip prerequisite installation |
| `--no-zips` | Don't write the Claude app zips |
| `--no-sync` | Use the copy npx provided instead of refreshing the managed clone |

Examples:

```bash
# New machine, no questions
npx -y github:MayankPunghal/Skills --yes

# One skill into the current project for Claude Code and Cursor
npx -y github:MayankPunghal/Skills --skills=codebase-documenter --scope=project --agents=claude,cursor
```

## How it works

```
npx github:MayankPunghal/Skills
        │
        ├─ refresh ~/.mayank-skills/repo   (git clone/fetch; npx's own cache can be stale)
        ├─ hand over to that copy's install.mjs
        ├─ copy or link skills/<name> → each agent's skills folder
        │     └─ an existing copy is moved to ~/.mayank-skills/backup/<timestamp>/ first
        ├─ run scripts/install_prerequisites.py for skills that ship one
        └─ record every install in ~/.mayank-skills/manifest.json (update · list · uninstall)
```

- **Always current.** npx reuses its cached copy of a GitHub package without checking for a newer one. The installer therefore keeps its own clone and installs from the latest `main` every time.
- **Safe to rerun.** Replaced skills are backed up, never deleted. The managed clone is never reset while it holds unpushed work.
- **Dependencies.** Selecting a skill brings the skills it needs. For example, migration-assessment brings codebase-documenter.
- **Prerequisites.** These are user-level installs with no admin rights; anything already present is skipped.
- **Private skills.** The installer also checks an optional private source. Machines with access get those skills in the same menu (tagged *personal*); everyone else sees only the skills in this repo, with no prompt and no error.

## Supported agents

| Agent | Global folder | Project folder | Auto-invocation |
|---|---|---|---|
| Claude Code | `~/.claude/skills` | `.claude/skills` | ✓ |
| Codex / shared `.agents` | `~/.agents/skills` | `.agents/skills` | ✓ |
| Cursor | — | `.cursor/skills` | ✓ |
| GitHub Copilot | — | `.github/skills` | ✓ |
| Claude app (desktop, web, phone) | Upload the zips from `~/.mayank-skills/zips` under **Settings → Capabilities → Skills** ([details](#claude-app-and-phone)) | — | ✓ |

## Claude app and phone

Chats in the Claude app (desktop, web, phone) use skills stored in your **claude.ai account**. No installer can write there, so every `install`, `update` and `zips` run also writes one upload-ready zip per skill to `~/.mayank-skills/zips/` and lists the ones that changed since the last run:

```
Claude app / claude.ai (phone, web, desktop chats use skills stored in your account)
  Upload-ready zips: C:\Users\you\.mayank-skills\zips
  Upload these in Settings → Capabilities → Skills (replace the old copy): ytstudio.zip
```

Upload just those under **Settings → Capabilities → Skills**. Once uploaded, they're on every device signed in to the account. `npx -y github:MayankPunghal/Skills zips` rebuilds the zips on demand (and opens the folder on Windows); `--no-zips` skips them.

## Publishing a skill

Hand any skill folder to the publisher in Claude Code:

```
/skill-publisher C:\path\to\my-skill
```

1. **Stage.** It makes a clean copy without caches, secrets, zips or `_old/`. Your source is never modified.
2. **Refactor.** Claude applies [CONVENTIONS.md](CONVENTIONS.md) additively, merging if the skill already exists here.
3. **Gate.** The validator and secret scan must pass before anything is published.
4. **Publish.** It commits, pushes and adds a row to the skills table. New skills go to the private source unless you say they're shareable (`--to public`).
5. **Install.** It installs into every folder your other skills live in, with prerequisites. Other machines get it with `update`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `npm error code EALLOWGIT` | npm 12+: run `npm config set allow-git root` once, or add `--allow-git=all` to the command |
| `npx` prints nothing and exits | Old npm (10.0.x) on Windows: upgrade with `npm install -g npm@latest` |
| An old version installs | Run once: `rmdir /s /q "%LocalAppData%\npm-cache\_npx"` (Windows) or `rm -rf ~/.npm/_npx` |
| `Python 3.10+ not found` | Install Python (`winget install --id Python.Python.3.14 -e`), open a new terminal, then run `… setup` |
| A skill doesn't show up | Run `/reload-skills` in Claude Code, and check `… list` |

## Repository layout

```
skills/<name>/              one folder per skill (SKILL.md + reference/ + scripts/ + assets)
install.mjs                 the installer (zero dependencies)
scripts/validate_skills.py  checks every skill against CONVENTIONS.md
CLAUDE.md                   how an agent updates a skill here (read automatically by Claude Code)
CONVENTIONS.md              authoring rules, based on Anthropic's skill best practices
package.json                makes the repo runnable with npx
```

## Contributing

- Follow [CONVENTIONS.md](CONVENTIONS.md). Changes are **additive**: never drop a rule, command or lesson without the owner's agreement.
- Run `python scripts/validate_skills.py` before committing (CI-friendly: it exits 1 on errors).
- Prefer `/skill-publisher`, which does the refactor, checks, commit and install in one pass.

### Skill-specific notes

- **migration-assessment** puts a consultancy name on reports: pass `--prepared-by "Your Company"`, or set `ASSESSMENT_PREPARED_BY` once per machine.
- **codebase-documenter** names graph communities with an LLM. When no key is set it suggests OpenRouter with **GLM 5.3 Flash** (`z-ai/glm-5.3-flash`, the default), and any other model or provider works: `--model`, `graph.model`, or `CODEBASE_DOCS_LLM_MODEL`.
