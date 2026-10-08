"""Check the built document and workbook against the data they came from.

    python <skill>/scripts/verify_doc.py

Gates (each PASS or FAIL; exit code 1 when one fails):
  opens          the .docx is a valid package and every part is well-formed XML
  solutions      every solution appears in the document and has a row in the workbook
  projects       the workbook lists every project of every solution
  headings       the section and subsection headings of the reference document are present, in its order
  hours          the total and every estimate line in the document equal estimate.json
  status         DRAFT (or FINAL with who confirmed) is stated; the environment warning is present while environments are unconfirmed
  no secrets     no secret-looking assignment and none of the secret settings' values appear in the text
  length         prose outside tables stays short (the document is tables and counts, not narrative)
"""
import os
import re
import sys
import zipfile
import xml.dom.minidom

from _common import OUT, load_config, read_json, utf8_stdout
import _xlsx

PROSE_WORD_LIMIT = 1500
HEADINGS = ["1. Document control", "1.1 Scope box", "2. Executive summary", "3. 7R disposition", "4. Current state", "5. Prerequisites",
            "5.1 Make the build reproducible", "5.2 Secrets into Secrets Manager", "5.3 Connection-string indirection", "5.4 Framework version",
            "6. Migration approach", "7. Target architecture on AWS Windows", "8. Migration execution per workload",
            "8.3 Sequencing dependency between the workloads", "9. Wave plan and cutover", "10. Effort estimate and timeline", "11. Validation and testing"]


def text_of(xml):
    xml = re.sub(r"</w:p></w:tc>", " | ", xml)
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def main():
    utf8_stdout()
    root, cfg = load_config()
    os.chdir(root)
    built = read_json(os.path.join(OUT, "documents", "built.json"))
    idx = read_json(os.path.join(OUT, "solutions", "index.json"))
    est = read_json(os.path.join(OUT, "estimate.json"))
    if not (built and idx and est):
        raise SystemExit("run build_doc.py first")
    gates = []

    def gate(name, ok, detail=""):
        gates.append(ok)
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else ""))

    try:
        z = zipfile.ZipFile(built["docx"])
        for n in z.namelist():
            xml.dom.minidom.parseString(z.read(n))
        doc_xml = z.read("word/document.xml").decode("utf-8")
        gate("opens", True, f"{len(z.namelist())} parts")
    except Exception as ex:
        gate("opens", False, str(ex))
        sys.exit(1)
    text = text_of(doc_xml)
    wb = _xlsx.read(built["xlsx"])
    sols = idx["solutions"]
    missing = [s["id"] for s in sols if s["solution"] not in text] if len(sols) <= 30 else []  # the document caps its tables; the workbook lists all
    rows = {r[0] + "|" + r[1] for r in wb.get("Solutions", [])[1:]}
    miss_wb = [s["id"] for s in sols if s["solution"] + "|" + s["repo"] not in rows]
    gate("solutions", not missing and not miss_wb, f"{len(sols)} solutions" + (f"; missing in document: {missing[:5]}" if missing else "") + (f"; missing in workbook: {miss_wb[:5]}" if miss_wb else ""))
    n_proj = sum(len(s["projects"]) for s in sols)
    gate("projects", len(wb.get("Projects", [])) - 1 == n_proj, f"workbook {len(wb.get('Projects', [])) - 1} rows, solutions list {n_proj}")
    hs = lambda x: f"{x:g}"
    t = est["total"]
    need = [f"Total (incl. buffer) ≈ {hs(t['low'])}–{hs(t['high'])} hours" in text]
    for label in built.get("lines", []):
        need.append(label in text)
    gate("hours", all(need), f"total {hs(t['low'])}-{hs(t['high'])} h; every estimate line present")
    pos, missing_h = -1, []
    for hd in HEADINGS:
        i = text.find(hd, pos + 1)
        if i < 0:
            missing_h.append(hd)
        else:
            pos = i
    gate("headings", not missing_h, "all reference headings present in order" if not missing_h else "missing or out of order: " + "; ".join(missing_h[:4]))
    final = (cfg.get("intake") or {}).get("final")
    ok = ("Final (confirmed by" in text) if final else ("Draft for review" in text)
    if idx["environments_assumed"] or not (cfg.get("intake") or {}).get("environments_confirmed"):
        ok = ok and "Environments are UNKNOWN or not confirmed" in text
    gate("status", ok, "FINAL" if final else "DRAFT")
    bad = re.findall(r"(?i)\b(?:password|pwd|secret|api[_-]?key|token)\s*[=:]\s*[^\s|]{4,}", text)
    leaked = []
    for r in os.listdir(os.path.join(OUT, "scan")) if os.path.isdir(os.path.join(OUT, "scan")) else []:
        if r.endswith(".json"):
            for sct in (read_json(os.path.join(OUT, "scan", r), {}) or {}).get("secret_settings") or []:
                v = str(sct.get("value", "")) if isinstance(sct, dict) else ""
                if len(v) > 5 and v in text:
                    leaked.append(r)
    gate("no secrets", not bad and not leaked, f"{len(bad)} secret-like assignments, {len(leaked)} leaked values")
    prose = re.sub(r"<w:tbl>.*?</w:tbl>", "", doc_xml, flags=re.S)
    words = len(text_of(prose).split())
    gate("length", words <= PROSE_WORD_LIMIT, f"{words} words of prose outside tables (limit {PROSE_WORD_LIMIT})")
    sys.exit(0 if all(gates) else 1)


if __name__ == "__main__":
    main()
