# Working in this skills repo

This repo is a master copy of Agent Skills. Each skill is `skills/<name>/` (SKILL.md + reference/ + scripts/ + templates).

## Updating a skill
1. Pull first: `git pull`.
2. Edit only under `skills/<name>/`. Changes are **additive**: never drop a rule, command, lesson or detail unless the owner says so. Moving text into a reference file is fine.
3. Follow the conventions: `CONVENTIONS.md` in the public Skills repo (description ≤1,024 chars, third person, "Use when…"; SKILL.md body <500 lines; references one level deep; `## Contents` on files >100 lines; self-contained; no secrets or machine paths).
4. Validate: `python scripts/validate_skills.py` (public repo) or `python ../Skills/scripts/validate_skills.py skills` (private repo, run from its root). Fix every ERROR; fix WARNs unless there's a reason.
5. Commit and push: `git add -A`, `git commit -m "<skill>: <what changed>"`, `git push`.
6. Install the new version: `npx -y github:MayankPunghal/Skills update`. It refreshes Claude Code's copies and prints which zips (in `~/.mayank-skills/zips`) to re-upload in the Claude app: Settings → Capabilities → Skills.

## Which repo
- **Skills** (public): skills to share with colleagues. Anything here, and in its git history, is readable by anyone.
- **Skills-Personal** (private): personal skills. When unsure, put a skill here.

## Don't
- Don't edit `~/.mayank-skills/repo` or `~/.mayank-skills/personal`: the installer resets them on every run.
- Don't edit installed copies in `~/.claude/skills`: `update` overwrites them.
- Don't commit secrets, client data, caches or zips.
