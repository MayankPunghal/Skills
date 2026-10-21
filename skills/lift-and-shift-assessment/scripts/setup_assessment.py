"""Create (or update) an assessment workspace.

    python <skill>/scripts/setup_assessment.py --client "Acme Corp" --roots "D:/clients/acme/repos" ["D:/more"] \
        [--prepared-by "Your Name"] [--hosting "Hyper-V on-premises"] [--offline]         [--gitlab-url https://gitlab.example.com] [--gitlab-token-env GITLAB_TOKEN]         [--docx-template "D:/branding/company-template.docx"] [--workbook-url <shared link>] [--client-contact "Sam"]

Run in the folder that will hold the assessment (not inside the client's repositories, which stay read-only). Writes assessment.json,
creates assessment/ (inventory, scan, findings, solutions, build, documents) and SKILL-ISSUES.md (the run issues log for the skill owner).
Existing values are kept unless passed again; every setting has a flag, so assessment.json never needs editing by hand.
--gitlab-url / --gitlab-token-env: the GitLab host and the NAME of the environment variable that holds a read-only token (the value is never
stored). --docx-template: a finished company .docx for the branded look (kept outside the skill: it holds logos). --workbook-url: the shared
link of the uploaded workbook; the word "workbook" in the document becomes a link to it.
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
    ap.add_argument("--gitlab-url", help="GitLab base URL, e.g. https://gitlab.example.com (read-only API use)")
    ap.add_argument("--gitlab-token-env", help="name of the environment variable holding the GitLab read token (never the token itself)")
    ap.add_argument("--docx-template", help="company-branded .docx template (cover, welcome page, header, footer, fonts)")
    ap.add_argument("--workbook-url", help="shared link of the uploaded workbook")
    ap.add_argument("--client-contact", help="first name the client email greets (build_open_questions.py)")
    ap.add_argument("--build-work-dir", help="folder for the build copies (default assessment/build/work, or a short folder in the tool cache when the workspace path is long)")
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
    if a.gitlab_url:
        cfg.setdefault("gitlab", {})["base_url"] = a.gitlab_url.rstrip("/")
    if a.gitlab_token_env:
        if len(a.gitlab_token_env) > 40 or not a.gitlab_token_env.replace("_", "").isalnum():
            raise SystemExit("--gitlab-token-env takes the NAME of an environment variable (e.g. GITLAB_TOKEN), never the token")
        cfg.setdefault("gitlab", {})["token_env"] = a.gitlab_token_env
    if a.docx_template:
        if not os.path.exists(a.docx_template):
            raise SystemExit(f"--docx-template: {a.docx_template} not found")
        cfg["docx_template"] = os.path.abspath(a.docx_template).replace("\\", "/")
    if a.workbook_url:
        cfg["workbook_url"] = a.workbook_url.strip()
    if a.client_contact:
        cfg["client_contact"] = a.client_contact.strip()
    if a.build_work_dir:
        cfg["build_work_dir"] = os.path.abspath(a.build_work_dir).replace("\\", "/")
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
