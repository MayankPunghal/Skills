"""Extract reference / seed data from the database deployment (seed) scripts.

Parses the INSERT statements in the seed folder (option `seeds_dir`, auto-detected: a DataSeeds / Seeds /
PostDeployment folder of the first SSDT project) and writes docs/reference/seed-data.md.
Sub-selects such as `(select Order_Status_Id from Order_Status where Name = 'Closed')`
are shown as the looked-up name, e.g. `→ Closed`.
Run from the workspace root:  python docs/_tools/gen_seeds.py
"""
import os
import re
from collections import defaultdict, OrderedDict

from _options import ROOT as _ROOT, DOCS as _DOCS, SEEDS_DIR

SEEDS = os.path.join(_ROOT, SEEDS_DIR) if SEEDS_DIR else None
OUT = os.path.join(_DOCS, "reference")


def read(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if len(raw) > 3 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        return raw.decode("utf-16-le")
    return raw.decode("utf-8-sig", errors="replace")


def strip_comments(sql):
    out, i, n, in_str = [], 0, len(sql), False
    while i < n:
        c = sql[i]
        if in_str:
            out.append(c)
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("'")
                    i += 1
                else:
                    in_str = False
        elif c == "'":
            in_str = True
            out.append(c)
        elif sql.startswith("--", i):
            while i < n and sql[i] != "\n":
                i += 1
            continue
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def split_top(s, sep=","):
    parts, cur, depth, in_str, i = [], "", 0, False, 0
    while i < len(s):
        c = s[i]
        if in_str:
            cur += c
            if c == "'":
                if i + 1 < len(s) and s[i + 1] == "'":
                    cur += "'"
                    i += 1
                else:
                    in_str = False
        elif c == "'":
            in_str = True
            cur += c
        elif c == "(":
            depth += 1
            cur += c
        elif c == ")":
            depth -= 1
            cur += c
        elif c == sep and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += c
        i += 1
    if cur.strip():
        parts.append(cur.strip())
    return parts


def balanced(s, start):
    """Return index just after the ')' matching the '(' at s[start]."""
    depth, in_str, i = 0, False, start
    while i < len(s):
        c = s[i]
        if in_str:
            if c == "'":
                if i + 1 < len(s) and s[i + 1] == "'":
                    i += 1
                else:
                    in_str = False
        elif c == "'":
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def show(v):
    v = v.strip()
    m = re.match(r"^\(\s*select\s+.*?\bwhere\b.*?=\s*'((?:[^']|'')*)'.*\)$", v, re.I | re.S)
    if m:
        return "→ " + m.group(1).replace("''", "'")
    if v.upper() == "NULL":
        return ""
    if v.startswith("N'"):
        v = v[1:]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1].replace("''", "'")
    return re.sub(r"\s+", " ", v)


def parse_inserts(sql):
    rows = []
    for m in re.finditer(r"insert\s+(?:into\s+)?(?:\[?dbo\]?\.)?\[?(@?\w+)\]?\s*\(", sql, re.I):
        table = m.group(1)
        cstart = m.end() - 1
        cend = balanced(sql, cstart)
        if cend < 0:
            continue
        cols = [c.strip(" []") for c in split_top(sql[cstart + 1:cend - 1])]
        rest = sql[cend:]
        vm = re.match(r"\s*values\s*", rest, re.I)
        if not vm:
            # INSERT ... SELECT <values> FROM <lookup> WHERE <condition>: keep the literal values and the condition
            sm = re.match(r"\s*select\s+(.*?)\s+from\s+(.*?)(?=\binsert\b|\bdelete\b|\bupdate\b|\bset\b|\bprint\b|\bexec\b|\bend\b|$)", rest, re.I | re.S)
            if sm:
                vals = split_top(sm.group(1))
                if len(vals) == len(cols):
                    cond = re.sub(r"\s+", " ", sm.group(2)).strip()
                    rows.append((table, cols + ["(looked up from)"], [show(v) for v in vals] + [cond]))
            continue
        pos = cend + vm.end()
        while pos < len(sql) and sql[pos] == "(":
            vend = balanced(sql, pos)
            if vend < 0:
                break
            vals = split_top(sql[pos + 1:vend - 1])
            if len(vals) == len(cols):
                rows.append((table, cols, [show(v) for v in vals]))
            nxt = re.match(r"\s*,\s*", sql[vend:])
            if not nxt:
                break
            pos = vend + nxt.end()
    return rows


def slug(*parts):
    return re.sub(r"[^a-z0-9]+", "-", "-".join(parts).lower()).strip("-")


def md_table(cols, rows):
    esc = lambda x: str(x).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(esc(c) for c in cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    out += ["| " + " | ".join(esc(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def gen_seed_tables():
    files = sorted(f for f in os.listdir(SEEDS) if f.lower().endswith(".sql"))
    out = ["# Seed and reference data", "",
           f"Rows inserted by the seed scripts in `{SEEDS_DIR}`. "
           "These scripts rebuild the lookup tables on every deployment, so this is the configuration the application "
           "runs with. Values written as `→ Name` are looked up by name in the script. Statements the extractor could not "
           "read row by row (loops, MERGE, dynamic SQL) are not listed; check the script itself for those.", ""]
    index = []
    body = []
    for f in files:
        rows = parse_inserts(strip_comments(read(os.path.join(SEEDS, f))))
        if not rows:
            continue
        grouped = OrderedDict()
        for table, cols, vals in rows:
            key = (table.lower(), tuple(c.lower() for c in cols))
            grouped.setdefault(key, (table, cols, []))[2].append(vals)
        anchor = slug("seed", f[:-4])
        tables = sorted({t for (t, _, _) in rows}, key=str.lower)
        tlinks = ", ".join(f"[{t}](db-tables.md#{slug('tbl', t)})" if not t.startswith("@") and not t.startswith("#") else t for t in tables)
        index.append(f"| [{f}](#{anchor}) | {tlinks} | {len(rows)} |")
        body += ["", f'<a id="{anchor}"></a>', "", f"## {f[:-4]}", "", f"Source: `{SEEDS_DIR}/{f}` · [↑ Back to index](#index)"]
        for (_, _), (table, cols, vals) in grouped.items():
            tl = f"[{table}](db-tables.md#{slug('tbl', table)})" if not table.startswith(("@", "#")) else table
            body += ["", f"### {table} ({len(vals)} rows)", "", f"Table definition: {tl}", "", md_table(cols, vals)]
    out += ['<a id="index"></a>', "", "| Script | Tables loaded | Rows extracted |", "| --- | --- | --- |"] + index + body
    with open(os.path.join(OUT, "seed-data.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    return len(index)


if __name__ == "__main__":
    if not SEEDS or not os.path.isdir(SEEDS):
        print("no seed folder found; seed-data.md not written (set adapter_options.aspnet-mvc-ssdt.seeds_dir)")
    else:
        os.makedirs(OUT, exist_ok=True)
        print("seed scripts", gen_seed_tables())
