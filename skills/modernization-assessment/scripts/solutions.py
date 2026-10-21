"""Solution-wise inventory: for every solution its projects, deployables, workloads and the measures the estimate counts.

    python <skill>/scripts/solutions.py

Reads assessment/inventory and config (run scan_repo.py and map_infra.py first) and the intake answers, and writes
assessment/solutions/index.json. Part of the lift-and-shift track (hours calculator, estimate_hours.py); estimate_effort.py runs it itself. Nothing is read from the client repositories except the .cs files of each project, to list the
environment variables the code reads. Every number is a count of something found in the code; nothing is guessed.

Measures per solution:
  env_vars          distinct names read with GetEnvironmentVariable in the solution's projects (moved into Secrets Manager)
  config_files      config files that hold hard-coded addresses, paths or credentials (values to externalise)
  endpoints         distinct internal addresses and host names the solution connects to (DNS or connection values to set)
  deployables       projects that are deployed (Windows service, web application, console job)
  workloads         solution x environment (one environment = one workload; the deployables sit inside it); an unknown environment list counts as 1 environment (flagged UNKNOWN)
  retarget          projects whose framework differs from the target framework chosen in the intake
A project shared by two solutions is listed in both and counted once in the estate totals (estimate_hours.py).
"""
import os
import re

from _common import skip_dir, OUT, SOURCE_DIR_SKIP, load_config, load_state, mark_step, read_json, utf8_stdout, write_json
import intake as I

ENV_VAR = re.compile(r'GetEnvironmentVariable\(\s*"([A-Za-z0-9_.]+)"')
INTERNAL = ("private IP", "internal host name", "company domain")


def keys(p):
    """Names a project goes by in the other outputs (infra, config, findings)."""
    path = (p.get("path") or "").replace("\\", "/").lower()
    return {path, os.path.basename(path), p.get("name", "").lower(), os.path.splitext(os.path.basename(path))[0]} - {""}


def env_vars_of(root, rel):
    base = os.path.dirname(os.path.join(root, rel))
    found = set()
    for d, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if not skip_dir(d, x, SOURCE_DIR_SKIP)]
        for f in files:
            if f.lower().endswith(".cs"):
                try:
                    found.update(ENV_VAR.findall(open(os.path.join(d, f), encoding="utf-8-sig", errors="replace").read()))
                except OSError:
                    pass
    return found


def norm_fw(tf):
    return re.sub(r"[^0-9]", "", str(tf))


def build(root, cfg, quiet=False):
    """Build assessment/solutions/index.json; returns the index. The cwd must be the workspace root."""
    I.require_hours(cfg, "solutions.py")
    st = load_state(root)
    retarget_to = (cfg.get("intake") or {}).get("retarget_to") or ""
    wants_retarget = "retarget" in I.selected(cfg)
    excluded = {x.strip().lower() for x in re.split(r"[,;\n]", str((cfg.get("intake") or {}).get("scope_exclusions") or "")) if x.strip() and x.strip().lower() != "unknown"}
    sols, assumed = [], False
    for repo in sorted(r for r in st["repos"] if st["repos"][r].get("scope") != "out"):
        inv = read_json(os.path.join(OUT, "inventory", repo + ".json"))
        if not inv:
            continue
        conf = read_json(os.path.join(OUT, "config", repo + ".json"), {})
        by_path = {p["path"]: p for p in inv.get("projects", [])}
        groups = []
        for s in inv.get("solutions", []):
            groups.append((os.path.splitext(os.path.basename(s["path"]))[0], s["path"], [x["path"] for x in s["projects"] if x["path"] in by_path]))
        loose = [p["path"] for p in inv.get("projects", []) if not any(p["path"] in g[2] for g in groups)]
        if loose:
            groups.append(("(no solution file)", "", loose))
        taken = [g[0] for g in groups]
        groups = [(g[0] if taken.count(g[0]) == 1 else f"{g[0]} ({os.path.dirname(g[1].replace(chr(92), '/')) or 'root'})", g[1], g[2]) for g in groups]  # same file name in two folders: keep the ids unique
        for name, sln_path, paths in groups:
            if {repo.lower(), name.lower(), f"{repo}/{name}".lower(), (sln_path or "").lower()} & excluded:
                continue  # out of scope (intake: scope_exclusions)
            projs = [by_path[x] for x in paths]
            names = set().union(*[keys(p) for p in projs]) if projs else set()
            envs, confirmed = I.environments_of(cfg, f"{repo}/{name}")
            deployables = [p for p in projs if p.get("deployable")]
            ev = set()
            for p in projs:
                ev |= env_vars_of(inv["root"], p["path"])
            cfiles = sorted({r["file"] for r in conf.get("rows", []) if (r.get("project") or "").lower() in names})
            eps = {}
            for r in conf.get("network_access", []):
                if r.get("class") in INTERNAL and (r.get("project") or "").lower() in names:
                    eps.setdefault(r["destination"], {"destination": r["destination"], "class": r["class"], "projects": set()})["projects"].add(r["project"])
            wl_envs = envs or ["UNKNOWN"]
            assumed = assumed or not envs
            fw = sorted({str(t) for p in projs for t in (p.get("target_frameworks") or [])})
            to_change = [p["name"] for p in projs if wants_retarget and p.get("framework_family") == "netfx"
                         and not (retarget_to not in ("", "unknown") and all(norm_fw(t) == norm_fw(retarget_to) for t in p.get("target_frameworks") or []))]
            sols.append({
                "id": f"{repo}/{name}", "repo": repo, "solution": name, "solution_file": sln_path,
                "projects": [{"name": p["name"], "path": p["path"], "type": p.get("type"), "frameworks": p.get("target_frameworks"),
                              "family": p.get("framework_family"), "deployable": bool(p.get("deployable")), "loc": p.get("loc_code", 0)} for p in projs],
                "deployables": [p["name"] for p in deployables],
                "environments": envs, "environments_confirmed": confirmed, "environments_assumed": not envs,
                "workloads": [{"environment": e, "deployables": [d["name"] for d in deployables]} for e in wl_envs] if deployables else [],  # a solution without a deployable (libraries only) is nothing to move
                "frameworks": fw, "retarget_projects": to_change,
                "env_vars": sorted(ev), "config_files": cfiles,
                "endpoints": [{**v, "projects": sorted(v["projects"])} for v in sorted(eps.values(), key=lambda x: x["destination"])],
                "loc": sum(p.get("loc_code", 0) for p in projs),
            })
    count = {}
    for s in sols:
        for p in s["projects"]:
            count.setdefault((s["repo"], p["path"]), []).append(s["id"])
    shared = [{"repo": k[0], "project": k[1], "solutions": v} for k, v in count.items() if len(v) > 1]
    index = {"solutions": sols, "shared_projects": shared, "environments_assumed": assumed, "retarget_to": retarget_to or "unknown"}
    write_json(os.path.join(OUT, "solutions", "index.json"), index)
    mark_step(root, "solutions")
    if quiet:
        return index
    print(f"{len(sols)} solutions · {sum(len(s['projects']) for s in sols)} projects · {sum(len(s['deployables']) for s in sols)} deployables · "
          f"{sum(len(s['workloads']) for s in sols)} workloads" + (" · environments UNKNOWN: 1 per solution assumed" if assumed else ""))
    for s in sols:
        print(f"  {s['id']}: {len(s['projects'])} projects, {len(s['deployables'])} deployables, {len(s['env_vars'])} env vars, "
              f"{len(s['config_files'])} config files, {len(s['endpoints'])} internal endpoints, {len(s['retarget_projects'])} to retarget")
    if shared:
        print(f"  {len(shared)} project(s) belong to more than one solution: counted once in the estate totals")
    return index


def main():
    utf8_stdout()
    root, cfg = load_config()
    os.chdir(root)
    build(root, cfg)


if __name__ == "__main__":
    main()
