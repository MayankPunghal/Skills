"""Minimal .xlsx reader and writer (standard library only): several sheets, bold frozen header row, auto-filter, column widths.

read(path)  -> {sheet name: [row, ...]} with every row a list of strings (empty string for blank cells), header included.
write(path, sheets)  sheets = [(name, rows, widths, wrap_cols), ...]; rows[0] is the header. `auto(name, rows)` builds one with sensible widths.
update(path, new_sheets)  replace or add the named sheets in an existing workbook and keep every other sheet as it was (values and merged cells).
"""
import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _colnum(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def read(path, styles=False, typed=False):
    """typed=True keeps numbers as int/float and booleans as bool (used when an existing sheet is written back); otherwise every value is a string."""
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sh in wb.find("m:sheets", NS):
        target = rels[sh.get(REL)].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        rows = []
        for r in ET.fromstring(z.read(target)).iter("{%s}row" % NS["m"]):
            while r.get("r", "").isdigit() and len(rows) < int(r.get("r")) - 1:
                rows.append([])  # rows missing from the file are blank rows: keep the positions
            cells = {}
            for c in r.findall("m:c", NS):
                v, is_ = c.find("m:v", NS), c.find("m:is", NS)
                if c.get("t") == "s" and v is not None:
                    val = shared[int(v.text)]
                elif is_ is not None:
                    val = "".join(x.text or "" for x in is_.iter("{%s}t" % NS["m"]))
                else:
                    val = v.text if v is not None and v.text is not None else ""
                    if typed and val != "" and c.get("t") in (None, "n"):
                        try:
                            val = int(val) if re.fullmatch(r"-?\d+", val) else float(val)
                        except ValueError:
                            pass
                    elif typed and c.get("t") == "b":
                        val = val == "1"
                if styles and c.get("s") and c.get("s").isdigit() and int(c.get("s")) in _NAME_BY_ID and val != "":
                    val = (val, _NAME_BY_ID[int(c.get("s"))])  # keep the colour of cells this writer coloured
                cells[_colnum(re.match(r"[A-Z]+", c.get("r")).group())] = val
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
        out[sh.get("name")] = rows
    return out


def read_merges(path):
    """{sheet name: ["A2:A9", ...]}: the merged ranges of every sheet (so a sheet can be written back with its merges)."""
    z = zipfile.ZipFile(path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sh in wb.find("m:sheets", NS):
        target = rels[sh.get(REL)].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        out[sh.get("name")] = [m.get("ref") for m in ET.fromstring(z.read(target)).iter("{%s}mergeCell" % NS["m"])]
    return out


def _cell(ref, v, style):
    if isinstance(v, tuple):  # (value, "red" | "amber" | "green" | "grey" | "bold" | "blue"): a coloured cell
        v, name = v
        style = STYLE_IDS.get(name, style)
    st = f' s="{style}"' if style else ""
    if v is None or v == "":
        return f'<c r="{ref}"{st}/>'
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"{st}><v>{1 if v else 0}</v></c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"{st}><v>{v}</v></c>'
    t = escape(_BAD.sub("", str(v)))[:32000]
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{t}</t></is></c>'


def _sheet(rows, widths, wrap_cols, merges=None):
    ncols = max((len(r) for r in rows), default=1)
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    out = []
    for ri, row in enumerate(rows, 1):
        cells = "".join(_cell(f"{_col(ci)}{ri}", v, 1 if ri == 1 else (2 if ci in wrap_cols else 0)) for ci, v in enumerate(row))
        out.append(f'<row r="{ri}">{cells}</row>')
    last = f"{_col(max(ncols - 1, 0))}{max(len(rows), 1)}"
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<cols>{cols}</cols><sheetData>{"".join(out)}</sheetData>'
            + (f'<autoFilter ref="A1:{last}"/>' if len(rows) > 1 and not merges else "")  # a filter and merged cells do not mix: filtering would hide half a merged block
            + (f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges) + '</mergeCells>' if merges else "") + '</worksheet>')


STYLE_IDS = {"red": 3, "amber": 4, "green": 5, "grey": 6, "bold": 7, "blue": 8, "grp1": 9, "grp2": 10, "grp3": 11, "grp4": 12,
             "tick_blue": 13, "tick_amber": 14, "tick_green": 15, "tick_red": 16, "tick_grey": 17}  # grp*: bold, centred, one fill per group band; tick_*: centred, filled
_NAME_BY_ID = {v: k for k, v in STYLE_IDS.items()}
STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="4"><font><sz val="10"/><name val="Calibri"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
          '<font><sz val="10"/><color rgb="FF7F7F7F"/><name val="Calibri"/></font><font><b/><sz val="10"/><name val="Calibri"/></font></fonts>'
          '<fills count="10"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E79"/></patternFill></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FFF8D7DA"/></patternFill></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF3CD"/></patternFill></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FFD4EDDA"/></patternFill></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FFDDEBF7"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE4DFEC"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFFCE4D6"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFEDEDED"/></patternFill></fill></fills>'
          '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
          '<cellXfs count="18"><xf/><xf fontId="1" fillId="2" applyFont="1" applyFill="1"><alignment vertical="center" wrapText="1"/></xf>'
          '<xf applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
          '<xf fillId="3" applyFill="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
          '<xf fillId="4" applyFill="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
          '<xf fillId="5" applyFill="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
          '<xf fontId="2" applyFont="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
          '<xf fontId="3" applyFont="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
          '<xf fillId="6" fontId="3" applyFill="1" applyFont="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf fillId="7" fontId="3" applyFill="1" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf fillId="8" fontId="3" applyFill="1" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf fillId="6" fontId="3" applyFill="1" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf fillId="5" fontId="3" applyFill="1" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf fillId="6" fontId="3" applyFill="1" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf><xf fillId="4" fontId="3" applyFill="1" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf><xf fillId="5" fontId="3" applyFill="1" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf><xf fillId="3" fontId="3" applyFill="1" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf><xf fillId="9" fontId="3" applyFill="1" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf></cellXfs></styleSheet>')


def auto(name, rows):
    """(name, rows, widths, wrap_cols) with widths from the content (10-60) and wrapping for long text columns."""
    n = max((len(r) for r in rows), default=1)
    widths, wrap = [], []
    for ci in range(n):
        longest = max((len(str(r[ci][0] if isinstance(r[ci], tuple) else r[ci])) for r in rows[:300] if ci < len(r) and r[ci] is not None), default=8)
        widths.append(max(10, min(60, longest + 2)))
        if longest > 45:
            wrap.append(ci)
    return (name, rows, widths, wrap)


def write(path, sheets):
    """sheets: list of (name, rows, widths, wrap_cols[, merges]) — rows[0] is the header; merges = ["A2:A9", ...] (the sheet then has no filter)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        n = len(sheets)
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, n + 1))
                   + '</Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(s[0][:31])}" sheetId="{i}" r:id="rId{i}"/>' for i, s in enumerate(sheets, 1)) + '</sheets>'
                   + '<definedNames>' + "".join(
                       f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">\'{escape(s[0][:31])}\'!$A$1:${_col(max(len(r) for r in s[1]) - 1)}${len(s[1])}</definedName>'
                       for i, s in enumerate(sheets) if len(s[1]) > 1 and not (len(s) > 4 and s[4])) + '</definedNames></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, n + 1))
                   + f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", STYLES)
        for i, (name, rows, widths, wrap, *more) in enumerate(sheets, 1):
            merges = more[0] if more else None
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet(rows, widths, set(wrap), merges))


def update(path, new_sheets, dest=None):
    """Replace / add `new_sheets` ([(name, rows)]) in the workbook at `path`; every other sheet keeps its values, with numbers and booleans still numbers and booleans and blank rows kept; formatting is regenerated (number and date formats are not kept: a date cell shows its serial number), so the caller keeps a backup copy."""
    old = read(path, styles=True, typed=True)
    merges = read_merges(path)
    replaced = {x[0] for x in new_sheets}
    merged = [auto(n, rows) + (merges.get(n) or None,) if merges.get(n) else auto(n, rows) for n, rows in old.items() if n not in replaced]
    out = []
    for x in new_sheets:  # (name, rows) or (name, rows, merges)
        out.append(auto(x[0], x[1]) + ((x[2],) if len(x) > 2 and x[2] else ()))
    # keep the existing sheet order; replaced sheets stay where they were, new ones are appended
    result = []
    by_name = {s[0]: s for s in merged + out}
    for n in old:
        result.append(by_name[n])
    for s in out:
        if s[0] not in old:
            result.append(s)
    write(dest or path, result)
    return [s[0] for s in result]
