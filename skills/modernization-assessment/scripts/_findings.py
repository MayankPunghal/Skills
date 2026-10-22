"""Load findings for downstream steps: scanner output + wiring findings + reviewer verdicts + manual findings, mapped to applications.

assessment/findings/<repo>.json        scan_repo.py
assessment/graphs/<repo>/wiring-findings.json   map_graphs.py (category di-wiring: legacy DI container, captive dependency,
                                         missing registration, service locator, reflection)

assessment/reviews/<repo>.json         {"<finding id>": {"verdict": "confirmed|dismissed|adjusted", "severity": "...",
                                         "confidence": "...", "note": "...", "reviewer": "...", "app": "<app id, optional>"}}
assessment/reviews/<repo>.manual.json  [ {finding written by the reviewer: rule "MAN-...", category, title, severity,
                                         confidence, project, evidence: [{file, line, text}], why, fix, alt, effort_key} ]
assessment/linux/<repo>/linux-readiness.json   linux_readiness.py (step 3.2, the linux-readiness skill's scanner):
                                         blocking and warn hits of checks this skill's own rules do not already cover
                                         become findings (one per check and project, rule = the LNX- id), so they are
                                         reviewed, costed and planned like any other finding
"""
import json
import os
import re
from collections import Counter

from _common import OUT, data, linux_readiness_dir, mask, read_json, slug

SEV_ORDER = {"Blocker": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
CONF_ORDER = {"Confirmed": 0, "Likely": 1, "Needs verification": 2}

# Linux readiness level -> finding severity and effort key (data/estimation.json finding_hours). Info hits are not
# findings: they stay in the Linux readiness section of the report as "verify".
LNX_SEVERITY = {"block": "High", "warn": "Medium"}
LNX_EFFORT = {"block": "small-change", "warn": "trivial"}
# Linux readiness area -> this skill's finding category (all three are in the "linux" segment).
LNX_CATEGORY = {"File system and paths": "file-handling", "Encodings, line endings and text": "file-handling",
                "Time zones": "time-culture", "Globalization and culture (ICU vs NLS)": "time-culture"}
LNX_EVIDENCE = 25
_LNX = {}


def linux_catalogue():
    """{rule id: catalogue row} of the linux-readiness skill, or {} when the skill is not installed."""
    if "rules" not in _LNX:
        d = linux_readiness_dir()
        cat = json.load(open(os.path.join(d, "scripts", "data", "linux_readiness.json"), encoding="utf-8")) if d else {"rules": []}
        _LNX["rules"] = {r["id"]: r for r in cat["rules"]}
        _LNX["ma_ids"] = {r["id"] for r in data("rules.json")["rules"]}
    return _LNX["rules"]


def linux_counted_by(rule):
    """The rules of this skill that cover a Linux readiness check (named in the catalogue's already_in), and whether the
    catalogue calls it covered with no rule named. A check is costed as its own finding unless one of those rules has a
    finding in the same repository (or it is covered with no rule named)."""
    linux_catalogue()
    ids = sorted({t for t in re.findall(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", rule.get("already_in", "")) if t in _LNX["ma_ids"]})
    return ids, rule.get("coverage") == "COVERED" and not ids


def linux_title(rule):
    what = re.sub(r"\s+", " ", rule.get("what", "")).strip()
    head = what.split(": ")[0]
    return short(head if 20 <= len(head) <= 110 else what, 110)


def linux_findings(root, repo, raw):
    """Blocking and warn hits of the Linux readiness report as findings, for checks this skill's rules do not cover here:
    a check whose covering rule already has a finding in this repository is skipped (no double count)."""
    rep = read_json(os.path.join(root, OUT, "linux", repo, "linux-readiness.json"))
    cat = linux_catalogue() if rep else {}
    if not rep or not cat:
        return []
    inv = load_inventory(root, repo)
    pidx = project_index(inv) if inv else []
    have = {f["rule"].split(":")[0] for f in raw}
    groups = {}
    for h in rep.get("hits", []):
        r = cat.get(h["rule"])
        if not r or h.get("waived") or r["level"] not in LNX_SEVERITY:
            continue
        ids, covered = linux_counted_by(r)
        if covered or have & set(ids):
            continue
        proj = project_of_file(pidx, h["file"]) or "(repository)"
        groups.setdefault((h["rule"], proj), []).append(h)
    out = []
    for (rid, proj), hs in sorted(groups.items()):
        r = cat[rid]
        known = [s for s in r.get("sources", []) if s != "K"]
        out.append({"id": f"{repo}:{rid}:{slug(proj)}", "repo": repo, "project": proj, "rule": rid,
                    "category": LNX_CATEGORY.get(r["area"], "linux-readiness"), "title": linux_title(r),
                    "severity": LNX_SEVERITY[r["level"]], "confidence": "Likely" if known else "Needs verification",
                    "occurrences": len(hs), "files": sorted({h["file"] for h in hs}),
                    "evidence": [{"file": h["file"], "line": h["line"], "text": mask(h["text"])} for h in hs[:LNX_EVIDENCE]],
                    "why": r.get("what", ""), "fix": r.get("fix", ""), "alt": "", "effort_key": LNX_EFFORT[r["level"]],
                    "baseline": False, "source": "linux-readiness"})
    return out


def repos(root):
    st = read_json(os.path.join(root, OUT, "state.json"), {"repos": {}})
    return sorted(r for r, v in st["repos"].items() if v.get("scope") != "out")  # repositories with no .NET project are not assessed


def load_inventory(root, repo):
    return read_json(os.path.join(root, OUT, "inventory", f"{repo}.json"))


def load(root, repo, include_dismissed=False):
    raw = read_json(os.path.join(root, OUT, "findings", f"{repo}.json"), []) or []
    raw = raw + (read_json(os.path.join(root, OUT, "graphs", repo, "wiring-findings.json"), []) or [])  # map_graphs.py: DI / wiring
    raw = raw + linux_findings(root, repo, raw)  # linux_readiness.py: checks this skill's rules do not cover
    reviews = read_json(os.path.join(root, OUT, "reviews", f"{repo}.json"), {}) or {}
    manual = read_json(os.path.join(root, OUT, "reviews", f"{repo}.manual.json"), []) or []
    out = []

    def masked(f):  # every snippet passes the secret mask again, whichever script wrote it
        if any(e.get("text") and mask(e["text"]) != e["text"].strip()[:220] for e in f.get("evidence") or []):
            f = dict(f, evidence=[dict(e, text=mask(e["text"])) if e.get("text") else e for e in f["evidence"]])
        return f

    def reviewed(f, r):  # apply a review verdict; None = dismissed and not wanted
        if not r:
            return f
        f = dict(f)
        f["review"] = r
        if r.get("verdict") == "dismissed":
            if not include_dismissed:
                return None
            f["dismissed"] = True
        for k in ("severity", "confidence", "fix", "alt", "title"):
            if r.get(k):
                f[k] = r[k]
        if r.get("verdict") == "confirmed" and f.get("confidence") != "Confirmed":
            f["confidence"] = "Confirmed"
        return f

    for f in raw:
        f = reviewed(masked(f), reviews.get(f["id"]))
        if f:
            out.append(f)
    seen = Counter()
    for m in manual:
        m = dict(m)
        rule = m.get("rule", "MAN")
        seen[rule] += 1
        legacy = f"{repo}:{rule}:{len(out)}"  # the id this loader gave before manual ids were stable
        m.setdefault("repo", repo)
        m.setdefault("source", "review")
        m.setdefault("occurrences", len(m.get("evidence", [])) or 1)
        m.setdefault("files", sorted({e.get("file") for e in m.get("evidence", []) if e.get("file")}))
        m.setdefault("id", f"{repo}:{rule}" + (f":{seen[rule]}" if seen[rule] > 1 else ""))
        m.setdefault("baseline", False)
        m.setdefault("effort_key", "small-change")
        m.setdefault("manual", True)
        # a manual finding takes a verdict by its id, by repo:rule, by its rule id or by the old positional id
        m = reviewed(masked(m), reviews.get(m["id"]) or reviews.get(f"{repo}:{rule}") or reviews.get(rule) or reviews.get(legacy))
        if m:
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
    # line 0 = file-level evidence (e.g. a file that should exist and does not)
    return any(e.get("file") and (isinstance(e.get("line"), int) or e.get("package")) for e in ev) or bool(f.get("package"))


def evidence_ref(e):
    return f"{e.get('file')}:{e.get('line')}" if e.get("line") else str(e.get("file"))


def short(text, n=160):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 1] + "…"
