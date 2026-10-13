"""Create (or update) an assessment workspace.

    python <skill>/scripts/setup_assessment.py --client "Acme Corp" --roots "D:/clients/acme/repos" ["D:/more"] \
        [--prepared-by "Your Name"] [--hosting "Hyper-V on-premises"] [--offline]

Run in the folder that will hold the assessment (not inside the client's repositories, which stay read-only). Writes assessment.json,
creates assessment/ (inventory, scan, findings, solutions, build, documents) and SKILL-ISSUES.md (the run issues log for the skill owner).
Existing values are kept unless passed again.
"""
import argparse
import os

from _common import CONFIG_NAME, DEFAULTS, OUT, issues_log, read_json, save_config, utf8_stdout, write_json


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--client")
    ap.add_argument("--roots", nargs="+")
    ap.add_argument("--prepared-by")
    ap.add_argument("--hosting", help="current hosting as stated by the client (Hyper-V, VMware, Proxmox, bare metal, colo)")
    ap.add_argument("--online", action="store_true", help="api.nuget.org lookups for package licences and deprecation (the default)")
    ap.add_argument("--offline", action="store_true", help="no api.nuget.org lookups (package ids stay on this machine)")
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
    if a.hosting:
        cfg["current_hosting"] = a.hosting
    if a.online:
        cfg["online_package_lookup"] = True
    if a.offline:
        cfg["online_package_lookup"] = False
    for r in cfg["estate_roots"]:
        if os.path.abspath(root).startswith(os.path.abspath(r) + os.sep):
            print(f"WARN the workspace is inside the estate root {r}; keep assessment output outside client repositories")
    save_config(root, cfg)
    for d in ("inventory", "scan", "findings", "infra", "config", "solutions", "build", "documents"):
        os.makedirs(os.path.join(root, OUT, d), exist_ok=True)
    issues_log(root, cfg.get("client") or "")
    if not os.path.exists(os.path.join(root, OUT, "state.json")):
        write_json(os.path.join(root, OUT, "state.json"), {"repos": {}, "steps": {"setup": "done"}})
    gi = os.path.join(root, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8") as fh:
            fh.write("assessment/cache/\n")
    print(f"workspace: {root}\nclient: {cfg['client'] or '(not set)'} · roots: {', '.join(cfg['estate_roots']) or '(none)'} · online package lookup: {cfg['online_package_lookup']}\n"
          "next: python <skill>/scripts/discover_estate.py, then the intake questionnaire (python <skill>/scripts/intake.py --questions)")


if __name__ == "__main__":
    main()
