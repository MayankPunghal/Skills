"""Turn a sample assessment report into a compact outline for calibration (token economy: read the outline, not the file).

    python <skill>/scripts/extract_sample.py calibration/samples/<file> [more files]

Supports .docx, .pptx, .xlsx, .md, .html/.htm, .txt (standard library only). For .pdf, read the PDF directly with the
Read tool (pages 1-20 at a time) and write the outline by hand in the same format.
Writes calibration/samples/<name>.outline.md next to the sample:
  - headings tree with word counts per section
  - every table: caption/heading above it, column headers, row count, first two rows (to see what is captured per item)
  - assessment vocabulary detected (7R terms, severity/rating scales, effort units, cost/licensing terms, AWS services)
The outline is the input to calibration/gap-analysis.md (references/calibration.md).
"""
import html
import os
import re
import sys
import zipfile
from collections import Counter

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
VOCAB = {
    "7R / strategy": r"\b(retire|retain|rehost|relocate|repurchase|replatform|refactor|re-architect|lift[- ]and[- ]shift)\b",
    "ratings": r"\b(blocker|critical|high|medium|low|severity|priority|likelihood|impact|confidence|RAG|red|amber|green)\b",
    "effort": r"\b(person[- ]days?|man[- ]days?|story points?|hours|weeks|sprints?|FTEs?|t-shirt|S/M/L|XL)\b",
    "cost": r"\b(TCO|licen[cs]e|licen[cs]ing|BYOL|license[- ]included|OLA|MAP|savings|cost|pricing|ROI|\$|USD|INR|EUR)\b",
    "aws": r"\b(EC2|ECS|EKS|Fargate|Lambda|RDS|Aurora|Babelfish|S3|EFS|FSx|SQS|SNS|ElastiCache|CloudWatch|Secrets Manager|Transform|MGN|DMS|Landing Zone|Control Tower)\b",
    "dotnet": r"\b(\.NET (Framework|Core|\d+)|ASP\.NET|Web Forms|WCF|WPF|WinForms|Entity Framework|EF Core|IIS|System\.Web|NuGet)\b",
}


def text_of(el):
    return "".join(t.text or "" for t in el.iter(W + "t"))


def docx(path):
    import xml.etree.ElementTree as ET
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    items = []
    for el in body:
        if el.tag == W + "p":
            style = el.find(f"{W}pPr/{W}pStyle")
            sv = style.get(W + "val") if style is not None else ""
            m = re.match(r"(?i)heading\s*(\d)|title", sv or "")
            t = text_of(el).strip()
            if not t:
                continue
            if m:
                items.append(("h", int(m.group(1) or 1), t))
            else:
                items.append(("p", 0, t))
        elif el.tag == W + "tbl":
            rows = [[text_of(c).strip() for c in r.iter(W + "tc")] for r in el.iter(W + "tr")]
            items.append(("t", 0, rows))
    return items


def pptx(path):
    import xml.etree.ElementTree as ET
    z = zipfile.ZipFile(path)
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[0]))
    items = []
    for i, n in enumerate(slides, 1):
        root = ET.fromstring(z.read(n))
        paras = ["".join(t.text or "" for t in p.iter(A + "t")).strip() for p in root.iter(A + "p")]
        paras = [p for p in paras if p]
        items.append(("h", 2, f"Slide {i}: {paras[0] if paras else ''}"))
        for p in paras[1:]:
            items.append(("p", 0, p))
        for tbl in root.iter(A + "tbl"):
            rows = [["".join(t.text or "" for t in c.iter(A + "t")).strip() for c in r.iter(A + "tc")] for r in tbl.iter(A + "tr")]
            items.append(("t", 0, rows))
    return items


def xlsx(path):
    import xml.etree.ElementTree as ET
    z = zipfile.ZipFile(path)
    S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = ["".join(t.text or "" for t in si.iter(S + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(S + "si")]
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    names = [s.get("name") for s in wb.iter(S + "sheet")]
    items = []
    for i, nm in enumerate(names, 1):
        p = f"xl/worksheets/sheet{i}.xml"
        if p not in z.namelist():
            continue
        rows = []
        for r in ET.fromstring(z.read(p)).iter(S + "row"):
            vals = []
            for c in r.iter(S + "c"):
                v = c.find(S + "v")
                t = c.find(f"{S}is/{S}t")
                val = (t.text if t is not None else (v.text if v is not None else "")) or ""
                if c.get("t") == "s" and val.isdigit() and int(val) < len(shared):
                    val = shared[int(val)]
                vals.append(val)
            rows.append(vals)
        items.append(("h", 2, f"Sheet: {nm}"))
        items.append(("t", 0, rows))
    return items


def md_or_html(path):
    raw = open(path, encoding="utf-8", errors="ignore").read()
    items = []
    if path.lower().endswith((".html", ".htm")):
        raw = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
        for m in re.finditer(r"(?is)<h([1-6])[^>]*>(.*?)</h\1>|<table.*?</table>|<p[^>]*>(.*?)</p>", raw):
            if m.group(1):
                items.append(("h", int(m.group(1)), html.unescape(re.sub("<[^>]+>", "", m.group(2))).strip()))
            elif m.group(0).lower().startswith("<table"):
                rows = [[html.unescape(re.sub("<[^>]+>", "", c)).strip() for c in re.findall(r"(?is)<t[hd][^>]*>(.*?)</t[hd]>", r)] for r in re.findall(r"(?is)<tr.*?</tr>", m.group(0))]
                items.append(("t", 0, rows))
            else:
                t = html.unescape(re.sub("<[^>]+>", "", m.group(3) or "")).strip()
                if t:
                    items.append(("p", 0, t))
        return items
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"^(#{1,6})\s+(.*)", ln)
        if m:
            items.append(("h", len(m.group(1)), m.group(2).strip()))
        elif ln.strip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\s*\|[\s:\-|]+\|\s*$", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            items.append(("t", 0, rows))
            continue
        elif ln.strip():
            items.append(("p", 0, ln.strip()))
        i += 1
    return items


def outline(path):
    ext = os.path.splitext(path)[1].lower()
    items = {"docx": docx, "pptx": pptx, "xlsx": xlsx}.get(ext.lstrip("."), md_or_html)(path)
    out = [f"# Outline of {os.path.basename(path)}", "", "Generated by extract_sample.py. Use with calibration/gap-analysis.md.", "", "## Structure", ""]
    words, cur = Counter(), "(start)"
    full = []
    last_heading = "(start)"
    for kind, lvl, val in items:
        if kind == "h":
            cur = last_heading = val
            out.append(f"{'  ' * (lvl - 1)}- **{val}**")
        elif kind == "p":
            words[cur] += len(val.split())
            full.append(val)
        else:
            rows = [r for r in val if any(x.strip() for x in r)]
            if not rows:
                continue
            full.append(" ".join(" ".join(r) for r in rows))
            hdr = " | ".join(rows[0])[:300]
            ex = "; ".join(" | ".join(r)[:160] for r in rows[1:3])
            out.append(f"{'  ' * 2}- table under '{last_heading}': {len(rows) - 1} rows; columns: {hdr}" + (f"; e.g. {ex}" if ex else ""))
    out += ["", "## Words per section", ""] + [f"- {k}: {v}" for k, v in words.most_common()]
    alltext = " ".join(full + [v for k, _, v in items if k == "h"])
    out += ["", "## Vocabulary detected", ""]
    for name, rx in VOCAB.items():
        hits = Counter(m.group(0).lower() for m in re.finditer(rx, alltext, re.I))
        out.append(f"- {name}: " + (", ".join(f"{k} ({v})" for k, v in hits.most_common(15)) or "none"))
    dst = os.path.splitext(path)[0] + ".outline.md"
    open(dst, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print(f"{path} -> {dst} ({len(items)} elements)")


def main():
    for s in (sys.stdout,):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in sys.argv[1:]:
        if p.lower().endswith(".pdf"):
            print(f"{p}: PDF - read it with the Read tool (pages 1-20 per call) and write {os.path.splitext(p)[0]}.outline.md in the same format.")
            continue
        outline(p)


if __name__ == "__main__":
    main()
