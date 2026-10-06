# Quick start

A one-page guide to using these skills in Claude Code. For every option and detail, see the [README](README.md).

## 1. Install (once, about 2 minutes)

You need **Node.js 18+**, **Git** and **Python 3.10+**.

```bash
npm config set allow-git root
npx -y github:MayankPunghal/Skills --yes --skills=codebase-documenter,migration-assessment,gh-review-pr
```

The first line is only needed on npm 12 or later. The second installs the three skills below for Claude Code, with their prerequisites, without questions (drop the flags to choose interactively). Claude Code picks them up straight away.

## 2. Use

Type the skill name on its own (for example `/migration-assessment`) and it shows its menu and the recommended next step. Or just ask in plain words: Claude picks the right skill.

### Document a codebase: `codebase-documenter`

```
/codebase-documenter full run on C:\code\MyApp
```

- **You get:** an offline, searchable docs website covering architecture, business modules, workflows, data model, security findings and a full cross-linked reference. Open `site/index.html`. A shareable zip goes in `publish/`.
- **It asks first:** whether it may use subagents, and whether it may use an LLM key to name code areas (optional).
- **Tip:** run it from an empty folder for the docs, not inside the code. Long runs can stop and pick up again: `/codebase-documenter resume`.

### Assess a .NET app for AWS: `migration-assessment`

```
/migration-assessment assess the estate at C:\code\MyApp, workspace C:\work\myapp-assessment
```

- **You get:** a client-ready report covering what breaks on Linux or .NET 10, a 7R decision per application, an effort estimate and timeline, risks and open questions. It comes as an interactive HTML page (`assessment/report/*.html`), Markdown and CSV exports.
- **It asks first:** your target (modernize to .NET 10 on Linux, or keep Windows) and the database plan (SQL Server + PostgreSQL, PostgreSQL only, or no change).
- **Tip:** tell it your company name to put it on the report (or set `ASSESSMENT_PREPARED_BY` once per machine). Say `continue` in a later session to resume.

### Review a pull request: `gh-review-pr`

```
/gh-review-pr 42
/gh-review-pr https://github.com/owner/repo/pull/42
/gh-review-pr review --since main --wip
```

- **You get:** findings on three axes: quality (bugs, security, design, performance), the repo's own standards, and the spec (the linked issue). Each finding has the issue, possible fixes, the risk if not addressed and a risk rating. The HTML report goes to `~/.claude/gh-review-pr/reports/`.
- **Posting:** add `--post` and it shows the comments and asks before posting them on the PR.
- **Needs:** the GitHub CLI, signed in (`gh auth login`). Reviewing local changes (`--since`) works without it.

## 3. Stay up to date

```bash
npx -y github:MayankPunghal/Skills update
```

## Good to know

- **Your code is read-only.** The skills write only to their own output folders.
- **No secrets in outputs.** Reports name configuration keys, never their values, and both report skills check for leaks before finishing.
- **Nothing is installed or downloaded silently.** The skills ask first.

## If something goes wrong

| Problem | Fix |
|---|---|
| `EALLOWGIT` error | `npm config set allow-git root`, then rerun |
| An old version installs | Delete the npx cache: `rmdir /s /q "%LocalAppData%\npm-cache\_npx"` (Windows) or `rm -rf ~/.npm/_npx` |
| `Python 3.10+ not found` | Install Python, open a new terminal, then `npx -y github:MayankPunghal/Skills setup` |
| A skill doesn't appear | Run `/reload-skills` in Claude Code |

More: [README → Troubleshooting](README.md#troubleshooting).
