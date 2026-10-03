# Skill conventions

The rules every skill in this repo follows, picked from Anthropic's [skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) for how we actually work. `python scripts/validate_skills.py` checks the mechanical ones.

## Contents
- Frontmatter
- Discovery (Claude picks skills itself)
- Self-contained skills
- Structure and progressive disclosure
- Writing
- Scripts
- Changing a skill
- Adding a new skill

## Frontmatter
- `name`: max 64 characters, lowercase letters / numbers / hyphens, no "anthropic" or "claude", same as the folder name.
- `description`: max 1,024 characters (hard limit — longer ones are rejected on upload), no XML tags, **third person** ("Documents…", not "I can…" or "Document…").
- The description says **what the skill does and when to use it**, with the trigger words a user would actually type. It is the only thing Claude sees when choosing among skills.
- If the full scope doesn't fit, keep the description to the essentials and put the long version in a **Full scope** section of the body.
- Claude Code extras (`version`, `user-invocable`, `argument-hint`, `allowed-tools`, `license`) are fine.

## Discovery (Claude picks skills itself)
- Claude reads every skill's `name` + `description` up front and invokes a skill on its own when a request matches (Claude Code, claude.ai, Codex and Cursor all work this way). The description is the whole trigger: lead with what the skill does, then a "Use when …" clause with the words people actually type.
- Leave model invocation on. Set `disable-model-invocation: true` only for a skill that must never run unless typed (none of ours).
- Claude Code truncates `description` + `when_to_use` at 1,536 characters in its listing, and drops whole descriptions first when many skills are installed. Shorter descriptions survive.

## Self-contained skills
- A skill carries everything it needs: scripts, templates, data, reference docs. It must work on a machine that has only the installed skill.
- If a skill works on a user folder (a workspace or studio folder), it ships the folder's template and a script that finds it, creates it or refreshes it. The skill holds the master copy of the code, and the folder holds the user's work.
- No machine-specific paths (`C:\Users\…`, `/Users/…`) and no tool caches (`.impeccable/`, `.venv/`). The validator flags both.
- Dependencies on other skills in this repo go in `DEPENDS` in `install.mjs`; tools to install go in `scripts/install_prerequisites.py`.

## API keys and models
- **Key first, then fallbacks.** When a step works best with an API (an LLM, TTS, image model), the skill suggests setting up the key when it's missing: where to get it, one line on what it unlocks, and an offer from `install_prerequisites.py` to save it. It falls back only if the user declines, and the fallbacks are written down.
- **Never tied to one model.** A cheap sensible default, overridable per run (a flag), per project (config) and per machine (an environment variable). Keys come from environment variables or a git-ignored `.secrets/` file, never from chat or the repo.

## Structure and progressive disclosure
- SKILL.md body under 500 lines. It is the map: setup, the command table, the always-on rules, links to references.
- Detail lives in reference files linked **directly from SKILL.md** (one level deep). Never SKILL.md → a.md → b.md → content.
- Reference files over 100 lines start with a `## Contents` list so partial reads still see the whole scope.
- SKILL.md files with several sections get a `## Contents` list too.
- Name files by content (`windows-api-catalog.md`, not `ref2.md`); forward slashes in every path.
- Generated files are fixed at the generator, never by hand.

## Writing
- Concise: Claude is already smart. Only add what it wouldn't know — our tools, our rules, our lessons.
- One term per concept throughout a skill.
- Match freedom to fragility: exact commands for fragile steps, heuristics for judgment calls.
- Multi-step workflows get a numbered table or checklist; quality-critical ones get a validate → fix → repeat loop.
- No "before/after <date>" instructions. Superseded methods go under an "Old patterns" note. Facts that age (versions, support dates, quotas) live in one place and say to re-check them.
- MCP tools are named fully (`Server:tool_name`).

## Scripts
- Scripts solve problems instead of failing back to Claude; errors say what to do next.
- Constants are explained (no magic numbers).
- Say whether Claude should **run** a script or **read** it.
- List dependencies and how to install them; prefer the standard library.

## Changing a skill
- **Additive by default.** Never drop a rule, command, lesson or detail without the owner's say-so. Moving text into a reference file is fine; deleting it is not.
- Improve the skill in the same session a lesson is learned.
- Run `python scripts/validate_skills.py` before committing.

## Adding a new skill
Easiest: `/skill-publisher <folder>` in Claude Code does all of the below, putting new skills in the private repo unless you say they're shareable. Public means anyone can read the skill and its history. By hand:

1. Copy the folder into `skills/<name>/` (folder name = `name`).
2. Leave out client data, secrets, caches (`__pycache__`), build zips and generated output.
3. Validate, add a row to the README table, commit, push.
