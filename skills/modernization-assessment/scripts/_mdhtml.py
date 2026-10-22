"""Markdown -> self-contained HTML for the generated Markdown outputs (no third-party packages).

Every script that writes a .md deliverable also writes the .html twin with write_pair(). Covers what the generators emit:
headings, paragraphs, bullet / numbered lists (nested by indent), pipe tables, fenced code, inline code, bold, italic and
links. Offline page, light and dark theme, printable, sortable tables (click a header). brand=True adds the company look of the
branded .docx (green table headers, green rules); build_doc.py's template decides it (assessment.json -> docx_template set).
"""
import html
import os
import re

CSS = """
:root{--bg:#fff;--fg:#1d2329;--muted:#5b6670;--line:#dfe3e7;--head:#f4f6f8;--accent:#0b6e74;--code:#f2f4f6}
@media (prefers-color-scheme:dark){:root{--bg:#14181c;--fg:#e4e8ec;--muted:#9aa5ae;--line:#2c343b;--head:#1c2227;--accent:#5ccfcf;--code:#1f262c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 64px}h1{font-size:1.7rem;margin:.2em 0 .6em}h2{font-size:1.3rem;margin:1.8em 0 .5em;
border-bottom:1px solid var(--line);padding-bottom:.25em}h3{font-size:1.08rem;margin:1.4em 0 .4em}a{color:var(--accent)}
code{background:var(--code);padding:.08em .35em;border-radius:4px;font:.88em ui-monospace,SFMono-Regular,Consolas,monospace}
pre{background:var(--code);padding:12px;border-radius:6px;overflow:auto}pre code{background:none;padding:0}
.tw{overflow-x:auto;margin:.8em 0}table{border-collapse:collapse;width:100%;font-size:.92em}th,td{border:1px solid var(--line);padding:6px 8px;
text-align:left;vertical-align:top}th{background:var(--head);cursor:pointer;position:sticky;top:0}tr:nth-child(even) td{background:color-mix(in srgb,var(--head) 45%,transparent)}
.meta{color:var(--muted);font-size:.85em;margin-bottom:1.2em}@media print{th{position:static}a{color:inherit}}
"""
JS = """document.querySelectorAll('th').forEach(function(th){th.addEventListener('click',function(){var t=th.closest('table'),i=[].indexOf.call(th.parentNode.children,th),
b=t.tBodies[0],r=[].slice.call(b.rows),d=th.dataset.d==='1'?-1:1;th.dataset.d=d===1?'1':'0';r.sort(function(x,y){var a=x.cells[i].innerText,c=y.cells[i].innerText,
n=parseFloat(a.replace(/[^0-9.\\-]/g,'')),m=parseFloat(c.replace(/[^0-9.\\-]/g,''));return (!isNaN(n)&&!isNaN(m)?n-m:a.localeCompare(c))*d});r.forEach(function(e){b.appendChild(e)})})})"""


def inline(t):
    parts = re.split(r"(`[^`]+`)", t)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append("<code>" + html.escape(p[1:-1]) + "</code>")
            continue
        s = html.escape(p, quote=False)
        s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
        s = re.sub(r"(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])", r"<i>\1</i>", s)
        out.append(s)
    return "".join(out)


def _cells(row):
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)]


def convert(md):
    """Markdown text -> HTML body fragment."""
    lines = md.replace("\r\n", "\n").split("\n")
    out, i, para, stack = [], 0, [], []

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    def close_lists(level=0):
        while len(stack) > level:
            out.append(f"</li></{stack.pop()}>")

    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            flush(), close_lists()
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            flush(), close_lists()
            n = len(m.group(1))
            slug = re.sub(r"[^\w]+", "-", m.group(2).lower()).strip("-")
            out.append(f'<h{n} id="{slug}">{inline(m.group(2))}</h{n}>')
            i += 1
            continue
        if ln.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush(), close_lists()
            head = _cells(ln)
            rows = []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            out.append('<div class="tw"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table></div>")
            continue
        m = re.match(r"^(\s*)([-*]|\d+[.)])\s+(.*)$", ln)
        if m:
            flush()
            level = len(m.group(1).replace("\t", "    ")) // 2 + 1
            tag = "ol" if m.group(2)[0].isdigit() else "ul"
            if len(stack) < level:
                while len(stack) < level:
                    out.append(f"<{tag}><li>")
                    stack.append(tag)
            else:
                close_lists(level)
                out.append("</li><li>")
            out.append(inline(m.group(3)))
            i += 1
            continue
        if not ln.strip():
            flush()
            if not (i + 1 < len(lines) and re.match(r"^\s*([-*]|\d+[.)])\s+", lines[i + 1])):
                close_lists()
            i += 1
            continue
        if stack and ln.startswith("  "):
            out.append(" " + inline(ln.strip()))
            i += 1
            continue
        close_lists()
        para.append(ln.strip())
        i += 1
    flush(), close_lists()
    return "\n".join(out)


BRAND_CSS = """
:root{--accent:#4f7a00}@media (prefers-color-scheme:dark){:root{--accent:#a6e22e}}
th{background:#88cb00;color:#fff}h2{border-bottom:2px solid #88cb00}h1{border-left:6px solid #88cb00;padding-left:10px}
"""


def page(md, title=None, brand=False):
    m = re.search(r"(?m)^#\s+(.+)$", md)
    title = title or (re.sub(r"[`*_]", "", m.group(1)) if m else "Report")
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta name="color-scheme" content="light dark"><title>{html.escape(title)}</title><style>{CSS}{BRAND_CSS if brand else ""}</style></head>'
            f"<body><main>{convert(md)}</main><script>{JS}</script></body></html>\n")


def write_pair(md_path, md, title=None, brand=False):
    """Write md_path and the .html next to it; returns the html path."""
    os.makedirs(os.path.dirname(os.path.abspath(md_path)), exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    hp = os.path.splitext(md_path)[0] + ".html"
    with open(hp, "w", encoding="utf-8") as fh:
        fh.write(page(md, title, brand))
    return hp


def main():
    import sys
    args = [a for a in sys.argv[1:] if a != "--brand"]
    for p in args:
        md = open(p, encoding="utf-8").read()
        hp = os.path.splitext(p)[0] + ".html"
        open(hp, "w", encoding="utf-8").write(page(md, brand="--brand" in sys.argv))
        print(hp)


if __name__ == "__main__":
    main()
