"""Write what the assessment found back into the client's repository-inventory workbook (standard library only).

    python <skill>/scripts/update_inventory_xlsx.py --xlsx <inventory.xlsx>   (the path is remembered in assessment.json)

Adds or refreshes these sheets and keeps every other sheet and row as it was (a copy "<name>.before-update.xlsx" is made once):
  Assessment scope      every repository in the workbook: in scope (.NET) or out of scope (no .NET project), the non-.NET projects inside it
  Non-.NET coupling     every non-.NET project the .NET code depends on (build writes into it, MSBuild runs npm, ...), with evidence
  Server dependencies   the single view: repository x server type, evidence, hosts named in code, the servers of the client's list that match
  Server coverage       the client's server roles against the repositories that depend on them (and types the code uses that the list lacks)
  Servers (DevOps list) the imported infrastructure list with the role each server was given
  Network access        every destination each project connects to (host/IP, port, kind) and what must be opened, routed, resolved or re-registered on AWS
  Config map            every configuration file and setting that holds an address or path (URL, IP, host, UNC share, drive path), by project, with the line
  Hosting evidence      what each repository's files say about Windows / Linux and how it is deployed (inferred, unverified)
  Assessment additions  what the assessment found that this workbook did not have (dependencies, hosts, cross-repo links) and what it corrected
Needs discover_estate.py; scan_repo.py and map_infra.py add the dependency, host and server sheets.
"""
import argparse
import datetime
import glob
import os
import re
import shutil
import sys
from collections import Counter

import _xlsx
from _common import OUT, load_config, read_json, save_config, slug, utf8_stdout

INV_NAMES = {"sql-server": ["sql server"], "redis": ["redis"], "memcached": ["memcache"], "elasticsearch": ["elasticsearch", "opensearch"], "kafka": ["kafka"],
             "rabbitmq": ["rabbitmq"], "smtp": ["smtp"], "sftp-ftp": ["ftp"], "file-share": ["unc", "file share"], "ldap-ad": ["ldap", "active directory"],
             "mongodb": ["mongo"], "mysql": ["mysql"], "postgresql": ["postgres"], "oracle": ["oracle"], "aerospike": ["aerospike"], "http-proxy": ["proxy"]}


def table(rows, cols):
    return [[c[0] for c in cols]] + [[c[1](r) for c in cols] for r in rows] if rows else [[c[0] for c in cols]]


def hdr(sheet, *names):
    """Index of the first header in `names` (case-insensitive) in a sheet, else None."""
    for i, h in enumerate(sheet[0] if sheet else []):
        if h.strip().lower() in [n.lower() for n in names]:
            return i
    return None


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", help="the client's repository inventory workbook (remembered after the first use)")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    path = a.xlsx or (cfg.get("infra") or {}).get("inventory_xlsx")
    if not path or not os.path.exists(path):
        sys.exit("give --xlsx <inventory workbook> (the file must exist)")
    path = os.path.abspath(path)
    cfg.setdefault("infra", {})["inventory_xlsx"] = path
    save_config(root, cfg)
    book = _xlsx.read(path)
    invs = {}
    for p in sorted(glob.glob(os.path.join(OUT, "inventory", "*.json"))):
        if p.endswith("estate.json"):
            continue
        i = read_json(p)
        if i:
            invs[i["repo"]] = i
    infra = {r: read_json(os.path.join(OUT, "infra", f"{r}.json")) for r in invs}
    infra = {r: v for r, v in infra.items() if v}
    scans = {r: read_json(os.path.join(OUT, "scan", f"{r}.json"), {}) or {} for r in invs}
    view = read_json(os.path.join(OUT, "infra", "estate-infra.json"), {}) or {}
    servers = read_json(os.path.join(OUT, "infra", "servers.json"))
    group_of = {r: os.path.basename(os.path.dirname(i["root"].replace("\\", "/").rstrip("/"))) for r, i in invs.items()}
    key = lambda g, n: (g.lower(), slug(n))
    by_key = {key(group_of[r], r): r for r in invs}
    sheets = []

    # ---- Assessment scope: one row per repository of the workbook
    repos_sheet = book.get("Repositories") or []
    gi, ri = hdr(repos_sheet, "group"), hdr(repos_sheet, "repository")
    ni, nodi, pyi = hdr(repos_sheet, ".NET projects"), hdr(repos_sheet, "Node.js projects"), hdr(repos_sheet, "Python projects")
    scope_rows = []
    for row in repos_sheet[1:]:
        if not row or ri is None or ri >= len(row):
            continue
        g, n = (row[gi] if gi is not None and gi < len(row) else ""), row[ri]

        def num(i):
            try:
                return int(row[i]) if i is not None and i < len(row) and row[i] != "" else 0
            except ValueError:
                return 0
        net, node, py = num(ni), num(nodi), num(pyi)
        r = by_key.get(key(g, n))
        inv = invs.get(r) if r else None
        if inv:
            sc = inv["scope"]
            oos = inv.get("out_of_scope_projects", [])
            status = "IN SCOPE (.NET)" if sc["in_scope"] else "OUT OF SCOPE: no .NET project"
            detail = sc["reason"]
            inside = "; ".join(f"{o['path']} ({o['ecosystem']}, {o['coupling']})" for o in oos[:6])
            hosted = (infra.get(r) or {}).get("hosting", {}).get("os_inferred", "")
            assessed = "yes"
        else:
            status = "IN SCOPE (.NET), not assessed yet" if net else "OUT OF SCOPE: no .NET project"
            other = ", ".join(x for x, c in (("Node.js", node), ("Python", py)) if c)
            detail = "has .NET projects" if net else ("not .NET: " + other if other else "no .NET project and no Node.js / Python project found")
            inside, hosted, assessed = "", "", "no"
        scope_rows.append({"g": g, "n": n, "status": status, "detail": detail, "net": net, "node": node, "py": py, "inside": inside, "hosted": hosted, "assessed": assessed})
    if scope_rows:
        sheets.append(("Assessment scope", table(scope_rows, [
            ("Group", lambda r: r["g"]), ("Repository", lambda r: r["n"]), ("Assessment scope", lambda r: r["status"]), ("Why", lambda r: r["detail"]),
            (".NET projects", lambda r: r["net"]), ("Node.js projects (not assessed)", lambda r: r["node"]), ("Python projects (not assessed)", lambda r: r["py"]),
            ("Non-.NET projects inside an assessed repo (coupling)", lambda r: r["inside"]), ("Assessed", lambda r: r["assessed"]), ("Hosting OS (inferred, unverified)", lambda r: r["hosted"])])))

    # ---- Non-.NET coupling
    coup = [{"repo": r, "g": group_of[r], **o} for r, i in invs.items() for o in i.get("out_of_scope_projects", [])]
    sheets.append(("Non-.NET coupling", table(coup, [
        ("Group", lambda r: r["g"]), ("Repository", lambda r: r["repo"]), ("Non-.NET project", lambda r: r["path"]), ("Ecosystem", lambda r: r["ecosystem"]),
        ("Relation", lambda r: r["relation"]), ("Coupling to the .NET code", lambda r: r["coupling"]), ("What that means", lambda r: r["coupling_meaning"]),
        ("Evidence (first 4)", lambda r: " | ".join(f"{s['file']}:{s['line']} [{s['kind']}]" for s in r["signals"][:4])),
        ("Scope", lambda r: r["scope"])])))

    # ---- Server dependencies, coverage, servers, hosting
    rows = view.get("rows", [])
    if rows or infra:
        sheets.append(("Server dependencies", table(rows, [
            ("Group", lambda r: group_of.get(r["repo"], "")), ("Repository", lambda r: r["repo"]), ("Server type", lambda r: r["label"]), ("Kind", lambda r: r["kind"]),
            ("How sure", lambda r: r["strength"]), ("Found by", lambda r: r["found_by"]), ("Projects", lambda r: r["projects"]), ("Hosts named in code", lambda r: r["hosts_in_code"]),
            ("Link to the DevOps list", lambda r: r["link_status"]), ("Matched servers", lambda r: r["matched_servers"]), ("Candidate servers of this type", lambda r: r["candidate_servers"]),
            ("Candidates by environment", lambda r: r["candidate_envs"]), ("Evidence (file:line)", lambda r: r["evidence"]), ("AWS option (later)", lambda r: r["aws_option"]),
            ("Lift-and-shift: what moves", lambda r: r["lift_and_shift"])])))
        sheets.append(("Server coverage", table(view.get("server_coverage", []), [
            ("Server role", lambda r: r["role"]), ("Servers in the DevOps list", lambda r: r["servers_in_list"]), ("Environments", lambda r: r["environments"]),
            ("Operating systems", lambda r: r["os"]), ("Assessed repos depending on it", lambda r: r["repos_depending"]), ("Repos", lambda r: r["repos"]), ("Note", lambda r: r["note"])])))
        sheets.append(("Hosting evidence", table(view.get("hosting", []), [
            ("Repository", lambda r: r["repo"]), ("OS (inferred)", lambda r: r["os_inferred"]), ("Status", lambda r: r["status"]), ("Basis", lambda r: r["basis"]),
            ("Evidence kinds", lambda r: r["evidence_kinds"]), ("Pipeline files", lambda r: r["pipeline_files"]), ("Strongest evidence", lambda r: r["strongest_evidence"])])))
    cfgview = read_json(os.path.join(OUT, "infra", "config-map.json"), {}) or {}
    colour = {"private IP": "red", "internal host name": "red", "company domain": "red", "UNC share": "red", "local drive path": "amber", "unix path": "amber", "set at deploy time": "amber",
              "public IP": "amber", "external service": "green"}
    if cfgview.get("network_access"):
        na = cfgview["network_access"]
        sheets.append(("Network access", table(na, [
            ("Group", lambda r: group_of.get(r["repo"], "")), ("Repository", lambda r: r["repo"]), ("Project that connects", lambda r: r["project"]), ("Destination (host or IP)", lambda r: r["destination"]),
            ("Port", lambda r: r["port"] or ""), ("Protocol", lambda r: r["protocol"]), ("What it is", lambda r: r["role"]), ("Kind of destination", lambda r: (r["class"], colour.get(r["class"], ""))),
            ("Held in", lambda r: r["found_in"]), ("What must happen on AWS", lambda r: r["need"]), ("Detail", lambda r: r["what_to_do"]), ("Config keys", lambda r: r["config_keys"]),
            ("Evidence", lambda r: r["evidence"]), ("Server in the DevOps list", lambda r: r["server_in_list"])])))
    if cfgview.get("rows"):
        sheets.append(("Config map", table(cfgview["rows"], [
            ("Group", lambda r: group_of.get(r["repo"], "")), ("Repository", lambda r: r["repo"]), ("Project", lambda r: r["project"]), ("Config file", lambda r: r["file"]), ("Line", lambda r: r["line"]),
            ("Environment of the file", lambda r: r["environment"]), ("Setting", lambda r: r["setting"]), ("What it holds", lambda r: r["type"]), ("Target (address or path)", lambda r: r["target"]),
            ("Port", lambda r: r["port"] or ""), ("Kind", lambda r: (r["class"], colour.get(r["class"], ""))), ("What to do on AWS", lambda r: r["action"])])))
    if servers:
        dep_roles = {}
        for r in rows:
            pass
        used = {}
        for c in view.get("server_coverage", []):
            used[c["role"]] = c["repos_depending"]
        sheets.append(("Servers (DevOps list)", table(servers["servers"], [
            ("Server", lambda s: s["name"]), ("Environment", lambda s: s["environment"]), ("Operating system", lambda s: s["os"]), ("OS family", lambda s: s["os_family"]),
            ("Roles (from name / software)", lambda s: ", ".join(f"{g['role']} ({g['from']})" for g in s["roles"])), ("Assessed repos depending on its role", lambda s: sum(used.get(g["role"], 0) for g in s["roles"])),
            ("CPU cores", lambda s: s["cores"]), ("Memory (GB)", lambda s: s["memory_gb"]), ("Storage (GB)", lambda s: s["storage_gb"]), ("SQL edition", lambda s: s["sql_edition"]),
            ("Hypervisor", lambda s: s["hypervisor"]), ("Installed software (first 200 chars)", lambda s: s["applications"][:200])])))

    # ---- Assessment additions: what the workbook did not have
    add = []
    deps_sheet = book.get("Dependencies") or []
    di_g, di_r, di_d = hdr(deps_sheet, "group"), hdr(deps_sheet, "repository"), hdr(deps_sheet, "dependency")
    have = {}
    for row in deps_sheet[1:]:
        if di_r is not None and di_r < len(row) and di_d is not None and di_d < len(row):
            have.setdefault(key(row[di_g] if di_g is not None and di_g < len(row) else "", row[di_r]), []).append(row[di_d].lower())
    for r, ir in infra.items():
        have_r = have.get(key(group_of[r], r), [])
        for d in ir["dependencies"]:
            if d["strength"] == "local-dev only":
                continue
            kws = INV_NAMES.get(d["type"], [d["label"].lower().split(" ")[0]])
            if not any(any(k in h for k in kws) for h in have_r):
                ev = d["evidence"][0] if d["evidence"] else {}
                add.append({"g": group_of[r], "r": r, "what": "Server dependency not in the Dependencies sheet", "detail": f"{d['label']} ({d['strength']})",
                            "evidence": f"{ev.get('file', '')}:{ev.get('line', '')}", "action": "Added to 'Server dependencies'"})
    hosts_sheet = book.get("Hosts referenced") or []
    hg, hr, hh = hdr(hosts_sheet, "group"), hdr(hosts_sheet, "repository"), hdr(hosts_sheet, "host / ip")
    seen_hosts = {}
    for row in hosts_sheet[1:]:
        if hr is not None and hh is not None and hr < len(row) and hh < len(row):
            seen_hosts.setdefault(key(row[hg] if hg is not None and hg < len(row) else "", row[hr]), set()).add(row[hh].lower())
    for r in invs:
        known = seen_hosts.get(key(group_of[r], r), set())
        for e in scans.get(r, {}).get("endpoints", []):
            if e["host"].lower() not in known and e["kind"] in ("internal", "external-ip"):
                add.append({"g": group_of[r], "r": r, "what": f"{'Internal host' if e['kind'] == 'internal' else 'Hard-coded public IP'} not in 'Hosts referenced'", "detail": e["host"],
                            "evidence": f"{e['evidence'][0]['file']}:{e['evidence'][0]['line']}" if e.get("evidence") else "", "action": "Check what it is (finding NET-ENDPOINT-*)"})
    for r, i in invs.items():
        for o in i.get("out_of_scope_projects", []):
            for s in o["signals"]:
                if s["kind"] == "emits-outside-repo":
                    add.append({"g": group_of[r], "r": r, "what": "Build writes into a folder outside the repository (cross-repo link)", "detail": s["text"][:140],
                                "evidence": f"{s['file']}:{s['line']}", "action": "Add to 'Cross-repo links': builds must run in this order"})
    proj_sheet = book.get("Projects") or []
    pg, pr, pe, pm = hdr(proj_sheet, "group"), hdr(proj_sheet, "repository"), hdr(proj_sheet, "ecosystem"), hdr(proj_sheet, "manifest file")
    for row in proj_sheet[1:]:
        if None in (pr, pe, pm) or max(pr, pe, pm) >= len(row) or row[pe] != "Node.js":
            continue
        r = by_key.get(key(row[pg] if pg is not None and pg < len(row) else "", row[pr]))
        if not r:
            continue
        manifest_dir = os.path.dirname(row[pm]).replace("\\", "/") or "."
        found = {o["path"] for o in invs[r].get("out_of_scope_projects", []) if o["ecosystem"] == "Node.js"}
        if manifest_dir not in found:
            add.append({"g": row[pg] if pg is not None else "", "r": r, "what": "Listed as a Node.js project but not an npm manifest", "detail": row[pm],
                        "evidence": row[pm], "action": "Correct the Projects sheet: the file is a data file or sits outside any buildable project"})
    sheets.append(("Assessment additions", table(add[:1500], [
        ("Group", lambda r: r["g"]), ("Repository", lambda r: r["r"]), ("What the assessment found", lambda r: r["what"]), ("Detail", lambda r: r["detail"]),
        ("Evidence", lambda r: r["evidence"]), ("Action", lambda r: r["action"])])))

    # ---- About: say what was added and when (rows with the same item are replaced)
    about = [list(r) for r in book.get("About", [["Item", "Detail"]])]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    new_items = {
        "Assessment sheets": f"Added {now} by the migration-assessment skill: Assessment scope, Non-.NET coupling, Server dependencies, Server coverage, Network access, Config map, Servers (DevOps list), Hosting evidence, Assessment additions. "
                             "Other sheets are unchanged.",
        "Server dependencies (how)": "Found in code by the skill's catalogue (NuGet package, code use, config key, docker-compose image). Only host names / IPs / ports are kept, never config values. "
                                     "'Candidate servers' = servers of that type in the DevOps list; 'Matched servers' only when the code names a server of the list.",
        "Assessment scope (how)": "The assessment covers .NET code only. Repositories with no .NET project are out of scope; non-.NET projects inside .NET repositories are listed with how the .NET code depends on them."}
    for k, v in new_items.items():
        for row in about:
            if row and row[0] == k:
                row[1:] = [v]
                break
        else:
            about.append([k, v])
    sheets.append(("About", about))
    backup = os.path.splitext(path)[0] + ".before-update.xlsx"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    tmp = path + ".tmp"
    names = _xlsx.update(path, [(n, r) for n, r in sheets], dest=tmp)
    os.replace(tmp, path)
    cnt = Counter(s["status"] for s in scope_rows)
    print(f"updated {path}\nsheets: {', '.join(names)}\nscope: " + ", ".join(f"{k} {v}" for k, v in cnt.items()) +
          f" · server dependency rows {len(rows)} · additions {len(add)} · backup {os.path.basename(backup)}")


if __name__ == "__main__":
    main()
