#!/usr/bin/env node
/**
 * findings-cache.mjs — persist a completed review's {summary, findings} to
 * disk, keyed by PR, so a later `--post` call can post without re-running
 * the (expensive) review pass in the same or a different session.
 *
 * Cache location: ~/.claude/gh-review-pr/findings/<owner>-<repo>-pr<N>.json
 *
 * Save:
 *   node findings-cache.mjs --save --owner <o> --repo <r> --pr <n> \
 *     --head-sha <sha> --findings '<json>'
 *
 * Load:
 *   node findings-cache.mjs --load --owner <o> --repo <r> --pr <n> \
 *     [--require-head-sha <sha>]
 *
 *   Exit 0 + prints {summary, findings} JSON to stdout: usable cache hit.
 *   Exit 1: no cache found for this PR.
 *   Exit 2: cache found but --require-head-sha didn't match (new commits
 *           landed since the cached review) — re-review is needed.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { exit } from 'node:process';

const { values } = parseArgs({
  args: process.argv.slice(2),
  options: {
    save: { type: 'boolean' },
    load: { type: 'boolean' },
    owner: { type: 'string', short: 'o' },
    repo: { type: 'string', short: 'r' },
    pr: { type: 'string', short: 'p' },
    'head-sha': { type: 'string' },
    'require-head-sha': { type: 'string' },
    findings: { type: 'string', short: 'f' },
    help: { type: 'boolean', short: 'H' },
  },
});

if (values.help || !values.owner || !values.repo || !values.pr || (!values.save && !values.load) || (values.save && values.load)) {
  console.error(`
Usage:
  findings-cache.mjs --save --owner <o> --repo <r> --pr <n> --head-sha <sha> --findings '<json>'
  findings-cache.mjs --load --owner <o> --repo <r> --pr <n> [--require-head-sha <sha>]
`);
  exit(1);
}

const cacheDir = join(homedir(), '.claude', 'gh-review-pr', 'findings');
const cachePath = join(cacheDir, `${values.owner}-${values.repo}-pr${values.pr}.json`);

if (values.save) {
  if (!values.findings || !values['head-sha']) {
    console.error('Error: --save requires --findings and --head-sha');
    exit(1);
  }
  let parsed;
  try {
    parsed = JSON.parse(values.findings);
  } catch {
    console.error('Error: --findings must be valid JSON');
    exit(1);
  }
  mkdirSync(cacheDir, { recursive: true });
  writeFileSync(cachePath, JSON.stringify({
    owner: values.owner,
    repo: values.repo,
    pr: Number(values.pr),
    headSha: values['head-sha'],
    savedAt: new Date().toISOString(),
    summary: parsed.summary,
    findings: parsed.findings,
  }, null, 2));
  console.log(`Saved: ${cachePath}`);
  exit(0);
}

// --load
if (!existsSync(cachePath)) {
  console.error(`No cached review for PR #${values.pr} (looked in ${cachePath})`);
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

console.log(JSON.stringify({ summary: cached.summary, findings: cached.findings }, null, 2));
