"""Minimal .docx writer (standard library only): title, headings, paragraphs, bullets, notes, tables. Plain look, like the reference document
(black headings, light-grey table header, no colours, no footer).

    d = Docx()
    d.title("Title", "subtitle"); d.h1("1. Section"); d.h2("1.1 Sub"); d.p("text"); d.bullets(["a", "b"])
    d.banner("DRAFT ..."); d.table([header, *rows], widths_in_percent=[30, 20, ...])
    d.save("out.docx")

Opens in Word, and imports into Google Docs and LibreOffice. Cell values are plain strings; a string starting with '**' is bold.
"""
import zipfile
from xml.sax.saxutils import escape

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
FONT = "Arial"
HEAD_FILL = "EEF0F2"  # light grey table header, as in the reference


def _runs(text, size=None, bold=False, color=None):
    out = []
    for i, part in enumerate(str(text).split("\n")):
        rpr = ""
        if bold:
            rpr += "<w:b/>"
        if color:
            rpr += f'<w:color w:val="{color}"/>'
        if size:
            rpr += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
        br = "<w:br/>" if i else ""
        out.append(f'<w:r>{"<w:rPr>" + rpr + "</w:rPr>" if rpr else ""}{br}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return "".join(out)


class Docx:
    def __init__(self, footer=""):
        self.body = []

    def _para(self, text, style=None, size=None, bold=False, color=None, shade=None, ind=None, keep=False, after=None):
        ppr = ""
        if style:
            ppr += f'<w:pStyle w:val="{style}"/>'
        if keep:
            ppr += "<w:keepNext/>"
        if shade:
            ppr += f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>'
        if ind:
            ppr += f'<w:ind w:left="{ind[0]}" w:hanging="{ind[1]}"/>'
        if after is not None:
            ppr += f'<w:spacing w:after="{after}"/>'
        self.body.append(f'<w:p>{"<w:pPr>" + ppr + "</w:pPr>" if ppr else ""}{_runs(text, size, bold, color)}</w:p>')

    def title(self, text, sub=""):
        self._para(text, "Title")
        if sub:
            self._para(sub, "Subtitle")

    def h1(self, text):
        self._para(text, "Heading1", keep=True)

    def h2(self, text):
        self._para(text, "Heading2", keep=True)

    def p(self, text, bold=False):
        self._para(text, bold=bold)

    def lead(self, bold_text, text):
        """Paragraph that starts with a bold lead-in ('What Phase 1 achieves.')."""
        self.body.append(f'<w:p>{_runs(bold_text + " ", None, True)}{_runs(text)}</w:p>')

    def bullets(self, items):
        for t in items:
            self._para("•\t" + t, ind=(360, 360), after=40)

    def banner(self, text, fill=None):
        self._para(text, bold=True)

    def table(self, rows, widths=None, size=20):
        n = len(rows[0])
        widths = widths or [100 // n] * n
        total = 9360  # text width in twips for 1 inch margins on Letter
        grid = "".join(f'<w:gridCol w:w="{int(total * w / sum(widths))}"/>' for w in widths)
        trs = []
        for ri, row in enumerate(rows):
            tcs = []
            for ci, cell in enumerate(row):
                cell = "" if cell is None else str(cell)
                bold = cell.startswith("**")
                cell = cell[2:] if cell.startswith("**") else cell
                shade = f'<w:shd w:val="clear" w:color="auto" w:fill="{HEAD_FILL}"/>' if ri == 0 else ""
                tcs.append(f'<w:tc><w:tcPr><w:tcW w:w="{int(total * widths[ci] / sum(widths))}" w:type="dxa"/>{shade}</w:tcPr>'
                           f'<w:p><w:pPr>{"<w:keepNext/>" if ri == 0 else ""}<w:spacing w:after="0"/></w:pPr>{_runs(cell, size, bold)}</w:p></w:tc>')
            trs.append(f'<w:tr>{"<w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>" if ri == 0 else "<w:trPr><w:cantSplit/></w:trPr>"}{"".join(tcs)}</w:tr>')
        self.body.append(
            '<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>'
            + "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="D0D4D9"/>' for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
            + '</w:tblBorders><w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="60" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr>'
            + f"<w:tblGrid>{grid}</w:tblGrid>{''.join(trs)}</w:tbl>")
        self._para("", after=60)

    def save(self, path):
        sect = ('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>')
        document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}><w:body>{"".join(self.body)}{sect}</w:body></w:document>'
        style = lambda sid, name, size, bold, before=0, after=120: (
            f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
            f'<w:pPr><w:spacing w:before="{before}" w:after="{after}"/></w:pPr><w:rPr>{"<w:b/>" if bold else ""}'
            f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr></w:style>')
        styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {W}><w:docDefaults><w:rPrDefault><w:rPr>'
                  f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>'
                  '<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="324" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
                  '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
                  + style("Title", "Title", 40, False, 0, 120) + style("Subtitle", "Subtitle", 22, False, 0, 160)
                  + style("Heading1", "heading 1", 28, True, 240, 120) + style("Heading2", "heading 2", 24, True, 200, 100)
                  + "</w:styles>")
        ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
              '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
              '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        drels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/document.xml", document)
            z.writestr("word/styles.xml", styles)
            z.writestr("word/_rels/document.xml.rels", drels)
