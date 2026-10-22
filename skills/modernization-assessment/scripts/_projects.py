"""Every project in the estate as one unit of migration work: what it is, how hard it is to port, its 7R (class libraries
and test projects too, not only deployables), what it needs ported first, what depends on it (blast radius) and the
wave it belongs to. Pure functions over data the other steps wrote; build_report, build_html_report, build_summary,
build_tracker and classify_apps all call build().

    model = build(inventories, findings, classification, analyses, cfg, decisions)

Dependencies come from three places, each edge labelled with its source:
  project reference      <ProjectReference> in the .csproj / .vbproj
  code (graph)           calls between projects that graphify saw (analysis.json project_edges), when no reference exists
  DLL from <repo>        a <Reference> to an assembly another repository of the estate builds (cross-repository)
Blast radius = how much breaks or must be retested when the project changes: projects that depend on it directly and
transitively, the deployables among them, and the code fan-in (how many other files use code in the project, from the
graph). Waves: a project moves after everything it depends on (wave 1 = depends on nothing in the estate); projects in
one dependency cycle share a wave. Inside a wave, shared code that unblocks most goes first, then by difficulty.
"""
import os
import re
from collections import defaultdict

# type slug -> (display kind, porting group)
KIND = {
    "aspnet-core": ("ASP.NET Core app / API", "modern"), "aspnet-webapi": ("Web API", "api"), "web-service": ("ASMX web service", "api"),
    "wcf-service": ("WCF service", "service"), "aspnet-mvc": ("MVC web app", "ui"), "aspnet-webforms": ("Web Forms app", "webforms"),
    "website": ("ASP.NET website (Web Forms)", "webforms"), "class-library": ("Class library", "lib"), "web-library": ("Web library", "lib"),
    "netcore-other": (".NET library", "lib"), "console": ("Console app", "job"), "netcore-console": ("Console app", "job"),
    "netcore-worker": ("Worker service", "job"), "windows-service": ("Windows service", "service"), "winforms": ("WinForms desktop app", "desktop"),
    "wpf": ("WPF desktop app", "desktop"), "windows-desktop": ("Windows desktop app", "desktop"), "wcf-desktop": ("WCF desktop client", "desktop"),
    "test": ("Test project", "test"), "database": ("Database project", "db"),
}
# porting group -> base difficulty and why (what a .NET developer has to do)
BASE = {
    "lib": (1, "class library: retarget the project file, fix API gaps"),
    "api": (1, "API: controllers / handlers move to ASP.NET Core with their logic intact"),
    "modern": (1, "already modern .NET: retarget the TFM"),
    "job": (1, "console / worker: retarget, swap the host builder"),
    "test": (1, "test project: moves with the code it tests"),
    "db": (1, "database project: no .NET port"),
    "service": (2, "service host: Windows service / WCF hosting must become a Worker Service, CoreWCF or ASP.NET Core"),
    "ui": (2, "MVC UI: views, bundling, filters and auth move to ASP.NET Core MVC"),
    "webforms": (3, "Web Forms UI: no ASP.NET Core equivalent, pages are rewritten (Razor Pages / Blazor)"),
    "desktop": (3, "desktop UI: stays on Windows (.NET 10 Windows Desktop) or is rewritten"),
}
LEVEL = {1: "Easy", 2: "Medium", 3: "Hard"}
WINDOWS_BOUND = re.compile(r"^(INTEROP-|WIN-|COM-|API-REMOTING|WCF-BINDING|DESK-|OFFICE-|CRYSTAL|WF-|WIN32)", re.I)
SYSTEM_WEB = {"WEB-SYSTEMWEB", "WEB-HTTPCONTEXT-CURRENT", "WEB-WEBFORMS-UI", "WEB-HTTPMODULES"}
MODERN_TFM = re.compile(r"^net(\d+)\.\d+|^netcoreapp|^netstandard", re.I)


def _tfm_major(tfms):
    for t in tfms or []:
        m = re.match(r"^net(\d+)\.\d+", t or "")
        if m:
            return int(m.group(1))
    return 0


def _loc(p):
    """Lines of code: loc_code, else the per-language counts without generated code and config (older inventories)."""
    if isinstance(p.get("loc_code"), int):
        return p["loc_code"]
    loc = p.get("loc") or 0
    return sum(v for k, v in loc.items() if k not in ("generated", "config") and isinstance(v, int)) if isinstance(loc, dict) else int(loc)


def _token_ui(app):
    """A Web Forms project that is really an API: few pages, little markup (classify_apps' own test)."""
    return app and app.get("type") in ("aspnet-webforms", "website") and str(app.get("r7", "")).startswith("Replatform") and (app.get("web_forms_pages") or 0) <= 3


def build(invs, findings, cls, analyses=None, cfg=None, decisions=None):
    cfg, analyses, decisions = cfg or {}, analyses or {}, decisions or {}
    target = cfg.get("target_dotnet", "net10.0")
    apps = cls.get("applications", []) if cls else []
    app_by_entry = {(a["repo"], a["entry"]): a for a in apps}
    hybrid = {(h["repo"], h["path"]): h for h in (cls or {}).get("hybrid", [])}
    nodes = {}
    asm = {}  # assembly name -> project key, across the estate
    for repo, inv in invs.items():
        for p in (inv or {}).get("projects", []):
            key = f"{repo}:{p['path']}"
            asm.setdefault((p.get("assembly_name") or p["name"]).lower(), key)
            nodes[key] = {"key": key, "repo": repo, "path": p["path"], "name": p["name"], "type": p.get("type", ""), "deployable": bool(p.get("deployable")),
                          "tfm": ", ".join(p.get("target_frameworks") or []), "family": p.get("framework_family", ""), "loc": _loc(p),
                          "_p": p, "deps": {}, "users": {}}
    # ---- edges
    for key, n in nodes.items():
        p, repo = n["_p"], n["repo"]
        for r in p.get("project_references") or []:
            k = f"{repo}:{r}"
            if k in nodes and k != key:
                n["deps"][k] = "project reference"
        for r in p.get("references") or []:
            name = (r if isinstance(r, str) else (r.get("name") or "")).split(",")[0].strip().lower()
            k = asm.get(name)
            if k and k != key and k not in n["deps"]:
                n["deps"][k] = "project reference" if nodes[k]["repo"] == repo else f"DLL from {nodes[k]['repo']}"
        for b in p.get("binary_references") or []:
            k = asm.get((b.get("name") or "").lower())
            if k and k != key and k not in n["deps"]:
                n["deps"][k] = f"DLL from {nodes[k]['repo']}" if nodes[k]["repo"] != repo else "DLL (same repository)"
    for repo, g in analyses.items():
        by_name = {nodes[k]["name"]: k for k in nodes if nodes[k]["repo"] == repo}
        for e in (g or {}).get("project_edges", []):
            a, z = by_name.get(e.get("from")), by_name.get(e.get("to"))
            if a and z and a != z and z not in nodes[a]["deps"]:
                nodes[a]["deps"][z] = "code (graph)"
    for k, n in nodes.items():
        for d, how in n["deps"].items():
            nodes[d]["users"][k] = how
    # ---- findings per project
    fby = defaultdict(list)
    for f in findings:
        fby[f"{f['repo']}:{f.get('project')}"].append(f)
    # ---- blast radius
    def reach(k, attr):
        seen, todo = set(), [k]
        while todo:
            for x in nodes[todo.pop()][attr]:
                if x not in seen and x != k:
                    seen.add(x)
                    todo.append(x)
        return seen
    fan_in = {}
    for repo, g in analyses.items():
        for f, v in ((g or {}).get("file_impact") or {}).items():
            fan_in[(repo, f.replace("\\", "/"))] = v
    for k, n in nodes.items():
        n["all_users"] = sorted(reach(k, "users"))
        n["all_deps"] = sorted(reach(k, "deps"))
        pdir = os.path.dirname(n["path"]).replace("\\", "/")
        n["fan_in"] = sum(v for (r, f), v in fan_in.items() if r == n["repo"] and (not pdir or f.startswith(pdir + "/")))
    # ---- kind first (a library's 7R looks at its consumers' kinds), then difficulty and 7R
    for k, n in nodes.items():
        app = app_by_entry.get((n["repo"], n["path"]))
        kind, group = KIND.get(n["type"], (n["type"].replace("-", " ") or "Project", "lib"))
        if _token_ui(app):
            kind, group = "HTTP API (Web Forms project, token UI)", "api"
        if n["family"] and n["family"] != "netfx" and group not in ("desktop", "test", "db"):
            group = "modern" if group in ("lib", "api", "job", "ui", "service") and _tfm_major(n["_p"].get("target_frameworks")) >= 5 else group
        n["kind"], n["group"] = kind, group
    for k, n in nodes.items():
        app = app_by_entry.get((n["repo"], n["path"]))
        group = n["group"]
        lvl, base_why = BASE.get(group, (2, ""))
        why = [base_why] if base_why else []
        fs = fby.get(k, [])
        wb = sorted({f["title"] for f in fs if WINDOWS_BOUND.match(f["rule"]) and f["severity"] in ("Blocker", "High")})
        blockers = [f for f in fs if f["severity"] == "Blocker" and f["rule"] != "WEB-WEBFORMS-UI"]
        if wb and group not in ("desktop",):
            lvl += 1
            why.append("Windows-bound code: " + "; ".join(wb[:3]))
        elif blockers:
            lvl += 1
            why.append(f"{len(blockers)} blocker finding(s): " + "; ".join(sorted({f['title'] for f in blockers})[:3]))
        if n["loc"] > 50000:
            lvl += 1
            why.append(f"large: {n['loc']:,} lines of code")
        n["difficulty"], n["difficulty_why"] = LEVEL[min(3, lvl)], why
        n["blockers"] = sorted({f"{f['title']}" for f in fs if f["severity"] in ("Blocker", "High")})[:12]
        n["findings"] = len(fs)
        n["apps"] = sorted({a["name"] for a in apps if a["repo"] == n["repo"] and n["path"] in a.get("projects", [])})
        n["r7"], n["target"], n["r7_why"] = _r7(n, app, fs, nodes, hybrid.get((n["repo"], n["path"])), target, apps)
        d = decisions.get(f"project:{k}") or decisions.get(f"project:{n['repo']}/{n['path']}")
        if d:
            n.update({x: d[x] for x in ("r7", "target") if d.get(x)})
            n["r7_why"] = d.get("rationale") or n["r7_why"]
            n["decision_source"] = "review"
        else:
            n["decision_source"] = "rules" if not app else ("review" if app.get("decision_source") == "review" else "rules")
    # ---- waves (strongly connected components first, so a cycle shares a wave)
    comp = _scc(nodes)
    wave = {}

    def wave_of(c):
        if c in wave:
            return wave[c]
        wave[c] = 0  # guard
        deps = {comp[d] for m in comp_members[c] for d in nodes[m]["deps"]} - {c}
        wave[c] = 1 + max((wave_of(x) for x in deps), default=0)
        return wave[c]
    comp_members = defaultdict(list)
    for k, c in comp.items():
        comp_members[c].append(k)
    for c in comp_members:
        wave_of(c)
    for k, n in nodes.items():
        n["wave"] = wave[comp[k]]
        n["cycle"] = sorted(nodes[m]["name"] for m in comp_members[comp[k]] if m != k)
    order = sorted(nodes, key=lambda k: (nodes[k]["wave"], nodes[k]["group"] == "test", nodes[k]["deployable"], -len(nodes[k]["all_users"]),
                                         list(LEVEL.values()).index(nodes[k]["difficulty"]), nodes[k]["repo"], nodes[k]["name"]))
    out = []
    for i, k in enumerate(order, 1):
        n = nodes[k]
        out.append({"order": i, "key": k, "repo": n["repo"], "path": n["path"], "name": n["name"], "type": n["type"], "kind": n["kind"], "group": n["group"],
                    "deployable": n["deployable"], "tfm": n["tfm"], "loc": n["loc"], "apps": n["apps"],
                    "r7": n["r7"], "target": n["target"], "r7_why": n["r7_why"], "decision_source": n["decision_source"],
                    "difficulty": n["difficulty"], "difficulty_why": n["difficulty_why"],
                    "depends_on": [{"name": nodes[d]["name"], "repo": nodes[d]["repo"], "key": d, "how": how} for d, how in sorted(n["deps"].items())],
                    "used_by": [{"name": nodes[u]["name"], "repo": nodes[u]["repo"], "key": u, "how": how} for u, how in sorted(n["users"].items())],
                    "blast": {"direct": len(n["users"]), "transitive": len(n["all_users"]),
                              "deployables": sorted({nodes[u]["name"] for u in n["all_users"] if nodes[u]["deployable"]} | ({n["name"]} if n["deployable"] else set())),
                              "fan_in": n["fan_in"]},
                    "needs_first": sorted({nodes[d]["name"] for d in n["all_deps"]}), "cycle": n["cycle"],
                    "wave": n["wave"], "blockers": n["blockers"], "findings": n["findings"]})
    for x in out:
        x["blast"]["level"] = "High" if x["blast"]["transitive"] >= 3 or len(x["blast"]["deployables"]) >= 3 else (
            "Medium" if x["blast"]["transitive"] or x["blast"]["fan_in"] >= 20 else "Low")
    return {"projects": out, "waves": _waves(out), "pilot": _pilot(out), "repos": _repo_order(out), "edges": [
        {"from": nodes[a]["name"], "to": nodes[d]["name"], "from_key": a, "to_key": d, "how": how} for a in nodes for d, how in nodes[a]["deps"].items()]}


def _r7(n, app, fs, nodes, hyb, target, apps):
    if app:
        return app.get("r7", ""), app.get("target", ""), list(app.get("rationale", []))[:3]
    rules = {f["rule"] for f in fs}
    users = [nodes[u] for u in n["users"]]
    if n["group"] == "test":
        tested = ", ".join(sorted(nodes[d]["name"] for d in n["deps"])) or "the code it tests"
        return "Replatform", f"{target} with {tested}", ["Test projects move with the code they test; update the test framework packages."]
    if n["group"] == "db":
        return "Retain", "database project (handled in the database plan)", ["Not a .NET port."]
    if not n["users"] and not n["deployable"] and not any(n["path"] in a.get("projects", []) for a in apps if a["repo"] == n["repo"]):
        return "Retire?", "confirm it is unused", ["No project in the estate references it. Confirm no other repository uses its DLL before dropping it."]
    if n["group"] == "modern":
        return ("Retain" if _tfm_major(n["_p"].get("target_frameworks")) >= (_tfm_major([target]) or 10) else "Replatform",
                target, ["Already modern .NET: retarget the TFM only." if _tfm_major(n["_p"].get("target_frameworks")) else "Already .NET Standard / Core."])
    wb = sorted({f["title"] for f in fs if WINDOWS_BOUND.match(f["rule"]) and f["severity"] in ("Blocker", "High")})
    if wb:
        return "Refactor", f"{target} after replacing Windows-only code", ["Windows-bound code must be replaced first: " + "; ".join(wb[:3]) + "."]
    if rules & SYSTEM_WEB:
        return "Refactor", f"netstandard2.0 / {target} without System.Web", [
            "Uses System.Web: move the web-specific code into the web apps, or use Microsoft.AspNetCore.SystemWebAdapters during the move."]
    if hyb:
        return "Replatform", hyb.get("plan", target), [hyb.get("note", "")]
    stay = [u["name"] for u in users if u["group"] in ("desktop",)]
    if stay:
        return "Replatform", "netstandard2.0 (shared with Windows desktop apps)", [f"Used by {', '.join(stay)}, which stay on Windows: one netstandard2.0 build serves both."]
    return "Replatform", f"{target} (or netstandard2.0 while .NET Framework consumers remain)", ["Pure library: retarget with its consumers."]


def _scc(nodes):
    """Tarjan: project key -> component id."""
    idx, low, on, stack, comp, n = {}, {}, set(), [], {}, [0]

    def visit(v):
        idx[v] = low[v] = n[0]
        n[0] += 1
        stack.append(v)
        on.add(v)
        for w in nodes[v]["deps"]:
            if w not in idx:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            while True:
                w = stack.pop()
                on.discard(w)
                comp[w] = v
                if w == v:
                    break
    import sys
    sys.setrecursionlimit(max(10000, sys.getrecursionlimit()))
    for v in nodes:
        if v not in idx:
            visit(v)
    return comp


def _waves(out):
    waves = defaultdict(list)
    for x in out:
        waves[x["wave"]].append(x)
    res = []
    for w in sorted(waves):
        xs = waves[w]
        libs = [x for x in xs if not x["deployable"] and x["group"] != "test"]
        deps = [x for x in xs if x["deployable"]]
        res.append({"wave": w, "projects": [x["name"] for x in xs], "libraries": [x["name"] for x in libs], "deployables": [x["name"] for x in deps],
                    "hardest": max((x["difficulty"] for x in xs), key=lambda d: list(LEVEL.values()).index(d), default="Easy"),
                    "summary": ("Depends on nothing else in the estate: start here" if w == 1 else f"Starts when wave {w - 1} is done")})
    return res


def _pilot(out):
    """The first deployable to port: easiest, smallest blast radius, everything it needs is easy too. A pilot has to prove
    the pipeline on real code, so projects under 1,000 lines (or of unknown size) are picked only when nothing larger fits."""
    rank = lambda d: list(LEVEL.values()).index(d)
    by = {x["key"]: x for x in out}
    cands = [x for x in out if x["deployable"] and x["r7"] not in ("Retain", "Retire", "Retire?", "Rehost")]
    if not cands:
        return None
    best = min(cands, key=lambda x: (x["loc"] < 1000, rank(x["difficulty"]), max((rank(by[d["key"]]["difficulty"]) for d in x["depends_on"]), default=0),
                                     x["blast"]["transitive"], len(x["needs_first"]), x["loc"]))
    return {"name": best["name"], "repo": best["repo"], "key": best["key"], "difficulty": best["difficulty"], "needs_first": best["needs_first"],
            "why": f"{best['difficulty']} to port; {_n(len(best['needs_first']), 'project')} to port before it; {_n(best['blast']['transitive'], 'project')} depending on it. "
                   "A contained first move that proves the pipeline (build, container, deploy, test)."}


def _n(k, word):
    return f"no {word}s" if not k else f"{k} {word}" + ("" if k == 1 else "s")


def _repo_order(out):
    """Repositories in the order their code can move: a repository whose projects use DLLs from another moves after it."""
    after = defaultdict(set)
    for x in out:
        for d in x["depends_on"]:
            if d["repo"] != x["repo"]:
                after[x["repo"]].add(d["repo"])
    repos = sorted({x["repo"] for x in out})
    level = {}

    def lv(r, seen=()):
        if r in level:
            return level[r]
        if r in seen:
            return 1
        level[r] = 1 + max((lv(a, seen + (r,)) for a in after[r]), default=0)
        return level[r]
    return [{"repo": r, "step": lv(r), "after": sorted(after[r])} for r in sorted(repos, key=lambda r: (lv(r), r))]
