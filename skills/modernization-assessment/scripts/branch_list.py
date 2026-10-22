"""Every branch of every repository, with its exact name and last commit date (GitLab, read-only GET requests; VPN).

Writes assessment/branches/list.json: {repo: {"default": name, "branches": [{"name", "date", "protected"}...]}}, newest first.
build_doc.py uses it for the workbook sheet Branches (exact branch names, how many branches exist, the newest ones).
Usage: py branch_list.py [--repos a,b]      The read token is taken from the environment variable named in assessment.json
(gitlab.token_env, default GITLAB_TOKEN) and is never printed."""
import argparse
import os
import re
import urllib.parse

from _common import gitlab_token, load_config, utf8_stdout, write_json
from branch_evidence import Gl, git


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", help="comma separated folder names (default: every estate root)")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    g = cfg.get("gitlab") or {}
    token = gitlab_token(cfg)  # env var named in gitlab.token_env (Windows: also the user environment); never printed
    want = {x.strip().lower() for x in a.repos.split(",")} if a.repos else None
    out = {}
    for r_ in cfg.get("estate_roots") or []:
        name = os.path.basename(r_.replace("\\", "/").rstrip("/"))
        if want and name.lower() not in want:
            continue
        url = git(r_, "remote", "get-url", "origin")
        m = re.match(r"https?://([^/]+)/(.+?)(?:\.git)?$", re.sub(r"//[^@/]+@", "//", url))
        if not m:
            print(f"{name}: no GitLab origin URL, skipped")
            continue
        gl = Gl(g.get("base_url") or f"https://{m.group(1)}", token)
        pid = urllib.parse.quote(m.group(2), safe="")
        try:
            proj, _ = gl.get(f"/projects/{pid}")
            branches = gl.pages(f"/projects/{pid}/repository/branches")
        except Exception as e:  # network or permission: say so, keep going
            print(f"{name}: not read ({type(e).__name__})")
            continue
        rows = sorted(({"name": b["name"], "date": (b["commit"].get("committed_date") or "")[:10], "protected": bool(b.get("protected"))} for b in branches), key=lambda x: x["date"], reverse=True)
        out[name] = {"default": proj.get("default_branch"), "branches": rows}
        print(f"{name}: {len(rows)} branches")
    os.makedirs(os.path.join("assessment", "branches"), exist_ok=True)
    write_json(os.path.join("assessment", "branches", "list.json"), out)


if __name__ == "__main__":
    main()
