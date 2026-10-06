"""Every view, page, screen and UI component (.NET), with totals: what a user can see and how much of it there is.

Writes docs/reference/views-and-pages.md (anchors ui-…) and docs/agent/views.json:
  summary     totals by kind and by project; lines of markup and code-behind
  per kind    MVC views / partials / layouts (.cshtml, .vbhtml), Razor Pages (@page) and their handlers, Blazor components
              (routable or not), Web Forms pages / user controls / master pages, ASMX web services, ASHX handlers,
              WinForms forms and user controls, WPF / MAUI XAML windows, pages and user controls
  columns     route (from @page, or the MVC / Web Forms convention), model, layout / master page, code-behind, lines,
              and the controller action that renders an MVC view (by convention, linked when the method map has it)
The page name differs from aspnet-mvc-ssdt's views.md, so both can run.
"""
import json
import os
import re
from collections import Counter, defaultdict

from _scan import BACK, DOCS, ROOT, Methods, esc, esc_text, project_of, read, slug, walk, write_page
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

M = Methods()
UI_EXT = {".cshtml", ".vbhtml", ".razor", ".aspx", ".ascx", ".master", ".asmx", ".ashx", ".xaml"}
KIND_ORDER = ["MVC view", "MVC partial view", "MVC layout", "MVC view start / imports", "Razor Page", "Razor Pages partial / layout",
              "Blazor routable component", "Blazor component", "Blazor layout", "Web Forms page", "Web Forms user control",
              "Web Forms master page", "ASMX web service", "ASHX handler", "WinForms form", "WinForms user control",
              "XAML window", "XAML page", "XAML user control", "XAML other"]
GROUPS = [("ASP.NET MVC views", "ui-mvc", lambda k: k.startswith("MVC")),
          ("Razor Pages", "ui-razor-pages", lambda k: k.startswith("Razor Page")),
          ("Blazor components", "ui-blazor", lambda k: k.startswith("Blazor")),
          ("Web Forms, ASMX and ASHX", "ui-webforms", lambda k: k.startswith(("Web Forms", "ASMX", "ASHX"))),
          ("Windows Forms", "ui-winforms", lambda k: k.startswith("WinForms")),
          ("WPF / MAUI (XAML)", "ui-xaml", lambda k: k.startswith("XAML"))]
RX_PAGE = re.compile(r'^[ \t]*@page(?:[ \t]+"([^"]*)")?[ \t]*\r?$', re.M)  # the directive alone on its line (not @pager)
RX_MODEL = re.compile(r"^\s*@(?:model|ModelType)\s+([^\r\n]+)", re.M)
RX_INHERITS = re.compile(r"^\s*@inherits\s+([^\r\n]+)", re.M)
RX_LAYOUT = re.compile(r'\bLayout\s*=\s*"([^"]*)"')
RX_BLAZOR_LAYOUT = re.compile(r"^\s*@layout\s+([\w.]+)", re.M)
RX_BODY = re.compile(r"@RenderBody\(\)|@Body\b|\bLayoutComponentBase\b")
RX_DIRECTIVE = re.compile(r"<%@\s*(Page|Control|Master|WebService|WebHandler)\b([^%]*)%>", re.I)
RX_ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
RX_HANDLER = re.compile(r"\b(?:public|private|protected|internal)?\s*(?:async\s+)?[\w<>\[\],. ]+\s+On(Get|Post|Put|Delete|Patch)(\w*?)(?:Async)?\s*\(")
RX_WINFORM = re.compile(r"\bclass\s+(\w+)\s*(?:<[^>]*>)?\s*:\s*(?:global::)?([\w.]+)", re.M)
RX_VB_INHERITS = re.compile(r"^\s*(?:Partial\s+)?(?:Public\s+|Friend\s+)?(?:Partial\s+)?Class\s+(\w+)\s*\r?\n\s*Inherits\s+([\w.]+)", re.M | re.I)
RX_XAML_ROOT = re.compile(r"<(?!\?|!)([\w.:]+)[\s>]")
RX_XCLASS = re.compile(r'x:Class\s*=\s*"([^"]+)"')


RX_AREA_FOLDER = re.compile(r"(?i)(?:^|/)Areas/([^/]+)/")
RX_AREA_REG = re.compile(r"\bclass\s+(\w+)\s*:\s*(?:System\.Web\.Mvc\.)?AreaRegistration\b")
RX_AREA_NAME = re.compile(r"\bAreaName\b[^\"]{0,80}\"([^\"]+)\"", re.S)
RX_MAPROUTE = re.compile(r"\.MapRoute\(\s*(?:name\s*:\s*)?\"[^\"]*\"\s*,\s*(?:url\s*:\s*)?\"([^\"]*)\"")
RX_AREA_ATTR = re.compile(r"\[Area\(\s*\"([^\"]+)\"\s*\)\][\s\S]{0,400}?\bclass\s+(\w+)")
RX_MAP_AREA = re.compile(r"\bMapAreaControllerRoute\(\s*(?:name\s*:\s*)?\"[^\"]*\"\s*,\s*(?:areaName\s*:\s*)?\"([^\"]+)\"\s*,\s*(?:pattern\s*:\s*)?\"([^\"]*)\"")
RX_AREA_EXISTS = re.compile(r"\"([^\"]*\{area(?::exists)?[^}]*\}[^\"]*)\"")
# MVC 5 plugin areas: routes.MapRoute("n", "Plugins/X/{controller}/{action}", …).DataTokens["area"] = "X"
RX_AREA_TOKEN = re.compile(r"\.MapRoute\(\s*\"[^\"]*\"\s*,\s*\"([^\"]*)\"(?:(?!\.MapRoute\()[\s\S]){0,800}?\.DataTokens\[\s*\"area\"\s*\]\s*=\s*"
                           r"(?:\"([^\"]+)\"|([\w.]+))")
RX_CONST = re.compile(r"\b(?:const|static\s+readonly|static)\s+string\s+(\w+)\s*=>?\s*\"([^\"]+)\"")  # const, static readonly, static … =>
RX_CLASS = re.compile(r"\bclass\s+(\w+)")


def mvc_areas(items):
    """MVC / Razor Pages areas: the Areas/<Name> folders, AreaRegistration classes (MVC 5), [Area] attributes and
    MapAreaControllerRoute / {area} routes (ASP.NET Core), with what each area holds."""
    areas = {}

    def get(project, name):
        return areas.setdefault((project, name.lower()), {"project": project, "name": name, "registered": [], "routes": [],
                                                          "controllers": {}, "folder": None})
    generic_routes, proj_ctrls, token_areas, tokens, consts = [], defaultdict(dict), set(), [], {}
    for rp, ap in walk(exts={".cs", ".vb"}):
        t = read(ap)
        f = RX_AREA_FOLDER.search(rp)
        proj = project_of(rp)
        if not f and "Controller" in t:
            for c in re.findall(r"\bclass\s+(\w+Controller)\b", t):
                proj_ctrls[proj].setdefault(c, rp)
        if "string" in t:  # string constants, so DataTokens["area"] = Plugin.SystemName can be resolved
            classes = [(m.start(), m.group(1)) for m in RX_CLASS.finditer(t)]
            for m in RX_CONST.finditer(t):
                owner = next((n for s, n in reversed(classes) if s < m.start()), "")
                consts[(proj, f"{owner}.{m.group(1)}")] = m.group(2)  # Plugin.SystemName exists once per plugin project
                consts.setdefault(f"{owner}.{m.group(1)}", m.group(2))
        tokens += [(proj, m.group(1), m.group(2), m.group(3), rp, t.count("\n", 0, m.start()) + 1) for m in RX_AREA_TOKEN.finditer(t)]
        if f:
            get(proj, f.group(1))["folder"] = rp[:f.end()].rstrip("/")
            if re.search(r"(?i)/Controllers/", rp):
                for c in re.findall(r"\bclass\s+(\w+Controller)\b", t):
                    get(proj, f.group(1))["controllers"].setdefault(c, rp)
        if "Area" not in t and "{area" not in t:
            continue
        for m in RX_AREA_REG.finditer(t):
            n = RX_AREA_NAME.search(t, m.end())
            a = get(proj, n.group(1) if n else (f.group(1) if f else re.sub(r"AreaRegistration$", "", m.group(1))))
            a["registered"].append(f"AreaRegistration `{m.group(1)}` ({rp}:{t.count(chr(10), 0, m.start()) + 1})")
            a["routes"] += RX_MAPROUTE.findall(t, m.end())
        for m in RX_AREA_ATTR.finditer(t):
            a = get(proj, m.group(1))
            a["controllers"].setdefault(m.group(2), rp)
            if "[Area] attribute" not in a["registered"]:
                a["registered"].append("[Area] attribute")
        for m in RX_MAP_AREA.finditer(t):
            a = get(proj, m.group(1))
            a["registered"].append(f"MapAreaControllerRoute ({rp}:{t.count(chr(10), 0, m.start()) + 1})")
            a["routes"].append(m.group(2))
        generic_routes += [(r, rp) for r in RX_AREA_EXISTS.findall(t)]  # "{area:exists}/…": serves every area of the app
    for proj, template, literal, expr, rp, line in tokens:
        # a constant is resolved in its own project first; anything else (computed at run time) is shown as written
        name = literal or consts.get((proj, expr)) or consts.get(expr) or expr
        a = get(proj, name)
        if not any(r.startswith("route DataTokens") for r in a["registered"]):
            a["registered"].append(f'route DataTokens["area"] ({rp}:{line})')
        a["routes"].append(template)
        token_areas.add((proj, name.lower()))
    for i in items:
        f = RX_AREA_FOLDER.search(i["file"])
        if f:
            i["area"] = f.group(1)
            get(i["project"], f.group(1))["folder"] = i["file"][:f.end()].rstrip("/")
    eps = []
    p = os.path.join(DOCS, "agent", "endpoints.json")
    if os.path.exists(p):
        eps = json.load(open(p, encoding="utf-8"))
    out = []
    for (proj, _), a in sorted(areas.items()):
        mine = [i for i in items if i["project"] == proj and (i.get("area") or "").lower() == a["name"].lower()]
        if (proj, a["name"].lower()) in token_areas:  # a plugin project routed as one area: its own controllers and views
            mine += [i for i in items if i["project"] == proj and not i.get("area")]
            for c, rp in proj_ctrls[proj].items():
                a["controllers"].setdefault(c, rp)
        files = set(a["controllers"].values())
        a["actions"] = sum(1 for e in eps if e.get("file") in files)
        a["views"] = sum(1 for i in mine if i["kind"].startswith("MVC"))
        a["razor_pages"] = sum(1 for i in mine if i["kind"] == "Razor Page")
        a["screens"] = sum(1 for i in mine if i["kind"] in ("MVC view", "Razor Page"))
        a["generic_routes"] = sorted({r for r, rp in generic_routes if project_of(rp) == proj})
        if not (a["registered"] or a["controllers"] or mine):
            continue  # an "Areas" folder that holds no MVC / Razor Pages code
        if not a["registered"]:
            a["registered"].append("folder only (no registration found: check the start-up code)")
        a["controllers"] = dict(sorted(a["controllers"].items()))
        a["anchor"] = slug("ui-area", proj, a["name"])
        out.append(a)
    return out


def lines(p):
    try:
        with open(p, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def anchors(page):
    p = os.path.join(DOCS, "reference", page)
    return set(re.findall(r'<a id="([^"]+)"', open(p, encoding="utf-8").read())) if os.path.exists(p) else set()


def side(path, *suffixes):
    """First existing companion file (code-behind / designer), relative to ROOT."""
    for s in suffixes:
        if os.path.exists(os.path.join(ROOT, path + s)):
            return path + s
    return None


def mvc_route(parts):
    """Areas/<A>/Views/<C>/<V> or Views/<C>/<V> -> /A/C/V (None for Shared and special files)."""
    low = [p.lower() for p in parts]
    if "views" not in low:
        return None, None, None
    i = len(low) - 1 - low[::-1].index("views")
    rest = parts[i + 1:]
    area = parts[i - 1] if i >= 2 and low[i - 2] == "areas" else None
    if len(rest) != 2 or rest[0].lower() == "shared":
        return None, area, None
    ctrl, view = rest[0], os.path.splitext(rest[1])[0]
    return "/" + "/".join(x for x in (area, ctrl, view) if x), area, ctrl


def page_route(parts, template):
    """Razor Page route: an absolute @page template wins, else the path under Pages/ (Index -> folder)."""
    if template and template.startswith("/"):
        return template
    low = [p.lower() for p in parts]
    i = low.index("pages") if "pages" in low else -1
    segs = parts[i + 1:-1] + [os.path.splitext(parts[-1])[0]]
    if segs and segs[-1].lower() == "index":
        segs = segs[:-1]
    area = parts[low.index("areas") + 1] if "areas" in low and low.index("areas") + 1 < len(parts) else None
    base = "/" + "/".join(([area] if area else []) + segs)
    return (base.rstrip("/") + "/" + template if template else base) if base != "/" else ("/" + template if template else "/")


def main():
    comp = anchors("components.md")
    by_name = defaultdict(list)
    for a, m in M.data.items():
        by_name[m["name"].lower()].append(a)
    items = []

    def cls_link(name, file):
        if name and file:
            a = slug("cls", file, name.split(".")[-1])
            if a in comp:
                return f"[{esc(name.split('.')[-1])}](components.md#{a})"
        return f"`{esc(name)}`" if name else "—"

    def add(kind, path, **kw):
        kw.setdefault("lines", lines(os.path.join(ROOT, path)))
        cb = kw.get("code_behind")
        kw["code_lines"] = lines(os.path.join(ROOT, cb)) if cb else 0
        items.append(dict(kind=kind, file=path, project=project_of(path), name=os.path.splitext(os.path.basename(path))[0], **kw))

    for rp, ap in walk(exts=UI_EXT):
        ext = os.path.splitext(rp)[1].lower()
        parts = rp.split("/")
        base = os.path.basename(rp)
        text = read(ap)
        if ext in (".cshtml", ".vbhtml"):
            m = RX_PAGE.search(text)
            model = (RX_MODEL.search(text) or RX_INHERITS.search(text))
            model = model.group(1).strip().rstrip(";") if model else None
            layout = RX_LAYOUT.search(text)
            layout = layout.group(1) if layout else None
            special = base.lower().startswith(("_viewstart.", "_viewimports."))
            if m and not special:
                cb = side(rp, ".cs", ".vb")
                handlers = sorted({f"On{h[0]}{h[1]}" for h in RX_HANDLER.findall(read(os.path.join(ROOT, cb)))}) if cb else []
                add("Razor Page", rp, route=page_route(parts, m.group(1)), model=model, layout=layout, code_behind=cb, handlers=handlers)
            elif "pages" in [p.lower() for p in parts] and "views" not in [p.lower() for p in parts]:
                add("MVC view start / imports" if special else "Razor Pages partial / layout", rp, model=model, layout=layout)
            else:
                route, area, ctrl = mvc_route(parts)
                # no Views/<Controller>/<View> route (Shared, EditorTemplates, DisplayTemplates, Components, e-mail templates):
                # rendered inside another view, so not a screen
                kind = ("MVC view start / imports" if special else "MVC layout" if RX_BODY.search(text)
                        else "MVC partial view" if base.startswith("_") or not route else "MVC view")
                action = None
                if kind == "MVC view" and ctrl:
                    hits = by_name.get(f"{ctrl}controller.{os.path.splitext(base)[0]}".lower(), [])
                    action = hits[0] if hits else None
                add(kind, rp, route=route if kind == "MVC view" else None, area=area, model=model, layout=layout, action=action)
        elif ext == ".razor":
            if base.lower() == "_imports.razor":
                continue
            routes = [r or "(no template)" for r in RX_PAGE.findall(text)]
            lay = RX_BLAZOR_LAYOUT.search(text)
            kind = "Blazor layout" if RX_BODY.search(text) else "Blazor routable component" if routes else "Blazor component"
            add(kind, rp, route=", ".join(routes) or None, layout=lay.group(1) if lay else None, code_behind=side(rp, ".cs"),
                model=(RX_INHERITS.search(text).group(1).strip() if RX_INHERITS.search(text) else None))
        elif ext in (".aspx", ".ascx", ".master", ".asmx", ".ashx"):
            d = RX_DIRECTIVE.search(text)
            attrs = {k.lower(): v for k, v in RX_ATTR.findall(d.group(2))} if d else {}
            cb = (attrs.get("codebehind") or attrs.get("codefile") or "").replace("\\", "/")
            proj = project_of(rp)
            if cb.startswith("~/"):  # "~/" is the web application root, i.e. the project folder
                cb = (cb[2:] if proj == "." else f"{proj}/{cb[2:]}")
            elif cb:
                cb = "/".join(parts[:-1] + cb.split("/"))
            if not cb or not os.path.exists(os.path.join(ROOT, cb)):
                cb = side(rp, ".cs", ".vb")
            kind = {".aspx": "Web Forms page", ".ascx": "Web Forms user control", ".master": "Web Forms master page",
                    ".asmx": "ASMX web service", ".ashx": "ASHX handler"}[ext]
            route = "/" + rp[len(proj) + 1:] if ext in (".aspx", ".asmx", ".ashx") and proj != "." else ("/" + rp if ext in (".aspx", ".asmx", ".ashx") else None)
            add(kind, rp, route=route, layout=attrs.get("masterpagefile"), code_behind=cb,
                model=attrs.get("inherits") or attrs.get("class") or attrs.get("itemtype"), title=attrs.get("title"))
        elif ext == ".xaml":
            body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
            r = RX_XAML_ROOT.search(body)
            root = r.group(1).split(":")[-1] if r else ""
            if root in ("ResourceDictionary", "Application", "Styles", "Style"):
                continue
            kind = ("XAML window" if root.endswith("Window") else "XAML page" if root.endswith(("Page", "Shell"))
                    else "XAML user control" if root.endswith(("UserControl", "ContentView")) else "XAML other")
            xc = RX_XCLASS.search(body)
            add(kind, rp, model=xc.group(1) if xc else None, root=root, code_behind=side(rp, ".cs", ".vb"))

    # WinForms: classes deriving from Form / UserControl (directly or through another form of this code base)
    bases, known = {}, {}
    for rp, ap in walk(exts={".cs", ".vb"}):
        if rp.lower().endswith((".xaml.cs", ".xaml.vb")):  # WPF / MAUI code-behind: already listed with its .xaml
            continue
        t = read(ap)
        winforms = "System.Windows.Forms" in t or side(os.path.splitext(rp)[0], ".Designer.cs", ".designer.cs", ".Designer.vb")
        for name, b in RX_WINFORM.findall(t) + RX_VB_INHERITS.findall(t):
            b0 = b.split(".")[-1]
            bases.setdefault(name, (b0, rp))
            if b0 in ("Form", "UserControl") and (winforms or b.startswith("System.Windows.Forms.")):
                known[name] = "WinForms form" if b0 == "Form" else "WinForms user control"
    changed = True
    while changed:  # forms deriving from a base form of this code base
        changed = False
        for name, (b0, rp) in bases.items():
            if name not in known and b0 in known:
                known[name] = known[b0]
                changed = True
    derived_from = {b0 for n, (b0, _) in bases.items() if n in known}
    for name, (b0, rp) in sorted(bases.items(), key=lambda kv: kv[1][1]):
        if name in ("Form", "UserControl") or name not in known:
            continue
        if any(i["file"] == rp and i["kind"].startswith("WinForms") for i in items):
            continue
        add(known[name], rp, model=name, layout=b0 if b0 not in ("Form", "UserControl") else None,
            code_behind=side(os.path.splitext(rp)[0], ".Designer.cs", ".designer.cs", ".Designer.vb"), base=name in derived_from)
        items[-1]["name"] = name

    for i in items:
        i["anchor"] = slug("ui", i["file"])
    areas = mvc_areas(items)
    kinds = Counter(i["kind"] for i in items)
    out = ["# Views and pages", "",
           "Every screen, page, view and UI component in the code, by technology, with totals. Routes come from `@page` or "
           "the framework convention (MVC: `/Area/Controller/Action`; Web Forms: the file path); custom routes in "
           "`RouteConfig` / `MapControllerRoute` / attribute routes are in the "
           + ("[endpoints](endpoints.md) reference." if os.path.exists(os.path.join(DOCS, "reference", "endpoints.md")) else "endpoint reference (generic-api)."), "",
           '<a id="index"></a>', "", "- [Totals](#ui-totals)", "- [By project](#ui-projects)"] + (["- [MVC areas](#ui-areas)"] if areas else [])
    out += [f"- [{t}](#{a})" for t, a, f in GROUPS if any(f(k) for k in kinds)]
    screens = sum(1 for i in items if i["kind"] in ("MVC view", "Razor Page", "Blazor routable component", "Web Forms page",
                                                     "WinForms form", "XAML window", "XAML page") and not i.get("base"))
    out += ["", '<a id="ui-totals"></a>', "", "## Totals", "", BACK, "",
            f"{len(items)} UI files: **{screens} screens** a user can open (MVC views with an action folder, Razor Pages, routable "
            f"Blazor components, Web Forms pages, forms, XAML windows and pages) and {len(items) - screens} partials, layouts, "
            f"components, controls and handlers. Markup {sum(i['lines'] for i in items):,} lines; code-behind "
            f"{sum(i['code_lines'] for i in items):,} lines.", "",
            "| Kind | Files | Lines (markup / code-behind) |", "| --- | --- | --- |"]
    for k in sorted(kinds, key=lambda k: KIND_ORDER.index(k) if k in KIND_ORDER else 99):
        ks = [i for i in items if i["kind"] == k]
        out.append(f"| {k} | {kinds[k]} | {sum(i['lines'] for i in ks):,} / {sum(i['code_lines'] for i in ks):,} |")
    proj = defaultdict(Counter)
    for i in items:
        proj[i["project"]][i["kind"]] += 1
    out += ["", '<a id="ui-projects"></a>', "", "## By project", "", BACK, "", "| Project | Files | Breakdown |", "| --- | --- | --- |"]
    for p in sorted(proj, key=lambda p: (-sum(proj[p].values()), p)):
        out.append(f"| `{esc(p)}` | {sum(proj[p].values())} | " + ", ".join(f"{k} {n}" for k, n in sorted(proj[p].items(), key=lambda kv: KIND_ORDER.index(kv[0]) if kv[0] in KIND_ORDER else 99)) + " |")

    if areas:
        out += ["", '<a id="ui-areas"></a>', "", "## MVC areas", "", BACK, "",
                "Areas split an MVC / Razor Pages application into sections with their own controllers, views and routes "
                "(`/<Area>/<Controller>/<Action>`). Found from the `Areas/<Name>` folders, `AreaRegistration` classes (MVC 5), "
                "`[Area]` attributes and `MapAreaControllerRoute` / `{area}` route templates (ASP.NET Core).", "",
                "| Area | Project | Registered by | Route templates | Controllers | Actions | Views | Razor Pages | Screens |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for ar in areas:
            out.append(f'| <a id="{ar["anchor"]}"></a>**{esc(ar["name"])}** | `{esc(ar["project"])}` | {esc_text("; ".join(ar["registered"]))} | '
                       f'{", ".join("`" + esc(r) + "`" for r in dict.fromkeys(ar["routes"] + ar["generic_routes"])) or "default convention"} | '
                       f'{", ".join("`" + esc(c) + "`" for c in ar["controllers"]) or "—"} | {ar["actions"] if os.path.exists(os.path.join(DOCS, "agent", "endpoints.json")) else "?"} | '
                       f'{ar["views"]} | {ar["razor_pages"]} | {ar["screens"]} |')
    for title, a, f in GROUPS:
        rows = sorted((i for i in items if f(i["kind"])), key=lambda i: (i["project"], KIND_ORDER.index(i["kind"]) if i["kind"] in KIND_ORDER else 99, i["file"].lower()))
        if not rows:
            continue
        out += ["", f'<a id="{a}"></a>', "", f"## {title}", "", BACK, "",
                "| Kind | File | Route | Model / class | Layout / master / base | Code-behind | Lines | Notes |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for i in rows:
            notes = []
            if i.get("base"):
                notes.append("base class of other forms / controls (not counted as a screen)")
            if i.get("action"):
                notes.append("rendered by " + M.link(i["action"]))
            if i.get("handlers"):
                notes.append("handlers: " + ", ".join(f"`{h}`" for h in i["handlers"]))
            if i.get("title"):
                notes.append(f"title: {esc_text(i['title'])}")
            if i.get("root") and i["kind"] == "XAML other":
                notes.append(f"root: `{esc(i['root'])}`")
            model = cls_link(i.get("model"), i.get("code_behind") or i["file"]) if i.get("model") else "—"
            out.append(f'| <a id="{i["anchor"]}"></a>{i["kind"]} | `{esc(i["file"])}` | {esc_text(i.get("route") or "—")} | {model} | '
                       f'{esc_text(i.get("layout") or "—")} | {("`" + esc(os.path.basename(i["code_behind"])) + "`") if i.get("code_behind") else "—"} | '
                       f'{i["lines"]}{" + " + str(i["code_lines"]) if i["code_lines"] else ""} | {"; ".join(notes)} |')
    write_page("views-and-pages.md", out)

    agent = os.path.join(DOCS, "agent")
    os.makedirs(agent, exist_ok=True)
    open(os.path.join(agent, "views.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(
        {"totals": dict(kinds), "screens": screens, "items": items, "areas": areas}, ensure_ascii=False, separators=(",", ":")))
    stat("views", ui_files=len(items), screens=screens, areas=len(areas),  # plus one count per kind: mvc_view, web_forms_page ...
         **{slug(k).replace("-", "_"): n for k, n in kinds.items()})
    print(f"views-and-pages: {len(items)} UI files, {screens} screens, {len(areas)} MVC areas ("
          + ", ".join(f"{k} {n}" for k, n in kinds.most_common()) + ")")


if __name__ == "__main__":
    main()
