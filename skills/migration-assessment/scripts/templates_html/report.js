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
const FLABEL = {r7:'7R decisions', type:'types', risk:'risk levels', repo:'repositories', kind:'kinds', status:'statuses', size:'sizes', level:'readiness levels', vulnerable:'advisory states', reviewed:'decision states', area:'areas', service:'services', severity:'severities', confidence:'confidence levels'};
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
  function render() {
    const fa = document.activeElement, keep = fa && wrap.contains(fa) ? (fa.dataset.k ? `th[data-k="${CSS.escape(fa.dataset.k)}"]` : fa.dataset.id !== undefined ? `tr.row[data-id="${CSS.escape(fa.dataset.id)}"]` : fa.dataset.a ? `[data-a="${fa.dataset.a}"]` : null) : null;
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
    if (opt.detail) wrap.querySelectorAll('tr.row').forEach(tr => tr.onclick = e => { if (e.target.closest('a')) return; const id = tr.dataset.id; st.open.has(id) ? st.open.delete(id) : st.open.add(id); render(); });
    wrap.querySelector('[data-a=csv]').onclick = () => csv(opt.csvCols || opt.cols, rows(), opt.name);
    const ex = wrap.querySelector('[data-a=expand]'); if (ex) ex.onclick = () => { if (st.open.size) st.open.clear(); else rows().forEach((x,i) => st.open.add(String(opt.id ? opt.id(x) : i))); render(); };
    const pv = wrap.querySelector('[data-a=prev]'); if (pv) { pv.onclick = () => { st.page = Math.max(0, st.page-1); render(); }; wrap.querySelector('[data-a=next]').onclick = () => { st.page++; render(); }; }
    if (keep) { const el = wrap.querySelector(keep); if (el) el.focus({preventScroll: true}); }
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
     cols: [{key:'name',label:'Application'},{key:'type',label:'Type',fmt:typeName,html:x=>hl(typeName(x.type)),csv:x=>typeName(x.type)},{key:'framework',label:'Framework'},{key:'loc',label:'LOC',cls:'num',html:x=>x.loc.toLocaleString()},{key:'r7',label:'7R'},
            {key:'target',label:'Target',cls:'mid',html:x=>hl(x.target.split(' - ')[0])},{key:'lh',label:'Effort (P10–P90)',html:x=>hd(x.h,x.d),csv:x=>rng(x.h,' h')},{key:'size',label:'Size'},
            {key:'risk',label:'Risk',html:x=>SEV.includes(x.risk)?pill(x.risk):hl(x.risk),sortv:x=>SEV.indexOf(x.risk)},{key:'reviewed',label:'Decision',fmt:v=>v==='reviewed'?'Reviewed':'Draft',html:x=>x.reviewed==='reviewed'?'Reviewed':'<span class="muted">Draft</span>'}],
     detail: x => `<h5>Target</h5><p>${hl(x.target)}</p><h5>Why</h5>${list(x.rationale)}<h5>Options considered</h5>${list(x.options)}<h5>Blocking / high findings</h5>${list(x.blockers)}<h5>Main effort drivers</h5>${list(x.drivers)}<h5>Work items</h5>${list(x.work)}${x.notes.length ? '<h5>To confirm</h5>' + list(x.notes) : ''}`}),
  'linux-scorecard': h => { const lv = {}; D.linux.forEach(r => lv[r.level] = (lv[r.level]||0) + 1);
     const names = {ready:['Linux-ready','already cross-platform, no blockers'], port:['Ready after porting','moves to .NET 10 on Linux with code changes (and replacing any Windows-only parts)'], blocked:['Blocked','Windows-bound: stays on Windows until redesigned'], windows:['Windows-only (desktop)','client app on user machines'], na:['Retiring','not assessed for Linux']};
     h.innerHTML = `<div class="tiles">${Object.keys(names).map(k => `<div class="tile" data-l="${k}" tabindex="0" role="button" aria-pressed="false" title="Show only these applications"><div class="l"><span class="lv ${k}">${names[k][0]}</span></div><div class="v">${lv[k]||0}</div><div class="s">${names[k][1]}</div></div>`).join('')}</div>`;
     const host = document.createElement('div'); h.appendChild(host);
     const t = DataTable(host, {name:'linux-readiness', title:'Readiness by application', rows: D.linux, filters:['level','repo'], sort:'level', asc:true, id: x => x.id,
       cols: [{key:'app',label:'Application'},{key:'framework',label:'Framework'},{key:'level',label:'Linux readiness',flabel:'readiness levels',html:x=>`<span class="lv ${x.level}">${esc(x.status)}</span>`,csv:x=>x.status,sortv:x=>['blocked','port','windows','ready','na'].indexOf(x.level)},
              {key:'windows_apis',label:'Windows APIs',cls:'num'},{key:'framework_blockers',label:'Framework blockers',cls:'num'},{key:'packages',label:'Incompatible pkgs',cls:'num'},{key:'paths',label:'Path issues',cls:'num'},
              {key:'time_culture',label:'Time / culture',cls:'num'},{key:'windows_auth',label:'Windows auth',cls:'num'},{key:'linux_build',label:'Linux build',cls:'mid'},{key:'summary',label:'What stops it',cls:'wide'}]});
     h.querySelectorAll('.tile').forEach(tl => tl.onclick = () => { const on = tl.classList.toggle('sel'); h.querySelectorAll('.tile').forEach(o => { if (o !== tl) o.classList.remove('sel'); o.setAttribute('aria-pressed', o.classList.contains('sel')); }); t.st.filters.level = on ? tl.dataset.l : ''; t.render(); }); },
  'linux-issues': h => DataTable(h, {name:'linux-issues', title:'What breaks on Linux — by issue type', rows: D.linuxIssues, filters:['severity'], sort:'severity', asc:true, empty:'No Linux blockers found.',
     cols: [{key:'severity',label:'Severity',html:x=>pill(x.severity),sortv:x=>SEV.indexOf(x.severity)},{key:'issue',label:'Issue',cls:'mid'},{key:'apps',label:'Applications',cls:'mid'},{key:'occurrences',label:'Occurrences',cls:'num'},{key:'refs',label:'Findings',html:x=>x.refs.split(', ').map(r=>`<a class="fref" href="#finding-${esc(r)}">${esc(r)}</a>`).join(' ')}],
     id: x => x.issue, detail: x => `<h5>Why it breaks</h5><p>${hl(x.why)}</p><h5>Fix</h5><p>${hl(x.fix)}</p>`}),
  'linux-build': h => DataTable(h, {name:'linux-build', title:'Linux build validation', rows: D.linuxBuild, filters:['status'], empty:'Not run yet (validate_linux_build.py).', cols:[{key:'project',label:'Project'},{key:'tfms',label:'TFM',html:x=>esc((x.tfms||[]).join(', '))},{key:'status',label:'Result'},{key:'detail',label:'Detail',cls:'wide'}]}),
  'package-groups': h => { const cnt = {}; D.packages.forEach(p => cnt[p.group] = (cnt[p.group]||0) + 1); const vul = D.packages.filter(p => p.vulnerable === 'yes').length;
     h.innerHTML = `<div class="tiles">${D.pgroups.map(g => `<div class="tile" data-g="${esc(g.group)}" tabindex="0" role="button" aria-pressed="false"><div class="l">${esc(g.group)}</div><div class="v">${cnt[g.group]||0}</div><div class="s">${esc(g.desc)}</div></div>`).join('')}<div class="tile" data-v="1" tabindex="0" role="button" aria-pressed="false"><div class="l">With security advisories</div><div class="v">${vul}</div><div class="s">published vulnerabilities for the version in use</div></div></div>`;
     h.querySelectorAll('.tile').forEach(tl => tl.onclick = () => { const t = TABLES.find(t => t.opt.name === 'packages'); if (!t) return; const on = tl.classList.toggle('sel'); h.querySelectorAll('.tile').forEach(o => { if (o !== tl) o.classList.remove('sel'); o.setAttribute('aria-pressed', o.classList.contains('sel')); });
       t.st.filters = {}; if (on) { if (tl.dataset.v) t.st.filters.vulnerable = 'yes'; else t.st.filters.group = tl.dataset.g; } t.st.page = 0; t.render(); t.host.scrollIntoView({behavior:SMOOTH}); }); },
  'packages-table': h => DataTable(h, {name:'packages', title:'All packages', rows: D.packages, filters:['group','rec','vulnerable','repo'], sort:'group', asc:true, id: x => x.repo + x.id,
     cols: [{key:'id',label:'Package'},{key:'versions',label:'Version(s)'},{key:'latest',label:'Latest'},{key:'group',label:'Group',flabel:'groups',html:x=>`<span class="tag">${esc(x.group)}</span>`,sortv:x=>D.pgroups.findIndex(g=>g.group===x.group)},
            {key:'vulnerable',label:'Advisories',flabel:'advisory states',html:x=>x.advisories?`<span class="pill High">${esc(x.advisories)}</span>`:'',csv:x=>x.advisories},{key:'rec',label:'Recommendation',flabel:'recommendations',html:x=>x.rec?`<span class="tag">${esc(x.rec)}</span> ${esc(x.rec_version)}`:'',csv:x=>(x.rec+' '+x.rec_version).trim()},{key:'replacement',label:'Replacement / successor',cls:'wide'},{key:'projects',label:'Projects',cls:'num'}],
     detail: x => `<p>${hl(x.note)}</p>${x.rec_why ? `<p><b>Recommendation:</b> ${esc(x.rec_why)}</p>` : ''}${x.rec_risks ? `<p><b>Risks:</b> ${esc(x.rec_risks)}</p>` : ''}${x.licence_change ? `<p><b>Licence history:</b> ${esc(x.licence_change)}</p>` : ''}${x.licence ? `<p class="muted">Licence: ${esc(x.licence)}</p>` : ''}`}),
  'integrations-summary': h => { const c = D.tpCounts; h.innerHTML = `<div class="tiles">${[['Third-party / external services',c.external,'called over the internet: allow-lists, credentials, TLS'],['On-premises systems',c.onprem,'need VPN / Direct Connect, or must move too'],['Service SDKs',c.sdks,'client libraries for cloud / SaaS services'],['Identity providers & AD',c.identity,'sign-in and directory dependencies'],['Other integrations',c.other,'email, file transfer, SOAP, reporting, shares']].map(t=>`<div class="tile"><div class="l">${t[0]}</div><div class="v">${t[1]}</div><div class="s">${t[2]}</div></div>`).join('')}</div>`; },
  'thirdparty-table': h => DataTable(h, {name:'third-party-services', title:'Third-party / external services', rows: D.tp.external, filters:['used_by'], sort:'references', empty:'No external services found in code or configuration.',
     cols: [{key:'system',label:'Service / host'},{key:'protocols',label:'Protocol'},{key:'used_by',label:'Used by',flabel:'applications'},{key:'references',label:'Refs',cls:'num'},{key:'evidence',label:'Evidence'},{key:'needs',label:'Needed on AWS',cls:'wide'}]}),
  'onprem-table': h => DataTable(h, {name:'on-premises-systems', title:'On-premises / internal systems', rows: D.tp.onprem, filters:['used_by','protocols'], sort:'references', empty:'No on-premises host names or private IPs found.',
     cols: [{key:'system',label:'System'},{key:'protocols',label:'Protocol'},{key:'used_by',label:'Used by',flabel:'applications'},{key:'references',label:'Refs',cls:'num'},{key:'evidence',label:'Evidence',cls:'mid'},{key:'needs',label:'Needed on AWS',cls:'wide'}]}),
  'sdk-table': h => DataTable(h, {name:'service-sdks', title:'Service SDKs (packages that talk to external services)', rows: D.tp.sdks, filters:['service','status'], sort:'service', asc:true, empty:'No cloud / SaaS client libraries found.',
     cols: [{key:'service',label:'Service'},{key:'package',label:'Package'},{key:'versions',label:'Version(s)'},{key:'status',label:'Package group'},{key:'aws',label:'On AWS',cls:'wide'}]}),
  'effort-summary': h => { const e = D.effort;
     const pct = Math.round(100 - (e.lh / Math.max(1, lk(e.mh))) * 100);
     h.innerHTML = `<div class="kpis"><div class="kpi"><div class="l">Coding effort${e.ai ? ' (AI-assisted)' : ''}</div><div class="v">${e.lh} h</div><div class="s">≈ ${e.ld} person-days likely (P50) · P10–P90 ${hd(e.h, e.d)}${e.p80 ? ` · P80 ${e.p80} h` : ''}</div></div>
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
};

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
search.oninput = () => { clearTimeout(timer); timer = setTimeout(() => { Q = search.value.trim(); TABLES.forEach(t => { t.st.page = 0; t.render(); }); renderPlans();
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
