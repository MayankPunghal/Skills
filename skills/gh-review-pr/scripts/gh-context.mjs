#!/usr/bin/env node
/**
 * gh-context.mjs — Reusable GitHub/PR context gathering
 * Used by both review-pr and create-pr slash commands.
 *
 * Modes:
 *   --pr <number|url>       : Fetch PR context (review mode). A full PR URL also sets --owner / --repo.
 *   --base <branch> --head <branch> : Fetch branch comparison (create-pr mode)
 *   --since <ref> [--wip]   : Local changes since a commit / branch / tag (merge-base, three-dot), run inside
 *                             the repository; --wip also includes uncommitted (staged + unstaged) changes and
 *                             lists untracked files. --owner / --repo not required.
 *
 * Common:
 *   --owner <owner> --repo <repo>   (default: the GitHub repository of the current folder, via `gh repo view`)
 *   --json                  : Output JSON (default)
 *
 * Review output also carries what a complete review needs besides the diff: linked issues (the spec),
 * references it could not fetch (Jira keys, GitLab !N), spec-file candidates matching the branch name,
 * CI check results, existing review comments (so findings are not posted twice), the repository's
 * documented standards files, the lint / format tooling that already enforces rules, and a coverage block
 * listing every file that was excluded, truncated or sent without a patch, so nothing is silently skipped.
 *
 * Fails early, with a message saying what to do, on: gh missing or not logged in, a ref that does not
 * resolve, an empty change.
 */

import { spawnSync } from 'node:child_process';
import { parseArgs } from 'node:util';
import { exit } from 'node:process';
import { existsSync, readdirSync } from 'node:fs';

const { values, positionals } = parseArgs({
  args: process.argv.slice(2),
  options: {
    owner: { type: 'string', short: 'o' },
    repo: { type: 'string', short: 'r' },
    pr: { type: 'string', short: 'p' },
    base: { type: 'string', short: 'b' },
    head: { type: 'string', short: 'h' },
    since: { type: 'string', short: 's' },
    wip: { type: 'boolean', default: false },
    json: { type: 'boolean', default: true },
    help: { type: 'boolean', short: 'H' },
  },
  allowPositionals: true,
});

if (values.help || positionals.length > 0) {
  console.error(`
Usage:
  gh-context.mjs [--owner <owner> --repo <repo>] --pr <number|url>
  gh-context.mjs [--owner <owner> --repo <repo>] --base <branch> --head <branch>
  gh-context.mjs --since <ref> [--wip]   (local: changes since a commit, branch or tag)

Options:
  -o, --owner    Repository owner (default: this folder's GitHub repository)
  -r, --repo     Repository name (default: this folder's GitHub repository)
  -p, --pr       PR number or full PR URL (review mode)
  -b, --base     Base branch (create-pr mode)
  -h, --head     Head branch (create-pr mode)
  -s, --since    Commit / branch / tag to diff against locally (merge-base, three-dot)
      --wip      With --since: include uncommitted changes and list untracked files
      --json     Output JSON (default: true)
  -H, --help     Show help
`);
  exit(values.help ? 0 : 1);
}

// A PR URL carries owner, repo and number: https://github.com/<owner>/<repo>/pull/<n>[/files...]
if (values.pr && !/^\d+$/.test(values.pr)) {
  const m = values.pr.match(/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/);
  if (!m) {
    console.error(`Error: --pr must be a number or a PR URL like https://github.com/owner/repo/pull/42 (got "${values.pr}")`);
    exit(1);
  }
  values.owner = values.owner || m[1];
  values.repo = values.repo || m[2];
  values.pr = m[3];
}

const isReviewMode = Boolean(values.pr);
const isCreateMode = Boolean(values.base && values.head);
const isLocalMode = Boolean(values.since);

if (!isReviewMode && !isCreateMode && !isLocalMode) {
  console.error('Error: Either --pr (review), --base and --head (create-pr) or --since (local review) required');
  exit(1);
}

if (isReviewMode && isCreateMode) {
  console.error('Error: Cannot use --pr with --base/--head');
  exit(1);
}

if (values.wip && !isLocalMode) {
  console.error('Error: --wip only applies to --since (local review)');
  exit(1);
}

function run(cmd, args, opts = {}) {
  const result = spawnSync(cmd, args, { encoding: 'utf8', maxBuffer: 50 * 1024 * 1024, ...opts });
  if (result.error) {
    if (result.error.code === 'ENOENT') {
      throw new Error(`'${cmd}' is not installed or not on PATH.${cmd === 'gh' ? ' Install the GitHub CLI (https://cli.github.com) and run `gh auth login`.' : ''}`);
    }
    throw new Error(`Command failed: ${cmd} ${args.join(' ')}\n${result.error.message}`);
  }
  if (result.status !== 0) {
    const stderr = result.stderr?.toString().trim() || '(no stderr)';
    throw new Error(`Command exited ${result.status}: ${cmd} ${args.join(' ')}\n${stderr}`);
  }
  return result.stdout.trim();
}

function runJson(cmd, args) {
  return JSON.parse(run(cmd, args));
}

function gh(args) {
  return run('gh', ['api', ...args]);
}

function ghJson(args) {
  return JSON.parse(gh(args));
}

// Every page of a list endpoint (GitHub returns 30 items per page by default: a PR with more files or
// commits than that used to be reviewed without the rest, silently).
function ghPaged(path) {
  const sep = path.includes('?') ? '&' : '?';
  const pages = JSON.parse(run('gh', ['api', '--paginate', '--slurp', `${path}${sep}per_page=100`]));
  return pages.flat();
}

function tryRun(cmd, args) {
  try { return run(cmd, args); } catch { return null; }
}

// Files that document how code should be written here; the Standards axis reads them (repo rules beat the
// built-in smell baseline). Matched by name in the root, .github/, docs/ and docs/agents/.
const STANDARDS_NAME = /^(contributing|coding[-_ ]?standards?|code[-_ ]?style|style[-_ ]?guide|conventions|guidelines|agents|claude|copilot-instructions|architecture|\.editorconfig)(\.(md|txt|rst))?$/i;

// Config of tools that already enforce rules (linters, formatters, analyzers, hooks): the Standards axis
// skips anything these enforce, instead of repeating what CI or the editor already reports.
const TOOLING_NAME = /^(\.eslintrc(\..+)?|eslint\.config\.\w+|\.prettierrc(\..+)?|prettier\.config\.\w+|biome\.jsonc?|\.stylelintrc(\..+)?|stylelint\.config\.\w+|\.editorconfig|tsconfig\.json|ruff\.toml|\.ruff\.toml|pyproject\.toml|setup\.cfg|\.flake8|\.pylintrc|mypy\.ini|\.golangci\.ya?ml|\.rubocop\.yml|\.globalconfig|stylecop\.json|directory\.build\.props|\.clang-format|\.clang-tidy|rustfmt\.toml|clippy\.toml|\.pre-commit-config\.yaml|\.markdownlint(\..+)?|\.sqlfluff|detekt\.yml|checkstyle\.xml|\.swiftlint\.yml|\.husky|lefthook\.ya?ml)$/i;

// Where the repo says how to read its issue tracker when issues are not on GitHub (Jira, Linear, GitLab ...).
const ISSUE_TRACKER_DOC = 'docs/agents/issue-tracker.md';

// Folders that hold specs, plans and design notes; a file there whose name shares words with the branch
// name is offered as a spec candidate (the model confirms it before using it).
const SPEC_DIRS = /^(docs|specs?|\.scratch|rfcs?|design|plans?|adr|decisions)\//i;
const BRANCH_NOISE = new Set(['feat', 'feature', 'features', 'fix', 'fixes', 'bugfix', 'hotfix', 'chore', 'refactor', 'docs', 'doc',
  'test', 'tests', 'wip', 'main', 'master', 'develop', 'dev', 'release', 'users', 'user', 'patch', 'update', 'add', 'the', 'and', 'for']);

// Ticket references GitHub cannot resolve: Jira-style keys (ABC-123) and GitLab merge requests (!67).
// Reported so the model fetches them through the repo's issue-tracker doc or asks the user.
const FOREIGN_REF = /\b([A-Z][A-Z0-9]{1,9}-\d+)\b|(?:^|\s)(![0-9]+)\b/g;

// --- Exclusion patterns for diff filtering ---
// (^|/) so a top-level folder (bin/, build/) is excluded as well as a nested one.
const EXCLUDE_PATTERNS = [
  /package-lock\.json$/,
  /yarn\.lock$/,
  /pnpm-lock\.yaml$/,
  /pnpm-lock\.json$/,
  /\.min\.(js|css|map)$/,
  /(^|\/)packages\//,
  /(^|\/)node_modules\//,
  /(^|\/)bin\//,
  /(^|\/)obj\//,
  /(^|\/)dist\//,
  /(^|\/)build\//,
  /\.dll$/,
  /\.exe$/,
  /\.pdb$/,
  /\.jar$/,
];

function shouldExclude(filename) {
  return EXCLUDE_PATTERNS.some(p => p.test(filename));
}

// Cap the diff: 500 lines per file, 4,000 in total. Most findings need only a few lines around the change;
// fetch-file.mjs (or the local file) goes past the cap where a finding needs it. Each cap leaves exactly one
// marker line, and an excluded file is dropped whole (header and body).
function truncateDiff(diff, maxLinesPerFile = 500, maxTotalLines = 4000) {
  const output = [];
  let totalKept = 0;
  let skipping = false;
  let fileLines = 0;
  let fileMarked = false;
  let totalMarked = false;

  for (const line of diff.split('\n')) {
    const fileMatch = line.match(/^diff --git a\/(.+?) b\/(.+)$/);
    if (fileMatch) {
      skipping = shouldExclude(fileMatch[2]) || shouldExclude(fileMatch[1]);
      fileLines = 0;
      fileMarked = false;
    }
    if (skipping) continue;

    if (totalKept >= maxTotalLines) {
      if (!totalMarked) {
        output.push(`... (truncated: ${maxTotalLines} total line limit reached)`);
        totalMarked = true;
      }
      continue;
    }
    if (fileLines >= maxLinesPerFile) {
      if (!fileMarked) {
        output.push(`... (truncated: ${maxLinesPerFile} line limit reached)`);
        fileMarked = true;
      }
      continue;
    }

    output.push(line);
    fileLines++;
    totalKept++;
  }

  return output.join('\n');
}

// --- Main ---
async function main() {
  if (isLocalMode) {
    console.log(JSON.stringify(fetchLocal(values.since, values.wip), null, 2));
    return;
  }

  ensureGhReady();
  if (!values.owner || !values.repo) {
    // Default to the repository of the current folder, like `gh pr view` does.
    const nwo = tryRun('gh', ['repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner']);
    if (!nwo) throw new Error('--owner and --repo are required (no GitHub repository found for the current folder)');
    [values.owner, values.repo] = nwo.split('/');
  }
  const owner = values.owner;
  const repo = values.repo;

  let result;
  if (isReviewMode) {
    result = await fetchPrContext(owner, repo, values.pr);
  } else {
    result = await fetchBranchComparison(owner, repo, values.base, values.head);
  }

  console.log(JSON.stringify(result, null, 2));
}

function ensureGhReady() {
  // `gh auth token` (output discarded) checks the ACTIVE account only; `gh auth status` also fails when an
  // inactive account's token is stale, which would block a working login.
  const r = spawnSync('gh', ['auth', 'token'], { stdio: ['ignore', 'ignore', 'pipe'], encoding: 'utf8' });
  if (r.error?.code === 'ENOENT') throw new Error('The GitHub CLI (gh) is not installed. Install it from https://cli.github.com, then run `gh auth login`.');
  if (r.status !== 0) throw new Error('gh is not logged in. Run `gh auth login`, then retry.');
}

async function fetchPrContext(owner, repo, prNumber) {
  // Get PR metadata
  const pr = ghJson([
    `repos/${owner}/${repo}/pulls/${prNumber}`,
    '--jq', '{number: .number, title: .title, body: .body, baseRef: .base.ref, headRef: .head.ref, headSha: .head.sha, baseSha: .base.sha, headRepo: .head.repo.full_name, url: .html_url, state: .state, merged: .merged, draft: .draft, author: .user.login, assignees: [.assignees[].login], requestedReviewers: [.requested_reviewers[].login], labels: [.labels[].name], changedFiles: .changed_files}'
  ]);

  // Get commits and files: every page (the API caps a PR's file list at 3,000 files)
  const commitsRaw = ghPaged(`repos/${owner}/${repo}/pulls/${prNumber}/commits`)
    .map(c => ({ sha: c.sha, message: c.commit.message, author: c.commit.author?.name, login: c.author?.login ?? null, date: c.commit.author?.date }));
  const filesRaw = ghPaged(`repos/${owner}/${repo}/pulls/${prNumber}/files`)
    .map(f => ({ filename: f.filename, status: f.status, additions: f.additions, deletions: f.deletions, patch: f.patch ?? null, ...(f.previous_filename ? { previousFilename: f.previous_filename } : {}) }));

  if (!filesRaw.length) {
    throw new Error(`PR #${prNumber} changes no files: nothing to review.`);
  }

  // Raw diff. GitHub refuses the diff media type for very large PRs (HTTP 406, "diff exceeded the maximum
  // number of files / lines"); rebuild it from the per-file patches then, so a big PR is still reviewed.
  let diffRaw = tryRun('gh', ['pr', 'diff', prNumber, '--repo', `${owner}/${repo}`]);
  let diffSource = 'gh pr diff';
  if (diffRaw === null) {
    diffRaw = filesRaw.filter(f => f.patch).map(f => `diff --git a/${f.previousFilename || f.filename} b/${f.filename}\n--- a/${f.previousFilename || f.filename}\n+++ b/${f.filename}\n${f.patch}`).join('\n');
    diffSource = 'per-file patches (GitHub refused the full diff: too large)';
  }

  // Filter and cap diff
  const diff = truncateDiff(diffRaw);

  // Filter files list to match diff (exclude same patterns)
  const files = filesRaw.filter(f => !shouldExclude(f.filename));

  const repoFiles = remoteRepoFiles(owner, repo, pr.headSha);
  const checks = checkSummary(owner, repo, prNumber);
  const refs = linkedIssues(owner, repo, prNumber, pr.body, commitsRaw, pr.headRef, ghIssueFetcher(owner, repo));

  return {
    mode: 'pr',
    pr,
    commits: commitsRaw,
    diff,
    files,
    linkedIssues: refs.issues,
    unresolvedRefs: refs.unresolved,
    specCandidates: specCandidates(repoFiles.all, pr.headRef, pr.title),
    checks,
    existingComments: existingComments(owner, repo, prNumber),
    standards: repoFiles.standards,
    tooling: repoFiles.tooling,
    issueTrackerDoc: repoFiles.issueTrackerDoc,
    coverage: { ...coverageOf(filesRaw, diff), diffSource, apiFileCapReached: filesRaw.length >= 3000 },
    notes: prNotes(pr, checks),
    stats: {
      filesChanged: files.length,
      insertions: files.reduce((s, f) => s + f.additions, 0),
      deletions: files.reduce((s, f) => s + f.deletions, 0),
    },
  };
}

async function fetchBranchComparison(owner, repo, base, head) {
  // Get comparison
  // `author.login` is the commit's linked GitHub account (null if GitHub
  // can't match the commit's email to one) - distinct from
  // `commit.author.name`, which is just the git identity string and isn't
  // usable for @mentions or as a PR assignee.
  const comparison = ghJson([
    `repos/${owner}/${repo}/compare/${base}...${head}`,
    '--jq', '{commits: [.commits[] | {sha: .sha, message: .commit.message, author: .commit.author.name, login: .author.login, date: .commit.author.date}], files: [.files[] | {filename: .filename, status: .status, additions: .additions, deletions: .deletions, patch: .patch}], stats: {filesChanged: (.files | length), insertions: (.files | map(.additions) | add), deletions: (.files | map(.deletions) | add)} }'
  ]);

  // Build diff entirely from the GitHub compare API's per-file patches — no
  // local clone/checkout of either branch required (this used to also shell
  // out to `git diff --merge-base base...head`, but that git invocation was
  // both broken — --merge-base doesn't accept a `...` range — and unused,
  // since the diff returned below was always built from `comparison.files`).
  let diffParts = [];
  for (const file of comparison.files) {
    if (!shouldExclude(file.filename) && file.patch) {
      diffParts.push(`diff --git a/${file.filename} b/${file.filename}`);
      diffParts.push(file.patch);
    }
  }
  const diff = truncateDiff(diffParts.join('\n'));

  // Filter files
  const files = comparison.files.filter(f => !shouldExclude(f.filename));

  return {
    mode: 'compare',
    base,
    head,
    commits: comparison.commits,
    diff,
    files,
    stats: comparison.stats,
  };
}

// --- Review context beyond the diff ---

function ghIssueFetcher(owner, repo) {
  return (o, r, n) => {
    const issue = tryRun('gh', ['api', `repos/${o || owner}/${r || repo}/issues/${n}`, '--jq', '{title: .title, body: .body, url: .html_url, state: .state, pr: (.pull_request != null)}']);
    return issue ? JSON.parse(issue) : null;
  };
}

function linkedIssues(owner, repo, prNumber, body, commits, branch, fetchIssue) {
  // Issues GitHub links as "closing", plus #N / owner/repo#N references in the description and commit
  // messages, plus an issue number at the start of the branch name (123-add-login, feature/123_x).
  const refs = new Map();
  const unresolved = new Set();
  if (owner && prNumber) {
    const q = `query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n){closingIssuesReferences(first:20){nodes{number title body url state repository{nameWithOwner}}}}}}`;
    const gql = tryRun('gh', ['api', 'graphql', '-f', `query=${q}`, '-F', `o=${owner}`, '-F', `r=${repo}`, '-F', `n=${prNumber}`]);
    for (const n of (gql ? JSON.parse(gql).data?.repository?.pullRequest?.closingIssuesReferences?.nodes : null) || []) {
      const ref = `${n.repository.nameWithOwner}#${n.number}`;
      refs.set(ref, { ref, title: n.title, body: (n.body || '').slice(0, 4000), url: n.url, state: n.state, closing: true, source: 'closing reference' });
    }
  }
  const here = owner ? `${owner}/${repo}` : '';
  const candidates = [];
  const text = [body || '', ...commits.map(c => c.message || '')].join('\n');
  for (const m of text.matchAll(/(?:([\w.-]+\/[\w.-]+))?#(\d+)\b/g)) candidates.push({ nwo: m[1] || here, n: m[2], source: 'mentioned' });
  const bm = (branch || '').match(/(?:^|\/)(\d+)[-_]/);
  if (bm) candidates.push({ nwo: here, n: bm[1], source: 'branch name' });
  for (const c of candidates) {
    const full = `${c.nwo}#${c.n}`;
    if (refs.has(full) || refs.size >= 20 || (c.nwo === here && c.n === String(prNumber))) continue;
    const [o, r] = c.nwo ? c.nwo.split('/') : [null, null];
    const i = fetchIssue(o, r, c.n);
    if (!i) { unresolved.add(full); continue; }
    if (!i.pr) refs.set(full, { ref: full, title: i.title, body: (i.body || '').slice(0, 4000), url: i.url, state: i.state, closing: false, source: c.source });
  }
  for (const m of [text, branch || ''].join('\n').matchAll(FOREIGN_REF)) unresolved.add(m[1] || m[2]);
  return { issues: [...refs.values()], unresolved: [...unresolved] };
}

function specCandidates(paths, branch, title) {
  const words = new Set(`${branch || ''} ${title || ''}`.toLowerCase().split(/[^a-z0-9]+/)
    .filter(w => w.length >= 3 && !BRANCH_NOISE.has(w) && !/^v?\d+$/.test(w)));
  if (!words.size) return [];
  const scored = [];
  for (const p of paths) {
    if (!SPEC_DIRS.test(p) || !/\.(md|mdx|txt|rst|adoc)$/i.test(p)) continue;
    const name = p.toLowerCase().split(/[^a-z0-9]+/);
    const hits = [...words].filter(w => name.includes(w)).length;
    if (hits) scored.push({ path: p, hits });
  }
  return scored.sort((a, b) => b.hits - a.hits || a.path.length - b.path.length).slice(0, 10).map(s => s.path);
}

function checkSummary(owner, repo, prNumber) {
  // `gh pr checks` exits non-zero when checks fail or are pending; its JSON is still what we want.
  const r = spawnSync('gh', ['pr', 'checks', String(prNumber), '--repo', `${owner}/${repo}`, '--json', 'name,state,bucket'], { encoding: 'utf8' });
  let list = [];
  try { list = JSON.parse(r.stdout || '[]'); } catch { return { available: false }; }
  const by = b => list.filter(c => c.bucket === b).map(c => c.name);
  return { available: true, total: list.length, pass: by('pass').length, fail: by('fail'), pending: by('pending'), skipped: by('skipping').length };
}

function existingComments(owner, repo, prNumber) {
  try {
    return ghPaged(`repos/${owner}/${repo}/pulls/${prNumber}/comments`)
      .map(c => ({ path: c.path, line: c.line ?? c.original_line ?? null, user: c.user?.login, body: (c.body || '').slice(0, 300) }));
  } catch { return []; }
}

function classifyRepoFiles(paths) {
  const top = paths.filter(p => /^(\.github\/|docs\/agents\/|docs\/)?[^/]+$/.test(p));
  return {
    standards: top.filter(p => STANDARDS_NAME.test(p.split('/').pop())),
    tooling: paths.filter(p => !p.includes('/') || p.startsWith('.github/')).filter(p => TOOLING_NAME.test(p.split('/').pop())),
    issueTrackerDoc: paths.includes(ISSUE_TRACKER_DOC) ? ISSUE_TRACKER_DOC : null,
  };
}

function remoteRepoFiles(owner, repo, ref) {
  // One recursive tree read at the PR head: standards, tooling, the issue-tracker doc and spec candidates.
  const out = tryRun('gh', ['api', `repos/${owner}/${repo}/git/trees/${ref}?recursive=1`, '--jq', '{truncated: .truncated, paths: [.tree[] | select(.type == "blob") | .path]}']);
  let all = [];
  let truncated = false;
  if (out) ({ paths: all, truncated } = JSON.parse(out));
  if (!out || truncated) {
    // Very large repositories: the tree is cut off; list the folders that matter directly instead.
    for (const dir of ['', '.github', 'docs', 'docs/agents', 'specs', 'spec', '.scratch']) {
      const ls = tryRun('gh', ['api', `repos/${owner}/${repo}/contents/${dir}?ref=${ref}`, '--jq', '[.[] | select(.type == "file") | .path]']);
      if (ls) all.push(...JSON.parse(ls));
    }
    all = [...new Set(all)];
  }
  return { all, ...classifyRepoFiles(all) };
}

function localRepoFiles() {
  const all = [];
  const walk = (dir, depth) => {
    if (!existsSync(dir) || depth > 4) return;
    for (const f of readdirSync(dir, { withFileTypes: true })) {
      const rel = dir === '.' ? f.name : `${dir}/${f.name}`;
      if (f.isDirectory()) {
        if (dir === '.' ? SPEC_DIRS.test(`${f.name}/`) || f.name === '.github' : true) walk(rel, depth + 1);
      } else if (f.isFile()) all.push(rel);
    }
  };
  walk('.', 0);
  return { all, ...classifyRepoFiles(all) };
}

function prNotes(pr, checks) {
  const notes = [];
  if (pr.draft) notes.push('Draft PR: the author may still be changing it; say so in the summary.');
  if (pr.state === 'closed') notes.push(pr.merged ? 'PR is already merged: findings become follow-up work; ask before posting.' : 'PR is closed without merging: ask before posting.');
  if (checks.available && checks.fail?.length) notes.push(`CI failing: ${checks.fail.join(', ')}. Mention it in the summary; do not re-report what a failing check already reports.`);
  if (checks.available && checks.pending?.length) notes.push(`CI still running: ${checks.pending.join(', ')}.`);
  if (pr.headRepo && pr.headRepo !== `${values.owner}/${values.repo}`) notes.push(`PR comes from the fork ${pr.headRepo}.`);
  return notes;
}

function coverageOf(allFiles, diff) {
  const excluded = allFiles.filter(f => shouldExclude(f.filename)).map(f => f.filename);
  const patchMissing = allFiles.filter(f => !shouldExclude(f.filename) && !f.patch && f.status !== 'removed').map(f => f.filename);
  const shown = new Set([...diff.matchAll(/^diff --git a\/.+? b\/(.+)$/gm)].map(m => m[1]));
  const cut = diff.includes('total line limit reached');
  const notShown = allFiles.filter(f => !shouldExclude(f.filename) && f.status !== 'removed' && !shown.has(f.filename)).map(f => f.filename);
  const truncated = [];
  let cur = null;
  for (const line of diff.split('\n')) {
    const m = line.match(/^diff --git a\/.+? b\/(.+)$/);
    if (m) cur = m[1];
    else if (line.startsWith('... (truncated:') && cur) truncated.push(cur);
  }
  return { filesInChange: allFiles.length, excluded, patchMissing, truncated: [...new Set(truncated)], notInDiff: cut ? notShown : notShown.filter(f => patchMissing.includes(f)),
           note: 'Read every file listed under patchMissing, truncated or notInDiff with fetch-file.mjs (or the local file) before judging it; excluded files are generated or vendored.' };
}

function fetchLocal(since, wip) {
  if (tryRun('git', ['rev-parse', '--is-inside-work-tree']) !== 'true') throw new Error('--since must run inside a git repository (cd into it first)');
  if (!tryRun('git', ['rev-parse', '--verify', '--quiet', `${since}^{commit}`])) throw new Error(`'${since}' does not resolve to a commit here (git rev-parse failed). Check the branch / tag / SHA, or fetch it first.`);
  const mergeBase = tryRun('git', ['merge-base', since, 'HEAD']);
  if (!mergeBase) throw new Error(`'${since}' and HEAD share no history (git merge-base failed)`);
  // Committed: three-dot (merge-base...HEAD). --wip: merge-base against the working tree (staged + unstaged).
  const range = wip ? [mergeBase] : [`${since}...HEAD`];
  const untracked = wip ? (tryRun('git', ['ls-files', '--others', '--exclude-standard']) || '').split('\n').filter(Boolean) : [];
  const raw = run('git', ['diff', '-U3', '--no-renames', ...range]);
  if (!raw.trim() && !untracked.length) throw new Error(`No changes between ${since} and ${wip ? 'the working tree' : 'HEAD'} (git diff is empty)${wip ? '' : '; add --wip to include uncommitted work'}`);
  const log = run('git', ['log', `${since}..HEAD`, '--format=%H%x1f%an%x1f%aI%x1f%B%x1e']);
  const commits = log ? log.split('\x1e').map(s => s.trim()).filter(Boolean).map(l => { const [sha, author, date, message] = l.split('\x1f'); return { sha, author, date, message: (message || '').trim() }; }) : [];
  const status = new Map(run('git', ['diff', '--name-status', '--no-renames', ...range]).split('\n').filter(Boolean).map(l => { const [s, p] = l.split('\t'); return [p, s]; }));
  const STATUS = { A: 'added', M: 'modified', D: 'removed', T: 'modified' };
  const allFiles = run('git', ['diff', '--numstat', '--no-renames', ...range]).split('\n').filter(Boolean).map(l => {
    const [a, d, filename] = l.split('\t');
    const st = STATUS[status.get(filename)?.[0]] || 'modified';
    return { filename, status: st, additions: Number(a) || 0, deletions: Number(d) || 0, patch: a === '-' || st === 'removed' ? null : 'local' };
  });
  for (const u of untracked) allFiles.push({ filename: u, status: 'untracked', additions: 0, deletions: 0, patch: null });
  const diff = truncateDiff(raw);
  const branch = tryRun('git', ['rev-parse', '--abbrev-ref', 'HEAD']) || '';
  const repoFiles = localRepoFiles();
  const ghOk = spawnSync('gh', ['auth', 'token'], { stdio: ['ignore', 'ignore', 'ignore'] }).status === 0;
  // In a GitHub checkout, `gh issue view` resolves #N for the spec; elsewhere the refs are listed as unresolved.
  const fetchIssue = ghOk
    ? (o, r, n) => { const j = tryRun('gh', ['issue', 'view', n, ...(o ? ['--repo', `${o}/${r}`] : []), '--json', 'title,body,url,state']); return j ? JSON.parse(j) : null; }
    : () => null;
  const refs = linkedIssues(null, null, null, '', commits, branch, fetchIssue);
  const openPr = ghOk ? tryRun('gh', ['pr', 'view', '--json', 'number,url', '--jq', '"\\(.number) \\(.url)"']) : null;
  return { mode: 'local', since, mergeBase, head: wip ? 'WORKING TREE' : run('git', ['rev-parse', 'HEAD']), wip, branch,
           openPr: openPr ? { number: Number(openPr.split(' ')[0]), url: openPr.split(' ')[1] } : null,
           commits, diff, files: allFiles.filter(f => !shouldExclude(f.filename)),
           linkedIssues: refs.issues, unresolvedRefs: refs.unresolved, specCandidates: specCandidates(repoFiles.all, branch, ''),
           standards: repoFiles.standards, tooling: repoFiles.tooling, issueTrackerDoc: repoFiles.issueTrackerDoc,
           coverage: { ...coverageOf(allFiles, diff), untracked },
           stats: { filesChanged: allFiles.length, insertions: allFiles.reduce((s, f) => s + f.additions, 0), deletions: allFiles.reduce((s, f) => s + f.deletions, 0) } };
}

main().catch(err => {
  console.error('Error:', err.message);
  exit(1);
});
