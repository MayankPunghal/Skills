"""Load findings for downstream steps: scanner output + wiring findings + reviewer verdicts + manual findings, mapped to applications.

assessment/findings/<repo>.json        scan_repo.py
assessment/graphs/<repo>/wiring-findings.json   map_graphs.py (category di-wiring: legacy DI container, captive dependency,
                                         missing registration, service locator, reflection)

assessment/reviews/<repo>.json         {"<finding id>": {"verdict": "confirmed|dismissed|adjusted", "severity": "...",
                                         "confidence": "...", "note": "...", "reviewer": "...", "app": "<app id, optional>"}}
assessment/reviews/<repo>.manual.json  [ {finding written by the reviewer: rule "MAN-...", category, title, severity,
                                         confidence, project, evidence: [{file, line, text}], why, fix, alt, effort_key} ]
"""
import os
import re

from _common import OUT, read_json

SEV_ORDER = {"Blocker": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
CONF_ORDER = {"Confirmed": 0, "Likely": 1, "Needs verification": 2}


def repos(root):
    st = read_json(os.path.join(root, OUT, "state.json"), {"repos": {}})
    return sorted(r for r, v in st["repos"].items() if v.get("scope") != "out")  # repositories with no .NET project are not assessed


def load_inventory(root, repo):
    return read_json(os.path.join(root, OUT, "inventory", f"{repo}.json"))


def load(root, repo, include_dismissed=False):
    raw = read_json(os.path.join(root, OUT, "findings", f"{repo}.json"), []) or []
    raw = raw + (read_json(os.path.join(root, OUT, "graphs", repo, "wiring-findings.json"), []) or [])  # map_graphs.py: DI / wiring
    reviews = read_json(os.path.join(root, OUT, "reviews", f"{repo}.json"), {}) or {}
    manual = read_json(os.path.join(root, OUT, "reviews", f"{repo}.manual.json"), []) or []
    out = []
    for f in raw:
        r = reviews.get(f["id"])
        if r:
            f = dict(f)
            f["review"] = r
            if r.get("verdict") == "dismissed":
                if not include_dismissed:
                    continue
                f["dismissed"] = True
            for k in ("severity", "confidence", "fix", "alt", "title"):
                if r.get(k):
                    f[k] = r[k]
            if r.get("verdict") == "confirmed" and f["confidence"] != "Confirmed":
                f["confidence"] = "Confirmed"
        out.append(f)
    for m in manual:
        m = dict(m)
        m.setdefault("repo", repo)
        m.setdefault("source", "review")
        m.setdefault("occurrences", len(m.get("evidence", [])) or 1)
        m.setdefault("files", sorted({e.get("file") for e in m.get("evidence", []) if e.get("file")}))
        m.setdefault("id", f"{repo}:{m.get('rule', 'MAN')}:{len(out)}")
        m.setdefault("baseline", False)
        m.setdefault("effort_key", "small-change")
        out.append(m)
    return out


def project_index(inv):
    return sorted(((os.path.dirname(p["path"]).replace("\\", "/"), p["path"]) for p in inv["projects"]), key=lambda x: -len(x[0]))


def project_of_file(pidx, f):
    f = (f or "").replace("\\", "/")
    for d, p in pidx:
        if d and f.startswith(d + "/"):
            return p
    return None


def assign_apps(findings, inv):
    """Attach app ids: by project membership, package usage, or evidence file location; else repository-wide."""
    pidx = project_index(inv)
    apps_of_proj = {}
    for a in inv["applications"]:
        for p in a["projects"]:
            apps_of_proj.setdefault(p, []).append(a["id"])
        if a["type"] == "website":
            apps_of_proj.setdefault(a["entry"], []).append(a["id"])
    for f in findings:
        projs = set()
        if f.get("review", {}).get("app"):
            f["apps"] = [f["review"]["app"]]
            continue
        if f.get("projects_affected"):
            projs |= set(f["projects_affected"])
        elif f.get("project") and f["project"] != "(repository)":
            projs.add(f["project"])
        else:
            for e in f.get("evidence", []):
                p = project_of_file(pidx, e.get("file"))
                if p:
                    projs.add(p)
        apps = sorted({a for p in projs for a in apps_of_proj.get(p, [])})
        f["apps"] = apps
        f["projects_in_scope"] = sorted(projs)
    return findings


def sort_key(f):
    return (SEV_ORDER.get(f.get("severity"), 9), CONF_ORDER.get(f.get("confidence"), 9), f.get("category", ""), f.get("rule", ""))


def has_evidence(f):
    ev = f.get("evidence") or []
    return any(e.get("file") and (e.get("line") or e.get("package")) for e in ev) or bool(f.get("package"))


def evidence_ref(e):
    return f"{e.get('file')}:{e.get('line')}" if e.get("line") else str(e.get("file"))


def short(text, n=160):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 1] + "…"
