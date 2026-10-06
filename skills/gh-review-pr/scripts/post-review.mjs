#!/usr/bin/env node
/**
 * post-review.mjs — Post review findings as inline PR comments
 *
 * Usage:
 *   node scripts/post-review.mjs --owner <owner> --repo <repo> --pr <number> --findings-file <path> [--dry-run]
 *   node scripts/post-review.mjs --owner <owner> --repo <repo> --pr <number> --findings '<json>'
 *
 * The findings are the review output (contract: references/output-and-posting.md):
 * { "summary": "...", "findings": [ { "axis": "quality", "file": "...", "line": 42, "title": "...", "issue": "...",
 *   "riskIfIgnored": "...", "solutions": ["..."], "impact": "high", "likelihood": "medium", "severity": "bug" } ] }
 * The older shape ({ file, line, severity, message, suggestion }) still works.
 *
 * Posts each finding as an inline review comment on the RIGHT side of the diff (a multi-line comment when
 * the finding has endLine), as a general PR comment when its line is not in the diff, then one summary
 * comment with the per-axis tables. Skips a finding already posted on the same file and line, and a summary
 * already posted for the same head commit, so a re-run does not duplicate comments.
 */

import { spawnSync } from 'node:child_process';
import { parseArgs } from 'node:util';
import { exit } from 'node:process';
import { readFindingsArg, normalize, validate, commentBody, summaryMarkdown, RISK_LABEL } from './findings-lib.mjs';

const { values, positionals } = parseArgs({
  args: process.argv.slice(2),
  options: {
    owner: { type: 'string', short: 'o' },
    repo: { type: 'string', short: 'r' },
    pr: { type: 'string', short: 'p' },
    findings: { type: 'string', short: 'f' },
    'findings-file': { type: 'string', short: 'F' },
    'commit-sha': { type: 'string', short: 'c' },
    mention: { type: 'string' },
    'dry-run': { type: 'boolean', default: false },
    'no-summary': { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'H' },
  },
  allowPositionals: true,
});

if (values.help || positionals.length > 0) {
  console.error(`
Usage:
  post-review.mjs --owner <owner> --repo <repo> --pr <number> (--findings-file <path> | --findings '<json>')
                  [--commit-sha <sha>] [--mention login1,login2] [--dry-run] [--no-summary]

Options:
  -o, --owner          Repository owner (required)
  -r, --repo           Repository name (required)
  -p, --pr             PR number (required)
  -F, --findings-file  Path to the findings JSON (preferred: no shell-quoting limits)
  -f, --findings       JSON string with { summary, findings[] }
  -c, --commit-sha     Specific commit SHA to comment on (default: PR head SHA)
      --mention        Comma-separated GitHub logins used as a FALLBACK — only
                        when a finding has no line, its line isn't part of the
                        diff, or git blame can't resolve a GitHub login for
                        that line. Each inline comment normally mentions
                        whoever's blame actually covers that line, not this
                        list (typically the PR's assignees, or its author).
      --dry-run        Print every comment that would be posted (and where); post nothing
      --no-summary     Skip the summary comment
  -H, --help           Show help
`);
  exit(values.help ? 0 : 1);
}

if (!values.owner || !values.repo || !values.pr) {
  console.error('Error: --owner, --repo, --pr and --findings-file (or --findings) are required');
  exit(1);
}

let findingsData;
try {
  findingsData = readFindingsArg(values);
} catch (e) {
  console.error(`Error: ${e.message}`);
  exit(1);
}

const check = validate(findingsData);
for (const w of check.warnings) console.warn(`  ! ${w}`);
if (check.errors.length) {
  console.error(`Error: the findings do not match the contract (references/output-and-posting.md):\n  - ${check.errors.join('\n  - ')}`);
  exit(1);
}
findingsData = normalize(findingsData);

function run(cmd, args, opts = {}) {
  const result = spawnSync(cmd, args, { encoding: 'utf8', maxBuffer: 10 * 1024 * 1024, ...opts });
  if (result.error) {
    throw new Error(`Command failed: ${cmd} ${args.join(' ')}\n${result.error.message}`);
  }
  if (result.status !== 0) {
    const stderr = result.stderr?.toString().trim() || '(no stderr)';
    throw new Error(`Command exited ${result.status}: ${cmd} ${args.join(' ')}\n${stderr}`);
  }
  return result.stdout.trim();
}

function gh(args) {
  return run('gh', ['api', ...args]);
}

function ghJson(args) {
  return JSON.parse(gh(args));
}

function ghPaged(path) {
  const sep = path.includes('?') ? '&' : '?';
  return JSON.parse(run('gh', ['api', '--paginate', '--slurp', `${path}${sep}per_page=100`])).flat();
}

const BLAME_QUERY = `
query($owner: String!, $repo: String!, $expr: String!, $path: String!) {
  repository(owner: $owner, name: $repo) {
    object(expression: $expr) {
      ... on Commit {
        blame(path: $path) {
          ranges {
            startingLine
            endingLine
            commit { author { user { login } } }
          }
        }
      }
    }
  }
}`;

const blameCache = new Map(); // "ref:path" -> ranges[] | null

function blameRangesForFile(owner, repo, ref, path) {
  const key = `${ref}:${path}`;
  if (blameCache.has(key)) return blameCache.get(key);

  let ranges = null;
  try {
    const result = spawnSync('gh', [
      'api', 'graphql',
      '-f', `query=${BLAME_QUERY}`,
      '-f', `owner=${owner}`,
      '-f', `repo=${repo}`,
      '-f', `expr=${ref}`,
      '-f', `path=${path}`,
    ], { encoding: 'utf8', maxBuffer: 10 * 1024 * 1024 });
    if (result.status === 0) {
      const data = JSON.parse(result.stdout);
      ranges = data?.data?.repository?.object?.blame?.ranges ?? null;
    }
  } catch {
    // ranges stays null — caller falls back to the --mention list
  }

  blameCache.set(key, ranges);
  return ranges;
}

// Who actually wrote the line a finding points at, per git blame at the
// PR's head commit — this is who should be @-mentioned on that specific
// comment, not the whole assignee list.
function blameLoginForLine(owner, repo, ref, path, line) {
  const ranges = blameRangesForFile(owner, repo, ref, path);
  if (!ranges) return null;
  const range = ranges.find((r) => line >= r.startingLine && line <= r.endingLine);
  return range?.commit?.author?.user?.login ?? null;
}

// A finding counts as already posted when an existing comment on the same file (and line, for inline
// comments) contains the start of its title or issue text. Normalised so whitespace changes don't matter.
function squash(s = '') {
  return String(s).toLowerCase().replace(/\s+/g, ' ').trim();
}

function alreadyPosted(existing, finding) {
  const needles = [finding.title, finding.issue].map(t => squash(t).slice(0, 60)).filter(n => n.length >= 12);
  return existing.some(c => {
    if (c.path && c.path !== finding.file) return false;
    if (c.path && finding.line && c.line && c.line !== (finding.endLine || finding.line) && c.line !== finding.line) return false;
    const body = squash(c.body);
    return needles.some(n => body.includes(n));
  });
}

async function main() {
  const owner = values.owner;
  const repo = values.repo;
  const prNumber = values.pr;
  const findings = findingsData.findings;
  const providedSha = values['commit-sha'];
  const dryRun = values['dry-run'];
  const mentionLogins = values.mention
    ? [...new Set(values.mention.split(',').map((s) => s.trim()).filter(Boolean))]
    : [];

  // Get PR details to find the head SHA if not provided
  let commitSha = providedSha;
  if (!commitSha) {
    const pr = ghJson([
      `repos/${owner}/${repo}/pulls/${prNumber}`,
      '--jq', '{headSha: .head.sha}'
    ]);
    commitSha = pr.headSha;
  }

  // Get the diff so we can check whether a finding's line actually appears in
  // it — GitHub's create-review-comment endpoint rejects a `line` that isn't
  // part of the diff hunk for that file. Very large PRs: GitHub refuses the
  // full diff, so rebuild it from the per-file patches.
  let diffOutput;
  try {
    diffOutput = run('gh', ['pr', 'diff', prNumber, '--repo', `${owner}/${repo}`]);
  } catch {
    diffOutput = ghPaged(`repos/${owner}/${repo}/pulls/${prNumber}/files`)
      .filter(f => f.patch).map(f => `+++ b/${f.filename}\n${f.patch}`).join('\n');
  }
  const diffableLines = buildDiffableLineSet(diffOutput);

  // Existing comments: inline review comments and general PR comments, to skip duplicates on a re-run.
  const existing = [
    ...ghPaged(`repos/${owner}/${repo}/pulls/${prNumber}/comments`).map(c => ({ path: c.path, line: c.line ?? c.original_line, body: c.body })),
    ...ghPaged(`repos/${owner}/${repo}/issues/${prNumber}/comments`).map(c => ({ path: null, line: null, body: c.body })),
  ];

  console.log(`${dryRun ? '[dry run] Would post' : 'Posting'} ${findings.length} findings to PR #${prNumber} (commit ${commitSha})...`);

  let posted = 0;
  let failed = 0;
  let skipped = 0;

  for (const finding of findings) {
    try {
      const { file, line, endLine } = finding;

      if (!file) {
        console.warn(`Skipping finding without file: ${finding.issue}`);
        failed++;
        continue;
      }

      if (alreadyPosted(existing, finding)) {
        skipped++;
        console.log(`  = Already on the PR, skipped: ${file}${line ? `:${line}` : ''} — ${finding.title}`);
        continue;
      }

      const hasLine = line !== null && line !== undefined;
      const inDiff = hasLine && diffableLines[file]?.has(line);
      // A multi-line comment needs both ends in the diff; otherwise comment on the single line.
      const multi = inDiff && endLine && endLine > line && diffableLines[file]?.has(endLine);

      if (!inDiff) {
        // Fallback: no line, or the line isn't part of the diff — post as a
        // general PR comment instead (inline comments require a diff line).
        // No specific line means no one specific to blame, so use the
        // fallback mention list as-is.
        if (hasLine) {
          console.warn(`Line ${line} in ${file} is not part of the diff; posting as a general comment`);
        }
        const body = commentBody(finding, mentionLogins, { inline: false });
        if (dryRun) printDry(`general comment (${file}${line ? `:${line}` : ''})`, body);
        else await postGeneralComment(owner, repo, prNumber, body);
      } else {
        const blamedLogin = blameLoginForLine(owner, repo, commitSha, file, line);
        const commentMentions = blamedLogin ? [blamedLogin] : mentionLogins;
        if (!blamedLogin && mentionLogins.length) {
          console.warn(`Could not blame ${file}:${line} to a GitHub user; falling back to ${mentionLogins.join(', ')}`);
        }
        // A ```suggestion block replaces exactly the commented lines; drop it when the range was narrowed.
        const f = endLine && endLine > line && !multi ? { ...finding, fix: undefined } : finding;
        const body = commentBody(f, commentMentions, { inline: true });
        if (dryRun) printDry(`inline ${file}:${multi ? `${line}-${endLine}` : line}`, body);
        else await postInlineComment(owner, repo, prNumber, commitSha, file, multi ? endLine : line, multi ? line : null, body);
      }

      posted++;
      if (!dryRun) console.log(`  ✓ Posted: ${file}${line ? `:${line}` : ''} [${RISK_LABEL[finding.risk]} risk, ${finding.axis}]`);
    } catch (err) {
      failed++;
      console.error(`  ✗ Failed: ${finding.file || 'unknown'} — ${err.message}`);
    }
  }

  console.log(`\nDone: ${posted} ${dryRun ? 'would be posted' : 'posted'}, ${skipped} already on the PR, ${failed} failed`);

  if (findingsData.summary && !values['no-summary']) {
    // Post summary as a general PR comment, once per head commit (the hidden marker finds an earlier one).
    const marker = `<!-- gh-review-pr:summary sha=${commitSha} -->`;
    if (existing.some(c => (c.body || '').includes(marker))) {
      console.log('  = Summary for this commit already on the PR, skipped');
    } else {
      const mentionLine = mentionLogins.length ? `${mentionLogins.map((l) => `@${l}`).join(' ')}\n\n` : '';
      const body = `${marker}\n${mentionLine}${summaryMarkdown(findingsData)}`;
      if (dryRun) printDry('summary comment', body);
      else {
        await postGeneralComment(owner, repo, prNumber, body);
        console.log('  ✓ Posted summary as general comment');
      }
    }
  }
  if (failed) exit(1);
}

function printDry(where, body) {
  console.log(`\n----- ${where} -----\n${body}`);
}

// GitHub's `position` field (diff-relative line index) on the pulls/comments
// create endpoint is deprecated and rejected on current repos ("position is
// not a permitted key") — the endpoint now wants the new-file `line` number
// directly plus `side`. This builds, per file, the set of new-file line
// numbers that actually appear in the diff (added or context lines), so we
// know whether a finding's line is safe to comment on inline.
function buildDiffableLineSet(diff) {
  const map = {};
  const lines = diff.split('\n');
  let currentFile = null;
  let inDiff = false;
  let newFileLine = 0;

  for (const line of lines) {
    const fileMatch = line.match(/^\+\+\+ b\/(.+)$/);
    if (fileMatch) {
      currentFile = fileMatch[1];
      inDiff = true;
      newFileLine = 0;
      map[currentFile] = new Set();
      continue;
    }

    if (line.match(/^--- (a\/|\/dev\/null)/)) continue;
    if (!inDiff || !currentFile) continue;

    const hunkMatch = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunkMatch) {
      newFileLine = parseInt(hunkMatch[1], 10) - 1; // incremented below
      continue;
    }

    if (line.startsWith('+')) {
      newFileLine++;
      map[currentFile].add(newFileLine);
    } else if (line.startsWith('-')) {
      // Deleted line - doesn't advance new file line number
    } else if (line.startsWith(' ')) {
      newFileLine++;
      map[currentFile].add(newFileLine);
    }
    // Lines starting with \ (no newline at end of file) - ignore
  }

  return map;
}

async function postInlineComment(owner, repo, prNumber, commitSha, file, line, startLine, body) {
  const args = [
    '--method', 'POST',
    `repos/${owner}/${repo}/pulls/${prNumber}/comments`,
    '-f', `body=${body}`,
    '-f', `commit_id=${commitSha}`,
    '-f', `path=${file}`,
    '-f', `side=RIGHT`,
    '-F', `line=${line}`,
  ];
  // Multi-line comment: `line` is the last line, `start_line` the first (both on the RIGHT side).
  if (startLine) args.push('-F', `start_line=${startLine}`, '-f', 'start_side=RIGHT');
  gh(args);
}

// Body is passed in fully-formed (header/mention already composed by the
// caller) since the two call sites need different wrapping.
async function postGeneralComment(owner, repo, prNumber, body) {
  gh([
    '--method', 'POST',
    `repos/${owner}/${repo}/issues/${prNumber}/comments`,
    '-f', `body=${body}`,
  ]);
}

main().catch(err => {
  console.error('Error:', err.message);
  exit(1);
});
