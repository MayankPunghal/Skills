"""Estimate in developer working hours (AI-assisted), per solution and for the whole project.

    python <skill>/scripts/estimate_hours.py

Reads assessment/solutions/index.json, third_party.json and the intake answers, applies the rates of data/hours.json to the counts and
writes assessment/estimate.json. Only the work items the intake selected are estimated. Rates marked 'sample' are calibrated to the
manager's reference estimate (source of truth); rates marked 'inferred' are the skill's own estimate with nothing behind them yet.
A project shared by two solutions is counted once (in the first solution that lists it). Nothing is final: the estimate is a draft
until the user says so, and every rate can be changed in data/hours.json.
"""
import math
import os
import re

from _common import OUT, data, load_config, mark_step, read_json, utf8_stdout, write_json
import intake as I


def half(x):
    return math.ceil(x * 2 - 1e-9) / 2


def main():
    utf8_stdout()
    root, cfg = load_config()
    os.chdir(root)
    import intake as _intake
    _intake.require(cfg, root, ['before_scan', 'after_scan', 'after_build'], "estimate_hours.py")
    idx = read_json(os.path.join(OUT, "solutions", "index.json"))
    tp = read_json(os.path.join(OUT, "solutions", "third_party.json"))
    if not idx or not tp:
        raise SystemExit("run solutions.py and third_party.py first")
    rates = data("hours.json")
    items = I.selected(cfg)
    if not items:
        raise SystemExit("no work item selected in the intake: nothing to estimate")
    rekey = {s["id"]: s["rekey_count"] for s in tp["solutions"]}
    ia = cfg.get("intake") or {}
    piped = {x.strip().lower() for x in re.split(r"[,;\n]", str(ia.get("pipeline_solutions") or "")) if x.strip()} if ia.get("pipeline_scope") == "selected" else None
    seen, per = set(), []
    for s in idx["solutions"]:
        own = [p for p in s["projects"] if (s["repo"], p["path"]) not in seen]
        for p in s["projects"]:
            seen.add((s["repo"], p["path"]))
        own_names = {p["name"] for p in own}
        counts = {
            "env_vars": len(s["env_vars"]), "config_files": len(s["config_files"]), "endpoints": len(s["endpoints"]),
            "rekey": rekey.get(s["id"], 0), "solutions": 1, "workloads": len(s["workloads"]),
            "deployables": len([d for d in s["deployables"] if d in own_names]), "solution_deployables": len(s["deployables"]),
            "projects": len(own), "retarget_projects": len([n for n in s["retarget_projects"] if n in own_names]),
            "retarget_solutions": 1 if s["retarget_projects"] else 0,
        }
        lines = []
        for it in items:
            for ln in rates["items"][it]["lines"]:
                n = counts[ln["driver"]]
                if ln["id"].startswith("pipeline") and piped is not None and not ({s["solution"].lower(), s["id"].lower(), s["repo"].lower()} & piped):
                    n = 0  # intake: only some solutions get a pipeline
                if n:
                    lines.append({"work_item": it, "id": ln["id"], "label": ln["label"], "count": n, "unit": ln["unit"], "rate": ln["rate"],
                                  "low": n * ln["rate"][0], "high": n * ln["rate"][1], "basis": ln["basis"]})
        per.append({"id": s["id"], "counts": counts, "lines": lines, "low": sum(x["low"] for x in lines), "high": sum(x["high"] for x in lines),
                    "environments": s["environments"], "environments_assumed": s["environments_assumed"]})
    low = sum(p["low"] for p in per)
    high = sum(p["high"] for p in per)
    pct = rates["contingency_pct"]
    by_item = {}
    for p in per:
        for x in p["lines"]:
            b = by_item.setdefault(x["work_item"], {"low": 0, "high": 0})
            b["low"] += x["low"]
            b["high"] += x["high"]
    sample_low = sum(x["low"] for p in per for x in p["lines"] if x["basis"] == "sample")
    sample_high = sum(x["high"] for p in per for x in p["lines"] if x["basis"] == "sample")
    t_low, t_high = half(low * (1 + pct / 100)), half(high * (1 + pct / 100))
    day = rates["day_hours"]
    final = (cfg.get("intake") or {}).get("final")
    est = {
        "work_items": items, "solutions": per,
        "by_work_item": {k: {"label": rates["items"][k]["label"], "low": half(v["low"]), "high": half(v["high"])} for k, v in by_item.items()},
        "subtotal": {"low": half(low), "high": half(high)}, "contingency_pct": pct,
        "contingency": {"low": half(low * pct / 100), "high": half(high * pct / 100)},
        "total": {"low": t_low, "high": t_high}, "days_low": half(t_low / day), "days_high": half(t_high / day), "day_hours": day,
        "sample_basis": {"low": half(sample_low * (1 + pct / 100)), "high": half(sample_high * (1 + pct / 100))},
        "inferred_share": {"low": half((low - sample_low) * (1 + pct / 100)), "high": half((high - sample_high) * (1 + pct / 100))},
        "environments_assumed": idx["environments_assumed"],
        "status": "FINAL" if final else "DRAFT: estimate, nothing is final until the user says so",
    }
    write_json(os.path.join(OUT, "estimate.json"), est)
    mark_step(root, "estimate")
    print(f"TOTAL {t_low}-{t_high} dev hours incl. {pct}% buffer ({est['days_low']}-{est['days_high']} dev days of {day} h) · {est['status']}")
    for k, v in est["by_work_item"].items():
        print(f"  {v['label']}: {v['low']}-{v['high']} h (before buffer)")
    for p in per:
        print(f"  {p['id']}: {half(p['low'])}-{half(p['high'])} h")
    print(f"  of the total, calibrated to the sample: {est['sample_basis']['low']}-{est['sample_basis']['high']} h; inferred by the skill: {est['inferred_share']['low']}-{est['inferred_share']['high']} h")


if __name__ == "__main__":
    main()
