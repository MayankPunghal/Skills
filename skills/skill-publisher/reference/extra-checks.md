# Extra checks from skill-creator-plus (additive)

These come from robonuggets/skill-creator-plus and Anthropic's best practices. They add to the refactor rules in SKILL.md; nothing here replaces or relaxes a rule there. Apply what the skill needs, skip the rest.

## Contents

- [Advisory audit](#advisory-audit)
- [Extra refactor checks](#extra-refactor-checks)
- [Evals for the published skill](#evals-for-the-published-skill)
- [Before you publish](#before-you-publish)

## Advisory audit

`publish_skill.py check <name>` also prints an **extra audit** section when skill-creator-plus is installed (`~/.claude/skills-tools/skill-creator-plus` or `~/.claude/skills/skill-creator-plus`).
- It is advisory: it never changes `"ready"` and never blocks a publish.
- Fix its ERROR lines unless the skill has a reason (for example a script that legitimately mentions `TODO`); say which you skipped in the summary.
- If the tool is not installed, the section is skipped silently.

## Extra refactor checks

- **Quote the description** when it contains `: `, otherwise YAML reads it as a new key and the frontmatter fails to parse.
- **Go-back lines.** Any checklist or numbered loop ends with a line such as "If the check fails, return to step 2".
- **Hooks for must-hold rules.** A rule worded "always" or "after every" that must really hold every time is better enforced by a hook than by prose, which can be skipped or lost to compaction. Mention it in the summary instead of adding a hook unasked.
- **Important instructions near the top** of SKILL.md, not buried after the workflow.
- **Install lines.** If a script needs a package, name it with its install command.
- **No instructions to narrate reasoning aloud.** Newer models may decline them, and they spend tokens without changing the result.
- **Reference chains.** Prefer links from SKILL.md to each reference file over reference-to-reference links.
- **Every bundled file is mentioned** in SKILL.md or another file, so Claude has a reason to open it.
- **No time-sensitive wording** (a version number stated as the newest, a month and year as a cutoff); state the current way and move old ways under "Old patterns".

## Evals for the published skill

Offer to add `evals/evals.md` with at least three test prompts, one that should trigger by plain description, one bare invocation, and one that should **not** trigger. Use this shape per test:

```text
### <short name>
Prompt: <exactly what a user would type>
Should trigger: yes | no
First file Claude should open: <file>
Done looks like: <one checkable line>
```

Add a baseline log (date, model, with or without the skill, result). Never add evals to a skill the owner did not ask to change beyond the refactor without saying so in the summary.

## Before you publish

If a skill has scripts, run one end to end with real input, not just the validator. If it was only validated, say so in the summary.
