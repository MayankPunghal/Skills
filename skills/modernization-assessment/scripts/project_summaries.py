"""Projects at a glance: 3-4 plain lines per project (purpose, workflow, what it connects to, how hard the port is).

    py -X utf8 project_summaries.py [--repo X] [--force] [--check]

Run after effort_facts.py and estimate_phases.py. Collects evidence per project from assessment/effort/<repo>/facts.json
(type, size, entry points, request types, services called, database engines, who uses it, the T-shirt size) into
assessment/summaries/<repo>.json and writes a DRAFT for every project into assessment/narrative/project-summaries.md
(report section 7.0). The draft is built from evidence only, so it is correct but generic: the assessor then reads each
project's entry points (graphify explain, the controllers / handlers / Main) and rewrites the lines in plain words, then
deletes the DRAFT marker. A project block without the marker is never overwritten (use --force to rebuild everything).
--check lists the projects still marked DRAFT and exits 1 if there are any.

Style: at a glance, 3-4 lines, no jargon (see references/style-guide.md). Purpose = what the business gets from it;
Workflow = what goes in, what happens, what comes out.
"""
import argparse
import os
import re
import sys

from _common import OUT, load_config, load_state, read_json, utf8_stdout, write_json

MARK = "<!-- DRAFT: rewrite from the code, then delete this marker -->"
PLAIN_TYPE = {"aspnet-webforms": "ASP.NET Web Forms web application", "aspnet-mvc": "ASP.NET MVC web application", "webapi": "web API",
              "wcf": "WCF service", "library": "class library", "console": "console program", "windows-service": "Windows service",
              "winforms": "desktop (Windows Forms) program", "wpf": "desktop (WPF) program", "test": "test project", "database": "database project"}


def plain_type(t):
    t = (t or "").lower()
    return next((v for k, v in PLAIN_TYPE.items() if k in t), t or "project")


def name_of(path):
    return re.sub(r"\.(cs|vb|fs)proj$", "", os.path.basename(path))


def evidence(f, p, size):
    web = (f.get("web") or {}).get(p["path"], {}) or {}
    tot = web.get("totals") or {}
    folder = os.path.dirname(p["path"])
    conns = [c for c in f.get("connection_strings", []) if (c.get("file") or "").startswith(folder + "/") or not folder]
    net = [n for n in f.get("network", []) if any((x or "").startswith(folder + "/") or not folder for x in n.get("files", []))]
    refs = [r for r in f.get("service_references", []) if (r.get("folder") or "").startswith(folder + "/") or not folder]
    finds = {}
    for x in f.get("findings", []):
        if x.get("project") == p["path"]:
            finds[x.get("title") or x["rule"]] = finds.get(x.get("title") or x["rule"], 0) + (x.get("occurrences") or 1)
    return {
        "project": p["path"], "name": name_of(p["path"]), "type": p.get("type"), "plain_type": plain_type(p.get("type")),
        "kloc": round(((p.get("loc_handwritten") or 0) + (p.get("loc_markup") or 0)) / 1000, 1), "deployable": bool(p.get("deployable")),
        "framework": ", ".join(p.get("frameworks") or []), "tshirt": size.get("size", "-"), "tshirt_why": size.get("why", ""),
        "pages": len(web.get("pages") or []), "handlers": tot.get("handlers", 0), "asmx": tot.get("asmx", 0), "svc": tot.get("svc", 0),
        "request_types": (f.get("contracts") or {}).get("request_types", [])[:6] if p.get("deployable") and (tot.get("handlers") or tot.get("asmx") or tot.get("svc")) else [],
        "uses": [name_of(x) for x in p.get("project_references") or []], "used_by": [name_of(x) for x in p.get("referenced_by") or []],
        "databases": sorted({c.get("engine", "sqlserver") for c in conns}), "services_called": [r["name"] for r in refs],
        "network_roles": sorted({n.get("role") or n.get("kind") or "" for n in net} - {""}),
        "top_findings": [k for k, _ in sorted(finds.items(), key=lambda kv: -kv[1])[:2]],
    }


def draft(e):
    """Four plain lines from evidence only."""
    ph = f"{e['kloc']:g} thousand lines"
    if e["deployable"]:
        inbound = []
        if e["handlers"] or e["asmx"] or e["svc"]:
            inbound.append(f"{e['handlers'] + e['asmx'] + e['svc']} web entry point(s)")
        if e["pages"]:
            inbound.append(f"{e['pages']} page(s)")
        what = f"{'An' if e['plain_type'][0].upper() in 'AEIOU' else 'A'} {e['plain_type']} ({ph}) that runs on its own" + (f" and answers requests such as {', '.join(e['request_types'][:4])}" if e["request_types"] else "") + "."
    else:
        what = f"{'An' if e['plain_type'][0].upper() in 'AEIOU' else 'A'} {e['plain_type']} ({ph}) with shared code" + (f" used by {', '.join(e['used_by'][:4])}" if e["used_by"] else " that no other project uses") + "."
    flow = ("Takes " + " and ".join(x for x in [f"{e['handlers'] + e['asmx'] + e['svc']} web entry point(s)" if e["handlers"] or e["asmx"] or e["svc"] else "",
                                                 f"{e['pages']} page(s)" if e["pages"] else ""] if x) + " in, does its work, sends the result back." if e["deployable"] and (e["handlers"] or e["asmx"] or e["svc"] or e["pages"])
            else "Called from other projects' code; it has no entry point of its own." if not e["deployable"] else "Runs on its own; entry points to be confirmed in the code.")
    conn = []
    if e["databases"]:
        conn.append("database (" + ", ".join(e["databases"]) + ")")
    if e["services_called"]:
        conn.append("services: " + ", ".join(e["services_called"][:3]))
    if e["uses"]:
        conn.append("projects: " + ", ".join(e["uses"][:4]))
    conn_s = "Connects to " + "; ".join(conn) + "." if conn else "No database or service connection found in its own files."
    port = f"Size {e['tshirt']} for the move to .NET 10 ({e['tshirt_why']})" + (f"; main work: {', '.join(e['top_findings'])}." if e["top_findings"] else ".")
    return [("Purpose", what), ("Workflow", flow), ("Connects to", conn_s), ("Move to .NET 10", port)]


def block(e, repo):
    L = [f"### {e['name']} ({repo}) {MARK}", ""]
    L += [f"- **{k}:** {v}" for k, v in draft(e)]
    return "\n".join(L) + "\n"


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    root, cfg = load_config()
    st = load_state(root)
    npath = os.path.join(OUT, "narrative", "project-summaries.md")
    old = open(npath, encoding="utf-8").read() if os.path.exists(npath) else ""
    kept = {}
    for m in re.finditer(r"(?ms)^### (.+?)$.*?(?=^### |\Z)", old):
        kept[m.group(1).split(" <!--")[0].strip()] = m.group(0).rstrip() + "\n"
    if a.check:
        todo = [k for k, v in kept.items() if "DRAFT" in v]
        print(f"{len(todo)} project(s) still DRAFT" + (": " + ", ".join(todo) if todo else ""))
        sys.exit(1 if todo else 0)
    repos = [a.repo] if a.repo else sorted(r for r, v in st["repos"].items() if v.get("scope") != "out" and os.path.exists(os.path.join(OUT, "effort", r, "facts.json")))
    out, n_draft = ["<!-- Projects at a glance: 3-4 plain lines per project. Written by project_summaries.py as DRAFT; rewrite each from the code, delete its DRAFT marker. -->", ""], 0
    for r in repos:
        f = read_json(os.path.join(OUT, "effort", r, "facts.json"))
        sizes = (read_json(os.path.join(OUT, "effort", r, "estimate.json"), {}) or {}).get("sizes", {})
        ev = [evidence(f, p, sizes.get(p["path"], {})) for p in f["projects"] if (p.get("type") or "") != "test"]
        write_json(os.path.join(OUT, "summaries", f"{r}.json"), {"repo": r, "projects": ev})
        out += [f"## {r}", ""]
        for e in ev:
            key = f"{e['name']} ({r})"
            if key in kept and "DRAFT" not in kept[key] and not a.force:
                out.append(kept[key])
            else:
                out.append(block(e, r))
                n_draft += 1
        out.append("")
    os.makedirs(os.path.dirname(npath), exist_ok=True)
    open(npath, "w", encoding="utf-8").write("\n".join(out))
    print(f"{npath}: {n_draft} project block(s) are DRAFT: read each project's entry points and rewrite the four lines in plain words, then delete the marker")


if __name__ == "__main__":
    main()
