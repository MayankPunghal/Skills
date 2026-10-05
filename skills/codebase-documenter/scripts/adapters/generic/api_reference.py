"""API reference: every HTTP endpoint the code declares, with verb, route, handler, parameters and auth.

Writes docs/reference/endpoints.md (anchors ep-<verb>-<route>, tag [[ep:GET /api/orders/{id}]]).
Recognises: ASP.NET Core / Web API controllers (attribute routes, [controller] / [action] tokens, class route prefix,
[Authorize] / [AllowAnonymous]), conventional MVC actions (public controller methods without verb attributes,
listed as ANY /{controller}/{action}), minimal APIs (MapGet ... with MapGroup prefixes), Express / Koa / Fastify style
routers, NestJS, Flask, FastAPI, Django urls.py, Spring (@RequestMapping + @GetMapping ...), Go (net/http, gin, chi,
echo) and OpenAPI / Swagger files (JSON, simple YAML). Handlers link to the method map when it exists.
Options (adapter_options.generic-api): conventional_mvc (default true), skip_regex.
"""
import json
import os
import re
from collections import Counter, defaultdict

from _scan import BACK, DOCS, Methods, esc, esc_text, line_at, options, project_of, read, slug, walk, write_page

OPT = options("generic-api")
CONVENTIONAL = OPT.get("conventional_mvc", True)
VERBS = ("get", "post", "put", "delete", "patch")
M = Methods()
rows = []


def add(verb, route, framework, path, line, handler=None, params=None, auth="", note="", inline_params=None):
    route = "/" + re.sub(r"/{2,}", "/", route.strip()).lstrip("/~") if route is not None else "/"
    if handler is None:  # attribute / decorator style: the method declared just below
        handler = M.next_after(path, line)
    registered = None
    if handler is False:  # inline or registration style: no single handler method
        handler, registered = None, M.enclosing(path, line)
    if params is None:
        params = (M.data.get(handler) or {}).get("params")
    if params is None and inline_params is not None:
        params = [p.strip() for p in inline_params.split(",") if p.strip()]
    rows.append({"verb": verb.upper(), "route": route, "framework": framework, "file": path, "line": line,
                 "handler": handler, "registered_in": registered, "params": params or [], "auth": auth, "note": note})


def lambda_params(text):
    m = re.search(r"^[^;]{0,300}?(?:\(([^()]*)\)\s*=>|function\s*\w*\s*\(([^()]*)\)|func\s*\(([^()]*)\))", text, re.S)
    return next((g for g in m.groups() if g is not None), None) if m else None


# ---------------------------------------------------------------- .NET
CS_CLASS = re.compile(r"((?:\s*\[[^\]]+\]\s*)*)\s*(?:public\s+|internal\s+)?(?:sealed\s+|abstract\s+|partial\s+)*class\s+(\w+)(?:\s*\([^)]*\))?\s*(?::\s*([^{]+))?\{", re.S)
CS_METHOD = re.compile(r"((?:[ \t]*\[[^\]\n]+\][ \t]*\r?\n)*)[ \t]*public\s+(?!class\b)(?:(?:async|virtual|override|new|sealed)\s+)*[\w<>\[\],.?() ]+?\s+(\w+)\s*(?:<[^>]*>)?\s*\(")
HTTP_ATTR = re.compile(r"\[(?:\w+,\s*)*Http(Get|Post|Put|Delete|Patch)(?:\s*\(\s*(?:template:\s*)?\"([^\"]*)\"[^)]*\))?", re.I)


def attr_route(attrs):
    m = re.search(r"\[(?:\w+,\s*)*Route(?:Prefix)?\s*\(\s*(?:template:\s*)?\"([^\"]*)\"", attrs)
    return m.group(1) if m else None


def auth_of(attrs):
    if re.search(r"\[(?:\w+,\s*)*AllowAnonymous", attrs):
        return "anonymous"
    m = re.search(r"\[(?:\w+,\s*)*Authorize(?:\s*\(([^)]*)\))?", attrs)
    return ("authorize" + (f" ({m.group(1).strip()})" if m.group(1) else "")) if m else ""


def dotnet(path, text):
    classes = list(CS_CLASS.finditer(text))
    for k, c in enumerate(classes):
        name, bases, cattrs = c.group(2), c.group(3) or "", c.group(1) or ""
        is_api = "ApiController" in cattrs or "ControllerBase" in bases or "ApiController" in bases
        if not (name.endswith("Controller") or is_api):
            continue
        start, end = c.end(), (classes[k + 1].start() if k + 1 < len(classes) else len(text))
        body = text[start:end]
        ctl = re.sub(r"Controller$", "", name)
        area = re.search(r"\[Area\(\s*\"([^\"]+)\"", cattrs)
        prefix = attr_route(cattrs) or ""
        cauth = auth_of(cattrs)
        for m in CS_METHOD.finditer(body):
            attrs, meth = m.group(1) or "", m.group(2)
            if meth in (name, "Dispose") or "NonAction" in attrs:
                continue
            line = line_at(text, start + m.start(2))
            verbs = HTTP_ATTR.findall(attrs)
            mroute = attr_route(attrs)
            auth = auth_of(attrs) or cauth
            handler = M.next_after(path, line, within=0) or M.enclosing(path, line)

            def tokens(r):
                return r.replace("[controller]", ctl).replace("[action]", meth).replace("[area]", area.group(1) if area else "")
            conventional = f"{('/' + area.group(1)) if area else ''}/{ctl}/{meth}"
            if verbs or mroute is not None:
                for verb, tmpl in (verbs or [("ANY", "")]):
                    t = tmpl or mroute or ""
                    if not t and not prefix and not is_api:  # [HttpPost] on an MVC action: a verb filter, conventional route
                        add(verb, conventional, "ASP.NET MVC (conventional)", path, line, handler, auth=auth,
                            note="route from the default {controller}/{action} convention")
                        continue
                    full = t if t.startswith(("/", "~/")) else f"{prefix}/{t}" if prefix else t
                    add(verb, tokens(full), "ASP.NET", path, line, handler, auth=auth)
            elif CONVENTIONAL and not is_api and not re.search(r"\boverride\b", m.group(0)) and re.search(
                    r"ActionResult|IActionResult|Task<|JsonResult|ViewResult|\bstring\b|\bvoid\b", m.group(0)):
                add("ANY", conventional, "ASP.NET MVC (conventional)", path, line,
                    handler, auth=auth, note="route from the default {controller}/{action} convention")
    groups = {g.group(1): g.group(2) for g in re.finditer(r"(\w+)\s*=\s*[\w.]+\.MapGroup\(\s*\"([^\"]*)\"", text)}
    for m in re.finditer(r"(\w+)\s*\.\s*Map(Get|Post|Put|Delete|Patch|Methods|Fallback)\s*\(\s*\"([^\"]*)\"", text):
        recv, verb, route = m.group(1), m.group(2), m.group(3)
        line = line_at(text, m.start())
        handler_text = text[m.end():m.end() + 400]
        mg = re.match(r"\s*,\s*([\w.]+)\s*\)", handler_text)
        add("ANY" if verb in ("Methods", "Fallback") else verb, f"{groups.get(recv, '')}/{route}", "ASP.NET minimal API", path, line,
            handler=False, inline_params=lambda_params(handler_text),
            note=f"handler {mg.group(1)}" if mg else f"registered in {M.data.get(M.enclosing(path, line), {}).get('name', 'top-level code')}")


# ---------------------------------------------------------------- JS / TS
def javascript(path, text):
    for m in re.finditer(r"\b(app|router|server|api|fastify|\w+Router|\w+Routes)\s*\.\s*(get|post|put|delete|patch|all)\s*\(\s*(['\"`])([^'\"`]+)\3", text):
        line = line_at(text, m.start())
        add("ANY" if m.group(2) == "all" else m.group(2), m.group(4), "Express-style", path, line, handler=False,
            inline_params=lambda_params(text[m.end():m.end() + 400]))
        rows[-1]["note"] = f"registered in {M.data.get(M.enclosing(path, line), {}).get('name', 'module scope')}"
    ctl = re.search(r"@Controller\(\s*['\"]?([^'\")]*)['\"]?\s*\)", text)
    if ctl:
        for m in re.finditer(r"@(Get|Post|Put|Delete|Patch|All)\(\s*(?:['\"]([^'\"]*)['\"])?\s*\)", text):
            line = line_at(text, m.start())
            auth = "guarded" if re.search(r"@UseGuards", text[max(0, m.start() - 200):m.start()]) else ""
            add(m.group(1), f"{ctl.group(1)}/{m.group(2) or ''}", "NestJS", path, line, auth=auth)


# ---------------------------------------------------------------- Python
def python(path, text):
    for m in re.finditer(r"@(\w+)\.route\(\s*['\"]([^'\"]+)['\"]([^)]*)\)", text):
        methods = re.findall(r"['\"](\w+)['\"]", (re.search(r"methods\s*=\s*\[([^\]]*)\]", m.group(3)) or [None, ""])[1]) or ["GET"]
        for v in methods:
            add(v, m.group(2), "Flask", path, line_at(text, m.start()))
    for m in re.finditer(r"@(\w+)\.(get|post|put|delete|patch)\(\s*['\"]([^'\"]+)['\"]", text):
        prefix = re.search(re.escape(m.group(1)) + r"\s*=\s*APIRouter\([^)]*prefix\s*=\s*['\"]([^'\"]+)['\"]", text)
        add(m.group(2), (prefix.group(1) if prefix else "") + m.group(3), "FastAPI / Flask", path, line_at(text, m.start()))
    if path.endswith("urls.py"):
        for m in re.finditer(r"\b(?:re_)?path\(\s*r?['\"]([^'\"]*)['\"]\s*,\s*([\w.]+(?:\.as_view\(\))?)", text):
            add("ANY", m.group(1), "Django", path, line_at(text, m.start()), handler=False, note=f"view {m.group(2)}")


# ---------------------------------------------------------------- Java / Kotlin
def spring(path, text):
    cls = re.search(r"@RequestMapping\(\s*(?:value\s*=\s*|path\s*=\s*)?\"([^\"]*)\"[^)]*\)\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:public\s+)?(?:class|interface)", text)
    prefix = cls.group(1) if cls else ""
    for m in re.finditer(r"@(Get|Post|Put|Delete|Patch)Mapping(?:\(\s*(?:value\s*=\s*|path\s*=\s*)?\"([^\"]*)\"[^)]*\))?", text):
        add(m.group(1), f"{prefix}/{m.group(2) or ''}", "Spring", path, line_at(text, m.start()))
    for m in re.finditer(r"@RequestMapping\(([^)]*method\s*=\s*RequestMethod\.(\w+)[^)]*)\)", text):
        route = re.search(r"\"([^\"]*)\"", m.group(1))
        add(m.group(2), f"{prefix}/{route.group(1) if route else ''}", "Spring", path, line_at(text, m.start()))


# ---------------------------------------------------------------- Go
def golang(path, text):
    for m in re.finditer(r"\b\w+\.(HandleFunc|Handle|GET|POST|PUT|DELETE|PATCH|Get|Post|Put|Delete|Patch|Any)\(\s*\"([^\"]+)\"", text):
        verb = m.group(1).upper()
        route = m.group(2)
        if verb in ("HANDLEFUNC", "HANDLE"):
            vm = re.match(r"(GET|POST|PUT|DELETE|PATCH)\s+(.+)", route)  # Go 1.22 "GET /path" patterns
            verb, route = (vm.group(1), vm.group(2)) if vm else ("ANY", route)
        line = line_at(text, m.start())
        add(verb, route, "Go", path, line, handler=False, inline_params=lambda_params(text[m.end():m.end() + 300]),
            note=f"registered in {M.data.get(M.enclosing(path, line), {}).get('name', 'package scope')}")


# ---------------------------------------------------------------- OpenAPI
def openapi(path, text):
    if path.endswith(".json"):
        try:
            d = json.loads(text)
        except ValueError:
            return
        for route, ops in (d.get("paths") or {}).items():
            for verb, op in (ops or {}).items():
                if verb in VERBS and isinstance(op, dict):
                    add(verb, route, "OpenAPI", path, 1, handler=False, params=[p.get("name", "") for p in op.get("parameters", []) if isinstance(p, dict)],
                        note=op.get("summary") or op.get("operationId") or "")
        return
    inside, route = False, None
    for k, line in enumerate(text.splitlines(), 1):
        if re.match(r"^paths:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            inside = False
        if not inside:
            continue
        m = re.match(r"^  (['\"]?/[^:]*?['\"]?):\s*$", line)
        if m:
            route = m.group(1).strip("'\"")
            continue
        m = re.match(r"^    (get|post|put|delete|patch):\s*$", line)
        if m and route:
            add(m.group(1), route, "OpenAPI", path, k, handler=False, params=[])


def main():
    skip = re.compile(OPT["skip_regex"]) if OPT.get("skip_regex") else None
    for path, full in walk(exts={".cs", ".vb", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".py", ".java", ".kt", ".go", ".json", ".yaml", ".yml"}):
        if skip and skip.search(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        base = os.path.basename(path).lower()
        if ext in (".json", ".yaml", ".yml"):
            if re.match(r"(openapi|swagger)", base):
                openapi(path, read(full))
            continue
        text = read(full)
        if ext in (".cs", ".vb") and ("Controller" in text or ".Map" in text):
            dotnet(path, text)
        elif ext in (".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx"):
            javascript(path, text)
        elif ext == ".py":
            python(path, text)
        elif ext in (".java", ".kt"):
            spring(path, text)
        elif ext == ".go":
            golang(path, text)
    if not rows:
        print("endpoints: none found")
        return
    by_proj = defaultdict(list)
    for r in rows:
        by_proj[project_of(r["file"])].append(r)
    fw = Counter(r["framework"] for r in rows)
    out = ["# Endpoints", "",
           f"Every HTTP endpoint declared in the code ({len(rows)}: " + ", ".join(f"{k} {v}" for k, v in fw.most_common()) + "). "
           "Routes are read from attributes, decorators and route registrations; anything built at run time (reflection, "
           "convention plug-ins, gateways) is not visible here. Auth shows what the code declares on the endpoint or its "
           "class; global filters and middleware apply on top.", "", '<a id="index"></a>', "",
           "| Project | Endpoints |", "| --- | ---: |"]
    out += [f"| [{esc_text(p)}](#{slug('area', p)}) | {len(v)} |" for p, v in sorted(by_proj.items())]
    for p, rs in sorted(by_proj.items()):
        out += ["", f'<a id="{slug("area", p)}"></a>', "", f"## {p}", "", BACK, "",
                "| Endpoint | Handler | Parameters | Auth | Source |", "| --- | --- | --- | --- | --- |"]
        for r in sorted(rs, key=lambda r: (r["route"].lower(), r["verb"])):
            h = M.link(r["handler"]) or esc_text(r["note"]) or "—"
            if r["handler"] and r["note"]:
                h += f" · {esc_text(r['note'])}"
            params = ", ".join(f"`{esc(x)}`" for x in r["params"]) or "—"
            out.append(f'| <a id="{slug("ep", r["verb"] + " " + r["route"])}"></a>**{r["verb"]} {esc_text(r["route"])}** | {h} | {params} | '
                       f'{esc_text(r["auth"]) or "—"} | `{esc(r["file"])}:{r["line"]}` ({r["framework"]}) |')
    write_page("endpoints.md", out)
    os.makedirs(os.path.join(DOCS, "agent"), exist_ok=True)
    for r in rows:
        r["anchor"] = slug("ep", r["verb"] + " " + r["route"])
    open(os.path.join(DOCS, "agent", "endpoints.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"endpoints: {len(rows)} in {len(by_proj)} projects (" + ", ".join(f"{k} {v}" for k, v in fw.most_common()) + ")")


if __name__ == "__main__":
    main()
