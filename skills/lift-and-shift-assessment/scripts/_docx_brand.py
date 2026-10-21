"""Branded .docx writer: the same calls as Docx (h1, h2, p, lead, bullets, table, banner), but the package is built from a company template.

The template is a finished .docx formatted by the company (cover page, welcome page, table of contents, header, footer, fonts, heading and table
look). Set its path in assessment.json as "docx_template". It is NOT part of this repository: it holds the company's and the client's logos and
fonts. Everything up to the heading "Table of Contents" is kept from the template (the cover gets the version, date and author); the table of
contents is generated here; the body is written in the template's look; header, footer, theme, fonts, numbering and media come from the template.

  - h1("N. Title")  -> a green "Section N" line, then the title in large type (new page); two entries in the table of contents
  - h2("N.M Title") -> sub-heading; one entry
  - table           -> green header row, white bold text, light grey cell borders
Page numbers in the table of contents are read from Word when Word is installed (Windows); without Word the numbers are left empty and the
document asks Word to update the table when it opens.
"""
import json
import os
import re
import subprocess
import tempfile
import zipfile
from xml.sax.saxutils import escape

import _docx
from _docx import Docx, _runs

GREEN = "88cb00"
RIGHT = '<w:ind w:right="1110"/>'
POPPINS_SB = '<w:rFonts w:ascii="Poppins SemiBold" w:cs="Poppins SemiBold" w:eastAsia="Poppins SemiBold" w:hAnsi="Poppins SemiBold"/>'
TOC_INDENT = {1: 0, 2: 360, 3: 720, 4: 1080}


def _top_level(body):
    return re.findall(r"<w:p[ >].*?</w:p>|<w:tbl>.*?</w:tbl>|<w:sectPr.*?</w:sectPr>", body, re.S)


class BrandedDocx(Docx):
    def __init__(self, template, prepared_by="", version="", date_text=""):
        super().__init__()
        self.template, self.prepared_by, self.version, self.date_text = template, prepared_by, version, date_text
        self.toc = []  # (level, text, bookmark)
        self._bm = 0
        self.pages = {}
        _docx.LINK_RID = "rIdWorkbook"

    # ---- body -----------------------------------------------------------------
    def _bookmark(self):
        self._bm += 1
        name = f"_toc_{self._bm:03d}"
        return name, f'<w:bookmarkStart w:id="{self._bm + 100}" w:name="{name}"/><w:bookmarkEnd w:id="{self._bm + 100}"/>'

    def title(self, text, sub=""):
        pass  # the cover page comes from the template

    def h1(self, text):
        m = re.match(r"(\d+)\.\s*(.*)$", text)
        num, title = (m.group(1), m.group(2)) if m else (None, text)
        if num:
            name, bm = self._bookmark()
            self.toc.append((1, f"Section {num}", name))
            self.body.append(f'<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:pageBreakBefore w:val="1"/>{RIGHT}</w:pPr>{bm}<w:r><w:t>Section {num}</w:t></w:r></w:p>')
        name, bm = self._bookmark()
        self.toc.append((2, title, name))
        pb = "" if num else "<w:pageBreakBefore/>"
        self.body.append(f'<w:p><w:pPr><w:pStyle w:val="Heading2"/>{pb}{RIGHT}<w:jc w:val="left"/></w:pPr>{bm}<w:r><w:t xml:space="preserve">{escape(title)}</w:t></w:r></w:p>')

    def h2(self, text):
        name, bm = self._bookmark()
        self.toc.append((3, text, name))
        self.body.append(f'<w:p><w:pPr><w:pStyle w:val="Heading3"/><w:spacing w:line="276" w:lineRule="auto"/>{RIGHT}<w:jc w:val="left"/></w:pPr>{bm}'
                         f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')

    def _ppr(self, after=240, keep=False):
        return f'<w:pPr>{"<w:keepNext/>" if keep else ""}<w:spacing w:after="{after}" w:line="276" w:lineRule="auto"/>{RIGHT}</w:pPr>'

    def p(self, text, bold=False):
        self.body.append(f"<w:p>{self._ppr(160, keep=bold)}{_runs(text, None, bold)}</w:p>")

    def lead(self, bold_text, text):
        self.body.append(f"<w:p>{self._ppr(160)}{_runs(bold_text + ' ', None, True)}{_runs(text)}</w:p>")

    def banner(self, text, fill=None):
        self.p(text, bold=True)

    def bullets(self, items):
        for t in items:
            self.body.append('<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="11"/></w:numPr><w:spacing w:line="276" w:lineRule="auto" w:after="80"/>'
                             f'<w:ind w:left="720" w:right="1110" w:hanging="360"/></w:pPr>{_runs(t)}</w:p>')
        self.body.append('<w:p><w:pPr><w:spacing w:after="60"/></w:pPr></w:p>')

    def table(self, rows, widths=None, size=18):
        n = len(rows[0])
        widths = widths or [100 // n] * n
        total = 9360
        w = [int(total * x / sum(widths)) for x in widths]
        border = "".join(f'<w:{s} w:color="d9d9d9" w:space="0" w:sz="8" w:val="single"/>' for s in ("top", "left", "bottom", "right"))
        mar = '<w:tcMar><w:top w:w="100" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="100" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tcMar>'
        trs = []
        for ri, row in enumerate(rows):
            tcs = []
            for ci, cell in enumerate(row):
                cell = "" if cell is None else str(cell)
                bold = cell.startswith("**")
                cell = cell[2:] if bold else cell
                head = ri == 0
                fill = f'<w:shd w:fill="{GREEN}" w:val="clear"/>' if head else '<w:shd w:fill="auto" w:val="clear"/>'
                jc = "center" if head or len(cell) <= 40 else "left"
                runs = _runs(cell, None if head else size, True if head else bold, "ffffff" if head else None)
                tcs.append(f'<w:tc><w:tcPr><w:tcW w:w="{w[ci]}" w:type="dxa"/><w:tcBorders>{border}</w:tcBorders>{fill}{mar}<w:vAlign w:val="center"/></w:tcPr>'
                           f'<w:p><w:pPr>{"<w:keepNext/>" if head else ""}<w:spacing w:line="276" w:lineRule="auto" w:after="0"/><w:jc w:val="{jc}"/></w:pPr>{runs}</w:p></w:tc>')
            trpr = '<w:trPr><w:cantSplit w:val="1"/><w:trHeight w:val="555" w:hRule="atLeast"/><w:tblHeader w:val="1"/></w:trPr>' if ri == 0 else '<w:trPr><w:cantSplit w:val="1"/></w:trPr>'
            trs.append(f"<w:tr>{trpr}{''.join(tcs)}</w:tr>")
        self.body.append('<w:tbl><w:tblPr><w:tblW w:w="9360" w:type="dxa"/><w:jc w:val="left"/><w:tblInd w:w="15" w:type="dxa"/><w:tblBorders>'
                         + "".join(f'<w:{s} w:color="cccccc" w:space="0" w:sz="8" w:val="single"/>' for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
                         + '</w:tblBorders><w:tblLayout w:type="fixed"/><w:tblLook w:val="0600"/></w:tblPr>'
                         + "<w:tblGrid>" + "".join('<w:gridCol w:w="%d"/>' % x for x in w) + "</w:tblGrid>" + "".join(trs) + "</w:tbl>")
        self.body.append('<w:p><w:pPr><w:spacing w:after="120"/></w:pPr></w:p>')

    # ---- package --------------------------------------------------------------
    def _toc_xml(self):
        out = []
        last = len(self.toc) - 1
        for i, (lvl, text, bm) in enumerate(self.toc):
            color = GREEN if lvl == 1 else "666666"
            begin = ('<w:r><w:fldChar w:fldCharType="begin"/><w:instrText xml:space="preserve"> TOC \\h \\u \\z \\t "Heading 1,1,Heading 2,2,Heading 3,3,Heading 4,4," </w:instrText>'
                     '<w:fldChar w:fldCharType="separate"/></w:r>') if i == 0 else ""
            end = '<w:r><w:fldChar w:fldCharType="end"/></w:r>' if i == last else ""
            page = self.pages.get(bm, "")
            out.append('<w:p><w:pPr><w:widowControl w:val="0"/><w:tabs><w:tab w:val="right" w:leader="none" w:pos="12000"/></w:tabs>'
                       f'<w:spacing w:before="60" w:line="240" w:lineRule="auto"/><w:ind w:left="{TOC_INDENT[lvl]}" w:right="1110" w:firstLine="0"/><w:jc w:val="left"/></w:pPr>'
                       f'{begin}<w:hyperlink w:anchor="{bm}"><w:r><w:rPr>{POPPINS_SB}<w:color w:val="{color}"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>'
                       f'<w:t xml:space="preserve">{escape(text)}</w:t><w:tab/><w:t xml:space="preserve">{page}</w:t></w:r></w:hyperlink>{end}</w:p>')
        return "".join(out)

    def _front(self, items):
        k = next(i for i, it in enumerate(items) if "Table of Contents" in it)
        front = "".join(items[:k + 1])
        if self.version:
            front, n = re.subn(r"Version: [^<]*", "Version: " + escape(self.version), front)
        if self.date_text:
            split = re.subn(r'(Date: </w:t></w:r><w:r[^>]*><w:rPr>.*?</w:rPr><w:t[^>]*>)[^<]*', lambda m: m.group(1) + escape(self.date_text), front, count=1, flags=re.S)
            front = split[0] if split[1] else re.sub(r"Date: [^<]+", "Date: " + escape(self.date_text), front)
        if self.prepared_by:  # the first text run after the template's "Prepared by" label holds the author's name
            front = re.sub(r"(Prepared by:?\s*</w:t>.*?<w:t[^>]*>)[^<]*", lambda m: m.group(1) + escape(self.prepared_by), front, count=1, flags=re.S)
        return front

    def _write(self, path, update_fields=False):
        tz = zipfile.ZipFile(self.template)
        doc = tz.read("word/document.xml").decode("utf-8")
        i = doc.index("<w:body>") + len("<w:body>")
        items = _top_level(doc[i:])
        sect = next(it for it in reversed(items) if it.startswith("<w:sectPr"))
        body = self._front(items) + self._toc_xml() + "".join(self.body) + sect
        document = doc[:i] + body + "</w:body></w:document>"
        rels = tz.read("word/_rels/document.xml.rels").decode("utf-8")
        if _docx.LINK_URL:
            rels = re.sub(r'(Id="rIdWorkbook"[^>]*Target=")[^"]*"', lambda m: m.group(1) + escape(_docx.LINK_URL, {'"': "&quot;"}) + '"', rels)
        settings = tz.read("word/settings.xml").decode("utf-8")
        if update_fields and "w:updateFields" not in settings:
            settings = settings.replace("<w:compat>", '<w:updateFields w:val="true"/><w:compat>', 1)  # schema order: updateFields comes just before compat
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for info in tz.infolist():
                if info.filename.endswith("/"):
                    continue
                data = tz.read(info.filename)
                if info.filename == "word/document.xml":
                    data = document.encode("utf-8")
                elif info.filename == "word/_rels/document.xml.rels":
                    data = rels.encode("utf-8")
                elif info.filename == "word/settings.xml":
                    data = settings.encode("utf-8")
                z.writestr(info.filename, data)

    def _word_pages(self, path):
        """{bookmark: page} read from Word (Windows with Word installed); {} when that is not available."""
        names = [bm for _l, _t, bm in self.toc]
        if os.name != "nt" or not names:
            return {}
        ps = ("$ErrorActionPreference='Stop';$w=New-Object -ComObject Word.Application;$w.Visible=$false;$w.DisplayAlerts=0;"
              "try{$d=$w.Documents.Open($args[0],$false,$true);$d.Repaginate();$d.Bookmarks.ShowHidden=$true;$o=@{};foreach($n in $args[1].Split(',')){if($d.Bookmarks.Exists($n)){$o[$n]=$d.Bookmarks.Item($n).Range.Information(3)}};"
              "$d.Close($false);$o|ConvertTo-Json -Compress}finally{$w.Quit()}")
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as f:
                f.write(ps)
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", f.name, os.path.abspath(path), ",".join(names)], capture_output=True, text=True, timeout=300)
            os.unlink(f.name)
            return {k: int(v) for k, v in json.loads(r.stdout.strip().splitlines()[-1]).items()}
        except Exception:
            return {}

    def _pdf_pages(self, path):
        """{bookmark: page} from Word's own PDF export of the first pass (the bookmark positions Word reports while hidden can be a page
        off). Each table-of-contents entry is looked up in the PDF in order, on or after the page of the previous one. {} when Word or
        pymupdf is not available."""
        if os.name != "nt" or not self.toc:
            return {}
        try:
            import pymupdf
        except ImportError:
            return {}
        pdf = os.path.splitext(os.path.abspath(path))[0] + ".toc-check.pdf"
        ps = ("$ErrorActionPreference='Stop';$w=New-Object -ComObject Word.Application;$w.Visible=$false;$w.DisplayAlerts=0;"
              "try{$d=$w.Documents.Open($args[0],$false,$true);$d.SaveAs2($args[1],17);$d.Close($false)}finally{$w.Quit()}")
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as f:
                f.write(ps)
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", f.name, os.path.abspath(path), pdf], capture_output=True, text=True, timeout=300)
            os.unlink(f.name)
            doc = pymupdf.open(pdf)
            norm = lambda t: re.sub(r"\s+", " ", t).strip()
            texts = [norm(p.get_text()) for p in doc]
            doc.close()
            os.unlink(pdf)
        except Exception:
            return {}
        start = next((i for i, t in enumerate(texts) if "Table of Contents" in t), 0) + 1
        out, cur = {}, start
        for _lvl, text, bm in self.toc:
            hit = next((i for i in range(cur, len(texts)) if norm(text) in texts[i]), None)
            if hit is None:
                return {}  # a heading could not be placed: let Word fill the table instead
            out[bm], cur = hit + 1, hit
        return out

    def save(self, path):
        self._write(path)  # first pass: Word must not refresh the table of contents while the page numbers are read from it
        pages = self._pdf_pages(path) or self._word_pages(path)
        if pages:
            self.pages = pages
            self._write(path)  # same layout (the table of contents has the same number of lines), now with the page numbers
        else:
            self._write(path, update_fields=True)  # no Word here: it fills in the table of contents when the document is opened
