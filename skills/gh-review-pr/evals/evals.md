# Evaluations for gh-review-pr

Run each prompt in a fresh session, first without the skill (baseline), then with it. Record the difference below.

## Contents

- [Triggering and routing](#triggering-and-routing)
- [Review behaviour](#review-behaviour)
- [Posting and report](#posting-and-report)
- [Script checks](#script-checks)
- [Baseline log](#baseline-log)

## Triggering and routing

### Bare invocation
Prompt: `/gh-review-pr`
Should trigger: yes
Done looks like: asks for the repository and PR number (or a `--since` ref) and shows the command table; nothing is fetched.

### PR URL
Prompt: "Review https://github.com/cli/cli/pull/14592"
Should trigger: yes
First file Claude should open: `scripts/gh-context.mjs --pr <url>` output (owner and repo come from the URL)
Done looks like: three axes reported separately; the Spec axis uses the closing issue `cli/cli#14045`; HTML report written; asks "report only or post?".

### Local review since a ref
Prompt: "Review everything on this branch since main, including what I haven't committed yet"
Should trigger: yes
Done looks like: `gh-context.mjs --since main --wip`; untracked files are read; nothing is posted; report key is `<repo-folder>-local-<branch>`.

### Should not trigger
Prompt: "Fix the failing test in src/auth/token.test.ts"
Should trigger: no
Done looks like: skill not loaded; normal coding help.

## Review behaviour

### Spec missing
Prompt: `/gh-review-pr 42` on a PR with no linked issue, no spec file and a one-line description
Should trigger: yes
Done looks like: Claude asks once where the spec is; if there is none, the Spec axis shows "no spec available" and the other two axes still run.

### Repo standard beats the smell baseline
Setup: CONTRIBUTING.md says "thin delegating services are the house pattern".
Done looks like: no "Middle Man" smell is reported for a delegating service; a documented-rule breach elsewhere is reported as `kind: "hard"` with the file and rule quoted.

### Tooling-enforced rules are skipped
Setup: the repo has `.eslintrc` with `semi: always`; the diff misses a semicolon.
Done looks like: no Standards finding for the semicolon.

### Large PR coverage
Prompt: review a PR with 70+ files (e.g. cli/cli#14475)
Done looks like: every file is in `files` (pagination); files listed in `coverage.truncated` / `notInDiff` are fetched and read; the summary names anything not reviewed.

### No cross-axis ranking
Done looks like: report sections `Quality`, `Standards`, `Spec`, each ordered within itself; the closing line gives totals and the worst finding per axis, never one overall winner.

## Posting and report

### Report then post later
Prompt 1: `/gh-review-pr 42` (choose "report only"). Prompt 2 (new session): `/gh-review-pr post 42`
Done looks like: prompt 2 loads the cache (same head SHA), shows the preview, asks `[y/N]`, posts; no second review.

### Re-run does not duplicate
Prompt: post the same review twice
Done looks like: the second run reports every finding as "already on the PR, skipped" and does not post a second summary for the same commit.

### Comment content
Done looks like: each comment has the risk rating, title, **Issue**, evidence block, **Risk if not addressed**, **Possible fixes** (recommended first), a `suggestion` block only when `fix` is set, the axis / rule line, and a blame-based `cc`.

## Script checks

Run from `skills/gh-review-pr/scripts/` (no posting; the `--dry-run` reads only):

| Check | Command | Expect |
|---|---|---|
| URL + pagination | `node gh-context.mjs -p https://github.com/cli/cli/pull/14475` | 75 files, `checks.total` 11, `standards` includes `AGENTS.md` |
| Closing issue | `node gh-context.mjs -o cli -r cli -p 14592` | `linkedIssues[0].ref` = `cli/cli#14045`, `closing: true` |
| Bad ref | `node gh-context.mjs --since nope` | exit 1, "does not resolve to a commit" |
| Empty diff | `node gh-context.mjs --since HEAD` | exit 1, suggests `--wip` |
| Excluded file dropped whole | local repo with a changed `package-lock.json` | lockfile body absent from `diff`, listed in `coverage.excluded` |
| Contract | `node findings-cache.mjs --save ... --findings-file bad.json` | exit 1 listing each bad field |
| Dry run | `node post-review.mjs ... --findings-file f.json --dry-run` | every comment printed with its target; nothing posted |
| Report | `node render-report.mjs --findings-file f.json --context ctx.json --out r.html` | one HTML file, no external URLs except links to GitHub |

## Baseline log

| Date | Version | Prompt | Without skill | With skill |
|---|---|---|---|---|
| 2026-10-06 | 2.0.0 | Script checks above | — | all pass (cli/cli#14475, #14592, local temp repo, dry run on MayankPunghal/Skills#13) |
