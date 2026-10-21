"""Shallow, read-only clones of the included GitLab projects (assessment/gitlab/projects.json, written by gitlab_projects.py).

    py <skill>/scripts/clone_repos.py --dest DIR [--only-dotnet] [--projects a,b] [--branch PROJECT=BRANCH ...]
        [--depth N] [--workers N] [--set-roots]

Clones into DIR/<group path>/<repo>. The token goes only into the child git process environment (http.extraHeader through
GIT_CONFIG_COUNT/KEY/VALUE): never on the command line, never into .git/config. The credential helper is disabled and
GIT_TERMINAL_PROMPT=0. After a clone the push URL is set to a disabled value, so nothing can be pushed from it.

Resumable: complete clones are skipped (their push URL is re-checked); folders that stopped half way are removed and cloned again.
Writes DIR/_clone-report.json (cloned, skipped, failed with the stderr tail; never the token) and prints the folders to pass to
setup_assessment.py --roots. --set-roots writes those folders into assessment.json -> estate_roots (replacing the list).

DIR must be outside the workspace's assessment folder and outside the estate roots, so client repositories are never touched.
"""
import argparse
import base64
import datetime
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from _common import OUT, gitlab_token, load_config, read_json, save_config, utf8_stdout, write_json

PATH_PART = re.compile(r"^[A-Za-z0-9._-]+$")
DISABLED_PUSH = "DISABLED-read-only-assessment"
MIN_GIT = (2, 31)  # GIT_CONFIG_COUNT needs git 2.31 or newer
CLONE_TIMEOUT = 3600  # seconds per repository


def git_version():
    try:
        out = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit("git is not on PATH")
    m = re.search(r"(\d+)\.(\d+)", out)
    if not m or (int(m.group(1)), int(m.group(2))) < MIN_GIT:
        raise SystemExit(f"git {MIN_GIT[0]}.{MIN_GIT[1]} or newer is needed (found: {out})")
    return out


def _real(path):
    return os.path.normcase(os.path.realpath(path))  # resolves 8.3 short names and symlinks where they exist


def inside(path, root):
    """path is strictly inside root."""
    a, b = _real(path), _real(root)
    return a != b and os.path.commonpath([a, b]) == b


def same_or_inside(path, root):
    return _real(path) == _real(root) or inside(path, root)


def resolve(projects, key):
    """One project by its full path or its name (case-insensitive)."""
    k = key.strip().lower()
    hits = [p for p in projects if p["path"].lower() == k] or [p for p in projects if p["name"].lower() == k]
    if not hits:
        raise SystemExit(f"no included project matches '{key}' (use the full path from assessment/gitlab/projects.json)")
    if len(hits) > 1:
        raise SystemExit(f"'{key}' matches {len(hits)} projects: use the full path")
    return hits[0]


def auth_env(token):
    """Child environment only: the header goes through git's own config variables. Existing GIT_CONFIG_* entries are kept."""
    n = int(os.environ.get("GIT_CONFIG_COUNT") or 0)
    value = "Authorization: Basic " + base64.b64encode(f"oauth2:{token}".encode()).decode()
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
                f"GIT_CONFIG_KEY_{n}": "http.extraHeader", f"GIT_CONFIG_VALUE_{n}": value,
                f"GIT_CONFIG_KEY_{n + 1}": "credential.helper", f"GIT_CONFIG_VALUE_{n + 1}": "",
                "GIT_CONFIG_COUNT": str(n + 2)})
    return env


def redact(text, token):
    text = text.replace(token, "***") if token else text
    text = re.sub(r"(https?://)[^/@\s]+@", r"\1***@", text)
    return text.strip()[-300:]


def remove_tree(path):
    def _writable(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)  # git pack files are read-only on Windows
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_writable)
    else:
        shutil.rmtree(path, onerror=_writable)


def head_branch(path):
    """Branch checked out in a complete clone; None when the folder is not a complete clone."""
    if not os.path.isdir(os.path.join(path, ".git")):
        return None
    if subprocess.run(["git", "-C", path, "rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode != 0:
        return None
    r = subprocess.run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or "HEAD"


def disable_push(path):
    """Set the push URL to a value that cannot work. Uses the plain environment: no token needed."""
    r = subprocess.run(["git", "-C", path, "remote", "set-url", "--push", "origin", DISABLED_PUSH], capture_output=True, text=True)
    return r.returncode == 0


def clone_one(p, dest_root, depth, branch, env, token):
    """Returns (status, note, folder). Never raises: every project ends up in the report."""
    rel = p["path"].split("/")
    if not all(PATH_PART.match(x) for x in rel):
        return "failed", "unsafe project path", None
    dest = os.path.join(dest_root, *rel)
    if not inside(dest, dest_root):
        return "failed", "path leaves the destination folder", None
    if p.get("empty"):
        return "skipped", "empty repository (nothing to clone)", None
    if os.path.isdir(dest):
        cur = head_branch(dest)
        if cur is not None:  # complete clone from an earlier run
            if not disable_push(dest):
                return "failed", "existing clone: could not disable the push URL", dest
            if branch and cur != branch:
                return "failed", f"already cloned on branch {cur}, asked for {branch}: use another --dest", dest
            return "skipped", f"already cloned (branch {cur})", dest
        remove_tree(dest)  # half finished: remove and clone again
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    cmd = ["git", "-c", "core.longpaths=true", "clone", "--depth", str(depth), "--no-tags", "--single-branch", "--quiet"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [p["http_url"], dest]
    t = time.time()
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=CLONE_TIMEOUT)
        code, err = r.returncode, r.stderr
    except subprocess.TimeoutExpired:
        code, err = 1, f"timeout after {CLONE_TIMEOUT}s"
    if code:
        if os.path.isdir(dest):
            remove_tree(dest)
        return "failed", redact(err, token), None
    if not disable_push(dest):
        remove_tree(dest)
        return "failed", "clone made but the push URL could not be disabled; removed", None
    return "cloned", f"{time.time() - t:.0f}s, branch {head_branch(dest)}", dest


def safe_clone(p, dest_root, depth, branch, env, token):
    """clone_one, but an unexpected error is one failed project, not an aborted run."""
    try:
        return clone_one(p, dest_root, depth, branch, env, token)
    except Exception as e:  # noqa: BLE001
        return "failed", redact(f"{type(e).__name__}: {e}", token), None


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Shallow, read-only clones of the included GitLab projects.")
    ap.add_argument("--dest", required=True, help="folder for the clones (outside assessment/ and the estate roots)")
    ap.add_argument("--only-dotnet", action="store_true", help="only projects with C# or VB.NET code")
    ap.add_argument("--projects", help="comma separated project paths or names (default: every included project)")
    ap.add_argument("--branch", action="append", default=[], metavar="PROJECT=BRANCH",
                    help="clone this branch (single branch) instead of the default; repeatable; the project must be selected")
    ap.add_argument("--depth", type=int, default=1, help="history depth (default 1)")
    ap.add_argument("--workers", type=int, default=4, help="parallel clones, 1 to 8 (default 4)")
    ap.add_argument("--set-roots", action="store_true", help="write the folders into assessment.json -> estate_roots (replaces the list)")
    a = ap.parse_args()
    if a.depth < 1:
        ap.error("--depth must be 1 or more")
    if not 1 <= a.workers <= 8:
        ap.error("--workers must be 1 to 8")

    root, cfg = load_config()
    os.chdir(root)
    git_version()
    data = read_json(os.path.join(OUT, "gitlab", "projects.json"))
    if not data:
        raise SystemExit("assessment/gitlab/projects.json not found: run gitlab_projects.py first")
    included = [p for p in data["projects"] if p.get("included")]

    selected = included
    if a.projects:
        seen, selected = set(), []
        for key in (x for x in a.projects.split(",") if x.strip()):
            p = resolve(included, key)
            if p["path"] not in seen:
                seen.add(p["path"])
                selected.append(p)
    branches = {}
    for spec in a.branch:
        key, sep, br = spec.partition("=")
        if not sep or not key.strip() or not br.strip() or br.strip().startswith("-"):
            ap.error(f"--branch needs PROJECT=BRANCH, got {spec!r}")
        p = resolve(included, key)
        if p["path"] not in {s["path"] for s in selected}:
            ap.error(f"{p['path']} is in --branch but not selected: add it to --projects")
        branches[p["path"]] = br.strip()
    if a.only_dotnet:
        selected = [p for p in selected if p.get("dotnet")]
    if not selected:
        print("nothing to clone with these options")
        return

    dest = os.path.abspath(a.dest).replace("\\", "/")
    dest_native = os.path.abspath(a.dest)
    if os.path.exists(dest_native) and not os.path.isdir(dest_native):
        raise SystemExit(f"--dest is a file: {dest}")
    if same_or_inside(dest_native, os.path.join(root, OUT)):
        raise SystemExit("--dest must be outside the workspace's assessment folder")
    for r_ in cfg.get("estate_roots") or []:
        if same_or_inside(dest_native, r_):
            raise SystemExit(f"--dest is inside an estate root ({r_}): client repositories must stay untouched")
    os.makedirs(dest_native, exist_ok=True)

    token = gitlab_token(cfg)
    env = auth_env(token)
    print(f"cloning {len(selected)} projects into {dest} (depth {a.depth}, {a.workers} at a time)", flush=True)
    results = []
    with ThreadPoolExecutor(a.workers) as ex:
        futures = [ex.submit(safe_clone, p, dest_native, a.depth, branches.get(p["path"]), env, token) for p in selected]
        for i, (p, fut) in enumerate(zip(selected, futures), 1):
            status, note, folder = fut.result()
            results.append((p, status, note, folder))
            print(f"[{i}/{len(selected)}] {p['path']}: {status} ({note})", flush=True)

    report = {"generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "dest": dest, "depth": a.depth,
              "cloned": [], "skipped": [], "failed": []}
    folders = []
    for p, status, note, folder in results:
        if status == "failed":
            report["failed"].append({"path": p["path"], "error": note})
            continue
        entry = {"path": p["path"], "note": note}
        if folder:
            entry["folder"] = folder.replace("\\", "/")
            folders.append(entry["folder"])
        branch = branches.get(p["path"])
        if branch:
            entry["branch"] = branch
        report[status].append(entry)
    write_json(os.path.join(dest_native, "_clone-report.json"), report)

    print(f"done: {len(report['cloned'])} cloned, {len(report['skipped'])} skipped, {len(report['failed'])} failed "
          f"(report: {dest}/_clone-report.json)")
    if report["failed"]:
        print("failed: " + "; ".join(f"{f['path']} ({f['error']})" for f in report["failed"]))
    if folders:
        print("folders for setup_assessment.py --roots:")
        for f in folders:
            print(f"  {f}")
        print("--roots " + " ".join(f'"{f}"' for f in folders))
    if a.set_roots:
        if not folders:
            print("--set-roots: no folder present, assessment.json unchanged")
        else:
            old = cfg.get("estate_roots") or []
            cfg["estate_roots"] = folders
            save_config(root, cfg)
            print(f"assessment.json estate_roots: {len(old)} -> {len(folders)} folders")


if __name__ == "__main__":
    main()
