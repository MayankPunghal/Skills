"""Build the interactive, tabbed HTML report: one self-contained file for PMs, BAs, architects and the delivery team.

    python <skill>/scripts/build_html_report.py [--layout PATH] [--out NAME]

Tabs grouped in a sidebar (Summary · Assessment · Plan · Reference): overview with KPIs and charts, applications & 7R,
effort & timeline (hours and person-days, AI-assisted vs manual), Linux readiness (scorecard + what breaks), .NET
modernization, packages (incompatible / deprecated / framework-specific / upgrade / licence / private / compatible),
third-party & integrations, data, security, hosting, delivery, all findings, plan, architecture map, risks & questions,
method, appendices. Global search filters every table and shows matches per tab; every table sorts, filters, expands and
downloads as CSV. Works offline (no external libraries). Layout and wording: references/html-layout.json.
Output: assessment/report/<Client>-AWS-Migration-Assessment.html
"""
import argparse
import base64
import datetime
import html
import json
import os
import re
from collections import Counter

from _common import OUT, SKILL_DIR, data, load_config, mark_step, read_json, slug, utf8_stdout, write_text
import _analysis as A
import _findings as F
import build_report as BR

SEVS = ["Blocker", "High", "Medium", "Low", "Info"]


# Small line icons (stroke = currentColor), so no Unicode glyph stands in for an icon.
ICON = {
    "copy": '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 5.5V3.5a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2"/></svg>',
    "menu": '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11"/></svg>',
    "theme": '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.5"/><path d="M8 2.5a5.5 5.5 0 0 0 0 11z" fill="currentColor"/></svg>',
    "print": '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 6V2.5h7V6M4.5 11.5h-2v-5h11v5h-2"/><rect x="4.5" y="9.5" width="7" height="4"/></svg>',
    "up": '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 13V3.5M4 7.5l4-4 4 4"/></svg>',
    "lock": '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="7" width="9" height="6.5" rx="1"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></svg>',
}

# IBM Plex Sans and Plex Mono (SIL Open Font License, templates_html/fonts/OFL.txt), embedded as data URIs so the
# single-file report looks the same offline on any machine. Missing files fall back to the system stack.
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates_html", "fonts")
LATIN = "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"
LATIN_EXT = "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF"


def font_faces():
    out = []
    for file, family, weight, rng in (("plex-sans-latin.woff2", "Plex Sans", "100 700", LATIN), ("plex-sans-latin-ext.woff2", "Plex Sans", "100 700", LATIN_EXT),
                                      ("plex-mono-latin-400.woff2", "Plex Mono", "400", LATIN), ("plex-mono-latin-600.woff2", "Plex Mono", "600", LATIN)):
        p = os.path.join(FONT_DIR, file)
        if os.path.exists(p):
            b64 = base64.b64encode(open(p, "rb").read()).decode("ascii")
            out.append(f'@font-face{{font-family:"{family}";src:url(data:font/woff2;base64,{b64}) format("woff2");font-weight:{weight};font-style:normal;font-display:swap;unicode-range:{rng}}}')
    return "\n".join(out)


# ------------------------------------------------------------------ minimal Markdown -> HTML (narratives and blocks)
def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"&lt;br\s*/?&gt;", "<br>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", t)
    t = re.sub(r"(?<![\w])_([^_\n]+)_(?![\w])", r"<em>\1</em>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    t = re.sub(r"\b(F-\d{3})\b", r'<a class="fref" href="#finding-\1">\1</a>', t)
    return t


def md_list(items):
    """Nested <ul>/<ol> from (indent, ordered, text) items: an item indented deeper than the first is a child of the one above."""
    if not items:
        return ""
    base = items[0][0]
    tag = "ol" if items[0][1] else "ul"
    parts, j = [], 0
    while j < len(items):
        k = j + 1
        while k < len(items) and items[k][0] > base:
            k += 1
        parts.append(f"<li>{inline(items[j][2])}{md_list(items[j + 1:k])}</li>")
        j = k
    return f"<{tag}>" + "".join(parts) + f"</{tag}>"


def md_to_html(md):
    lines = md.replace("\r", "").split("\n")
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            lang = ln.strip()[3:].strip()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            if lang != "mermaid":  # diagrams are drawn natively in the HTML report
                out.append(f'<figure class="code"><figcaption><span>{html.escape(lang or "text")}</span>'
                           f'<button type="button" class="btn" data-copy>{ICON["copy"]}<span>Copy</span></button></figcaption>'
                           f"<pre><code>{html.escape(chr(10).join(body), quote=False)}</code></pre></figure>")
            continue
        if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:\-|]+\|\s*$", lines[i + 1]):
            head = [c.strip() for c in ln.strip().strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = re.split(r"(?<!\\)\|", lines[i].strip().strip("|"))
                rows.append([c.strip().replace("\\|", "|") for c in cells])
                i += 1
            th = "".join(f"<th>{inline(h)}</th>" for h in head)
            trs = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<div class="tablewrap"><table class="md"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>')
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            lvl = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        if re.match(r"^\s*([-*]|\d+\.)\s+", ln):
            items = []  # (indent, ordered, text); indented items nest under the item above them
            while i < len(lines) and (re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]) or (lines[i].startswith("   ") and lines[i].strip() and items)):
                m2 = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", lines[i])
                if m2:
                    items.append((len(m2.group(1).expandtabs(4)), m2.group(2)[0].isdigit(), m2.group(3)))
                else:
                    items[-1] = (items[-1][0], items[-1][1], items[-1][2] + " " + lines[i].strip())
                i += 1
            out.append(md_list(items))
            continue
        if not ln.strip():
            i += 1
            continue
        para = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|\s*([-*]|\d+\.)\s|\s*\||```)", lines[i]):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{inline(' '.join(p.strip() for p in para))}</p>")
    return "\n".join(out)


# ------------------------------------------------------------------ data for the interactive components
def collect(c, cfg):
    cats = data("categories.json")
    seg_title = {s["id"]: s["title"] for s in cats.get("segments", [])}
    cat_seg = {x["id"]: x.get("segment", "") for x in c.cats}
    cat_title = {x["id"]: x["title"] for x in c.cats}
    appname = {a["id"]: a["name"] for a in c.cls["applications"]}
    HPD = c.est.get("hours_per_day", 8)
    findings = []
    for f in c.findings:
        findings.append({"ref": f["ref"], "severity": f["severity"], "confidence": f["confidence"], "category": cat_title.get(f["category"], f["category"]),
                         "segment": seg_title.get(cat_seg.get(f["category"]), ""), "seg": cat_seg.get(f["category"], ""),
                         "title": f["title"], "apps": ", ".join(appname.get(a, a) for a in f.get("apps", [])) or "(repository-wide)",
                         "project": f.get("project"), "repo": f["repo"], "count": f.get("occurrences", 1), "rule": f["rule"],
                         "evidence": [{"loc": F.evidence_ref(e), "text": e.get("text", "")} for e in f.get("evidence", [])[:25]],
                         "why": f.get("why", ""), "fix": f.get("fix", ""), "alt": f.get("alt", ""), "note": f.get("note", ""),
                         "review": (f.get("review") or {}).get("note", ""), "verdict": (f.get("review") or {}).get("verdict", ""),
                         "question": f.get("question") or "", "source": f.get("source", "scan")})
    apps = []
    for a in c.cls["applications"]:
        w = c.wp.get(a["id"], {})
        blockers = [f"{f['ref']} {f['title']}" for f in c.findings if a["id"] in f.get("apps", []) and f["severity"] in ("Blocker", "High")][:12]
        apps.append({"id": a["id"], "name": a["name"], "repo": a["repo"], "type": a["type"], "framework": ", ".join(a.get("target_frameworks", [])) or a.get("framework_family", ""),
                     "loc": a["loc"], "r7": a["r7"], "target": a["target"], "risk": a["risk"], "confidence": a.get("confidence", ""),
                     "h": w.get("total_hours", [0, 0]), "lh": w.get("likely_hours", 0), "d": w.get("total_days", [0, 0]), "ld": w.get("likely_days", 0),
                     "size": w.get("complexity", ""), "reviewed": "reviewed" if a.get("decision_source") == "review" else "draft",
                     "rationale": a.get("rationale", []), "options": a.get("options", []), "notes": a.get("notes", []),
                     "drivers": w.get("drivers", []), "blockers": blockers, "work": [x["item"] for x in w.get("conversion", [])]})
    packages = []
    for r in c.repos:
        for p in c.scan[r].get("packages", []):
            packages.append({"id": p["id"], "versions": ", ".join(p["versions"]), "latest": p.get("latest", "") or "", "group": A.package_group(p), "status": p["status"],
                             "severity": p["severity"], "advisories": p.get("vulnerable", "") or "", "vulnerable": "yes" if p.get("vulnerable") else "no",
                             "note": p.get("note", ""), "replacement": p.get("replacement", ""), "projects": len(p["projects"]), "repo": r,
                             "licence": ((p.get("nuget") or {}).get("licence") or ""),
                             "licence_change": (((p.get("nuget") or {}).get("licence_info") or {}).get("text") or ""),
                             "rec": (p.get("recommendation") or {}).get("action", "") + (" (optional)" if (p.get("recommendation") or {}).get("optional") else ""),
                             "rec_version": (p.get("recommendation") or {}).get("version") or "",
                             "rec_why": (p.get("recommendation") or {}).get("why", ""), "rec_risks": "; ".join((p.get("recommendation") or {}).get("risks", []))})
    deps, projects = [], []
    for r in c.repos:
        for e in c.scan[r].get("endpoints", []):
            kind = {"internal": "On-prem / internal", "external": "External service", "external-ip": "Public IP"}.get(e["kind"], e["kind"])
            deps.append({"kind": kind, "system": e["host"], "details": ", ".join(e["schemes"]), "count": e["occurrences"], "evidence": "; ".join(F.evidence_ref(x) for x in e["evidence"][:3]), "repo": r})
        for cs in c.scan[r].get("connection_strings", []):
            deps.append({"kind": "Database", "system": f"{cs.get('host') or '-'} / {cs.get('database') or '-'}", "details": f"{cs.get('provider') or 'SqlClient'}; auth {cs.get('auth')}" + ("; LocalDB (dev)" if cs.get("localdb") else ""),
                         "count": 1, "evidence": f"{cs['file']}:{cs['line']}", "repo": r})
        for p in (c.inv[r] or {}).get("projects", []):
            projects.append({"repo": r, "project": p["path"], "type": p["type"], "tfm": ", ".join(p.get("target_frameworks", [])), "format": "SDK" if p.get("sdk_style") else "legacy",
                             "packages": "packages.config" if p.get("packages_config") else "PackageReference", "language": ", ".join(p.get("languages", [])), "loc": p.get("loc_code", 0),
                             "support": "; ".join(f"{t['label']} ({t['status']})" for t in p.get("tfm_support", []))})
    winapi = [{"ref": f["ref"], "rule": f["rule"], "api": f["title"], "loc": e["loc"], "code": e["text"]} for f in findings
              if f["seg"] in ("linux", "modernization") for e in f["evidence"]]
    questions = [{"n": i, "area": a, "question": q, "raised": r} for i, (a, q, r) in enumerate(BR.open_questions(c), 1)]
    wps = []
    for w in sorted(c.est.get("work_packages", []), key=lambda w: -w["likely_days"]):
        b = w.get("breakdown_hours", {})
        wps.append({"name": w["name"], "kind": w["kind"], "r7": w.get("r7") or "-", "h": w.get("total_hours", [0, 0]), "lh": w.get("likely_hours", 0),
                    "d": w["total_days"], "ld": w["likely_days"], "mh": w.get("manual_hours", [0, 0]), "size": w["complexity"], "confidence": w["confidence"],
                    "code": b.get("code", [0, 0]), "drivers": "; ".join(w["drivers"][:4]),
                    "items": [x["item"] for x in w.get("conversion", [])], "findings": [f"{x['title']} ({x['hours'][0]}–{x['hours'][1]} h)" for x in w.get("findings", [])[:15]]})
    for d in c.est.get("databases", []):
        sel = d.get("selected", d["recommended"])
        if sel == "none":
            continue
        o = d["options"][sel]
        hrs = o.get("hours", [o["days"][0] * HPD, o["days"][1] * HPD])
        wps.append({"name": f"{d['repo']}: database code ({sel})", "kind": "database", "r7": "Replatform", "h": hrs, "lh": o.get("likely_hours", round(o["likely"] * HPD)),
                    "d": o["days"], "ld": o["likely"], "mh": o.get("manual_hours", hrs), "size": "-", "confidence": "-", "code": hrs,
                    "drivers": ", ".join(o.get("redesign", []) + o.get("rework", [])) or "-", "items": [f"Convert {', '.join(d['databases'])} code to {sel}"], "findings": []})
    t = c.est.get("totals", {})
    loc = sum((c.inv[r] or {}).get("totals", {}).get("loc", 0) for r in c.repos)
    sev = Counter(f["severity"] for f in findings)
    lr = A.linux_readiness(c)
    lvl = Counter(r["level"] for r in lr)
    td = t.get("total_days", [0, 0])
    kpis = [("Applications", str(len(apps)), f"{len(c.repos)} repositories · {loc:,} lines"),
            ("Linux-ready now / after porting", f"{lvl['ready']} / {lvl['port']}", f"{lvl['blocked']} blocked · {lvl['windows']} desktop · {lvl['na']} retiring"),
            ("Findings", str(len(findings)), " · ".join(f"{k} {sev[k]}" for k in ("Blocker", "High") if sev[k]) or "no blockers"),
            ("Effort", f"{t.get('likely_hours', '-')} h", f"≈ {t.get('likely_days', '-')} person-days likely (P50) · P10–P90 {td[0]:g}–{td[1]:g} d · P80 {t.get('p80_hours', '-')} h"),
            ("Duration", f"~{t.get('duration_weeks', '-')} weeks", f"P50 · ~{t.get('duration_weeks_p80', '-')} weeks at P80 · team of {c.est.get('engineers', '-')} engineers"),
            ("Target", BR.pretty_tfm(cfg.get("target_dotnet", "net10.0")), "Linux on AWS · LTS to Nov 2028")]
    segs = [{"id": s["id"], "title": s["title"], **{k: sum(1 for f in findings if f["seg"] == s["id"] and f["severity"] == k) for k in SEVS}} for s in cats.get("segments", [])]
    catrows = [{"title": x["title"], "scanned": x["scanned"], **{s: sum(1 for f in findings if f["category"] == x["title"] and f["severity"] == s) for s in SEVS}} for x in c.cats]
    tp = A.third_party(c)
    effort = {"h": t.get("total_hours", [0, 0]), "lh": t.get("likely_hours", 0), "d": td, "ld": t.get("likely_days", 0),
              "mh": t.get("manual_equivalent_hours", [0, 0]), "md": t.get("manual_equivalent_days", [0, 0]), "weeks": t.get("duration_weeks", 0),
              "engineers": c.est.get("engineers"), "ai": c.est.get("ai_assisted", False), "ai_factor": c.est.get("ai_code_factor", [1, 1]),
              "split": {"code": [round(sum(w["code"][i] for w in wps)) for i in (0, 1)]},
              "scenario": c.est.get("scenario", {}), "factors": c.est.get("ai_factors", {}), "mlh": t.get("manual_likely_hours", 0), "kloc": t.get("kloc", 0), "hpk": t.get("likely_hours_per_kloc", 0),
              "p80": t.get("p80_hours", 0), "bounds": t.get("bounds_hours", [0, 0])}
    lbuild = []
    for r in c.repos:
        lb = read_json(os.path.join(OUT, "scan", f"{r}.linux-build.json")) or {}
        lbuild += [dict(p, repo=r, status=A.BUILD_LABEL.get(p["status"], p["status"])) for p in lb.get("projects", [])]
    return {"findings": findings, "apps": apps, "packages": packages, "pgroups": [{"group": g, "desc": d} for g, d in A.PACKAGE_GROUPS],
            "deps": deps, "projects": projects, "winapi": winapi, "questions": questions, "wps": wps, "timeline": c.est.get("timeline", []), "kpis": kpis,
            "segs": segs, "cats": catrows, "r7": dict(Counter(a["r7"] for a in apps)), "sev": {s: sev[s] for s in SEVS}, "linux": lr,
            "linuxIssues": A.linux_issue_types(c), "tp": {k: v for k, v in tp.items() if k in ("external", "onprem", "sdks")},
            "tpCounts": {"external": len(tp["external"]), "onprem": len(tp["onprem"]), "sdks": len({x["service"] for x in tp["sdks"]}),
                         "identity": len(tp["identity"]), "other": len(tp["other"])},
            "linuxBuild": lbuild, "map": A.architecture_map(c), "effort": effort}


# blocks that need a heading on their card (the Markdown report has its own section headings)
BLOCK_TITLES = {"sprints": "Coding sprint plan", "multipliers": "How the hours are built", "assumptions": "Estimate assumptions",
                "methodology": "How the estimate was calculated",
                "optional": "Optional modernizations"}


def component(name, c):
    if name.startswith("narrative:"):
        n = name.split(":", 1)[1]
        txt = BR.narrative(n)
        if txt.startswith("_Narrative"):
            return f'<div class="callout warn">Narrative <code>{n}</code> not written yet.</div>'
        return f'<div class="card prose">{md_to_html(txt)}</div>'
    if name.startswith("block:"):
        key = name.split(":", 1)[1]
        fn = BR.BLOCKS.get(key)
        title = BLOCK_TITLES.get(key)
        head = f"<h3>{html.escape(title)}</h3>" if title else ""
        return f'<div class="card prose">{head}{md_to_html(fn(c))}</div>' if fn else ""
    return f'<div class="component" data-component="{html.escape(name)}"></div>'


CSS = (open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates_html", "report.css"), encoding="utf-8").read()
       if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates_html", "report.css")) else "")
JS = (open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates_html", "report.js"), encoding="utf-8").read()
      if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates_html", "report.js")) else "")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", default=os.path.join(SKILL_DIR, "references", "html-layout.json"))
    ap.add_argument("--out")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    layout = json.load(open(a.layout, encoding="utf-8"))
    c = BR.Ctx(root, cfg)
    d = collect(c, cfg)
    client = cfg.get("client") or "Client"
    brand = layout.get("brand", {})
    company = brand.get("company") or cfg.get("prepared_by", "")
    groups = [dict(g, tabs=list(g["tabs"])) for g in layout["groups"]]
    placed = {i.split(":", 1)[1] for g in groups for t in g["tabs"] for i in t["items"] if i.startswith("narrative:")}
    ndir = os.path.join(OUT, "narrative")
    extra = sorted(os.path.splitext(f)[0] for f in os.listdir(ndir) if f.endswith(".md") and os.path.splitext(f)[0] not in placed) if os.path.isdir(ndir) else []
    if extra:
        groups[-1]["tabs"].append({"id": "notes", "title": "Additional notes", "intro": "", "items": [f"narrative:{n}" for n in extra]})
    nav, body = [], []
    for g in groups:
        nav.append(f'<div class="grp">{html.escape(g["title"])}</div>')
        for t in g["tabs"]:
            nav.append(f'<a href="#{t["id"]}" data-tab="{t["id"]}"><span>{html.escape(t["title"])}</span><span class="badge"></span></a>')
            inner = "\n".join(component(i, c) for i in t["items"])
            cover, h2cls = "", ""
            if t["id"] == "overview":  # the report title leads the first tab; its "Overview" heading stays for screen readers only
                today = datetime.date.today()
                note = brand.get("confidential_note", "").replace("{client}", client)
                cover = (f'<div class="cover"><h1>{html.escape(cfg.get("engagement", "AWS Migration & Modernization Assessment"))}</h1>'
                         f'<div class="meta">Prepared for <b>{html.escape(client)}</b>{" by <b>" + html.escape(company) + "</b>" if company else ""} · {today.day} {today:%B %Y} · '
                         f'target {html.escape(BR.pretty_tfm(cfg.get("target_dotnet", "net10.0")))} on AWS</div>'
                         + (f'<div class="conf">{ICON["lock"]}<span>{html.escape(note)}</span></div>' if note else "") + "</div>")
                h2cls = ' class="sr"'
            body.append(f'<section class="tab" id="tab-{t["id"]}">{cover}<h2{h2cls}>{html.escape(t["title"])}</h2>' + (f'<p class="intro">{html.escape(t.get("intro", ""))}</p>' if t.get("intro") else "") + inner + "</section>")
    css = font_faces() + "\n" + CSS.replace("ACCENTDARK", brand.get("accent_dark", "#5ccfcf")).replace("ACCENT", brand.get("accent", "#0b6e74"))
    title = f"{client} — {cfg.get('engagement', 'AWS Migration & Modernization Assessment')}"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light dark">
<title>{html.escape(client)} AWS Assessment</title><style>{css}</style></head>
<body><a class="skip" href="#main">Skip to the report</a><header class="top"><button id="menu" class="icon" title="Sections" aria-label="Open the section menu" aria-expanded="false">{ICON["menu"]}</button><span class="title">{html.escape(title)}</span><input id="q" type="search" placeholder="Search applications, findings, files, packages, hosts…   /" aria-label="Search the whole report (shortcut: /)">
<button id="theme" class="icon" title="Light or dark theme" aria-label="Switch between light and dark">{ICON["theme"]}</button><button class="print" onclick="window.print()" title="Print or save as PDF (prints every tab)">{ICON["print"]}<span>Print</span></button></header>
<div class="layout"><nav class="side" aria-label="Report sections">{''.join(nav)}</nav><main id="main" tabindex="-1">{''.join(body)}</main></div><button id="totop" type="button">{ICON["up"]}<span>Top</span></button>
<script type="application/json" id="data">{json.dumps(d, ensure_ascii=False).replace("</", "<\\/")}</script>
<script>window.GLOSSARY = {json.dumps(layout.get("glossary", []), ensure_ascii=False).replace("</", "<\\/")};</script>
<script>{JS}</script></body></html>"""
    name = a.out or f"{slug(client).title().replace('-', '')}-AWS-Migration-Assessment.html"
    path = os.path.join(OUT, "report", name)
    page = BR.tags(page)  # {{f:RULE}} / {{v:path}} tags anywhere (narratives, decisions, review notes)
    write_text(path, page)
    mark_step(root, "html-report")
    print(f"html report: {path} ({len(page) // 1024} KB; {sum(len(g['tabs']) for g in groups)} tabs, {len(d['findings'])} findings, {len(d['apps'])} applications, {len(d['packages'])} packages)")


if __name__ == "__main__":
    main()
