const D = JSON.parse(document.getElementById('data').textContent);
const SEV = ['Blocker','High','Medium','Low','Info'];
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let Q = '';
const hl = s => { const t = esc(s); if (!Q) return t; const re = new RegExp('(' + Q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&') + ')', 'ig'); return t.replace(re, '<mark>$1</mark>'); };
const pill = s => `<span class="pill ${esc(s)}">${esc(s)}</span>`;
const rng = (a, u='') => `${Math.round(a[0])}–${Math.round(a[1])}${u}`;
const dd = d => d.map(x => (+x).toFixed(1).replace(/\.0$/,'')).join('–');
const hd = (h, d) => `${Math.round(h[0])}–${Math.round(h[1])} h <span class="muted">(${dd(d || h.map(x => x/8))} d)</span>`;
const lk = a => a[0] + 0.4 * (a[1] - a[0]);
const csv = (cols, rows, name) => { const q = v => '"' + String(v ?? '').replace(/"/g,'""') + '"'; const body = [cols.map(c=>q(c.label)).join(',')].concat(rows.map(r => cols.map(c => q(c.csv ? c.csv(r) : r[c.key])).join(','))).join('\r\n');
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob(['﻿' + body], {type:'text/csv'})); a.download = name + '.csv'; a.click(); };
const list = a => a && a.length ? '<ul>' + a.map(x => `<li>${hl(x)}</li>`).join('') + '</ul>' : '<p class="muted">—</p>';
// Display names for the classifier's type slugs (data and CSV keep the slug only when no name is known)
const TYPE = {'aspnet-core':'ASP.NET Core','aspnet-mvc':'ASP.NET MVC','aspnet-webapi':'ASP.NET Web API','aspnet-webforms':'ASP.NET Web Forms','website':'ASP.NET website',
  'class-library':'Class library','web-library':'Web library','web-service':'ASMX web service','wcf-service':'WCF service','wcf-desktop':'WCF desktop client',
  'netcore-console':'.NET console app','netcore-worker':'.NET worker service','netcore-other':'.NET (other)','console':'Console app','windows-service':'Windows service',
  'windows-desktop':'Windows desktop app','winforms':'WinForms','wpf':'WPF'};
const typeName = s => TYPE[s] || String(s ?? '').replace(/-/g, ' ').replace(/^./, c => c.toUpperCase());
// Filter menu wording ("All 7R decisions", not "All 7r") for columns whose label does not pluralise on its own
const FLABEL = {r7:'7R decisions', type:'types', risk:'risk levels', repo:'repositories', kind:'kinds', status:'statuses', size:'sizes', level:'readiness levels', vulnerable:'advisory states', reviewed:'decision states', area:'areas', service:'services', severity:'severities', confidence:'confidence levels', wave:'waves', difficulty:'difficulty levels', action:'actions'};
const TABLES = [];
const SMOOTH = matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';

function DataTable(host, opt) {
  const st = {sort: opt.sort || null, asc: opt.asc ?? false, filters: {}, page: 0, open: new Set(), size: opt.pageSize || 50};
  const wrap = document.createElement('div'); wrap.className = 'dtwrap'; host.appendChild(wrap);
  const base = () => opt.rows;
  function rows() {
    let r = base().filter(x => Object.entries(st.filters).every(([k,v]) => !v || String(x[k]) === v));
    if (Q) { const q = Q.toLowerCase(); r = r.filter(x => (opt.text ? opt.text(x) : Object.values(x).join(' ')).toLowerCase().includes(q)); }
    if (st.sort) { const c = opt.cols.find(c => c.key === st.sort); const sv = c && c.sortv ? c.sortv : (x => x[st.sort]);
      r = r.slice().sort((a,b) => { const A = sv(a), B = sv(b); const o = (typeof A === 'number' && typeof B === 'number') ? A - B : String(A).localeCompare(String(B), undefined, {numeric:true}); return st.asc ? o : -o; }); }
    return r;
  }
  // The table scrolls inside its own box: redrawing it would put that box (and so the row just clicked) back at the top.
  // Every redraw keeps the page and the sideways scroll; expand / collapse (keep = true) also keeps the box's own scroll.
  function render(keep = false) {
    const tw0 = wrap.querySelector('.tablewrap'), pos = [tw0 ? tw0.scrollTop : 0, tw0 ? tw0.scrollLeft : 0, window.scrollX, window.scrollY];
    const fa = document.activeElement, kf = fa && wrap.contains(fa) ? (fa.dataset.k ? `th[data-k="${CSS.escape(fa.dataset.k)}"]` : fa.dataset.id !== undefined ? `tr.row[data-id="${CSS.escape(fa.dataset.id)}"]` : fa.dataset.a ? `[data-a="${fa.dataset.a}"]` : null) : null;
    const r = rows(); const pages = Math.max(1, Math.ceil(r.length / st.size)); st.page = Math.min(st.page, pages - 1);
    const view = r.slice(st.page * st.size, (st.page + 1) * st.size);
    const sel = (opt.filters || []).map(k => { const c = opt.cols.find(c => c.key === k) || {label: k}; const vals = [...new Set(base().map(x => String(x[k])))].sort((a,b)=> (SEV.indexOf(a) - SEV.indexOf(b)) || a.localeCompare(b));
      const fl = c.flabel || FLABEL[k] || c.label.toLowerCase();
      return vals.length > 1 || st.filters[k] ? `<select data-f="${k}" aria-label="Filter by ${esc(fl)}"><option value="">All ${esc(fl)}</option>${vals.map(v => `<option value="${esc(v)}" ${st.filters[k]===v?'selected':''}>${esc(c.fmt ? c.fmt(v) : v)}</option>`).join('')}</select>` : ''; }).join('');
    wrap.innerHTML = `${opt.title ? `<h3>${esc(opt.title)}</h3>` : ''}<div class="tools">${sel}<button class="btn" data-a="csv">Download CSV</button>${opt.detail ? `<button class="btn" data-a="expand">${st.open.size ? 'Collapse all' : 'Expand all'}</button>` : ''}<span class="count" aria-live="polite">${r.length} of ${base().length} shown</span></div>
     <div class="tablewrap"><table class="dt"><thead><tr>${opt.cols.map(c => `<th scope="col" tabindex="0" data-k="${c.key}" aria-sort="${st.sort===c.key?(st.asc?'ascending':'descending'):'none'}" title="Sort by ${esc(c.label)}" class="${st.sort===c.key?'sorted'+(st.asc?' asc':''):''}">${esc(c.label)}</th>`).join('')}</tr></thead><tbody>
     ${view.map((x,i) => { const id = opt.id ? opt.id(x) : (st.page*st.size+i); const open = st.open.has(String(id));
        return `<tr class="row" data-id="${esc(id)}" ${opt.detail ? `tabindex="0" aria-expanded="${open}"` : ''} ${opt.anchor ? `data-anchor="${esc(opt.anchor(x))}"` : ''}>${opt.cols.map(c => `<td class="${c.cls||''}">${c.html ? c.html(x) : hl(x[c.key])}</td>`).join('')}</tr>` +
          (opt.detail && open ? `<tr class="detail"><td colspan="${opt.cols.length}"><div class="detail">${opt.detail(x)}</div></td></tr>` : ''); }).join('') || `<tr><td colspan="${opt.cols.length}" class="muted">${Q ? 'No rows match the search.' : (opt.empty || 'Checked, none found.')}</td></tr>`}
     </tbody></table></div>${pages > 1 ? `<div class="pager"><button class="btn" data-a="prev" ${st.page ? '' : 'disabled'}>Previous</button><span>Page ${st.page+1} of ${pages}</span><button class="btn" data-a="next" ${st.page + 1 < pages ? '' : 'disabled'}>Next</button></div>` : ''}`;
    wrap.querySelectorAll('select[data-f]').forEach(s => s.onchange = () => { st.filters[s.dataset.f] = s.value; st.page = 0; render(); });
    wrap.querySelectorAll('th[data-k]').forEach(th => th.onclick = () => { if (st.sort === th.dataset.k) st.asc = !st.asc; else { st.sort = th.dataset.k; st.asc = true; } render(); });
    if (opt.detail) wrap.querySelectorAll('tr.row').forEach(tr => tr.onclick = e => { if (e.target.closest('a')) return; const id = tr.dataset.id; st.open.has(id) ? st.open.delete(id) : st.open.add(id); render(true); });
    wrap.querySelector('[data-a=csv]').onclick = () => csv(opt.csvCols || opt.cols, rows(), opt.name);
    const ex = wrap.querySelector('[data-a=expand]'); if (ex) ex.onclick = () => { if (st.open.size) st.open.clear(); else rows().forEach((x,i) => st.open.add(String(opt.id ? opt.id(x) : i))); render(true); };
    const pv = wrap.querySelector('[data-a=prev]'); if (pv) { pv.onclick = () => { st.page = Math.max(0, st.page-1); render(); }; wrap.querySelector('[data-a=next]').onclick = () => { st.page++; render(); }; }
    const tw = wrap.querySelector('.tablewrap'); if (tw) { tw.scrollTop = keep ? pos[0] : 0; tw.scrollLeft = pos[1]; } window.scrollTo(pos[2], pos[3]);
    if (kf) { const el = wrap.querySelector(kf); if (el) el.focus({preventScroll: true}); }
    return r.length;
  }
  const t = {render, rows, opt, st, host: wrap, openRow(id) { st.open.add(String(id)); st.filters = {}; const r = rows(); const i = r.findIndex(x => String(opt.id(x)) === String(id)); if (i >= 0) st.page = Math.floor(i / st.size); render(); }};
  TABLES.push(t); render(); return t;
}

const findingCols = inSegment => [{key:'ref',label:'Ref'},{key:'severity',label:'Severity',html:x=>pill(x.severity),sortv:x=>SEV.indexOf(x.severity)},{key:'confidence',label:'Confidence'},{key:'title',label:'Finding',cls:'mid'},{key:'apps',label:'Application',flabel:'applications',cls:'mid'},
  ...(inSegment ? [] : [{key:'segment',label:'Area',flabel:'areas'}]),{key:'category',label:'Category',flabel:'categories'},{key:'count',label:'Count',cls:'num'}];
const findingDetail = x => `<h5>What it means</h5><p>${hl(x.why)}</p><h5>What to do</h5><p>${hl(x.fix)}${x.alt ? '<br><b>Alternatives:</b> ' + hl(x.alt) : ''}</p>${x.note ? `<p class="muted">${hl(x.note)}</p>` : ''}
  ${x.review ? `<div class="callout"><b>Assessor review (${esc(x.verdict)}):</b> ${hl(x.review)}</div>` : ''}${x.question ? `<div class="callout warn"><b>Question for the client:</b> ${hl(x.question)}</div>` : ''}
  <h5>Evidence (${x.count} occurrence${x.count==1?'':'s'}${x.evidence.length < x.count ? ', first ' + x.evidence.length + ' shown' : ''})</h5>${x.evidence.map(e => `<div class="ev"><b>${hl(e.loc)}</b>  ${hl(e.text)}</div>`).join('')}
  <p class="muted small">Rule ${esc(x.rule)} · project ${esc(x.project)} · repository ${esc(x.repo)}${x.source==='review' ? ' · added by the assessor' : ''}</p>`;
const findingCsv = [{key:'ref',label:'Ref'},{key:'severity',label:'Severity'},{key:'confidence',label:'Confidence'},{key:'segment',label:'Area'},{key:'category',label:'Category'},{key:'title',label:'Finding'},{key:'apps',label:'Application'},{key:'project',label:'Project'},{key:'count',label:'Count'},{key:'ev',label:'Evidence',csv:x=>x.evidence.map(e=>e.loc).join('; ')},{key:'why',label:'Impact'},{key:'fix',label:'Recommendation'},{key:'alt',label:'Alternative'},{key:'review',label:'Review note'},{key:'question',label:'Open question'}];
const findingText = x => [x.ref,x.title,x.apps,x.category,x.segment,x.why,x.fix,x.alt,x.note,x.review,x.project,x.rule,x.evidence.map(e=>e.loc+' '+e.text).join(' ')].join(' ');
function findings(h, seg) {
  const rows = seg === 'all' ? D.findings : D.findings.filter(f => f.seg === seg);
  DataTable(h, {name: 'findings-' + seg, title: seg === 'all' ? 'All findings' : `Findings in this area (${rows.length})`, rows, filters: seg === 'all' ? ['segment','severity','confidence','category','apps'] : ['severity','confidence','category','apps'],
    sort:'severity', asc:true, id: x => x.ref, anchor: x => 'finding-' + x.ref, cols: findingCols(seg !== 'all'), csvCols: findingCsv, text: findingText, detail: findingDetail, empty: 'Checked, none found in this area.'});
}
// Rows with findings get a bar; rows checked with nothing found are named once underneath instead of drawing empty tracks.
const sevBars = (rows, label, click) => { const tot = c => SEV.reduce((a,s)=>a+c[s],0); const m = Math.max(1, ...rows.map(tot));
  const used = SEV.filter(s => rows.some(c => c[s])); const none = rows.filter(c => !tot(c));
  return (used.length ? `<div class="legend">${used.map(s => `<span style="--c:var(--${s.toLowerCase()})">${s}</span>`).join('')}</div>` : '') + rows.map((c,i) => { const n = tot(c); if (!n) return '';
    return `<div class="bar ${click?'click':''}" data-i="${i}" ${click ? 'tabindex="0" role="button"' : ''} title="${esc(n + ' finding' + (n === 1 ? '' : 's') + ': ' + SEV.filter(s => c[s]).map(s => c[s] + ' ' + s.toLowerCase()).join(', '))}"><span class="lab">${esc(c[label])}</span><span class="track">${SEV.map(s => c[s] ? `<span class="seg sev-${s}" style="width:${c[s]/m*100}%"></span>` : '').join('')}</span><span class="n">${n}</span></div>`; }).join('')
    + (none.length ? `<p class="none-line">Checked, nothing found: ${none.map(c => `<span title="${esc(c.scanned || '')}">${esc(c[label])}</span>`).join(', ')}.</p>` : ''); };
const card = (h, inner) => { h.className = 'card'; h.innerHTML = inner; };

const C = {
  'kpis': h => h.innerHTML = '<div class="kpis">' + D.kpis.map(k => `<div class="kpi"><div class="l">${esc(k[0])}</div><div class="v">${esc(k[1])}</div><div class="s">${esc(k[2])}</div></div>`).join('') + '</div>',
  'chart:segments': h => { card(h, `<h3>Findings by area</h3><p class="muted small">Select an area to open it.</p>` + sevBars(D.segs, 'title', true)); h.querySelectorAll('.bar').forEach(b => b.onclick = () => show(D.segs[b.dataset.i].id)); },
  'chart:categories': h => { card(h, `<h3>Findings by category</h3><p class="muted small">Select a category to filter the findings table.</p>` + sevBars(D.cats, 'title', true));
     h.querySelectorAll('.bar').forEach(b => b.onclick = () => { const t = TABLES.find(t => t.opt.name === 'findings-all'); if (t) { t.st.filters.category = D.cats[b.dataset.i].title; t.st.page = 0; t.render(); t.host.scrollIntoView({behavior:SMOOTH}); } }); },
  'chart:r7': h => { const t = Object.values(D.r7).reduce((a,b)=>a+b,0) || 1; card(h, `<h3>Recommended path (7R)</h3>${Object.entries(D.r7).sort((a,b)=>b[1]-a[1]).map(([k,v]) => `<div class="bar"><span class="lab">${esc(k)}</span><span class="track"><span class="seg" style="width:${v/t*100}%;background:var(--accent)"></span></span><span class="n">${v}</span></div>`).join('')}`); },
  'chart:severity': h => { const t = SEV.reduce((a,s)=>a+(D.sev[s]||0),0) || 1; card(h, `<h3>Findings by severity</h3>${SEV.map(s => `<div class="bar"><span class="lab">${s}</span><span class="track"><span class="seg sev-${s}" style="width:${(D.sev[s]||0)/t*100}%"></span></span><span class="n">${D.sev[s]||0}</span></div>`).join('')}`); },
  'apps-table': h => DataTable(h, {name:'applications', rows: D.apps, filters:['r7','type','risk','repo'], sort:'lh', id: x => x.id,
     cols: [{key:'name',label:'Application'},{key:'type',label:'Type',fmt:typeName,html:x=>hl(typeName(x.type)),csv:x=>typeName(x.type)},{key:'framework',label:'Framework'},{key:'loc',label:'LOC',cls:'num',html:x=>(x.loc_own ?? x.loc).toLocaleString() + (x.loc_own != null && x.loc > x.loc_own ? `<div class="muted small">+${(x.loc - x.loc_own).toLocaleString()} in referenced projects</div>` : '')},{key:'r7',label:'7R'},
            {key:'target',label:'Target',cls:'mid',html:x=>hl(x.target.split(' - ')[0])},{key:'lh',label:'Effort (P10–P90)',html:x=>hd(x.h,x.d),csv:x=>rng(x.h,' h')},{key:'size',label:'Size'},
            {key:'risk',label:'Risk',html:x=>SEV.includes(x.risk)?pill(x.risk):hl(x.risk),sortv:x=>SEV.indexOf(x.risk)},{key:'reviewed',label:'Decision',fmt:v=>v==='reviewed'?'Reviewed':'Draft',html:x=>x.reviewed==='reviewed'?'Reviewed':'<span class="muted">Draft</span>'}],
     detail: x => `<h5>Target</h5><p>${hl(x.target)}</p><h5>Why</h5>${list(x.rationale)}<h5>Options considered</h5>${list(x.options)}${(x.why_not||[]).length ? '<h5>Why not the other Rs</h5>' + list(x.why_not) : ''}${(x.then||[]).length ? '<h5>Then</h5>' + list(x.then) : ''}${(x.risks||[]).length ? '<h5>Risks</h5>' + list(x.risks) + '<h5>Signs off</h5>' + list(x.sign_off||[]) : ''}<h5>Blocking / high findings</h5>${list(x.blockers)}<h5>Main effort drivers</h5>${list(x.drivers)}<h5>Work items</h5>${list(x.work)}${x.notes.length ? '<h5>To confirm</h5>' + list(x.notes) : ''}`}),
  'linux-scorecard': h => { const lv = {}; D.linux.forEach(r => lv[r.level] = (lv[r.level]||0) + 1);
     const names = {ready:['Linux-ready','already cross-platform, no blockers'], port:['Ready after porting','moves to .NET 10 on Linux with code changes (and replacing any Windows-only parts)'], blocked:['Blocked','Windows-bound: stays on Windows until redesigned'], windows:['Windows-only (desktop)','client app on user machines'], na:['Retiring','not assessed for Linux']};
     h.innerHTML = `<div class="tiles">${Object.keys(names).map(k => `<div class="tile" data-l="${k}" tabindex="0" role="button" aria-pressed="false" title="Show only these applications"><div class="l"><span class="lv ${k}">${names[k][0]}</span></div><div class="v">${lv[k]||0}</div><div class="s">${names[k][1]}</div></div>`).join('')}</div>`;
     const host = document.createElement('div'); h.appendChild(host);
     const t = DataTable(host, {name:'linux-readiness', title:'Readiness by application', rows: D.linux, filters:['level','repo'], sort:'level', asc:true, id: x => x.id,
       cols: [{key:'app',label:'Application'},{key:'framework',label:'Framework'},{key:'level',label:'Linux readiness',flabel:'readiness levels',html:x=>`<span class="lv ${x.level}">${esc(x.status)}</span>`,csv:x=>x.status,sortv:x=>['blocked','port','windows','ready','na'].indexOf(x.level)},
              {key:'windows_apis',label:'Windows APIs',cls:'num'},{key:'framework_blockers',label:'Framework blockers',cls:'num'},{key:'packages',label:'Incompatible pkgs',cls:'num'},{key:'paths',label:'Path issues',cls:'num'},
              {key:'time_culture',label:'Time / culture',cls:'num'},{key:'windows_auth',label:'Windows auth',cls:'num'},{key:'linux_build',label:'Linux build',cls:'mid'},{key:'linux_checks',label:'Linux checks (block / warn)',cls:'mid'},{key:'summary',label:'What stops it',cls:'wide'}]});
     h.querySelectorAll('.tile').forEach(tl => tl.onclick = () => { const on = tl.classList.toggle('sel'); h.querySelectorAll('.tile').forEach(o => { if (o !== tl) o.classList.remove('sel'); o.setAttribute('aria-pressed', o.classList.contains('sel')); }); t.st.filters.level = on ? tl.dataset.l : ''; t.render(); }); },
  'linux-issues': h => DataTable(h, {name:'linux-issues', title:'What breaks on Linux — by issue type', rows: D.linuxIssues, filters:['severity'], sort:'severity', asc:true, empty:'No Linux blockers found.',
     cols: [{key:'severity',label:'Severity',html:x=>pill(x.severity),sortv:x=>SEV.indexOf(x.severity)},{key:'issue',label:'Issue',cls:'mid'},{key:'apps',label:'Applications',cls:'mid'},{key:'occurrences',label:'Occurrences',cls:'num'},{key:'refs',label:'Findings',html:x=>x.refs.split(', ').map(r=>`<a class="fref" href="#finding-${esc(r)}">${esc(r)}</a>`).join(' ')}],
     id: x => x.issue, detail: x => `<h5>Why it breaks</h5><p>${hl(x.why)}</p><h5>Fix</h5><p>${hl(x.fix)}</p>`}),
  'linux-checks': h => { const lv = {block:'Blocking', warn:'Review', info:'Verify'}; const reps = D.linuxReports || {};
     const host = document.createElement('div'); h.appendChild(host);
     DataTable(host, {name:'linux-checks', title:'Linux readiness checks that hit', rows: D.linuxChecks || [], filters:['level','area'], sort:'level', asc:true, id: x => x.id,
       empty:'The Linux readiness scan (step 3.2) has not been run yet.',
       cols: [{key:'id',label:'Check',html:x=>`<code>${esc(x.id)}</code>${x.verify ? ' <span class="muted">(verify)</span>' : ''}`,csv:x=>x.id},
              {key:'level',label:'Level',fmt:v=>lv[v]||v,html:x=>esc(lv[x.level]||x.level),csv:x=>lv[x.level]||x.level,sortv:x=>['block','warn','info'].indexOf(x.level)},
              {key:'area',label:'Area',cls:'mid'},{key:'repos',label:'Repositories',cls:'mid'},{key:'apps',label:'Applications',cls:'mid'},{key:'hits',label:'Hits',cls:'num'},{key:'costed',label:'Costed as',cls:'mid'}],
       detail: x => `<h5>What breaks</h5><p>${hl(x.what)}</p><h5>Fix</h5><p>${hl(x.fix)}</p><h5>Examples</h5><p>${esc(x.where)}</p>`});
     const keys = Object.keys(reps);
     if (keys.length) { const p = document.createElement('p'); p.className = 'muted'; p.innerHTML = 'Full report per repository: ' + keys.map(k => `<code>${esc(reps[k])}</code>`).join(', '); h.appendChild(p); } },
  'linux-build': h => DataTable(h, {name:'linux-build', title:'Linux build validation', rows: D.linuxBuild, filters:['status'], empty:'Not run yet (validate_linux_build.py).', cols:[{key:'project',label:'Project'},{key:'tfms',label:'TFM',html:x=>esc((x.tfms||[]).join(', '))},{key:'status',label:'Result'},{key:'detail',label:'Detail',cls:'wide'}]}),
  'package-groups': h => { const cnt = {}; D.packages.forEach(p => cnt[p.group] = (cnt[p.group]||0) + 1); const vul = D.packages.filter(p => p.vulnerable === 'yes').length;
     h.innerHTML = `<div class="tiles">${D.pgroups.map(g => `<div class="tile" data-g="${esc(g.group)}" tabindex="0" role="button" aria-pressed="false"><div class="l">${esc(g.group)}</div><div class="v">${cnt[g.group]||0}</div><div class="s">${esc(g.desc)}</div></div>`).join('')}<div class="tile" data-v="1" tabindex="0" role="button" aria-pressed="false"><div class="l">With security advisories</div><div class="v">${vul}</div><div class="s">published vulnerabilities for the version in use</div></div></div>`;
     h.querySelectorAll('.tile').forEach(tl => tl.onclick = () => { const t = TABLES.find(t => t.opt.name === 'packages'); if (!t) return; const on = tl.classList.toggle('sel'); h.querySelectorAll('.tile').forEach(o => { if (o !== tl) o.classList.remove('sel'); o.setAttribute('aria-pressed', o.classList.contains('sel')); });
       t.st.filters = {}; if (on) { if (tl.dataset.v) t.st.filters.vulnerable = 'yes'; else t.st.filters.group = tl.dataset.g; } t.st.page = 0; t.render(); t.host.scrollIntoView({behavior:SMOOTH}); }); },
  'packages-table': h => DataTable(h, {name:'packages', title:'All packages', rows: D.packages, filters:['group','rec','vulnerable','repo'], sort:'group', asc:true, id: x => x.repo + x.id,
     cols: [{key:'id',label:'Package'},{key:'versions',label:'Version(s)'},{key:'latest',label:'Latest'},{key:'group',label:'Group',flabel:'groups',html:x=>`<span class="tag">${esc(x.group)}</span>`,sortv:x=>D.pgroups.findIndex(g=>g.group===x.group)},
            {key:'vulnerable',label:'Advisories',flabel:'advisory states',html:x=>x.advisories?`<span class="pill High">${esc(x.advisories)}</span>`:'',csv:x=>x.advisories},{key:'rec',label:'Recommendation',flabel:'recommendations',html:x=>x.rec?`<span class="tag">${esc(x.rec)}</span> ${esc(x.rec_version)}`:'',csv:x=>(x.rec+' '+x.rec_version).trim()},{key:'linux',label:'Runs on Linux',cls:'mid'},{key:'replacement',label:'Replacement / action',cls:'wide'},{key:'projects',label:'Projects',cls:'num'}],
     detail: x => `<p>${hl(x.note)}</p>${x.frameworks ? `<p><b>Latest targets:</b> ${esc(x.frameworks)}</p>` : ''}${x.rec_why ? `<p><b>Recommendation:</b> ${esc(x.rec_why)}</p>` : ''}${x.rec_risks ? `<p><b>Risks:</b> ${esc(x.rec_risks)}</p>` : ''}${x.licence_change ? `<p><b>Licence history:</b> ${esc(x.licence_change)}</p>` : ''}${x.licence ? `<p class="muted">Licence: ${esc(x.licence)}</p>` : ''}`}),
  'binaries-table': h => DataTable(h, {name:'binaries', title:'DLL references (not from NuGet)', rows: D.binaries || [], filters:['repo'], sort:'assembly', asc:true, id: x => x.repo + x.project + x.assembly,
     empty:'No project references a DLL outside a NuGet package.',
     cols: [{key:'assembly',label:'Assembly'},{key:'project',label:'Project',cls:'mid'},{key:'built_for',label:'Built for',cls:'mid'},{key:'nuget',label:'nuget.org',cls:'mid'},{key:'runs_on_linux',label:'Runs on Linux',cls:'mid'},{key:'action',label:'Action',cls:'wide'}],
     detail: x => `<p><b>HintPath:</b> <code>${esc(x.hint)}</code> (version ${esc(x.version)})</p><p><b>Other builds next to it:</b> ${esc(x.other_builds)}</p><p><b>Source:</b> ${esc(x.source)}</p>`}),
  'integrations-summary': h => { const c = D.tpCounts; h.innerHTML = `<div class="tiles">${[['Third-party / external services',c.external,'called over the internet: allow-lists, credentials, TLS'],['On-premises systems',c.onprem,'need VPN / Direct Connect, or must move too'],['Service SDKs',c.sdks,'client libraries for cloud / SaaS services'],['Identity providers & AD',c.identity,'sign-in and directory dependencies'],['Other integrations',c.other,'email, file transfer, SOAP, reporting, shares']].map(t=>`<div class="tile"><div class="l">${t[0]}</div><div class="v">${t[1]}</div><div class="s">${t[2]}</div></div>`).join('')}</div>`; },
  'thirdparty-table': h => DataTable(h, {name:'third-party-services', title:'Third-party / external services', rows: D.tp.external, filters:['used_by'], sort:'references', empty:'No external services found in code or configuration.',
     cols: [{key:'system',label:'Service / host'},{key:'protocols',label:'Protocol'},{key:'used_by',label:'Used by',flabel:'applications'},{key:'references',label:'Refs',cls:'num'},{key:'evidence',label:'Evidence'},{key:'needs',label:'Needed on AWS',cls:'wide'}]}),
  'onprem-table': h => DataTable(h, {name:'on-premises-systems', title:'On-premises / internal systems', rows: D.tp.onprem, filters:['used_by','protocols'], sort:'references', empty:'No on-premises host names or private IPs found.',
     cols: [{key:'system',label:'System'},{key:'protocols',label:'Protocol'},{key:'used_by',label:'Used by',flabel:'applications'},{key:'references',label:'Refs',cls:'num'},{key:'evidence',label:'Evidence',cls:'mid'},{key:'needs',label:'Needed on AWS',cls:'wide'}]}),
  'sdk-table': h => DataTable(h, {name:'service-sdks', title:'Service SDKs (packages that talk to external services)', rows: D.tp.sdks, filters:['service','status'], sort:'service', asc:true, empty:'No cloud / SaaS client libraries found.',
     cols: [{key:'service',label:'Service'},{key:'package',label:'Package'},{key:'versions',label:'Version(s)'},{key:'status',label:'Package group'},{key:'aws',label:'On AWS',cls:'wide'}]}),
  'effort-summary': h => { const e = D.effort;
     const pct = Math.round(100 - (e.lh / Math.max(1, lk(e.mh))) * 100);
     const p = e.phased;
     h.innerHTML = `<div class="kpis">${p ? `<div class="kpi"><div class="l">Planning figure (phased, tool-run)</div><div class="v">${p.h[0]}–${p.h[1]} h</div><div class="s">≈ ${p.days[0]}–${p.days[1]} dev-days · ${Math.round(p.buffer*100)}% buffer included · per repository in effort/&lt;repo&gt;/estimate.html</div></div>` : ''}<div class="kpi"><div class="l">${p ? 'Parametric cross-check' : 'Coding effort'}${e.ai ? ' (AI-assisted)' : ''}</div><div class="v">${e.lh} h</div><div class="s">≈ ${e.ld} person-days likely (P50) · P10–P90 ${hd(e.h, e.d)}${e.p80 ? ` · P80 ${e.p80} h` : ''}</div></div>
       <div class="kpi"><div class="l">Manual equivalent</div><div class="v">${e.mlh || Math.round(lk(e.mh))} h</div><div class="s">${hd(e.mh, e.md)}${e.ai && pct > 0 ? ` · AI saves ~${pct}%` : ''}</div></div>
       <div class="kpi"><div class="l">Size</div><div class="v">${e.kloc} KLOC</div><div class="s">${e.hpk} likely h per KLOC</div></div>
       <div class="kpi"><div class="l">Duration</div><div class="v">~${e.weeks} weeks</div><div class="s">team of ${e.engineers} engineers</div></div></div>
       <div class="card"><p class="muted small">Coding effort only: code and SQL conversion, fixing findings, and unit tests written with the code. QA, DevOps and infrastructure, project management and contingency are not included. ${e.ai ? `Assumes coding agents / AWS Transform for .NET / GitHub Copilot app modernization do the mechanical port; ${Math.round(e.ai_factor[0]*100)}–${Math.round(e.ai_factor[1]*100)}% of the manual effort remains for engineers to direct, review and fix. ` : ''}1 person-day = 8 hours.</p></div>`; },
  'workpackages-table': h => DataTable(h, {name:'effort', title:'Effort by work package', rows: D.wps, filters:['kind','r7'], sort:'lh', id: x => x.name,
     cols: [{key:'name',label:'Work package'},{key:'r7',label:'7R'},{key:'lh',label:'Effort (P10–P90)',html:x=>hd(x.h,x.d),csv:x=>rng(x.h,' h')},{key:'ld',label:'Likely (P50)',cls:'num',html:x=>`${x.lh} h / ${x.ld} d`,csv:x=>x.lh},
            {key:'mh',label:'Manual equiv.',html:x=>rng(x.mh,' h'),csv:x=>rng(x.mh,' h'),sortv:x=>x.mh[1]},{key:'size',label:'Size'}],
     detail: x => `<h5>Work items</h5>${list(x.items)}<h5>Findings costed (AI-assisted hours)</h5>${list(x.findings)}<p class="muted small">Main drivers: ${hl(x.drivers || '—')}</p>`}),
  'gantt': h => { const T = D.timeline; if (!T.length) { card(h, '<p class="muted">Not estimated.</p>'); return; } const end = Math.max(...T.map(p => p.start + p.weeks)); const W = 100 / end;
     card(h, `<h3>Phased timeline</h3><div class="gantt"><div class="gscale"><span></span><span>${Array.from({length:end},(_, i)=>`<span style="display:inline-block;width:${W}%">${(i % Math.max(1,Math.ceil(end/16)))===0 ? 'W'+(i+1) : ''}</span>`).join('')}</span></div>
     ${T.map(p => `<div class="grow"><span title="${esc(p.phase)}">${hl(p.phase)}</span><span class="gtrack" style="--w:${W}%"><span class="gbar" style="left:${p.start*W}%;width:${p.weeks*W}%" title="week ${p.start+1}, ${p.weeks} week(s)"></span></span></div>`).join('')}
     <p class="muted small">Weeks from project start; overlapping bars run in parallel. Total ~${end} weeks.</p></div>`); },
  'architecture-map': h => drawMap(h),
  'dependencies-table': h => DataTable(h, {name:'dependencies', title:'All upstream and downstream systems', rows: D.deps, filters:['kind','repo'], sort:'kind', asc:true, cols: [{key:'kind',label:'Kind'},{key:'system',label:'System'},{key:'details',label:'Protocol / details'},{key:'count',label:'Refs',cls:'num'},{key:'evidence',label:'Evidence'}]}),
  'questions-table': h => DataTable(h, {name:'open-questions', title:'Open questions for the client', rows: D.questions, filters:['area'], sort:'n', asc:true, cols: [{key:'n',label:'#',cls:'num'},{key:'area',label:'Area'},{key:'question',label:'Question',cls:'wide'},{key:'raised',label:'Raised by',html:x=>/^F-\d+/.test(x.raised)?`<a class="fref" href="#finding-${esc(x.raised)}">${esc(x.raised)}</a>`:hl(x.raised)}],
     csvCols: [{key:'n',label:'#'},{key:'area',label:'Area'},{key:'question',label:'Question'},{key:'raised',label:'Raised by'},{key:'answer',label:'Answer',csv:()=>''}]}),
  'projects-table': h => DataTable(h, {name:'projects', title:'Projects', rows: D.projects, filters:['type','format','repo'], sort:'loc', cols: [{key:'project',label:'Project'},{key:'type',label:'Type'},{key:'tfm',label:'TFM'},{key:'format',label:'Format'},{key:'packages',label:'Packages'},{key:'language',label:'Language'},{key:'loc',label:'LOC',cls:'num'},{key:'support',label:'Support status'}]}),
  'winapi-table': h => DataTable(h, {name:'windows-and-legacy-api-usage', title:'Every Windows-only and legacy API occurrence', rows: D.winapi, filters:['api'], sort:'ref', asc:true, cols: [{key:'ref',label:'Ref',html:x=>`<a class="fref" href="#finding-${esc(x.ref)}">${esc(x.ref)}</a>`},{key:'api',label:'API / technology',flabel:'APIs'},{key:'loc',label:'Location'},{key:'code',label:'Code',html:x=>`<code>${hl(x.code)}</code>`}]}),
  'glossary': h => card(h, `<h3>Glossary</h3><div class="tablewrap"><table class="md glossary"><tbody>${(window.GLOSSARY||[]).map(g => `<tr><th>${esc(g[0])}</th><td>${esc(g[1])}</td></tr>`).join('')}</tbody></table></div>`),
  // ---- developer screens: what to do first, in which order, per project
  'next-steps': h => { const P = D.P || {projects: [], waves: []}; const pil = P.pilot; const draft = D.apps.filter(a => a.reviewed !== 'reviewed').length; const sev = D.sev || {};
     const authHi = (D.auth || []).filter(a => ['Blocker','High'].includes(a.worst)).length; const pk = D.packages.filter(p => !['Keep'].includes(p.action)).length;
     const items = [
       pil && ['order', `Start with ${pil.name}`, pil.why + (pil.needs_first.length ? ` Port first: ${pil.needs_first.join(', ')}.` : '')],
       P.waves.length && ['order', `${P.waves.length} migration wave${P.waves.length === 1 ? '' : 's'}, ${P.projects.length} projects`, P.waves.map(w => `Wave ${w.wave}: ${w.projects.slice(0, 4).join(', ')}${w.projects.length > 4 ? ' +' + (w.projects.length - 4) : ''}`).join(' · ')],
       ['work', `${(sev.Blocker||0) + (sev.High||0)} blocker / high findings to fix`, 'Grouped by project in migration order, each with what to change and where.'],
       (D.auth || []).length && ['security', `Sign-in and access rules: ${authHi} application${authHi === 1 ? '' : 's'} with high-risk auth`, (D.auth || []).map(a => `${a.app}: ${a.who}`).join(' · ')],
       ['packages', `${pk} package${pk === 1 ? '' : 's'} to change`, 'Replace, remove or upgrade, with the target version.'],
       ['risks', `${D.questions.length} questions for the client${draft ? `, ${draft} 7R decision${draft === 1 ? '' : 's'} still draft` : ''}`, 'Answers change the plan: ask them first.']].filter(Boolean);
     card(h, `<h3>What to do first</h3><ol class="next">${items.map(([t, a, b]) => `<li><a href="#${t}" data-goto="${t}"><b>${esc(a)}</b></a><span>${esc(b)}</span></li>`).join('')}</ol>`);
     h.querySelectorAll('[data-goto]').forEach(a => a.onclick = e => { e.preventDefault(); show(a.dataset.goto); }); },
  'pilot': h => { const p = (D.P || {}).pilot; if (!p) { h.remove(); return; } const x = D.P.projects.find(y => y.key === p.key) || {};
     card(h, `<h3>Pilot: ${esc(p.name)}</h3><p>${esc(p.why)}</p><div class="row2"><span class="pill ${esc(p.difficulty)}">${esc(p.difficulty)}</span><span class="tag">${esc(x.kind || '')}</span><span class="tag">${esc(x.r7 || '')}</span><span class="tag">wave ${x.wave}</span></div>
       ${p.needs_first.length ? `<p><b>Port first:</b> ${p.needs_first.map(esc).join(', ')}</p>` : '<p class="muted">Nothing else in the estate has to move before it.</p>'}`); },
  'waves': h => { const P = D.P; if (!P || !P.projects.length) { card(h, '<p class="muted">No projects inventoried.</p>'); return; }
     card(h, `<h3>Migration waves</h3><p class="muted small">Left to right: a project starts when everything it depends on (to its left) has moved. Colour = difficulty; ▣ = deployable. Select a project for its details.</p>
       <div class="waves">${P.waves.map(w => `<div class="wave"><h4>Wave ${w.wave}</h4><div class="muted small">${esc(w.summary)}</div>${P.projects.filter(x => x.wave === w.wave).map(x => `<button type="button" class="pnode ${esc(x.difficulty)}" data-k="${esc(x.key)}" title="${esc(x.kind + ' · ' + x.r7 + ' · blast radius ' + x.blast.level)}"><span class="pn">${x.deployable ? '▣ ' : ''}${esc(x.name)}</span><span class="ps">${esc(x.kind)} · ${esc(x.r7)}</span><span class="ps">${esc(x.difficulty)} · blast ${esc(x.blast.level)}${x.blast.transitive ? ' (' + x.blast.transitive + ')' : ''}</span></button>`).join('')}</div>`).join('')}</div>`);
     h.querySelectorAll('.pnode').forEach(b => b.onclick = () => openProject(b.dataset.k)); },
  'order-table': h => { const P = D.P || {projects: []}; DataTable(h, {name:'migration-order', title:'Migration order (every project)', rows: P.projects, filters:['wave','difficulty','r7','kind','repo'], sort:'order', asc:true, id: x => x.key,
     cols: [{key:'order',label:'#',cls:'num'},{key:'wave',label:'Wave',cls:'num'},{key:'name',label:'Project',html:x=>`${x.deployable ? '▣ ' : ''}<b>${hl(x.name)}</b><div class="muted small">${esc(x.repo)}</div>`},{key:'kind',label:'Kind'},
            {key:'difficulty',label:'Difficulty',html:x=>pill(x.difficulty),sortv:x=>['Easy','Medium','Hard'].indexOf(x.difficulty)},{key:'r7',label:'7R'},
            {key:'needs',label:'Port first',cls:'mid',html:x=>hl(x.needs_first.join(', ') || '—'),csv:x=>x.needs_first.join(', ')},{key:'users',label:'Used by',cls:'mid',html:x=>hl(x.used_by.map(u=>u.name).join(', ') || '—'),csv:x=>x.used_by.map(u=>u.name).join(', ')},
            {key:'blast',label:'Blast radius',html:x=>`${pill(x.blast.level === 'High' ? 'High' : x.blast.level === 'Medium' ? 'Medium' : 'Low')} <span class="muted small">${x.blast.transitive} project(s)${x.blast.fan_in ? ', fan-in ' + x.blast.fan_in : ''}</span>`,csv:x=>x.blast.level,sortv:x=>x.blast.transitive * 1000 + x.blast.fan_in}],
     detail: projectDetail, text: x => [x.name, x.kind, x.r7, x.target, x.repo, x.needs_first.join(' '), x.r7_why.join(' ')].join(' ')}); },
  'projects-7r': h => { const P = D.P || {projects: []}; const cnt = {}; P.projects.forEach(x => cnt[x.r7] = (cnt[x.r7] || 0) + 1); const dif = {}; P.projects.forEach(x => dif[x.difficulty] = (dif[x.difficulty] || 0) + 1);
     h.innerHTML = `<div class="tiles">${['Easy','Medium','Hard'].map(d => `<div class="tile"><div class="l"><span class="pill ${d}">${d}</span></div><div class="v">${dif[d] || 0}</div><div class="s">${{Easy:'APIs, class libraries, console / worker: the logic moves intact',Medium:'service hosts, MVC UIs, or easy projects with blockers',Hard:'Web Forms / desktop UIs (rewritten), Windows-bound code, very large'}[d]}</div></div>`).join('')}
       ${Object.entries(cnt).sort((a,b)=>b[1]-a[1]).map(([k, v]) => `<div class="tile"><div class="l">${esc(k)}</div><div class="v">${v}</div><div class="s">project${v === 1 ? '' : 's'}</div></div>`).join('')}</div>`;
     const host = document.createElement('div'); h.appendChild(host);
     DataTable(host, {name:'projects-7r', title:'Every project: kind, difficulty and 7R (class libraries included)', rows: P.projects, filters:['kind','difficulty','r7','repo'], sort:'order', asc:true, id: x => x.key,
       cols: [{key:'name',label:'Project',html:x=>`${x.deployable ? '▣ ' : ''}<b>${hl(x.name)}</b><div class="muted small">${esc(x.repo)} · ${esc(x.tfm)}</div>`},{key:'kind',label:'Kind'},{key:'loc',label:'Lines',cls:'num',html:x=>(x.loc||0).toLocaleString()},
              {key:'difficulty',label:'Difficulty',html:x=>pill(x.difficulty),sortv:x=>['Easy','Medium','Hard'].indexOf(x.difficulty)},{key:'r7',label:'7R'},{key:'target',label:'Target',cls:'mid',html:x=>hl(x.target.split(' - ')[0])},
              {key:'wave',label:'Wave',cls:'num'},{key:'findings',label:'Findings',cls:'num'}], detail: projectDetail}); },
  'project-graph': h => { const P = D.P; if (!P || !P.projects.length) { card(h, '<p class="muted">No projects inventoried.</p>'); return; }
     const waves = [...new Set(P.projects.map(x => x.wave))].sort((a,b)=>a-b);
     const repos = [...new Set(P.projects.map(x => x.repo))].sort();
     card(h, `<h3>Project dependency map</h3><div class="tools">${repos.length > 1 ? `<select class="prepo" aria-label="Show one repository"><option value="">All repositories</option>${repos.map(r => `<option>${esc(r)}</option>`).join('')}</select>` : ''}<span class="muted small">Columns are waves: arrows point from a project to what it needs. Hover a project to see what it needs (left) and what needs it (right). Colour = difficulty.</span></div>
       <div class="amap pmap"><svg></svg><div class="cols" style="grid-template-columns:repeat(${waves.length},minmax(170px,1fr));min-width:${waves.length * 210}px">${waves.map(w => `<div class="col"><h4>Wave ${w}</h4>${P.projects.filter(x => x.wave === w).map(x => `<div class="node" tabindex="0" data-id="${esc(x.key)}" data-repo="${esc(x.repo)}" style="--c:var(--${x.difficulty === 'Easy' ? 'ready' : x.difficulty === 'Medium' ? 'medium' : 'blocker'})"><div>${x.deployable ? '▣ ' : ''}${esc(x.name)}</div><div class="s">${esc(x.kind)} · ${esc(x.r7)}</div></div>`).join('')}</div>`).join('')}</div></div>`);
     const M = {edges: P.edges.map(e => [e.from_key, e.to_key, e.how])};
     const box = h.querySelector('.amap'), svg = box.querySelector('svg'), inner = box.querySelector('.cols');
     function lines() { if (box.offsetParent === null) return; const b = inner.getBoundingClientRect(); svg.setAttribute('width', inner.scrollWidth); svg.setAttribute('height', inner.scrollHeight);
       svg.innerHTML = '<defs><marker id="pm-ar" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L8,4L0,8z"/></marker></defs>' + M.edges.map(([a, z, k]) => { const A = box.querySelector(`.node[data-id="${CSS.escape(a)}"]`), Z = box.querySelector(`.node[data-id="${CSS.escape(z)}"]`); if (!A || !Z || A.style.display === 'none' || Z.style.display === 'none') return '';
         // a project points at what it needs: usually a column to its left; same column = a cycle (they move together)
         const ra = A.getBoundingClientRect(), rz = Z.getBoundingClientRect(), y1 = ra.top + ra.height/2 - b.top, y2 = rz.top + rz.height/2 - b.top; let d;
         if (Math.abs(rz.left - ra.left) < 5) { const x = ra.left - b.left; d = `M${x},${y1} C${x-40},${y1} ${x-40},${y2} ${x},${y2}`; }
         else { const back = rz.left < ra.left, x1 = (back ? ra.left : ra.right) - b.left, x2 = (back ? rz.right : rz.left) - b.left, dx = (x2 - x1) / 2; d = `M${x1},${y1} C${x1+dx},${y1} ${x2-dx},${y2} ${x2},${y2}`; }
         return `<path marker-end="url(#pm-ar)" data-a="${esc(a)}" data-z="${esc(z)}" d="${d}"><title>${esc(k)}</title></path>`; }).join(''); }
     box.querySelectorAll('.node').forEach(n => { n.onmouseenter = () => { const id = n.dataset.id; const linked = new Set([id]); M.edges.forEach(([a,z]) => { if (a === id) linked.add(z); if (z === id) linked.add(a); });
         box.querySelectorAll('.node').forEach(o => o.classList.toggle('dim', !linked.has(o.dataset.id))); svg.querySelectorAll('path').forEach(p => { const on = p.dataset.a === id || p.dataset.z === id; p.classList.toggle('hl', on); p.classList.toggle('dim', !on); }); };
       n.onmouseleave = () => { box.querySelectorAll('.node').forEach(o => o.classList.remove('dim')); svg.querySelectorAll('path').forEach(p => p.classList.remove('hl','dim')); };
       n.onfocus = n.onmouseenter; n.onblur = n.onmouseleave; n.onclick = () => openProject(n.dataset.id); });
     // one repository: its projects plus what they need from, and give to, other repositories
     const pr = h.querySelector('.prepo'); if (pr) pr.onchange = () => { const r = pr.value; const keep = new Set(P.projects.filter(x => !r || x.repo === r).map(x => x.key));
       if (r) M.edges.forEach(([a, z]) => { const ra = P.projects.find(x => x.key === a), rz = P.projects.find(x => x.key === z); if (ra && ra.repo === r) keep.add(z); if (rz && rz.repo === r) keep.add(a); });
       box.querySelectorAll('.node').forEach(n => n.style.display = keep.has(n.dataset.id) ? '' : 'none'); lines(); };
     window.addEventListener('resize', lines); h._draw = lines; },
  'deployable-needs': h => { const P = D.P || {projects: []}; const ord = P.projects.map(x => x.name); const bins = D.binaries || [];
     const rows = P.projects.filter(x => x.deployable).map(x => ({...x, needs: x.needs_first.slice().sort((a,b) => ord.indexOf(a) - ord.indexOf(b)),
       dlls: [...new Set(x.depends_on.filter(d => d.how.startsWith('DLL from')).map(d => d.name + ' (' + d.repo + ')'))], ext: [...new Set(bins.filter(b => b.repo === x.repo && b.project === x.path).map(b => b.assembly))]}));
     DataTable(h, {name:'deployable-needs', title:'What each deployable needs ported first', rows, filters:['repo'], sort:'order', asc:true, id: x => x.key, empty:'No deployables.',
       cols: [{key:'name',label:'Deployable',html:x=>`<b>${hl(x.name)}</b><div class="muted small">${esc(x.kind)}</div>`},{key:'wave',label:'Wave',cls:'num'},{key:'needs',label:'Port first, in this order',cls:'wide',html:x=>x.needs.length ? x.needs.map((n,i)=>`<span class="tag">${i+1}. ${hl(n)}</span>`).join(' ') : '<span class="muted">nothing</span>',csv:x=>x.needs.join(' > ')},
              {key:'dlls',label:'DLLs from other repositories',cls:'mid',html:x=>hl(x.dlls.join(', ') || '—'),csv:x=>x.dlls.join(', ')},{key:'ext',label:'Other DLLs (no NuGet)',cls:'mid',html:x=>hl(x.ext.join(', ') || '—'),csv:x=>x.ext.join(', ')},
              {key:'difficulty',label:'Difficulty',html:x=>pill(x.difficulty)}]}); },
  'repo-order': h => { const R = (D.P || {}).repos || []; if (R.length < 2 || !R.some(r => r.after.length)) { h.remove(); return; }
     DataTable(h, {name:'repository-order', title:'Repository order (DLLs built by one repository and used by another)', rows: R, sort:'step', asc:true, cols:[{key:'step',label:'Step',cls:'num'},{key:'repo',label:'Repository'},{key:'after',label:'Moves after',cls:'wide',html:x=>hl(x.after.join(', ') || '—'),csv:x=>x.after.join(', ')}]}); },
  'graph-links': h => { const G = D.graphs || []; if (!G.length) { card(h, '<p class="muted">No code graph yet (map_graphs.py).</p>'); return; }
     card(h, `<h3>Explore the code</h3><p>Each repository has an explorer for blast radius (what depends on a class, file or package), dependencies and paths between two pieces of code, plus graphify's own interactive graph, code tree, call flows and wiki. Run <code>graph_ui.py --serve</code> in the workspace to also ask free-text questions.</p>
       ${G.map(g => `<div class="plan"><h4>${esc(g.repo)} <span class="muted small">${(g.nodes||0).toLocaleString()} code elements · ${(g.edges||0).toLocaleString()} relationships · ${g.communities} clusters</span></h4><p>${g.pages.map(([t, u]) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(t)}</a>`).join(' · ')}</p>
       ${g.files.length ? `<p class="small"><b>Most depended-on files</b> (other files using them): ${g.files.map(([f, n]) => `<code>${esc(f)}</code> ${n}`).join(' · ')}</p>` : ''}
       <p class="small muted">Query from the workspace: <code>graphify query "&lt;question&gt;" --graph ${esc(g.graph)}</code></p></div>`).join('')}`); },
  'work-items': h => { const P = D.P || {projects: []}; const order = new Map(P.projects.map(x => [x.repo + ':' + x.path, x]));
     const groups = new Map(); D.findings.forEach(f => { const k = f.repo + ':' + f.project; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(f); });
     const keys = [...groups.keys()].sort((a, b) => ((order.get(a) || {order: 1e9}).order) - ((order.get(b) || {order: 1e9}).order));
     const st = {min: 'Medium'}; const lv = s => SEV.indexOf(s);
     function draw() { const q = Q.toLowerCase();
       h.innerHTML = `<div class="card"><h3>Work items by project</h3><p class="muted small">Projects in migration order. Each line: what to change, why, and where (first occurrences; the finding has all of them).</p><div class="tools"><label class="small">Show <select class="wmin"><option value="High" ${st.min==='High'?'selected':''}>Blocker and High</option><option value="Medium" ${st.min==='Medium'?'selected':''}>down to Medium</option><option value="Info" ${st.min==='Info'?'selected':''}>everything</option></select></label></div>
       ${keys.map(k => { const x = order.get(k); const fs = groups.get(k).filter(f => lv(f.severity) <= lv(st.min)).filter(f => !q || findingText(f).toLowerCase().includes(q)).sort((a,b) => lv(a.severity) - lv(b.severity)); if (!fs.length) return '';
         return `<details class="wi" ${fs.some(f => lv(f.severity) <= 1) ? 'open' : ''}><summary><b>${esc(x ? x.name : k.split(':').pop())}</b> <span class="muted small">${x ? `#${x.order} · wave ${x.wave} · ${esc(x.kind)} · ` : ''}${fs.length} item${fs.length === 1 ? '' : 's'}</span> ${x ? pill(x.difficulty) : ''}</summary>
           <ol>${fs.map(f => `<li>${pill(f.severity)} <b>${hl(f.title)}</b> <a class="fref" href="#finding-${esc(f.ref)}">${esc(f.ref)}</a><div class="small"><b>Do:</b> ${hl(f.fix)}</div><div class="small muted">${hl(f.why)}</div><div class="small mono">${f.evidence.slice(0,3).map(e => esc(e.loc)).join(' · ')}${f.count > 3 ? ` · +${f.count - 3} more` : ''}</div></li>`).join('')}</ol></details>`; }).join('') || '<p class="muted">Nothing at this level.</p>'}</div>`;
       h.querySelector('.wmin').onchange = e => { st.min = e.target.value; draw(); }; }
     draw(); h._redraw = draw; WORK.push(draw); },
  'auth': h => { const A = D.auth || []; if (!A.length) { card(h, '<p class="muted">No applications classified yet.</p>'); return; }
     const AREA = {authn:'Sign-in', authz:'Access rules', secrets:'Secrets', session:'Session'};
     h.innerHTML = `<div class="tiles">${A.map(a => `<div class="tile"><div class="l">${esc(a.app)}</div><div class="v small-v">${esc(a.who)}</div><div class="s">${esc(a.authn.join(', ') || 'no sign-in found in code')}</div></div>`).join('')}</div>` +
       A.map(a => `<div class="card auth"><h3>${esc(a.app)} <span class="muted small">${esc(a.repo)} · ${esc(a.who)}</span></h3>
         <div class="callout"><b>Recommended on AWS:</b> ${hl(a.aws)}.<br><b>On ASP.NET Core:</b> ${hl(a.core)}.<br><span class="muted">${hl(a.why)}</span></div>
         ${a.mechanisms.length ? `<div class="tablewrap"><table class="md"><thead><tr><th>Area</th><th>Today</th><th>How it works now</th><th>On ASP.NET Core</th><th>AWS options (first = recommended)</th><th>Where</th></tr></thead><tbody>${a.mechanisms.map(m => `<tr><td>${esc(AREA[m.area] || m.area)}</td><td><b>${hl(m.label)}</b> ${pill(m.severity)}</td><td>${hl(m.today)}</td><td>${hl(m.core)}</td><td><ol class="tight">${m.aws.map(x => `<li>${hl(x)}</li>`).join('')}</ol></td><td class="small mono">${m.where.slice(0,3).map(esc).join('<br>')}<br>${m.refs.map(r => `<a class="fref" href="#finding-${esc(r)}">${esc(r)}</a>`).join(' ')}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">No sign-in or access check found in this application\'s code.</p>'}
         <h4>Steps for the developer</h4><ol>${a.steps.map(s => `<li>${hl(s)}</li>`).join('')}</ol>${a.questions.length ? `<h4>Ask the client</h4><ul>${a.questions.map(q => `<li>${hl(q)}</li>`).join('')}</ul>` : ''}</div>`).join(''); },
  'package-actions': h => { const acts = D.pkgActions || []; const cnt = {}; D.packages.forEach(p => cnt[p.action] = (cnt[p.action] || 0) + 1);
     h.innerHTML = `<div class="tiles">${acts.filter(([a]) => cnt[a]).map(([a, d]) => `<div class="tile" data-a="${esc(a)}" tabindex="0" role="button" aria-pressed="false"><div class="l">${esc(a)}</div><div class="v">${cnt[a]}</div><div class="s">${esc(d)}</div></div>`).join('')}</div>`;
     const host = document.createElement('div'); h.appendChild(host);
     const ord = acts.map(a => a[0]);
     const t = DataTable(host, {name:'package-actions', title:'Packages: what to do with each', rows: D.packages, filters:['action','repo'], sort:'action', asc:true, id: x => x.repo + x.id,
       cols: [{key:'action',label:'Action',html:x=>`<b>${esc(x.action)}</b>`,sortv:x=>ord.indexOf(x.action)},{key:'id',label:'Package'},{key:'versions',label:'In use'},{key:'rec_version',label:'Target version',html:x=>esc(x.rec_version || x.latest || '')},
              {key:'replacement',label:'What to do',cls:'wide',html:x=>hl(x.replacement || x.note || '')},{key:'advisories',label:'Advisories',html:x=>x.advisories?`<span class="pill High">${esc(x.advisories)}</span>`:''},{key:'projects',label:'Projects',cls:'num'}],
       detail: x => `<p>${hl(x.note)}</p>${x.rec_why ? `<p><b>Why:</b> ${esc(x.rec_why)}</p>` : ''}${x.rec_risks ? `<p><b>Risks:</b> ${esc(x.rec_risks)}</p>` : ''}${x.frameworks ? `<p class="muted">Latest targets: ${esc(x.frameworks)}</p>` : ''}${x.licence ? `<p class="muted">Licence: ${esc(x.licence)}${x.licence_change ? ' · ' + esc(x.licence_change) : ''}</p>` : ''}`});
     t.st.filters.action = ''; t.render();
     h.querySelectorAll('.tile').forEach(tl => tl.onclick = () => { const on = tl.classList.toggle('sel'); h.querySelectorAll('.tile').forEach(o => { if (o !== tl) o.classList.remove('sel'); o.setAttribute('aria-pressed', o.classList.contains('sel')); }); t.st.filters.action = on ? tl.dataset.a : ''; t.st.page = 0; t.render(); }); },
};
const WORK = [];
const projectDetail = x => `<div class="cols2"><div><h5>7R: ${esc(x.r7)}</h5><p><b>Target:</b> ${hl(x.target)}</p>${list(x.r7_why)}<h5>Difficulty: ${esc(x.difficulty)}</h5>${list(x.difficulty_why)}</div>
  <div><h5>Port first (${x.needs_first.length})</h5>${list(x.depends_on.map(d => d.name + ' — ' + d.how + (d.repo !== x.repo ? ' (' + d.repo + ')' : '')))}<h5>Used by (${x.used_by.length})</h5>${list(x.used_by.map(u => u.name + ' — ' + u.how))}
  <h5>Blast radius: ${esc(x.blast.level)}</h5><p>${x.blast.transitive ? x.blast.transitive + ' project' + (x.blast.transitive === 1 ? ' depends' : 's depend') + ' on it' : 'No other project depends on it'}${x.blast.deployables.length ? '; deployables to retest: ' + x.blast.deployables.map(esc).join(', ') : ''}${x.blast.fan_in ? '; ' + x.blast.fan_in + ' uses of its code from other files' : ''}.</p></div></div>
  ${x.blockers.length ? '<h5>Blocker / high findings</h5>' + list(x.blockers) : ''}${x.cycle.length ? `<div class="callout warn">In a dependency cycle with ${x.cycle.map(esc).join(', ')}: they move together.</div>` : ''}
  ${(D.graphs || []).some(g => g.repo === x.repo) ? `<p class="small"><a href="${esc(((D.graphs.find(g => g.repo === x.repo).pages.find(p => p[0].startsWith('Explorer')) || [])[1]) || '#')}#q=${encodeURIComponent(x.name)}" target="_blank" rel="noopener">Open in the graph explorer</a></p>` : ''}`;
function openProject(key) { const t = TABLES.find(t => t.opt.name === 'projects-7r') || TABLES.find(t => t.opt.name === 'migration-order'); if (!t) return; const tab = t.host.closest('.tab'); if (tab) show(tab.id.slice(4)); t.openRow(key);
  const row = t.host.querySelector(`tr.row[data-id="${CSS.escape(key)}"]`); if (row) { row.scrollIntoView({behavior: SMOOTH, block: 'center'}); row.focus({preventScroll: true}); } }

function drawMap(h) {
  const M = D.map; const cols = [['clients','Clients'],['apps','Applications'],['libs','Shared libraries'],['data','Data'],['external','External systems']];
  const colour = n => n.col === 'external' ? (n.r7 === 'onprem' ? 'var(--blocked)' : n.r7 === 'more' ? 'var(--na)' : 'var(--port)') : ({Replatform:'var(--ready)',Refactor:'var(--port)',Retain:'var(--windows)',Rehost:'var(--medium)',Retire:'var(--na)',Repurchase:'var(--high)',Relocate:'var(--medium)'}[n.r7] || 'var(--accent)');
  card(h, `<h3>Application and dependency map</h3><div class="tools"><label class="small"><input type="checkbox" class="hideRetired" checked> hide retired applications</label><span class="muted small">Hover a box to highlight its connections. Colour = 7R decision (green Replatform, blue Refactor, purple Retain, amber Rehost, grey Retire); red = on-premises system, blue = third-party.</span></div>
    <div class="amap"><svg></svg><div class="cols">${cols.map(([k,t]) => `<div class="col"><h4>${t}</h4>${M.nodes.filter(n => n.col === k).map(n => `<div class="node ${n.r7==='Retire'?'retired':''}" tabindex="0" data-id="${esc(n.id)}" style="--c:${colour(n)}"><div>${esc(n.label)}</div>${n.sub ? `<div class="s">${esc(n.sub)}</div>` : ''}</div>`).join('') || '<div class="muted small">—</div>'}</div>`).join('')}</div></div>`);
  const box = h.querySelector('.amap'), svg = box.querySelector('svg'), inner = box.querySelector('.cols');
  function lines() {
    if (box.offsetParent === null) return;
    const b = inner.getBoundingClientRect(); svg.setAttribute('width', inner.scrollWidth); svg.setAttribute('height', inner.scrollHeight);
    svg.innerHTML = M.edges.map(([a, z, k]) => { const A = box.querySelector(`.node[data-id="${CSS.escape(a)}"]`), Z = box.querySelector(`.node[data-id="${CSS.escape(z)}"]`);
      if (!A || !Z || A.style.display === 'none' || Z.style.display === 'none') return '';
      const ra = A.getBoundingClientRect(), rz = Z.getBoundingClientRect(); const fwd = rz.left >= ra.right - 4; const same = Math.abs(rz.left - ra.left) < 5;
      const x1 = (fwd || same ? ra.right : ra.left) - b.left, y1 = ra.top + ra.height/2 - b.top, x2 = (fwd ? rz.left : rz.right) - b.left, y2 = rz.top + rz.height/2 - b.top;
      const dx = same ? 40 : Math.max(30, Math.abs(x2 - x1) / 2) * (fwd ? 1 : -1);
      return `<path data-a="${esc(a)}" data-z="${esc(z)}" d="M${x1},${y1} C${x1+dx},${y1} ${x2-dx},${y2} ${x2},${y2}"><title>${esc(k)}</title></path>`; }).join(''); }
  h.querySelector('.hideRetired').onchange = e => { box.querySelectorAll('.node.retired').forEach(n => n.style.display = e.target.checked ? 'none' : ''); lines(); };
  box.querySelectorAll('.node').forEach(n => { n.onmouseenter = () => { const id = n.dataset.id; const linked = new Set([id]); M.edges.forEach(([a,z]) => { if (a === id) linked.add(z); if (z === id) linked.add(a); });
      box.querySelectorAll('.node').forEach(o => o.classList.toggle('dim', !linked.has(o.dataset.id))); n.classList.add('hl');
      svg.querySelectorAll('path').forEach(p => { const on = p.dataset.a === id || p.dataset.z === id; p.classList.toggle('hl', on); p.classList.toggle('dim', !on); }); };
    n.onmouseleave = () => { box.querySelectorAll('.node').forEach(o => o.classList.remove('dim','hl')); svg.querySelectorAll('path').forEach(p => p.classList.remove('hl','dim')); };
    n.onfocus = n.onmouseenter; n.onblur = n.onmouseleave; });
  box.querySelectorAll('.node.retired').forEach(n => n.style.display = 'none');
  window.addEventListener('resize', lines); h._draw = lines;
}
function renderPlans(h) { h = h || document.getElementById('app-plans-host'); if (!h) return;
  h.innerHTML = D.apps.map(x => `<div class="plan"><h4>${hl(x.name)} <span class="muted small">${esc(x.repo)}</span></h4><div class="row2"><span class="tag">${esc(x.r7)}</span><span class="tag">${esc(typeName(x.type))}</span><span class="tag">${esc(x.risk)} risk</span><span class="tag">${rng(x.h)} h (${dd(x.d)} d)</span><span class="tag">${x.reviewed==='reviewed'?'reviewed decision':'draft — pending review'}</span></div>
  <p><b>Target:</b> ${hl(x.target)}</p><p><b>Why:</b> ${x.rationale.map(hl).join(' ')}</p>${x.options.length ? `<p><b>Options:</b> ${x.options.map((o,i)=>`(${i+1}) ${hl(o)}`).join(' ')}</p>` : ''}${x.drivers.length ? `<p class="muted small"><b>Effort drivers:</b> ${x.drivers.map(esc).join('; ')}</p>` : ''}</div>`).join(''); }

document.querySelectorAll('.component').forEach(h => { const n = h.dataset.component;
  if (n.startsWith('findings:')) findings(h, n.split(':')[1]); else if (n === 'app-plans') { h.id = 'app-plans-host'; renderPlans(h); } else if (C[n]) C[n](h); });
// "On this page" links for long tabs: one per titled block, pointing at the block (its title is re-rendered by filters)
document.querySelectorAll('.tab').forEach(tab => { const blocks = [...tab.querySelectorAll(':scope > .component, :scope > .card, :scope > .prose')].map((b, i) => { const t = b.querySelector('h3'); if (!t) return null; b.id = b.id || tab.id + '-s' + i; return [b.id, t.textContent.replace(/\s*\(\d+\)$/, '').replace(/ — click.*$/, '')]; }).filter(Boolean);
  if (blocks.length < 4) return; const nav = document.createElement('nav'); nav.className = 'jump'; nav.setAttribute('aria-label', 'On this page');
  nav.innerHTML = '<b>On this page</b>' + blocks.map(([id, t]) => `<a href="#${id}" data-jump="${id}">${esc(t)}</a>`).join('');
  const after = tab.querySelector(':scope > .intro') || tab.querySelector(':scope > h2'); after.after(nav); });
document.addEventListener('click', e => { const a = e.target.closest('a[data-jump]'); if (!a) return; e.preventDefault(); document.getElementById(a.dataset.jump).scrollIntoView({behavior: SMOOTH, block: 'start'}); });
function show(id, push = true) { const tab = document.getElementById('tab-' + id) ? id : 'overview';
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.id === 'tab-' + tab)); document.querySelectorAll('nav.side a').forEach(a => a.classList.toggle('active', a.dataset.tab === tab));
  if (push) history.replaceState(null, '', '#' + tab); window.scrollTo(0, 0); document.querySelector('nav.side').classList.remove('open');
  requestAnimationFrame(() => document.querySelectorAll('#tab-' + tab + ' .card').forEach(c => c._draw && c._draw())); }
document.querySelectorAll('nav.side a').forEach(a => a.onclick = e => { e.preventDefault(); show(a.dataset.tab); });
document.getElementById('menu').onclick = e => { const open = document.querySelector('nav.side').classList.toggle('open'); e.currentTarget.setAttribute('aria-expanded', open); };
const search = document.getElementById('q'); let timer;
search.oninput = () => { clearTimeout(timer); timer = setTimeout(() => { Q = search.value.trim(); TABLES.forEach(t => { t.st.page = 0; t.render(); }); renderPlans(); WORK.forEach(f => f());
  document.querySelectorAll('nav.side a').forEach(a => { const sec = document.getElementById('tab-' + a.dataset.tab); const b = a.querySelector('.badge'); if (!sec || !b) return;
    const n = Q ? (sec.textContent.toLowerCase().split(Q.toLowerCase()).length - 1) : 0; b.textContent = n; b.style.display = Q && n ? 'inline-block' : 'none'; }); }, 220); };
document.addEventListener('click', e => { const a = e.target.closest('a.fref'); if (!a) return; e.preventDefault(); const ref = a.getAttribute('href').replace('#finding-','');
  const t = TABLES.find(t => t.opt.name === 'findings-all'); if (!t) return; search.value = ''; Q = ''; TABLES.forEach(x => x.render()); show('findings'); t.openRow(ref);
  const row = document.querySelector(`#tab-findings tr[data-anchor="finding-${ref}"]`); (row || t.host).scrollIntoView({behavior:SMOOTH, block:'center'}); if (row) row.focus({preventScroll: true}); });
// keyboard: Enter / Space act on sortable headers, expandable rows, filter tiles and clickable bars; / jumps to search
document.addEventListener('keydown', e => { const typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);
  if (e.key === '/' && !typing) { e.preventDefault(); search.focus(); search.select(); return; }
  if (e.key === 'Escape' && document.activeElement === search && search.value) { search.value = ''; search.oninput(); return; }
  if ((e.key === 'Enter' || e.key === ' ') && !typing) { const el = e.target.closest('th[data-k], tr.row[tabindex], .tile[tabindex], .bar[tabindex]'); if (el && !e.target.closest('a, button')) { e.preventDefault(); el.click(); } } });
// top-level names in this inline script are globals: never reuse a window property (top, name, status, open...), it stops the whole report
const toTop = document.getElementById('totop'); window.addEventListener('scroll', () => toTop.classList.toggle('on', scrollY > 900), {passive: true}); toTop.onclick = () => window.scrollTo({top: 0, behavior: SMOOTH});
document.getElementById('theme').onclick = () => { const r = document.documentElement; const cur = r.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); r.dataset.theme = cur === 'dark' ? 'light' : 'dark'; try { localStorage.setItem('theme', r.dataset.theme); } catch (e) {} };
try { const t = localStorage.getItem('theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
window.addEventListener('hashchange', () => { const h = location.hash.slice(1); if (document.getElementById('tab-' + h)) show(h, false); });
// Copy buttons on code blocks (narratives): clipboard API, with a fallback for pages opened from disk
document.addEventListener('click', async e => { const b = e.target.closest('[data-copy]'); if (!b) return; const code = b.closest('figure').querySelector('pre').innerText; let ok = false;
  try { await navigator.clipboard.writeText(code); ok = true; } catch (err) { const t = document.createElement('textarea'); t.value = code; document.body.appendChild(t); t.select(); try { ok = document.execCommand('copy'); } catch (x) {} t.remove(); }
  const s = b.querySelector('span'); const was = s.textContent; s.textContent = ok ? 'Copied' : 'Copy failed'; setTimeout(() => { s.textContent = was; }, 1400); });
document.querySelector('.skip').onclick =e => { e.preventDefault(); document.getElementById('main').focus(); };
show((location.hash || '#overview').slice(1), false);
