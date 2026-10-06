# Axes, sources and sub-agent briefs

How the three review axes are kept apart, where each axis gets its source of truth, and the briefs for running them as parallel sub-agents.

## Contents

- [Why separate axes](#why-separate-axes)
- [Pin the fixed point](#pin-the-fixed-point)
- [Spec sources, in order](#spec-sources-in-order)
- [Standards sources](#standards-sources)
- [Running the axes](#running-the-axes)
- [Sub-agent briefs](#sub-agent-briefs)
- [Aggregating](#aggregating)

## Why separate axes

| Axis | Question | Source of truth |
|---|---|---|
| **Quality** | Will it break, leak, or slow down? | The code itself, lenses A–F ([review-lenses.md](review-lenses.md)) |
| **Standards** | Does it follow this repository's rules? | The repo's documented standards, then the smell baseline |
| **Spec** | Does it do what was asked? | The linked issue, spec file or stated requirements |

A change can pass one axis and fail another:

- Code that follows every standard but implements the wrong thing → **Standards pass, Spec fail.**
- Code that does exactly what the issue asked but breaks the project's conventions → **Spec pass, Standards fail.**
- Code that is on-spec and on-standard but races under load → **Quality fail.**

Reporting them separately stops one axis from masking another. Never merge, rerank or pick a single "worst" across axes.

## Pin the fixed point

- **PR:** the base is the PR's base branch at its merge-base; the head is `pr.headSha`. Every finding refers to that head commit.
- **Local:** the user names the fixed point (a commit SHA, branch, tag, `main`, `HEAD~5` ...). If they didn't, ask for it. The diff is `git diff <fixed-point>...HEAD` (three-dot: against the merge-base); `--wip` diffs the merge-base against the working tree (staged and unstaged) and lists untracked files.
- `gh-context.mjs` confirms the ref resolves and the diff is non-empty before anything else; a bad ref or empty diff fails there, not halfway through a review.

## Spec sources, in order

1. **A spec the user passed** (`--spec <path | #123 | URL>`, or named in the request). Read it; it wins.
2. **`linkedIssues`** from the context: GitHub "closing" references first, then `#N` / `owner/repo#N` mentioned in the description or commit messages, then an issue number at the start of the branch name. Each carries its title and body.
3. **`unresolvedRefs`**: references GitHub could not fetch (Jira keys like `PROJ-77`, GitLab `!67`, a `#N` with no GitHub remote). If `issueTrackerDoc` is set (`docs/agents/issue-tracker.md`), follow it to fetch them; otherwise ask the user for the text or a link.
4. **`specCandidates`**: files under `docs/`, `specs/`, `.scratch/`, `rfcs/`, `design/`, `plans/`, `adr/` whose names share words with the branch name or PR title. Open the best match and use it only if it really describes this change.
5. **The PR description**, when it states requirements (acceptance criteria, a list of behaviours). Record `"source": "PR description"`.
6. **Nothing found:** ask the user once where the spec is. If there is none, the Spec axis reports `"status": "no spec available"` and is skipped; the Quality axis still cross-checks the code against the title and description.

Record what was used in `axes.spec.source`, so the reader knows what the change was measured against.

## Standards sources

- **`standards`** from the context: `CONTRIBUTING`, `CODING_STANDARDS`, `CODE_STYLE`, `STYLE_GUIDE`, `CONVENTIONS`, `GUIDELINES`, `AGENTS.md`, `CLAUDE.md`, `copilot-instructions.md`, `ARCHITECTURE` in the root, `.github/`, `docs/` and `docs/agents/`. Read the parts that cover the languages and areas in the diff. A file the user points to counts too.
- **`tooling`**: linter, formatter and analyzer configs (`.eslintrc*`, `.prettierrc*`, `.editorconfig`, `ruff.toml`, `.golangci.yml`, `stylecop.json`, `.globalconfig`, `Directory.Build.props`, pre-commit hooks ...). Do not report what these enforce.
- **The smell baseline** in [review-lenses.md](review-lenses.md): always on, always a judgement call, overridden by any documented repo rule.

Record the files used in `axes.standards.sources`.

## Running the axes

- **Sequential (default).** Review one axis at a time, Quality → Standards → Spec. Write each axis's findings into the findings file before starting the next, and judge each axis only against its own source of truth, so one axis does not colour another.
- **Parallel sub-agents** (when the user passes `--parallel` or asks for it). Each axis runs in its own sub-agent with a clean context, which is the strongest separation but costs more tokens: each sub-agent reads the diff again. Give each one the brief below, the path of the saved context JSON, and the diff command. The lead then verifies, rates and merges the three outputs into one findings file.
- `--axes quality,standards` (any subset) runs only those; the others report `"status": "not requested"`.

## Sub-agent briefs

Each brief goes to its sub-agent verbatim, with the placeholders filled. Every brief ends with the output rule: *Return findings as a JSON array in the contract of references/output-and-posting.md (fields `axis`, `file`, `line`, `title`, `issue`, `evidence`, `riskIfIgnored`, `solutions`, `impact`, `likelihood`, `severity`, `kind`, `rule`), and nothing else.*

**Quality**
> Review the change in `<context.json>` (diff command: `<diff command>`; commits: `<list>`). Apply lenses A–F from `<skill-base-dir>/references/review-lenses.md` and its false-positive filters. Read every file the context lists under `coverage.patchMissing`, `coverage.truncated` and `coverage.notInDiff` before judging it. Report bugs, security holes, design flaws, performance problems and maintainability concerns with a concrete trigger for each. At most 10 findings, worst first. Under 600 words of finding text in total.

**Standards**
> Review the change in `<context.json>` against these standards files: `<list>`, plus the smell baseline below, pasted in full. Report, per file/hunk where relevant, (a) every place the diff violates a documented standard: cite the standard (file + the rule) in `rule`; and (b) any baseline smell you spot: name it in `rule` and quote the hunk in `evidence`. Distinguish hard violations from judgement calls: documented-standard breaches can be hard, but baseline smells are always judgement calls, and a documented repo standard overrides the baseline. Skip anything tooling enforces (`<tooling list>`). Under 400 words.
> `<smell baseline, pasted from review-lenses.md>`

**Spec**
> Review the change in `<context.json>` against this spec: `<path, or the fetched issue text>`. Report: (a) requirements the spec asked for that are missing or partial (`specGap: "missing" | "partial"`); (b) behaviour in the diff that wasn't asked for (`"scope-creep"`); (c) requirements that look implemented but where the implementation looks wrong (`"wrong"`). Quote the spec line for each finding in `rule`. Also return the requirements checklist: every requirement in the spec with status met / partial / missing / wrong / unclear and where it is implemented. Under 400 words of finding text.

If the spec is missing, skip the Spec sub-agent and note this in the final report.

## Aggregating

- Present the axes under `## Quality`, `## Standards` and `## Spec`, each ordered worst-first **within** the axis only.
- End with a one-line summary: total findings per axis, and the worst issue *within each axis* (if any). Don't pick a single winner across axes: that's the reranking the separation exists to prevent. `findings-cache.mjs --load --markdown` and `render-report.mjs` produce exactly this layout.
