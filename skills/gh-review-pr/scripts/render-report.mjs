#!/usr/bin/env node
/**
 * render-report.mjs — turn a review's findings into a self-contained HTML report (and optionally Markdown).
 *
 * Usage:
 *   node render-report.mjs --findings-file <path> [--context <gh-context.json>] --out <report.html> [--markdown <report.md>]
 *   node render-report.mjs --owner <o> --repo <r> --pr <n> [--context <gh-context.json>] --out <report.html>   (from the cache)
 *   node render-report.mjs --key <repo-folder>-local-<branch> --out <report.html>                              (local review, from the cache)
 *
 * Without --out the report goes to ~/.claude/gh-review-pr/reports/<owner>-<repo>-pr<N>.html (or <key>.html).
 *
 * --context is the JSON gh-context.mjs printed (saved to a file); it adds the PR header, CI, spec sources,
 * standards, tooling and the coverage panel. The report works without it.
 *
 * The HTML has no external requests (fonts, scripts, styles all inline), so it is safe to open offline and
 * to share privately. Light and dark themes follow the system; it prints cleanly.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { exit } from 'node:process';
import { readFindingsArg, normalize, validate, byAxis, summaryMarkdown, commentBody, axisLine,
  AXES, AXIS_LABEL, RISKS, RISK_LABEL, LEVELS, langOf } from './findings-lib.mjs';

const { values } = parseArgs({
  args: process.argv.slice(2),
  options: {
    owner: { type: 'string', short: 'o' },
    repo: { type: 'string', short: 'r' },
    pr: { type: 'string', short: 'p' },
    key: { type: 'string', short: 'k' },
    findings: { type: 'string', short: 'f' },
    'findings-file': { type: 'string', short: 'F' },
    context: { type: 'string', short: 'c' },
    out: { type: 'string' },
    markdown: { type: 'string' },
    help: { type: 'boolean', short: 'H' },
  },
});

if (values.help) {
  console.error(`
Usage:
  render-report.mjs --findings-file <path> [--context <gh-context.json>] --out <report.html> [--markdown <report.md>]
  render-report.mjs --owner <o> --repo <r> --pr <n> [--context <file>] --out <report.html>   (reads the findings cache)
  render-report.mjs --key <cache-key> --out <report.html>
`);
  exit(values.help ? 0 : 1);
}

let data;
try {
  if (values.findings || values['findings-file']) data = readFindingsArg(values);
  else {
    const target = values.key || (values.owner && values.repo && values.pr ? `${values.owner}-${values.repo}-pr${values.pr}` : null);
    if (!target) throw new Error('give --findings-file, or --owner/--repo/--pr (or --key) to read the findings cache');
    const p = join(homedir(), '.claude', 'gh-review-pr', 'findings', `${target.replace(/[^\w.-]+/g, '_')}.json`);
    if (!existsSync(p)) throw new Error(`no cached review at ${p}; run the review first`);
    data = JSON.parse(readFileSync(p, 'utf-8'));
  }
} catch (e) {
  console.error(`Error: ${e.message}`);
  exit(1);
}

const check = validate(data);
for (const w of check.warnings) console.warn(`  ! ${w}`);
if (check.errors.length) {
  console.error(`Error: the findings do not match the contract:\n  - ${check.errors.join('\n  - ')}`);
  exit(1);
}
data = normalize(data);

let ctx = {};
if (values.context) {
  try {
    ctx = JSON.parse(readFileSync(values.context, 'utf-8').replace(/^﻿/, ''));
  } catch (e) {
    console.error(`Error: cannot read --context ${values.context}: ${e.message}`);
    exit(1);
  }
}

const owner = values.owner || data.owner || (ctx.pr?.url ? ctx.pr.url.split('/')[3] : null);
const repo = values.repo || data.repo || (ctx.pr?.url ? ctx.pr.url.split('/')[4] : null);
const headSha = ctx.pr?.headSha || data.headSha || (ctx.mode === 'local' ? ctx.head : null);
const canLink = owner && repo && headSha && /^[0-9a-f]{7,40}$/.test(headSha);

const esc = (s = '') => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// Inline Markdown the findings use: `code`, **bold**, *em*, [text](url). Everything else is escaped text.
function inline(s = '') {
  // Code spans are held aside first, so * inside them is never read as emphasis.
  const spans = [];
  return esc(s)
    .replace(/`([^`]+)`/g, (_, c) => `\u0000${spans.push(c) - 1}\u0000`)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?![*\w])/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" rel="noopener">$1</a>')
    .replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${spans[i]}</code>`);
}

function para(s = '') {
  return String(s).split(/\n{2,}/).map(p => `<p>${inline(p).replace(/\n/g, '<br>')}</p>`).join('');
}

// Display-only token colouring for code blocks: comments, strings, numbers and common keywords.
// It never decides anything; an unknown language simply shows plain monospace text.
const KEYWORDS = new Set(('abstract as async await base bool break case catch class const continue def default delete do double else enum '
  + 'except export extends false final finally float for foreach from func function go if implements import in int interface is let '
  + 'long match namespace new nil none not null object of override package private protected public raise readonly record ref return '
  + 'select self sealed static string struct super switch this throw true try type typeof using var virtual void volatile where while with yield '
  + 'and or elif lambda pass fn mut impl pub use mod crate begin end declare exec procedure table into values update set insert join on').split(' '));

function highlight(code, lang) {
  if (!lang || lang === 'markdown' || lang === 'json' && code.length > 20000) return esc(code);
  const lineComment = ['python', 'ruby', 'bash', 'yaml', 'powershell'].includes(lang) ? '#' : lang === 'sql' ? '--' : '//';
  const re = new RegExp([
    `(${lineComment.replace(/[/]/g, '\\/')}[^\\n]*)`,
    '(\\/\\*[\\s\\S]*?\\*\\/)',
    '("(?:[^"\\\\\\n]|\\\\.)*"|\'(?:[^\'\\\\\\n]|\\\\.)*\'|`(?:[^`\\\\]|\\\\.)*`)',
    '(\\b\\d[\\d_.]*[a-zA-Z]*\\b)',
    '([A-Za-z_][A-Za-z0-9_]*)',
  ].join('|'), 'g');
  let out = '';
  let last = 0;
  for (const m of code.matchAll(re)) {
    out += esc(code.slice(last, m.index));
    const [t] = m;
    if (m[1] || m[2]) out += `<span class="tc">${esc(t)}</span>`;
    else if (m[3]) out += `<span class="ts">${esc(t)}</span>`;
    else if (m[4]) out += `<span class="tn">${esc(t)}</span>`;
    else if (KEYWORDS.has(lang === 'sql' ? t.toLowerCase() : t)) out += `<span class="tk">${esc(t)}</span>`;
    else out += esc(t);
    last = m.index + t.length;
  }
  return out + esc(code.slice(last));
}

function codeBlock(code, { lang = '', start = null, label = '' } = {}) {
  const lines = String(code).replace(/\n$/, '').split('\n');
  const html = highlight(lines.join('\n'), lang).split('\n');
  const gutter = start ? `<span class="gutter" aria-hidden="true">${lines.map((_, i) => start + i).join('\n')}</span>` : '';
  return `<figure class="code">${label ? `<figcaption><span>${esc(label)}</span>${lang ? `<span class="lang">${esc(lang)}</span>` : ''}<button type="button" class="copy" data-copy>Copy</button></figcaption>` : ''}`
    + `<pre tabindex="0">${gutter}<code>${html.join('\n')}</code></pre><textarea hidden>${esc(code)}</textarea></figure>`;
}

function where(f) {
  const range = f.line ? (f.endLine && f.endLine !== f.line ? `${f.line}-${f.endLine}` : `${f.line}`) : '';
  const text = `${f.file}${range ? `:${range}` : ''}`;
  if (!canLink) return `<code class="loc">${esc(text)}</code>`;
  const anchor = f.line ? `#L${f.line}${f.endLine && f.endLine !== f.line ? `-L${f.endLine}` : ''}` : '';
  return `<a class="loc" href="https://github.com/${esc(owner)}/${esc(repo)}/blob/${esc(headSha)}/${f.file.split('/').map(encodeURIComponent).join('/')}${anchor}" rel="noopener"><code>${esc(text)}</code></a>`;
}

function findingCard(f) {
  const lang = langOf(f.file);
  const open = f.risk === 'critical' || f.risk === 'high' ? ' open' : '';
  const metaBits = [
    ['Category', f.severity], ['Kind', f.kind === 'judgement' ? 'Judgement call' : 'Hard issue'], ['Spec gap', f.specGap],
    ['Confidence', f.confidence], ['Impact', f.impact], ['Likelihood', f.likelihood],
  ].filter(([, v]) => v);
  return `<details class="finding" id="${esc(f.id)}" data-risk="${f.risk}" data-axis="${f.axis}"${open}>
<summary><span class="risk risk-${f.risk}">${RISK_LABEL[f.risk]}</span><span class="ttl">${inline(f.title)}</span><span class="fid">${esc(f.id)}</span></summary>
<div class="body">
<div class="where">${where(f)}${f.rule ? `<span class="rule">${f.axis === 'spec' ? 'Spec: ' : 'Rule: '}${inline(f.rule)}</span>` : ''}</div>
<section><h4>Issue</h4>${para(f.issue)}</section>
${f.evidence ? codeBlock(f.evidence, { lang, start: f.line || null, label: 'Evidence' }) : ''}
${f.riskIfIgnored ? `<section class="ifnot"><h4>Risk if not addressed</h4>${para(f.riskIfIgnored)}</section>` : ''}
${f.solutions.length ? `<section><h4>${f.solutions.length > 1 ? 'Possible fixes' : 'Fix'}</h4><ol class="fixes">${f.solutions.map((s, i) => `<li>${inline(s)}${i === 0 && f.solutions.length > 1 ? ' <span class="rec">Recommended</span>' : ''}</li>`).join('')}</ol></section>` : ''}
${f.fix ? codeBlock(f.fix, { lang, start: f.line || null, label: 'Suggested change' }) : ''}
<dl class="meta">${metaBits.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
<div class="actions"><button type="button" class="copy" data-copy>Copy as PR comment</button><textarea hidden>${esc(commentBody(f, [], { inline: true }))}</textarea></div>
</div></details>`;
}

// 3×3 matrix of finding counts by impact (rows) and likelihood (columns); cells take the rating's colour.
function matrix(findings) {
  const rated = findings.filter(f => f.impact && f.likelihood);
  if (!rated.length) return '';
  const cell = (i, l) => rated.filter(f => f.impact === i && f.likelihood === l).length;
  const rating = { high: { high: 'critical', medium: 'high', low: 'medium' }, medium: { high: 'high', medium: 'medium', low: 'low' }, low: { high: 'medium', medium: 'low', low: 'low' } };
  return `<figure class="matrix" aria-label="Findings by impact and likelihood"><figcaption>Impact × likelihood</figcaption><table>
<thead><tr><th scope="col"><span class="sr">Impact</span></th>${LEVELS.slice().reverse().map(l => `<th scope="col">${l}</th>`).join('')}</tr></thead>
<tbody>${LEVELS.map(i => `<tr><th scope="row">${i}</th>${LEVELS.slice().reverse().map(l => { const n = cell(i, l); return `<td class="m-${rating[i][l]}${n ? '' : ' zero'}" title="impact ${i}, likelihood ${l}: ${n}">${n || '·'}</td>`; }).join('')}</tr>`).join('')}</tbody>
</table><p class="axislabel">likelihood →</p></figure>`;
}

function list(items, fmt = esc) {
  return items?.length ? `<ul>${items.map(i => `<li>${fmt(i)}</li>`).join('')}</ul>` : '<p class="muted">None</p>';
}

const groups = byAxis(data.findings);
const counts = Object.fromEntries(RISKS.map(r => [r, data.findings.filter(f => f.risk === r).length]));
const pr = ctx.pr || {};
const title = pr.title ? `PR #${pr.number}: ${pr.title}` : ctx.mode === 'local' ? `Changes since ${ctx.since}${ctx.branch ? ` on ${ctx.branch}` : ''}` : (values.pr ? `PR #${values.pr}` : 'Code review');
const verdict = counts.critical ? 'Blocking issues' : counts.high ? 'Changes needed' : data.findings.length ? 'Minor findings' : 'No findings';
const verdictClass = counts.critical ? 'critical' : counts.high ? 'high' : data.findings.length ? 'medium' : 'ok';
const cov = ctx.coverage || {};
const checks = ctx.checks || {};

const axisSection = (a) => {
  const st = data.axes[a];
  const g = groups[a];
  const head = `<header class="axis-head"><h2 id="axis-${a}">${AXIS_LABEL[a]}</h2><p class="axis-q">${{ quality: 'Will it break, leak, or slow down?', standards: 'Does it follow this repository\'s rules?', spec: 'Does it do what was asked?' }[a]}</p>`
    + `<p class="axis-n">${st.status !== 'reviewed' ? esc(st.status) : `${g.length} finding${g.length === 1 ? '' : 's'}`}</p></header>`;
  const src = st.source || st.sources ? `<p class="src">Source: ${esc([].concat(st.source || st.sources).join(', '))}</p>` : '';
  if (st.status && st.status !== 'reviewed') return `<section class="axis" data-axis="${a}">${head}${src}<p class="empty">${esc(st.status)}</p></section>`;
  const reqs = a === 'spec' && st.requirements?.length
    ? `<table class="reqs"><caption>Requirements checklist</caption><thead><tr><th scope="col">Requirement</th><th scope="col">Status</th><th scope="col">Where</th></tr></thead><tbody>${st.requirements.map(r => `<tr><td>${inline(r.text)}</td><td><span class="req req-${esc(r.status)}">${esc(r.status)}</span></td><td>${r.where ? `<code>${esc(r.where)}</code>` : r.finding ? `<a href="#${esc(r.finding)}">${esc(r.finding)}</a>` : ''}</td></tr>`).join('')}</tbody></table>`
    : '';
  return `<section class="axis" data-axis="${a}">${head}${src}${reqs}${g.length ? g.map(findingCard).join('\n') : '<p class="empty">Nothing found on this axis.</p>'}</section>`;
};

const reviewedPanel = ctx.mode ? `<section class="panel" aria-labelledby="scope"><h2 id="scope">What was reviewed</h2><div class="grid">
<div><h3>Change</h3><p>${esc(String(ctx.stats?.filesChanged ?? '?'))} files · <span class="plus">+${esc(String(ctx.stats?.insertions ?? 0))}</span> <span class="minus">−${esc(String(ctx.stats?.deletions ?? 0))}</span> · ${esc(String(ctx.commits?.length ?? 0))} commits</p>
${cov.excluded?.length ? `<p class="muted">${cov.excluded.length} generated / vendored files skipped</p>` : ''}
${[...(cov.patchMissing || []), ...(cov.truncated || []), ...(cov.notInDiff || [])].length ? `<p class="muted">${new Set([...(cov.patchMissing || []), ...(cov.truncated || []), ...(cov.notInDiff || [])]).size} files read in full beyond the capped diff</p>` : ''}</div>
<div><h3>Spec</h3>${list((ctx.linkedIssues || []).map(i => `${i.ref}: ${i.title}`))}${ctx.unresolvedRefs?.length ? `<p class="muted">Not on GitHub: ${esc(ctx.unresolvedRefs.join(', '))}</p>` : ''}</div>
<div><h3>Standards</h3>${list(ctx.standards)}${ctx.tooling?.length ? `<p class="muted">Enforced by tooling (not repeated): ${esc(ctx.tooling.join(', '))}</p>` : ''}</div>
<div><h3>CI</h3>${checks.available ? `<p>${checks.pass}/${checks.total} passing${checks.fail?.length ? ` · <span class="bad">failing: ${esc(checks.fail.join(', '))}</span>` : ''}${checks.pending?.length ? ` · pending: ${esc(checks.pending.join(', '))}` : ''}</p>` : '<p class="muted">Not available</p>'}</div>
</div></section>` : '';

const metaRow = [
  pr.author && ['Author', `@${pr.author}`], pr.baseRef && ['Branches', `${pr.headRef} → ${pr.baseRef}`],
  headSha && ['Commit', headSha.slice(0, 10)], ['Reviewed', (data.savedAt || new Date().toISOString()).slice(0, 10)],
  pr.state && ['State', pr.draft ? 'draft' : pr.merged ? 'merged' : pr.state],
].filter(Boolean);

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>${esc(title)} — Review</title>
<style>
:root{--bg:#f7f6f3;--surface:#fff;--ink:#1d1c1a;--ink-2:#55524c;--ink-3:#77736b;--line:#e3e0d9;--line-2:#d2cec5;--code-bg:#f2f0eb;--accent:#2b59c3;
--critical:#b42318;--critical-bg:#fdecea;--high:#b54708;--high-bg:#fef0e1;--medium:#8a6100;--medium-bg:#fbf3d9;--low:#53606e;--low-bg:#eef1f4;--ok:#1d7a45;
--tc:#6f6a60;--ts:#0f6e3c;--tn:#9a3f05;--tk:#7a2fb5;--radius:10px;--mono:ui-monospace,"Cascadia Code","SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#141413;--surface:#1c1b19;--ink:#ecebe7;--ink-2:#b5b1a8;--ink-3:#8f8b82;--line:#2e2c29;--line-2:#3b3935;--code-bg:#232220;--accent:#8fb0ff;
--critical:#ff8a7a;--critical-bg:#3a1714;--high:#ffb066;--high-bg:#38220f;--medium:#f0c75e;--medium-bg:#332a10;--low:#a9b4c0;--low-bg:#232830;--ok:#6fd39a;--tc:#8f8b82;--ts:#7fd6a0;--tn:#ffb37a;--tk:#d4a8ff}}
:root[data-theme=dark]{--bg:#141413;--surface:#1c1b19;--ink:#ecebe7;--ink-2:#b5b1a8;--ink-3:#8f8b82;--line:#2e2c29;--line-2:#3b3935;--code-bg:#232220;--accent:#8fb0ff;
--critical:#ff8a7a;--critical-bg:#3a1714;--high:#ffb066;--high-bg:#38220f;--medium:#f0c75e;--medium-bg:#332a10;--low:#a9b4c0;--low-bg:#232830;--ok:#6fd39a;--tc:#8f8b82;--ts:#7fd6a0;--tn:#ffb37a;--tk:#d4a8ff}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 var(--sans);font-feature-settings:"tnum" 1}
a{color:var(--accent);text-underline-offset:2px}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
.skip{position:absolute;left:-999px}.skip:focus{left:16px;top:12px;background:var(--surface);padding:8px 12px;z-index:9}
.wrap{max-width:1040px;margin:0 auto;padding:40px 24px 80px}
.eyebrow{font:600 12px/1 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin:0 0 10px}
h1{font-size:clamp(22px,3vw,30px);line-height:1.2;letter-spacing:-.015em;margin:0 0 14px;text-wrap:balance}
h1 a{color:inherit;text-decoration:none}h1 a:hover{text-decoration:underline}
.metarow{display:flex;flex-wrap:wrap;gap:6px 22px;margin:0 0 28px;padding:0;color:var(--ink-2);font-size:13.5px}
.metarow div{display:flex;gap:6px}.metarow dt{color:var(--ink-3)}.metarow dd{margin:0;overflow-wrap:anywhere;font-family:var(--mono);font-size:12.5px;padding-top:1px}
.top{display:grid;grid-template-columns:1fr auto;gap:28px;align-items:start;padding:24px 0 28px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.verdict{display:inline-flex;align-items:center;gap:10px;font-weight:650;font-size:17px;margin:0 0 10px}
.verdict::before{content:"";width:10px;height:10px;border-radius:50%;background:var(--v)}
.v-critical{--v:var(--critical)}.v-high{--v:var(--high)}.v-medium{--v:var(--medium)}.v-ok{--v:var(--ok)}
.summary{max-width:68ch;color:var(--ink-2);margin:0}.summary p{margin:0 0 8px}
.tally{display:flex;gap:8px;margin:18px 0 0;padding:0;list-style:none;flex-wrap:wrap}
.tally li{display:flex;align-items:baseline;gap:6px;padding:6px 12px;border:1px solid var(--line);border-radius:999px;background:var(--surface);font-size:13px;color:var(--ink-2)}
.tally b{font-size:16px;color:var(--ink)}.tally li.zero{opacity:.55}
.tally .dot{width:8px;height:8px;border-radius:50%;align-self:center}
.notes{margin:14px 0 0;padding:10px 14px;border-left:3px solid var(--line-2);color:var(--ink-2);font-size:14px;background:var(--surface);border-radius:0 6px 6px 0}
.notes p{margin:2px 0}
.matrix{margin:0}.matrix figcaption{font-size:12px;color:var(--ink-3);margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.matrix table{border-collapse:separate;border-spacing:3px}.matrix th{font:500 11.5px var(--sans);color:var(--ink-3);text-transform:capitalize;padding:0 6px}
.matrix th[scope=row]{text-align:right}
.matrix td{width:46px;height:38px;text-align:center;border-radius:6px;font-weight:650;font-size:15px}
.m-critical{background:var(--critical-bg);color:var(--critical)}.m-high{background:var(--high-bg);color:var(--high)}.m-medium{background:var(--medium-bg);color:var(--medium)}.m-low{background:var(--low-bg);color:var(--low)}
.matrix td.zero{background:transparent;border:1px dashed var(--line-2);color:var(--ink-3);font-weight:400}
.axislabel{margin:2px 0 0;text-align:right;font-size:11.5px;color:var(--ink-3)}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.bar{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 92%,transparent);backdrop-filter:saturate(1.4) blur(8px);border-bottom:1px solid var(--line);margin:0 -24px;padding:10px 24px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.bar nav{display:flex;gap:4px}.bar nav a{padding:6px 10px;border-radius:6px;text-decoration:none;color:var(--ink-2);font-size:14px;font-weight:550}
.bar nav a:hover{background:var(--surface);color:var(--ink)}.bar nav a span{color:var(--ink-3);font-weight:400;margin-left:4px}
.filters{display:flex;gap:6px;margin-left:auto;flex-wrap:wrap}
.filters button,.copy,.tools button{font:inherit;font-size:13px;border:1px solid var(--line-2);background:var(--surface);color:var(--ink-2);border-radius:999px;padding:5px 12px;cursor:pointer;min-height:32px}
.filters button[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.filters button:hover,.copy:hover,.tools button:hover{border-color:var(--ink-3);color:var(--ink)}
.axis{margin-top:44px}
.axis-head{display:grid;grid-template-columns:auto 1fr auto;align-items:baseline;gap:14px;margin-bottom:14px;scroll-margin-top:70px}
.axis-head h2{margin:0;font-size:21px;letter-spacing:-.01em;scroll-margin-top:70px}.axis-q{margin:0;color:var(--ink-3);font-size:14px}.axis-n{margin:0;color:var(--ink-3);font-size:13.5px}
.src{margin:-6px 0 14px;color:var(--ink-3);font-size:13.5px}
.reqs{width:100%;border-collapse:collapse;margin:0 0 16px;font-size:14px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius)}
.reqs caption{text-align:left;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);padding:0 0 6px;font-weight:600}
.reqs th,.reqs td{text-align:left;padding:8px 12px;border-top:1px solid var(--line);vertical-align:top}.reqs th{font-size:12px;color:var(--ink-3);font-weight:600;border-top:0}
.req{font:600 11.5px var(--sans);text-transform:capitalize;padding:2px 8px;border-radius:4px;white-space:nowrap}
.req-met{color:var(--ok);background:color-mix(in srgb,var(--ok) 12%,transparent)}.req-partial,.req-unclear{color:var(--medium);background:var(--medium-bg)}.req-missing,.req-wrong{color:var(--critical);background:var(--critical-bg)}
.empty{padding:18px;border:1px dashed var(--line-2);border-radius:var(--radius);color:var(--ink-3);margin:0}
.finding{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);margin:0 0 10px;scroll-margin-top:70px}
.finding[hidden]{display:none}
.finding>summary{list-style:none;display:grid;grid-template-columns:auto 1fr auto auto;gap:14px;align-items:center;padding:14px 16px;cursor:pointer;border-radius:var(--radius)}
.finding>summary::-webkit-details-marker{display:none}
.finding>summary::after{content:"";width:8px;height:8px;border-right:1.5px solid var(--ink-3);border-bottom:1.5px solid var(--ink-3);transform:rotate(-45deg);transition:transform .15s}
.finding[open]>summary::after{transform:rotate(45deg)}
.finding>summary:hover{background:color-mix(in srgb,var(--ink) 3%,transparent)}
.ttl{font-weight:600;line-height:1.4;min-width:0;overflow-wrap:anywhere}.fid{font:12px var(--mono);color:var(--ink-3)}
.risk{font:650 11.5px/1 var(--sans);letter-spacing:.04em;text-transform:uppercase;padding:5px 8px;border-radius:5px;min-width:72px;text-align:center}
.risk-critical{background:var(--critical-bg);color:var(--critical)}.risk-high{background:var(--high-bg);color:var(--high)}.risk-medium{background:var(--medium-bg);color:var(--medium)}.risk-low{background:var(--low-bg);color:var(--low)}
.body{padding:2px 18px 18px 16px;border-top:1px solid var(--line)}
.where{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline;margin:14px 0 4px;font-size:13.5px}
.loc code{font-size:12.5px;overflow-wrap:anywhere}.where{min-width:0}.rule{color:var(--ink-3)}
.body section{margin-top:14px}.body h4{margin:0 0 4px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3)}
.body p{margin:0 0 8px;max-width:76ch}
.ifnot{padding:10px 14px;border-radius:8px;background:color-mix(in srgb,var(--high-bg) 55%,transparent);border:1px solid color-mix(in srgb,var(--high) 18%,transparent)}
.ifnot h4{color:var(--high)}
.fixes{margin:0;padding-left:22px}.fixes li{margin:0 0 6px;max-width:76ch;padding-left:2px}
.rec{font:600 11px var(--sans);color:var(--ok);border:1px solid color-mix(in srgb,var(--ok) 40%,transparent);border-radius:4px;padding:1px 6px;margin-left:4px;white-space:nowrap}
code{font-family:var(--mono);font-size:.9em;background:var(--code-bg);padding:.1em .35em;border-radius:4px}
.code{margin:14px 0 0;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--code-bg)}
.code figcaption{display:flex;gap:10px;align-items:center;padding:6px 8px 6px 12px;border-bottom:1px solid var(--line);font-size:12px;color:var(--ink-3)}
.code figcaption .lang{font-family:var(--mono);margin-left:auto}.code figcaption .copy{min-height:26px;padding:2px 10px;font-size:12px}
.code pre{margin:0;padding:12px 14px;overflow:auto;display:flex;gap:16px;font:13px/1.55 var(--mono);tab-size:4;max-height:420px}
.code pre code{background:none;padding:0;font-size:inherit;white-space:pre;flex:1}
.gutter{color:var(--ink-3);text-align:right;user-select:none;white-space:pre;opacity:.7;border-right:1px solid var(--line);padding-right:12px}
.tc{color:var(--tc);font-style:italic}.ts{color:var(--ts)}.tn{color:var(--tn)}.tk{color:var(--tk)}
.meta{display:flex;flex-wrap:wrap;gap:4px 18px;margin:16px 0 0;font-size:12.5px}.meta div{display:flex;gap:5px}.meta dt{color:var(--ink-3)}.meta dd{margin:0;color:var(--ink-2);text-transform:capitalize}
.actions{margin-top:12px}
.panel{margin-top:56px;padding-top:22px;border-top:1px solid var(--line)}
.panel h2{font-size:17px;margin:0 0 14px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px}
.grid h3{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);margin:0 0 6px}
.grid p,.grid ul{margin:0 0 6px;font-size:14px}.grid ul{padding-left:18px}.muted{color:var(--ink-3)}.plus{color:var(--ok)}.minus,.bad{color:var(--critical)}
.tools{display:flex;gap:8px;margin-top:10px}
footer{margin-top:48px;color:var(--ink-3);font-size:12.5px}
@media (max-width:720px){.wrap{padding:24px 16px 64px}.top{grid-template-columns:1fr}.bar{position:static;margin:0;padding:8px 0;backdrop-filter:none;background:none}.filters{margin-left:0}.bar nav{overflow-x:auto}
.finding>summary{grid-template-columns:auto 1fr auto;gap:10px;padding:12px}.fid{display:none}.axis-head{grid-template-columns:1fr auto}.axis-q{grid-column:1/-1;grid-row:2}
.body{padding:2px 12px 14px}.filters button,.copy,.tools button,.bar nav a{min-height:40px}}
@media (pointer:coarse){.filters button,.copy,.tools button{min-height:44px}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
@media print{body{background:#fff;color:#000;font-size:11pt}.bar,.tools,.actions,.copy,.skip{display:none!important}.finding{break-inside:avoid;border-color:#ccc}
.finding>summary::after{display:none}.code pre{max-height:none;white-space:pre-wrap}.wrap{padding:0;max-width:none}a{color:#000}}
</style>
</head>
<body>
<a class="skip" href="#axis-quality">Skip to findings</a>
<div class="wrap">
<header>
<p class="eyebrow">${ctx.mode === 'local' ? 'Local change review' : 'Pull request review'}${owner && repo ? ` · ${esc(owner)}/${esc(repo)}` : ''}</p>
<h1>${pr.url ? `<a href="${esc(pr.url)}" rel="noopener">${esc(title)}</a>` : esc(title)}</h1>
<dl class="metarow">${metaRow.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
</header>
<section class="top" aria-label="Summary">
<div>
<p class="verdict v-${verdictClass}">${verdict}</p>
<div class="summary">${para(data.summary || '')}</div>
<ul class="tally">${RISKS.map(r => `<li class="${counts[r] ? '' : 'zero'}"><span class="dot" style="background:var(--${r})"></span><b>${counts[r]}</b>${RISK_LABEL[r]}</li>`).join('')}</ul>
${[...(ctx.notes || []), ...(data.notes || [])].length ? `<div class="notes">${[...new Set([...(ctx.notes || []), ...(data.notes || [])])].map(n => `<p>${inline(n)}</p>`).join('')}</div>` : ''}
</div>
${matrix(data.findings)}
</section>
<div class="bar">
<nav aria-label="Review axes">${AXES.map(a => `<a href="#axis-${a}">${AXIS_LABEL[a]}<span>${data.axes[a].status !== 'reviewed' ? '–' : groups[a].length}</span></a>`).join('')}</nav>
<div class="filters" role="group" aria-label="Filter by risk"><button type="button" data-f="all" aria-pressed="true">All</button>${RISKS.filter(r => counts[r]).map(r => `<button type="button" data-f="${r}" aria-pressed="false">${RISK_LABEL[r]}</button>`).join('')}</div>
</div>
<div class="tools"><button type="button" data-expand>Expand all</button><button type="button" data-collapse>Collapse all</button></div>
<main>
${AXES.map(axisSection).join('\n')}
</main>
${reviewedPanel}
<footer><p>${esc(axisLine(data))}</p><p>Generated by gh-review-pr. Findings are reported per axis and never ranked across axes. Risk = impact × likelihood.</p></footer>
</div>
<script>
(()=>{
const $$=(s,r=document)=>[...r.querySelectorAll(s)];
$$('.filters button').forEach(b=>b.addEventListener('click',()=>{
  $$('.filters button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));
  const f=b.dataset.f;
  $$('.finding').forEach(d=>{d.hidden=f!=='all'&&d.dataset.risk!==f;});
}));
$$('[data-expand]').forEach(b=>b.addEventListener('click',()=>$$('.finding:not([hidden])').forEach(d=>d.open=true)));
$$('[data-collapse]').forEach(b=>b.addEventListener('click',()=>$$('.finding').forEach(d=>d.open=false)));
document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-copy]');if(!b)return;
  const t=b.closest('figure,.actions').querySelector('textarea');if(!t)return;
  const txt=t.value;let ok=false;
  try{await navigator.clipboard.writeText(txt);ok=true;}catch{ /* file:// pages may block the clipboard API */
    t.hidden=false;t.select();try{ok=document.execCommand('copy');}catch{}t.hidden=true;}
  const was=b.textContent;b.textContent=ok?'Copied':'Copy failed';setTimeout(()=>{b.textContent=was;},1400);
});
const open=()=>{const id=decodeURIComponent(location.hash.slice(1));const d=id&&document.getElementById(id);if(d&&d.tagName==='DETAILS')d.open=true;};
addEventListener('hashchange',open);open();
})();
</script>
</body>
</html>
`;

if (!values.out) {
  const prNo = values.pr || data.pr || pr.number;
  const key = values.key || data.key || (owner && repo && prNo ? `${owner}-${repo}-pr${prNo}` : ctx.mode === 'local' ? `local-${ctx.branch || 'review'}` : 'review');
  values.out = join(homedir(), '.claude', 'gh-review-pr', 'reports', `${key.replace(/[^\w.-]+/g, '_')}.html`);
}
mkdirSync(dirname(resolve(values.out)), { recursive: true });
writeFileSync(values.out, html);
console.log(`Report: ${resolve(values.out)} (${data.findings.length} findings; ${axisLine(data)})`);
if (values.markdown) {
  writeFileSync(values.markdown, summaryMarkdown(data));
  console.log(`Markdown: ${resolve(values.markdown)}`);
}
