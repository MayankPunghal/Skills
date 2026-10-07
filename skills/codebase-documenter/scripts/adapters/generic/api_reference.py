"""API reference: every HTTP endpoint the code declares, with verb, route, handler, parameters and auth.

Writes docs/reference/endpoints.md (anchors ep-<verb>-<route>, tag [[ep:GET /api/orders/{id}]]).
Recognises: ASP.NET Core / Web API controllers (attribute routes, [controller] / [action] tokens, class route prefix,
[Authorize] / [AllowAnonymous]), conventional MVC actions (public controller methods without verb attributes,
listed as ANY /{controller}/{action}), minimal APIs (MapGet ... with MapGroup prefixes), Express / Koa / Fastify style
routers, NestJS, Flask, FastAPI, Django urls.py, Spring (@RequestMapping + @GetMapping ...), Go (net/http, gin, chi,
echo) and OpenAPI / Swagger files (JSON, simple YAML). Handlers link to the method map when it exists.
Every public instance method of an MVC controller is listed (MVC routes it whatever it returns); the ones that do not return
an action result are marked "helper exposed as action". Attributes are read after comments are blanked, so //[HttpPost] does
not count. Auth is the EFFECTIVE authorisation: method attributes, else the controller or a base controller, else global
filters (GlobalFilters / FilterConfig / AddMvc options), with the project's own attributes that derive from AuthorizeAttribute
or an authorisation / authentication filter (any of their base types; anti-forgery filters excluded). The anti-forgery
(CSRF) filter is shown beside it the same way (method, controller, base controller, global; the framework's and the
project's own classes named like one, noting when such a class checks the HTTP verb). A "Security review
candidates" section lists what a reviewer must confirm: authorisation attributes on methods MVC never runs as actions,
admin-looking actions (or most of a controller) missing the role attribute siblings carry, admin-area actions without a role
filter, state-changing actions that accept GET, anonymous state-changing actions, test / temporary actions, user-id
parameters without a user filter.
Options (adapter_options.generic-api): conventional_mvc (default true), skip_regex, user_filters / role_filters (attribute
names that check the user / the role, when they are not recognisable from their base class), sibling_role_min (default 2),
test_name_ignore (regexes of action names that only look like test code).
"""
import bisect
import json
import os
import re
import sys
from collections import Counter, defaultdict

from _scan import BACK, DOCS, Methods, esc, esc_text, global_filters, line_at, options, project_of, read, slug, walk, write_page
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from code_text import block_close, code_only, strip_comments, strip_web_comments  # noqa: E402

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
CS_CLASS = re.compile(r"((?:\[[^\]]+\]\s*)*)(?<![\w.])(?:public\s+|internal\s+)?(?:sealed\s+|abstract\s+|partial\s+)*class\s+(\w+)(?:\s*\([^)]*\))?\s*(?::\s*([^{]+))?\{", re.S)
# the attribute block may hold blank lines: a commented-out attribute between two others is blanked by strip_comments
CS_METHOD = re.compile(r"(?m)^((?:[ \t]*(?:\[[^\]\n]+\][ \t]*)*\r?\n)*[ \t]*(?:\[[^\]\n]+\][ \t]*)*)public\s+(?!class\b)(?:(?:async|virtual|override|new|sealed)\s+)*[\w<>\[\],.?() ]+?\s+(\w+)\s*(?:<[^>]*>)?\s*\(")
HTTP_ATTR = re.compile(r"\[(?:\w+,\s*)*Http(Get|Post|Put|Delete|Patch)(?:\s*\(\s*(?:template:\s*)?\"([^\"]*)\"[^)]*\))?", re.I)


def sig_params(text, open_paren):
    """Parameters of the signature whose "(" is at open_paren, read from the text itself (overloads share one method-map
    entry, so Create() and [HttpPost] Create(CouponForm form) would otherwise both show the first one's parameters)."""
    depth, out, cur, quote = 0, [], "", ""
    for ch in text[open_paren:open_paren + 2000]:
        if quote:  # inside a default value's string / char literal: brackets there do not nest
            cur += ch
            quote = "" if ch == quote and not cur.endswith("\\" + ch) else quote
            continue
        if ch in "\"'" and depth >= 1:
            quote = ch
            cur += ch
            continue
        depth += (ch in "(<[{") - (ch in ")>]}")
        if depth == 0:
            break
        if ch == "," and depth == 1:
            out.append(cur)
            cur = ""
        elif depth >= 1 and not (depth == 1 and ch == "("):
            cur += ch
    out.append(cur)
    return [p for p in (re.sub(r"\[[^\]]*\]", "", re.sub(r"\s+", " ", x)).strip() for x in out) if p]


def attr_route(attrs):
    m = re.search(r"\[(?:\w+,\s*)*Route(?:Prefix)?\s*\(\s*(?:template:\s*)?\"([^\"]*)\"", attrs)
    return m.group(1) if m else None


AUTH_BASES = {"AuthorizeAttribute", "AuthorizationFilterAttribute", "IAuthorizationFilter", "IAsyncAuthorizationFilter",
              "AuthorizeFilter", "IAuthorizationRequirement", "IAuthenticationFilter", "IAsyncAuthenticationFilter"}
AUTH_ATTRS = {"Authorize"}           # plus the project's own authorisation attributes (found in main)
CLASS_ATTRS = {}                     # controller class -> (attribute block, base class), for inherited [Authorize]
# anti-forgery (CSRF) filters: the framework's, plus the project's own classes named like one (found in prepass)
CSRF_ATTRS = {"validateantiforgerytoken", "autovalidateantiforgerytoken"}
CSRF_SKIPS_GET = {"autovalidateantiforgerytoken": "framework: validates unsafe verbs only"}  # filter -> where it checks the verb
CSRF_NAME = re.compile(r"(?i)anti_?forgery|csrf|xsrf")
GLOBAL = []                          # global filters [(name, file, line)]
FINDINGS = []                        # security review candidates
CONTROLLERS = {}                     # class -> [{"meth", "auth", "verbs", "params", "file", "line", "action": bool}]
# return types that make a method a real action: any ...Result, HttpResponseMessage, string (content), bare Task (empty result)
ACTION_RESULT = re.compile(r"\b(?:\w*Result|HttpResponseMessage|string)\b(?!\s*\[)|\bTask\s*$|\bTask\s+\w+\s*$")
STATE_CHANGE = re.compile(r"^(Update|Delete|Save|Set|Add|Remove|Reset|Insert|Create|Edit|Change|Cancel|Approve|Reject|Disable|"
                          r"Enable|Activate|Deactivate|Upload|Import|Send|Assign|Grant|Revoke|Clear|Purge|Restore|Move|Merge|Post)(?=[A-Z_]|$)")
TEST_ANYWHERE = {"test", "debug", "dummy", "sandbox"}   # a camel-case word anywhere in the name ("SaveDebug", "Test_Upload")
TEST_EDGE = {"temp", "tmp", "fake", "demo"}             # only as the first or last word: "CreateUserWithTempPwd" is business
NON_ACTION = re.compile(r"(?m)^((?:[ \t]*(?:\[[^\]\n]+\][ \t]*)*\r?\n)*[ \t]*(?:\[[^\]\n]+\][ \t]*)*)(?:(private|protected|internal)\s+|public\s+(?=(?:\w+\s+)*static\b))"
                        r"(?:(?:static|async|virtual|override|new|sealed)\s+)*[\w<>\[\],.?() ]+?\s+(\w+)\s*(?:<[^>]*>)?\s*\(")


ADMIN_NAME = re.compile(r"Admin|Authori[sz]ation|Role|Permission|Privilege|Impersonat", re.I)


def role_like(auth):
    """True when an auth label restricts more than "any signed-in user": Authorize with arguments, a custom attribute."""
    return bool(auth) and auth != "anonymous" and bool(re.sub(r"\b(?:Authorize(?:Filter)?|RequireAuthorization)\b(?! \()", "", auth).strip(" ,"))


def test_name(name):
    """True when an action name reads as test / temporary code. Whole camel-case words only ("Tester", "Testing", "Template"
    do not count), "Back"+"Test" is the business term backtest, and adapter option test_name_ignore lists more exceptions."""
    if any(re.fullmatch(p, name) for p in OPT.get("test_name_ignore", [])):
        return False
    words = [w.lower() for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+", name)]
    if any(w in TEST_ANYWHERE and not (w == "test" and k and words[k - 1] == "back") for k, w in enumerate(words)):
        return True
    return bool(words) and (words[0] in TEST_EDGE or words[-1] in TEST_EDGE)


def attr_names(attrs):
    """Attribute names in an attribute block ([A, B(x)] [C] -> A, B, C) with their argument text."""
    out = []
    for blk in re.findall(r"\[([^\]]*)\]", attrs):
        for m in re.finditer(r"(?:^|,)\s*([\w.]+)\s*(?:\(([^)]*)\))?", blk):
            out.append((m.group(1).split(".")[-1].removesuffix("Attribute"), (m.group(2) or "").strip()))
    return out


def auth_of(attrs):
    """Declared authorisation of an attribute block: "anonymous", "Authorize (Roles = …)", the project's own attributes."""
    names = attr_names(attrs)
    if any(n == "AllowAnonymous" for n, _ in names):
        return "anonymous"
    found = [n + (f" ({a})" if a else "") for n, a in names if n in AUTH_ATTRS]
    return ", ".join(found)


def csrf_of(attrs):
    """Anti-forgery filters in an attribute block; "ignored" for [IgnoreAntiforgeryToken]."""
    names = attr_names(attrs)
    if any(n.lower() == "ignoreantiforgerytoken" for n, _ in names):
        return "ignored"
    return ", ".join(n for n, _ in names if n.lower() in CSRF_ATTRS)


def effective_csrf(mattrs, cname):
    """(anti-forgery filters, where): the method's, else the controller's or a base controller's, else global filters."""
    c = csrf_of(mattrs)
    if c:
        return c, "method"
    seen, name = set(), cname
    while name in CLASS_ATTRS and name not in seen:
        seen.add(name)
        attrs, base = CLASS_ATTRS[name]
        c = csrf_of(attrs)
        if c:
            return c, "class" if name == cname else f"base {name}"
        name = base
    g = sorted({n.removesuffix("Attribute") for n, _, _ in GLOBAL if n.removesuffix("Attribute").lower() in CSRF_ATTRS})
    return (", ".join(g), "global filter") if g else ("", "")


def class_auth(name, seen=None):
    """(auth, where) declared on the controller or inherited from a base controller of the code base."""
    seen = seen or set()
    if name in seen or name not in CLASS_ATTRS:
        return "", ""
    seen.add(name)
    attrs, base = CLASS_ATTRS[name]
    a = auth_of(attrs)
    if a:
        return a, "class" if not seen - {name} else f"base {name}"
    return class_auth(base, seen) if base else ("", "")


def effective(mauth, cname):
    """Effective auth = method attributes, else controller / base controller, else global filters, else none declared."""
    if mauth:
        return mauth, "method"
    ca, where = class_auth(cname)
    if ca:
        return ca, where
    g = [n for n, _, _ in GLOBAL if n.removesuffix("Attribute") in AUTH_ATTRS or n in ("AuthorizeFilter", "RequireAuthorization")]
    if g:
        return ", ".join(sorted(set(n.removesuffix("Attribute") for n in g))), "global filter"
    return "", ""


def dotnet(path, raw):
    text = strip_comments(raw)  # //[HttpPost] and /* [Authorize] */ are not attributes
    code = code_only(raw)       # braces inside strings and comments do not count
    classes = list(CS_CLASS.finditer(text))
    spans = []                  # (start, end) of each class body: a nested class must not end its controller
    for k, c in enumerate(classes):
        close = block_close(code, c.end() - 1)
        spans.append((c.end(), close if close < len(code) else (classes[k + 1].start() if k + 1 < len(classes) else len(text))))
    for k, c in enumerate(classes):
        name, bases, cattrs = c.group(2), c.group(3) or "", c.group(1) or ""
        is_api = "ApiController" in cattrs or "ControllerBase" in bases or "ApiController" in bases
        if not (name.endswith("Controller") or is_api):
            continue
        start, end = spans[k]
        body = list(text[start:end])
        for j, (a, b) in enumerate(spans):  # blank nested types: their methods are not this controller's actions
            if j != k and start <= classes[j].start() and b <= end:
                for x in range(classes[j].start() - start, min(b + 1, end) - start):
                    if body[x] != "\n":
                        body[x] = " "
        body = "".join(body)
        ctl = re.sub(r"Controller$", "", name)
        # [Area("X")] (ASP.NET Core), else the Areas/<X>/Controllers folder (MVC 5 AreaRegistration convention)
        area = re.search(r"\[Area\(\s*\"([^\"]+)\"", cattrs) or re.search(r"(?i)(?:^|/)Areas/([^/]+)/Controllers/", path)
        prefix = attr_route(cattrs) or ""
        members = CONTROLLERS.setdefault(name, [])
        # filters on methods MVC never runs as actions: private / protected / static / [NonAction]
        for m in NON_ACTION.finditer(body):
            a = auth_of(m.group(1))
            if a and a != "anonymous":
                line = line_at(text, start + m.start(3))
                FINDINGS.append({"kind": "role attribute on a method that is not an action", "controller": name, "method": m.group(3),
                                 "file": path, "line": line, "detail": f"{a} on a {m.group(2) or 'static'} method: MVC never evaluates "
                                 "filters on non-actions; the action that calls it is not protected by it"})
        for m in CS_METHOD.finditer(body):
            attrs, meth = m.group(1) or "", m.group(2)
            line = line_at(text, start + m.start(2))
            if meth in (name, "Dispose") or re.search(r"\bstatic\b", m.group(0)):
                continue
            if "NonAction" in attrs:
                a = auth_of(attrs)
                if a and a != "anonymous":
                    FINDINGS.append({"kind": "role attribute on a method that is not an action", "controller": name, "method": meth,
                                     "file": path, "line": line, "detail": f"{a} on a [NonAction] method: never evaluated"})
                continue
            verbs = HTTP_ATTR.findall(attrs)
            mroute = attr_route(attrs)
            mauth = auth_of(attrs)
            eff, where = effective(mauth, name)
            auth = (f"{eff} ({where})" if where and where != "method" else eff) or "none declared"
            cs, cs_where = effective_csrf(attrs, name)
            first_row = len(rows)
            handler = M.next_after(path, line, within=0) or M.enclosing(path, line)
            params = sig_params(body, m.end() - 1)
            ret = m.group(0)[:m.start(2) - m.start()]
            helper = not is_api and not ACTION_RESULT.search(re.sub(r"\[[^\]]*\]", "", ret))
            members.append({"meth": meth, "auth": eff, "where": where, "declared": mauth, "file": path, "line": line,
                            "verbs": [v.upper() for v, _ in verbs] or ["ANY"], "params": params, "helper": helper,
                            "area": area.group(1) if area else "", "csrf": cs, "csrf_where": cs_where})

            def tokens(r):
                return r.replace("[controller]", ctl).replace("[action]", meth).replace("[area]", area.group(1) if area else "")
            conventional = f"{('/' + area.group(1)) if area else ''}/{ctl}/{meth}"
            if verbs or mroute is not None:
                for verb, tmpl in (verbs or [("ANY", "")]):
                    t = tmpl or mroute or ""
                    if not t and not prefix and not is_api:  # [HttpPost] on an MVC action: a verb filter, conventional route
                        add(verb, conventional, "ASP.NET MVC (conventional)", path, line, handler, params=params, auth=auth,
                            note="route from the default {controller}/{action} convention")
                        continue
                    full = t if t.startswith(("/", "~/")) else f"{prefix}/{t}" if prefix else t
                    add(verb, tokens(full), "ASP.NET", path, line, handler, params=params, auth=auth)
            elif CONVENTIONAL and not is_api and not re.search(r"\boverride\b", m.group(0)):
                # MVC routes EVERY public instance method of a controller, whatever it returns
                add("ANY", conventional, "ASP.NET MVC (conventional)", path, line, handler, params=params, auth=auth,
                    note="route from the default {controller}/{action} convention"
                         + ("; helper exposed as action (does not return an action result, but MVC still routes it)" if helper else ""))
            else:
                members[-1]["listed"] = False
                continue
            if helper and (verbs or mroute is not None):
                rows[-1]["note"] = (rows[-1]["note"] + "; " if rows[-1]["note"] else "") + "helper exposed as action"
            for r in rows[first_row:]:
                r["csrf"] = (f"{cs} ({cs_where})" if cs_where != "method" else cs) if cs else ""
    groups = {g.group(1): g.group(2) for g in re.finditer(r"(\w+)\s*=\s*[\w.]+\.MapGroup\(\s*\"([^\"]*)\"", text)}
    for m in re.finditer(r"(\w+)\s*\.\s*Map(Get|Post|Put|Delete|Patch|Methods|Fallback)\s*\(\s*\"([^\"]*)\"", text):
        recv, verb, route = m.group(1), m.group(2), m.group(3)
        line = line_at(text, m.start())
        handler_text = text[m.end():m.end() + 400]
        mg = re.match(r"\s*,\s*([\w.]+)\s*\)", handler_text)
        target, ncalls = minimal_handler(path, line, text, m.start(), mg.group(1) if mg else None)
        lp = lambda_params(handler_text)
        calls = " (calls the linked method)" if ncalls == 1 else f" (first of {ncalls} methods it calls is linked)"
        add("ANY" if verb in ("Methods", "Fallback") else verb, f"{groups.get(recv, '')}/{route}", "ASP.NET minimal API", path, line,
            handler=target or False, inline_params=lp,
            params=[x.strip() for x in lp.split(",") if x.strip()] if (target and not mg and lp is not None) else None,
            note=(f"handler {mg.group(1)}" if mg else "inline lambda" + (calls if target else
                  f", registered in {M.data.get(M.enclosing(path, line), {}).get('name', 'top-level code')}")))


def minimal_handler(path, line, text, start, group):
    """(method, calls) behind a minimal-API endpoint: the method group (MapGet("/x", Health)), else the first call the lambda
    makes on one of its typed parameters or on a type (runner.RunAllAsync(..), ScenarioRunner.Find(..)) and how many distinct
    known methods it calls, so a lambda that runs several is not presented as a thin wrapper around one."""
    by_name = {}
    for a, x in M.data.items():
        by_name.setdefault(x["name"], []).append(a)
    if group:
        parts = group.split(".")
        cands = [a for n, al in by_name.items() if n.endswith("." + parts[-1]) and (len(parts) == 1 or n.startswith(parts[-2] + "."))
                 for a in al]
        same = [a for a in cands if M.data[a]["file"] == path]
        return (same or cands or [None])[0], 1
    p = text.find("(", start)
    depth, end = 0, len(text)
    for k in range(p, len(text)):
        depth += (text[k] == "(") - (text[k] == ")")
        if depth == 0:
            end = k
            break
    body = text[p:end]
    lam = re.search(r"\(([^()]*)\)\s*=>", body)
    ptypes = {}
    for prm in (lam.group(1).split(",") if lam else []):
        prm = re.sub(r"\[[^\]]*\]", "", prm).strip()
        mm = re.match(r"([\w.]+)(?:<[^>]*>)?\??\s+(\w+)$", prm)
        if mm:
            ptypes[mm.group(2)] = mm.group(1).split(".")[-1]
    found = []
    for mm in re.finditer(r"(?<![\w.])(\w+)\s*\.\s*(\w+)\s*(?:<[^()]*>)?\s*\(", body):
        owner = ptypes.get(mm.group(1)) or (mm.group(1) if mm.group(1)[:1].isupper() else None)
        if owner and by_name.get(f"{owner}.{mm.group(2)}") and by_name[f"{owner}.{mm.group(2)}"][0] not in found:
            found.append(by_name[f"{owner}.{mm.group(2)}"][0])
    return (found[0], len(found)) if found else (None, 0)


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


CLIENT_EXT = {".js", ".mjs", ".ts", ".jsx", ".tsx", ".vue", ".cshtml", ".vbhtml", ".razor", ".aspx", ".ascx", ".master",
              ".html", ".htm"}
URL_PAIR = re.compile(r"(?=(?:/|(?<=['\"`]))([A-Za-z_]\w*)/([A-Za-z_]\w*)(?!\w))")  # '/Orders/Ship' or relative 'Orders/Ship'
URL_ONE = re.compile(r"(?=/([A-Za-z_]\w*)(?![\w/]))")
HELPER_URL = re.compile(r"(?:Url\.Action|Html\.ActionLink|Html\.BeginForm|Ajax\.BeginForm|Url\.RouteUrl|Html\.RenderAction|Html\.Action)"
                        r"\s*\(\s*(?:\"[^\"]*\"\s*,\s*)??\"(\w+)\"\s*,\s*\"(\w+)\"")
# inside Views/<Controller>/: a helper that names only the action targets the view's own controller
HELPER_ACT = re.compile(r"(?:(?:Url\.Action|Html\.BeginForm|Ajax\.BeginForm|Html\.Action|Html\.RenderAction)\s*\(\s*|"
                        r"Html\.ActionLink\s*\(\s*\"[^\"]*\"\s*,\s*)\"(\w+)\"\s*(?:\)|,\s*(?!\"))")
FORM_SELF = re.compile(r"(?:Html|Ajax)\.BeginForm\s*\(\s*\)|<form\b(?![^>]*\baction\s*=)[^>]*>", re.I)  # posts back to its own action
VIEW_OF = re.compile(r"(?i)(?:^|/)Views/(\w+)/(\w+)\.(?:cshtml|vbhtml|aspx)$")
ASP_ACTION = re.compile(r"\basp-action\s*=\s*\"")
ASP_CTL = re.compile(r"\basp-controller\s*=\s*\"(\w+)\"")
QUOTED = re.compile(r"\"(\w+)\"")


def tag_actions(text):
    """(controller or None, action, pos) for each asp-action tag helper. A Razor value (asp-action="@(isNew ? "Create" :
    "Edit")") gives every quoted name in it; None = no asp-controller on the tag, i.e. the view's own controller."""
    for m in ASP_ACTION.finditer(text):
        i = m.end()
        if text.startswith("@(", i):
            depth, j = 0, i + 1
            while j < len(text) and text[j] != "\n":
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                if depth == 0:
                    break
                j += 1
            acts, end = QUOTED.findall(text[i:j]), j + 1
        else:
            v = re.match(r"(\w+)\"", text[i:i + 200])
            if not v:
                continue
            acts, end = [v.group(1)], i + v.end()
        start = m.start()
        while start > 0:  # the tag's own "<name", not a "<=" inside an earlier Razor expression
            start = text.rfind("<", 0, start)
            if start < 0 or text[start + 1:start + 2].isalpha():
                break
        close = text.find(">", end)
        ctl = ASP_CTL.search(text[max(start, 0):close if close >= 0 else len(text)])
        for a in acts:
            yield (ctl.group(1) if ctl else None, a, m.start())


def client_callers():
    """{(controller, action) lower: [file:line, ...]} of the URLs that scripts, views and forms name ('/Orders/Ship',
    Url.Action("Ship", "Orders"), asp-action with or without asp-controller), comments blanked, copied libraries skipped; plus
    {controller: [...]} for '/Orders' (the Index action). URLs built at run time from variables are not seen."""
    from _scan import vendored
    lib = vendored()
    pairs, ones = defaultdict(list), defaultdict(list)
    for path, full in walk(exts=CLIENT_EXT):
        if path in lib:
            continue
        text = strip_web_comments(read(full))
        nl = [k for k, ch in enumerate(text) if ch == "\n"]

        def line_at(_text, pos):  # bisect over newline offsets: files with thousands of URLs stay linear
            return bisect.bisect_right(nl, pos - 1) + 1
        found = set()
        for m in URL_PAIR.finditer(text):
            found.add((m.group(1).lower(), m.group(2).lower(), m.start()))
        for m in HELPER_URL.finditer(text):
            found.add((m.group(2).lower(), m.group(1).lower(), m.start()))
        view = VIEW_OF.search(path)
        own = view.group(1).lower() if view and view.group(1).lower() != "shared" else None
        for ctl, act, pos in tag_actions(text):
            if ctl or own:
                found.add(((ctl or own).lower(), act.lower(), pos))
        if own:
            for m in HELPER_ACT.finditer(text):
                found.add((view.group(1).lower(), m.group(1).lower(), m.start()))
            for m in FORM_SELF.finditer(text):
                found.add((view.group(1).lower(), view.group(2).lower(), m.start()))
        for ctl, act, pos in found:
            pairs[(ctl, act)].append(f"{path}:{line_at(text, pos)}")
        for m in URL_ONE.finditer(text):
            ones[m.group(1).lower()].append(f"{path}:{line_at(text, m.start())}")
    return pairs, ones


def mark_callers():
    """Each ASP.NET endpoint gets "callers" (count) and "caller" (first file:line) from client_callers(); an endpoint no script,
    view or form names says so in its note: it may be dead, called only from server code, or by a client outside the repo."""
    pairs, ones = client_callers()
    for r in rows:
        if not r["framework"].startswith("ASP.NET") or "minimal API" in r["framework"]:
            continue
        segs = [s for s in r["route"].split("/") if s]
        if len(segs) < 2 or "{" in r["route"]:  # a templated URL is assembled in the client: not checked
            continue
        ctl, act = segs[-2].lower(), segs[-1].lower()
        hits = pairs.get((ctl, act), []) + (ones.get(ctl, []) if act == "index" else [])
        r["callers"], r["caller"] = len(hits), (sorted(hits)[0] if hits else "")
        if not hits:
            r["note"] = (r["note"] + "; " if r["note"] else "") + "no script, view or form in the repository names this URL"


def main():
    skip = re.compile(OPT["skip_regex"]) if OPT.get("skip_regex") else None
    prepass([(p, f) for p, f in walk(exts={".cs"}) if not (skip and skip.search(p))])
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
    review()
    mark_callers()
    by_proj = defaultdict(list)
    for r in rows:
        by_proj[project_of(r["file"])].append(r)
    fw = Counter(r["framework"] for r in rows)
    out = ["# Endpoints", "",
           f"Every HTTP endpoint declared in the code ({len(rows)}: " + ", ".join(f"{k} {v}" for k, v in fw.most_common()) + "). "
           "Routes are read from attributes, decorators and route registrations; anything built at run time (reflection, "
           "convention plug-ins, gateways) is not visible here. **Auth** is the effective authorisation the code declares: "
           "the method's attributes, else its controller or a base controller (`class`, `base X`), else a global filter; "
           "`none declared` means any visitor can call it unless middleware outside the controller checks. "
           "*anti-forgery* names the request-forgery (CSRF) filter that applies, found the same way; it checks a token, not "
           "the user, and many such filters skip GET requests. An MVC controller "
           "routes every public instance method, so helpers that return data rather than an action result are listed too "
           "(marked *helper exposed as action*)."
           + (" Global filters: " + ", ".join(f"`{n}` (`{f}:{ln}`)" for n, f, ln in GLOBAL) + "." if GLOBAL else ""), "",
           '<a id="index"></a>', "", "| Project | Endpoints |", "| --- | ---: |"]
    out += [f"| [{esc_text(p)}](#{slug('area', p)}) | {len(v)} |" for p, v in sorted(by_proj.items())]
    if FINDINGS:
        out += ["", f"[Security review candidates ({len(FINDINGS)})](#security-review)"]
    for p, rs in sorted(by_proj.items()):
        out += ["", f'<a id="{slug("area", p)}"></a>', "", f"## {p}", "", BACK, "",
                "| Endpoint | Handler | Parameters | Auth | Source |", "| --- | --- | --- | --- | --- |"]
        for r in sorted(rs, key=lambda r: (r["route"].lower(), r["verb"])):
            h = M.link(r["handler"]) or esc_text(r["note"]) or "—"
            if r["handler"] and r["note"]:
                h += f" · {esc_text(r['note'])}"
            params = ", ".join(f"`{esc(x)}`" for x in r["params"]) or "—"
            auth = esc_text(r["auth"]) or "—"
            if r.get("csrf"):
                auth += f" · anti-forgery: {esc_text(r['csrf'])}"
            out.append(f'| <a id="{slug("ep", r["verb"] + " " + r["route"])}"></a>**{r["verb"]} {esc_text(r["route"])}** | {h} | {params} | '
                       f'{auth} | `{esc(r["file"])}:{r["line"]}` ({r["framework"]}) |')
    if FINDINGS:
        kinds = Counter(f["kind"] for f in FINDINGS)
        out += ["", '<a id="security-review"></a>', "", "## Security review candidates", "", BACK, "",
                "Patterns that often hide an authorisation or CSRF gap, found mechanically. Each is a **candidate** for "
                "`security/findings.md`: read the code and confirm or dismiss it before it becomes a finding.", "",
                "| Kind | Count |", "| --- | ---: |"] + [f"| {esc_text(k)} | {n} |" for k, n in kinds.most_common()]
        out += ["", "| Kind | Controller · method | Detail | Source |", "| --- | --- | --- | --- |"]
        for f in sorted(FINDINGS, key=lambda f: (f["kind"], f["controller"], f["method"])):
            out.append(f"| {esc_text(f['kind'])} | {esc_text(f['controller'])} · {esc_text(f['method'])} | {esc_text(f['detail'])} | "
                       f"`{esc(f['file'])}:{f['line']}` |")
    write_page("endpoints.md", out)
    os.makedirs(os.path.join(DOCS, "agent"), exist_ok=True)
    open(os.path.join(DOCS, "agent", "api-findings.json"), "w", encoding="utf-8", newline="\n").write(
        json.dumps(FINDINGS, ensure_ascii=False, indent=1))
    for r in rows:
        r["anchor"] = slug("ep", r["verb"] + " " + r["route"])
    open(os.path.join(DOCS, "agent", "endpoints.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(rows, ensure_ascii=False, indent=1))
    stat("endpoints", endpoints=len(rows), projects=len(by_proj), review_candidates=len(FINDINGS),
         anonymous=sum(1 for r in rows if r["auth"].startswith("anonymous")), no_auth=sum(1 for r in rows if r["auth"] == "none declared"),
         no_client_caller=sum(1 for r in rows if r.get("callers") == 0))
    print(f"endpoints: {len(rows)} in {len(by_proj)} projects (" + ", ".join(f"{k} {v}" for k, v in fw.most_common()) + ")"
          + (f"; {len(FINDINGS)} security review candidates" if FINDINGS else ""))


def prepass(files):
    """The project's own authorisation attributes (classes deriving, directly or through each other, from AuthorizeAttribute
    or an authorisation filter, plus user_filters / role_filters), controller attributes and bases, and global filters."""
    bases = {}
    for path, full in files:
        t = strip_comments(read(full))
        cls = list(CS_CLASS.finditer(t))
        for k, m in enumerate(cls):
            if CSRF_NAME.search(m.group(2)):  # the project's own anti-forgery filter; does it look at the HTTP verb?
                n = m.group(2).removesuffix("Attribute").lower()
                CSRF_ATTRS.add(n)
                body = t[m.end():cls[k + 1].start() if k + 1 < len(cls) else len(t)]
                v = re.search(r"HttpMethod|RequestType|\bIsPost\b|HttpVerbs\.Post|\"POST\"", body, re.I)
                if v:
                    CSRF_SKIPS_GET[n] = f"{path}:{line_at(t, m.end() + v.start())}"
        for m in cls:
            # every base type counts: "ActionFilterAttribute, IAuthenticationFilter" is an authentication gate
            types = [b.strip().split("<")[0].split(".")[-1] for b in re.sub(r"<[^<>]*>", "", m.group(3) or "").split(",")]
            name, base = m.group(2), types[0] if types else ""
            bases[name] = [t for t in types if t]
            if name.endswith("Controller") or "Controller" in base:
                CLASS_ATTRS[name] = (m.group(1) or "", base)
    changed = True
    auth_classes = set()
    while changed:
        changed = False
        for name, types in bases.items():
            if name not in auth_classes and any(t in AUTH_BASES or t in auth_classes for t in types):
                auth_classes.add(name)
                changed = True
    # anti-forgery filters implement IAuthorizationFilter but validate the request, they do not authorise the user
    AUTH_ATTRS.update(n.removesuffix("Attribute") for n in auth_classes if not re.search(r"(?i)anti_?forgery|csrf|xsrf", n))
    AUTH_ATTRS.update(OPT.get("user_filters", []) + OPT.get("role_filters", []))
    GLOBAL.extend(global_filters())


def review():
    """Security review candidates from the controller members collected by dotnet()."""
    sib_min = OPT.get("sibling_role_min", 2)
    user_f = set(OPT.get("user_filters", []))
    for cname, ms in CONTROLLERS.items():
        acts = [m for m in ms if m.get("listed", True)]
        declared = Counter(a.split(" (")[0] for m in acts for a in [m["declared"]] if role_like(a))
        common = declared.most_common(1)[0] if declared else None
        for m in acts:
            loc = {"controller": cname, "method": m["meth"], "file": m["file"], "line": m["line"]}
            state = bool(STATE_CHANGE.match(m["meth"]))
            accepts_get = any(v in ("ANY", "GET") for v in m["verbs"])
            # admin-looking action (or most siblings) with no role filter of its own while siblings declare one
            if (common and common[1] >= sib_min and not role_like(m["auth"]) and (ADMIN_NAME.search(m["meth"])
                                                                                   or common[1] * 2 >= len(acts))):
                FINDINGS.append(dict(loc, kind="action without the role attribute its siblings carry",
                                     detail=f"{common[1]} of {len(acts)} actions in the controller declare {common[0]}; this one has "
                                     f"no role filter (effective: {m['auth'] or 'none'})"))
            elif ADMIN_NAME.search(m["area"]) and not role_like(m["auth"]):
                FINDINGS.append(dict(loc, kind="admin-area action without a role filter",
                                     detail=f"in area {m['area']}; effective auth {m['auth'] or 'none'}: any signed-in user may call it"))
            if state and accepts_get:
                cs = [c.strip() for c in m["csrf"].split(",") if c.strip() and m["csrf"] != "ignored"]
                skip = [f"{c} checks the HTTP verb (`{CSRF_SKIPS_GET[c.lower()]}`)" for c in cs if c.lower() in CSRF_SKIPS_GET]
                guard = ("" if not cs else f"; anti-forgery {', '.join(cs)} ({m['csrf_where']}) applies" +
                         (f", but {'; '.join(skip)}: confirm whether a GET request runs the action without the token" if skip
                          else ": confirm it validates GET requests too"))
                FINDINGS.append(dict(loc, kind="state-changing action accepting GET", detail=f"verbs: {', '.join(m['verbs'])}: a link or "
                                     "image tag can trigger it, and anti-forgery checks that only cover POST do not apply" + guard))
            if m["auth"] == "anonymous" and state:
                FINDINGS.append(dict(loc, kind="anonymous state-changing action", detail="[AllowAnonymous] on an action whose name "
                                     "says it changes data"))
            if not m["auth"] and state:
                FINDINGS.append(dict(loc, kind="no authorisation declared", detail="no attribute on the method, the controller, a "
                                     "base controller or a global filter"))
            if test_name(m["meth"]):
                FINDINGS.append(dict(loc, kind="test or temporary action left routable", detail=f"name suggests test / temporary code "
                                     f"(effective auth: {m['auth'] or 'none'})"))
            if m["helper"]:
                FINDINGS.append(dict(loc, kind="helper exposed as action", detail="public method that returns data, not an action "
                                     "result: MVC routes it; make it private or [NonAction] if it is not meant to be called"))
            if user_f and not any(u in (m["auth"] or "") for u in user_f) and any(
                    re.search(r"(?i)\b(user_?id|uid|userid)\b", p) for p in m["params"]):
                FINDINGS.append(dict(loc, kind="user-id parameter without the user filter",
                                     detail=f"takes a user id but declares none of {', '.join(sorted(user_f))}: may let one user act for another"))


if __name__ == "__main__":
    main()
