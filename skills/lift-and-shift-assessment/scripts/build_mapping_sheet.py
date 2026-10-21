"""Writes the blank application-to-server mapping workbook the client fills in and returns. check_mapping.py reads it back.

    py <skill>/scripts/build_mapping_sheet.py [--out PATH]

Needs solutions.py first (assessment/solutions/index.json). The servers and the environments come from map_infra.py --servers FILE
(assessment/infra/servers.json) when it was imported; otherwise from the intake answer on environments; otherwise Production, UAT and Development.
Writes assessment/documents/<Client>-Application-Server-Mapping.xlsx (or --out PATH) with four sheets:
  Read me          what to fill in, in plain words; no passwords; nothing to install or run on a server
  Applications     one row per solution: repository, solution, deployables, .NET version and application type (from the code), then one
                   server column per environment. The server columns are never pre-filled: which application runs on which server is not guessed from names
  Servers          every server of the DevOps list: name, environment, operating system, IP address(es) when the list has them
  Other projects   for projects whose repositories we cannot access: one row per project, blank for the client to fill in
Sheet and column names are the ones check_mapping.py reads (its server-column check knows Production, UAT, Sandbox and CDN only).
"""
import argparse
import os
import re

from _common import OUT, load_config, read_json, utf8_stdout
import _xlsx
from intake import split_envs

DEFAULT_ENVS = ["Production", "UAT", "Development"]
ENV_ORDER = ["production", "uat", "sandbox", "cdn"]  # the order check_mapping.py knows; any other environment follows alphabetically
DETAIL_APP = ["IIS website name(s)", "Address (host name, port, https or not)", "Scheduled tasks or Windows services (name, schedule)",
              "Settings kept outside the code (names and where they are set, no passwords)", "Who can confirm (person, team or source)", "Notes"]
DETAIL_OTHER = ["What it does (one line)", "Repository or source (if any)", ".NET version", "Project type (MVC, WebForms, Web API, console, Windows service ...)",
                "Hosting OS (Windows / Linux)", "IIS website name(s) and address (if any)", "Scheduled tasks or Windows services (if any)",
                "Projects or services it talks to (name, address) (if any)", "Databases it uses (type, server, database name) (if any)",
                "Other dependencies (SFTP, SMTP, Redis, Elasticsearch, APIs ...) (if any)", "Settings kept outside the code (names only, no passwords) (if any)",
                "Who can confirm (if any)", "Notes (if any)"]
OTHER_ROWS = 15
SERVER_ROWS_WITHOUT_LIST = 20


def environments(cfg, servers):
    """Environments from the server list when imported, else from the intake answer, else the default three. One spelling per name, ordered."""
    seen = {}
    for s in servers:
        e = (s.get("environment") or "").strip()
        if e:
            seen.setdefault(e.lower(), e)
    if not seen:
        for e in split_envs((cfg.get("intake") or {}).get("environments")):
            seen.setdefault(e.lower(), e)
    if not seen:
        return list(DEFAULT_ENVS)
    return [seen[k] for k in sorted(seen, key=lambda k: (ENV_ORDER.index(k) if k in ENV_ORDER else len(ENV_ORDER), k))]


def server_cols(envs):
    return [f"{e} server(s)" for e in envs]


def application_rows(envs):
    idx = read_json(os.path.join(OUT, "solutions", "index.json"))
    if not idx:
        raise SystemExit("run solutions.py first (assessment/solutions/index.json is missing)")
    sols = sorted(idx.get("solutions", []), key=lambda s: (s["repo"].lower(), s["solution"].lower()))
    rows = [["Application (repository)", "Solution", "Deployables (projects that are deployed)", ".NET version (from the code)", "Application type (from the code)"]
            + server_cols(envs) + DETAIL_APP]
    for s in sols:
        deploy = ", ".join(s.get("deployables") or []) or "none (library only)"
        types = ", ".join(sorted({p["type"] for p in s.get("projects", []) if p.get("type")}))
        rows.append([s["repo"], s["solution"], deploy, ", ".join(s.get("frameworks") or []), types] + [""] * (len(envs) + len(DETAIL_APP)))
    return rows, len(sols)


def server_rows(servers):
    rows = [["Server name", "Environment", "Operating system", "IP address(es)", "Notes"]]
    if not servers:
        return rows + [[""] * 5 for _ in range(SERVER_ROWS_WITHOUT_LIST)]
    for s in sorted(servers, key=lambda s: ((s.get("environment") or "").lower(), s["name"].lower())):
        rows.append([s["name"], s.get("environment") or "", s.get("os") or "", s.get("ip") or "", ""])
    return rows


def other_rows(envs):
    head = ["Project name"] + DETAIL_OTHER[:4] + server_cols(envs) + DETAIL_OTHER[4:]
    return [head] + [[""] * len(head) for _ in range(OTHER_ROWS)]


def readme_rows(envs, has_servers):
    srv = ("Sheet 'Servers': the servers from the server list you shared, with name, environment and operating system. Please check them and add the IP address(es) "
           "where they are blank (several addresses separated by commas)." if has_servers else
           "Sheet 'Servers': one row per server: name, environment, operating system and IP address(es) (several addresses separated by commas).")
    return [
        ["Application to server mapping: what we need from you"],
        [""],
        ["We need to know which application runs on which server in each environment, so that the move to AWS can be planned. The applications come from the code "
         "we were given. The server names come from your server list."],
        [""],
        ["Sheet 'Applications': one row per solution found in the code. The repository, solution, deployables, .NET version and application type are already filled in from the code. Please fill in the rest."],
        ["Server columns (one per environment: " + ", ".join(envs) + "): the name(s) of the server(s) the application runs on in that environment, comma separated. "
         "Leave it empty if the application is not in that environment."],
        ["The server columns are empty on purpose: we have not guessed which application runs on which server from the server names. Only you can confirm that."],
        ["  - IIS website name(s) and the address used to reach it (host name, port, https or not)."],
        ["  - Scheduled tasks or Windows services it uses (name and schedule)."],
        ["  - Settings kept outside the code (names and where they are set). Never passwords. The deployment pipeline or deployment tool usually holds these."],
        ["  - Who can confirm: the person, team or source (deployment tool, IIS Manager, runbook) that knows the answer."],
        ["  - If a detail differs per environment, write it as 'Production: ...; UAT: ...'."],
        [""],
        [srv],
        ["Sheet 'Other projects': only for projects whose repositories we could not access. One row per project. Columns marked (if any) can be left empty."],
        [""],
        ["Write 'unknown' where you do not know. A partial answer is more useful than none."],
        ["No passwords, please. Write setting names only."],
        ["Nothing needs to be installed or run on any server."],
    ]


def client_file_name(cfg):
    name = re.sub(r"[^A-Za-z0-9]+", "-", str(cfg.get("client") or "")).strip("-")
    return name or "Client"


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Write the blank application-to-server mapping workbook for the client.")
    ap.add_argument("--out", help="output .xlsx (default: assessment/documents/<Client>-Application-Server-Mapping.xlsx)")
    a = ap.parse_args()
    out_arg = os.path.abspath(a.out) if a.out else None
    root, cfg = load_config()
    os.chdir(root)
    out = out_arg or os.path.join(root, OUT, "documents", f"{client_file_name(cfg)}-Application-Server-Mapping.xlsx")
    servers = (read_json(os.path.join(OUT, "infra", "servers.json")) or {}).get("servers", [])
    envs = environments(cfg, servers)
    apps, n_apps = application_rows(envs)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    _xlsx.write(out, [
        ("Read me", readme_rows(envs, bool(servers)), [130], [0]),
        _xlsx.auto("Applications", apps),
        _xlsx.auto("Servers", server_rows(servers)),
        _xlsx.auto("Other projects", other_rows(envs)),
    ])
    print(f"{out}: {n_apps} applications (solutions), {len(servers)} servers, environments: {', '.join(envs)}"
          + ("" if servers else " (no server list imported: Servers sheet left for the client)"))


if __name__ == "__main__":
    main()
