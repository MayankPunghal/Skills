"""Create (or update) an assessment workspace.

    python <skill>/scripts/setup_assessment.py --client "Acme Corp" --roots "D:/clients/acme/repos" ["D:/more"] \
        [--prepared-by "Your Company"] [--compliance HIPAA "PCI DSS"] [--hosting "on-prem VMware"] [--online] [--target net10.0]

Run in the folder that will hold the assessment (not inside the client's repositories). Writes assessment.json,
creates assessment/ (inventory, graphs, findings, reviews, narrative, report) and the narrative stubs the report
builder includes. Existing values are kept unless passed again.
"""
import argparse
import os
import shutil

from _common import CONFIG_NAME, DEFAULTS, OUT, SKILL_DIR, save_config, utf8_stdout, write_json, read_json

NARRATIVE = ["executive-summary", "architecture", "application-plans", "database", "risks-and-questions", "testing-and-merge", "cost"]


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--client")
    ap.add_argument("--roots", nargs="+")
    ap.add_argument("--prepared-by")
    ap.add_argument("--compliance", nargs="*")
    ap.add_argument("--hosting", help="current hosting as stated by the client (VMware, Proxmox, Hyper-V, bare metal, colo)")
    ap.add_argument("--residency")
    ap.add_argument("--target", help="target framework moniker (default net10.0)")
    ap.add_argument("--target-hosting", dest="scen_hosting", choices=["modernize", "linux-lift", "windows-rehost"], help="client hosting preference (default modernize)")
    ap.add_argument("--target-database", dest="scen_db", choices=["auto", "rds-sqlserver", "babelfish", "postgresql", "dual", "ec2-sqlserver"], help="database target (default auto)")
    ap.add_argument("--online", action="store_true", help="allow api.nuget.org lookups for package TFMs/deprecation/vulnerabilities/licences")
    a = ap.parse_args()
    root = os.getcwd()
    path = os.path.join(root, CONFIG_NAME)
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        cfg.update(read_json(path))
    if a.client:
        cfg["client"] = a.client
    if a.roots:
        cfg["estate_roots"] = [os.path.abspath(r).replace("\\", "/") for r in a.roots]
    if a.prepared_by:
        cfg["prepared_by"] = a.prepared_by
    if a.compliance is not None:
        cfg["compliance"] = a.compliance
    if a.hosting:
        cfg["current_hosting"] = a.hosting
    if a.residency:
        cfg["data_residency"] = a.residency
    if a.target:
        cfg["target_dotnet"] = a.target
    if a.online:
        cfg["online_package_lookup"] = True
    cfg.setdefault("scenario", {"hosting": "modernize", "database": "auto"})
    if a.scen_hosting:
        cfg["scenario"]["hosting"] = a.scen_hosting
    if a.scen_db:
        cfg["scenario"]["database"] = a.scen_db
    for r in cfg["estate_roots"]:
        if os.path.abspath(r).startswith(root + os.sep) is False and os.path.abspath(root).startswith(os.path.abspath(r) + os.sep):
            print(f"WARN the workspace is inside the estate root {r}; keep assessment output outside client repositories")
    save_config(root, cfg)
    for d in ("inventory", "graphs", "findings", "scan", "reviews", "narrative", "report", "cache"):
        os.makedirs(os.path.join(root, OUT, d), exist_ok=True)
    tdir = os.path.join(SKILL_DIR, "templates", "narrative")
    for n in NARRATIVE:
        dst = os.path.join(root, OUT, "narrative", f"{n}.md")
        if not os.path.exists(dst) and os.path.exists(os.path.join(tdir, f"{n}.md")):
            shutil.copy2(os.path.join(tdir, f"{n}.md"), dst)
    if not os.path.exists(os.path.join(root, OUT, "state.json")):
        write_json(os.path.join(root, OUT, "state.json"), {"repos": {}, "steps": {"setup": "done"}})
    gi = os.path.join(root, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8") as fh:
            fh.write("assessment/cache/\nassessment/graphs/\n")
    print(f"workspace: {root}\nclient: {cfg['client'] or '(not set)'} · roots: {', '.join(cfg['estate_roots']) or '(none)'} · target: {cfg['target_dotnet']}"
          f" · online package lookup: {cfg['online_package_lookup']}\nnext: python <skill>/scripts/discover_estate.py")


if __name__ == "__main__":
    main()
