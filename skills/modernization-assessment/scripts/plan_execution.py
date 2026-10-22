"""Execution plan: the hand-off from this assessment to the dotnet-modernization skill that does the work.

    python scripts/plan_execution.py [--port-engine devtx|aws-transform|claude] [--db-tool db-agent|claude]

Run after estimate_effort.py (it reads assessment/estimate.json). Operating model, one tool per job:
  - ONE porting engine for every package: the AWS DevTx Version Upgrade Toolkit (Upgrade Assistant + Kiro CLI with its
    .NET knowledge base) or AWS Transform for .NET; "claude" only when neither is available. Never two engines on one
    project.
  - Claude with the dotnet-modernization skill cleans up what that engine does not cover (playbook by playbook) and does
    the AWS managed-service swaps.
  - ONE database tool: the DB porting agent, or Claude with the DB porting skills when the DB porting agent is not approved or the
    repository is too complex for it.
  - Applications already on modern .NET (net5.0 or later) get the Linux readiness check only: no engine run.
Order: shared class libraries first, simplest first (they unblock the applications that reference them), then the
applications in the estimate's timeline order.
For each package it writes a short stream table (who does what, hours) and the clean-up grouped by playbook; every
finding with its owner, playbook and files stays in assessment/execution-plan.json. Also: data access (raw SQL,
procedure calls, result-set procedures) and the AWS managed-service swaps.
Writes assessment/execution-plan.json, assessment/report/execution-plan.md and its .html twin.
Defaults: assessment.json "execution": {"port_engine": "devtx", "db_tool": "db-agent" for dual else "claude"}.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import OUT, data, load_config, read_json, utf8_stdout  # noqa: E402
import _findings as F  # noqa: E402
from _mdhtml import write_pair  # noqa: E402

ENGINES = {
    "devtx": "AWS DevTx Version Upgrade Toolkit (Upgrade Assistant, then Kiro CLI with the .NET knowledge base, iterated to a green build)",
    "aws-transform": "AWS Transform for .NET (ports projects to .NET 10 on Linux; Web Forms to Blazor where supported)",
    "claude": "Claude with the dotnet-modernization skill (knowledge base and playbooks), project by project",
}
SHORT = {"devtx": "DevTx toolkit", "aws-transform": "AWS Transform", "claude": "Claude"}
DB_TOOLS = {"db-agent": "DB porting agent", "claude": "Claude with the DB porting skills"}
GATES = [
    "baseline: the original solution builds and its tests (or recorded request/response pairs) are captured before any change",
    "build: dotnet build -c Release passes for net10.0 with no new warnings treated as errors",
    "residue: residue_scan.py finds no blocking pattern left (System.Web, packages.config, CallContext, BinaryFormatter, Windows paths ...), or each one has a written waiver",
    "linux: the Linux readiness rules pass (case-sensitive paths, separators, time zones, culture, Windows-only APIs and packages)",
    "tests: existing tests pass; parity replay of the recorded requests matches (volatile fields masked)",
    "container: docker build of the Linux image passes and the health endpoint answers",
    "database: every procedure in the DB contract exists on PostgreSQL non-prod and the data-access parity run passes (when the database moves)",
    "aws-native: each swapped service is exercised against its AWS endpoint in a test environment",
]
STREAMS = [("prepare", "Prepare: baseline, golden request/response files"), ("engine", "Port to .NET 10"),
           ("linux", "Linux readiness check (already on modern .NET)"), ("claude", "Claude clean-up"),
           ("db", "Data access for PostgreSQL"), ("aws-native", "AWS managed-service swaps"), ("outside", "Outside the code: DB team, DevOps, client decisions")]


def coverage():
    c = data("tool_coverage.json")
    return c["owners"], [(re.compile(e["match"]), e) for e in c["entries"]]


def classify(rule, rules):
    for rx, e in rules:
        if rx.search(rule or ""):
            return e
    return {"owner": "claude", "devtx_kb": [], "transform": False, "playbook": "windows-only-apis"}


def stream(e, engine, modern):
    """Which single stream fixes a finding, given the one engine chosen."""
    o = e["owner"]
    if o in ("dba", "devops", "decision"):
        return "outside"
    if o in ("db", "aws-native"):
        return o
    if modern:
        return "linux" if o == "port" else "claude"
    if o == "port":
        covered = engine == "claude" or (engine == "devtx" and e["devtx_kb"]) or (engine == "aws-transform" and e["transform"] in (True, "partial"))
        return "engine" if covered else "claude"
    return "claude"


def modern_projects(root):
    """Project name -> True when every target framework is net5.0 or later (no engine run needed)."""
    out = {}
    for repo in F.repos(root):
        inv = read_json(os.path.join(root, OUT, "inventory", f"{repo}.json")) or {}
        for p in inv.get("projects", []):
            tf = [str(x) for x in (p.get("target_frameworks") or p.get("frameworks") or [])]
            out[p.get("name")] = bool(tf) and all(re.match(r"net([5-9]|\d\d)\.\d|netcoreapp|netstandard", x) for x in tf)
    return out


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--port-engine", choices=sorted(ENGINES))
    ap.add_argument("--db-tool", choices=sorted(DB_TOOLS))
    a = ap.parse_args()
    root, cfg = load_config()
    est = read_json(os.path.join(root, OUT, "estimate.json"))
    if not est:
        raise SystemExit("run estimate_effort.py first (assessment/estimate.json is missing)")
    ex = cfg.get("execution") or {}
    db_sel = (est.get("scenario") or {}).get("database", "none")
    engine = a.port_engine or ex.get("port_engine") or "devtx"
    db_tool = a.db_tool or ex.get("db_tool") or ("db-agent" if db_sel == "dual" else "claude")
    owners, rules = coverage()
    mod = modern_projects(root)
    files_of = {}
    for repo in F.repos(root):
        for f in F.load(root, repo):
            files_of[f["id"]] = f.get("files") or sorted({e.get("file") for e in f.get("evidence", []) if e.get("file")})
    dbs = {d["repo"]: d for d in est.get("databases", [])}
    opt = defaultdict(list)
    for o in est.get("optional", []):
        opt[o["repo"]].append(o)
    in_scope = (cfg.get("intake") or {}).get("aws_native") == "now"
    plan = {"generated_from": "assessment/estimate.json", "scenario": est.get("scenario"), "port_engine": engine, "port_engine_label": ENGINES[engine],
            "db_tool": db_tool, "db_tool_label": DB_TOOLS[db_tool], "owners": owners, "gates": GATES, "aws_native_in_scope": in_scope, "packages": []}
    order = []  # the estimate's timeline order = first sprint each work package appears in
    for s in (est.get("sprints") or {}).get("plan") or []:
        for it in s.get("items", []):
            if it.get("work") and it["work"] not in order:
                order.append(it["work"])
    pk = sorted(est["work_packages"], key=lambda p: (p["kind"] != "library", p["kind"] == "repository",
                                                     (p.get("likely_hours") or 0) if p["kind"] == "library" else 0,
                                                     order.index(p["name"]) if p["name"] in order else 999, p["repo"]))
    by_stream = Counter()
    for p in pk:
        if p.get("mode") in ("retire", "repurchase"):
            plan["packages"].append({"name": p["name"], "repo": p["repo"], "kind": p["kind"], "r7": p.get("r7"), "mode": p.get("mode"),
                                     "likely_hours": p.get("likely_hours"), "streams": {}, "items": [], "note": f"{p.get('mode')}: no code work"})
            continue
        names = [re.match(r"Port (\S+) ", c.get("item", "")).group(1) for c in p.get("conversion", []) if re.match(r"Port (\S+) ", c.get("item", ""))]
        modern = bool(names) and all(mod.get(n) for n in names)
        items = []
        for f in p.get("findings", []):
            e = classify(f["rule"], rules)
            items.append({"rule": f["rule"], "title": f["title"], "severity": f.get("severity"), "occurrences": f.get("occurrences"),
                          "hours": f.get("hours") or [0, 0], "owner": e["owner"], "stream": stream(e, engine, modern), "devtx_kb": e["devtx_kb"],
                          "transform": e["transform"], "playbook": e["playbook"], "files": (files_of.get(f["id"]) or [])[:5]})
        mid = lambda h: (h[0] + h[1]) / 2  # noqa: E731
        st = Counter()
        for i in items:
            st[i["stream"]] += mid(i["hours"])
        rest = max((p.get("likely_hours") or 0) - sum(mid(i["hours"]) for i in items), 0)
        st["linux" if modern else "engine"] += rest  # project conversion (KLOC based): the engine's run + review
        for k, v in st.items():
            by_stream[k] += v
        plan["packages"].append({"name": p["name"], "repo": p["repo"], "kind": p["kind"], "r7": p.get("r7"), "mode": p.get("mode"),
                                 "modern": modern, "likely_hours": p.get("likely_hours"), "streams": {k: round(v, 1) for k, v in st.items()},
                                 "items": items, "playbooks": sorted({i["playbook"] for i in items if i["stream"] in ("claude", "aws-native", "db", "linux")})})
    for repo in sorted({p["repo"] for p in pk}):
        d = dbs.get(repo)
        inv = (d or {}).get("inventory") or {}
        rsq = inv.get("raw_sql") or {}
        pc = inv.get("procedure_calls") or []
        plan.setdefault("data_access", []).append({
            "repo": repo, "database_option": (d or {}).get("selected", "none"), "tool": DB_TOOLS[db_tool] if d and d.get("selected") != "none" else None,
            "procedures": len(pc), "procedure_call_sites": ((rsq.get("stored_procedures") or {}).get("call_sites")),
            "result_set_procedures": sum(1 for x in pc if set(x.get("apis") or []) & {"ExecuteReader", "Fill", "DataAdapter", "ExecuteXmlReader"}),
            "multi_result_procedures": sum(1 for x in pc if x.get("multi_result")),
            "raw_sql_statements": ((rsq.get("statements") or {}).get("statements")), "dynamic_sql": ((rsq.get("statements") or {}).get("dynamic")),
            "redesign_items": len(inv.get("redesign_items") or []), "code": inv.get("code", {}), "procedure_list": [x["name"] for x in pc]})
        plan.setdefault("aws_native", []).extend({"repo": repo, "id": o["id"], "service": o["title"], "target": o["aws"], "hours": o.get("hours"),
                                                   "files": [x["file"] for x in o.get("files", [])], "why": o.get("why", "")}
                                                  for o in opt.get(repo, []) if o["id"].startswith("AWS-"))
    for d in est.get("databases", []):
        o = (d.get("options") or {}).get(d.get("selected")) or {}
        by_stream["db"] += o.get("likely_hours") or 0
    for o in est.get("optional", []):
        if o.get("in_estimate"):  # AWS managed-service swaps chosen at intake: their own work, not inside any work package
            by_stream["aws-native"] += o.get("likely_hours") or 0
    plan["hours_by_stream"] = {k: round(v) for k, v in by_stream.most_common()}
    json.dump(plan, open(os.path.join(root, OUT, "execution-plan.json"), "w", encoding="utf-8"), indent=1)

    who = {"prepare": "Claude", "engine": SHORT[engine], "linux": "Claude (Linux readiness rules)", "claude": "Claude",
           "db": DB_TOOLS[db_tool], "aws-native": "Claude", "outside": "DB team / DevOps / client"}
    L = [f"# Execution plan: {cfg.get('client', 'Client')}", "",
         "The hand-off from the assessment to the work, carried out with the dotnet-modernization skill. Tools make the changes; "
         "engineers run them, approve plans, review and sign off. No hand-coding is planned.", "",
         f"- **Porting engine (one for every project):** {ENGINES[engine]}",
         f"- **Clean-up:** Claude, playbook by playbook, for what {SHORT[engine]} does not cover",
         f"- **Data access:** {DB_TOOLS[db_tool]} (database option: {db_sel})",
         "- **Already on modern .NET:** Linux readiness check only, no engine run",
         f"- **AWS managed services:** {'in scope' if in_scope else 'listed, not in scope (intake aws_native)'}",
         "- **Order:** shared class libraries first, simplest first; then the applications in the timeline order", "",
         "## Hours by stream (likely)", "", "| Stream | Who | Hours |", "|---|---|---|"]
    for k, title in STREAMS:
        if plan["hours_by_stream"].get(k):
            L.append(f"| {title} | {who[k]} | {plan['hours_by_stream'][k]} |")
    L += ["", "## Verification gates", ""] + [f"{i}. {g}" for i, g in enumerate(GATES, 1)]
    L += ["", "## Work packages in order", "", "| # | Package | Kind | 7R | Path | Likely hours |", "|---|---|---|---|---|---|"]
    for n, e in enumerate(plan["packages"], 1):
        path = e.get("note") or ("Linux readiness check" if e.get("modern") else f"{SHORT[engine]} port + Claude clean-up")
        L.append(f"| {n} | {e['name']} | {e['kind']} | {e.get('r7') or '-'} | {path} | {e.get('likely_hours') or 0:g} |")
    for e in plan["packages"]:
        if not e["items"] and not e["streams"]:
            continue
        L += ["", f"## {e['name']} ({e['repo']}, {e['kind']}, {e.get('r7') or '-'})", "", "| Stream | Who | What | Hours |", "|---|---|---|---|"]
        for k, title in STREAMS:
            if not e["streams"].get(k):
                continue
            its = [i for i in e["items"] if i["stream"] == k]
            what = "project conversion" if k in ("engine", "linux") else ""
            if its:
                c = Counter(re.sub(r":\s.*$", "", i["title"]) for i in its)
                what = (what + "; " if what else "") + ", ".join(f"{t} ({n})" if n > 1 else t for t, n in sorted(c.items()))
            L.append(f"| {title} | {who[k]} | {what} | {e['streams'][k]:g} |")
        cl = [i for i in e["items"] if i["stream"] in ("claude", "linux")]
        if cl:
            g = defaultdict(list)
            for i in cl:
                g[i["playbook"]].append(i)
            L += ["", "Clean-up by playbook (dotnet-modernization references/playbooks):", "",
                  "| Playbook | Findings | Occurrences | Hours | Files |", "|---|---|---|---|---|"]
            for pb, its in sorted(g.items(), key=lambda x: -sum(i["hours"][1] for i in x[1])):
                fl = sorted({x for i in its for x in i["files"]})
                L.append(f"| {pb} | {', '.join(sorted({i['title'] for i in its}))} | {sum(i['occurrences'] or 0 for i in its)} | "
                         f"{sum(i['hours'][0] for i in its):g}-{sum(i['hours'][1] for i in its):g} | {', '.join('`' + x + '`' for x in fl[:3])}{' ...' if len(fl) > 3 else ''} |")
    if plan.get("data_access"):
        L += ["", "## Data access (raw SQL and stored-procedure calls)", "",
              "| Repository | Database option | Tool | Procedures | Call sites | Return result sets (refcursor / set-returning function) | Several result sets | Raw SQL statements | Built at run time |",
              "|---|---|---|---|---|---|---|---|---|"]
        for d in plan["data_access"]:
            L.append(f"| {d['repo']} | {d['database_option']} | {d['tool'] or '-'} | {d['procedures']} | {d['procedure_call_sites'] or 0} | "
                     f"{d['result_set_procedures']} | {d['multi_result_procedures']} | {d['raw_sql_statements'] or 0} | {d['dynamic_sql'] or 0} |")
    if plan.get("aws_native"):
        L += ["", "## AWS managed-service swaps (Claude)", "", "| Repository | Service | AWS target | Hours | Where |", "|---|---|---|---|---|"]
        for s in plan["aws_native"]:
            h = s.get("hours") or [0, 0]
            L.append(f"| {s['repo']} | {s['service']} | {s['target']} | {h[0]:g}-{h[1]:g} | {', '.join('`' + x + '`' for x in list(dict.fromkeys(s['files']))[:3])} |")
    md = os.path.join(root, OUT, "report", "execution-plan.md")
    hp = write_pair(md, "\n".join(L) + "\n")
    print(f"execution plan: {len(plan['packages'])} work packages, engine {engine}, db tool {db_tool}; hours by stream {plan['hours_by_stream']} -> {md}, {hp}")


if __name__ == "__main__":
    main()
