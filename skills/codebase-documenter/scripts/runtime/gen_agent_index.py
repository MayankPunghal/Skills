"""Build the machine-readable entry points that let coding agents use the documentation.

Writes:
  docs/agent/entities.jsonl  one JSON object per documented thing (table, procedure, controller, action, class,
                             view, enum, seed script, claim, role, script, report, narrative section, finding row
                             with a SEC- / DEF- / TD- id, narrative table row that links a method / class / endpoint):
                             {"kind", "name", "file", "anchor", "summary"}
  docs/llms.txt              llms.txt-style map of the narrative pages (title + one-line description each)

Run from the workspace root after build_docs.py:  python docs/_tools/gen_agent_index.py
Look things up with:  python docs/_tools/lookup.py <name> [--kind K] [--find TEXT] [--src PATH]
  (run from the workspace root; prints doc: <path>:<line> and src: <path>:<line> for each match)
"""
import json
import os
import re

DOCS = (json.load(open("codebase-docs.json", encoding="utf-8")).get("docs_dir", "docs") if os.path.exists("codebase-docs.json") else "docs")
REF = os.path.join(DOCS, "reference")
KIND = {"tbl": "table", "sp": "routine", "ctl": "controller", "act": "action", "cls": "class", "view": "view",
        "views": "view-folder", "enum": "enum", "seed": "seed", "claim": "claim", "role": "role", "js": "script",
        "rpt": "report", "area": "area", "kind": "section", "fn": "function", "mod": "module", "com": "community",
        "ep": "endpoint", "cfg": "config-key", "mth": "method", "prj": "project", "pkg": "package",
        "err": "error", "net": "network-endpoint", "run": "runbook", "dba": "db-access", "ui": "ui-trigger", "ent": "entry-point"}
CFG = json.load(open("codebase-docs.json", encoding="utf-8")) if os.path.exists("codebase-docs.json") else {}
FRONT = re.compile(r"\A---\n.*?\n---\n", re.S)  # YAML front matter
SKIP_DIRS = {"_src", "_notes", "_tools", "agent", "assets"}


def plain(md):
    md = re.sub(r"<[^>]+>", "", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"[*`]", "", md)
    return re.sub(r"\s+", " ", md).strip(" |")


def reference_entities():
    for page in sorted(os.listdir(REF)):
        if not page.endswith(".md"):
            continue
        lines = open(os.path.join(REF, page), encoding="utf-8").read().splitlines()
        db = {"db-": "main", "reportdb-": "report", "shareddb-": "shared"}
        dbname = next((v for k, v in db.items() if page.startswith(k)), None)
        for i, line in enumerate(lines):
            for aid in re.findall(r'<a id="([^"]+)"></a>', line):
                prefix = aid.split("-")[0]
                if prefix not in KIND or aid == "index":
                    continue
                rest = line.split(f'<a id="{aid}"></a>', 1)[1]
                if not plain(rest):  # anchor on its own line: the heading / text follows
                    rest = next((l for l in lines[i + 1:i + 6] if l.strip()), "")
                text = plain(rest)
                name = re.match(r"(?:#+\s*)?([^|]+?)(?:\s*\(|\s*\||$)", text)
                name = re.sub(r"^(dbo|reports)\.", "", (name.group(1) if name else text).lstrip("# ").strip())
                ent = {"kind": KIND[prefix], "name": name, "file": f"docs/reference/{page}", "anchor": aid,
                       "summary": text[:400]}
                if dbname and prefix in ("tbl", "sp"):
                    ent["database"] = dbname
                yield ent


SEED_ROWS = {t.lower() for t in CFG.get("seed_row_tables", [])}  # seed tables whose rows are indexed one by one


def seed_row_entities():
    """Individual rows of the seed tables agents ask about most (validation messages, rules, statuses, document types),
    so e.g. `lookup.py 336` or `lookup.py "CORE ID"` finds validation message 336 with its severity."""
    path = os.path.join(REF, "seed-data.md")
    if not SEED_ROWS or not os.path.exists(path):
        return
    lines = open(path, encoding="utf-8").read().splitlines()
    table, header, anchor = None, None, None
    for line in lines:
        m = re.match(r'<a id="(seed-[^"]+)"></a>', line)
        if m:
            anchor = m.group(1)
        m = re.match(r"### @?(\w+) \(", line)
        if m:
            table, header = m.group(1), None
            continue
        if not table or table.lower() not in SEED_ROWS or not line.startswith("|") or line.startswith("| ---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        row = dict(zip(header, cells))
        label = row.get("Message") or row.get("Name") or row.get("Procedure_Name") or ""
        yield {"kind": "seed-row", "name": f"{table} {cells[0]}: {label}", "file": "docs/reference/seed-data.md",
               "anchor": anchor, "summary": "; ".join(f"{k}={v}" for k, v in row.items() if v)[:400]}


def slugify(h):
    return re.sub(r"[\s]+", "-", re.sub(r"[^\w\s-]", "", h.lower())).strip("-")


def narrative_entities():
    for d, dirs, files in os.walk(DOCS):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not (d == DOCS and x == "reference")]
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            p = os.path.join(d, f).replace("\\", "/")
            raw = open(p, encoding="utf-8").read()
            fm = FRONT.match(raw)
            off = fm.group(0).count("\n") if fm else 0  # rows carry their real 0-based line in the file
            text = re.sub(FRONT, "", raw)  # front matter
            lines = text.splitlines()
            heading = ""
            for i, line in enumerate(lines):
                if line.startswith("|") and not line.startswith("| ---"):
                    # table rows of narrative pages: finding ids (SEC-nn, DEF-nn, TD-nn) and rows that link a method,
                    # class, endpoint or controller, so "claims editor without role check -> SEC-02" is found without grep
                    row = plain(line)
                    ids = re.findall(r"\b(?:SEC|DEF|TD)-\d+\b", row)
                    if ids:
                        yield {"kind": "finding", "name": (row if row.startswith(ids[0]) else f"{ids[0]} {row}")[:120], "file": p, "anchor": "", "line": off + i,
                               "summary": (f"{heading}: " if heading else "") + row[:400]}
                    elif re.search(r"reference/[\w-]+\.md#(?:mth|cls|ep|act|ctl)-", line):
                        first = plain(line.strip("|").split("|")[0])
                        yield {"kind": "narrative-row", "name": first[:120], "file": p, "anchor": "", "line": off + i,
                               "summary": (f"{heading}: " if heading else "") + row[:400]}
                    continue
                m = re.match(r"(#{1,3})\s+(.+)", line)
                if not m:
                    continue
                heading = plain(m.group(2))
                para = next((plain(l) for l in lines[i + 1:i + 8] if l.strip() and not l.startswith(("#", "<a", "```", "|"))), "")
                yield {"kind": "page" if m.group(1) == "#" else "section", "name": plain(m.group(2)), "file": p,
                       "anchor": "" if m.group(1) == "#" else slugify(plain(m.group(2))), "summary": para[:400]}


def llms_txt():
    nav = open("mkdocs.yml", encoding="utf-8").read().split("\nnav:", 1)[1]
    name = " / ".join(x for x in (CFG.get("product"), CFG.get("code_name")) if x) or "Project"
    what = CFG.get("description") or "the system"
    stack = f" ({CFG['stack']})" if CFG.get("stack") else ""
    out = [f"# {name} documentation", "",
           f"> Product and technical documentation of {what}{stack}. Narrative pages explain behaviour and rules; reference "
           "pages list every documented code element and data object with anchors. Machine index: docs/agent/entities.jsonl; "
           "lookup: python docs/_tools/lookup.py <Name>.", ""]
    section = None
    for line in nav.splitlines():
        m = re.match(r"\s*-\s+(?:\"?([^:\"]+)\"?:\s*)?([\w/.-]+\.md)?\s*$", line)
        if not m:
            continue
        title, path = m.group(1), m.group(2)
        if title and not path:
            section = title.strip()
            out += ["", f"## {section}", ""]
            continue
        if path:
            fp = os.path.join(DOCS, path)
            first = ""
            if os.path.exists(fp):
                body = re.sub(FRONT, "", open(fp, encoding="utf-8").read()).splitlines()
                h = next((l[2:] for l in body if l.startswith("# ")), path)
                first = next((plain(l) for l in body if l.strip() and not l.startswith(("#", "<", "|", "!", "```", "-"))), "")
                title = title or h
            out.append(f"- [{(title or path).strip()}](docs/{path}): {first[:200]}")
    return "\n".join(out) + "\n"


def main():
    os.makedirs(os.path.join(DOCS, "agent"), exist_ok=True)
    ents = list(reference_entities()) + list(seed_row_entities()) + list(narrative_entities())
    with open(os.path.join(DOCS, "agent", "entities.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
        for e in ents:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(os.path.join(DOCS, "llms.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(llms_txt())
    counts = {}
    for e in ents:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    print(len(ents), "entities", counts)


if __name__ == "__main__":
    main()
