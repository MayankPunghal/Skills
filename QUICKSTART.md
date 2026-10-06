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

### Ask questions about a documented codebase (docs + code together)

The documentation run also creates a project skill (`<name>-docs`) and a lookup tool. Used together with the code, the agent reads the docs as a map instead of loading the whole codebase, then jumps to the exact `file:line` in the code. Its answers then cite the docs **and** show the real code.

**Recommended: put the docs next to the code.**

1. Unzip the package from `publish/` anywhere.
2. In Claude Code, say: `Read README.md in C:\work\MyApp-Docs and install the docs skill into C:\code\MyApp`.
3. It copies `docs/`, `AGENTS.md`, `CLAUDE.md` and `.claude/skills/<name>-docs/` to the **root of the code repository**, next to the code.
4. Open Claude Code in `C:\code\MyApp` and ask (for example, "how does checkout work?").

To keep the docs out of git, add `docs/`, `site/`, `AGENTS.md` and `.claude/skills/` to `.git/info/exclude`, which applies on your machine only. The security findings page should never reach a public remote.

**Check that it is wired up.** Run `python docs/_tools/lookup.py <SomeClass> --list`. It should print a `doc:` line and a `src:` line:

- `src: …` points into the code: docs and code are connected.
- `src: … (file not found under the source root)`: the code was not found, so answers come from the docs only.

**What Claude uses to answer.** The project skill points Claude at three tools in `docs/_tools/`. You can run them yourself too:

- `lookup.py <Name>` prints the item's doc entry, its code, what it connects to, and the findings that mention it.
- `lookup.py --search "how are refunds handled"` ranks pages and code items for a question in plain words.
- `trace_calls.py <Class.Method> --entry` shows which screens, endpoints and jobs reach a method. `--up` shows what calls it.

**Docs in a separate folder also work.** The lookup tool finds the code through:

1. `--src <path>`;
2. the `DOCS_SOURCE_ROOT` environment variable;
3. `source_root` in `codebase-docs.json`;
4. otherwise, a search of the docs folder, its parent and nearby folders.

Claude Code can only read folders the session was opened in or given access to, so add the code folder to the session too. The workspace where you ran the documentation skill already works this way: its `codebase-docs.json` points at the code.

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

It also lists the tools the skills use (graphify, MkDocs Material, sqlglot, Mermaid) with the installed version, the version the skills were tested with, and the newest release. It never upgrades them. To move to the tested versions, run `python <codebase-documenter>/scripts/install_prerequisites.py --update`.

## Good to know

- **Your code is read-only.** The skills write only to their own output folders.
- **No secrets in outputs.** Reports name configuration keys, never their values. The assessment and documentation skills scan their outputs for leaked values before finishing.
- **Nothing is installed or downloaded silently.** The skills ask first.

## If something goes wrong

| Problem | Fix |
|---|---|
| `EALLOWGIT` error | `npm config set allow-git root`, then rerun |
| An old version installs | Delete the npx cache: `rmdir /s /q "%LocalAppData%\npm-cache\_npx"` (Windows) or `rm -rf ~/.npm/_npx` |
| `Python 3.10+ not found` | Install Python, open a new terminal, then `npx -y github:MayankPunghal/Skills setup` |
| A skill doesn't appear | Run `/reload-skills` in Claude Code |

More: [README → Troubleshooting](README.md#troubleshooting).
