#!/usr/bin/env node
/**
 * findings-cache.mjs — persist a completed review's {summary, findings} to
 * disk, keyed by PR, so a later `--post` call can post without re-running
 * the (expensive) review pass in the same or a different session.
 *
 * Cache location: ~/.claude/gh-review-pr/findings/<owner>-<repo>-pr<N>.json
 * (local reviews: keyed by --key <repo-folder>-local-<branch>)
 *
 * Save:
 *   node findings-cache.mjs --save --owner <o> --repo <r> --pr <n> \
 *     --head-sha <sha> --findings-file <path>        (or --findings '<json>')
 *
 * Load:
 *   node findings-cache.mjs --load --owner <o> --repo <r> --pr <n> \
 *     [--require-head-sha <sha>] [--markdown]
 *
 *   Exit 0 + prints {summary, findings} JSON to stdout (or the per-axis
 *           Markdown report with --markdown): usable cache hit.
 *   Exit 1: no cache found for this PR.
 *   Exit 2: cache found but --require-head-sha didn't match (new commits
 *           landed since the cached review) — re-review is needed.
 *
 * --save validates the findings against the contract (references/output-and-posting.md) and refuses
 * malformed ones, so a bad review is caught before it is posted.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { exit } from 'node:process';
import { readFindingsArg, normalize, validate, summaryMarkdown } from './findings-lib.mjs';

const { values } = parseArgs({
  args: process.argv.slice(2),
  options: {
    save: { type: 'boolean' },
    load: { type: 'boolean' },
    path: { type: 'boolean' },
    owner: { type: 'string', short: 'o' },
    repo: { type: 'string', short: 'r' },
    pr: { type: 'string', short: 'p' },
    key: { type: 'string', short: 'k' },
    'head-sha': { type: 'string' },
    'require-head-sha': { type: 'string' },
    findings: { type: 'string', short: 'f' },
    'findings-file': { type: 'string', short: 'F' },
    markdown: { type: 'boolean' },
    help: { type: 'boolean', short: 'H' },
  },
});

const target = values.key || (values.owner && values.repo && values.pr ? `${values.owner}-${values.repo}-pr${values.pr}` : null);
const modes = [values.save, values.load, values.path].filter(Boolean).length;

if (values.help || !target || modes !== 1) {
  console.error(`
Usage:
  findings-cache.mjs --save --owner <o> --repo <r> --pr <n> --head-sha <sha> --findings-file <path>
  findings-cache.mjs --load --owner <o> --repo <r> --pr <n> [--require-head-sha <sha>] [--markdown]
  findings-cache.mjs --path --owner <o> --repo <r> --pr <n>      (print the cache file path)
  Local reviews: --key <repo-folder>-local-<branch> instead of --owner/--repo/--pr.
  --findings '<json>' works in place of --findings-file.
`);
  exit(1);
}

const cacheDir = join(homedir(), '.claude', 'gh-review-pr', 'findings');
const cachePath = join(cacheDir, `${target.replace(/[^\w.-]+/g, '_')}.json`);

if (values.path) {
  console.log(cachePath);
  exit(0);
}

if (values.save) {
  if (!values['head-sha']) {
    console.error('Error: --save requires --head-sha (and --findings-file or --findings)');
    exit(1);
  }
  let parsed;
  try {
    parsed = readFindingsArg(values);
  } catch (e) {
    console.error(`Error: ${e.message}`);
    exit(1);
  }
  const check = validate(parsed);
  for (const w of check.warnings) console.warn(`  ! ${w}`);
  if (check.errors.length) {
    console.error(`Error: the findings do not match the contract (references/output-and-posting.md):\n  - ${check.errors.join('\n  - ')}`);
    exit(1);
  }
  const data = normalize(parsed);
  mkdirSync(cacheDir, { recursive: true });
  writeFileSync(cachePath, JSON.stringify({
    owner: values.owner ?? null,
    repo: values.repo ?? null,
    pr: values.pr ? Number(values.pr) : null,
    key: values.key ?? null,
    headSha: values['head-sha'],
    savedAt: new Date().toISOString(),
    ...data,
  }, null, 2));
  console.log(`Saved: ${cachePath}`);
  exit(0);
}

// --load
if (!existsSync(cachePath)) {
  console.error(`No cached review for ${values.pr ? `PR #${values.pr}` : target} (looked in ${cachePath})`);
  exit(1);
}

const cached = JSON.parse(readFileSync(cachePath, 'utf-8'));

if (values['require-head-sha'] && cached.headSha !== values['require-head-sha']) {
  console.error(
    `Cached review is stale: cached at commit ${cached.headSha}, PR is now at ` +
    `${values['require-head-sha']}. Re-review needed.`
  );
  exit(2);
}

const { owner, repo, pr, key, ...review } = cached;
if (values.markdown) console.log(summaryMarkdown(normalize(review)));
else console.log(JSON.stringify(review, null, 2));
