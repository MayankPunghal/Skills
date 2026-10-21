"""Which GitLab projects belong in the assessment? Read-only: GET requests only; nothing is created or changed in GitLab.

    py <skill>/scripts/gitlab_projects.py [--exclude-groups a,b] [--exclude-name-pattern REGEX] [--active-months N]
        [--include-personal] [--include-archived]

Lists the groups and the projects the read token is a member of (GET /groups, GET /projects?membership=true) with default branch,
last activity, archived and empty flags, languages (GET /projects/:id/languages, included projects only) and a dotnet flag
(C# or VB.NET among the languages). Every filter is recorded in the output and in the Source line of the workbook.

Writes:
  assessment/gitlab/projects.json                      every project: included flag and the reasons when excluded
  assessment/documents/<client>-gitlab-projects.xlsx   sheet Projects (included; Languages, .NET code) and sheet Excluded (reason)

Reads gitlab.base_url from assessment.json; the token is the environment variable named in gitlab.token_env (see _common.gitlab_token).
The token is never printed or written.
"""
import argparse
import calendar
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import _xlsx
from _common import OUT, gitlab_token, load_config, slug, utf8_stdout, write_json

WORKERS = 4  # polite: at most four requests in parallel
DOTNET_LANGUAGES = {"c#", "vb.net", "visual basic .net"}
RETRY_CODES = (429, 500, 502, 503, 504)


class Gl:
    """GET-only client for the GitLab v4 API (same approach as branch_evidence.py). There is no other HTTP method here."""

    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/") + "/api/v4", token

    def get(self, path, **q):
        url = self.base + path + ("?" + urllib.parse.urlencode(q) if q else "")
        req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": self.token}, method="GET")
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.load(r), r.headers
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_CODES or attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))  # rate limited or server busy: wait and try again
        raise RuntimeError("unreachable")

    def pages(self, path, **q):
        out, page = [], 1
        while True:
            data, headers = self.get(path, per_page=100, page=page, **q)
            out += data
            if not headers.get("X-Next-Page"):
                return out
            page = int(headers["X-Next-Page"])


def months_before(now, n):
    """The same day n months earlier (clamped to the end of that month)."""
    y, m = now.year, now.month - n
    while m <= 0:
        m += 12
        y -= 1
    return now.replace(year=y, month=m, day=min(now.day, calendar.monthrange(y, m)[1]))


def parse_time(text):
    """GitLab timestamps are UTC, for example 2025-03-04T10:00:00.000Z."""
    if not text:
        return None
    return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)


def is_dotnet(languages):
    return any(name.lower() in DOTNET_LANGUAGES for name in languages)


def language_text(languages):
    return ", ".join(f"{k} {v:.1f}%" for k, v in sorted(languages.items(), key=lambda kv: -kv[1])[:5])


def excluded_group(group, excluded):
    """The excluded group that this group is, or is a subgroup of (case-insensitive); None when it is not excluded."""
    g = group.lower()
    for x in excluded:
        if g == x.lower() or g.startswith(x.lower() + "/"):
            return x
    return None


def source_line(base, f, today):
    parts = [f"Source: GitLab at {base}, projects the connected account is a member of, extracted {today:%Y-%m-%d}."]
    parts.append("Personal (user namespace) projects included." if f["include_personal"] else "Personal (user namespace) projects excluded.")
    parts.append("Archived projects included." if f["include_archived"] else "Archived projects excluded.")
    if f["exclude_groups"]:
        parts.append(f"Groups {', '.join(f['exclude_groups'])} excluded (with their subgroups).")
    if f["exclude_name_pattern"]:
        parts.append(f"Projects with a name matching '{f['exclude_name_pattern']}' excluded (case-insensitive).")
    if f["active_months"]:
        parts.append(f"Projects with no activity in the last {f['active_months']} months (since {f['active_since']}) excluded.")
    return " ".join(parts)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="List the GitLab groups and projects in scope for the assessment (read-only).")
    ap.add_argument("--exclude-groups", default="", help="comma separated group paths to leave out (their subgroups too)")
    ap.add_argument("--exclude-name-pattern", default="", help="regular expression; projects whose name matches (case-insensitive) are left out, e.g. Hackathon")
    ap.add_argument("--active-months", type=int, default=0, help="leave out projects with no activity in the last N months (0 = no filter)")
    ap.add_argument("--include-personal", action="store_true", help="keep personal (user namespace) projects, which are left out by default")
    ap.add_argument("--include-archived", action="store_true", help="keep archived projects, which are left out by default")
    a = ap.parse_args()
    if a.active_months < 0:
        ap.error("--active-months must be 0 or more")
    pattern = None
    if a.exclude_name_pattern:
        try:
            pattern = re.compile(a.exclude_name_pattern, re.IGNORECASE)
        except re.error as e:
            ap.error(f"--exclude-name-pattern is not a valid regular expression: {e}")

    root, cfg = load_config()
    os.chdir(root)
    base = ((cfg.get("gitlab") or {}).get("base_url") or "").strip()
    if not base:
        raise SystemExit('assessment.json has no gitlab.base_url (for example "https://gitlab.example.com"); add it and run again')
    gl = Gl(base, gitlab_token(cfg))

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = months_before(now, a.active_months) if a.active_months else None
    excluded_groups = [x.strip() for x in a.exclude_groups.split(",") if x.strip()]
    filters = {"membership": True, "exclude_groups": excluded_groups, "exclude_name_pattern": a.exclude_name_pattern or None,
               "active_months": a.active_months or None, "active_since": cutoff.strftime("%Y-%m-%d") if cutoff else None,
               "include_personal": a.include_personal, "include_archived": a.include_archived}

    try:
        me, _ = gl.get("/user")
        groups = gl.pages("/groups", all_available="true")
        projects = gl.pages("/projects", membership="true", simple="false")
    except urllib.error.HTTPError as e:  # HTTPError is an OSError too: keep it first
        raise SystemExit(f"GitLab answered HTTP {e.code}: check the read token in the environment variable named by gitlab.token_env "
                         "and that it can read the projects")
    except OSError as e:
        raise SystemExit(f"GitLab at {base} is not reached ({type(e).__name__}): connect to the VPN and run again")
    print(f"token user: {me.get('username')}")

    reason_counts = Counter()
    rows = []
    for p in projects:
        ns = p.get("namespace") or {}
        group = ns.get("full_path") or p["path_with_namespace"].rsplit("/", 1)[0]
        last = parse_time(p.get("last_activity_at"))
        why = []  # (category, text)
        hit = excluded_group(group, excluded_groups)
        if hit:
            why.append(("group", f"group {hit} excluded"))
        if ns.get("kind") == "user" and not a.include_personal:
            why.append(("personal", "personal namespace"))
        if p.get("archived") and not a.include_archived:
            why.append(("archived", "archived"))
        if pattern and pattern.search(p["name"]):
            why.append(("name", f"name matches {a.exclude_name_pattern}"))
        if cutoff and (last is None or last < cutoff):
            when = f"{last:%Y-%m-%d}" if last else "unknown"
            why.append(("inactive", f"no activity in the last {a.active_months} months (last activity {when})"))
        for cat, _ in why:
            reason_counts[cat] += 1
        rows.append({
            "id": p["id"], "path": p["path_with_namespace"], "name": p["name"], "group": group,
            "personal": ns.get("kind") == "user", "archived": bool(p.get("archived")), "empty": bool(p.get("empty_repo")),
            "default_branch": p.get("default_branch"), "last_activity": last.strftime("%Y-%m-%d") if last else None,
            "web_url": p.get("web_url"), "http_url": p.get("http_url_to_repo"), "description": p.get("description") or "",
            "included": not why, "reasons": [t for _, t in why], "languages": None, "dotnet": None,
        })

    included = [r for r in rows if r["included"]]

    def read_languages(r):
        if r["empty"]:
            r["languages"], r["dotnet"] = {}, False  # an empty repository has no languages and no endpoint answer
            return
        try:
            langs, _ = gl.get(f"/projects/{r['id']}/languages")
            r["languages"], r["dotnet"] = langs, is_dotnet(langs)
        except (OSError, ValueError) as e:
            r["languages"], r["dotnet"], r["languages_error"] = None, None, type(e).__name__

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(read_languages, included))

    excluded = [r for r in rows if not r["included"]]
    dotnet_n = sum(1 for r in included if r["dotnet"])
    unread = [r for r in included if r["dotnet"] is None]
    by_group = {}
    for r in rows:
        g = by_group.setdefault(r["group"], {"total": 0, "included": 0, "dotnet_included": 0})
        g["total"] += 1
        g["included"] += int(r["included"])
        g["dotnet_included"] += int(bool(r["dotnet"]))

    source = source_line(base, filters, now)
    rows.sort(key=lambda r: r["path"].lower())
    inc_sorted = [r for r in rows if r["included"]]
    exc_sorted = [r for r in rows if not r["included"]]

    write_json(os.path.join(OUT, "gitlab", "projects.json"), {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "host": base, "filters": filters, "source": source,
        "groups_visible": sorted(g["full_path"] for g in groups),
        "counts": {"projects_seen": len(rows), "included": len(inc_sorted), "excluded": len(exc_sorted), "dotnet_included": dotnet_n},
        "by_group": by_group, "projects": rows,
    })

    def dotnet_cell(r):
        return "unknown" if r["dotnet"] is None else ("yes" if r["dotnet"] else "no")

    sheet = [["#", "Project Name", "Group / Namespace", "Web URL", "HTTPS Clone URL", "Languages", ".NET code (yes/no)"]]
    for i, r in enumerate(inc_sorted, 1):
        sheet.append([str(i), r["name"], r["group"], r["web_url"] or "", r["http_url"] or "",
                      language_text(r["languages"]) if r["languages"] else "", dotnet_cell(r)])
    sheet += [[], ["", source]]
    exc = [["#", "Project Name", "Group / Namespace", "Web URL", "Reason"]]
    for i, r in enumerate(exc_sorted, 1):
        exc.append([str(i), r["name"], r["group"], r["web_url"] or "", "; ".join(r["reasons"])])
    os.makedirs(os.path.join(OUT, "documents"), exist_ok=True)
    xlsx_path = os.path.join(OUT, "documents", f"{slug(cfg.get('client') or '')}-gitlab-projects.xlsx")
    _xlsx.write(xlsx_path, [_xlsx.auto("Projects", sheet), _xlsx.auto("Excluded", exc)])

    print(f"GitLab {base}: {len(rows)} projects the token is a member of, {len(groups)} groups visible")
    print(f"included {len(inc_sorted)}, excluded {len(exc_sorted)}, with .NET code {dotnet_n}")
    if reason_counts:
        print("excluded by reason (a project can have more than one): " + ", ".join(f"{k} {v}" for k, v in reason_counts.most_common()))
    print(f"{'group':<34}{'total':>7}{'included':>10}{'.NET':>7}")
    for g in sorted(by_group):
        s = by_group[g]
        print(f"{g:<34}{s['total']:>7}{s['included']:>10}{s['dotnet_included']:>7}")
    if unread:
        print(f"languages not read for {len(unread)} included projects (shown as unknown)")
    print(f"wrote {os.path.join(OUT, 'gitlab', 'projects.json')} and {xlsx_path}")


if __name__ == "__main__":
    main()
