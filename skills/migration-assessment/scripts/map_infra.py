"""Server dependencies and hosting evidence for every repository, tied to the client's infrastructure list (deterministic).

    python <skill>/scripts/map_infra.py [--repo NAME | --all] [--servers FILE] [--sheet NAME]

Needs discover_estate.py first (scan_repo.py adds connection-string hosts, run it before for the best result).
--servers FILE   import the client's server list (.xlsx / .csv, see import_servers.py) first; later runs reuse it.
Writes assessment/config/<repo>.json         configuration map (every address / path setting by project) and the network access list
       assessment/infra/config-map.json, report/config-map.csv, report/network-access.csv
       assessment/infra/<repo>.json            dependencies (type, strength, evidence, hosts named in code, linked servers), hosting evidence, questions
       assessment/infra/estate-infra.json      the single view: every repository x server type, plus the server-side coverage
       assessment/report/infra-dependencies.csv, infra-server-coverage.csv, hosting-evidence.csv
Evidence = file:line and key names. Config values are never copied; only host names / IPs / ports are kept (they tie a dependency to a server).
"""
import argparse
import csv
import datetime
import glob
import os
import sys
from collections import Counter, defaultdict

import _config
import _infra
import _servers
import scan_repo as _scan
from _common import OUT, load_config, load_state, mark, mark_step, read_json, save_config, utf8_stdout, write_json

INFRA = os.path.join(OUT, "infra")


def load_index():
    sv = read_json(os.path.join(INFRA, "servers.json"))
    return (sv, _servers.Index(sv)) if sv else (None, None)


def do_import(path, sheet):
    sv = _servers.import_servers(path, sheet)
    sv["summary"] = _servers.summary(sv)
    sv["imported"] = datetime.datetime.now().isoformat(timespec="seconds")
    write_json(os.path.join(INFRA, "servers.json"), sv)
    return sv


def questions_for(repo, deps, hosting):
    qs = []
    for d in deps:
        l, lab = d["link"], d["label"]
        if l["status"] == "no server of this type in the list":
            qs.append(f"{repo} uses {lab} but the infrastructure list has no {lab} server. Where does it run, and who owns it?")
        elif l["status"].startswith("no host in code"):
            qs.append(f"Which {lab} server(s) does {repo} use in production? The host is not in the code (set per environment); the list has {l['candidate_count']} candidate(s).")
        elif l["status"].startswith("host in code is not"):
            qs.append(f"{repo} names {', '.join(l['unmatched_hosts'][:3])} for {lab}: which server in the list is that (IP or alias)?")
        elif l["status"] == "no-list" and d["strength"] != "local-dev only":
            qs.append(f"Which {lab} server(s) does {repo} use? (No infrastructure list imported yet.)")
    if hosting["os_inferred"] == "unknown":
        qs.append(f"On which server(s) and operating system does {repo} run (IIS, Windows service, container)? The repository holds no deployment evidence.")
    elif hosting["os_inferred"] == "mixed":
        qs.append(f"{repo} shows both Windows and Linux hosting evidence: which project runs where?")
    else:
        qs.append(f"Confirm {repo} runs on {hosting['os_inferred'].title()} (inferred from code only), and on which server(s).")
    return qs


def map_repo(root, cfg, repo, index):
    inv = read_json(os.path.join(OUT, "inventory", f"{repo}.json"))
    facts = read_json(os.path.join(OUT, "scan", f"{repo}.json"), {}) or {}
    rr = inv["root"]
    deps = _infra.finalize(_infra.detect_dependencies(rr, inv, facts, cfg))
    deps = _servers.link(deps, index)
    hosting = _infra.hosting_evidence(rr, inv, cfg)
    cmap, cfiles = _config.config_map(rr, inv, cfg, _scan.host_kind, _scan.private_ip)
    net = _config.network_access(repo, inv, facts, cmap, _scan.host_kind, _scan.private_ip, [d.lower() for d in cfg.get("company_domains", [])], index)
    write_json(os.path.join(OUT, "config", f"{repo}.json"), {"repo": repo, "generated": datetime.datetime.now().isoformat(timespec="seconds"), "files": cfiles, "rows": cmap, "network_access": net})
    res = {"repo": repo, "root": rr, "generated": datetime.datetime.now().isoformat(timespec="seconds"), "server_list": bool(index),
           "scan_used": bool(facts), "dependencies": deps, "hosting": hosting,
           "config_rows": len(cmap), "network_rows": len(net),
           "out_of_scope_projects": [{k: o[k] for k in ("path", "ecosystem", "relation", "coupling", "coupling_meaning")} for o in inv.get("out_of_scope_projects", [])],
           "questions": questions_for(repo, deps, hosting)}
    write_json(os.path.join(INFRA, f"{repo}.json"), res)
    mark(root, repo, "infra")
    return res


def estate_view(results, sv, index):
    rows = []
    for r in results:
        for d in r["dependencies"]:
            l = d["link"]
            ev = d["evidence"][0] if d["evidence"] else {}
            rows.append({"repo": r["repo"], "type": d["type"], "label": d["label"], "kind": d["kind"], "strength": d["strength"], "found_by": ", ".join(d["found_by"]),
                         "projects": "; ".join(d["projects"][:4]), "hosts_in_code": "; ".join(h["host"] + (f":{h['port']}" if h["port"] else "") for h in d["hosts"][:6]),
                         "link_status": l["status"], "matched_servers": "; ".join(f"{m['name']} ({m['environment'] or '?'})" for m in l["matched"][:6]),
                         "candidate_servers": l["candidate_count"], "candidate_envs": ", ".join(f"{k} {v}" for k, v in l["candidate_envs"].items()),
                         "evidence": f"{ev.get('file', '')}:{ev.get('line', '')} [{ev.get('via', '')}]" if ev else "", "evidence_count": len(d["evidence"]),
                         "aws_option": d["aws"], "lift_and_shift": d["lift_and_shift"]})
    cover = []
    if sv:
        used = defaultdict(set)
        for r in results:
            for d in r["dependencies"]:
                for role in d["server_roles"]:
                    used[role].add(r["repo"])
        roles_in_list = defaultdict(list)
        for s in sv["servers"]:
            for g in s["roles"]:
                roles_in_list[g["role"]].append(s)
        for role in sorted(set(roles_in_list) | set(used)):
            ss = roles_in_list.get(role, [])
            cover.append({"role": role, "servers_in_list": len(ss), "environments": ", ".join(f"{k} {v}" for k, v in Counter(s["environment"] or "(blank)" for s in ss).items()),
                          "os": ", ".join(f"{k} {v}" for k, v in Counter(s["os"] or "(blank)" for s in ss).items()),
                          "repos_depending": len(used.get(role, [])), "repos": "; ".join(sorted(used.get(role, [])))[:300],
                          "note": ("code uses this type but the list has no such server: ask DevOps" if not ss and used.get(role) else
                                   "no assessed repository depends on this role (other repositories or applications may; the code sample is partial)" if ss and not used.get(role) else "")})
    return rows, cover


def write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--servers", help="the client's infrastructure list (.xlsx / .csv): imported first")
    ap.add_argument("--sheet")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    if a.servers:
        sv = do_import(a.servers, a.sheet)
        cfg.setdefault("infra", {})["servers_file"] = os.path.abspath(a.servers)
        save_config(root, cfg)
        s = sv["summary"]
        print(f"servers: {s['servers']} from {sv['source']} [{sv['sheet']}] · OS {s['os_family']} · environments {s['environments']}\n"
              f"roles from names/software: {s['roles']} · without a role: {len(s['without_role'])}")
    sv, index = load_index()
    if not sv:
        print("NOTE: no infrastructure list imported (map_infra.py --servers <file>): dependencies are reported without server links.")
    repos = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(OUT, "inventory", "*.json")) if not p.endswith("estate.json"))
    if a.repo:
        repos = [a.repo]
    elif not a.all and a.servers is None:
        sys.exit("use --repo NAME or --all")
    results, skipped = [], []
    for repo in repos:
        inv = read_json(os.path.join(OUT, "inventory", f"{repo}.json"))
        if not inv:
            continue
        if not (inv.get("scope") or {}).get("in_scope", True):
            skipped.append(repo)
            continue
        r = map_repo(root, cfg, repo, index)
        results.append(r)
        print(f"{repo}: {len(r['dependencies'])} server types, hosting {r['hosting']['os_inferred']} ({r['hosting']['basis'].split(' (')[0]})")
    # the single view covers every repository mapped so far (not only this run)
    all_results = [read_json(p) for p in sorted(glob.glob(os.path.join(INFRA, "*.json"))) if not p.endswith(("estate-infra.json", "servers.json"))]
    all_results = [r for r in all_results if r and "dependencies" in r]
    rows, cover = estate_view(all_results, sv, index)
    host_rows = [{"repo": r["repo"], "os_inferred": r["hosting"]["os_inferred"], "status": r["hosting"]["status"], "basis": r["hosting"]["basis"],
                  "evidence_kinds": "; ".join(r["hosting"]["deployment_files"]), "pipeline_files": "; ".join(r["hosting"]["pipeline_files"]),
                  "strongest_evidence": next((f"{s['file']}:{s['line']} {s['text']}" for s in r["hosting"]["signals"] if s["strength"] == "strong"),
                                             next((f"{s['file']}:{s['line']} {s['text']}" for s in r["hosting"]["signals"]), ""))} for r in all_results]
    questions = [{"repo": r["repo"], "question": q} for r in all_results for q in r["questions"]]
    cfgs = [read_json(os.path.join(OUT, "config", f"{r['repo']}.json")) or {} for r in all_results]
    config_rows = [{"repo": c["repo"], **r} for c in cfgs if c for r in c.get("rows", [])]
    network_rows = [r for c in cfgs if c for r in c.get("network_access", [])]
    write_json(os.path.join(INFRA, "config-map.json"), {"rows": config_rows, "network_access": network_rows})
    view = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "server_list": sv["source"] if sv else None, "repos": len(all_results),
            "rows": rows, "server_coverage": cover, "hosting": host_rows, "questions": questions, "out_of_scope_repos": skipped}
    write_json(os.path.join(INFRA, "estate-infra.json"), view)
    rdir = os.path.join(OUT, "report")
    write_csv(os.path.join(rdir, "infra-dependencies.csv"), rows)
    write_csv(os.path.join(rdir, "infra-server-coverage.csv"), cover)
    write_csv(os.path.join(rdir, "hosting-evidence.csv"), host_rows)
    write_csv(os.path.join(rdir, "config-map.csv"), [{k: v for k, v in r.items() if k not in ("template_file",)} for r in config_rows])
    write_csv(os.path.join(rdir, "network-access.csv"), network_rows)
    mark_step(root, "infra")
    types = Counter(r["type"] for r in rows)
    print(f"single view: {len(all_results)} repositories, {len(rows)} dependency rows ({', '.join(f'{k} {v}' for k, v in types.most_common(8))}); "
          f"{len(config_rows)} address/path settings, {len(network_rows)} network destinations; {len(questions)} questions; {len(skipped)} repositories out of scope -> {INFRA}/estate-infra.json, {rdir}/infra-*.csv")


if __name__ == "__main__":
    main()
