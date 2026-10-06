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
 * to share privately. Light and dark themes follow the system; it prints cleanly (every finding expanded).
 * Typeface: IBM Plex Sans and Plex Mono (SIL Open Font License, see assets/fonts/OFL.txt), embedded as data URIs.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
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

// Embedded IBM Plex (woff2 data URIs) so the report looks the same offline, on any machine. Missing files fall
// back to the system stack silently.
const FONT_DIR = join(dirname(fileURLToPath(import.meta.url)), 'assets', 'fonts');
const LATIN = 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD';
const LATIN_EXT = 'U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF';
function fontFaces() {
  const face = (file, family, weight, range) => {
    const p = join(FONT_DIR, file);
    if (!existsSync(p)) return '';
    return `@font-face{font-family:"${family}";src:url(data:font/woff2;base64,${readFileSync(p).toString('base64')}) format("woff2");`
      + `font-weight:${weight};font-style:normal;font-display:swap;unicode-range:${range}}\n`;
  };
  return face('plex-sans-latin.woff2', 'Plex Sans', '100 700', LATIN)
    + face('plex-sans-latin-ext.woff2', 'Plex Sans', '100 700', LATIN_EXT)
    + face('plex-mono-latin-400.woff2', 'Plex Mono', '400', LATIN)
    + face('plex-mono-latin-600.woff2', 'Plex Mono', '600', LATIN);
}

// Small line icons (stroke = currentColor), so no glyph or emoji ever stands in for an icon.
const ICON = {
  copy: '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 5.5V3.5a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2"/></svg>',
  check: '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>',
  chevron: '<svg class="i chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5l4.5 4.5L6 12.5"/></svg>',
  info: '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6"/><path d="M8 7.25v4M8 4.75v.01"/></svg>',
};

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

const copyButton = (label) => `<button type="button" class="btn" data-copy>${ICON.copy}<span>${label}</span></button>`;

// A code figure: caption row (what it is, language, copy), then a gutter of real line numbers beside the code.
function codeBlock(code, { lang = '', start = null, label = '' } = {}) {
  const lines = String(code).replace(/\n$/, '').split('\n');
  const html = highlight(lines.join('\n'), lang).split('\n');
  const gutter = start ? `<span class="gutter" aria-hidden="true">${lines.map((_, i) => start + i).join('\n')}</span>` : '';
  return `<figure class="code"><figcaption><span class="cap">${esc(label)}</span>${lang ? `<span class="lang">${esc(lang)}</span>` : ''}${copyButton('Copy')}</figcaption>`
    + `<pre tabindex="0">${gutter}<code>${html.join('\n')}</code></pre><textarea hidden>${esc(code)}</textarea></figure>`;
}

function where(f) {
  const range = f.line ? (f.endLine && f.endLine !== f.line ? `${f.line}-${f.endLine}` : `${f.line}`) : '';
  const text = `${f.file}${range ? `:${range}` : ''}`;
  if (!canLink) return `<code class="loc">${esc(text)}</code>`;
  const anchor = f.line ? `#L${f.line}${f.endLine && f.endLine !== f.line ? `-L${f.endLine}` : ''}` : '';
  return `<a class="loc" href="https://github.com/${esc(owner)}/${esc(repo)}/blob/${esc(headSha)}/${f.file.split('/').map(encodeURIComponent).join('/')}${anchor}" rel="noopener"><code>${esc(text)}</code></a>`;
}

const cap = (s = '') => String(s).charAt(0).toUpperCase() + String(s).slice(1);
const riskTag = (r) => `<span class="risk"><i aria-hidden="true"></i>${RISK_LABEL[r]}</span>`;

function findingRow(f) {
  const lang = langOf(f.file);
  const open = f.risk === 'critical' || f.risk === 'high' ? ' open' : '';
  const facts = [
    f.severity && cap(f.severity), f.kind && (f.kind === 'judgement' ? 'Judgement call' : 'Hard issue'),
    f.specGap && `Spec gap: ${f.specGap}`, f.confidence && `${cap(f.confidence)} confidence`,
    f.impact && `${cap(f.impact)} impact`, f.likelihood && `${cap(f.likelihood)} likelihood`,
  ].filter(Boolean);
  const row = (label, body, cls = '') => body ? `<div class="row${cls}"><dt>${label}</dt><dd>${body}</dd></div>` : '';
  const fixes = f.solutions.length > 1
    ? `<ol class="fixes">${f.solutions.map((s, i) => `<li>${inline(s)}${i === 0 ? ' <span class="rec">recommended</span>' : ''}</li>`).join('')}</ol>`
    : f.solutions.length ? `<p>${inline(f.solutions[0])}</p>` : '';
  return `<details class="finding" id="${esc(f.id)}" data-risk="${f.risk}" data-axis="${f.axis}"${open}>
<summary>${riskTag(f.risk)}<span class="ttl">${inline(f.title)}</span><span class="fid">${esc(f.id)}</span>${ICON.chevron}</summary>
<dl class="rows">
${row('Location', `${where(f)}${f.rule ? `<span class="rule">${f.axis === 'spec' ? 'Spec' : 'Rule'}: ${inline(f.rule)}</span>` : ''}`)}
${row('Issue', para(f.issue))}
${f.evidence ? row('Evidence', codeBlock(f.evidence, { lang, start: f.line || null, label: f.file.split('/').pop() })) : ''}
${row('Risk if not addressed', f.riskIfIgnored ? para(f.riskIfIgnored) : '', ' ifnot')}
${row(f.solutions.length > 1 ? 'Possible fixes' : 'Fix', fixes)}
${f.fix ? row('Suggested change', codeBlock(f.fix, { lang, start: f.line || null, label: 'Replacement' })) : ''}
${row('Rating', `<span class="facts">${facts.map(esc).join('<span class="sep" aria-hidden="true">·</span>')}</span>`)}
</dl>
<div class="actions">${copyButton('Copy as PR comment')}<textarea hidden>${esc(commentBody(f, [], { inline: true }))}</textarea></div>
</details>`;
}

// 3×3 grid of finding counts by impact (rows) and likelihood (columns); filled cells take the rating's colour.
function matrix(findings) {
  const rated = findings.filter(f => f.impact && f.likelihood);
  if (!rated.length) return '';
  const cell = (i, l) => rated.filter(f => f.impact === i && f.likelihood === l).length;
  const rating = { high: { high: 'critical', medium: 'high', low: 'medium' }, medium: { high: 'high', medium: 'medium', low: 'low' }, low: { high: 'medium', medium: 'low', low: 'low' } };
  const cols = LEVELS.slice().reverse();
  return `<figure class="matrix" aria-label="Findings by impact and likelihood"><figcaption>Impact × likelihood</figcaption><table>
<thead><tr><th scope="col"><span class="sr">Impact</span></th>${cols.map(l => `<th scope="col">${cap(l)}</th>`).join('')}</tr></thead>
<tbody>${LEVELS.map(i => `<tr><th scope="row">${cap(i)}</th>${cols.map(l => { const n = cell(i, l); return `<td class="${n ? `m-${rating[i][l]}` : 'zero'}" title="${cap(i)} impact, ${l} likelihood: ${n} → ${rating[i][l]}">${n || ''}</td>`; }).join('')}</tr>`).join('')}</tbody>
</table><p class="axislabel"><span>Impact ↓</span><span>Likelihood →</span></p></figure>`;
}

function list(items, fmt = esc) {
  return items?.length ? `<ul>${items.map(i => `<li>${fmt(i)}</li>`).join('')}</ul>` : '<p class="muted">None</p>';
}

const groups = byAxis(data.findings);
const counts = Object.fromEntries(RISKS.map(r => [r, data.findings.filter(f => f.risk === r).length]));
const pr = ctx.pr || {};
const title = pr.title ? pr.title : ctx.mode === 'local' ? `Changes since ${ctx.since}${ctx.branch ? ` on ${ctx.branch}` : ''}` : (values.pr ? `PR #${values.pr}` : 'Code review');
const docTitle = pr.title ? `#${pr.number} ${pr.title}` : title;
const verdict = counts.critical ? 'Blocking issues — do not merge yet'
  : counts.high ? 'Changes needed before merge'
    : counts.medium ? 'Changes suggested'
      : data.findings.length ? 'Minor findings only' : 'No findings';
const verdictClass = counts.critical ? 'critical' : counts.high ? 'high' : counts.medium ? 'medium' : data.findings.length ? 'low' : 'ok';
const cov = ctx.coverage || {};
const checks = ctx.checks || {};
const notes = [...new Set([...(ctx.notes || []), ...(data.notes || [])])];

const AXIS_Q = { quality: 'Will it break, leak, or slow down?', standards: 'Does it follow this repository’s rules?', spec: 'Does it do what was asked?' };
const REQ = { met: 'Met', partial: 'Partial', missing: 'Missing', wrong: 'Wrong', unclear: 'Unclear' };

const axisSection = (a) => {
  const st = data.axes[a];
  const g = groups[a];
  const reviewed = !st.status || st.status === 'reviewed';
  const head = `<header class="axis-head"><h2 id="axis-${a}">${AXIS_LABEL[a]}</h2><p class="axis-n">${reviewed ? `${g.length} finding${g.length === 1 ? '' : 's'}` : esc(cap(st.status))}</p><p class="axis-q">${AXIS_Q[a]}</p></header>`;
  const src = st.source || st.sources ? `<p class="src">Checked against ${esc([].concat(st.source || st.sources).join(', '))}</p>` : '';
  if (!reviewed) return `<section class="axis" data-axis="${a}">${head}${src}<p class="empty">${esc(cap(st.status))}</p></section>`;
  const reqs = a === 'spec' && st.requirements?.length
    ? `<div class="tablewrap"><table class="reqs"><caption>Requirements checklist</caption><thead><tr><th scope="col">Requirement</th><th scope="col">Status</th><th scope="col">Where</th></tr></thead><tbody>${st.requirements.map(r => `<tr><td>${inline(r.text)}</td><td><span class="req req-${esc(r.status)}"><i aria-hidden="true"></i>${esc(REQ[r.status] || r.status)}</span></td><td>${r.where ? `<code class="path">${esc(r.where).replace(/\//g, '/<wbr>')}</code>` : r.finding ? `<a href="#${esc(r.finding)}">${esc(r.finding)}</a>` : '<span class="muted">—</span>'}</td></tr>`).join('')}</tbody></table></div>`
    : '';
  return `<section class="axis" data-axis="${a}">${head}${src}${reqs}${g.length ? `<div class="findings">${g.map(findingRow).join('\n')}</div>` : '<p class="empty">Nothing found on this axis.</p>'}</section>`;
};

const extraRead = new Set([...(cov.patchMissing || []), ...(cov.truncated || []), ...(cov.notInDiff || [])]).size;
const reviewedPanel = ctx.mode ? `<section class="panel" aria-labelledby="scope"><h2 id="scope">What was reviewed</h2><dl class="grid">
<div><dt>Change</dt><dd><p>${esc(String(ctx.stats?.filesChanged ?? '?'))} files · <span class="plus">+${esc(String(ctx.stats?.insertions ?? 0))}</span> <span class="minus">−${esc(String(ctx.stats?.deletions ?? 0))}</span> · ${esc(String(ctx.commits?.length ?? 0))} commits</p>
${cov.excluded?.length ? `<p class="muted">${cov.excluded.length} generated or vendored files skipped</p>` : ''}
${extraRead ? `<p class="muted">${extraRead} files read in full beyond the capped diff</p>` : ''}</dd></div>
<div><dt>Spec</dt><dd>${list((ctx.linkedIssues || []).map(i => `${i.ref}: ${i.title}`))}${ctx.unresolvedRefs?.length ? `<p class="muted">Not on GitHub: ${esc(ctx.unresolvedRefs.join(', '))}</p>` : ''}</dd></div>
<div><dt>Standards</dt><dd>${list(ctx.standards, s => `<code>${esc(s)}</code>`)}${ctx.tooling?.length ? `<p class="muted">Enforced by tooling, so not repeated: ${esc(ctx.tooling.join(', '))}</p>` : ''}</dd></div>
<div><dt>CI</dt><dd>${checks.available ? `<p>${checks.pass} of ${checks.total} passing${checks.fail?.length ? ` · <span class="bad">failing: ${esc(checks.fail.join(', '))}</span>` : ''}${checks.pending?.length ? ` · pending: ${esc(checks.pending.join(', '))}` : ''}</p>` : '<p class="muted">Not available</p>'}</dd></div>
</dl></section>` : '';

// One quiet line under the title: where, who, which commit, when. Only the commit hash is monospace (it is an ID).
const metaBits = [
  owner && repo && esc(`${owner}/${repo}`),
  pr.number && (pr.url ? `<a href="${esc(pr.url)}" rel="noopener">#${esc(String(pr.number))}</a>` : `#${esc(String(pr.number))}`),
  ctx.mode === 'local' && 'Local changes',
  pr.author && `by ${esc(pr.author)}`,
  pr.baseRef && `<span class="refs">${esc(pr.headRef)} → ${esc(pr.baseRef)}</span>`,
  headSha && `<code>${esc(headSha.slice(0, 7))}</code>`,
  pr.state && esc(pr.draft ? 'Draft' : pr.merged ? 'Merged' : cap(pr.state)),
  `Reviewed ${esc((data.savedAt || new Date().toISOString()).slice(0, 10))}`,
].filter(Boolean);

const tally = RISKS.filter(r => counts[r]);

const css = `${fontFaces()}
:root{--canvas:#fbfbfa;--surface:#fff;--ink:#16181d;--ink-2:#454a54;--ink-3:#6b717c;--line:#e7e7e4;--line-2:#d6d6d2;--code-bg:#f6f6f3;
--accent:#0b6e74;--accent-ink:#095c61;--accent-tint:color-mix(in srgb,#0b6e74 9%,transparent);
--critical:#b42318;--high:#c2410c;--medium:#a16207;--low:#5b6472;--ok:#1f7a4d;
--tc:#6b717c;--ts:#0a5c63;--tn:#2f5aa8;--tk:#a3304a;
--sans:"Plex Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
--mono:"Plex Mono",ui-monospace,"Cascadia Code","SF Mono",Menlo,Consolas,monospace;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--canvas:#111315;--surface:#17191c;--ink:#e9eaec;--ink-2:#b7bbc2;--ink-3:#8b919a;--line:#25282d;--line-2:#33373e;--code-bg:#1a1d21;
--accent:#5ccfcf;--accent-ink:#7adada;--accent-tint:color-mix(in srgb,#5ccfcf 12%,transparent);
--critical:#ff7b6b;--high:#ff9d5c;--medium:#e3b44c;--low:#9aa3b0;--ok:#5fcf8f;--tc:#8b919a;--ts:#7fd4d4;--tn:#9bb8ff;--tk:#ff8fa8;color-scheme:dark}}
:root[data-theme=dark]{--canvas:#111315;--surface:#17191c;--ink:#e9eaec;--ink-2:#b7bbc2;--ink-3:#8b919a;--line:#25282d;--line-2:#33373e;--code-bg:#1a1d21;
--accent:#5ccfcf;--accent-ink:#7adada;--accent-tint:color-mix(in srgb,#5ccfcf 12%,transparent);
--critical:#ff7b6b;--high:#ff9d5c;--medium:#e3b44c;--low:#9aa3b0;--ok:#5fcf8f;--tc:#8b919a;--ts:#7fd4d4;--tn:#9bb8ff;--tk:#ff8fa8;color-scheme:dark}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scrollbar-color:var(--line-2) transparent}
body{margin:0;background:var(--canvas);color:var(--ink);font:400 15px/1.6 var(--sans);font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
::selection{background:color-mix(in srgb,var(--accent) 22%,transparent)}
a{color:var(--accent-ink);text-decoration-thickness:1px;text-underline-offset:3px;text-decoration-color:color-mix(in srgb,currentColor 40%,transparent)}
a:hover{text-decoration-color:currentColor}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
.i{width:16px;height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.skip{position:absolute;left:-999px}.skip:focus{left:16px;top:12px;background:var(--surface);padding:8px 12px;z-index:9;border:1px solid var(--line-2);border-radius:6px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.wrap{max-width:1080px;margin:0 auto;padding:56px 32px 96px}
code{font-family:var(--mono);font-size:.875em;background:var(--code-bg);border:1px solid var(--line);padding:.05em .35em;border-radius:4px;overflow-wrap:anywhere}
a code{color:inherit}

/* Title block */
h1{font-size:28px;line-height:1.2;font-weight:600;letter-spacing:-.018em;margin:0 0 12px;text-wrap:balance;max-width:28em}
.meta{display:flex;flex-wrap:wrap;gap:4px 0;margin:0;color:var(--ink-3);font-size:14px}
.meta>span:not(:last-child)::after{content:"";display:inline-block;width:3px;height:3px;border-radius:50%;background:var(--line-2);margin:0 10px;vertical-align:middle}
.meta a{color:var(--ink-2)}.meta code{font-size:12.5px}.refs{overflow-wrap:anywhere}

/* Verdict + summary */
.top{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:48px;align-items:start;margin:36px 0 0;padding:28px 0 32px;border-top:1px solid var(--line)}
.verdict{display:flex;align-items:center;gap:10px;font-size:18px;font-weight:600;letter-spacing:-.01em;margin:0 0 10px}
.verdict i{width:10px;height:10px;border-radius:2px;background:var(--v)}
.v-critical{--v:var(--critical)}.v-high{--v:var(--high)}.v-medium{--v:var(--medium)}.v-low{--v:var(--low)}.v-ok{--v:var(--ok)}
.summary{max-width:66ch;color:var(--ink-2)}.summary p{margin:0 0 10px}
.tally{display:flex;flex-wrap:wrap;gap:4px 20px;margin:14px 0 0;padding:0;list-style:none;font-size:14px;color:var(--ink-2)}
.tally li{display:flex;align-items:center;gap:7px}.tally b{font-weight:600;color:var(--ink)}
.tally i{width:8px;height:8px;border-radius:2px;background:var(--r)}
.notes{margin:20px 0 0;padding:0;list-style:none;font-size:14px;color:var(--ink-2);max-width:72ch}
.notes li{display:flex;gap:8px;align-items:flex-start;margin:0 0 6px}.notes .i{margin-top:3px;color:var(--ink-3)}
.matrix{margin:0}.matrix figcaption{font-size:13px;font-weight:500;color:var(--ink-2);margin:0 0 8px}
.matrix table{border-collapse:separate;border-spacing:3px;margin-left:-3px}
.matrix th{font-size:12px;font-weight:400;color:var(--ink-3);padding:0 6px}.matrix th[scope=row]{text-align:right}
.matrix td{width:48px;height:40px;text-align:center;border-radius:4px;font-weight:600;font-size:15px}
.matrix td.zero{background:color-mix(in srgb,var(--ink) 3.5%,transparent)}
.m-critical{--r:var(--critical)}.m-high{--r:var(--high)}.m-medium{--r:var(--medium)}.m-low{--r:var(--low)}
.matrix td[class^=m-]{color:var(--r);background:color-mix(in srgb,var(--r) 13%,transparent)}
.axislabel{display:flex;justify-content:space-between;margin:4px 0 0;padding-left:44px;font-size:12px;color:var(--ink-3)}

/* Risk colour per finding */
[data-risk=critical],.r-critical{--r:var(--critical)}[data-risk=high],.r-high{--r:var(--high)}[data-risk=medium],.r-medium{--r:var(--medium)}[data-risk=low],.r-low{--r:var(--low)}

/* Sticky toolbar */
.bar{position:sticky;top:0;z-index:5;background:var(--canvas);border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:0 -32px;padding:10px 32px;display:flex;gap:12px 20px;align-items:center;flex-wrap:wrap}
.bar nav{display:flex;gap:2px}
.bar nav a{display:flex;align-items:baseline;gap:6px;padding:6px 10px;border-radius:6px;text-decoration:none;color:var(--ink-2);font-size:14px;font-weight:500;transition:background-color .15s,color .15s}
.bar nav a:hover{background:color-mix(in srgb,var(--ink) 5%,transparent);color:var(--ink)}
.bar nav a span{color:var(--ink-3);font-weight:400;font-size:13px}
.bar nav a.on{background:var(--accent-tint);color:var(--accent-ink)}.bar nav a.on span{color:inherit}
.seg{display:inline-flex;border:1px solid var(--line-2);border-radius:6px;overflow:hidden;margin-left:auto;background:var(--surface)}
.seg button{font:inherit;font-size:13px;border:0;border-left:1px solid var(--line);background:none;color:var(--ink-2);padding:5px 12px;cursor:pointer;min-height:32px;display:flex;align-items:center;gap:6px;transition:background-color .15s,color .15s}
.seg button:first-child{border-left:0}.seg button i{width:7px;height:7px;border-radius:2px;background:var(--r)}
.seg button:hover{color:var(--ink);background:color-mix(in srgb,var(--ink) 4%,transparent)}
.seg button[aria-pressed=true]{background:var(--ink);color:var(--canvas)}
.btn{font:inherit;font-size:13px;display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line-2);background:var(--surface);color:var(--ink-2);border-radius:6px;padding:5px 10px;cursor:pointer;min-height:32px;transition:border-color .15s,color .15s}
.btn:hover{border-color:var(--ink-3);color:var(--ink)}
.btn.ghost{border-color:transparent;background:none}.btn.ghost:hover{border-color:var(--line-2)}
.btn.done{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 45%,transparent)}

/* Axes and findings */
.axis{margin-top:56px}
.axis-head{display:grid;grid-template-columns:auto 1fr;align-items:baseline;gap:2px 12px;margin:0 0 16px}
.axis-head h2{margin:0;font-size:22px;font-weight:600;letter-spacing:-.012em;scroll-margin-top:80px}
.axis-n{margin:0;color:var(--ink-3);font-size:14px}.axis-q{grid-column:1/-1;margin:0;color:var(--ink-3);font-size:14px}
.src{margin:-8px 0 16px;color:var(--ink-3);font-size:13px}
.empty{padding:16px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);color:var(--ink-3);margin:0;font-size:14px}
.findings{border-top:1px solid var(--line)}
.finding{border-bottom:1px solid var(--line);scroll-margin-top:80px}
.finding[hidden]{display:none}
.finding>summary{list-style:none;display:grid;grid-template-columns:96px minmax(0,1fr) auto 16px;gap:16px;align-items:baseline;padding:14px 8px;margin:0 -8px;cursor:pointer;border-radius:6px;transition:background-color .15s}
.finding>summary::-webkit-details-marker{display:none}
.finding>summary:hover{background:color-mix(in srgb,var(--ink) 3%,transparent)}
.chev{color:var(--ink-3);align-self:center;transition:transform .15s ease-out}.finding[open] .chev{transform:rotate(90deg)}
.risk{display:inline-flex;align-items:center;gap:7px;font-size:13px;font-weight:600;color:var(--r);white-space:nowrap}
.risk i{width:8px;height:8px;border-radius:2px;background:var(--r)}
.ttl{font-weight:500;line-height:1.45;overflow-wrap:anywhere}.fid{font:12px var(--mono);color:var(--ink-3)}
.rows{margin:0 0 4px;padding:2px 0 8px 112px}
.row{display:grid;grid-template-columns:150px minmax(0,1fr);gap:16px;padding:10px 0;border-top:1px dashed var(--line)}
.row:first-child{border-top:0;padding-top:4px}
.row dt{font-size:13px;color:var(--ink-3);padding-top:2px}
.row dd{margin:0;min-width:0}.row dd p{margin:0 0 8px;max-width:72ch}.row dd p:last-child{margin-bottom:0}
.ifnot dt{color:var(--r);font-weight:500}
.rule{display:block;margin-top:4px;color:var(--ink-3);font-size:13.5px}
.loc code{font-size:13px}
.fixes{margin:0;padding-left:20px}.fixes li{margin:0 0 6px;max-width:72ch;padding-left:2px}.fixes li::marker{color:var(--ink-3);font-variant-numeric:tabular-nums}
.rec{font-size:12px;color:var(--accent-ink);background:var(--accent-tint);border-radius:4px;padding:1px 6px;margin-left:4px;white-space:nowrap}
.facts{color:var(--ink-2);font-size:13.5px}.sep{margin:0 8px;color:var(--line-2)}
.actions{padding:0 0 16px 112px}

/* Code figure */
.code{margin:0;border:1px solid var(--line);border-radius:6px;overflow:hidden;background:var(--code-bg)}
.code figcaption{display:flex;gap:12px;align-items:center;padding:4px 4px 4px 12px;border-bottom:1px solid var(--line);font-size:12.5px;color:var(--ink-3)}
.code .cap{font-family:var(--mono);color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.code .lang{margin-left:auto}.code .btn{min-height:28px;padding:3px 8px;font-size:12.5px;border-color:transparent;background:none}
.code .btn:hover{border-color:var(--line-2);background:var(--surface)}
.code pre{margin:0;padding:12px 0;overflow:auto;display:flex;font:13px/1.6 var(--mono);tab-size:4;max-height:440px}
.code pre code{background:none;border:0;padding:0 16px;font-size:inherit;white-space:pre;flex:1;overflow-wrap:normal}
.gutter{color:var(--ink-3);text-align:right;user-select:none;white-space:pre;padding:0 12px 0 16px;border-right:1px solid var(--line);opacity:.75}
.tc{color:var(--tc);font-style:italic}.ts{color:var(--ts)}.tn{color:var(--tn)}.tk{color:var(--tk)}

/* Requirements table */
.tablewrap{overflow-x:auto;margin:0 0 24px}
.reqs{width:100%;border-collapse:collapse;font-size:14px}
.reqs caption{text-align:left;font-size:13px;font-weight:500;color:var(--ink-2);padding:0 0 8px}
.reqs th,.reqs td{text-align:left;padding:9px 12px 9px 0;border-bottom:1px solid var(--line);vertical-align:top}
.reqs th{font-size:13px;color:var(--ink-3);font-weight:500;border-bottom-color:var(--line-2)}
.req{display:inline-flex;align-items:center;gap:7px;font-weight:500;white-space:nowrap}
.req i{width:8px;height:8px;border-radius:2px;background:currentColor}
.reqs code.path{background:none;border:0;padding:0;font-size:12.5px;color:var(--ink-2);overflow-wrap:normal}
.req-met{color:var(--ok)}.req-partial,.req-unclear{color:var(--medium)}.req-missing,.req-wrong{color:var(--critical)}

/* What was reviewed */
.panel{margin-top:72px;padding-top:24px;border-top:1px solid var(--line)}
.panel h2{font-size:18px;font-weight:600;margin:0 0 16px;letter-spacing:-.01em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:24px 32px;margin:0}
.grid dt{font-size:13px;font-weight:500;color:var(--ink-2);margin:0 0 6px}.grid dd{margin:0}
.grid p,.grid ul{margin:0 0 6px;font-size:14px}.grid ul{padding-left:18px}.grid li{margin:0 0 2px}
.muted{color:var(--ink-3)}.plus{color:var(--ok)}.minus,.bad{color:var(--critical)}
footer{margin-top:56px;padding-top:16px;border-top:1px solid var(--line);color:var(--ink-3);font-size:13px}
footer p{margin:0 0 4px}

@media (max-width:820px){.top{grid-template-columns:1fr;gap:28px}.rows{padding-left:0}.actions{padding-left:0}}
@media (max-width:640px){.wrap{padding:32px 16px 64px}h1{font-size:23px}
.bar{position:static;margin:0 -16px;padding:10px 16px}.bar nav{width:100%;overflow-x:auto}.seg{margin-left:0;overflow-x:auto;max-width:100%}
.finding>summary{grid-template-columns:minmax(0,1fr) 16px;gap:4px 12px;padding:14px 4px;margin:0 -4px}
.finding>summary .risk{grid-column:1;grid-row:1}.finding>summary .ttl{grid-column:1;grid-row:2}.fid{display:none}.chev{grid-column:2;grid-row:1/3}
.row{grid-template-columns:1fr;gap:4px}.seg button,.btn,.bar nav a{min-height:40px}}
@media (pointer:coarse){.seg button,.btn{min-height:44px}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
@media print{:root{--canvas:#fff;--surface:#fff}body{font-size:10.5pt;color:#000}.bar,.actions,.btn,.skip,.chev{display:none!important}
.wrap{padding:0;max-width:none}.finding{break-inside:avoid}.code pre{max-height:none;white-space:pre-wrap}.code pre code{white-space:pre-wrap}
a{color:inherit;text-decoration:none}.top{break-inside:avoid}}`;

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>${esc(docTitle)} · Review</title>
<style>
${css}
</style>
</head>
<body>
<a class="skip" href="#axis-quality">Skip to findings</a>
<div class="wrap">
<header>
<h1>${esc(title)}</h1>
<p class="meta">${metaBits.map(b => `<span>${b}</span>`).join('')}</p>
</header>
<section class="top" aria-label="Summary">
<div>
<p class="verdict v-${verdictClass}"><i aria-hidden="true"></i>${verdict}</p>
<div class="summary">${para(data.summary || '')}</div>
${tally.length ? `<ul class="tally" aria-label="Findings by risk">${tally.map(r => `<li class="r-${r}"><i aria-hidden="true"></i><span><b>${counts[r]}</b> ${RISK_LABEL[r].toLowerCase()}</span></li>`).join('')}</ul>` : ''}
${notes.length ? `<ul class="notes">${notes.map(n => `<li>${ICON.info}<span>${inline(n)}</span></li>`).join('')}</ul>` : ''}
</div>
${matrix(data.findings)}
</section>
<div class="bar">
<nav aria-label="Review axes">${AXES.map(a => `<a href="#axis-${a}">${AXIS_LABEL[a]}<span>${data.axes[a].status && data.axes[a].status !== 'reviewed' ? '–' : groups[a].length}</span></a>`).join('')}</nav>
${data.findings.length ? `<div class="seg" role="group" aria-label="Filter by risk"><button type="button" data-f="all" aria-pressed="true">All</button>${tally.map(r => `<button type="button" class="r-${r}" data-f="${r}" aria-pressed="false"><i aria-hidden="true"></i>${RISK_LABEL[r]}</button>`).join('')}</div>
<button type="button" class="btn ghost" data-toggle>Expand all</button>` : ''}
</div>
<main>
${AXES.map(axisSection).join('\n')}
</main>
${reviewedPanel}
<footer><p>${esc(axisLine(data))}</p><p>Generated by gh-review-pr. Each axis is reported on its own and never ranked against the others. Risk rating = impact × likelihood.</p></footer>
</div>
<script>
(()=>{
const $$=(s,r=document)=>[...r.querySelectorAll(s)];
const ICON_COPY=${JSON.stringify(ICON.copy)},ICON_CHECK=${JSON.stringify(ICON.check)};
$$('.seg button').forEach(b=>b.addEventListener('click',()=>{
  $$('.seg button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));
  const f=b.dataset.f;
  $$('.finding').forEach(d=>{d.hidden=f!=='all'&&d.dataset.risk!==f;});
}));
const tg=document.querySelector('[data-toggle]');
if(tg)tg.addEventListener('click',()=>{const open=tg.textContent==='Expand all';$$('.finding:not([hidden])').forEach(d=>d.open=open);tg.textContent=open?'Collapse all':'Expand all';});
document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-copy]');if(!b)return;
  const t=b.closest('figure,.actions').querySelector('textarea');if(!t)return;
  let ok=false;
  try{await navigator.clipboard.writeText(t.value);ok=true;}catch{ /* file:// pages may block the clipboard API */
    t.hidden=false;t.select();try{ok=document.execCommand('copy');}catch{}t.hidden=true;}
  const label=b.querySelector('span'),was=label.textContent;
  b.innerHTML=(ok?ICON_CHECK:ICON_COPY)+'<span>'+(ok?'Copied':'Copy failed')+'</span>';b.classList.toggle('done',ok);
  setTimeout(()=>{b.innerHTML=ICON_COPY+'<span>'+was+'</span>';b.classList.remove('done');},1400);
});
const open=()=>{const id=decodeURIComponent(location.hash.slice(1));const d=id&&document.getElementById(id);if(d&&d.tagName==='DETAILS')d.open=true;};
addEventListener('hashchange',open);open();
/* The axis link for the section in view is marked, so the toolbar doubles as a position indicator. */
const links=$$('.bar nav a');
if('IntersectionObserver' in window){const io=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting){links.forEach(a=>a.classList.toggle('on',a.hash==='#'+e.target.querySelector('h2').id));}});},{rootMargin:'-30% 0px -60% 0px'});$$('.axis').forEach(s=>io.observe(s));}
/* Printing opens every finding, so the paper copy is complete. */
let was=[];addEventListener('beforeprint',()=>{was=$$('.finding').map(d=>[d.open,d.hidden]);$$('.finding').forEach(d=>{d.open=true;d.hidden=false;});});
addEventListener('afterprint',()=>{$$('.finding').forEach((d,i)=>{[d.open,d.hidden]=was[i]||[d.open,d.hidden];});});
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
