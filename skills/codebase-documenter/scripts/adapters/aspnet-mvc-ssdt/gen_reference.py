"""ASP.NET MVC + SSDT adapter: enums, controllers/actions, SSDT tables/routines, config keys, NuGet packages.

Everything in the generated files is extracted from code; nothing is hand-typed.
Run by build_site.py (cwd = workspace root). Options: see _options.py.
"""
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

from _options import ROOT, DOCS, PRODUCT, WEB_PROJECT, DATABASES, EDMX, is_custom_js

WEB = os.path.join(ROOT, WEB_PROJECT)
OUT = os.path.join(DOCS, "reference")
SKIP_DIRS = {"bin", "obj", "packages", ".vs", "node_modules"}
SENSITIVE = re.compile(r"pass|pwd|secret|token|credential|key=|apikey|evopdfk|connectionstring|ntpassword", re.I)


def walk(base, exts):
    for d, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            if f.lower().endswith(exts):
                yield os.path.join(d, f)


def read(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if len(raw) > 3 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        return raw.decode("utf-16-le")
    return raw.decode("utf-8-sig", errors="replace")


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def write(name, text):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def slug(*parts):
    return re.sub(r"[^a-z0-9]+", "-", "-".join(parts).lower()).strip("-")


def anchor(aid):
    return f'<a id="{aid}"></a>'


BACK = "[↑ Back to index](#index)"

_CODE_CACHE = None


def code_files():
    """(relpath, text) for every hand-written C#/Razor/JS file (generated EF model files excluded)."""
    global _CODE_CACHE
    if _CODE_CACHE is None:
        _CODE_CACHE = []
        for p in walk(ROOT, (".cs", ".cshtml", ".js")):
            r = rel(p)
            if r.endswith((".Designer.cs", ".Context.cs", ".min.js")) or "/Web References/" in r or "/Service References/" in r:
                continue
            if r.endswith(".js") and "/Scripts/" in r and not is_custom_js(r):
                continue
            _CODE_CACHE.append((r, read(p)))
    return _CODE_CACHE


def md_escape(s):
    return s.replace("|", "\\|").strip()


# ---------------------------------------------------------------- enums
def gen_enums():
    enum_re = re.compile(r"public\s+enum\s+(\w+)\s*(?::\s*\w+)?\s*\{(.*?)\}", re.S)
    member_re = re.compile(r'(?:\[Description\("([^"]*)"\)\]\s*)?(\w+)\s*(?:=\s*([^,\r\n/]+))?\s*,?', re.S)
    rows = []
    for path in sorted(walk(WEB, (".cs",))):
        if "Designer" in path:
            continue
        text = read(path)
        for m in enum_re.finditer(text):
            name, body = m.group(1), re.sub(r"//[^\n]*", "", m.group(2))
            members = []
            for mm in member_re.finditer(body):
                desc, ident, val = mm.group(1), mm.group(2), mm.group(3)
                if not ident:
                    continue
                members.append((ident, (val or "").strip(), desc or ""))
            rows.append((name, rel(path), members))
    out = ["# Enumerations", "",
           f"Every `enum` declared in {PRODUCT}, extracted from source. "
           "Values are the numbers stored in the database; descriptions are the labels shown to users where the code defines one.", ""]
    out += [anchor("index"), "", "| Enum | File |", "| --- | --- |"]
    for name, path, _ in sorted(rows):
        out.append(f"| [{name}](#{slug('enum', name)}) | `{path}` |")
    for name, path, members in sorted(rows):
        out += ["", anchor(slug("enum", name)), "", f"## {name}", "", f"Source: `{path}` · {BACK}", "", "| Name | Value | Label |", "| --- | --- | --- |"]
        for ident, val, desc in members:
            out.append(f"| {ident} | {md_escape(val)} | {md_escape(desc)} |")
    write("enums.md", "\n".join(out) + "\n")
    return len(rows)


# ---------------------------------------------------------------- controllers
def gen_controllers():
    ctrl_re = re.compile(r"public\s+(?:partial\s+)?class\s+(\w+Controller\w*)\s*:\s*([\w.<>]+)")
    act_re = re.compile(
        r"((?:\s*\[[^\]]+\]\s*)*)\s*public\s+(?:async\s+)?(?:virtual\s+)?(?:override\s+)?"
        r"(?:Task<)?(ActionResult|JsonResult|PartialViewResult|ViewResult|FileResult|FileContentResult|"
        r"FileStreamResult|ContentResult|RedirectResult|RedirectToRouteResult|EmptyResult|JavaScriptResult|"
        r"HttpResponseMessage|IHttpActionResult|IEnumerable<[^>]+>|[\w<>]+)>?\s+(\w+)\s*\(([^)]*)\)")
    by_area = defaultdict(list)
    total = 0
    for path in sorted(walk(ROOT, (".cs",))):
        p = rel(path)
        if "Test" in p.split("/")[0]:
            continue
        text = read(path)
        cm = ctrl_re.search(text)
        # MVC controllers live in Controllers/; Web API controllers (ApiController) also live under Api/
        if not cm or ("Controllers/" not in p and not cm.group(2).endswith("Controller")):
            continue
        project = p.split("/")[0]
        area = p.split("Areas/")[1].split("/")[0] if "Areas/" in p else ("Api" if "/Api/" in p else "(root)")
        actions = []
        for am in act_re.finditer(text):
            attrs, ret, name, params = am.group(1), am.group(2), am.group(3), am.group(4)
            # MVC exposes every public instance method as an action (void and primitive returns included)
            if name == "Dispose" or "NonAction" in attrs or ret in ("class", "interface", "enum"):
                continue
            verbs = ",".join(sorted(set(re.findall(r"Http(Get|Post|Put|Delete|Patch)", attrs)))) or "GET*"
            routes = re.findall(r'Route\("([^"]*)"\)', attrs)
            params = re.sub(r"\s+", " ", params).strip()
            actions.append((name, verbs, params, ", ".join(routes), "AllowAnonymous" in attrs))
        total += len(actions)
        by_area[(project, area)].append((cm.group(1), cm.group(2), p, actions))
    out = ["# Controllers and actions", "",
           "Every MVC / Web API controller and its public actions, extracted from source. "
           "`GET*` means no HTTP verb attribute is present, so MVC accepts any verb (normally reached by GET).",
           "", f"Total controllers: {sum(len(v) for v in by_area.values())}; total actions: {total}.", ""]
    out += [anchor("index"), "", "| Project / area | Controller | Actions |", "| --- | --- | --- |"]
    for (project, area) in sorted(by_area):
        for cname, base, p, actions in sorted(by_area[(project, area)]):
            out.append(f"| [{project} / {area}](#{slug('area', project, area)}) | [{cname}](#{slug('ctl', project, area, cname)}) | {len(actions)} |")
    for (project, area) in sorted(by_area):
        out += ["", anchor(slug("area", project, area)), "", f"## {project} / {area}", ""]
        for cname, base, p, actions in sorted(by_area[(project, area)]):
            anon = bool(re.search(r"AllowAnonymous[^\]]*\]\s*(?:\[[^\]]*\]\s*)*public\s+(?:partial\s+)?class", read(os.path.join(ROOT, p))))
            out += [anchor(slug("ctl", project, area, cname)), "", f"### {cname}", "",
                    f"File: `{p}` · Base class: `{base}`" + (" · **Whole controller is anonymous (no login)**" if anon else "") + f" · {BACK}", ""]
            if actions:
                out += ["| Action | Verb | Anonymous | Parameters | Route attribute |", "| --- | --- | --- | --- | --- |"]
                for name, verbs, params, routes, anon_a in actions:
                    out.append(f"| {anchor(slug('act', project, area, cname, name))}{name} | {verbs} | {'yes' if anon_a else ''} | `{md_escape(params)}` | {md_escape(routes)} |")
            else:
                out.append("No public actions found.")
            out.append("")
    write("controllers.md", "\n".join(out) + "\n")
    return total


# ---------------------------------------------------------------- database
def split_columns(body):
    depth, cur, parts = 0, "", []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def gen_tables(dbroot, title, fname, prefix="tbl"):
    tbl_re = re.compile(r"CREATE\s+TABLE\s+(?:\[?(\w+)\]?\.)?\[?([\w ]+?)\]?\s*\((.*)\)", re.S | re.I)
    tables = []
    for path in sorted(walk(dbroot, (".sql",))):
        text = re.sub(r"--[^\n]*", "", read(path))
        m = tbl_re.search(text)
        if not m or "CREATE TABLE" not in text.upper()[:4000]:
            continue
        schema, name, body = m.group(1) or "dbo", m.group(2), m.group(3)
        body = body.split("\nGO")[0]
        cols, fks = [], []
        for part in split_columns(body):
            up = part.upper()
            if up.startswith("CONSTRAINT") or up.startswith("PRIMARY KEY") or up.startswith("FOREIGN KEY") or up.startswith("UNIQUE") or up.startswith("INDEX"):
                fk = re.search(r"FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+(?:\[?\w+\]?\.)?\[?(\w+)\]?\s*\(([^)]*)\)", part, re.I)
                if fk:
                    fks.append((fk.group(1).replace("[", "").replace("]", "").strip(), fk.group(2), fk.group(3).replace("[", "").replace("]", "").strip()))
                continue
            cm = re.match(r"\[?([\w ]+?)\]?\s+(.*)", part, re.S)
            if not cm:
                continue
            cname, rest = cm.group(1), re.sub(r"\s+", " ", cm.group(2))
            tm = re.match(r"(\[?\w+\]?\s*(?:\([^)]*\))?)", rest)
            ctype = tm.group(1).replace("[", "").replace("]", "") if tm else rest
            if rest.upper().startswith("AS "):
                ctype = "computed: " + rest[3:]
            nullable = "NOT NULL" not in rest.upper() and "PRIMARY KEY" not in rest.upper()
            ident = "IDENTITY" in rest.upper()
            dflt = re.search(r"DEFAULT\s*(\(.*?\)\)?|'[^']*'|\S+)", rest, re.I)
            notes = []
            if ident:
                notes.append("identity")
            if "PRIMARY KEY" in rest.upper():
                notes.append("PK")
            if dflt:
                notes.append("default " + dflt.group(1))
            cols.append((cname, ctype, "yes" if nullable else "no", ", ".join(notes)))
        for fk in re.finditer(r"FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+(?:\[?\w+\]?\.)?\[?(\w+)\]?\s*\(([^)]*)\)", text, re.I):
            t = (fk.group(1).replace("[", "").replace("]", "").strip(), fk.group(2), fk.group(3).replace("[", "").replace("]", "").strip())
            if t not in fks:
                fks.append(t)
        tables.append((schema, name.strip(), rel(path), cols, fks))
    names = {t[1].strip().lower() for t in tables}
    referenced_by = defaultdict(set)
    for schema, name, p, cols, fks in tables:
        for col, tgt, tcol in fks:
            referenced_by[tgt.lower()].add((name.strip(), col))
    out = [f"# {title}", "", "Every table defined in the database project, extracted from its `CREATE TABLE` script. "
           "Click a table name to jump to its column breakdown; foreign keys link to the referenced table.",
           "", f"Total tables: {len(tables)}.", "", anchor("index"), "", "| Table | Columns | File |", "| --- | --- | --- |"]
    for schema, name, p, cols, _ in sorted(tables, key=lambda t: t[1].lower()):
        out.append(f"| [{schema}.{name.strip()}](#{slug(prefix, name.strip())}) | {len(cols)} | `{p}` |")
    for schema, name, p, cols, fks in sorted(tables, key=lambda t: t[1].lower()):
        name = name.strip()
        out += ["", anchor(slug(prefix, name)), "", f"## {schema}.{name}", "", f"Source: `{p}` · {BACK}", "",
                "| Column | Type | Nullable | Notes |", "| --- | --- | --- | --- |"]
        for c in cols:
            out.append("| " + " | ".join(md_escape(x) for x in c) + " |")
        refs = referenced_by.get(name.lower())
        if fks:
            out += ["", "**Foreign keys (this table → referenced table):**", ""]
            for col, tgt, tcol in fks:
                tl = f"[`{tgt}`](#{slug(prefix, tgt)})" if tgt.lower() in names else f"`{tgt}`"
                out.append(f"- `{col}` → {tl} `.{tcol}`")
        if refs:
            out += ["", "**Referenced by:** " + ", ".join(f"[`{t}`](#{slug(prefix, t)}).`{c}`" for t, c in sorted(refs))]
    write(fname, "\n".join(out) + "\n")
    return len(tables)


def known_objects(dbroot):
    names = set()
    for path in walk(dbroot, (".sql",)):
        for m in re.finditer(r"CREATE\s+(?:TABLE|VIEW|FUNCTION|SYNONYM)\s+(?:\[?\w+\]?\.)?\[?(\w+)\]?", read(path), re.I):
            names.add(m.group(1).lower())
    return names


def gen_routines(dbroot, title, fname, prefix="sp", table_page="db-tables.md", table_prefix="tbl"):
    known = known_objects(dbroot)
    rt_re = re.compile(r"CREATE\s+(PROCEDURE|PROC|FUNCTION|VIEW|TRIGGER)\s+(?:\[?(\w+)\]?\.)?\[?([\w\-]+)\]?(.*?)(?:\bAS\b|\bRETURNS\b|\bWITH\b)", re.S | re.I)
    items = []
    for path in sorted(walk(dbroot, (".sql",))):
        raw = read(path)
        text = re.sub(r"--[^\n]*", "", raw)
        m = rt_re.search(text)
        if not m:
            continue
        kind = {"PROC": "PROCEDURE"}.get(m.group(1).upper(), m.group(1).upper())
        params = re.findall(r"(@\w+)\s+([\w]+(?:\s*\([^)]*\))?)", m.group(4)) if kind in ("PROCEDURE", "FUNCTION") else []
        body = text[m.end():]
        tables = sorted(set(t for t in re.findall(r"(?:FROM|JOIN|INTO|UPDATE|MERGE)\s+(?:\[?dbo\]?\.)?\[?([A-Za-z_]\w+)\]?", body, re.I)
                            if t.lower() in known))
        items.append((kind, m.group(3), rel(path), params, tables))
    table_names = set()
    for path in walk(dbroot, (".sql",)):
        m = re.search(r"CREATE\s+TABLE\s+(?:\[?\w+\]?\.)?\[?(\w+)\]?", read(path), re.I)
        if m:
            table_names.add(m.group(1).lower())
    routine_names = {i[1].lower() for i in items}
    used_by = defaultdict(set)
    word = re.compile(r"[A-Za-z_]\w+")
    # EF function imports can have a different C# name than the stored procedure (e.g. X_Func -> X)
    alias = {}
    edmx = os.path.join(ROOT, EDMX) if EDMX else ""
    if edmx and os.path.isfile(edmx):
        for imp, fn in re.findall(r'FunctionImportName="(\w+)"\s+FunctionName="[\w.]*?\.(\w+)"', read(edmx)):
            if fn.lower() in routine_names:
                alias[imp.lower()] = fn.lower()
    for fp, txt in code_files():
        for w in set(word.findall(txt)):
            lw = w.lower()
            target = lw if lw in routine_names else alias.get(lw)
            if target:
                used_by[target].add(fp)
    callers_sql = defaultdict(set)
    for kind, name, p, params, tables in items:
        for t in tables:
            if t.lower() in routine_names and t.lower() != name.lower():
                callers_sql[t.lower()].add(name)
    for path in walk(dbroot, (".sql",)):
        txt = re.sub(r"--[^\n]*", "", read(path))
        m = rt_re.search(txt)
        if not m:
            continue
        for ex in re.findall(r"\bEXEC(?:UTE)?\s+(?:@\w+\s*=\s*)?(?:\[?dbo\]?\.)?\[?(\w+)\]?", txt, re.I):
            if ex.lower() in routine_names and ex.lower() != m.group(3).lower():
                callers_sql[ex.lower()].add(m.group(3))

    def link_obj(t):
        if t.lower() in routine_names:
            return f"[{t}](#{slug(prefix, t)})"
        if t.lower() in table_names:
            return f"[{t}]({table_page}#{slug(table_prefix, t)})"
        return t

    out = [f"# {title}", "", "Every stored procedure, function, view and trigger in the database project, extracted from source.",
           "",
           "- **Touches**: tables, views and functions this routine reads or writes (FROM / JOIN / INTO / UPDATE / MERGE). Each links to its definition.",
           "- **Called by (SQL)**: other routines that EXEC it or select from it.",
           "- **Used by (application)**: C# / Razor / JavaScript files that mention the routine by name (EF function import, `SqlQueryByProcName`, `ExecuteSqlCommand`, …).",
           "", anchor("index"), ""]
    for kind in ("PROCEDURE", "FUNCTION", "VIEW", "TRIGGER"):
        group = sorted([i for i in items if i[0] == kind], key=lambda i: i[1].lower())
        if group:
            out.append(f"- [{kind.title()}s ({len(group)})](#{slug('kind', kind)})")
    for kind in ("PROCEDURE", "FUNCTION", "VIEW", "TRIGGER"):
        group = sorted([i for i in items if i[0] == kind], key=lambda i: i[1].lower())
        if not group:
            continue
        out += ["", anchor(slug("kind", kind)), "", f"## {kind.title()}s ({len(group)})", "", BACK, "",
                "| Name | Parameters | Touches | Called by (SQL) | Used by (application) | File |", "| --- | --- | --- | --- | --- | --- |"]
        for _, name, p, params, tables in group:
            ps = ", ".join(f"{a} {b}" for a, b in params)
            touches = ", ".join(link_obj(t) for t in tables[:30]) + (" …" if len(tables) > 30 else "")
            callers = ", ".join(f"[{c}](#{slug(prefix, c)})" for c in sorted(callers_sql.get(name.lower(), []))[:15])
            users = sorted(used_by.get(name.lower(), []))
            ushow = ", ".join(f"`{u.split('/')[-1]}`" for u in users[:8]) + (f" (+{len(users) - 8})" if len(users) > 8 else "")
            out.append(f"| {anchor(slug(prefix, name))}**{name}** | {md_escape(ps)} | {touches} | {callers} | {ushow} | `{p}` |")
    write(fname, "\n".join(out) + "\n")
    return len(items)


# ---------------------------------------------------------------- config keys
def gen_config():
    out = ["# Configuration settings", "",
           "Every `appSettings` key and connection string name in each project's `Web.config` / `App.config`, "
           "with the source files that read it. **Values are not reproduced here**: several of these settings hold "
           "credentials or API keys, which belong in a secret store, not in documentation.", ""]
    code_files = [(rel(p), read(p)) for p in walk(ROOT, (".cs", ".cshtml"))]
    for cfg in sorted(p for p in walk(ROOT, (".config",)) if os.path.basename(p).lower() in ("web.config", "app.config")):
        p = rel(cfg)
        if "/Views/" in p or "/Areas/" in p:
            continue
        try:
            tree = ET.parse(cfg)
        except ET.ParseError:
            continue
        root = tree.getroot()
        project = p.split("/")[0]
        keys = [a.get("key") for a in root.findall("./appSettings/add") if a.get("key")]
        conns = [a.get("name") for a in root.findall("./connectionStrings/add") if a.get("name")]
        if not keys and not conns:
            continue
        out += [f"## {p}", ""]
        if conns:
            out += ["Connection strings: " + ", ".join(f"`{c}`" for c in conns), ""]
        out += ["| Key | Read by |", "| --- | --- |"]
        for k in keys:
            users = sorted({fp for fp, txt in code_files if fp.startswith(project + "/") and f'"{k}"' in txt})
            shown = ", ".join(f"`{u.split('/')[-1]}`" for u in users[:6]) + (f" (+{len(users) - 6} more)" if len(users) > 6 else "")
            out.append(f"| `{k}` | {shown or '_not referenced by name in code (framework or library setting)_'} |")
        out.append("")
    write("configuration.md", "\n".join(out) + "\n")


# ---------------------------------------------------------------- packages
def gen_packages():
    rows = defaultdict(set)
    for cfg in walk(ROOT, ("packages.config",)):
        project = rel(cfg).split("/")[0]
        for pkg in ET.parse(cfg).getroot().findall("package"):
            rows[(pkg.get("id"), pkg.get("version"))].add(project)
    out = ["# NuGet packages", "", "Every package listed in a `packages.config`, with the projects that use it.", "",
           "| Package | Version | Used by |", "| --- | --- | --- |"]
    for (pid, ver), projects in sorted(rows.items(), key=lambda r: r[0][0].lower()):
        out.append(f"| {pid} | {ver} | {', '.join(sorted(projects))} |")
    write("packages.md", "\n".join(out) + "\n")


if __name__ == "__main__":
    print("enums", gen_enums())
    print("actions", gen_controllers())
    for db in DATABASES:
        path = os.path.join(ROOT, db["path"])
        if not os.path.isdir(path):
            print("skip missing database project", path)
            continue
        print(db["name"], "tables", gen_tables(path, f"Database tables ({db['name']})", db["tables_page"]))
        print(db["name"], "routines", gen_routines(path, f"Stored procedures, functions and views ({db['name']})",
                                                   db["routines_page"], table_page=db["tables_page"]))
    gen_config()
    gen_packages()

