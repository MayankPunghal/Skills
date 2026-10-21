"""Cross-check the application-to-server mapping workbook the client filled in against what we already know. Finds contradictions; confirms nothing by itself.

    python <skill>/scripts/check_mapping.py --workbook <filled Application-Server-Mapping.xlsx>

Compares the client's answers (sheets Applications, Servers, Other projects) with the DevOps server list (assessment/infra/servers.json), the
solutions found in the code (assessment/solutions/index.json) and the inferred address roles (assessment/infra/address_roles.json):

  UNKNOWN SERVER     a server name that is not in the DevOps list (typo? the closest names are suggested)
  ENVIRONMENT        a server listed under Production / UAT / Sandbox / CDN whose environment in the DevOps list is another one
  OPERATING SYSTEM   a .NET Framework application placed on a Linux server
  IP ADDRESS         an invalid address, or one address given to two servers
  ROLE CONTRADICTION an address our code uses as Redis (say) given to a server whose name says SQL Server
  ROLE CONFIRMED     the same, but the name agrees: an inferred role is now backed by the client's own data
  NOT MAPPED         internal IPs the code uses that no server in the Servers sheet carries yet

Findings are questions for the client or DevOps, not corrections: the client's workbook can be wrong, and so can a server name. Nothing is changed;
assessment/infra/mapping-check.json and mapping-check.md are written. Names and addresses only, no values from the code.
"""
import argparse
import difflib
import ipaddress
import os
import re

from _common import OUT, load_config, read_json, utf8_stdout, write_json
import _xlsx

try:
    from address_roles import LIST_ROLE
except Exception:  # pragma: no cover
    LIST_ROLE = {}

EMPTY = {"", "unknown", "n/a", "na", "none", "-", "tbd", "?"}
ENV_COLS = [("production server", "Production"), ("uat server", "UAT"), ("sandbox server", "Sandbox"), ("cdn server", "CDN")]


def cells(rows, header_start):
    hi = next((i for i, r in enumerate(rows[:10]) if any(str(c).strip().lower().startswith(header_start) for c in r)), 0)
    head = [str(c).strip().lower() for c in rows[hi]]
    return head, rows[hi + 1:]


def col(head, start):
    return next((i for i, h in enumerate(head) if h.startswith(start)), None)


def env_cols(head):
    """Environment columns by header: '<Environment> server(s)' (any environment the sheet names, as build_mapping_sheet.py writes them),
    else the four classic ones. Returns {environment as written: column index}."""
    out = {}
    for i, h in enumerate(head):
        m = re.match(r"^(.+?)\s+servers?\b", h)
        if m and not h.startswith(("server name", "other")):
            out[m.group(1).strip().title() if m.group(1).strip() not in ("uat", "cdn") else m.group(1).strip().upper()] = i
    return out or {env: col(head, start) for start, env in ENV_COLS}


def names_in(text):
    return [t for t in re.split(r"[,;/\n]+|\s{2,}", str(text or "")) if t.strip() and t.strip().lower() not in EMPTY]


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", required=True)
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    sv = (read_json(os.path.join(OUT, "infra", "servers.json")) or {}).get("servers", [])
    if not sv:
        raise SystemExit("import the DevOps server list first (map_infra.py --servers <file>)")
    by_name = {x["name"].lower(): x for x in sv}
    idx = read_json(os.path.join(OUT, "solutions", "index.json"), {}) or {}
    roles = {o["address"]: o for o in (read_json(os.path.join(OUT, "infra", "address_roles.json"), {}) or {}).get("addresses", [])}
    netfx = set()
    for s in idx.get("solutions", []):
        if any(p.get("family") == "netfx" for p in s.get("projects", [])):
            netfx.add(s["repo"].lower())
    book = _xlsx.read(a.workbook)
    apps_rows = next((v for k, v in book.items() if k.lower().startswith("applications")), [])
    srv_rows = next((v for k, v in book.items() if k.lower().startswith("servers")), [])
    oth_rows = next((v for k, v in book.items() if k.lower().startswith("other")), [])
    findings = []

    def add(kind, where, text, severity="CHECK"):
        findings.append({"check": kind, "where": where, "severity": severity, "text": text})

    # applications and other projects: server names, environments, operating system
    filled = {}
    for label, rows, first in (("Applications", apps_rows, "application"), ("Other projects", oth_rows, "project name")):
        if not rows:
            continue
        head, body = cells(rows, first)
        icol = env_cols(head)
        for r in body:
            name = str(r[0]).strip() if r else ""
            if not name:
                continue
            for env, ci in icol.items():
                if ci is None or ci >= len(r):
                    continue
                for srv in names_in(r[ci]):
                    filled[label] = filled.get(label, 0) + 1
                    x = by_name.get(srv.strip().lower())
                    if not x:
                        close = difflib.get_close_matches(srv.strip().lower(), list(by_name), n=3, cutoff=0.7)
                        add("UNKNOWN SERVER", f"{label}: {name} ({env})", f"'{srv}' is not in the DevOps list" + (f"; closest: {', '.join(by_name[c]['name'] for c in close)}" if close else ""))
                        continue
                    if (x.get("environment") or "").lower() not in ("", env.lower()):
                        add("ENVIRONMENT", f"{label}: {name} ({env})", f"{x['name']} is {x['environment']} in the DevOps list but listed under {env}")
                    if x.get("os_family") == "linux" and name.lower() in netfx:
                        add("OPERATING SYSTEM", f"{label}: {name}", f"a .NET Framework application is placed on {x['name']} ({x.get('os')})", "CONTRADICTION")

    # servers: addresses
    ip_to_server = {}
    if srv_rows:
        head, body = cells(srv_rows, "server name")
        ni, ii = col(head, "server name"), col(head, "ip")
        for r in body:
            nm = str(r[ni]).strip() if ni is not None and ni < len(r) else ""
            if not nm or ii is None or ii >= len(r):
                continue
            if nm.lower() not in by_name:
                add("UNKNOWN SERVER", f"Servers: {nm}", "the name is not in the DevOps list")
            for tok in re.findall(r"[0-9A-Fa-f:.]{3,}", str(r[ii])):
                if tok.lower() in EMPTY:
                    continue
                try:
                    ip = str(ipaddress.ip_address(tok))
                except ValueError:
                    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", tok):
                        add("IP ADDRESS", f"Servers: {nm}", f"'{tok}' is not a valid address")
                    continue
                if ip in ip_to_server and ip_to_server[ip] != nm:
                    add("IP ADDRESS", f"Servers: {nm}", f"{ip} is also given to {ip_to_server[ip]}")
                ip_to_server.setdefault(ip, nm)
    # roles: what the code says an address is, against what the server's name says it is
    confirmed = contradicted = 0
    for ip, nm in sorted(ip_to_server.items()):
        o = roles.get(ip)
        x = by_name.get(nm.lower())
        if not o or not o.get("role") or not x:
            continue
        code_roles = {LIST_ROLE.get(p.strip()) for p in re.split(r" and | / ", o["role"]) if LIST_ROLE.get(p.strip())}
        srv_roles = {r_["role"] for r_ in x.get("roles") or []}
        if not code_roles or not srv_roles:
            continue
        if code_roles & srv_roles:
            confirmed += 1
            add("ROLE CONFIRMED", f"{ip} = {nm}", f"the code uses it as {o['role']}; the server name says {', '.join(sorted(srv_roles))}", "CONFIRMED")
        else:
            contradicted += 1
            add("ROLE CONTRADICTION", f"{ip} = {nm}", f"the code uses it as {o['role']}; the server name says {', '.join(sorted(srv_roles))}", "CONTRADICTION")
    internal = [o for o in roles.values() if o["type"] == "private IP"]
    missing = sorted(o["address"] for o in internal if o["address"] not in ip_to_server)
    if internal:
        add("NOT MAPPED", "Servers sheet", f"{len(missing)} of {len(internal)} private IPs the code uses are not given to any server" + (": " + ", ".join(missing[:12]) + (" ..." if len(missing) > 12 else "") if missing else ""), "INFO")
    order = {"CONTRADICTION": 0, "CHECK": 1, "INFO": 2, "CONFIRMED": 3}
    findings.sort(key=lambda f: (order[f["severity"]], f["check"], f["where"]))
    write_json(os.path.join(OUT, "infra", "mapping-check.json"), {"workbook": os.path.basename(a.workbook), "findings": findings})
    lines = [f"# Mapping check: {os.path.basename(a.workbook)}", "",
             f"{sum(1 for f in findings if f['severity'] == 'CONTRADICTION')} contradictions, {sum(1 for f in findings if f['severity'] == 'CHECK')} to check, {confirmed} roles confirmed, {len(ip_to_server)} server addresses given.", "",
             "| Result | Check | Where | Detail |", "|---|---|---|---|"] + [f"| {f['severity']} | {f['check']} | {f['where']} | {f['text']} |" for f in findings]
    open(os.path.join(OUT, "infra", "mapping-check.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"{len(findings)} findings: " + ", ".join(f"{k} {sum(1 for f in findings if f['severity'] == k)}" for k in order if any(f['severity'] == k for f in findings)))
    for f in findings[:25]:
        print(f"  {f['severity']:13} {f['check']:18} {f['where']}: {f['text']}")
    print("assessment/infra/mapping-check.md written. These are questions, not corrections.")


if __name__ == "__main__":
    main()
