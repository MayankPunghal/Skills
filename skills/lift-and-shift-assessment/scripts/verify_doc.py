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

from _common import skip_dir, OUT, load_config, read_json, utf8_stdout
import _xlsx

SECRET_PAIRS = [re.compile(r"(?i)\b(?:password|pwd)\s*=\s*([^;\"'<>\s&]{4,})"),
                re.compile(r"(?i)(?:key|name)\s*=\s*\"[^\"]*(?:password|passwd|secret|apikey|api_key|token|pwd|licen[sc]e)[^\"]*\"\s+value\s*=\s*\"([^\"]{4,})\"")]
SECRET_FILES = (".config", ".json", ".xml", ".settings", ".ini", ".yml", ".yaml", ".properties", ".pubxml")
PLACEHOLDER_VALUE = re.compile(r"^(\{.*\}|#\{.*\}#?|\$\(.*\)|%.*%|\*+|x+|your.*|changeme|password|<.*>)$", re.I)


def secret_values(cfg):
    """Credential values that the repositories hold in configuration files (read only, never printed): the document and workbook must not contain any."""
    found = set()
    skip = {d.lower() for d in cfg.get("exclude_dirs", [])} | {".git", "bin", "obj", "node_modules", "packages"}
    for root in cfg.get("estate_roots", []):
        for dp, dn, fs in os.walk(root):
            dn[:] = [d for d in dn if not skip_dir(dp, d, skip)]
            for f in fs:
                p = os.path.join(dp, f)
                if f.lower().endswith(SECRET_FILES) and os.path.getsize(p) < 1_500_000:
                    try:
                        body = open(p, encoding="utf-8-sig", errors="replace").read()
                    except OSError:
                        continue
                    for rx in SECRET_PAIRS:
                        found.update(v for v in rx.findall(body) if not PLACEHOLDER_VALUE.match(v) and len(v) >= 4 and re.search(r"[\d\W_]", v))  # a plain word is too likely to be a coincidence
    cores = {m.group(0) for v in found for m in [re.match(r"\w{4,}", v)] if m and re.search(r"\d", m.group(0))}  # a parser may drop trailing symbols
    return sorted(found | cores)


PROSE_WORD_LIMIT = 1900  # plus PROSE_PER_SOLUTION for each solution: the workload and tool lists grow with the estate. 1.1.0: 1800 -> 1900, the fixed sections alone (branch note, release process, client answers) came to about 1850 words, so a 1-2 solution estate failed with no padding at all
PROSE_PER_SOLUTION = 25
HEADINGS = ["1. Document control", "1.1 Scope box", "2. Executive summary", "3. 7R disposition", "4. Current state", "5. Prerequisites",
            "5.1 Make the build reproducible", "Secrets into Secrets Manager", "Internal addresses and connectivity", "Framework version",
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
            if n.endswith((".xml", ".rels")):  # a branded document also holds images and fonts
                xml.dom.minidom.parseString(z.read(n))
        doc_xml = z.read("word/document.xml").decode("utf-8")
        if "Table of Contents" in doc_xml and 'w:fldCharType="end"' in doc_xml:  # branded: the cover, welcome page and contents list are the template's, not our prose
            doc_xml = doc_xml.split('w:fldCharType="end"', 1)[1]
        gate("opens", True, f"{len(z.namelist())} parts")
    except Exception as ex:
        gate("opens", False, str(ex))
        sys.exit(1)
    text = text_of(doc_xml)
    text = re.sub(r"Section (\d+)\s+", r"\1. ", text)  # branded headings: a green "Section N" line above the title
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
    selected_work = set((cfg.get("intake") or {}).get("work_items") or [])
    for hd in HEADINGS:
        if hd.startswith("Secrets into") and "cicd_secrets" not in selected_work:
            continue  # the secrets section is written only when that work is in scope
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
    wb_text = "\n".join(str(c) for rows in wb.values() for r in rows for c in r)
    haystack = text + "\n" + wb_text
    leaked = [v for v in secret_values(cfg) if re.search(r"(?<![\w.-])" + re.escape(v) + r"(?![\w-])", haystack)]  # whole tokens only; the values are never printed, only counted
    gate("no secrets", not bad and not leaked, f"{len(bad)} secret-like assignments, {len(leaked)} leaked values")
    prose = re.sub(r"<w:tbl>.*?</w:tbl>", "", doc_xml, flags=re.S)
    words = len(text_of(prose).split())
    limit = PROSE_WORD_LIMIT + PROSE_PER_SOLUTION * len((read_json(os.path.join(OUT, "solutions", "index.json"), {}) or {}).get("solutions", []))
    gate("length", words <= limit, f"{words} words of prose outside tables (limit {limit})")
    sys.exit(0 if all(gates) else 1)


if __name__ == "__main__":
    main()
