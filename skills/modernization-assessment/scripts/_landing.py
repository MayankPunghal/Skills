"""Lift-and-shift view of the findings (standard library only).

A lift-and-shift moves the same servers to Amazon EC2 with the same operating system. The only question that matters is what stops working
or behaves differently when the application leaves the on-premises servers, and who acts on it. `data/landing.json` answers that for every
rule. Findings of rules that are not listed there are "future": they matter only if the code is modernized later (Linux, .NET 10,
PostgreSQL), so they go to the Future options section and are never costed.

annotate(findings, cfg) adds to every finding:
  f["landing"] = {"relevance": "move" | "future", "area", "owner", "change", "action", "costed"}
and, for a "move" finding, replaces f["severity"] with the lift-and-shift severity (the modernization severity stays in
f["severity_modern"]; a reviewer's severity always wins).
"""
from _common import data

_CACHE = {}


def is_lift(cfg):
    return (cfg or {}).get("assessment_type") == "lift-and-shift" or (not (cfg or {}).get("assessment_type") and ((cfg or {}).get("scenario") or {}).get("hosting") == "lift-and-shift")


def table():
    if "t" not in _CACHE:
        _CACHE["t"] = data("landing.json")
    return _CACHE["t"]


def base_rule(rule):
    return (rule or "").split(":")[0]


def classify(rule):
    """The lift-and-shift entry of a rule, or None when the rule only matters for modernization."""
    row = table()["rules"].get(base_rule(rule))
    if not row:
        return None
    area, owner, change, severity, action = row
    return {"area": area, "owner": owner, "change": change, "severity": severity, "action": action}


def costed(landing):
    """The estimate covers code changes by the application team. Configuration changes are priced per CI variable (estimate_effort.lift_config_hours);
    server, network, identity and database items belong to DevOps or the DB team and are hand-offs."""
    return bool(landing) and landing.get("relevance") == "move" and landing["owner"] == "dotnet" and landing["change"] == "code"


def annotate(findings, cfg):
    if not is_lift(cfg):
        return findings
    for f in findings:
        mine = f.get("landing") if isinstance(f.get("landing"), dict) and f["landing"].get("owner") else None  # a reviewer's manual finding may carry its own
        c = dict(mine) if mine else classify(f.get("rule"))
        if mine:
            c.setdefault("area", "machine")
            c.setdefault("change", "verify")
            c.setdefault("severity", f.get("severity", "Medium"))
            c.setdefault("action", f.get("fix", ""))
        if not c:
            f["landing"] = {"relevance": "future", "costed": False}
            continue
        c["relevance"] = "move"
        c["costed"] = costed(c)
        f["landing"] = c
        if "severity_modern" not in f:
            f["severity_modern"] = f["severity"]
        if not (f.get("review") or {}).get("severity"):
            f["severity"] = c["severity"]
    return findings


def moves(f):
    return (f.get("landing") or {}).get("relevance") == "move"


def owner_label(key):
    return table()["owners"].get(key, key)


def change_label(key):
    return table()["changes"].get(key, key)


def area_label(key):
    return table()["areas"].get(key, key)
