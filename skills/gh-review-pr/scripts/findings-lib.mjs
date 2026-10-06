/**
 * findings-lib.mjs — the findings contract shared by findings-cache.mjs, post-review.mjs and
 * render-report.mjs: read, normalise, validate, rate and render review findings.
 *
 * Read by the other scripts; not run directly. The JSON contract is documented in
 * references/output-and-posting.md.
 */

import { readFileSync } from 'node:fs';

export const AXES = ['quality', 'standards', 'spec'];
export const AXIS_LABEL = { quality: 'Quality', standards: 'Standards', spec: 'Spec' };
// Finding ids: Q1.. (quality), ST1.. (standards), SP1.. (spec), numbered in order within each axis.
export const ID_PREFIX = { quality: "Q", standards: "ST", spec: "SP" };
export const SEVERITIES = ['security', 'bug', 'design', 'performance', 'maintainability'];
export const LEVELS = ['high', 'medium', 'low'];
export const RISKS = ['critical', 'high', 'medium', 'low'];
export const RISK_LABEL = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' };
export const RISK_DOT = { critical: '🔴', high: '🟠', medium: '🟡', low: '⚪' };
export const SPEC_GAPS = ['missing', 'partial', 'scope-creep', 'wrong'];
// Spec checklist: every requirement in the spec gets one status, so "nothing reported" is distinguishable
// from "nothing checked". unclear = the code cannot show it (needs a run, data or the author).
export const REQ_STATUS = ['met', 'partial', 'missing', 'wrong', 'unclear'];
export const REQ_LABEL = { met: '✅ Met', partial: '🟡 Partial', missing: '❌ Missing', wrong: '❌ Wrong', unclear: '❔ Unclear' };

// Risk rating = impact × likelihood (a standard 3×3 risk matrix). Impact: what breaks and for whom.
// Likelihood: how often the code path runs and how easy the trigger is.
const MATRIX = {
  high: { high: 'critical', medium: 'high', low: 'medium' },
  medium: { high: 'high', medium: 'medium', low: 'low' },
  low: { high: 'medium', medium: 'low', low: 'low' },
};

export function rateRisk(impact, likelihood) {
  return MATRIX[impact]?.[likelihood] ?? null;
}

/** --findings '<json>' or --findings-file <path>; the file form avoids shell-quoting limits on long JSON. */
export function readFindingsArg(values) {
  let text = values.findings;
  if (values['findings-file']) {
    try {
      text = readFileSync(values['findings-file'], 'utf-8');
    } catch (e) {
      throw new Error(`cannot read --findings-file ${values['findings-file']}: ${e.message}`);
    }
  }
  if (!text) throw new Error('--findings or --findings-file is required');
  try {
    return JSON.parse(text.replace(/^﻿/, ''));
  } catch {
    throw new Error('findings must be valid JSON ({ "summary": "...", "findings": [...] })');
  }
}

/**
 * Fill derived and older-format fields so every consumer sees one shape:
 * message → issue, suggestion → solutions[0], missing axis → quality, impact × likelihood → risk.
 */
export function normalize(data) {
  const seen = { quality: 0, standards: 0, spec: 0 };
  const out = { ...data, findings: (data.findings || []).map((f) => {
    const n = { ...f };
    n.axis = n.axis === 'risk' ? 'quality' : AXES.includes(n.axis) ? n.axis : 'quality';
    n.issue = n.issue || n.message || '';
    n.message = n.message || n.issue;
    if (!Array.isArray(n.solutions)) n.solutions = n.suggestion ? [n.suggestion] : [];
    n.suggestion = n.suggestion || n.solutions[0] || '';
    n.title = n.title || firstSentence(n.issue);
    n.kind = n.kind === 'judgement' ? 'judgement' : 'hard';
    if (!n.risk && n.impact && n.likelihood) n.risk = rateRisk(n.impact, n.likelihood);
    if (!n.risk) n.risk = { security: 'high', bug: 'high', design: 'medium', performance: 'medium', maintainability: 'low' }[n.severity] || 'medium';
    if (n.line !== null && n.line !== undefined) n.line = Number(n.line);
    if (n.endLine !== null && n.endLine !== undefined) n.endLine = Number(n.endLine);
    seen[n.axis] += 1;
    n.id = n.id || `${ID_PREFIX[n.axis]}${seen[n.axis]}`;
    return n;
  }) };
  out.axes = out.axes || {};
  if (out.axes.risk && !out.axes.quality) out.axes.quality = out.axes.risk; // older name of the quality axis
  delete out.axes.risk;
  for (const a of AXES) out.axes[a] = out.axes[a] || { status: 'reviewed' };
  return out;
}

/** Errors stop the script; warnings are printed and the run continues. */
export function validate(data) {
  const errors = [];
  const warnings = [];
  if (!data || !Array.isArray(data.findings)) errors.push('"findings" must be an array');
  if (!data?.summary) warnings.push('no "summary"');
  for (const [i, f] of (data?.findings || []).entries()) {
    const at = `finding ${i + 1}${f.file ? ` (${f.file}${f.line ? `:${f.line}` : ''})` : ''}`;
    if (!f.file) errors.push(`${at}: "file" is required`);
    if (!f.issue && !f.message) errors.push(`${at}: "issue" is required`);
    if (f.line !== null && f.line !== undefined && !(Number.isInteger(Number(f.line)) && Number(f.line) > 0)) errors.push(`${at}: "line" must be a positive integer or null`);
    if (f.endLine !== undefined && f.endLine !== null && Number(f.endLine) < Number(f.line)) errors.push(`${at}: "endLine" is before "line"`);
    if (f.axis && f.axis !== 'risk' && !AXES.includes(f.axis)) errors.push(`${at}: "axis" must be one of ${AXES.join(', ')}`);
    if (f.severity && !SEVERITIES.includes(f.severity)) errors.push(`${at}: "severity" must be one of ${SEVERITIES.join(', ')}`);
    if (f.risk && !RISKS.includes(f.risk)) errors.push(`${at}: "risk" must be one of ${RISKS.join(', ')}`);
    for (const k of ['impact', 'likelihood']) if (f[k] && !LEVELS.includes(f[k])) errors.push(`${at}: "${k}" must be high, medium or low`);
    if (f.impact && f.likelihood && f.risk && rateRisk(f.impact, f.likelihood) !== f.risk) warnings.push(`${at}: risk "${f.risk}" differs from impact × likelihood (${rateRisk(f.impact, f.likelihood)}); say why in the issue text`);
    if (f.specGap && !SPEC_GAPS.includes(f.specGap)) errors.push(`${at}: "specGap" must be one of ${SPEC_GAPS.join(', ')}`);
    if (!f.riskIfIgnored) warnings.push(`${at}: no "riskIfIgnored" (what happens if this is not addressed)`);
    if (!f.solutions?.length && !f.suggestion) warnings.push(`${at}: no "solutions"`);
    if (f.axis === 'spec' && !f.rule) warnings.push(`${at}: spec finding without the quoted spec line in "rule"`);
  }
  const reqs = data?.axes?.spec?.requirements;
  if (reqs !== undefined && !Array.isArray(reqs)) errors.push('"axes.spec.requirements" must be an array');
  for (const [i, r] of (Array.isArray(reqs) ? reqs : []).entries()) {
    if (!r?.text) errors.push(`requirement ${i + 1}: "text" is required (the spec line, quoted)`);
    if (!REQ_STATUS.includes(r?.status)) errors.push(`requirement ${i + 1}: "status" must be one of ${REQ_STATUS.join(', ')}`);
  }
  if (data?.axes?.spec?.status === 'reviewed' && data?.axes?.spec?.source && !reqs?.length) warnings.push('spec reviewed but no "axes.spec.requirements" checklist');
  return { errors, warnings };
}

export function firstSentence(text = '') {
  const s = String(text).split(/(?<=[.!?])\s/)[0];
  return s.length > 110 ? `${s.slice(0, 107)}…` : s;
}

export function byAxis(findings) {
  // Within an axis: worst risk first, then severity order. Never ranked across axes.
  const order = (f) => RISKS.indexOf(f.risk) * 10 + Math.max(0, SEVERITIES.indexOf(f.severity));
  return Object.fromEntries(AXES.map(a => [a, findings.filter(f => f.axis === a).sort((x, y) => order(x) - order(y))]));
}

export function axisLine(data) {
  const groups = byAxis(data.findings);
  return AXES.map(a => {
    const st = data.axes?.[a]?.status;
    if (st && st !== 'reviewed') return `${AXIS_LABEL[a]}: ${st}`;
    const g = groups[a];
    return g.length ? `${AXIS_LABEL[a]}: ${g.length} (worst: ${RISK_LABEL[g[0].risk]} — ${g[0].title})` : `${AXIS_LABEL[a]}: 0`;
  }).join(' · ');
}

function loc(f) {
  if (!f.line) return f.file;
  return f.endLine && f.endLine !== f.line ? `${f.file}:${f.line}-${f.endLine}` : `${f.file}:${f.line}`;
}

function fence(code, lang = '') {
  const longest = Math.max(2, ...[...String(code).matchAll(/`+/g)].map(m => m[0].length));
  const ticks = '`'.repeat(longest + 1);
  return `${ticks}${lang}\n${String(code).replace(/\n$/, '')}\n${ticks}`;
}

function meta(f) {
  const bits = [`${AXIS_LABEL[f.axis]} axis`, f.severity, f.kind === 'judgement' ? 'judgement call' : null,
    f.specGap ? `spec: ${f.specGap}` : null, f.confidence, f.rule ? `rule: ${f.rule}` : null,
    f.impact && f.likelihood ? `impact ${f.impact} × likelihood ${f.likelihood}` : null].filter(Boolean);
  return bits.join(' · ');
}

/** One finding as a GitHub comment: issue, risk if ignored, possible fixes, optional suggestion block. */
export function commentBody(f, mentionLogins = [], { inline = true } = {}) {
  const parts = [`${RISK_DOT[f.risk] || ''} **${RISK_LABEL[f.risk] || 'Medium'} risk** · ${f.title}`.trim()];
  if (!inline) parts.push(`\`${loc(f)}\``);
  parts.push(`**Issue.** ${f.issue}`);
  if (f.evidence) parts.push(fence(f.evidence, langOf(f.file)));
  if (f.riskIfIgnored) parts.push(`**Risk if not addressed.** ${f.riskIfIgnored}`);
  if (f.solutions.length === 1) parts.push(`**Fix.** ${f.solutions[0]}`);
  else if (f.solutions.length > 1) parts.push(`**Possible fixes**\n${f.solutions.map((s, i) => `${i + 1}. ${s}${i === 0 ? ' *(recommended)*' : ''}`).join('\n')}`);
  // GitHub turns a ```suggestion block into a one-click "Commit suggestion" for exactly the commented lines.
  if (f.fix && inline) parts.push(fence(f.fix, 'suggestion'));
  else if (f.fix) parts.push(fence(f.fix, langOf(f.file)));
  parts.push(`<sub>${meta(f)}</sub>`);
  if (mentionLogins.length) parts.push(`cc ${mentionLogins.map((l) => `@${l}`).join(' ')}`);
  parts.push('---\n*Posted by automated code review*');
  return parts.join('\n\n');
}

export function langOf(file = '') {
  const ext = file.split('.').pop().toLowerCase();
  return { cs: 'csharp', js: 'javascript', mjs: 'javascript', cjs: 'javascript', ts: 'typescript', tsx: 'tsx', jsx: 'jsx', py: 'python',
    go: 'go', rb: 'ruby', java: 'java', kt: 'kotlin', rs: 'rust', sql: 'sql', sh: 'bash', ps1: 'powershell', yml: 'yaml', yaml: 'yaml',
    json: 'json', md: 'markdown', html: 'html', css: 'css', cshtml: 'razor', razor: 'razor', xml: 'xml', csproj: 'xml', php: 'php',
    swift: 'swift', c: 'c', h: 'c', cpp: 'cpp', hpp: 'cpp' }[ext] || '';
}

/** The PR summary comment / chat report: per-axis tables, never merged or reranked across axes. */
export function summaryMarkdown(data, { marker = '' } = {}) {
  const groups = byAxis(data.findings);
  const out = [];
  if (marker) out.push(marker);
  out.push('## Code Review Summary', '', data.summary || '');
  if (data.notes?.length) out.push('', ...data.notes.map(n => `> ${n}`));
  for (const a of AXES) {
    out.push('', `### ${AXIS_LABEL[a]}`);
    const st = data.axes?.[a];
    if (st?.status && st.status !== 'reviewed') { out.push('', `_${st.status}_`); continue; }
    if (st?.source) out.push('', `Source: ${st.source}`);
    if (a === 'spec' && st?.requirements?.length) {
      out.push('', '| Requirement | Status | Where |', '|---|---|---|');
      for (const r of st.requirements) out.push(`| ${cell(r.text)} | ${REQ_LABEL[r.status] || r.status} | ${r.where ? `\`${cell(r.where)}\`` : r.finding ? cell(r.finding) : ''} |`);
    }
    if (!groups[a].length) { out.push('', '_No findings._'); continue; }
    out.push('', '| Risk | Finding | Where | If not addressed |', '|---|---|---|---|');
    for (const f of groups[a]) out.push(`| ${RISK_DOT[f.risk]} ${RISK_LABEL[f.risk]} | ${cell(f.title)} | \`${loc(f)}\` | ${cell(firstSentence(f.riskIfIgnored || ''))} |`);
  }
  out.push('', `**${axisLine(data)}**`);
  return out.join('\n');
}

function cell(s = '') {
  return String(s).replace(/\|/g, '\\|').replace(/\n+/g, ' ');
}
