"""The client's infrastructure / server list: import it, give every server a role, and tie code dependencies to it.

Input: the list the client's DevOps team shares (.xlsx or .csv): one row per server with name, operating system, environment,
installed software, and so on. Column names are matched by synonyms (data/server_roles.json "columns"). Nothing is guessed:
a role comes from the server NAME or its installed-software text by an editable rule, and is shown as "role (from name)".
"""
import csv
import os
import re
from collections import Counter, defaultdict

from _common import data, read_text
import _xlsx


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def load_rows(path, sheet=None):
    if path.lower().endswith((".csv", ".txt")):
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return list(csv.reader(fh)), os.path.basename(path)
    book = _xlsx.read(path)
    name = sheet if sheet in book else max(book, key=lambda n: len(book[n]))  # the biggest sheet unless one is named
    return book[name], name


def import_servers(path, sheet=None):
    cfg = data("server_roles.json")
    rows, sheet_name = load_rows(path, sheet)
    hi = next((i for i, r in enumerate(rows[:15]) if any(_norm(c) in cfg["columns"]["name"] for c in r)), 0)
    header = [_norm(c) for c in rows[hi]]
    idx = {}
    for field, names in cfg["columns"].items():
        for n in names:
            if n in header:
                idx[field] = header.index(n)
                break
    if "name" not in idx:
        raise SystemExit(f"No server-name column found in {path} (looked for {cfg['columns']['name']}); header was: {rows[hi][:12]}")
    roles = [(r["role"], r["label"], re.compile(r["name_regex"]) if r.get("name_regex") else None, re.compile(r["app_regex"]) if r.get("app_regex") else None)
             for r in cfg["roles"]]
    envs = [(e["env"], re.compile(e["regex"])) for e in cfg["env_prefixes"]]
    servers = []

    def cell(r, f):
        i = idx.get(f)
        return str(r[i]).strip() if i is not None and i < len(r) else ""

    for r in rows[hi + 1:]:
        name = cell(r, "name")
        if not name or name == "-":
            continue
        apps = cell(r, "applications")
        sql = cell(r, "sql_edition")
        got = []
        for role, label, nrx, arx in roles:
            if nrx and nrx.search(name):
                got.append({"role": role, "from": "name"})
            elif arx and apps and arx.search(apps):
                got.append({"role": role, "from": "installed software"})
        if sql and sql not in ("-", "") and not any(g["role"] == "sql-server" for g in got):
            got.append({"role": "sql-server", "from": "SQL edition column"})
        env = cell(r, "environment") or next((e for e, rx in envs if rx.search(name)), "")
        osn = cell(r, "os")
        family = "windows" if re.search(r"(?i)windows", osn) else "linux" if re.search(r"(?i)ubuntu|linux|centos|debian|rhel|red hat|suse|alma|rocky", osn) else "unknown"
        servers.append({"name": name, "os": osn or "", "os_family": family, "environment": env or "", "roles": got, "cores": cell(r, "cores"), "memory_gb": cell(r, "memory_gb"),
                        "storage_gb": cell(r, "storage_gb"), "sql_edition": sql if sql != "-" else "", "hypervisor": cell(r, "hypervisor") if cell(r, "hypervisor") != "-" else "",
                        "virtual": cell(r, "virtual"), "ip": cell(r, "ip"), "applications": apps[:400]})
    return {"source": os.path.basename(path), "sheet": sheet_name, "columns_found": sorted(idx), "count": len(servers), "servers": servers}


def summary(sv):
    s = sv["servers"]
    by_role = defaultdict(list)
    for x in s:
        for g in x["roles"]:
            by_role[g["role"]].append(x["name"])
    return {"servers": len(s), "os": dict(Counter(x["os"] or "(blank)" for x in s)), "os_family": dict(Counter(x["os_family"] for x in s)),
            "environments": dict(Counter(x["environment"] or "(blank)" for x in s)), "without_role": sorted(x["name"] for x in s if not x["roles"]),
            "roles": {k: len(v) for k, v in sorted(by_role.items())}}


class Index:
    def __init__(self, sv):
        self.servers = sv["servers"]
        self.by_name = {x["name"].lower(): x for x in self.servers}
        self.by_ip = {ip: x for x in self.servers for ip in re.findall(r"(?:\d{1,3}\.){3}\d{1,3}", x.get("ip") or "")}  # the list's IP column (one or several addresses per server)
        self.by_role = defaultdict(list)
        for x in self.servers:
            for g in x["roles"]:
                self.by_role[g["role"]].append(x)

    def find(self, host):
        h = host.lower()
        if h in self.by_name:
            return self.by_name[h]
        if h in self.by_ip:
            return self.by_ip[h]
        first = h.split(".")[0] if not re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", h) else None
        return self.by_name.get(first) if first else None


def link(deps, index, repo_hosting=None):
    """Tie each dependency of a repository to the server list. Returns the dependency rows with a `link` section:
    status: named (host in code matches a server) | hosts-not-in-list | role-only (no host in code: environment-specific) | no-server-of-this-type | no-list."""
    out = []
    for d in deps:
        l = {"status": "no-list", "matched": [], "unmatched_hosts": [], "candidates": [], "candidate_count": 0, "candidate_envs": {}}
        if index:
            for h in d["hosts"]:
                srv = index.find(h["host"])
                if srv:
                    if srv["name"] not in [m["name"] for m in l["matched"]]:
                        l["matched"].append({"name": srv["name"], "environment": srv["environment"], "os": srv["os"], "via": h["host"] + (f":{h['port']}" if h["port"] else "")})
                elif not re.fullmatch(r"[A-Za-z][A-Za-z]*[-_]?\d{1,3}|[A-Za-z0-9]+([-_][A-Za-z0-9]+)+", h["host"]) or h["port"]:
                    l["unmatched_hosts"].append(h["host"] + (f":{h['port']}" if h["port"] else ""))
            cands = {}
            for role in d["server_roles"]:
                for s in index.by_role.get(role, []):
                    cands[s["name"]] = s
            l["candidates"] = sorted(cands)
            l["candidate_count"] = len(cands)
            l["candidate_envs"] = dict(Counter(s["environment"] or "(blank)" for s in cands.values()))
            if l["matched"]:
                l["status"] = "named: server in the list"
            elif not cands:
                l["status"] = "no server of this type in the list"
            elif l["unmatched_hosts"]:
                l["status"] = "host in code is not a name in the list (IP or alias)"
            else:
                l["status"] = "no host in code (set per environment): candidates by type"
        out.append({**d, "link": l})
    return out
