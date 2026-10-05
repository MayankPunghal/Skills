#!/usr/bin/env node
/**
 * gh-context.mjs — Reusable GitHub/PR context gathering
 * Used by both review-pr and create-pr slash commands.
 *
 * Modes:
 *   --pr <number>           : Fetch PR context (review mode)
 *   --base <branch> --head <branch> : Fetch branch comparison (create-pr mode)
 *
 * Common:
 *   --owner <owner> --repo <repo>
 *   --json                  : Output JSON (default)
 */

import { spawnSync } from 'node:child_process';
import { parseArgs } from 'node:util';
import { exit } from 'node:process';

const { values, positionals } = parseArgs({
  args: process.argv.slice(2),
  options: {
    owner: { type: 'string', short: 'o' },
    repo: { type: 'string', short: 'r' },
    pr: { type: 'string', short: 'p' },
    base: { type: 'string', short: 'b' },
    head: { type: 'string', short: 'h' },
    json: { type: 'boolean', default: true },
    help: { type: 'boolean', short: 'H' },
  },
  allowPositionals: true,
});

if (values.help || positionals.length > 0) {
  console.error(`
Usage:
  gh-context.mjs --owner <owner> --repo <repo> --pr <number>
  gh-context.mjs --owner <owner> --repo <repo> --base <branch> --head <branch>

Options:
  -o, --owner    Repository owner (required)
  -r, --repo     Repository name (required)
  -p, --pr       PR number (review mode)
  -b, --base     Base branch (create-pr mode)
  -h, --head     Head branch (create-pr mode)
      --json     Output JSON (default: true)
  -H, --help     Show help
`);
  exit(values.help ? 0 : 1);
}

if (!values.owner || !values.repo) {
  console.error('Error: --owner and --repo are required');
  exit(1);
}

const isReviewMode = Boolean(values.pr);
const isCreateMode = Boolean(values.base && values.head);

if (!isReviewMode && !isCreateMode) {
  console.error('Error: Either --pr (review) or --base and --head (create-pr) required');
  exit(1);
}

if (isReviewMode && isCreateMode) {
  console.error('Error: Cannot use --pr with --base/--head');
  exit(1);
}

function run(cmd, args, opts = {}) {
  const result = spawnSync(cmd, args, { encoding: 'utf8', maxBuffer: 50 * 1024 * 1024, ...opts });
  if (result.error) {
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

// --- Exclusion patterns for diff filtering ---
const EXCLUDE_PATTERNS = [
  /package-lock\.json$/,
  /yarn\.lock$/,
  /pnpm-lock\.yaml$/,
  /pnpm-lock\.json$/,
  /\.min\.(js|css|map)$/,
  /\/packages\//,
  /\/node_modules\//,
  /\/bin\//,
  /\/obj\//,
  /\/dist\//,
  /\/build\//,
  /\.dll$/,
  /\.exe$/,
  /\.pdb$/,
  /\.jar$/,
];

function shouldExclude(filename) {
  return EXCLUDE_PATTERNS.some(p => p.test(filename));
}

function truncateDiff(diff, maxLinesPerFile = 500, maxTotalLines = 4000) {
  const lines = diff.split('\n');
  let totalKept = 0;
  const output = [];
  let inFile = false;
  let fileLines = 0;
  let currentFile = null;

  for (const line of lines) {
    const fileMatch = line.match(/^diff --git a\/(.+) b\/(.+)$/);
    if (fileMatch) {
      inFile = true;
      fileLines = 0;
      currentFile = fileMatch[1];
      if (shouldExclude(currentFile)) {
        inFile = false;
        continue;
      }
    }

    if (inFile) {
      if (fileLines >= maxLinesPerFile) {
        if (fileLines === maxLinesPerFile) {
          output.push(`... (truncated: ${maxLinesPerFile} line limit reached)`);
        }
        continue;
      }
      fileLines++;
    }

    if (totalKept >= maxTotalLines) {
      if (totalKept === maxTotalLines) {
        output.push(`... (truncated: ${maxTotalLines} total line limit reached)`);
      }
      continue;
    }

    output.push(line);
    totalKept++;
  }

  return output.join('\n');
}

// --- Main ---
async function main() {
  const owner = values.owner;
  const repo = values.repo;

  let result = { owner, repo };

  if (isReviewMode) {
    const prNumber = values.pr;
    result = await fetchPrContext(owner, repo, prNumber);
  } else {
    result = await fetchBranchComparison(owner, repo, values.base, values.head);
  }

  console.log(JSON.stringify(result, null, 2));
}

async function fetchPrContext(owner, repo, prNumber) {
  // Get PR metadata
  const pr = ghJson([
    `repos/${owner}/${repo}/pulls/${prNumber}`,
    '--jq', '{number: .number, title: .title, body: .body, baseRef: .base.ref, headRef: .head.ref, headSha: .head.sha, url: .html_url, state: .state, draft: .draft, author: .user.login, assignees: [.assignees[].login]}'
  ]);

  // Get commits
  const commitsRaw = ghJson([
    `repos/${owner}/${repo}/pulls/${prNumber}/commits`,
    '--jq', '[.[] | {sha: .sha, message: .commit.message, author: .commit.author.name, date: .commit.author.date}]'
  ]);

  // Get files
  const filesRaw = ghJson([
    `repos/${owner}/${repo}/pulls/${prNumber}/files`,
    '--jq', '[.[] | {filename: .filename, status: .status, additions: .additions, deletions: .deletions, patch: .patch}]'
  ]);

  // Get raw diff (unfiltered, for processing)
  const diffRaw = run('gh', ['pr', 'diff', prNumber, '--repo', `${owner}/${repo}`]);

  // Filter and cap diff
  const diff = truncateDiff(diffRaw);

  // Filter files list to match diff (exclude same patterns)
  const files = filesRaw.filter(f => !shouldExclude(f.filename));

  return {
    mode: 'pr',
    pr,
    commits: commitsRaw,
    diff,
    files,
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

main().catch(err => {
  console.error('Error:', err.message);
  exit(1);
});