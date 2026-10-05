#!/usr/bin/env node
/**
 * post-review.mjs — Post review findings as inline PR comments
 *
 * Usage:
 *   node scripts/post-review.mjs --owner <owner> --repo <repo> --pr <number> --findings '<json>'
 *
 * The --findings argument should be the JSON string from the review output:
 * { "summary": "...", "findings": [ { "file": "...", "line": 42, "severity": "bug", "message": "...", "suggestion": "..." } ] }
 *
 * Posts each finding as an inline review comment on the RIGHT side of the diff.
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
    findings: { type: 'string', short: 'f' },
    'commit-sha': { type: 'string', short: 'c' },
    mention: { type: 'string' },
    help: { type: 'boolean', short: 'H' },
  },
  allowPositionals: true,
});

if (values.help || positionals.length > 0) {
  console.error(`
Usage:
  post-review.mjs --owner <owner> --repo <repo> --pr <number> --findings '<json>' [--commit-sha <sha>] [--mention login1,login2]

Options:
  -o, --owner        Repository owner (required)
  -r, --repo         Repository name (required)
  -p, --pr           PR number (required)
  -f, --findings     JSON string with { summary, findings[] } (required)
  -c, --commit-sha   Specific commit SHA to comment on (default: PR head SHA)
      --mention      Comma-separated GitHub logins used as a FALLBACK — only
                      when a finding has no line, its line isn't part of the
                      diff, or git blame can't resolve a GitHub login for
                      that line. Each inline comment normally mentions
                      whoever's blame actually covers that line, not this
                      list (typically the PR's assignees, or its author).
  -H, --help         Show help
`);
  exit(values.help ? 0 : 1);
}

if (!values.owner || !values.repo || !values.pr || !values.findings) {
  console.error('Error: --owner, --repo, --pr, and --findings are required');
  exit(1);
}

let findingsData;
try {
  findingsData = JSON.parse(values.findings);
} catch (e) {
  console.error('Error: --findings must be valid JSON');
  exit(1);
}

if (!findingsData.findings || !Array.isArray(findingsData.findings)) {
  console.error('Error: findings must be an array');
  exit(1);
}

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

async function main() {
  const owner = values.owner;
  const repo = values.repo;
  const prNumber = values.pr;
  const findings = findingsData.findings;
  const providedSha = values['commit-sha'];
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
  // part of the diff hunk for that file.
  const diffOutput = run('gh', ['pr', 'diff', prNumber, '--repo', `${owner}/${repo}`]);
  const diffableLines = buildDiffableLineSet(diffOutput);

  console.log(`Posting ${findings.length} findings to PR #${prNumber} (commit ${commitSha})...`);

  let posted = 0;
  let failed = 0;

  for (const finding of findings) {
    try {
      const { file, line, severity, message, suggestion } = finding;

      if (!file) {
        console.warn(`Skipping finding without file: ${message}`);
        failed++;
        continue;
      }

      const inDiff = line !== null && line !== undefined && diffableLines[file]?.has(line);

      if (!inDiff) {
        // Fallback: no line, or the line isn't part of the diff — post as a
        // general PR comment instead (inline comments require a diff line).
        // No specific line means no one specific to blame, so use the
        // fallback mention list as-is.
        if (line !== null && line !== undefined) {
          console.warn(`Line ${line} in ${file} is not part of the diff; posting as a general comment`);
        }
        await postGeneralComment(owner, repo, prNumber, `**${file}${line ? `:${line}` : ''}**\n\n${formatCommentBody(message, suggestion, severity, mentionLogins)}`);
      } else {
        const blamedLogin = blameLoginForLine(owner, repo, commitSha, file, line);
        const commentMentions = blamedLogin ? [blamedLogin] : mentionLogins;
        if (!blamedLogin && mentionLogins.length) {
          console.warn(`Could not blame ${file}:${line} to a GitHub user; falling back to ${mentionLogins.join(', ')}`);
        }
        await postInlineComment(owner, repo, prNumber, commitSha, file, line, message, suggestion, severity, commentMentions);
      }

      posted++;
      console.log(`  ✓ Posted: ${file}${line ? `:${line}` : ''} [${severity}]`);
    } catch (err) {
      failed++;
      console.error(`  ✗ Failed: ${finding.file || 'unknown'} — ${err.message}`);
    }
  }

  console.log(`\nDone: ${posted} posted, ${failed} failed`);

  if (findingsData.summary) {
    // Post summary as a general PR comment
    const mentionLine = mentionLogins.length ? `${mentionLogins.map((l) => `@${l}`).join(' ')}\n\n` : '';
    await postGeneralComment(owner, repo, prNumber, `${mentionLine}## Code Review Summary\n\n${findingsData.summary}`);
    console.log('  ✓ Posted summary as general comment');
  }
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

    if (line.match(/^--- a\//)) continue;
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

async function postInlineComment(owner, repo, prNumber, commitSha, file, line, message, suggestion, severity, mentionLogins) {
  const body = formatCommentBody(message, suggestion, severity, mentionLogins);

  gh([
    '--method', 'POST',
    `repos/${owner}/${repo}/pulls/${prNumber}/comments`,
    '-f', `body=${body}`,
    '-f', `commit_id=${commitSha}`,
    '-f', `path=${file}`,
    '-f', `side=RIGHT`,
    '-F', `line=${line}`,
  ]);
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

function formatCommentBody(message, suggestion, severity, mentionLogins = []) {
  const severityLabel = severity.charAt(0).toUpperCase() + severity.slice(1);
  let body = `**${severityLabel}**: ${message}`;
  if (suggestion) {
    body += `\n\n> **Suggestion**: ${suggestion}`;
  }
  if (mentionLogins.length) {
    body += `\n\ncc ${mentionLogins.map((l) => `@${l}`).join(' ')}`;
  }
  body += `\n\n---\n*Posted by automated code review*`;
  return body;
}

main().catch(err => {
  console.error('Error:', err.message);
  exit(1);
});