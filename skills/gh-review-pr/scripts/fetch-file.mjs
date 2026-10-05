#!/usr/bin/env node
/**
 * fetch-file.mjs — fetch one file's full content at a given ref via the
 * GitHub Contents API. Used when the capped/truncated diff from
 * gh-context.mjs isn't enough context to assess a finding (or a file's
 * `patch` field is missing entirely because GitHub omitted it for a huge
 * change).
 *
 * Usage:
 *   node fetch-file.mjs --owner <owner> --repo <repo> --path <path> --ref <sha>
 *
 * Prints the raw file content to stdout. Exits non-zero (with a message on
 * stderr) if the file doesn't exist at that ref, or is too large for the
 * Contents API (>1MB — GitHub omits `content` in that case).
 */

import { spawnSync } from 'node:child_process';
import { parseArgs } from 'node:util';
import { exit } from 'node:process';

const { values } = parseArgs({
  args: process.argv.slice(2),
  options: {
    owner: { type: 'string', short: 'o' },
    repo: { type: 'string', short: 'r' },
    path: { type: 'string', short: 'p' },
    ref: { type: 'string' },
    help: { type: 'boolean', short: 'H' },
  },
});

if (values.help || !values.owner || !values.repo || !values.path || !values.ref) {
  console.error(`
Usage:
  fetch-file.mjs --owner <owner> --repo <repo> --path <path> --ref <sha>

Options:
  -o, --owner  Repository owner (required)
  -r, --repo   Repository name (required)
  -p, --path   File path within the repo, e.g. src/Auth/TokenStore.cs (required)
      --ref    Commit SHA / branch to read the file at (required)
`);
  exit(1);
}

// `gh api` defaults to POST as soon as any -f/-F flag is present (they're
// meant for request bodies) — so ref must go in the URL query string, with
// --method GET forced explicitly, or this silently POSTs to the contents
// endpoint (which 404s) instead of reading the file.
const result = spawnSync('gh', [
  'api',
  '--method', 'GET',
  `repos/${values.owner}/${values.repo}/contents/${values.path}?ref=${encodeURIComponent(values.ref)}`,
  '--jq', '.content // empty',
], { encoding: 'utf8', maxBuffer: 25 * 1024 * 1024 });

if (result.status !== 0) {
  const stderr = result.stderr?.toString().trim() || '(no stderr)';
  console.error(`Error fetching ${values.path}@${values.ref}:\n${stderr}`);
  exit(1);
}

const base64 = result.stdout.trim();
if (!base64) {
  console.error(
    `No content returned for ${values.path}@${values.ref} — the file may not exist at ` +
    `this ref, or it's over the Contents API's ~1MB limit (GitHub omits content for large files).`
  );
  exit(1);
}

process.stdout.write(Buffer.from(base64.replace(/\n/g, ''), 'base64').toString('utf-8'));
