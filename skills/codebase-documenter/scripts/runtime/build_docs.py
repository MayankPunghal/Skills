"""Resolve documentation sources (docs/_src/**) into the published Markdown (docs/**).

Authors write cross-references as short tags; this script turns every tag into a real link to the
generated reference pages, so every name in the documentation is clickable and no link is guessed.

Tags (text after | is optional display text):
  [[table:Order]]                 -> Database tables (first database page first)
  [[proc:Order_Calculate_Totals]] -> Stored procedures / functions / views
  [[enum:LineType]]               -> Enumerations
  [[ctl:Order]] / [[ctl:OrderController]] -> Controller section
  [[act:Order.Create]]            -> Controller action row
  [[cls:InvoiceService]]          -> Code component / model class
  [[views:Sales/Order]]           -> Razor view folder (Area/Folder; use (root) for non-area views)
  [[seed:Order_Status]]           -> Seed-data script
  [[role:Administrator]]          -> Role anchor (from a permissions adapter)
  [[js:app.js]]                   -> Custom JavaScript
  [[rpt:Sales_Summary]]           -> SSRS report
  [[page:security/findings.md#anchor|text]] -> another documentation page (checked to exist; the path is from the docs root,
                                     a leading ../ is dropped)
  [[n:db-access.sites]]           -> a headline number from docs/agent/stats.json (written by the adapters), so a page
                                     never carries a count copied from a generated page that goes stale on the next build

  [[<prefix>:Name]]               -> any other anchor prefix (exact, then suffix match)

Also writes docs/appendices/coverage.md (which narrative pages mention each item, per codebase-docs.json "coverage"),
regenerates the mkdocs.yml nav between the "# >>> nav" / "# <<< nav" markers (when present) and reports the
number of unfinished scaffold sections (docs:todo markers).
Run from the workspace root:  python docs/_tools/build_docs.py
"""
import json
import os
import re
from collections import defaultdict

# Workspace root = the folder holding codebase-docs.json (two levels above docs/_tools); run from there.
CFG_PATH = "codebase-docs.json"
CFG = json.load(open(CFG_PATH, encoding="utf-8")) if os.path.exists(CFG_PATH) else {}
DOCS = CFG.get("docs_dir", "docs")
SRC = os.path.join(DOCS, "_src")
REF = os.path.join(DOCS, "reference")
DEFAULT_COVERAGE = [{"title": "Controllers", "prefix": "ctl-", "page": "controllers.md"},
                    {"title": "Classes", "prefix": "cls-", "page": "components.md"},
                    {"title": "Routines", "prefix": "sp-", "page": "db-routines.md"},
                    {"title": "Tables", "prefix": "tbl-", "page": "db-tables.md"}]
SECTION_ORDER = ["", "getting-started", "architecture", "modules", "workflows", "integrations", "data", "shared",
                 "operations", "security", "how-to", "appendices"]


def slug(*parts):
    return re.sub(r"[^a-z0-9]+", "-", "-".join(parts).lower()).strip("-")


_MAIN = CFG.get("adapter_options", {}).get("aspnet-mvc-ssdt", {}).get("web_project") or CFG.get("code_name") or ""
MAIN_CTL = slug("ctl", _MAIN) + "-" if _MAIN else ""  # controllers of the main web project win name clashes
TAG = re.compile(r"\[\[(\w+):([^\]|]+)(?:\|([^\]]+))?\]\]")


def load_anchors():
    """anchor id -> reference page (first page wins, in priority order)."""
    order = ["db-tables.md", "db-routines.md", "controllers.md", "enums.md", "components.md", "models.md", "views.md",
             "seed-data.md", "permissions.md", "javascript.md", "ssrs-reports.md", "reportdb-tables.md",
             "reportdb-routines.md", "shareddb-tables.md", "shareddb-routines.md", "configuration.md", "packages.md"]
    present = set(os.listdir(REF)) if os.path.isdir(REF) else set()
    pages = [p for p in order if p in present] + sorted(f for f in present if f.endswith(".md") and f not in order)
    anchors = {}
    for page in pages:
        text = open(os.path.join(REF, page), encoding="utf-8").read()
        for a in re.findall(r'<a id="([^"]+)"', text):
            anchors.setdefault(a, page)
    return anchors


def build_suffix_index(anchors):
    by_prefix = defaultdict(list)
    for a, page in anchors.items():
        by_prefix[a.split("-")[0]].append((a, page))
    # controller anchor -> class name, from the "### Name" heading that follows each anchor
    names = defaultdict(list)
    cpath = os.path.join(REF, "controllers.md")
    text = open(cpath, encoding="utf-8").read() if os.path.exists(cpath) else ""
    for a, n in re.findall(r'<a id="(ctl-[^"]+)"></a>\s*### (\w+)', text):
        names[n.lower()].append(a)
    by_prefix["ctl_names"] = names
    return by_prefix


def resolve(kind, target, anchors, idx):
    t = target.strip()
    if kind in ("table", "proc", "enum", "seed", "role", "rpt"):
        prefix = {"table": "tbl", "proc": "sp", "enum": "enum", "seed": "seed", "role": "role", "rpt": "rpt"}[kind]
        a = slug(prefix, t)
        if a in anchors:
            return anchors[a], a
        if kind == "proc" and "." in t:  # SalesDb.dbo.Order_Approve / dbo.Order_Approve: entries are anchored on the bare name
            a = slug(prefix, t.rsplit(".", 1)[-1].strip("[]\""))
            if a in anchors:
                return anchors[a], a
        return None
    if kind in ("ctl", "act"):
        ctl, act = (t.rsplit(".", 1) + [None])[:2] if kind == "act" else (t, None)
        name = ctl if "controller" in ctl.lower() else ctl + "Controller"
        # exact class name first (Sales_RegionController must not match RegionController), main web project first
        cands = [a for a in idx["ctl_names"].get(name.lower(), [])]
        if not cands:  # qualified form, e.g. Api-root-AccountController
            cands = [a for a, _ in idx["ctl"] if a.endswith("-" + slug(name))]
        cands.sort(key=lambda a: (not (MAIN_CTL and a.startswith(MAIN_CTL)), len(a)))
        for c in cands:
            a = c if kind == "ctl" else "act-" + c[4:] + "-" + slug(act)
            if a in anchors:
                return anchors[a], a
        # no controllers.md (generic adapters only): the class / method entries of the graph reference, then the endpoint
        if kind == "ctl":
            return resolve("cls", name, anchors, idx) if "cls" in idx else None
        r = resolve("mth", f"{name}.{act}", anchors, idx) if "mth" in idx else None
        if r or "ep" not in idx:
            return r
        short = name[: -len("controller")] if name.lower().endswith("controller") else name
        cands = sorted(((x, p) for x, p in idx["ep"] if x.endswith("-" + slug(short, act))), key=lambda c: len(c[0]))
        return (cands[0][1], cands[0][0]) if cands else None
    if kind == "cls":
        end = "-" + slug(t)
        cands = [(a, p) for a, p in idx["cls"] if a.endswith(end)]
        cands.sort(key=lambda x: (x[1] != "components.md", len(x[0])))
        return (cands[0][1], cands[0][0]) if cands else None
    if kind == "views":
        area, folder = t.split("/", 1)
        cands = [(x, p) for x, p in idx["views"] if x.endswith("-" + slug(area, folder))]
        return (cands[0][1], cands[0][0]) if cands else None
    if kind == "js":
        cands = [(a, p) for a, p in idx["js"] if a.endswith("-" + slug(t))]
        return (cands[0][1], cands[0][0]) if cands else None
    if kind in idx:  # any other anchor prefix (fn, mod, com, cfg, ep ...): exact id, then suffix match
        a = slug(kind, t)
        if a in anchors:
            return anchors[a], a
        cands = sorted(((x, p) for x, p in idx[kind] if x.endswith("-" + slug(t))), key=lambda c: len(c[0]))
        return (cands[0][1], cands[0][0]) if cands else None
    return None


def dedupe_ids():
    """Overloads (GET/POST actions), case-variant file names and same-named nested classes produce the same
    anchor twice; keep the first and suffix later ones (-2, -3 ...) so every id in a page is unique."""
    for page in os.listdir(REF):
        if not page.endswith(".md"):
            continue
        fp = os.path.join(REF, page)
        text = open(fp, encoding="utf-8").read()
        seen = defaultdict(int)

        def fix(m):
            seen[m.group(1)] += 1
            n = seen[m.group(1)]
            return m.group(0) if n == 1 else f'<a id="{m.group(1)}-{n}"'
        new = re.sub(r'<a id="([^"]+)"', fix, text)
        if new != text:
            open(fp, "w", encoding="utf-8").write(new)


def unlink_missing_anchors():
    """Generated pages link table/action names optimistically; a name that has no entry (a view, a dropped
    object, a pseudo-table in a seed script) is shown as plain text instead of a dead link."""
    ids = {}
    for page in os.listdir(REF):
        if page.endswith(".md"):
            ids[page] = set(re.findall(r'<a id="([^"]+)"', open(os.path.join(REF, page), encoding="utf-8").read()))
    link = re.compile(r"\[([^\]]+)\]\(((?:[\w-]+\.md)?)#([^)\s]+)\)")
    for page in ids:
        fp = os.path.join(REF, page)
        text = open(fp, encoding="utf-8").read()

        def fix(m):
            target = m.group(2) or page
            if target in ids and m.group(3) not in ids[target] and m.group(3) != "index":
                return m.group(1)
            return m.group(0)
        new = link.sub(fix, text)
        if new != text:
            open(fp, "w", encoding="utf-8").write(new)


def main():
    dedupe_ids()
    unlink_missing_anchors()
    anchors = load_anchors()
    idx = build_suffix_index(anchors)
    sp = os.path.join(DOCS, "agent", "stats.json")
    stats = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    unresolved = defaultdict(set)
    mentions = defaultdict(set)  # (kind, anchor) -> pages
    written = []
    for d, _, files in os.walk(SRC):
        for f in files:
            if not f.endswith(".md"):
                continue
            src = os.path.join(d, f)
            relp = os.path.relpath(src, SRC)
            dst = os.path.join(DOCS, relp)
            text = open(src, encoding="utf-8").read()
            depth = relp.replace("\\", "/").count("/")
            to_ref = "../" * depth + "reference/"
            to_root = "../" * depth

            def sub(m):
                kind, target, label = m.group(1), m.group(2), m.group(3)
                if kind == "n":
                    area, _, key = target.strip().partition(".")
                    v = (stats.get(area) or {}).get(key)
                    if v is None:
                        unresolved["n"].add(f"{target} (in {relp}; known: {', '.join(sorted(stats)) or 'none'})")
                        return f"**[number {target} not found]**"
                    return f"{v:,}" if isinstance(v, int) else str(v)
                if kind == "page":
                    path, _, frag = target.partition("#")
                    # page targets are docs-root paths: a leading ../ ./ or / would be applied twice in the written link
                    path = re.sub(r"^(?:\.{1,2}/|/)+", "", path.strip().replace("\\", "/"))
                    if not os.path.exists(os.path.join(SRC, path)) and not os.path.exists(os.path.join(DOCS, path)):
                        unresolved["page"].add(f"{target} (in {relp})")
                    return f"[{label or path}]({to_root}{path}{'#' + frag if frag else ''})"
                r = resolve(kind, target, anchors, idx)
                shown = label or f"`{target.split('.')[-1] if kind == 'act' else target}`"
                if kind == "act" and not label:
                    shown = f"`{target}`"
                if not r:
                    unresolved[kind].add(f"{target} (in {relp})")
                    return shown
                page, a = r
                mentions[(kind, a)].add(relp.replace("\\", "/"))
                return f"[{shown}]({to_ref}{page}#{a})"

            out = TAG.sub(sub, text)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(out)
            written.append(relp)
    write_coverage(anchors, mentions)
    write_nav()
    print(f"built {len(written)} pages")
    todo, files = count_todo()
    if todo:
        print(f"TODO markers: {todo} in {len(files)} pages (first: {', '.join(files[:8])})")
    for k, v in sorted(unresolved.items()):
        print(f"UNRESOLVED {k}: {len(v)}")
        for x in sorted(v)[:200]:
            print("   ", x)


def write_coverage(anchors, mentions):
    """Every item of each configured kind with the narrative pages that discuss it."""
    covered = defaultdict(set)
    for (kind, a), pages in mentions.items():
        covered[a] |= pages
    out = ["# Coverage index", "",
           "This appendix is generated. It lists every documented item of the tracked kinds and the narrative pages that "
           "discuss it, so reviewers can check that nothing was left out. Items with no narrative page are still fully "
           "listed in the reference section.", ""]
    for c in CFG.get("coverage") or DEFAULT_COVERAGE:
        title, prefix, page = c["title"], c["prefix"], c["page"]
        items = sorted(a for a, p in anchors.items() if a.startswith(prefix) and p == page
                       and not (re.search(r"-\d+$", a) and re.sub(r"-\d+$", "", a) in anchors))  # overload / partial repeats
        if not items:
            continue
        if prefix == "ctl-":  # a controller is covered when any of its actions is discussed
            for a in items:
                pre = "act-" + a[4:] + "-"
                for m, pages in list(covered.items()):
                    if m.startswith(pre):
                        covered[a] |= pages
        done = [a for a in items if a in covered]
        out += ["", f"## {title}", "", f"{len(done)} of {len(items)} are discussed in a narrative page.", "",
                "| Item | Discussed in |", "| --- | --- |"]
        for a in items:
            label = a[len(prefix):]
            pages = ", ".join(f"[{p[:-3]}](../{p})" for p in sorted(covered.get(a, [])))
            out.append(f"| [{label}](../reference/{page}#{a}) | {pages or '_reference only_'} |")
    os.makedirs(os.path.join(DOCS, "appendices"), exist_ok=True)
    with open(os.path.join(DOCS, "appendices", "coverage.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")


def h1(path):
    for line in open(path, encoding="utf-8"):
        if line.startswith("# "):
            return re.sub(r"[*`]", "", line[2:].strip())
    return os.path.basename(path)[:-3]


def nav_order(path):
    m = re.search(r"<!--\s*nav:\s*(\d+)\s*-->", open(path, encoding="utf-8").read())
    return int(m.group(1)) if m else 999


def write_nav():
    """Rebuild the nav block of mkdocs.yml from docs/_src (sections in SECTION_ORDER; index first, then the
    <!-- nav: N --> order, then title) plus docs/reference and the coverage appendix. Only touches the text between
    the "# >>> nav" and "# <<< nav" markers, so a hand-written nav (no markers) is left alone."""
    yml = "mkdocs.yml"
    if not os.path.exists(yml):
        return
    text = open(yml, encoding="utf-8").read()
    start, end = "# >>> nav", "# <<< nav"
    if start not in text or end not in text:
        return

    def section_key(d):
        top = d.split("/")[0]
        return (SECTION_ORDER.index(top) if top in SECTION_ORDER else 50, d)

    dirs = set()
    for d, _, fs in os.walk(SRC):
        if any(f.endswith(".md") for f in fs):
            r = os.path.relpath(d, SRC).replace("\\", "/")
            dirs.add("" if r == "." else r)

    def pages_of(d):
        base = os.path.join(SRC, d)
        fs = [f for f in os.listdir(base) if f.endswith(".md")]
        return sorted(fs, key=lambda f: (f != "index.md", nav_order(os.path.join(base, f)), h1(os.path.join(base, f))))

    def q(t):
        return '"' + t.replace('"', "'") + '"'

    lines = ["nav:"]
    for d in sorted(dirs, key=section_key):
        if d == "":
            for f in pages_of(""):
                lines.append("  - Home: index.md" if f == "index.md" else f"  - {q(h1(os.path.join(SRC, f)))}: {f}")  # "Home", so the product name is not repeated as the first tab
            continue
        pad = "  " + "    " * d.count("/")  # a sub-folder nests under its parent's page list (YAML indent 2 + 4 per level)
        idx = os.path.join(SRC, d, "index.md")
        title = h1(idx) if os.path.exists(idx) else d.split("/")[-1].replace("-", " ").title()
        lines.append(f"{pad}- {q(title)}:")
        for f in pages_of(d):
            p = f"{d}/{f}"
            lines.append(f"{pad}    - {p}" if f == "index.md" else f"{pad}    - {q(h1(os.path.join(SRC, d, f)))}: {p}")
        if d == "appendices" and os.path.exists(os.path.join(DOCS, "appendices", "coverage.md")):
            lines.append(f"{pad}    - Coverage index: appendices/coverage.md")
    refs = sorted(f for f in os.listdir(REF) if f.endswith(".md")) if os.path.isdir(REF) else []
    if refs:
        ins = len(lines)
        for k, line in enumerate(lines):  # Reference goes just before Appendices
            if line.strip().startswith("- \"Appendices\""):
                ins = k
                break
        block = ['  - "Reference":'] + (["      - reference/index.md"] if "index.md" in refs else [])
        block += [f"      - {q(h1(os.path.join(REF, f)))}: reference/{f}" for f in refs if f != "index.md"]
        lines[ins:ins] = block
    i, j = text.index(start), text.index(end)
    head = text[:i] + start + " (generated by build_docs.py from docs/_src and docs/reference; do not edit by hand)\n"
    with open(yml, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(head + "\n".join(lines) + "\n" + text[j:])


def count_todo():
    n, files = 0, []
    for d, _, fs in os.walk(SRC):
        for f in fs:
            if f.endswith(".md"):
                c = open(os.path.join(d, f), encoding="utf-8").read().count("docs:todo")
                if c:
                    n += c
                    files.append(os.path.relpath(os.path.join(d, f), SRC).replace("\\", "/"))
    return n, sorted(files)


if __name__ == "__main__":
    main()
