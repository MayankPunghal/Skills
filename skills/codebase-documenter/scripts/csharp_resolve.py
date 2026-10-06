"""C# call resolver: adds the calls graphify's AST pass cannot see, so every adapter follows them.

    python <skill>/scripts/csharp_resolve.py              # scan C#, write graphify-out/csharp-resolve.json, add edges to graph.json
    python <skill>/scripts/csharp_resolve.py --scan-only  # facts only, graph.json untouched

Run by `code_graph.py build` (before clustering) and by `build_site.py` when generic-di is configured (idempotent: earlier
edges with _origin "csharp-resolve" are replaced, graphify's own edges are never touched). Standard library only; reads
comment-stripped source, so it needs no build and works for .NET Framework and .NET alike.

What graphify already does for C#: a call through a field lands on the declaring type's method (`_svc.Place()` ->
IOrderService.Place) and an interface with exactly one implementer is joined to it (dispatches_to). Everything below is
what it leaves cut:

  E1 registration dispatch   interface / abstract service -> the implementations the container is told to build:
                             Microsoft.Extensions.DependencyInjection (Add/TryAdd[Keyed]Scoped|Transient|Singleton with
                             generics, typeof() incl. open generics, factories `sp => new X(..)`, forwarding
                             `sp => sp.GetRequiredService<X>()`, instances, ServiceDescriptor.*, TryAddEnumerable,
                             AddHostedService, AddDbContext*, AddHttpClient<I,T>), Scrutor (Decorate, Scan with
                             AssignableTo / name filters / AsImplementedInterfaces), Autofac, Unity, Ninject, Simple
                             Injector, StructureMap / Lamar, Castle Windsor
  E2 implementer dispatch    interfaces with no registration found and 2..max_implementers implementers (AMBIGUOUS)
  E3 override dispatch       abstract / virtual base method -> overrides in derived classes
  E4 keyed narrowing         a class injecting [FromKeyedServices("k")] IX calls the "k" implementation directly
  E5 message dispatch        Send / Publish / Dispatch(new X(..)) -> every handler of X: MediatR, MassTransit IConsumer<T>,
                             NServiceBus / Rebus IHandleMessages<T>, Brighter, home-grown I*Handler<T>, and Wolverine-style
                             convention handlers (class *Handler / *Consumer with Handle / Consume(X ..))
  E6 local-variable calls    `var v = sp.GetRequiredService<T>()`, `foreach (var v in _items)` over IEnumerable<T>,
                             `var v = new T(..)`, `T v = ..`, `is T v`, `as T` -> v.M() resolved to T.M
  E7 events and delegates    `obj.Evt += Handler` / `obj.Del = Handler` subscriptions -> the method raising Evt / invoking Del
                             calls each subscribed handler
  E8 method groups           `items.Select(Format)`, `MapGet("/x", Health)`, `Task.Run(Work)`, `new Thread(Work)` ...
  E9 background jobs         Hangfire Enqueue / Schedule / AddOrUpdate<T>(x => x.M()), Quartz JobBuilder.Create<T>()
  E10 MVC transfers          RedirectToAction("Action"[, "Controller"]) / RedirectToAction(nameof(X)) -> that action
  E11 pipeline filters       [ServiceFilter(typeof(F))] / [TypeFilter(typeof(F))] / [F] on a controller or action -> the
                             filter's OnAction* / OnResult* / OnException* methods run around each action

Facts written for the generic-di adapter (dependency-injection.md) and agents: composition roots and registration modules,
registrations per host, consumers (constructor, primary constructor, [FromServices], [Inject], Razor @inject), message
handlers and senders, options bindings, request-pipeline components (middleware, filters, endpoint filters, pipeline
behaviours, startup filters, validators), service-locator calls, convention scans, and findings (missing registration,
captive dependency, service locator outside the composition root, duplicate registration).

Options (codebase-docs.json -> adapter_options.generic-di): max_implementers (default 6), skip_regex.
"""
import argparse
import json
import os
import re
from collections import Counter, defaultdict

from _common import load_config, utf8_stdout, write

ORIGIN = "csharp-resolve"
CALLS = {"calls", "indirect_call", "dispatches_to"}
SKIP = re.compile(r"(^|/)(\.git|\.vs|bin|obj|node_modules|packages|TestResults|wwwroot/lib)(/|$)|\.designer\.cs$|\.g\.cs$|\.g\.i\.cs$|"
                  r"AssemblyInfo\.cs$", re.I)
KEYWORDS = {"if", "for", "foreach", "while", "switch", "catch", "using", "lock", "return", "new", "throw", "await", "yield", "typeof",
            "sizeof", "nameof", "default", "fixed", "checked", "unchecked", "else", "do", "try", "finally", "case", "when", "in", "is",
            "as", "base", "this", "get", "set", "init", "add", "remove", "var", "where", "select", "from", "let", "on", "equals"}
MODS = r"(?:(?:public|private|protected|internal|static|sealed|abstract|partial|readonly|unsafe|file|new|ref|virtual|override|async|extern|required)\s+)*"
FRAMEWORK = {"ILogger", "ILoggerFactory", "IOptions", "IOptionsSnapshot", "IOptionsMonitor", "IConfiguration", "IConfigurationRoot",
             "IServiceProvider", "IServiceScopeFactory", "IHttpClientFactory", "HttpClient", "IWebHostEnvironment", "IHostEnvironment",
             "IHostingEnvironment", "IHostApplicationLifetime", "IHttpContextAccessor", "IMemoryCache", "IDistributedCache",
             "IMediator", "ISender", "IPublisher", "IMapper", "RequestDelegate", "CancellationToken", "IBus", "IPublishEndpoint",
             "ISendEndpointProvider", "IMessageSession", "IBackgroundJobClient", "IRecurringJobManager", "ISchedulerFactory",
             "IStringLocalizer", "IHubContext", "IAuthorizationService", "IDataProtectionProvider", "TimeProvider", "IUrlHelper",
             "IAntiforgery", "IEmailSender", "UserManager", "SignInManager", "RoleManager", "IMetricsFactory", "ActivitySource",
             "IDbContextFactory", "IValidator", "IEnumerable", "Lazy", "Func"}
LIFETIME = {"scoped": "Scoped", "transient": "Transient", "singleton": "Singleton"}


# ---------------------------------------------------------------- C# text helpers

def strip(t):
    """(code, mask): comments blanked in both; string / char literal contents also blanked in mask. Same length, same lines."""
    code, mask, i, n = [], [], 0, len(t)
    while i < n:
        c = t[i]
        if c == "/" and t.startswith("//", i):
            j = t.find("\n", i)
            j = n if j < 0 else j
            code.append(" " * (j - i)); mask.append(" " * (j - i)); i = j
            continue
        if c == "/" and t.startswith("/*", i):
            j = t.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank = re.sub(r"[^\n]", " ", t[i:j])
            code.append(blank); mask.append(blank); i = j
            continue
        if c == '"' or (c in "@$" and i + 1 < n and t[i + 1] in '"@$'):
            j, verbatim = i, False
            while j < n and t[j] in "@$":
                verbatim |= t[j] == "@"
                j += 1
            if j >= n or t[j] != '"':
                code.append(c); mask.append(c); i += 1
                continue
            if t.startswith('"""', j):
                k = t.find('"""', j + 3)
                k = n if k < 0 else k + 3
            else:
                k = j + 1
                while k < n:
                    if verbatim and t[k] == '"' and k + 1 < n and t[k + 1] == '"':
                        k += 2
                        continue
                    if not verbatim and t[k] == "\\":
                        k += 2
                        continue
                    if t[k] == '"':
                        k += 1
                        break
                    if not verbatim and t[k] == "\n":
                        break
                    k += 1
            lit = t[i:k]
            code.append(lit)
            mask.append(t[i:j + 1] + re.sub(r"[^\n]", " ", t[j + 1:k - 1]) + (t[k - 1] if k - 1 > j else ""))
            i = k
            continue
        if c == "'":
            m = re.match(r"'(?:\\.[^']*|[^'\\])'", t[i:i + 12])
            if m:
                code.append(m.group(0)); mask.append("'" + " " * (len(m.group(0)) - 2) + "'"); i += len(m.group(0))
                continue
        code.append(c); mask.append(c); i += 1
    return "".join(code), "".join(mask)


def match(s, i, o="(", c=")"):
    """Index of the bracket closing the one at s[i] (-1 if unbalanced). Use on the mask."""
    depth = 0
    for k in range(i, len(s)):
        if s[k] == o:
            depth += 1
        elif s[k] == c:
            depth -= 1
            if depth == 0:
                return k
    return -1


def angle(s, i):
    """Index of the '>' closing the generic list opened at s[i] == '<' (-1 if this is not a generic list)."""
    depth = 0
    for k in range(i, min(len(s), i + 400)):
        ch = s[k]
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
            if depth == 0:
                return k
        elif ch in ";{}()=" or (ch == "&" or ch == "|"):
            return -1
    return -1


def split_top(s, sep=","):
    out, depth, cur = [], 0, []
    for ch in s:
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def tname(s):
    """('IRepository', ['Order']) from 'global::Shop.Core.IRepository<Order>?' ; arity kept for open generics."""
    s = re.sub(r"\s+", "", s or "").lstrip("@").replace("global::", "").rstrip("?")
    s = re.sub(r"\[\]$", "", s)
    if "<" in s and s.endswith(">"):
        head, inner = s[:s.index("<")], s[s.index("<") + 1:-1]
        args = split_top(inner) if inner.strip(",") else [""] * (inner.count(",") + 1)
    else:
        head, args = s, []
    return head.split(".")[-1], args


def line_at(t, pos):
    return t.count("\n", 0, pos) + 1


def stmt_end(mask, i):
    """End of the statement starting at i: the next ';' (or unmatched '}') at bracket depth 0."""
    depth = 0
    for k in range(i, len(mask)):
        ch = mask[k]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return k
        elif ch == ";" and depth == 0:
            return k
    return len(mask)


def literal(arg):
    """'stripe' from '"stripe"', nameof(X) -> X, a constant name otherwise."""
    arg = (arg or "").strip()
    m = re.match(r'^@?"(.*)"$', arg)
    if m:
        return m.group(1)
    m = re.match(r"^nameof\(\s*([\w.]+)\s*\)$", arg)
    return m.group(1).split(".")[-1] if m else arg


# ---------------------------------------------------------------- source model

class Source:
    def __init__(self, rel, text):
        self.rel = rel
        self.code, self.mask = strip(text)
        self.types = []     # dicts: name, kind, start, body (start, end) or None, bases [(name, args)], prim (params text), abstract
        self.methods = []   # dicts: name, start, body_start, end, params text, cls, line, static, abstract, virtual, override
        self.parse()

    def line(self, pos):
        return line_at(self.mask, pos)

    def parse(self):
        for m in re.finditer(r"\b(?P<kind>class|interface|struct|record(?:\s+(?:class|struct))?)\s+(?P<name>[A-Za-z_]\w*)", self.mask):
            if m.group("name") in KEYWORDS:
                continue
            before = self.mask[max(0, m.start() - 300):m.start()]
            mods = re.search(r"(?:^|[;{}\]])\s*(" + MODS + r")$", before)
            if not mods and m.start() > 300:
                continue
            if not mods and not re.match(r"^\s*(" + MODS + r")$", before):
                continue
            i = m.end()
            while i < len(self.mask) and self.mask[i].isspace():
                i += 1
            if i < len(self.mask) and self.mask[i] == "<":
                j = angle(self.mask, i)
                i = j + 1 if j > 0 else i
            while i < len(self.mask) and self.mask[i].isspace():
                i += 1
            prim = None
            if i < len(self.mask) and self.mask[i] == "(":
                j = match(self.mask, i)
                if j < 0:
                    continue
                prim = self.code[i + 1:j]
                i = j + 1
            k = i
            while k < len(self.mask) and self.mask[k] not in "{;":
                k += 1
            head = self.code[i:k]
            bases_txt = ""
            hm = re.match(r"\s*:\s*(.*?)(?:\bwhere\b.*)?$", head, re.S)
            if hm:
                bases_txt = hm.group(1)
            bases = []
            for b in split_top(bases_txt):
                b = re.sub(r"\(.*\)$", "", b.strip(), flags=re.S)   # record base ctor args: Base(x)
                if b:
                    bases.append(tname(b))
            body = None
            if k < len(self.mask) and self.mask[k] == "{":
                e = match(self.mask, k, "{", "}")
                body = (k, e if e > 0 else len(self.mask))
            kind = re.sub(r"\s+", " ", m.group("kind"))
            self.types.append({"name": m.group("name"), "kind": kind, "start": m.start(), "line": self.line(m.start()), "body": body,
                               "bases": bases, "prim": prim, "abstract": "abstract" in (mods.group(1) if mods else ""),
                               "static": "static" in (mods.group(1) if mods else ""),
                               "partial": "partial" in (mods.group(1) if mods else "")})
        # namespace of each type (file-scoped or block)
        spaces = [(mm.start(), mm.group(1)) for mm in re.finditer(r"\bnamespace\s+([\w.]+)", self.mask)]
        for t in self.types:
            ns = [n for p, n in spaces if p < t["start"]]
            t["namespace"] = ns[-1] if ns else ""
        # methods / constructors / local functions with bodies
        rx = re.compile(r"(?:^|(?<=[;{}\]\s]))(?P<mods>" + MODS + r")(?:(?P<ret>[\w.?\[\]]+(?:\s*<[^;{}()=]*?>)?[?\[\]]*)\s+)?"
                        r"(?P<name>[A-Za-z_]\w*)\s*(?:<[^;{}()=]*?>)?\s*\(")
        for m in rx.finditer(self.mask):
            name = m.group("name")
            if name in KEYWORDS or (m.group("ret") or "") in KEYWORDS or (m.group("ret") or "") in ("return", "new", "await", "else", "throw"):
                continue
            p0 = m.end() - 1
            p1 = match(self.mask, p0)
            if p1 < 0:
                continue
            k = p1 + 1
            tail = re.match(r"\s*(?::\s*(?:base|this)\s*\((?:[^()]|\([^()]*\))*\)\s*)?(?:where\b[^{;=]*)?", self.mask[k:])
            k += tail.end() if tail else 0
            if self.mask.startswith("{", k):
                e = match(self.mask, k, "{", "}")
                if e < 0:
                    continue
            elif self.mask.startswith("=>", k):
                e = stmt_end(self.mask, k + 2)
            elif self.mask.startswith(";", k) and (m.group("ret") or "abstract" in m.group("mods")):
                e = k                                   # abstract / interface member
            else:
                continue
            if not m.group("ret") and not any(t["name"] == name for t in self.types):
                continue                                # a call statement, not a declaration (constructors have no return type)
            mods = m.group("mods") or ""
            self.methods.append({"name": name, "ret": re.sub(r"\s+", "", m.group("ret") or ""), "start": m.start("name"), "body_start": k, "end": e, "params": self.code[p0 + 1:p1],
                                 "line": self.line(m.start("name")), "static": "static" in mods, "abstract": "abstract" in mods,
                                 "virtual": "virtual" in mods, "override": "override" in mods, "ctor": not m.group("ret")})
        for md in self.methods:
            owners = [t for t in self.types if t["body"] and t["body"][0] < md["start"] < t["body"][1]]
            md["cls"] = min(owners, key=lambda t: t["body"][1] - t["body"][0])["name"] if owners else None

    def enclosing(self, pos):
        cands = [m for m in self.methods if m["body_start"] <= pos <= m["end"]]
        return min(cands, key=lambda m: m["end"] - m["body_start"]) if cands else None

    def type_at(self, pos):
        cands = [t for t in self.types if t["body"] and t["body"][0] < pos < t["body"][1]]
        return min(cands, key=lambda t: t["body"][1] - t["body"][0]) if cands else None


def params(txt):
    """[(type, args, name, key, attrs)] from a parameter list."""
    out = []
    for p in split_top(txt or ""):
        attrs = " ".join(re.findall(r"\[[^\]]*\]", p))
        key = re.search(r"\[\s*(?:FromKeyedServices|KeyFilter|Named|ServiceKey)\s*\(\s*([^)\]]+)\)", p)
        p = re.sub(r"\[[^\]]*\]", " ", p)
        p = re.sub(r"=.*$", "", p, flags=re.S).strip()
        p = re.sub(r"^(?:(?:this|ref|in|out|params|scoped|readonly)\s+)+", "", p)
        m = re.match(r"(.+?)\s*\b([A-Za-z_]\w*)$", p, re.S)
        if not m:
            continue
        base, args = tname(m.group(1))
        out.append({"type": base, "args": args, "display": re.sub(r"\s+", "", m.group(1)), "needs": elem(base, args), "name": m.group(2),
                    "key": literal(key.group(1)) if key else None, "attrs": attrs,
                    "this": bool(re.match(r"\s*this\s", txt.split(",")[0])) and not out})
    return out


# ---------------------------------------------------------------- scanning

class Model:
    def __init__(self, root, skip=None):
        self.root = root
        self.files = {}
        self.razor = []
        skip_rx = re.compile(skip, re.I) if skip else None
        for d, dirs, fs in os.walk(root):
            r = os.path.relpath(d, root).replace("\\", "/")
            r = "" if r == "." else r
            dirs[:] = [x for x in dirs if not SKIP.search(f"{r}/{x}/".lstrip("/"))]
            for f in fs:
                p = f"{r}/{f}".lstrip("/")
                if SKIP.search(p) or (skip_rx and skip_rx.search(p)):
                    continue
                low = f.lower()
                if low.endswith(".cs"):
                    try:
                        self.files[p] = Source(p, open(os.path.join(d, f), encoding="utf-8-sig", errors="replace").read())
                    except (OSError, RecursionError):
                        pass
                elif low.endswith((".cshtml", ".razor")):
                    try:
                        self.razor.append((p, open(os.path.join(d, f), encoding="utf-8-sig", errors="replace").read()))
                    except OSError:
                        pass
        self.types = defaultdict(list)          # name -> [(file, type)]
        for p, s in self.files.items():
            for t in s.types:
                t["file"] = p
                self.types[t["name"]].append(t)
        self.proj_cache = {}
        global MODEL
        MODEL = self                             # field_type() looks fields up in the other parts of a partial class

    def partials(self):
        """Partial types declared in more than one file: name -> parts (file, line, members declared there)."""
        out = {}
        for n, ts in self.types.items():
            parts = [t for t in ts if t.get("partial")]
            by_ns = defaultdict(list)
            for t in parts:
                by_ns[t["namespace"]].append(t)
            for ns, group in by_ns.items():
                if len({t["file"] for t in group}) > 1:
                    out[n if n not in out else f"{ns}.{n}"] = [
                        {"file": t["file"], "line": t["line"], "kind": t["kind"], "namespace": ns, "bases": [b for b, _ in t["bases"]],
                         "methods": sorted({m["name"] for m in self.files[t["file"]].methods if m["cls"] == n
                                            and t["body"] and t["body"][0] <= m["start"] <= t["body"][1]})}
                        for t in sorted(group, key=lambda t: t["file"])]
        return out

    def project(self, rel):
        """Folder name of the nearest project file (.csproj / .vbproj / .fsproj) above rel."""
        d = os.path.dirname(rel)
        while True:
            if d not in self.proj_cache:
                try:
                    hit = [f for f in os.listdir(os.path.join(self.root, d) if d else self.root) if re.search(r"\.(cs|vb|fs)proj$", f, re.I)]
                except OSError:
                    hit = []
                self.proj_cache[d] = os.path.splitext(hit[0])[0] if hit else None
            if self.proj_cache[d]:
                return self.proj_cache[d]
            if not d:
                return rel.split("/")[0] if "/" in rel else "(root)"
            d = os.path.dirname(d)

    def decl(self, name):
        ts = self.types.get(name) or []
        return ts[0] if ts else None

    def is_abstraction(self, name):
        ts = self.types.get(name) or []    # every part of a partial type: `abstract` may sit on one part only
        return bool(ts) and (ts[0]["kind"] == "interface" or any(t["abstract"] for t in ts))

    def implementers(self, name):
        """Repo classes deriving from / implementing `name`, transitively."""
        kids = defaultdict(set)
        for n, ts in self.types.items():
            for t in ts:
                for b, _ in t["bases"]:
                    kids[b].add(n)
        out, todo = set(), [name]
        while todo:
            for k in kids.get(todo.pop(), ()):
                if k not in out:
                    out.add(k)
                    todo.append(k)
        return {k for k in out if any(t["kind"] != "interface" and not t["abstract"] for t in self.types[k])}

    def supertypes(self, name, seen=None):
        seen = seen if seen is not None else set()
        for t in self.types.get(name, []):
            for b, _ in t["bases"]:
                if b not in seen:
                    seen.add(b)
                    self.supertypes(b, seen)
        return seen


# lifetime words in container chains
AUTOFAC_LT = [(r"\.SingleInstance\(", "Singleton"), (r"\.InstancePer(?:LifetimeScope|Request|MatchingLifetimeScope|OwnedLifetimeScope)\(", "Scoped"),
              (r"\.InstancePerDependency\(", "Transient")]
NINJECT_LT = [(r"\.InSingletonScope\(", "Singleton"), (r"\.In(?:Request|Thread|Call)Scope\(", "Scoped"), (r"\.InTransientScope\(", "Transient")]
UNITY_LT = [(r"ContainerControlledLifetimeManager|SingletonLifetimeManager", "Singleton"),
            (r"HierarchicalLifetimeManager|PerRequestLifetimeManager|PerResolveLifetimeManager|PerThreadLifetimeManager", "Scoped"),
            (r"TransientLifetimeManager", "Transient")]
CASTLE_LT = [(r"\.Lifestyle(?:Singleton)\(", "Singleton"), (r"\.Lifestyle(?:PerWebRequest|Scoped|PerThread)\(", "Scoped"),
             (r"\.LifestyleTransient\(", "Transient")]
SM_LT = [(r"\.Singleton\(", "Singleton"), (r"\.(?:Scoped|HybridHttpOrThreadLocalScoped|ContainerScoped)\(", "Scoped"), (r"\.Transient\(", "Transient")]


def chain_lifetime(chain, table, default):
    for rx, lt in table:
        if re.search(rx, chain):
            return lt
    return default


def factory_impl(arg_code):
    """Implementation named inside a factory / instance argument: `sp => new X(..)`, `new X()`, `sp => sp.GetRequiredService<X>()`."""
    m = re.search(r"\bnew\s+([\w.]+)\s*(?:<[^()]*>)?\s*[({]", arg_code)
    if m:
        return tname(m.group(1))[0], "factory" if "=>" in arg_code else "instance"
    m = re.search(r"\bGet(?:Required)?(?:Keyed)?Service\s*<\s*([\w.<>, ]+?)\s*>", arg_code)
    if m:
        return tname(m.group(1))[0], "forwarded"
    return None, "factory" if "=>" in arg_code or "delegate" in arg_code else "instance"


def scan(model):
    regs, modules, conventions, options_b, locators, pipeline, notes = [], [], [], [], [], [], []
    containers = Counter()

    def reg(src, pos, service, impl, lifetime, how, container, key=None, args=None, extra=None):
        if not service:
            return
        regs.append(dict({"service": service, "service_args": args or [], "impl": impl or service, "lifetime": lifetime, "how": how,
                          "container": container, "key": key, "file": src.rel, "line": src.line(pos), "pos": pos}, **(extra or {})))
        containers[container] += 1

    for p, src in model.files.items():
        M, C = src.mask, src.code

        def gen_at(i):
            """(types, end) for a generic list starting at mask index i (after optional spaces)."""
            while i < len(M) and M[i].isspace():
                i += 1
            if i < len(M) and M[i] == "<":
                j = angle(M, i)
                if j > 0:
                    return [x for x in split_top(C[i + 1:j])], j + 1
            return [], i

        def call_args(i):
            while i < len(M) and M[i].isspace():
                i += 1
            if i < len(M) and M[i] == "(":
                j = match(M, i)
                if j > 0:
                    return split_top(C[i + 1:j]), j + 1, C[i + 1:j]
            return None, i, ""

        # --- Microsoft.Extensions.DependencyInjection
        for m in re.finditer(r"\.\s*(?:Try)?Add(Keyed)?(Scoped|Transient|Singleton)\b", M):
            gens, i = gen_at(m.end())
            args, end, raw = call_args(i)
            if args is None:
                continue
            keyed, lt = bool(m.group(1)), m.group(2)
            key = None
            if keyed and args and "typeof" not in args[0]:
                key = literal(args.pop(0))
            elif keyed and len(args) >= 2 and "typeof" in args[0] and "typeof" not in args[1]:
                key = literal(args.pop(1))
            if len(gens) == 2:
                reg(src, m.start(), *(tname(gens[0])[0], tname(gens[1])[0]), lt, "type", "msdi", key, tname(gens[0])[1])
            elif len(gens) == 1:
                svc = tname(gens[0])
                impl, how = (factory_impl(raw) if args else (svc[0], "type"))
                reg(src, m.start(), svc[0], impl, lt, how, "msdi", key, svc[1])
            else:
                tys = [tname(re.sub(r"^typeof\s*\(\s*|\s*\)$", "", a))[0:2] for a in args if a.startswith("typeof")]
                if not tys:
                    impl, how = factory_impl(raw)        # AddSingleton(_ => new X(..)) / AddSingleton(instance)
                    if impl:
                        reg(src, m.start(), impl, impl, lt, how, "msdi", key)
                    continue
                svc = tys[0]
                if len(tys) >= 2:
                    impl, how = tys[1][0], "open generic" if svc[1] else "type"
                else:
                    rest = ",".join(a for a in args if not a.startswith("typeof"))
                    impl, how = factory_impl(rest) if rest else (svc[0], "type")
                    how = "open generic" if svc[1] and how == "type" else how
                reg(src, m.start(), svc[0], impl, lt, how, "msdi", key, svc[1])
        for m in re.finditer(r"\bServiceDescriptor\s*\.\s*(?:Keyed)?(Scoped|Transient|Singleton)\b", M):
            gens, i = gen_at(m.end())
            args, _, raw = call_args(i)
            if len(gens) == 2:
                reg(src, m.start(), tname(gens[0])[0], tname(gens[1])[0], m.group(1), "descriptor", "msdi")
            elif len(gens) == 1:
                impl, how = factory_impl(raw) if args else (tname(gens[0])[0], "descriptor")
                reg(src, m.start(), tname(gens[0])[0], impl, m.group(1), how, "msdi")
        for m in re.finditer(r"\bServiceDescriptor\s*\.\s*Describe\s*\(", M):
            args, _, _ = call_args(m.end() - 1)
            tys = [tname(re.sub(r"^typeof\s*\(\s*|\s*\)$", "", a))[0] for a in (args or []) if a.startswith("typeof")]
            lt = re.search(r"ServiceLifetime\.(\w+)", ",".join(args or []))
            if len(tys) == 2:
                reg(src, m.start(), tys[0], tys[1], lt.group(1) if lt else "?", "descriptor", "msdi")
        for m in re.finditer(r"\.\s*AddHostedService\b", M):
            gens, i = gen_at(m.end())
            args, _, raw = call_args(i)
            if gens:
                reg(src, m.start(), tname(gens[0])[0], tname(gens[0])[0], "Singleton", "hosted service", "msdi")
                pipeline.append({"kind": "hosted service", "type": tname(gens[0])[0], "file": p, "line": src.line(m.start())})
        for m in re.finditer(r"\.\s*Add(DbContext(?:Pool|Factory)?|PooledDbContextFactory)\b", M):
            gens, i = gen_at(m.end())
            if gens:
                ctx = tname(gens[-1])[0]
                svc = tname(gens[0])[0]
                lt = "Singleton" if "Factory" in m.group(1) else "Scoped"
                reg(src, m.start(), svc, ctx, lt, "DbContext" + (" pool" if "Pool" in m.group(1) else " factory" if "Factory" in m.group(1) else ""), "msdi")
        for m in re.finditer(r"\.\s*AddHttpClient\b", M):
            gens, i = gen_at(m.end())
            if gens:
                reg(src, m.start(), tname(gens[0])[0], tname(gens[-1])[0], "Transient", "typed HttpClient", "msdi")
        for m in re.finditer(r"\.\s*Add(?:Refit|Grpc)Client\b", M):
            gens, i = gen_at(m.end())
            if gens:
                reg(src, m.start(), tname(gens[0])[0], None, "Transient",
                    "Refit HTTP client (generated)" if "Refit" in m.group(0) else "gRPC client (generated)", "msdi", extra={"external": True})
        for m in re.finditer(r"\.\s*Decorate\b", M):
            gens, i = gen_at(m.end())
            if len(gens) == 2:
                reg(src, m.start(), tname(gens[0])[0], tname(gens[1])[0], "(as decorated)", "decorator", "scrutor")
        for m in re.finditer(r"\.\s*(Configure|ConfigureOptions|AddOptions|PostConfigure)\b", M):
            gens, i = gen_at(m.end())
            args, end, raw = call_args(i)
            if not gens or args is None:
                continue
            chain = C[m.start():stmt_end(M, m.start())]
            sec = re.search(r'GetSection\(\s*"([^"]+)"|BindConfiguration\(\s*"([^"]+)"', chain)
            options_b.append({"type": tname(gens[0])[0], "section": (sec.group(1) or sec.group(2)) if sec else None,
                              "how": m.group(1) + ("" if sec else " (code)"), "file": p, "line": src.line(m.start())})
        for m in re.finditer(r"\.\s*AddMediatR\s*\(", M):
            notes.append({"kind": "MediatR", "file": p, "line": src.line(m.start()), "text": "MediatR registered: handlers found by assembly scan"})
            containers["mediatr"] += 1
            chain = C[m.start():stmt_end(M, m.start())]
            for b in re.findall(r"(?:AddBehavior|AddOpenBehavior)\s*\(\s*typeof\s*\(\s*([\w.]+)", chain):
                pipeline.append({"kind": "MediatR pipeline behaviour", "type": tname(b)[0], "file": p, "line": src.line(m.start())})
        for m in re.finditer(r"\.\s*Scan\s*\(", M):
            end = stmt_end(M, m.start())
            chain = C[m.start():end]
            if "AddClasses" not in chain and "RegisterAssemblyTypes" not in chain:
                continue
            conventions.append({"file": p, "line": src.line(m.start()), "pos": m.start(), "text": re.sub(r"\s+", " ", chain)[:400], "kind": "scrutor"})
        for m in re.finditer(r"\.\s*RegisterAssemblyTypes\s*\(", M):
            end = stmt_end(M, m.start())
            conventions.append({"file": p, "line": src.line(m.start()), "pos": m.start(), "text": re.sub(r"\s+", " ", C[m.start():end])[:400], "kind": "autofac"})
        handled = re.compile(r"^(?:Try)?Add(?:Keyed)?(?:Scoped|Transient|Singleton)$|^Add(?:HostedService|DbContext\w*|PooledDbContextFactory|"
                             r"HttpClient|RefitClient|GrpcClient|Options|MediatR)$")
        for m in re.finditer(r"\b(?:[Ss]ervices|builder\.Services)\s*\.\s*(Add\w+)\s*(?:<[^;{}()]*>)?\s*\(", M):
            if not handled.match(m.group(1)):
                # framework / library features the application switches on: AddSession, AddHealthChecks, AddSignalR, AddConsumers ...
                notes.append({"kind": m.group(1), "file": p, "line": src.line(m.start()),
                              "text": re.sub(r"\s+", " ", C[m.start():stmt_end(M, m.start())])[:160], "host": model.project(p)})
        # --- Autofac
        for m in re.finditer(r"\.\s*Register(Type|Generic|Instance)?\b", M):
            kind = m.group(1)
            gens, i = gen_at(m.end())
            args, end, raw = call_args(i)
            if args is None:
                continue
            chain = C[m.start():stmt_end(M, m.start())]
            if not re.search(r"\.\s*(As|AsSelf|AsImplementedInterfaces|Keyed|Named|SingleInstance|InstancePer\w+)\b", chain):
                # Unity RegisterType<I,T>() / Simple Injector Register<I,T>()
                if len(gens) == 2 and kind in (None, "Type"):
                    lt = chain_lifetime(raw, UNITY_LT, "Transient") if kind == "Type" else \
                        (re.search(r"Lifestyle\.(\w+)", raw).group(1) if re.search(r"Lifestyle\.(\w+)", raw) else "Transient")
                    reg(src, m.start(), tname(gens[0])[0], tname(gens[1])[0], lt, "type", "unity" if kind == "Type" else "simpleinjector")
                elif len(gens) == 1 and kind is None and re.search(r"Lifestyle\.", raw):
                    reg(src, m.start(), tname(gens[0])[0], tname(gens[0])[0], re.search(r"Lifestyle\.(\w+)", raw).group(1), "type", "simpleinjector")
                continue
            lt = chain_lifetime(chain, AUTOFAC_LT, "Transient")
            if kind == "Generic":
                impl = tname(re.sub(r"^typeof\s*\(\s*|\s*\)$", "", args[0]))[0] if args else None
                svcs = [tname(x)[0] for x in re.findall(r"\.\s*As\s*\(\s*typeof\s*\(\s*([\w.<>, ]+?)\s*\)", chain)]
                how = "open generic"
            elif gens:
                impl, how = tname(gens[0])[0], "type"
                svcs = []
            else:
                impl, how = factory_impl(raw)
                svcs = []
            svcs += [tname(x)[0] for x in re.findall(r"\.\s*(?:As|Keyed|Named)\s*<\s*([\w.<>, ]+?)\s*>", chain)]
            key = re.search(r"\.\s*(?:Keyed|Named)\s*<[^>]*>\s*\(\s*([^)]+)\)", chain)
            if re.search(r"\.\s*AsImplementedInterfaces\s*\(", chain) and impl:
                svcs += [b for b in model.supertypes(impl) if model.decl(b) and model.decl(b)["kind"] == "interface"]
            if re.search(r"\.\s*AsSelf\s*\(", chain) or not svcs:
                svcs.append(impl)
            for s in dict.fromkeys(x for x in svcs if x):
                reg(src, m.start(), s, impl, lt, how, "autofac", literal(key.group(1)) if key else None)
        for m in re.finditer(r"\.\s*RegisterModule\b", M):
            gens, i = gen_at(m.end())
            args, _, raw = call_args(i)
            mod = tname(gens[0])[0] if gens else (factory_impl(raw)[0] if raw else None)
            if mod:
                modules.append({"call": mod, "file": p, "pos": m.start(), "line": src.line(m.start()), "kind": "module class"})
        # --- Ninject  Bind<I>().To<T>()
        for m in re.finditer(r"\bBind\s*<", M):
            gens, i = gen_at(m.start() + 4)
            chain = C[m.start():stmt_end(M, m.start())]
            to = re.search(r"\.\s*To\s*<\s*([\w.<>, ]+?)\s*>", chain)
            if gens and (to or re.search(r"\.\s*To(Self|Method|Constant)\b", chain)):
                impl = tname(to.group(1))[0] if to else (tname(gens[0])[0] if "ToSelf" in chain else factory_impl(chain)[0])
                for g in gens:
                    reg(src, m.start(), tname(g)[0], impl, chain_lifetime(chain, NINJECT_LT, "Transient"), "type", "ninject")
        # --- StructureMap / Lamar  For<I>().Use<T>() / Add<T>()
        for m in re.finditer(r"(?<![\w.])For\s*<", M):
            gens, i = gen_at(m.start() + 3)
            chain = C[m.start():stmt_end(M, m.start())]
            use = re.search(r"\.\s*(?:Use|Add)\s*<\s*([\w.<>, ]+?)\s*>", chain)
            if gens and use:
                reg(src, m.start(), tname(gens[0])[0], tname(use.group(1))[0], chain_lifetime(chain, SM_LT, "Transient"), "type", "structuremap")
        # --- Castle Windsor  Component.For<I>().ImplementedBy<T>()
        for m in re.finditer(r"\bComponent\s*\.\s*For\s*<", M):
            gens, i = gen_at(m.end() - 1)
            chain = C[m.start():stmt_end(M, m.start())]
            impl = re.search(r"\.\s*ImplementedBy\s*<\s*([\w.<>, ]+?)\s*>", chain)
            if gens:
                for g in gens:
                    reg(src, m.start(), tname(g)[0], tname(impl.group(1))[0] if impl else tname(gens[0])[0],
                        chain_lifetime(chain, CASTLE_LT, "Singleton"), "type", "windsor")
        # --- service locator calls (also used for E6)
        for m in re.finditer(r"\.\s*(GetRequiredService|GetService|GetRequiredKeyedService|GetKeyedService|Resolve|ResolveOptional|"
                             r"ResolveKeyed|GetInstance|GetAllInstances|GetServices)\s*<", M):
            gens, i = gen_at(m.end() - 1)
            if not gens:
                continue
            md = src.enclosing(m.start())
            locators.append({"type": tname(gens[0])[0], "call": m.group(1), "file": p, "line": src.line(m.start()), "pos": m.start(),
                             "method": md["name"] if md else None, "cls": md["cls"] if md else None})
        # --- request pipeline
        for m in re.finditer(r"\.\s*UseMiddleware\s*<", M):
            gens, _ = gen_at(m.end() - 1)
            if gens:
                pipeline.append({"kind": "middleware", "type": tname(gens[0])[0], "file": p, "line": src.line(m.start())})
        for m in re.finditer(r"\.\s*(?:Filters\s*\.\s*Add|AddEndpointFilter|AddFilter)\s*<", M):
            gens, _ = gen_at(m.end() - 1)
            if gens:
                pipeline.append({"kind": "endpoint filter" if "Endpoint" in m.group(0) else "global filter", "type": tname(gens[0])[0],
                                 "file": p, "line": src.line(m.start())})
        for m in re.finditer(r"\.\s*(?:Filters\s*\.\s*Add(?:Service)?)\s*\(\s*(?:typeof\s*\(\s*|new\s+)([\w.]+)", M):
            pipeline.append({"kind": "global filter", "type": tname(m.group(1))[0], "file": p, "line": src.line(m.start())})
    # pipeline types found by what they are, not where they are registered
    seen = {(x["kind"], x["type"]) for x in pipeline}
    for n, ts in model.types.items():
        for t in ts:
            bases = {b for b, _ in t["bases"]}
            src = model.files[t["file"]]
            kinds = []
            if bases & {"IMiddleware"} or (any(md["cls"] == n and md["name"] in ("Invoke", "InvokeAsync") and "HttpContext" in md["params"]
                                               for md in src.methods)):
                kinds.append("middleware")
            if bases & {"IActionFilter", "IAsyncActionFilter", "ActionFilterAttribute", "IResultFilter", "IAsyncResultFilter",
                        "IExceptionFilter", "IAsyncExceptionFilter", "ExceptionFilterAttribute", "IAuthorizationFilter",
                        "IAsyncAuthorizationFilter", "IResourceFilter", "IAsyncResourceFilter", "ResultFilterAttribute",
                        "IPageFilter", "IAsyncPageFilter", "IAlwaysRunResultFilter", "IAsyncAlwaysRunResultFilter"}:
                kinds.append("MVC filter")
            if "IEndpointFilter" in bases:
                kinds.append("endpoint filter")
            if "IPipelineBehavior" in bases or "IStreamPipelineBehavior" in bases:
                kinds.append("MediatR pipeline behaviour")
            if "IStartupFilter" in bases:
                kinds.append("startup filter")
            if bases & {"AbstractValidator"}:
                kinds.append("validator")
            if bases & {"IModelBinder", "IModelBinderProvider"}:
                kinds.append("model binder")
            if bases & {"DelegatingHandler"}:
                kinds.append("HTTP message handler")
            if bases & {"IInterceptor", "DbCommandInterceptor", "SaveChangesInterceptor", "DbConnectionInterceptor"}:
                kinds.append("interceptor")
            if bases & {"BackgroundService", "IHostedService"}:
                kinds.append("hosted service")
            if bases & {"Hub"}:
                kinds.append("SignalR hub")
            for k in kinds:
                if not any(x["type"] == n and x["kind"] == k for x in pipeline):
                    pipeline.append({"kind": k, "type": n, "file": t["file"], "line": t["line"], "declared_only": (k, n) not in seen})
    return regs, modules, conventions, options_b, locators, pipeline, notes, containers


def apply_conventions(model, conventions, regs):
    """Scrutor / Autofac assembly scans: resolve what can be read from the chain (AssignableTo<T>, name filters, As*)."""
    for c in conventions:
        t = c["text"]
        targets = [tname(x)[0] for x in re.findall(r"AssignableTo(?:Any)?\s*<\s*([\w.<>, ]+?)\s*>", t)]
        targets += [tname(x)[0] for x in re.findall(r"AssignableTo(?:Any)?\s*\(\s*typeof\s*\(\s*([\w.<>, ]+?)\s*\)", t)]
        suffix = re.findall(r'Name\.EndsWith\(\s*"(\w+)"', t)
        prefix = re.findall(r'Name\.StartsWith\(\s*"(\w+)"', t)
        lt = re.search(r"With(Scoped|Transient|Singleton)Lifetime|InstancePer(LifetimeScope|Dependency)|SingleInstance", t)
        lifetime = {"LifetimeScope": "Scoped", "Dependency": "Transient"}.get(lt.group(2), lt.group(1)) if lt and lt.group(2) else \
            (lt.group(1) if lt and lt.group(1) else ("Singleton" if lt else "Transient"))
        classes = set()
        for name, ts in model.types.items():
            if not any(x["kind"] not in ("interface",) and not x["abstract"] and not x["static"] for x in ts):
                continue
            if targets and not any(name in model.implementers(tg) for tg in targets):
                continue
            if suffix and not any(name.endswith(s) for s in suffix):
                continue
            if prefix and not any(name.startswith(s) for s in prefix):
                continue
            if not (targets or suffix or prefix):
                continue
            classes.add(name)
        c["resolved"] = sorted(classes)
        c["lifetime"] = lifetime
        if not classes:
            continue
        src_line = c["line"]
        for cl in classes:
            svcs = []
            if re.search(r"AsImplementedInterfaces|AsSelfWithInterfaces", t):
                svcs += [b for b in model.supertypes(cl) if model.decl(b) and model.decl(b)["kind"] == "interface"]
            if re.search(r"AsMatchingInterface|AsDefaultInterface", t):
                svcs += ["I" + cl] if model.decl("I" + cl) else []
            for tg in targets:
                if re.search(r"\.As\s*<\s*" + re.escape(tg), t) or re.search(r"AsSelf\b", t) is None and not svcs:
                    svcs.append(tg)
            if re.search(r"AsSelf\b", t) or not svcs:
                svcs.append(cl)
            for s in dict.fromkeys(svcs):
                regs.append({"service": s, "service_args": [], "impl": cl, "lifetime": lifetime, "how": f"{c['kind']} scan",
                             "container": c["kind"], "key": None, "file": c["file"], "line": src_line, "pos": c["pos"]})


# ---------------------------------------------------------------- composition roots

def attribute_hosts(model, regs, modules):
    """Which application (host project) runs each registration: follow registration modules to the code that calls them."""
    MODULE_PARAM = re.compile(r"^\s*this\s+(IServiceCollection|IHostApplicationBuilder|WebApplicationBuilder|IHostBuilder|ContainerBuilder|"
                              r"IUnityContainer|IKernel|IWindsorContainer|Container|ServiceRegistry|Registry)\b")
    MODULE_BASES = {"Module", "NinjectModule", "Registry", "ServiceRegistry", "IWindsorInstaller", "IModule", "IServiceRegistrar"}

    def root_of(src, pos):
        md = src.enclosing(pos)
        t = src.type_at(pos)
        if md and MODULE_PARAM.match(md["params"] or ""):
            return ("ext", md["name"])
        if t and {b for b, _ in t["bases"]} & MODULE_BASES:
            return ("cls", t["name"])
        return ("host", model.project(src.rel), (md or {}).get("name") or "top-level statements")

    calls = defaultdict(list)       # module id -> [(src, pos)]
    ext_names = {md["name"] for src in model.files.values() for md in src.methods if MODULE_PARAM.match(md["params"] or "")}
    mod_classes = {t["name"] for ts in model.types.values() for t in ts if {b for b, _ in t["bases"]} & MODULE_BASES}
    for p, src in model.files.items():
        for m in re.finditer(r"\.\s*(\w+)\s*(?:<[^;{}()]*>)?\s*\(", src.mask):
            if m.group(1) in ext_names:
                md = src.enclosing(m.start())
                if md and md["name"] == m.group(1) and MODULE_PARAM.match(md["params"] or ""):
                    continue                        # the declaration itself
                calls[("ext", m.group(1))].append((src, m.start()))
        for m in re.finditer(r"(?:RegisterModule\s*<\s*|new\s+|Install\s*\(\s*new\s+|Load\s*<\s*|IncludeRegistry\s*<\s*)(\w+)\b", src.mask):
            if m.group(1) in mod_classes:
                calls[("cls", m.group(1))].append((src, m.start()))

    memo = {}

    def hosts_of(root, seen=()):
        if root[0] == "host":
            return {root[1]: [root[2]]}
        if root in memo:
            return memo[root]
        if root in seen:
            return {}
        out = defaultdict(list)
        for src, pos in calls.get(root, []):
            for h, via in hosts_of(root_of(src, pos), seen + (root,)).items():
                out[h] += via + [root[1]]
        memo[root] = dict(out)
        return memo[root]

    for r in regs:
        src = model.files[r["file"]]
        root = root_of(src, r["pos"])
        r["module"] = root[1] if root[0] != "host" else None
        hs = hosts_of(root)
        r["hosts"] = sorted(hs) or ["(registration module not called in this repository)"]
        r["via"] = sorted({v for vs in hs.values() for v in vs if v})
    return {"modules": sorted(ext_names | mod_classes), "module_calls": {k[1]: [f"{s.rel}:{s.line(p)}" for s, p in v] for k, v in calls.items()}}


# ---------------------------------------------------------------- consumers, messages, other indirections

def consumers(model):
    out = []
    for p, src in model.files.items():
        for t in src.types:
            if t["kind"] == "interface":
                continue
            ps = []
            if t["prim"] is not None and t["kind"].startswith("class"):
                ps = [dict(x, via="primary constructor") for x in params(t["prim"])]
            ctors = [md for md in src.methods if md["ctor"] and md["name"] == t["name"] and md["cls"] == t["name"] and not md["static"]]
            if ctors:
                best = max(ctors, key=lambda md: len(params(md["params"])))
                ps += [dict(x, via="constructor") for x in params(best["params"])]
            if t["body"]:
                body = src.code[t["body"][0]:t["body"][1]]
                for m in re.finditer(r"\[\s*Inject\s*\]\s*(?:public|protected|internal|private)?\s*([\w.<>?, ]+?)\s+(\w+)\s*\{", body):
                    b, a = tname(m.group(1))
                    ps.append({"type": b, "args": a, "name": m.group(2), "key": None, "attrs": "[Inject]", "via": "[Inject] property"})
            for md in src.methods:
                if md["cls"] == t["name"] and "FromServices" in (md["params"] or ""):
                    for x in params(md["params"]):
                        if "FromServices" in x["attrs"] or "FromKeyedServices" in x["attrs"]:
                            ps.append(dict(x, via=f"[FromServices] on {md['name']}"))
            if ps:
                out.append({"class": t["name"], "file": p, "line": t["line"], "params": ps, "bases": [b for b, _ in t["bases"]]})
    for p, text in model.razor:
        for m in re.finditer(r"(?m)^\s*@inject\s+([\w.<>?, ]+?)\s+(\w+)\s*$", text):
            b, a = tname(m.group(1))
            out.append({"class": os.path.basename(p), "file": p, "line": line_at(text, m.start()), "view": True,
                        "params": [{"type": b, "args": a, "name": m.group(2), "key": None, "attrs": "", "via": "@inject"}], "bases": []})
    return out


HANDLER_IFACE = re.compile(r"^I\w*(Handler|Consumer)$|^IConsumer$|^IHandleMessages$|^IHandleRequests(Async)?$|^IAmA\w*Handler$")
HANDLER_METHODS = ("Handle", "HandleAsync", "Handles", "HandlesAsync", "Consume", "ConsumeAsync", "Consumes", "Execute", "ExecuteAsync",
                   "Process", "ProcessAsync")


def message_kind(iface):
    for word, kind in (("Notification", "notification"), ("Event", "event"), ("Command", "command"), ("Query", "query"),
                       ("Request", "request"), ("Consumer", "message"), ("Messages", "message")):
        if word in iface:
            return kind
    return "message"


def messages(model):
    """message type -> {kind, handlers: [(class, method, file, line)]}; interface handlers, base-class handlers (Brighter
    RequestHandler<T>) and Wolverine-style convention handlers (class *Handler / *Consumer with Handle / Consume(T ..))."""
    out = defaultdict(lambda: {"kind": None, "handlers": [], "senders": []})
    for p, src in model.files.items():
        for t in src.types:
            if t["kind"] == "interface":
                continue
            found = []
            for b, args in t["bases"]:
                if args and (HANDLER_IFACE.match(b) or b in ("RequestHandler", "RequestHandlerAsync", "Saga")) and b not in ("IPipelineBehavior",):
                    found.append((tname(args[0])[0], message_kind(b), b))
            methods = [md for md in src.methods if md["cls"] == t["name"] and not md["ctor"]]
            if not found and re.search(r"(Handler|Consumer)$", t["name"]):
                for md in methods:
                    if md["name"] in HANDLER_METHODS:
                        ps = params(md["params"])
                        if ps and model.decl(ps[0]["type"]) and ps[0]["type"] not in FRAMEWORK:
                            found.append((ps[0]["type"], "message", "convention"))
            for msg, kind, via in found:
                hm = [md for md in methods if md["name"] in HANDLER_METHODS and (msg in md["params"] or via == "convention" or len(found) == 1)]
                for md in hm or [md for md in methods if msg in (md["params"] or "")]:
                    out[msg]["kind"] = out[msg]["kind"] or kind
                    out[msg]["handlers"].append({"class": t["name"], "method": md["name"], "file": p, "line": md["line"], "via": via})
    return out


def var_type(src, md, name, pos):
    """Declared type of a local / parameter / field named `name` visible at pos (None when unknown)."""
    body = src.code[md["body_start"]:pos] if md else ""
    head = (md["params"] if md else "") + ";"
    n = re.escape(name)
    for txt in (body, head):
        m = None
        for m in re.finditer(r"\bvar\s+" + n + r"\s*=\s*(?:await\s+)?new\s+([\w.]+(?:\s*<[^;=()]*>)?)\s*[({]", txt):
            pass
        if m:
            return tname(m.group(1))[0]
        for m in re.finditer(r"\bvar\s+" + n + r"\s*=\s*[\w.\s]*?\.\s*(?:GetRequiredService|GetService|Resolve|GetInstance|GetRequiredKeyedService|GetKeyedService)\s*<\s*([\w.<>, ]+?)\s*>", txt):
            pass
        if m:
            return tname(m.group(1))[0]
        for m in re.finditer(r"\bvar\s+" + n + r"\s*=\s*\(\s*([\w.<>]+)\s*\)", txt):
            pass
        if m:
            return tname(m.group(1))[0]
        for m in re.finditer(r"\bvar\s+" + n + r"\s*=\s*[^;]*?\bas\s+([\w.<>]+)\s*;", txt):
            pass
        if m:
            return tname(m.group(1))[0]
        for m in re.finditer(r"\bis\s+([\w.<>]+)\s+" + n + r"\b", txt):
            pass
        if m:
            return tname(m.group(1))[0]
        for m in re.finditer(r"\bforeach\s*\(\s*(?:var|([\w.<>?]+))\s+" + n + r"\s+in\s+([\w.]+)", txt):
            pass
        if m:
            if m.group(1):
                return tname(m.group(1))[0]
            coll = m.group(2).split(".")[-1]
            ct = var_type(src, md, coll, pos) or field_type(src, md, coll)
            return ct
        for m in re.finditer(r"(?<![\w.])([A-Z][\w.]*(?:\s*<[^;=()]*>)?)\??\s+" + n + r"\s*(?:[=;,)]|\bin\b)", txt):
            if m.group(1).split("<")[0] not in ("return", "new", "await", "var", "case"):
                pass
        if m and m.group(1).split("<")[0] not in ("return", "new", "await", "var", "case"):
            b, a = tname(m.group(1))
            if b in ("IEnumerable", "IList", "List", "IReadOnlyList", "IReadOnlyCollection", "ICollection", "Lazy", "Func") and a:
                return tname(a[-1])[0] if b == "Func" else tname(a[0])[0]
            return b
    return None


MODEL = None


def field_type(src, md, name, local_only=False):
    """Element / declared type of a field or primary-constructor parameter in the enclosing class (all parts of a partial class)."""
    if not md:
        return None
    parts = [(src, t) for t in src.types if t["name"] == md["cls"]]
    if MODEL and not local_only:   # other files declaring the same partial class
        parts += [(MODEL.files[t["file"]], t) for t in MODEL.types.get(md["cls"], [])
                  if t.get("partial") and t["file"] != src.rel and t["file"] in MODEL.files]
    for s, t in parts:
        if t["prim"]:
            for x in params(t["prim"]):
                if x["name"] == name:
                    return elem(x["type"], x["args"])
        if t["body"]:
            body = s.code[t["body"][0]:t["body"][1]]
            m = re.search(r"([\w.]+(?:\s*<[^;=(){}]*>)?)\??\s+" + re.escape(name) + r"\s*(?:[;=]|\{\s*get)", body)
            if m:
                b, a = tname(m.group(1))
                return elem(b, a)
    return None


FILTER_BASES = {"ActionFilterAttribute", "ExceptionFilterAttribute", "ResultFilterAttribute", "IActionFilter", "IAsyncActionFilter",
                "IResultFilter", "IAsyncResultFilter", "IExceptionFilter", "IAsyncExceptionFilter", "IAuthorizationFilter",
                "IAsyncAuthorizationFilter", "IResourceFilter", "IAsyncResourceFilter", "IPageFilter", "IAsyncPageFilter",
                "AuthorizeAttribute", "FilterAttribute"}


def attribute_filters(model, before):
    """Filter classes named by the attribute block that ends `before` (modifiers / return type may follow the attributes)."""
    m = re.search(r"((?:\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]\s*)+)" + MODS + r"(?:[\w.<>?\[\], ]+\s+)?$", before)
    if not m:
        return []
    block = m.group(1)
    out = [tname(f)[0] for f in re.findall(r"(?:ServiceFilter|TypeFilter)\s*(?:<\s*([\w.]+)\s*>|\(\s*typeof\s*\(\s*([\w.]+)\s*\))", block)
           for f in f if f]
    for a in re.findall(r"[\[,]\s*([A-Z]\w*)\s*(?=[\](,])", block):
        for cand in (a + "Attribute", a):
            t = model.decl(cand)
            if t and FILTER_BASES & (model.supertypes(cand) | {b for b, _ in t["bases"]}):
                out.append(cand)
                break
    return list(dict.fromkeys(out))


def elem(b, a):
    if b in ("IEnumerable", "IList", "List", "IReadOnlyList", "IReadOnlyCollection", "ICollection", "Lazy", "HashSet", "ISet") and a:
        return tname(a[0])[0]
    if b == "Func" and a:
        return tname(a[-1])[0]
    return b


# ---------------------------------------------------------------- graph

class Graph:
    def __init__(self, path, model, source_root, ws):
        self.path = path
        self.g = json.load(open(path, encoding="utf-8"))
        self.g["links"] = [e for e in self.g["links"] if e.get("_origin") != ORIGIN]
        self.nodes = {n["id"]: n for n in self.g["nodes"]}
        # graph source_file -> model rel path
        self.rel = {}
        roots = [os.path.abspath(source_root), os.path.abspath(ws)]
        model_abs = {os.path.normcase(os.path.abspath(os.path.join(model.root, p))): p for p in model.files}
        for n in self.g["nodes"]:
            sf = n.get("source_file")
            if sf and sf not in self.rel:
                for r in roots + [""]:
                    k = os.path.normcase(os.path.abspath(os.path.join(r, sf)))
                    if k in model_abs:
                        self.rel[sf] = model_abs[k]
                        break
        self.cls = defaultdict(list)     # (name) -> [node id]
        self.cls_at = {}                 # (rel, name) -> node id
        for i, n in self.nodes.items():
            if n.get("_callable_class") and n.get("source_file") in self.rel:
                self.cls[n["label"]].append(i)
                self.cls_at[(self.rel[n["source_file"]], n["label"])] = i
        self.members = defaultdict(list)  # class id -> [method ids]
        self.owner = {}
        for e in self.g["links"]:
            if e.get("relation") == "method":
                self.members[e["source"]].append(e["target"])
                self.owner[e["target"]] = e["source"]
        self.by_file = defaultdict(list)  # rel -> [(line, id)] methods
        for i in self.owner:
            n = self.nodes.get(i)
            if n and n.get("source_file") in self.rel:
                m = re.match(r"L(\d+)", str(n.get("source_location") or ""))
                if m:
                    self.by_file[self.rel[n["source_file"]]].append((int(m.group(1)), i))
        self.existing = defaultdict(set)
        for e in self.g["links"]:
            if e.get("relation") in CALLS:
                self.existing[e["source"]].add(e["target"])
        self.added = []
        self.kinds = Counter()

    @staticmethod
    def mname(n):
        return re.sub(r"\(.*$", "", str(n.get("label") or "")).lstrip(".")

    def class_ids(self, name, model):
        ids = []
        for t in model.types.get(name, []):
            i = self.cls_at.get((t["file"], name))
            if i:
                ids.append(i)
        return ids or self.cls.get(name, [])

    def methods_of(self, cls_name, model, name=None, inherit=True):
        out, seen, todo = [], set(), [cls_name]
        while todo:
            c = todo.pop(0)
            if c in seen:
                continue
            seen.add(c)
            for ci in self.class_ids(c, model):
                for mi in self.members.get(ci, []):
                    if name is None or self.mname(self.nodes[mi]) == name:
                        out.append(mi)
            if out and name is not None or not inherit:
                break
            todo += [b for t in model.types.get(c, []) for b, _ in t["bases"] if model.decl(b) and model.decl(b)["kind"] != "interface"]
        return out

    def method_at(self, rel, line, name=None):
        """Graph node of the method declared at `line` (or the nearest one above it) in rel."""
        cands = [(ln, i) for ln, i in self.by_file.get(rel, []) if ln <= line + 1 and (name is None or self.mname(self.nodes[i]) == name)]
        return max(cands)[1] if cands else None

    def add(self, s, t, kind, conf, score, rel_file, line, meta, relation="dispatches_to"):
        if not s or not t or s == t or t in self.existing[s]:
            return False
        self.existing[s].add(t)
        sf = self.nodes[s].get("source_file") or rel_file
        self.added.append({"source": s, "target": t, "relation": relation, "_origin": ORIGIN, "confidence": conf, "confidence_score": score,
                           "context": kind, "source_file": sf, "source_location": f"L{line}" if line else None, "weight": 1.0,
                           "metadata": meta})
        self.kinds[kind] += 1
        return True

    def save(self):
        self.g["links"] += self.added
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.g, f, ensure_ascii=False)
        os.replace(tmp, self.path)


def resolve(model, G, regs, msgs, locators, opts, facts):
    max_impl = opts.get("max_implementers", 6)
    registered, keyed = defaultdict(list), defaultdict(list)
    for r in regs:
        if r.get("impl") and r["impl"] != r["service"]:
            # keyed implementations are only reachable through their key (E4), never through a plain injection
            (keyed if r.get("key") else registered)[r["service"]].append(r)
    services_any = {r["service"] for r in regs}

    def iface_methods(svc):
        names = [svc] + sorted(b for b in model.supertypes(svc) if model.decl(b))
        out = []
        for n in names:
            for ci in G.class_ids(n, model):
                out += G.members.get(ci, [])
        return out

    # E1 registration dispatch
    for svc, rs in registered.items():
        for mi in iface_methods(svc):
            nm = G.mname(G.nodes[mi])
            for r in rs:
                for ti in G.methods_of(r["impl"], model, nm):
                    G.add(mi, ti, "di registration" if r["how"] != "decorator" else "di decorator", "INFERRED", 0.9, r["file"], r["line"],
                          {"service": svc, "impl": r["impl"], "lifetime": r["lifetime"], "key": r["key"], "how": r["how"],
                           "registered_at": f"{r['file']}:{r['line']}", "hosts": r.get("hosts")})
    # E2 implementer dispatch (no registration seen) and E3 override dispatch
    for name, ts in model.types.items():
        t = ts[0]
        is_iface = t["kind"] == "interface"
        if not (is_iface or t["kind"].startswith("class")):
            continue
        if name in services_any and (registered.get(name) or keyed.get(name)):
            continue
        impls = sorted(model.implementers(name))
        if not impls:
            continue
        if is_iface and len(impls) > max_impl:
            facts["skipped_wide"].append({"type": name, "implementers": len(impls)})
            continue
        for mi in [x for ci in G.class_ids(name, model) for x in G.members.get(ci, [])]:
            nm = G.mname(G.nodes[mi])
            if not is_iface:
                src = model.files[t["file"]]
                decl = next((md for md in src.methods if md["cls"] == name and md["name"] == nm), None)
                if not decl or not (decl["abstract"] or decl["virtual"] or decl["override"]):
                    continue
            for impl in impls:
                own = [x for x in G.methods_of(impl, model, nm, inherit=False)]
                for ti in own:
                    if is_iface:
                        G.add(mi, ti, "implementation (no registration found)" if len(impls) > 1 else "only implementation",
                              "AMBIGUOUS" if len(impls) > 1 else "INFERRED", 0.5 if len(impls) > 1 else 0.8, t["file"], None,
                              {"service": name, "impl": impl, "implementers": len(impls)})
                    else:
                        G.add(mi, ti, "override", "INFERRED", 0.8, t["file"], None, {"base": name, "derived": impl})
    # E4 keyed narrowing
    for c in facts["consumers"]:
        for x in c["params"]:
            if not x.get("key"):
                continue
            impls = [r for r in keyed.get(x["type"], []) if r.get("key") == x["key"]]
            if not impls:
                continue
            for ci in G.class_ids(c["class"], model):
                for cm in G.members.get(ci, []):
                    for tgt in list(G.existing.get(cm, ())):
                        if G.owner.get(tgt) in G.class_ids(x["type"], model):
                            for r in impls:
                                for ti in G.methods_of(r["impl"], model, G.mname(G.nodes[tgt])):
                                    G.add(cm, ti, "keyed service", "INFERRED", 0.85, c["file"], c["line"],
                                          {"service": x["type"], "key": x["key"], "impl": r["impl"]})
    # E5 messages, E6 locals, E7 events, E8 method groups, E9 jobs, E10 redirects, E11 filters
    DISPATCH = re.compile(r"\.\s*(\w*(?:Send|Publish|Dispatch|Raise|Notify|Enqueue|Schedule|Execute|Handle|Request|Query|Command|Process|Bus)\w*)"
                          r"\s*(?:<\s*([\w.<>, ]+?)\s*>)?\s*\(")
    sent = Counter()
    for p, src in model.files.items():
        M, C = src.mask, src.code
        # E5
        for m in DISPATCH.finditer(M):
            j = match(M, m.end() - 1)
            if j < 0:
                continue
            args = split_top(C[m.end():j])
            md = src.enclosing(m.start())
            if not md:
                continue
            msg = None
            if m.group(2) and tname(m.group(2))[0] in msgs:
                msg = tname(m.group(2))[0]
            elif args:
                a0 = args[0]
                nm = re.match(r"new\s+([\w.]+)", a0)
                if nm:
                    msg = tname(nm.group(1))[0]
                elif re.match(r"^[A-Za-z_]\w*$", a0):
                    msg = var_type(src, md, a0, m.start())
            if not msg or msg not in msgs:
                continue
            caller = G.method_at(p, md["line"], md["name"])
            msgs[msg]["senders"].append({"file": p, "line": src.line(m.start()), "method": md["name"], "cls": md["cls"], "verb": m.group(1)})
            for h in msgs[msg]["handlers"]:
                for ti in G.methods_of(h["class"], model, h["method"], inherit=False):
                    if G.add(caller, ti, "message", "INFERRED", 0.85, p, src.line(m.start()), {"message": msg, "verb": m.group(1), "handler": h["class"]}):
                        sent[msg] += 1
        # E6 local variables: v.M( where v is a local whose type we can read; also fields declared in another part of a
        # partial class (graphify only sees the fields of the file it is reading)
        for md in src.methods:
            body = M[md["body_start"]:md["end"]]
            caller = None
            for m in re.finditer(r"(?<![\w.])([a-z_]\w*)\s*\??\.\s*([A-Z]\w*)\s*(?:<[^;{}()]*>)?\s*\(", body):
                var, meth = m.group(1), m.group(2)
                if var in KEYWORDS:
                    continue
                pos = md["body_start"] + m.start()
                ty, kind = var_type(src, md, var, pos), "local variable"
                if not ty and not field_type(src, md, var, local_only=True):
                    ty, kind = field_type(src, md, var), "partial class field"
                if not ty or not model.decl(ty):
                    continue
                caller = caller or G.method_at(p, md["line"], md["name"])
                if not caller:
                    break
                if any(G.mname(G.nodes[x]) == meth for x in G.existing.get(caller, ()) if x in G.nodes):
                    continue
                for ti in G.methods_of(ty, model, meth) or [x for b in sorted(model.supertypes(ty)) for x in G.methods_of(b, model, meth)]:
                    G.add(caller, ti, kind, "INFERRED", 0.8, p, src.line(pos), {"variable": var, "type": ty}, relation="calls")
        # E7 events / delegates
        for m in re.finditer(r"(?<![\w])([\w.]+?)\.?\b([A-Z]\w*)\s*(\+=|=)\s*(?:new\s+[\w.<>]+\s*\(\s*)?(?:this\.)?([A-Za-z_]\w*)\s*\)?\s*;", M):
            target_member, op, handler = m.group(2), m.group(3), m.group(4)
            md = src.enclosing(m.start())
            if not md:
                continue
            owner = md["cls"]
            if not any(x["cls"] == owner and x["name"] == handler for x in src.methods):
                continue                                    # right side is not a method of this class
            facts["events"].append({"member": target_member, "handler": handler, "cls": owner, "file": p, "line": src.line(m.start()), "op": op})
        # E8 method groups
        for m in re.finditer(r"[(,]\s*(?:this\.)?([A-Z]\w*)\s*(?=[),])", M):
            name = m.group(1)
            md = src.enclosing(m.start())
            if not md or name == md["name"]:
                continue
            if not any(x["cls"] == md["cls"] and x["name"] == name and not x["ctor"] for x in src.methods):
                continue
            pre = M[max(0, m.start() - 80):m.start() + 1]
            if re.search(r"\bnameof\s*\($", pre) or re.search(r"\btypeof\s*\($", pre):
                continue
            caller = G.method_at(p, md["line"], md["name"])
            for ti in G.methods_of(md["cls"], model, name, inherit=False):
                G.add(caller, ti, "method group", "INFERRED", 0.8, p, src.line(m.start()), {"method": name}, relation="calls")
        # E9 background jobs: Hangfire Enqueue<T>(x => x.M()), Quartz JobBuilder.Create<T>()
        for m in re.finditer(r"\b(BackgroundJob|RecurringJob|\w*[jJ]ob[Cc]lient|\w*[Jj]obManager|_\w+)\s*\.\s*(Enqueue|Schedule|AddOrUpdate|ContinueJobWith|Create)\s*<\s*([\w.<>]+?)\s*>\s*\(", M):
            j = match(M, m.end() - 1)
            md = src.enclosing(m.start())
            if j < 0 or not md:
                continue
            ty = tname(m.group(3))[0]
            lam = re.search(r"\b(\w+)\s*=>\s*(?:await\s+)?\1\s*\.\s*(\w+)\s*\(", C[m.end():j])
            if not lam or not model.decl(ty):
                continue
            caller = G.method_at(p, md["line"], md["name"])
            facts["jobs"].append({"type": ty, "method": lam.group(2), "api": f"{m.group(1)}.{m.group(2)}", "file": p, "line": src.line(m.start()),
                                  "caller": md["name"], "cls": md["cls"]})
            for ti in G.methods_of(ty, model, lam.group(2)):
                G.add(caller, ti, "background job", "INFERRED", 0.85, p, src.line(m.start()), {"api": m.group(2), "type": ty}, relation="calls")
        for m in re.finditer(r"\bJobBuilder\s*\.\s*Create\s*<\s*([\w.]+)\s*>|\.\s*AddJob\s*<\s*([\w.]+)\s*>", M):
            ty = tname(m.group(1) or m.group(2))[0]
            md = src.enclosing(m.start())
            facts["jobs"].append({"type": ty, "method": "Execute", "api": "Quartz", "file": p, "line": src.line(m.start()),
                                  "caller": md["name"] if md else None, "cls": md["cls"] if md else None})
            if md:
                caller = G.method_at(p, md["line"], md["name"])
                for ti in G.methods_of(ty, model, "Execute"):
                    G.add(caller, ti, "background job", "INFERRED", 0.8, p, src.line(m.start()), {"api": "Quartz", "type": ty}, relation="calls")
        # E10 MVC transfers
        for m in re.finditer(r"\bRedirectToAction(?:Permanent)?\s*\(", M):
            j = match(M, m.end() - 1)
            md = src.enclosing(m.start())
            if j < 0 or not md:
                continue
            args = split_top(C[m.end():j])
            if not args:
                continue
            action = literal(args[0])
            ctl = md["cls"]
            if len(args) > 1 and re.match(r'^@?"|^nameof', args[1].strip()):
                ctl = literal(args[1])
                ctl = ctl if ctl.endswith("Controller") else ctl + "Controller"
            caller = G.method_at(p, md["line"], md["name"])
            for ti in G.methods_of(ctl, model, action):
                G.add(caller, ti, "redirect", "INFERRED", 0.8, p, src.line(m.start()), {"action": action, "controller": ctl}, relation="calls")
        # E11 filters applied by attribute, on a controller (every action) or on one action
        targets = [(t["start"], t["name"], None, t["line"]) for t in src.types if t["kind"].startswith("class")]
        targets += [(md["start"], md["cls"], md["name"], md["line"]) for md in src.methods if md["cls"] and not md["ctor"]]
        for pos, cls, meth, ln in targets:
            for fname in attribute_filters(model, C[max(0, pos - 800):pos]):
                hooks = [x for x in G.methods_of(fname, model) if re.match(r"On\w+", G.mname(G.nodes[x]))]
                facts["pipeline"].append({"kind": "MVC filter (attribute)", "type": fname, "file": p, "line": ln,
                                          "applies_to": cls + (f".{meth}" if meth else "")})
                for ci in G.class_ids(cls, model):
                    for am in G.members.get(ci, []):
                        if meth and G.mname(G.nodes[am]) != meth:
                            continue
                        for h in hooks:
                            G.add(am, h, "filter", "INFERRED", 0.75, p, ln, {"filter": fname})
    # E7 second half: raise sites -> subscribed handlers
    subs = defaultdict(list)
    for ev in facts["events"]:
        subs[ev["member"]].append(ev)
    for p, src in model.files.items():
        for m in re.finditer(r"(?<![\w.])([A-Z]\w*)\s*\??\.\s*(?:Invoke|BeginInvoke|DynamicInvoke)\s*\(|(?<![\w.])([A-Z]\w*)\s*\(\s*this\s*,", src.mask):
            name = m.group(1) or m.group(2)
            if name not in subs:
                continue
            md = src.enclosing(m.start())
            if not md:
                continue
            caller = G.method_at(p, md["line"], md["name"])
            for ev in subs[name]:
                for ti in G.methods_of(ev["cls"], model, ev["handler"], inherit=False):
                    G.add(caller, ti, "event", "INFERRED", 0.75, p, src.line(m.start()), {"event": name, "subscriber": ev["cls"]})
    stored_delegates(model, G, facts)
    dispatch_tables(model, G, facts)
    # E6 for service-locator results used without a local variable: sp.GetRequiredService<T>().M()
    for loc in locators:
        src = model.files[loc["file"]]
        m = re.compile(r"\.\s*\w+\s*<[^;]*?>\s*\(\s*\)\s*\.\s*([A-Z]\w*)\s*\(").match(src.mask, loc["pos"])
        md = src.enclosing(loc["pos"])
        if m and md:
            caller = G.method_at(loc["file"], md["line"], md["name"])
            for ti in G.methods_of(loc["type"], model, m.group(1)):
                G.add(caller, ti, "service locator", "INFERRED", 0.8, loc["file"], loc["line"], {"type": loc["type"]}, relation="calls")


DELEGATE_TYPE = re.compile(r"^(Func|Action|Predicate|Converter|Comparison|EventHandler|RequestDelegate|AsyncCallback)$")


def delegate_types(model):
    """Delegate type names: the framework ones plus every `delegate R Name(...)` declared in the repository."""
    names = set()
    for src in model.files.values():
        names |= set(re.findall(r"\bdelegate\s+[\w.<>\[\]?, ]+?\s+(\w+)\s*(?:<[^()]*>)?\s*\(", src.mask))
    return names


def stored_delegates(model, G, facts):
    """E12: a type holding a delegate member (record parameter, property, field) whose instances are built with lambdas in one
    place and invoked in another: the invoking method calls (at run time) the lambdas, which graphify attributes to the
    method that built them -- so link invoker -> builder methods."""
    custom = delegate_types(model)

    def is_delegate(t):
        return bool(DELEGATE_TYPE.match(t)) or t in custom

    members = defaultdict(set)    # type name -> delegate member names
    for name, ts in model.types.items():
        for t in ts:
            for x in params(t["prim"]) if t["prim"] else []:
                if is_delegate(x["type"]):
                    members[name].add(x["name"])
            if t["body"]:
                body = model.files[t["file"]].mask[t["body"][0]:t["body"][1]]
                code = model.files[t["file"]].code[t["body"][0]:t["body"][1]]
                for m in re.finditer(r"(?:public|internal|protected|private)?\s*(?:readonly\s+|required\s+)?([\w.]+)\s*(?:<[^;{}()=]*>)?\??\s+([A-Z_]\w*)\s*(?:\{|;|=)", body):
                    if is_delegate(tname(code[m.start(1):m.end(1)])[0]) and m.group(2) not in ("get", "set"):
                        members[name].add(m.group(2))
    if not members:
        return
    builders = defaultdict(set)   # type -> {(file, method name, line)}
    for p, src in model.files.items():
        for md in src.methods:
            body_m = src.mask[md["body_start"]:md["end"]]
            for t in members:
                hit = re.search(r"\bnew\s+(?:[\w.]+\.)?" + re.escape(t) + r"\s*[({]", body_m)
                if not hit and re.search(r"\bnew\s*\(", body_m) and re.search(r"\b" + re.escape(t) + r"\b", md.get("ret") or ""):
                    hit = True                       # target-typed new(...) in a method returning T / IEnumerable<T>
                if hit and ("=>" in body_m or "delegate" in body_m):
                    builders[t].add((p, md["name"], md["line"]))
    for p, src in model.files.items():
        for md in src.methods:
            body = src.mask[md["body_start"]:md["end"]]
            for t, mems in members.items():
                if not builders.get(t):
                    continue
                for m in re.finditer(r"(?<![\w.])([a-z_]\w*)\s*\.\s*(" + "|".join(map(re.escape, mems)) + r")\s*(?:\?\s*\.\s*Invoke|\.\s*Invoke)?\s*\(", body):
                    pos = md["body_start"] + m.start()
                    vt = var_type(src, md, m.group(1), pos) or field_type(src, md, m.group(1))
                    if vt != t:
                        continue
                    caller = G.method_at(p, md["line"], md["name"])
                    for bf, bn, bl in builders[t]:
                        target = G.method_at(bf, bl, bn)
                        if target and G.add(caller, target, "stored delegate", "INFERRED", 0.7, p, src.line(pos),
                                            {"type": t, "member": m.group(2), "builder": bn}, relation="calls"):
                            facts.setdefault("stored_delegates", []).append({"type": t, "member": m.group(2), "invoker": md["name"],
                                                                              "invoker_cls": md["cls"], "file": p, "line": src.line(pos),
                                                                              "builder": bn, "builder_file": bf, "builder_line": bl})


def dispatch_tables(model, G, facts):
    """E13: Dictionary<K, Func/Action/delegate> tables filled with method groups and invoked by key: table[key](..)."""
    custom = delegate_types(model)
    for p, src in model.files.items():
        M, C = src.mask, src.code
        for t in src.types:
            if not t["body"]:
                continue
            body = C[t["body"][0]:t["body"][1]]
            for m in re.finditer(r"(?:I?Dictionary|IReadOnlyDictionary|ConcurrentDictionary|FrozenDictionary)\s*<\s*[\w.?]+\s*,\s*([\w.]+)\s*(?:<[^;{}()]*>)?\s*>\??\s+(\w+)", body):
                if not (DELEGATE_TYPE.match(tname(m.group(1))[0]) or tname(m.group(1))[0] in custom):
                    continue
                table = m.group(2)
                own = {md["name"] for md in src.methods if md["cls"] == t["name"] and not md["ctor"]}
                entries = set(re.findall(r"\{\s*[^{},]+,\s*(?:this\.)?([A-Z]\w*)\s*\}", body))          # { "x", Handle }
                entries |= set(re.findall(r"\[[^\]]+\]\s*=\s*(?:this\.)?([A-Z]\w*)\s*[,;}\n]", body))  # ["x"] = Handle
                entries |= set(re.findall(re.escape(table) + r"\s*\.\s*(?:Add|TryAdd)\s*\(\s*[^,]+,\s*(?:this\.)?([A-Z]\w*)\s*\)", body))
                entries &= own
                if not entries:
                    continue
                for im in re.finditer(r"\b" + re.escape(table) + r"\s*\[[^\]]+\]\s*(?:\?\s*\.\s*Invoke|\.\s*Invoke)?\s*\(", M[t["body"][0]:t["body"][1]]):
                    pos = t["body"][0] + im.start()
                    md = src.enclosing(pos)
                    if not md:
                        continue
                    caller = G.method_at(p, md["line"], md["name"])
                    for e in entries:
                        for ti in G.methods_of(t["name"], model, e, inherit=False):
                            G.add(caller, ti, "dispatch table", "INFERRED", 0.75, p, src.line(pos), {"table": table, "method": e}, relation="calls")
                facts.setdefault("dispatch_tables", []).append({"cls": t["name"], "table": table, "methods": sorted(entries), "file": p,
                                                                 "line": src.line(t["body"][0] + m.start())})


REFLECTION = re.compile(r"\bActivator\s*\.\s*CreateInstance\b[^;]{0,80}|\bType\s*\.\s*GetType\s*\([^;]{0,80}|\bAssembly\s*\.\s*Load\w*\s*\([^;]{0,60}|"
                        r"\.\s*GetMethod\s*\([^;]{0,80}|\.\s*InvokeMember\s*\([^;]{0,60}|\bMethodInfo\b[^;]{0,60}\.\s*Invoke\s*\(|"
                        r"\bdynamic\s+\w+\s*=[^;]{0,60}|\bProxyGenerator\b[^;]{0,60}|\bDispatchProxy\b[^;]{0,60}")


def reflection(model):
    out = []
    for p, src in model.files.items():
        for m in REFLECTION.finditer(src.mask):
            text = src.code[m.start():m.end()]
            if re.search(r"\bnameof\s*\(", text):
                continue  # GetMethod(nameof(X)) (EF HasDbFunction etc.): the compiler checks the name, so it is not decided at run time
            out.append({"text": re.sub(r"\s+", " ", text)[:120], "file": p, "line": src.line(m.start())})
    return out


# ---------------------------------------------------------------- findings

def findings(model, regs, cons, locators, conventions, msgs, containers):
    out = []
    by_host = defaultdict(lambda: defaultdict(list))
    for r in regs:
        for h in r.get("hosts") or []:
            by_host[h][r["service"]].append(r)
    any_reg = {r["service"] for r in regs}
    has_scan = bool(conventions)
    msdi_only = set(containers) <= {"msdi", "scrutor", "mediatr"}
    activated = {r["impl"] for r in regs}
    for c in cons:
        bases = set(c.get("bases") or [])
        if c.get("view") or c["class"].endswith("Controller") or bases & {"Controller", "ControllerBase", "PageModel", "ViewComponent", "Hub",
                                                                          "ComponentBase", "BackgroundService"}:
            activated.add(c["class"])
    for msg in msgs.values():
        activated |= {h["class"] for h in msg["handlers"]}
    for c in cons:
        if c["class"] not in activated:
            continue
        for x in c["params"]:
            t = x.get("needs") or x["type"]
            if x["type"] in ("IEnumerable", "IReadOnlyList", "IList", "ICollection", "IReadOnlyCollection"):
                continue                            # an empty collection is valid when nothing is registered
            if t in FRAMEWORK or not model.decl(t) or t in any_reg:
                continue
            if not model.is_abstraction(t) and not msdi_only:
                continue
            resolved_by_scan = any(t in (cv.get("resolved") or []) for cv in conventions)
            if resolved_by_scan:
                continue
            out.append({"kind": "possibly missing registration" if has_scan else "missing registration", "severity": "medium" if has_scan else "high",
                        "text": f"{c['class']} needs {t} ({x['via']}) but no registration for {t} was found"
                                + (" (assembly scanning is used, so it may be registered by convention)" if has_scan else ""),
                        "file": c["file"], "line": c["line"], "class": c["class"], "type": t})
    # captive dependencies: singleton -> scoped, per host
    lt_of = defaultdict(dict)
    for h, svcs in by_host.items():
        for s, rs in svcs.items():
            real = [r for r in rs if r["how"] != "decorator"] or rs
            lt_of[h][s] = real[-1]["lifetime"]
            for r in real:
                lt_of[h].setdefault(r["impl"], r["lifetime"])
    cons_of = {c["class"]: c for c in cons}
    for h, lts in lt_of.items():
        for impl, lt in lts.items():
            if lt != "Singleton" or impl not in cons_of:
                continue
            for x in cons_of[impl]["params"]:
                dep_lt = lts.get(x["type"])
                if dep_lt == "Scoped":
                    out.append({"kind": "captive dependency", "severity": "high",
                                "text": f"{impl} is a singleton in {h} but depends on {x['type']}, which is scoped there: the scoped instance "
                                        "lives for the whole application (stale DbContext / per-request state, thread-safety issues)",
                                "file": cons_of[impl]["file"], "line": cons_of[impl]["line"], "class": impl, "type": x["type"]})
    # duplicate registrations of one service in one host (last one wins for single injection)
    for h, svcs in by_host.items():
        for s, rs in svcs.items():
            plain = [r for r in rs if not r.get("key") and r["how"] not in ("decorator",) and r["impl"]]
            impls = {r["impl"] for r in plain}
            if len(impls) > 1:
                out.append({"kind": "multiple registrations", "severity": "info",
                            "text": f"{s} has {len(impls)} registrations in {h} ({', '.join(sorted(impls))}): a single injection gets the last one, "
                                    "IEnumerable<" + s + "> gets all", "file": plain[-1]["file"], "line": plain[-1]["line"], "type": s})
    roots = {r["file"] for r in regs}
    per_cls = defaultdict(list)
    for loc in locators:
        if loc["file"] not in roots:
            per_cls[(loc["cls"] or "?", loc["file"])].append(loc)
    for (c, f), locs in per_cls.items():
        types_ = sorted({l["type"] for l in locs})
        meths = sorted({l["method"] or "?" for l in locs})
        out.append({"kind": "service locator", "severity": "low",
                    "text": f"{c} resolves {len(types_)} service type(s) from the container at run time in {len(meths)} method(s) "
                            f"({', '.join(types_[:8])}{' …' if len(types_) > 8 else ''}): these dependencies are hidden from the "
                            "constructor (normal inside a scope created by a singleton or hosted service)",
                    "file": f, "line": locs[0]["line"], "class": c, "count": len(locs)})
    for msg, d in msgs.items():
        if d["kind"] in ("request", "command", "query") and len({h["class"] for h in d["handlers"]}) > 1:
            out.append({"kind": "several handlers", "severity": "medium",
                        "text": f"{msg} ({d['kind']}) has {len(d['handlers'])} handlers; request-style messages normally have exactly one",
                        "file": d["handlers"][0]["file"], "line": d["handlers"][0]["line"], "type": msg})
        if not d["senders"]:
            out.append({"kind": "message never sent", "severity": "info", "text": f"no Send / Publish of {msg} found in the code (sent from outside, "
                        "by reflection, or dead)", "file": d["handlers"][0]["file"], "line": d["handlers"][0]["line"], "type": msg})
    return out


# ---------------------------------------------------------------- main

def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--source-root", help="standalone use (no codebase-docs.json): the code to read")
    ap.add_argument("--graph-dir", help="standalone use: folder holding graph.json; csharp-resolve.json is written there")
    a = ap.parse_args()
    if a.source_root and a.graph_dir:      # e.g. migration-assessment's map_graphs.py
        root, cfg = os.getcwd(), {"source_root": a.source_root, "graph_dir": a.graph_dir, "adapter_options": {}}
    else:
        root, cfg = load_config()
    os.chdir(root)
    opts = cfg.get("adapter_options", {}).get("generic-di", {})
    src_root = cfg["source_root"]
    model = Model(src_root, opts.get("skip_regex"))
    if not model.files:
        print("csharp-resolve: no C# files under the source root; nothing to do")
        return
    regs, modules, conventions, options_b, locators, pipeline, notes, containers = scan(model)
    apply_conventions(model, conventions, regs)
    comp = attribute_hosts(model, regs, modules)
    cons = consumers(model)
    msgs = messages(model)
    facts = {"consumers": cons, "events": [], "jobs": [], "pipeline": pipeline, "skipped_wide": []}
    gpath = os.path.join(cfg["graph_dir"], "graph.json")
    edges = Counter()
    if not a.scan_only and os.path.exists(gpath):
        G = Graph(gpath, model, src_root, root)
        resolve(model, G, regs, msgs, locators, opts, facts)
        G.save()
        edges = G.kinds
    finds = findings(model, regs, cons, locators, conventions, msgs, containers)
    for r in regs:
        r.pop("pos", None)
    for c in conventions:
        c.pop("pos", None)
    for l in locators:
        l.pop("pos", None)
    types = {n: {"kind": ts[0]["kind"], "file": ts[0]["file"], "line": ts[0]["line"], "namespace": ts[0]["namespace"],
                 "abstract": ts[0]["abstract"], "bases": [b for b, _ in ts[0]["bases"]], "project": model.project(ts[0]["file"])}
             for n, ts in model.types.items()}
    out = {"generated_by": "csharp_resolve.py", "containers": dict(containers), "registrations": regs, "composition": comp,
           "conventions": conventions, "options": options_b, "consumers": cons,
           "messages": {k: dict(v) for k, v in msgs.items()}, "locators": locators, "pipeline": facts["pipeline"], "events": facts["events"],
           "jobs": facts["jobs"], "notes": notes, "reflection": reflection(model), "partials": model.partials(),
           "stored_delegates": facts.get("stored_delegates", []), "dispatch_tables": facts.get("dispatch_tables", []), "findings": finds, "edges_added": dict(edges), "skipped_wide": facts["skipped_wide"],
           "types": types, "files_scanned": len(model.files)}
    write(os.path.join(cfg["graph_dir"], "csharp-resolve.json"), json.dumps(out, indent=1, ensure_ascii=False))
    if not a.quiet:
        hosts = sorted({h for r in regs for h in r.get("hosts", [])})
        print(f"csharp-resolve: {len(model.files)} C# files · {len(regs)} registrations ({', '.join(f'{k} {v}' for k, v in containers.most_common())}) "
              f"in {len(hosts)} host(s) · {len(cons)} consumers · {len(msgs)} message types · {len(finds)} findings")
        print("  edges added: " + (", ".join(f"{k} {v}" for k, v in edges.most_common()) or "none") + (" (scan only)" if a.scan_only else ""))


if __name__ == "__main__":
    main()
