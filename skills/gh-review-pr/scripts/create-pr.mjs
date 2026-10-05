#!/usr/bin/env node
/**
 * create-pr.mjs — Create a GitHub PR with given title and body
 *
 * Usage:
 *   node scripts/create-pr.mjs --owner <owner> --repo <repo> --base <branch> --head <branch> --title "<title>" --body "<body>"
 */

import { spawnSync } from 'node:child_process';
import { parseArgs } from 'node:util';
import { exit } from 'node:process';

const { values, positionals } = parseArgs({
  args: process.argv.slice(2),
  options: {
    owner: { type: 'string', short: 'o' },
    repo: { type: 'string', short: 'r' },
    base: { type: 'string', short: 'b' },
    head: { type: 'string', short: 'h' },
    title: { type: 'string', short: 't' },
    body: { type: 'string', short: 'B' },
    draft: { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'H' },
  },
  allowPositionals: true,
});

if (values.help || positionals.length > 0) {
  console.error(`
Usage:
  create-pr.mjs --owner <owner> --repo <repo> --base <branch> --head <branch> --title "<title>" --body "<body>" [--draft]

Options:
  -o, --owner    Repository owner (required)
  -r, --repo     Repository name (required)
  -b, --base     Base branch (required)
  -h, --head     Head branch (required)
  -t, --title    PR title (required)
  -B, --body     PR body (required)
      --draft    Create as draft PR (default: false)
  -H, --help     Show help
`);
  exit(values.help ? 0 : 1);
}

if (!values.owner || !values.repo || !values.base || !values.head || !values.title || !values.body) {
  console.error('Error: --owner, --repo, --base, --head, --title, and --body are required');
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

async function main() {
  const args = [
    'pr', 'create',
    '--repo', `${values.owner}/${values.repo}`,
    '--base', values.base,
    '--head', values.head,
    '--title', values.title,
    '--body', values.body,
  ];

  if (values.draft) {
    args.push('--draft');
  }

  const output = run('gh', args);

  // gh pr create outputs the PR URL
  console.log(output);
}

main().catch(err => {
  console.error('Error:', err.message);
  exit(1);
});