"""Which branch of each repository is the live line? Evidence from GitLab, read-only (GET and HEAD requests only; nothing is created, changed or cloned).

    python <skill>/scripts/branch_evidence.py [--repos name,name] [--months 12]

Needs the GitLab host to be reachable (VPN) and a read token in the environment variable named in assessment.json -> gitlab.token_env
(default GITLAB_TOKEN); gitlab.base_url defaults to the host of each checkout's origin URL. The token is never printed or written.
With no token, no GitLab origin, or an unreachable host, the same evidence is read from the local clone instead (git for-each-ref,
merge commits "Merge branch 'x' into 'y'", tags, CI files per branch): branches the clone never fetched are missing, so say so.

For every estate root: default branch and the branch checked out, every branch with its last commit date, protected branches, newest tags,
the branches that merged requests were merged INTO over the last N months (the integration or release lines), CI / Jenkins files on the
default and key branches, and how far the newest branches are ahead of the branch we assessed. Writes assessment/branches/evidence.json and
summary.md.

A suggestion, not a decision: the suggested branch is the protected branch that received the most merged requests (else the default branch).
The newest branch by date can be an unmerged feature; it is flagged as such. The user confirms the branch per repository with the client or
DevOps before the assessment is re-run on it.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

from _common import OUT, gitlab_token, load_config, utf8_stdout, write_json

CI_FILES = ["Jenkinsfile", "jenkinsfile", "Jenkinsfile.groovy", ".gitlab-ci.yml", "azure-pipelines.yml", "buildspec.yml", "appveyor.yml"]
KEY_BRANCH = re.compile(r"^(master|main|FEATURE|develop|development|Development|release.*|Release.*|hotfix.*|HotFix.*|Staging|staging|Production|production|prod|PRIORITY|CRITICAL-FIX)$")


class Gl:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/") + "/api/v4", token

    def _req(self, path, method="GET", **q):
        url = self.base + path + ("?" + urllib.parse.urlencode(q) if q else "")
        return urllib.request.urlopen(urllib.request.Request(url, headers={"PRIVATE-TOKEN": self.token}, method=method), timeout=40)

    def get(self, path, **q):
        with self._req(path, **q) as r:
            return json.load(r), r.headers

    def pages(self, path, max_pages=30, **q):
        out, page = [], 1
        while page <= max_pages:
            data, h = self.get(path, per_page=100, page=page, **q)
            out += data
            if not h.get("X-Next-Page"):
                break
            page += 1
        return out

    def has_file(self, pid, path, ref):
        try:
            with self._req(f"/projects/{pid}/repository/files/{urllib.parse.quote(path, safe='')}", method="HEAD", ref=ref):
                return True
        except urllib.error.HTTPError:
            return False


def git(root, *a):
    try:
        return subprocess.check_output(["git", "-C", root] + list(a), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def ahead_behind(gl, pid, base, other):
    try:
        a, _ = gl.get(f"/projects/{pid}/repository/compare", **{"from": base, "to": other, "straight": "true"})
        b, _ = gl.get(f"/projects/{pid}/repository/compare", **{"from": other, "to": base, "straight": "true"})
        return len(a.get("commits", [])), len(b.get("commits", []))
    except Exception:
        return None, None


def local_evidence(r_, months):
    """The same facts from the local clone only (no GitLab): every branch it holds, merge targets from merge-commit subjects."""
    refs = [x.split("|") for x in git(r_, "for-each-ref", "--sort=-committerdate", "--format=%(refname:short)|%(committerdate:short)",
                                          "refs/heads", "refs/remotes").splitlines() if "|" in x]
    seen, sheet = set(), []
    for n, d in refs:
        n = re.sub(r"^origin/", "", n)
        if n not in seen and n not in ("HEAD", "origin"):
            seen.add(n)
            sheet.append((n, d))
    default = re.sub(r"^origin/", "", git(r_, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")) or git(r_, "branch", "--show-current")
    targets = Counter()
    for subj in git(r_, "log", "--all", "--merges", f"--since={months} months ago", "--format=%s").splitlines():
        m = re.search(r"into '?([\w./-]+)'?", subj)
        targets[m.group(1) if m else default] += 1
    tags = [tuple(x.split("|")) for x in git(r_, "for-each-ref", "--sort=-creatordate", "--count=5", "--format=%(refname:short)|%(creatordate:short)",
                                             "refs/tags").splitlines() if "|" in x]
    suggested = targets.most_common(1)[0][0] if targets else default
    newest = sheet[0][0] if sheet else default
    dates = dict(sheet)

    def ref(b):
        return b if git(r_, "rev-parse", "--verify", "--quiet", b) else f"origin/{b}"
    ci = {}
    for b in sorted({x for x in (default, suggested, newest) if x} | {n for n, _ in sheet if KEY_BRANCH.match(n)}):
        hit = [f for f in CI_FILES if git(r_, "ls-tree", "--name-only", ref(b), "--", f)]
        if hit:
            ci[b] = hit
    ab = git(r_, "rev-list", "--left-right", "--count", f"{ref(suggested)}...{ref(newest)}").split() if newest != suggested else ["0", "0"]
    behind, ahead = (int(ab[0]), int(ab[1])) if len(ab) == 2 else (0, 0)
    return {"project": os.path.basename(r_.rstrip("/\\")), "source": "local clone (no GitLab)", "default": default,
            "checked_out": git(r_, "branch", "--show-current"), "checked_out_date": git(r_, "log", "-1", "--format=%cs"),
            "branches": len(sheet), "newest": [newest, dates.get(newest)], "suggested": [suggested, dates.get(suggested)],
            "merged_into_last_months": targets.most_common(6), "merged_mr_count": sum(targets.values()), "mr_pages_capped": False,
            "protected": [], "tags": tags, "ci_files": ci,
            "newest_vs_suggested": {"ahead": ahead, "behind": behind, "newest_is_merge_target": newest in targets},
            "key_branches": {n: d for n, d in sheet if KEY_BRANCH.match(n)}}


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", help="comma separated folder names (default: every estate root)")
    ap.add_argument("--months", type=int, default=12)
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    g = cfg.get("gitlab") or {}
    try:
        token = gitlab_token(cfg)  # env var named in gitlab.token_env (Windows: also the user environment); never printed
    except SystemExit:
        token = None
        print("no GitLab read token: reading branch evidence from the local clones only (branches they never fetched are missing)")
    want = {x.strip().lower() for x in a.repos.split(",")} if a.repos else None
    import datetime
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30 * a.months)).strftime("%Y-%m-%dT00:00:00Z")
    results = {}
    for r_ in cfg.get("estate_roots") or []:
        name = os.path.basename(r_.replace("\\", "/").rstrip("/"))
        if want and name.lower() not in want:
            continue
        url = git(r_, "remote", "get-url", "origin")
        m = re.match(r"https?://([^/]+)/(.+?)(?:\.git)?$", re.sub(r"//[^@/]+@", "//", url))
        if not m or not token:
            if not git(r_, "rev-parse", "--git-dir"):
                print(f"{name}: not a git clone, skipped")
                continue
            results[name] = v = local_evidence(r_, a.months)
            print(f"{name}: local clone: default {v['default']}, checked out {v['checked_out']}, suggested {v['suggested'][0]}, "
                  f"{v['branches']} branches, ci files {v['ci_files'] or 'none'}", flush=True)
            continue
        gl = Gl(g.get("base_url") or f"https://{m.group(1)}", token)
        pid = urllib.parse.quote(m.group(2), safe="")
        try:
            proj, _ = gl.get(f"/projects/{pid}")
            branches = gl.pages(f"/projects/{pid}/repository/branches")
            protected = [p["name"] for p in gl.get(f"/projects/{pid}/protected_branches")[0]]
            tags = [(t["name"], t["commit"]["committed_date"][:10]) for t in gl.get(f"/projects/{pid}/repository/tags", per_page=5, order_by="updated", sort="desc")[0]]
            mrs = gl.pages(f"/projects/{pid}/merge_requests", max_pages=10, state="merged", updated_after=since, scope="all")
        except Exception as e:  # unreachable host, 403, 404: fall back to what the clone holds
            print(f"{name}: GitLab {type(e).__name__} {str(e)[:80]}; using the local clone")
            results[name] = dict(local_evidence(r_, a.months), gitlab_error=type(e).__name__)
            continue
        sheet = sorted(((b["name"], b["commit"]["committed_date"][:10]) for b in branches), key=lambda x: x[1], reverse=True)
        targets = Counter(x["target_branch"] for x in mrs)
        default = proj.get("default_branch")
        local = git(r_, "branch", "--show-current")
        prot_targets = [(b, n) for b, n in targets.most_common() if b in protected]
        suggested = prot_targets[0][0] if prot_targets else (targets.most_common(1)[0][0] if targets else default)
        newest = sheet[0][0] if sheet else default
        dates = dict(sheet)
        ci = {}
        for b in sorted({default, suggested, newest} | {n for n, _ in sheet if KEY_BRANCH.match(n)}):
            hit = [f for f in CI_FILES if gl.has_file(proj["id"], f, b)]
            if hit:
                ci[b] = hit
        ahead, behind = ahead_behind(gl, proj["id"], suggested, newest) if newest != suggested else (0, 0)
        results[name] = {"project": m.group(2), "default": default, "checked_out": local, "checked_out_date": git(r_, "log", "-1", "--format=%cs"),
                         "branches": len(sheet), "newest": [newest, dates.get(newest)], "suggested": [suggested, dates.get(suggested)],
                         "merged_into_last_months": targets.most_common(6), "merged_mr_count": len(mrs), "mr_pages_capped": len(mrs) >= 1000,
                         "protected": protected, "tags": tags, "ci_files": ci,
                         "newest_vs_suggested": {"ahead": ahead, "behind": behind, "newest_is_merge_target": newest in targets},
                         "key_branches": {n: d for n, d in sheet if KEY_BRANCH.match(n)}}
        print(f"{name}: default {default}, checked out {local}, suggested {suggested} ({dates.get(suggested)}), newest {newest} ({dates.get(newest)}), "
              f"ci files {ci or 'none'}", flush=True)
    os.makedirs(os.path.join(OUT, "branches"), exist_ok=True)
    write_json(os.path.join(OUT, "branches", "evidence.json"), results)
    lines = ["# Branch evidence (GitLab, read-only; local clone where GitLab was not available)", "", "| Repo | Checked out | Suggested (receives merged requests) | Newest branch | Newest ahead of suggested | CI / Jenkins files |", "|---|---|---|---|---|---|"]
    for n, v in results.items():
        if "error" in v:
            lines.append(f"| {n} | error: {v['error']} | | | | |")
            continue
        nv = v["newest_vs_suggested"]
        flag = "" if v["newest"][0] == v["suggested"][0] else f"{v['newest'][0]} ({v['newest'][1]}): " + ("merge target" if nv["newest_is_merge_target"] else "never merged: not a release line") + f", {nv['ahead']} ahead, {nv['behind']} behind"
        lines.append(f"| {n} | {v['checked_out']} ({v['checked_out_date']}) | {v['suggested'][0]} ({v['suggested'][1]}) | {flag or 'same'} | | {v['ci_files'] or 'none'} |")
    open(os.path.join(OUT, "branches", "summary.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("evidence: assessment/branches/evidence.json, summary.md (a suggestion: the user confirms the branch per repository)")


if __name__ == "__main__":
    main()
