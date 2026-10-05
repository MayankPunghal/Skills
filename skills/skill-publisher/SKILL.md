---
name: skill-publisher
description: "Publishes a skill folder to Mayank's skill collection in one go: the private Skills-Personal repo by default, or the public Skills repo for shareable skills. It refactors the skill to Anthropic's authoring best practices without dropping any content, scans for secrets, validates, commits and pushes, then installs it on this machine with its prerequisites. Use when the user gives a skill folder, SKILL.md path or skill zip and asks to add, publish, upload, sync, clean up or \"set up\" a skill; when they want to change, update or improve one of their existing skills (by name); or to make a skill follow best practices and put it in the repo."
argument-hint: "<skill folder | .zip | skill name> [changes to make]"
---

# Skill publisher

**No argument** (a bare `/skill-publisher`): ask one question, for the skill folder or .zip, and say in one line what happens next (refactor → checks → publish → install; private unless they say it's shareable).

**Changing an existing skill:** the user can give just its name plus the changes ("/skill-publisher ytstudio: add a shorts-first mode", or a change list from another session). `prepare <name>` stages the repo's current copy; make the requested changes in the staged copy (additively, with the same rules as a refactor), then check, publish and install as usual. If the changes were already made in a folder (an installed copy, a studio, another session's output), pass that folder instead and merge.

The user gives a path. Everything after that is yours: no questions unless a step below says to stop. The script does the mechanical work; you do the refactor.

## Contents
- Workflow
- Refactor rules
- Stop conditions
- Finish

## Workflow

Run the script with `python` (Windows) or `python3`. It lives at `<skill-base-dir>/scripts/publish_skill.py`, where `<skill-base-dir>` is the directory the runtime reports for this skill.

Copy this checklist and tick it off:

```
Publish progress:
- [ ] 1. prepare  (stage + report)
- [ ] 2. refactor the STAGED copy
- [ ] 3. check    (loop until ready)
- [ ] 4. publish  (commit + push)
- [ ] 5. install  (this machine + prerequisites)
```

1. **Prepare:** `python <skill-base-dir>/scripts/publish_skill.py prepare "<path>"`
   - It accepts a folder, a SKILL.md path's folder, or a .zip.
   - It refreshes `~/.mayank-skills/repo` and stages a clean copy in `~/.mayank-skills/staging/<name>`, without caches, `.secrets`, zips or `_old`.
   - It prints NAME, whether it's NEW or an UPDATE, the validator result, a secret scan and `STATUS {...}`.
   - The user's source folder is never changed.
2. **Refactor** the staged copy only, following the rules below and `~/.mayank-skills/repo/CONVENTIONS.md` (read it once).
3. **Check:** `… publish_skill.py check <name>`. Fix and rerun until `"ready": true`. WARN lines are judgment calls, so fix the ones the rules cover. If skill-creator-plus is installed, the output also has an advisory **extra audit** section; see [reference/extra-checks.md](reference/extra-checks.md). It never blocks a publish. If check still fails after a fix, return to step 2.
4. **Publish:** `… publish_skill.py publish <name> [--to personal|public] --message "Add skill: <name> — <one line>"`. It refuses if checks fail. It adds the README row for a new skill, commits and pushes.
   - **Where it goes:** a skill already in a repo stays there. A new skill goes to **personal** (private Skills-Personal: only the owner's machines get it) unless the user said it's shareable or for colleagues; then use `--to public`. Public means anyone can read it, including its git history, so when in doubt, personal.
   - `--to` on an existing skill moves it between repos, updating both READMEs.
5. **Install:** `… publish_skill.py install <name>`. It installs into every folder where the user's other skills live (Claude Code, `.agents`, …) and runs the published skill's `<skill>/scripts/install_prerequisites.py` if it has one. Claude Code hot-reloads skills, so no restart is needed.

## Refactor rules

**Additive.** Never delete a rule, command, example, lesson or detail. Moving text into a reference file is fine; losing it is not. For an UPDATE, diff the staged copy against `~/.mayank-skills/repo/skills/<name>` first. Keep everything the repo version has unless the user's new copy deliberately replaces it, and merge where both have content.

Apply only what the skill needs:
- **Frontmatter.**
  - `name` must equal the folder name: lowercase, hyphens, ≤64 characters, no "claude" or "anthropic".
  - `description` must be ≤1,024 characters, third person ("Documents…", not "I/you…"), saying what the skill does plus a **"Use when …"** clause with the words users actually type.
  - If the old description was longer, keep its full text in a `## Full scope` section of the body.
  - Keep extra keys (`allowed-tools`, `argument-hint`, `version`, …).
- **Size.** Keep the SKILL.md body under 500 lines by moving detail into `reference/*.md` files linked **directly** from SKILL.md (one level deep).
- **Contents lists.** Add `## Contents` at the top of a SKILL.md with several sections and of any reference file over 100 lines. If a file is generated by a script, change the generator, not the output.
- **Paths and terms.** Use forward slashes in paths and one term per concept. No "before/after <date>" instructions; put superseded methods under an "Old patterns" note.
- **Scripts.** Say whether each one is **run** or **read**. Name required packages. If the skill needs installed tools, add `<skill>/scripts/install_prerequisites.py` (idempotent, user-level, standard library). The installer runs it automatically.
- **Dependencies on other repo skills:** add the pair to `DEPENDS` at the top of `~/.mayank-skills/repo/install.mjs` in the same publish.
- **Maintaining section.** Add a short `## Maintaining this skill` section pointing at CONVENTIONS.md (copy the wording from any skill in the repo).
- **Extra checks** (quoting the description, go-back lines, hooks, evals, reference chains): see [reference/extra-checks.md](reference/extra-checks.md). Additive, apply only what the skill needs.
- **Leave alone:** working logic, the author's voice, and anything you don't understand. Note it in the summary instead.

## Stop conditions

Stop and ask only when:
- **The secret scan reports a real credential.** Don't publish. Move it to an environment variable or a `.secrets/` file (excluded), or ask the user. A placeholder like `YOUR_KEY` is not a secret.
- **The skill clearly belongs to a client** (client names, client source code or data). The repo is private but shared across machines, so confirm with the user first.
- **The name collides with a different skill already in the repo.** Ask whether to merge into it or use `--name`.
- **The push fails.** Report the error. The commit stays in `~/.mayank-skills/repo`, and the installer won't discard it.

## Finish

Reply with:
- the name and whether it was new or updated;
- what the refactor changed (descriptions shortened, ToCs added, files moved) in 3–6 bullets;
- the commit pushed;
- where it was installed, and the prerequisites result.

Don't paste file contents.

## Maintaining this skill

Follow `CONVENTIONS.md` in the repo. Changes are additive. The script is standard-library Python and must keep working on Windows, macOS and Linux.
- Test prompts and baseline log: [evals/evals.md](evals/evals.md).
