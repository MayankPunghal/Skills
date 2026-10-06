# Output, report and posting

The findings contract every script reads, how a review is cached, rendered as an HTML report and posted to a PR.

## Contents

- [Findings contract](#findings-contract)
- [Field rules](#field-rules)
- [Caps](#caps)
- [Files and cache](#files-and-cache)
- [HTML report](#html-report)
- [Posting to the PR](#posting-to-the-pr)
- [What a posted comment looks like](#what-a-posted-comment-looks-like)

## Findings contract

Write the review to `findings.json` in this shape (the scripts validate it and refuse malformed findings):

```json
{
  "summary": "2–3 sentence overall assessment. Example: 'The PR adds OAuth2 token refresh but has a race condition in token storage and misses authz checks on the refresh endpoint. Three security findings and one concurrency bug.'",
  "notes": ["Optional lines for the reader, e.g. 'Draft PR' or 'CI failing: lint'"],
  "axes": {
    "quality":   { "status": "reviewed" },
    "standards": { "status": "reviewed", "sources": ["CONTRIBUTING.md", "smell baseline"] },
    "spec":      { "status": "reviewed", "source": "acme/app#123",
                   "requirements": [
                     { "text": "Refresh tokens rotate on every use", "status": "met", "where": "src/Auth/TokenStore.cs:40" },
                     { "text": "Expired refresh tokens return 401", "status": "missing", "finding": "SP1" }
                   ] }
  },
  "findings": [
    {
      "axis": "quality",
      "file": "path/to/file.cs",
      "line": 42,
      "endLine": 45,
      "title": "Token refresh is not atomic",
      "issue": "Concise, specific description of the issue. Reference the exact code pattern and the input or timing that triggers it.",
      "evidence": "the exact line(s) from the head commit",
      "riskIfIgnored": "What happens if this is not addressed: who is affected, how badly, how often.",
      "solutions": ["Recommended fix first.", "An alternative, with its trade-off."],
      "fix": "optional exact replacement for lines line..endLine",
      "impact": "high",
      "likelihood": "medium",
      "severity": "security|bug|design|performance|maintainability",
      "kind": "hard|judgement",
      "confidence": "confirmed|likely",
      "rule": "B. Injection | CONTRIBUTING.md: \"...\" | Smell: Feature Envy | the quoted spec line",
      "specGap": "missing|partial|scope-creep|wrong"
    }
  ]
}
```

The older shape (`file`, `line`, `severity`, `message`, `suggestion`) is still accepted: `message` becomes `issue`, `suggestion` becomes the first solution, a missing `axis` means `quality`, and a missing rating is inferred from `severity`.

## Field rules

- **`line`** = **new-file line number** from the diff (right side), at the head commit. Use `null` for file-level findings. `endLine` (optional) makes it a multi-line comment; both ends must be in the diff for an inline multi-line comment.
- **`title`**: one line, the claim alone: "Token refresh uses non-atomic read-modify-write" — not "There's a bug here".
- **`issue`**: what is wrong and the trigger (input, state, sequence). Inline Markdown (`code`, **bold**, links) is rendered.
- **`evidence`**: the exact code, copied from the file at the head commit, not paraphrased. It is shown as a code block with line numbers.
- **`riskIfIgnored`**: the consequence in plain words, for a reader who will not open the code: "Two concurrent refreshes can both write, and one user's session ends up with another user's token."
- **`solutions`**: one to three specific, actionable fixes, recommended first. "Use `Interlocked.CompareExchange` or a `SemaphoreSlim` to make token update atomic" — not "Fix the race condition".
- **`fix`** (optional): the exact replacement text for `line`..`endLine`, keeping indentation. On GitHub it becomes a one-click "Commit suggestion". Only when the change is small, local and certainly right.
- **`impact` / `likelihood`**: see the matrix in [review-lenses.md](review-lenses.md); the scripts derive `risk` (`critical`, `high`, `medium`, `low`).
- **`kind`**: `judgement` for heuristics (every smell, most design calls); `hard` for definite defects and documented-rule breaches.
- **`confidence`**: `confirmed` when you traced it (read the caller, reproduced the path); `likely` otherwise. Unverifiable suspicions are not findings.
- **`rule`**: Quality → the lens (`A. Concurrency/race conditions`); Standards → the file and rule, or `Smell: <name>`; Spec → the quoted spec line (required).
- **`specGap`**: Spec axis only.
- **`axes.spec.requirements`**: the spec as a checklist, one row per requirement: `text` (quoted or tightly paraphrased from the spec), `status` (`met`, `partial`, `missing`, `wrong`, `unclear` = the code cannot show it), and `where` (file:line that implements it) or `finding` (the id of the finding that explains the gap, e.g. `SP1`). Every requirement appears, met ones included, so the reader sees what was checked, not only what failed.
- **`id`** (optional): ids default to `Q1`, `Q2` … (quality), `ST1` … (standards), `SP1` … (spec), numbered in the order the findings appear within each axis.

## Caps

- **Max 10 findings per axis.** If more exist, keep the 10 with the highest risk (Quality axis: then by severity ordering `security` > `bug` > `design` > `performance` > `maintainability`), and say in `summary` how many were left out.
- Findings are ordered worst-first **within** each axis by the scripts; never rerank across axes.

## Files and cache

- Work folder per review: `~/.claude/gh-review-pr/work/<key>/` holding `context.json` (gh-context output) and `findings.json`. `<key>` is `<owner>-<repo>-pr<N>`, or `<repo-folder>-local-<branch>` for a local review. Never write into the reviewed repository.
- **After producing findings**, always save them (this is what makes a later `post` instant):
  ```bash
  node <skill-base-dir>/scripts/findings-cache.mjs --save --owner <owner> --repo <repo> --pr <number> --head-sha <pr.headSha> --findings-file <work>/findings.json
  ```
  Local reviews: `--key <repo-folder>-local-<branch> --head-sha <head>` instead of owner / repo / pr.
- **Load** (reuse for posting): `--load ... --require-head-sha <current-head-sha>`. Exit 0 → cached review; exit 1 → none; exit 2 → stale (new commits) → re-review. `--markdown` prints the per-axis summary instead of JSON.

## HTML report

```bash
node <skill-base-dir>/scripts/render-report.mjs --findings-file <work>/findings.json --context <work>/context.json --out <report.html> [--markdown <report.md>]
```

- Default `--out`: `~/.claude/gh-review-pr/reports/<key>.html`; use the user's path when they give one.
- One self-contained file: no external fonts, scripts or styles, so it opens offline and is safe to share privately. IBM Plex Sans and Plex Mono are embedded from `scripts/assets/fonts/` (SIL Open Font License, `OFL.txt` beside them). Light and dark themes follow the system; printing expands every finding.
- Design rules it keeps: findings are rows separated by hairlines, not cards; a risk rating is a coloured square plus coloured text, never a filled pill; only real identifiers (commit, file:line, finding ID, code) are monospace; icons are inline SVG, never emoji or Unicode glyphs; zero counts are left out rather than shown greyed.
- It shows: the PR header (author, branches, commit, state), a verdict, counts per risk rating, an impact × likelihood matrix, the three axes with every finding (issue, evidence with line numbers, risk if not addressed, possible fixes, suggested change, rule and rating), risk filters, "Copy as PR comment" per finding, and a "What was reviewed" panel (files, spec sources, standards, tooling, CI).
- File locations link to the exact lines on GitHub at the reviewed commit.

## Posting to the PR

Only with `--post` (or the user choosing "post" when asked), and only after confirmation:

1. Show a preview table of findings (axis, risk, file:line, title).
2. Ask: `Post these N findings as inline comments on PR #<num>? [y/N]`
3. On `y`:
   ```bash
   node <skill-base-dir>/scripts/post-review.mjs --owner <owner> --repo <repo> --pr <number> --findings-file <work>/findings.json --mention <login1,login2>
   ```
   `--dry-run` prints every comment and where it would go, posting nothing: use it when the user wants to see the exact text first.

Pass `--mention` as a **fallback only** — `pr.assignees` (from the context), or `pr.author` if none are set. For each inline comment, the script blames the specific line via `git blame` and mentions whoever actually wrote it, not the whole assignee list; `--mention` only kicks in when a finding has no line, its line isn't in the diff, or blame can't resolve a GitHub login for that line.

What the script does:

- Each finding becomes an **inline review comment** on the `RIGHT` side of the diff (new file), multi-line when `endLine` is set and in the diff, with a `cc @login` line for whoever's blame covers that line. It uses `gh api` with the authenticated user's token.
- A finding whose line is not in the diff (or has no line) becomes a general PR comment headed with its `file:line`.
- **Re-runs do not duplicate:** a finding already present on the same file and line (matching title or issue text) is skipped, and the summary carries a hidden marker per head commit so it is posted once.
- Finally one **summary comment**: per-axis tables (risk, finding, where, if not addressed) and the per-axis one-line totals.
- Exit code 1 if any comment failed to post.

Do not post a top-level review (no `APPROVE`/`REQUEST_CHANGES`) — just comments. Ask before posting on a merged or closed PR (the context `notes` flag it).

## What a posted comment looks like

````markdown
🟠 **High risk** · Token refresh is not atomic

**Issue.** `RefreshAsync` reads `_token`, awaits the HTTP call, then writes `_token`; two concurrent callers both refresh and the slower one overwrites the newer token.

```csharp
var current = _token; var fresh = await _client.RefreshAsync(current); _token = fresh;
```

**Risk if not addressed.** Under load, users are randomly signed out and the identity provider sees duplicate refreshes that can trip its rate limit.

**Possible fixes**
1. Guard the refresh with a `SemaphoreSlim(1,1)` and re-check `_token` after acquiring it. *(recommended)*
2. Cache the in-flight `Task<Token>` so concurrent callers await the same refresh.

<sub>Quality axis · bug · confirmed · rule: A. Concurrency/race conditions · impact high × likelihood medium</sub>

cc @author

---
*Posted by automated code review*
````
