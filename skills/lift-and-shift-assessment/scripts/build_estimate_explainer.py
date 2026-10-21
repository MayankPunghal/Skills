"""Plain-English explanation of how every hour in the effort estimate was built, for a manager who wants to check or change the numbers.

    py <skill>/scripts/build_estimate_explainer.py [--out DIR]

Run from the workspace folder (the one holding assessment.json) after estimate_hours.py and build_doc.py, so the draft number is the
one build_doc.py last wrote. Reads assessment/estimate.json (every number), data/hours.json (the rates now in force), data/intake.json
(work item wording), assessment/documents/meta.json (the draft number), assessment/solutions/index.json (repository names) and the
intake answers in assessment.json. Writes <client>-effort-estimate-explained.md and its .html twin into DIR (default assessment/documents;
relative to the workspace).

Self-check: every line is recomputed (count x rate = hours), each weight is checked against its inputs, and the subtotal, buffer, total,
dev-days, work item, sample and inferred figures are compared with estimate.json. hours.json must still give the rates that were applied.
Any disagreement stops the script with an error and writes nothing: rerun estimate_hours.py first.

History: DIR/estimate-history.json keeps the last estimate per draft number (totals, work items, solutions, rates). Each run compares with
the nearest earlier draft and lists what moved in the section "Changes since the previous draft". A re-run of the same draft replaces its
entry. The file is data: delete it to start a new history.

REFERENCE (data/reference_estimate.json) is the benchmark the sample-basis rates were calibrated to (estimate-model.md, "How the sample was used").
"""
import argparse
import datetime
import os

from _common import OUT, SKILL_DIR, data, load_config, read_json, slug, utf8_stdout, write_json
from _mdhtml import write_pair
from estimate_hours import curve, half

SKILL_NAME = os.path.basename(SKILL_DIR)

REFERENCE = data("reference_estimate.json")  # the benchmark the sample-basis rates were calibrated to

SHORT = {
    "build_solution": "Build check",
    "artifact": "Artifact",
    "env_config": "Configuration",
    "pipeline_solution": "Pipeline",
    "pipeline_large": "Extra pipeline",
    "retarget_project": "Retarget",
    "retarget_regression": "Regression",
    "validation": "Test launch",
    "cutover_single": "Cutover (1 deployable)",
    "cutover_multi": "Cutover (several)",
}


def fmt(x):
    s = f"{x:,.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def rng(lo, hi):
    return fmt(lo) if abs(lo - hi) < 1e-9 else f"{fmt(lo)}-{fmt(hi)}"


def pc(x):
    """A share of the total, as a whole percentage."""
    return f"{x:.0f}"


def plu(n, unit, plural):
    return f"{n} {unit if n == 1 else plural}"


def signed(a, b):
    d = b - a
    if abs(d) < 1e-9:
        return "0"
    return ("+" if d > 0 else "") + fmt(d)


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in r) + " |")
    return "\n".join(lines)


def rate_lines(rates):
    """hours.json lines by id: (work item, line)."""
    out = {}
    for item, block in rates["items"].items():
        for ln in block["lines"]:
            out[ln["id"]] = (item, ln)
    return out


def self_check(est, rates):
    """Recomputes every figure from the lines and compares it with estimate.json. Returns (errors, number of lines)."""
    errs = []
    pct, day = est["contingency_pct"], est["day_hours"]
    known = rate_lines(rates)
    k = 1 + pct / 100
    raw_lo = raw_hi = samp_lo = samp_hi = 0.0
    per_item = {}
    n_lines = 0

    def same(name, got, want):
        if abs(got - want) > 1e-6:
            errs.append(f"{name}: estimate.json has {got}, the lines give {want}")

    for p in est["solutions"]:
        c = p["counts"]
        weight = c["config_files"] + c["secret_settings"] + c["env_vars"] + c["private_ips"] + 2 * c["rekey"]
        if weight != c["config_weight"]:
            errs.append(f"{p['id']}: weight {c['config_weight']} is not the sum of its inputs ({weight})")
        sol_lo = sol_hi = 0.0
        for x in p["lines"]:
            n_lines += 1
            where = f"{p['id']} / {x['id']}"
            if abs(x["count"] * x["rate"][0] - x["low"]) > 1e-6 or abs(x["count"] * x["rate"][1] - x["high"]) > 1e-6:
                errs.append(f"{where}: count x rate is not the stored hours")
            if x["work_item"] not in est["work_items"]:
                errs.append(f"{where}: work item {x['work_item']} is not selected")
            ref = known.get(x["id"])
            if ref is None:
                errs.append(f"{where}: line is not in hours.json")
            else:
                ln = ref[1]
                want = curve(ln["anchors"], c["config_weight"]) if ln["driver"] == "config_curve" else ln["rate"]
                if list(want) != list(x["rate"]):
                    errs.append(f"{where}: hours.json gives {want}, estimate.json used {x['rate']}")
                if ln["basis"] != x["basis"]:
                    errs.append(f"{where}: hours.json basis is {ln['basis']}, estimate.json has {x['basis']}")
            sol_lo += x["low"]
            sol_hi += x["high"]
            item = per_item.setdefault(x["work_item"], [0.0, 0.0])
            item[0] += x["low"]
            item[1] += x["high"]
            if x["basis"] == "sample":
                samp_lo += x["low"]
                samp_hi += x["high"]
        same(f"{p['id']} low", p["low"], sol_lo)
        same(f"{p['id']} high", p["high"], sol_hi)
        raw_lo += sol_lo
        raw_hi += sol_hi
    if n_lines == 0:
        errs.append("estimate.json has no lines")
    t_lo, t_hi = half(raw_lo * k), half(raw_hi * k)
    same("subtotal low", est["subtotal"]["low"], half(raw_lo))
    same("subtotal high", est["subtotal"]["high"], half(raw_hi))
    same("buffer low", est["contingency"]["low"], half(raw_lo * pct / 100))
    same("buffer high", est["contingency"]["high"], half(raw_hi * pct / 100))
    same("total low", est["total"]["low"], t_lo)
    same("total high", est["total"]["high"], t_hi)
    same("dev-days low", est["days_low"], half(t_lo / day))
    same("dev-days high", est["days_high"], half(t_hi / day))
    if set(per_item) != set(est["by_work_item"]):
        errs.append("the work items in the lines differ from by_work_item in estimate.json")
    for item, (lo, hi) in per_item.items():
        b = est["by_work_item"].get(item)
        if b:
            same(f"{item} low", b["low"], half(lo))
            same(f"{item} high", b["high"], half(hi))
    same("sample basis low", est["sample_basis"]["low"], half(samp_lo * k))
    same("sample basis high", est["sample_basis"]["high"], half(samp_hi * k))
    same("inferred share low", est["inferred_share"]["low"], half((raw_lo - samp_lo) * k))
    same("inferred share high", est["inferred_share"]["high"], half((raw_hi - samp_hi) * k))
    if abs(est["sample_basis"]["low"] + est["inferred_share"]["low"] - est["total"]["low"]) > 1.0 + 1e-6:
        errs.append("sample basis and inferred share do not add up to the total (low)")
    if abs(est["sample_basis"]["high"] + est["inferred_share"]["high"] - est["total"]["high"]) > 1.0 + 1e-6:
        errs.append("sample basis and inferred share do not add up to the total (high)")
    return errs, n_lines


def draft_entry(est, rates, today):
    """What this draft's numbers were, kept in the history file."""
    lines = {}
    for item, block in rates["items"].items():
        for ln in block["lines"]:
            lines[ln["id"]] = {"label": ln["label"], "work_item": item, "rate": ln.get("rate"), "anchors": ln.get("anchors"), "basis": ln.get("basis")}
    return {
        "date": today,
        "total": est["total"],
        "subtotal": est["subtotal"],
        "by_work_item": {k: {"label": v["label"], "low": v["low"], "high": v["high"]} for k, v in est["by_work_item"].items()},
        "solutions": {p["id"]: {"low": half(p["low"]), "high": half(p["high"]), "weight": p["counts"]["config_weight"],
                                "deployables": p["counts"]["deployables"], "workloads": p["counts"]["workloads"]} for p in est["solutions"]},
        "rates": lines,
    }


def rate_text(e):
    if e is None:
        return "not in the draft"
    if e.get("anchors"):
        return "weight curve: " + "; ".join(f"{fmt(w)}: {rng(*r)}" for w, r in e["anchors"]) + f" ({e.get('basis')})"
    return f"{rng(*e['rate'])} per unit ({e.get('basis')})"


def changes_section(prev, prev_rev, cur):
    """Lines for 'Changes since the previous draft', or None when there is no earlier draft."""
    if prev is None:
        return None
    pb, cb = prev.get("by_work_item", {}), cur["by_work_item"]
    tot = prev["total"], cur["total"]
    moved = tot[0] != tot[1]
    head = [f"Compared with Draft {prev_rev} ({prev.get('date', 'date not recorded')})."]
    rows_tot = [["Total with buffer (h)", rng(tot[0]["low"], tot[0]["high"]), rng(tot[1]["low"], tot[1]["high"]),
                 f"{signed(tot[0]['low'], tot[1]['low'])} / {signed(tot[0]['high'], tot[1]['high'])}"]]
    item_rows = []
    for k in dict.fromkeys(list(cb) + list(pb)):
        a = pb.get(k, {"low": 0, "high": 0})
        b = cb.get(k, {"low": 0, "high": 0})
        if a["low"] != b["low"] or a["high"] != b["high"]:
            label = (b.get("label") or a.get("label") or k)
            item_rows.append([label, rng(a["low"], a["high"]), rng(b["low"], b["high"]), f"{signed(a['low'], b['low'])} / {signed(a['high'], b['high'])}"])
    sol_rows = []
    ps, cs = prev.get("solutions", {}), cur["solutions"]
    for sid in dict.fromkeys(list(cs) + list(ps)):
        a, b = ps.get(sid), cs.get(sid)
        if a is None:
            sol_rows.append([sid, "-", rng(b["low"], b["high"]), "new", "new solution"])
            continue
        if b is None:
            sol_rows.append([sid, rng(a["low"], a["high"]), "-", "removed", "removed solution"])
            continue
        if all(a.get(f) == b.get(f) for f in ("low", "high", "weight", "deployables", "workloads")):
            continue
        why = [f"{name} {a.get(f)} -> {b.get(f)}" for f, name in (("weight", "config weight"), ("deployables", "deployables"), ("workloads", "workloads")) if a.get(f) != b.get(f)]
        sol_rows.append([sid, rng(a["low"], a["high"]), rng(b["low"], b["high"]), f"{signed(a['low'], b['low'])} / {signed(a['high'], b['high'])}",
                         "; ".join(why) or "rates changed"])
    rate_rows = []
    pr, cr = prev.get("rates", {}), cur["rates"]
    for lid in dict.fromkeys(list(cr) + list(pr)):
        a, b = pr.get(lid), cr.get(lid)
        if a == b:
            continue
        label = (b or a or {}).get("label", lid)
        rate_rows.append([label, rate_text(a), rate_text(b)])
    if not (moved or item_rows or sol_rows or rate_rows):
        return head + ["Nothing moved: the same total, work items, solutions and rates."]
    out = head + [""]
    out.append(table(["Measure", f"Draft {prev_rev}", "This draft", "Change (low / high)"], rows_tot))
    if item_rows:
        out += ["", "**Work items that moved**", "", table(["Work item", f"Draft {prev_rev} (h)", "This draft (h)", "Change (low / high)"], item_rows)]
    if sol_rows:
        out += ["", "**Solutions that moved**", "", table(["Solution", f"Draft {prev_rev} (h)", "This draft (h)", "Change (low / high)", "What moved"], sol_rows)]
    if rate_rows:
        out += ["", "**Rates that changed in hours.json**", "", table(["Task", f"Draft {prev_rev}", "This draft"], rate_rows)]
    return out


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Plain-English explanation of every hour in assessment/estimate.json, with a self-check. Run after estimate_hours.py and build_doc.py.")
    ap.add_argument("--out", default=os.path.join(OUT, "documents"),
                    help="folder for the .md, .html and estimate-history.json (default assessment/documents, relative to the workspace)")
    args = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    out = os.path.abspath(args.out)
    est = read_json(os.path.join(OUT, "estimate.json"))
    if not est:
        raise SystemExit("run estimate_hours.py first: assessment/estimate.json is missing")
    rates = data("hours.json")
    errs, n_lines = self_check(est, rates)
    if errs:
        raise SystemExit("self-check failed, nothing written. Rerun estimate_hours.py, then this script:\n  "
                         + "\n  ".join(errs[:40]) + ("\n  ..." if len(errs) > 40 else ""))

    # ---- facts used in the text (all from estimate.json, rates.json and the intake)
    pct, day = est["contingency_pct"], est["day_hours"]
    sols = est["solutions"]
    intake_opts = {o["value"]: o for q in data("intake.json")["questions"] if q["id"] == "work_items" for o in q["options"]}
    ia = cfg.get("intake") or {}
    meta = read_json(os.path.join(OUT, "documents", "meta.json"), {}) or {}
    rev = meta.get("revision")
    today = datetime.date.today().isoformat()
    client = cfg.get("client") or ""
    repo_of = {s["id"]: s.get("repo") for s in (read_json(os.path.join(OUT, "solutions", "index.json"), {}) or {}).get("solutions", [])}
    nrepo = len({repo_of.get(p["id"]) or p["id"].split("/")[0] for p in sols})
    nsol = len(sols)
    nproj = sum(p["counts"]["projects"] for p in sols)
    ndep = sum(p["counts"]["deployables"] for p in sols)
    tot, sub, cont = est["total"], est["subtotal"], est["contingency"]
    dd = (est["days_low"], est["days_high"])
    final = str(est.get("status", "")).startswith("FINAL")
    status = "FINAL" if final else "DRAFT"
    rev_txt = f"Draft {rev}" if rev is not None else "draft number not set (run build_doc.py)"
    items = est["work_items"]
    by_item = est["by_work_item"]

    def item_label(item):
        return (by_item.get(item) or {}).get("label") or (intake_opts.get(item) or {}).get("label") or item

    # line totals across solutions, in hours.json order
    pos = {}
    curve_ids = set()
    for block in rates["items"].values():
        for ln in block["lines"]:
            pos.setdefault(ln["id"], len(pos))
            if ln.get("driver") == "config_curve":
                curve_ids.add(ln["id"])
    agg = {}
    for p in sols:
        for x in p["lines"]:
            a = agg.get(x["id"])
            if a is None:
                a = agg[x["id"]] = {"id": x["id"], "item": x["work_item"], "label": x["label"], "unit": x["unit"], "plural": x["plural"],
                                    "count": 0, "low": 0.0, "high": 0.0, "rates": set(), "basis": x["basis"]}
            a["count"] += x["count"]
            a["low"] += x["low"]
            a["high"] += x["high"]
            a["rates"].add(tuple(x["rate"]))
    line_ids = sorted(agg, key=lambda i: pos.get(i, 999))
    ref_rates = {ln["id"]: ln for block in rates["items"].values() for ln in block["lines"]}
    inferred_lines = [agg[i]["label"] for i in line_ids if agg[i]["basis"] == "inferred"]
    raw_inf_share = (est["inferred_share"]["low"] / tot["low"], est["inferred_share"]["high"] / tot["high"])

    # ---- history and what moved
    hist_path = os.path.join(out, "estimate-history.json")
    history = read_json(hist_path, {"drafts": {}}) or {"drafts": {}}
    drafts = history.setdefault("drafts", {})
    cur_entry = draft_entry(est, rates, today)
    earlier = [int(k) for k in drafts if str(k).isdigit() and rev is not None and int(k) < rev]
    prev_key = max(earlier) if earlier else None
    changes = None
    if rev is None:
        changes = ["The draft number is not set (assessment/documents/meta.json is missing), so this draft is not in the history file. Run build_doc.py first."]
    else:
        changes = changes_section(drafts.get(str(prev_key)) if prev_key is not None else None, prev_key, cur_entry)
        if changes is None:
            changes = ["This is the first draft in the history file (estimate-history.json, next to this document). The next draft's run lists what moved."]

    # ---- the document
    md = []
    add = md.append
    add(f"# How the effort estimate was built{': ' + client if client else ''}")
    add("")
    add(f"**Status: {status}.** {rev_txt}, explained {today}. Nothing here is final until the user says so, and every rate can be changed.")
    add("")
    add(f"Numbers come from `assessment/estimate.json`. Rates live in `{SKILL_NAME}/scripts/data/hours.json`. Section 14 shows the checks this file passed.")
    add("")

    add("## 1. The short version")
    add("")
    add(f"- **What it is:** the developer hours to move the {nrepo} repositories ({nsol} solutions, {nproj} projects, {ndep} deployables) "
        f"to AWS as they are, with AI assistance: **{rng(tot['low'], tot['high'])} hours**, about {rng(*dd)} working days of {day} h, "
        f"including the {pct}% buffer.")
    add("- **What it covers:** the work items selected in the intake (section 3). Nothing else is priced.")
    add("- **How it is built:** each solution gets a short list of tasks. Each task has an hour range. Nothing is priced per setting, per key or per address.")
    add(f"- **Where the ranges come from:** lines marked sample are calibrated to a reference estimate (section 4). The rest are the skill's own "
        f"estimates, marked inferred: {pc(raw_inf_share[0] * 100)}-{pc(raw_inf_share[1] * 100)}% of the total (section 7).")
    add("- **What drives the number:** how many solutions and deployables there are, and how much configuration each solution holds (section 9).")
    add("- **What it is not:** a measured accuracy. It matches the one reference it was calibrated to. Independent accuracy needs actual hours from a finished project.")
    add("")

    add("## 2. The result")
    add("")
    add(f"**{rng(tot['low'], tot['high'])} developer hours ({rng(*dd)} dev-days of {day} h)**, AI-assisted, for {nsol} solutions, {nproj} projects "
        f"and {ndep} deployables, including a {pct}% buffer.")
    add("")
    rows = [[item_label(i), rng(by_item[i]["low"], by_item[i]["high"])] for i in items if i in by_item]
    rows += [["**Subtotal before buffer**", rng(sub["low"], sub["high"])], [f"Buffer ({pct}%)", rng(cont["low"], cont["high"])],
             ["**Total with buffer**", f"**{rng(tot['low'], tot['high'])}**"]]
    add(table(["Work item", "Hours (low-high)"], rows))
    add("")

    add("## 3. What is in and what is not")
    add("")
    add("**In the estimate** (selected in the intake):")
    add("")
    add(table(["Work item", "Hours before buffer"],
              [[item_label(i), rng(by_item[i]["low"], by_item[i]["high"])] for i in items if i in by_item]))
    add("")
    add("The tasks behind each work item, and their hour ranges, are in section 5.")
    add("")
    add("**Not in the estimate:**")
    add("")
    for value, opt in intake_opts.items():
        if value not in items:
            add(f"- {opt['label']}: not selected in the intake, so no hours.")
    if "cicd_secrets" in items:
        scope = ia.get("pipeline_scope")
        if scope == "none":
            add("- CI/CD pipelines: not priced. The intake says DevOps builds the pipelines (pipeline scope: none).")
        elif scope == "selected":
            add("- CI/CD pipelines: priced only for the solutions named in the intake.")
    add("- Projects outside any solution file: not estimated. The estimate counts solutions only.")
    add("- Always out of this estimate: C# code changes, modernisation (Linux, containers, native AWS services), database work, "
        "DevOps and server work, and testing by the client.")
    add("")
    if est.get("environments_assumed"):
        add(f"**Environments.** The intake does not say which environments move, so one environment per solution is assumed "
            f"({sum(p['counts']['workloads'] for p in sols)} workloads). Each extra environment adds the amount in section 10.")
    else:
        add(f"**Environments.** The environments are confirmed in the intake: {sum(p['counts']['workloads'] for p in sols)} workloads "
            f"(one per solution and environment).")
    add("")

    add("## 4. The reference the rates were calibrated to")
    add("")
    add(f"The rates marked sample were set so that a reference estimate comes out right. The reference covers {REFERENCE['solutions']} solutions "
        f"and {REFERENCE['deployables']} deployables, and gives {REFERENCE['total'][0]}-{REFERENCE['total'][1]} hours with the buffer. Its lines:")
    add("")
    add(table(["Reference line", "Hours (low-high)"], [[lbl, rng(*h)] for lbl, h in REFERENCE["lines"]]))
    add("")
    sb = est["sample_basis"]
    add(f"The lines marked sample in this estimate come to **{rng(sb['low'], sb['high'])} hours with the buffer**, against the reference's "
        f"{REFERENCE['total'][0]}-{REFERENCE['total'][1]}.")
    add("")
    add("The calibration is by construction: the sample rates were chosen to reproduce one reference. A re-run on that reference is a regression "
        "check, not proof of accuracy. Independent accuracy needs actual hours from another finished project.")
    add("")

    add("## 5. The model: tasks, not items")
    add("")
    add("Every line is a task for a solution or a deployable. Nothing is priced per setting, per key or per address. The hours of a task "
        "depend on how big the solution is, not on a rate per item.")
    add("")
    trows = []
    item_of = {ln["id"]: it for it, block in rates["items"].items() for ln in block["lines"]}
    for lid in line_ids:
        ln = ref_rates.get(lid)
        if ln is None:
            continue
        if ln.get("driver") == "config_curve":
            hrs = f"{rng(min(a[1][0] for a in ln['anchors']), max(a[1][1] for a in ln['anchors']))}, weight curve below"
        else:
            hrs = rng(*ln["rate"])
        trows.append([item_label(item_of[lid]), ln["label"], ln["unit"], hrs, ln["basis"]])
    add(table(["Work item", "Task", "Per", "Hours", "Basis"], trows))
    add("")
    cv = next((ln for block in rates["items"].values() for ln in block["lines"] if ln.get("driver") == "config_curve"), None)
    if cv:
        add("**Weight curve for the configuration task.** A solution's weight is its config files (publish profiles excluded), plus "
            "secret-like settings, environment variables, distinct private IP addresses, and 2 for each third-party key. "
            "The weight only sets the size of one task. Hours rise in straight lines between these points and stay flat outside them, "
            "rounded to the nearest 0.5 h:")
        add("")
        add(table(["Weight", "Hours (low-high)"], [[fmt(w), rng(*r)] for w, r in cv["anchors"]]))
        add("")

    add("## 6. Every estimate line")
    add("")
    add("Each line is summed over all solutions. Count is the number of units (solutions, deployables, test launches or workloads).")
    add("")
    arows = []
    for lid in line_ids:
        a = agg[lid]
        if lid in curve_ids:
            rate_t = "weight curve (section 5)"
            formula = f"{plu(a['count'], a['unit'], a['plural'])}, each read from the weight curve"
        else:
            r = next(iter(a["rates"]))
            rate_t = f"{rng(*r)} per {a['unit']}"
            formula = f"{a['count']} x {rng(*r)} h"
        arows.append([item_label(a["item"]), a["label"], a["count"], rate_t, formula, fmt(a["low"]), fmt(a["high"]), a["basis"]])
    arows += [["", "**Subtotal before buffer**", "", "", "", fmt(sub["low"]), fmt(sub["high"]), ""],
              ["", f"Buffer ({pct}%, once, on the subtotal)", "", "", "", fmt(cont["low"]), fmt(cont["high"]), ""],
              ["", "**Total with buffer**", "", "", "", f"**{fmt(tot['low'])}**", f"**{fmt(tot['high'])}**", ""],
              ["", f"Dev-days of {day} h", "", "", "", fmt(dd[0]), fmt(dd[1]), ""]]
    add(table(["Work item", "Task", "Count", "Rate per unit (h)", "Formula", "Low (h)", "High (h)", "Basis"], arows))
    add("")
    add("Subtotal, buffer and total are rounded up to the next 0.5 h, as in estimate.json. The line sums above are exact.")
    add("")

    add("## 7. Sample and inferred rates")
    add("")
    add(table(["Basis", "Meaning", "Hours with buffer (low-high)"], [
        ["sample", "calibrated to the reference in section 4", rng(sb["low"], sb["high"])],
        ["inferred", "the skill's own estimate, no sample behind it", rng(est["inferred_share"]["low"], est["inferred_share"]["high"])],
    ]))
    add("")
    add(f"The inferred part is {pc(raw_inf_share[0] * 100)}% of the total at the low end and {pc(raw_inf_share[1] * 100)}% at the high end.")
    add("")
    if inferred_lines:
        add("Inferred lines: " + "; ".join(inferred_lines) + ".")
        add("")
    add("Replace the inferred rates with real figures from the dev lead when they are available: change the rate and its `basis` in hours.json (section 11).")
    add("")

    add("## 8. The buffer")
    add("")
    add(f"A {pct}% buffer is added once, on the subtotal: {rng(cont['low'], cont['high'])} hours. It covers dependencies that nobody "
        "documented and that only show up at test launch. It is not split across solutions.")
    add("")

    add("## 9. Per solution")
    add("")
    add("### Inputs that drive the configuration task")
    add("")
    add("Weight = config files + secret-like settings + environment variables + distinct private IP addresses + 2 for each third-party key. "
        "The weight is read on the curve in section 5. Counts are from the scans and the solution files.")
    add("")
    irows = []
    for p in sols:
        c = p["counts"]
        irows.append([p["id"], c["projects"], c["deployables"], c["workloads"], c["config_files"], c["secret_settings"], c["env_vars"],
                      c["private_ips"], c["rekey"], c["config_weight"]])
    tsum = [sum(p["counts"][f] for p in sols) for f in ("projects", "deployables", "workloads", "config_files", "secret_settings", "env_vars", "private_ips", "rekey")]
    irows.append(["**Total**", f"**{tsum[0]}**", f"**{tsum[1]}**", f"**{tsum[2]}**", f"**{tsum[3]}**", f"**{tsum[4]}**", f"**{tsum[5]}**",
                  f"**{tsum[6]}**", f"**{tsum[7]}**", "-"])
    add(table(["Solution", "Projects", "Deployables", "Workloads", "Config files", "Secret-like settings", "Environment variables",
               "Private IPs", "Third-party keys", "Weight"], irows))
    add("")
    add("### Hours per solution (before buffer)")
    add("")
    used = [i for i in line_ids]
    hrows = []
    for p in sols:
        by_id = {x["id"]: x for x in p["lines"]}
        cells = [f"{fmt(by_id[i]['low'])}-{fmt(by_id[i]['high'])}" if i in by_id else "-" for i in used]
        hrows.append([p["id"]] + cells + [rng(half(p["low"]), half(p["high"]))])
    hrows.append(["**Total**"] + [f"**{rng(agg[i]['low'], agg[i]['high'])}**" for i in used] + [f"**{rng(sub['low'], sub['high'])}**"])
    add(table(["Solution"] + [SHORT.get(i, i) for i in used] + ["Solution total"], hrows))
    add("")
    add("The buffer is not in these figures. It is added once to the total (section 8).")
    add("")
    add("### Worked examples")
    add("")
    big = max(sols, key=lambda p: p["high"])
    small = min(sols, key=lambda p: p["high"])
    examples = [("Largest solution", big)] if small is big else [("Largest solution", big), ("Smallest solution", small)]
    for label, p in examples:
        c = p["counts"]
        add(f"**{label}: {p['id']}**")
        add("")
        wrows = [["Weight", f"{c['config_files']} config files + {c['secret_settings']} secret-like settings + {c['env_vars']} environment variables "
                             f"+ {c['private_ips']} private IPs + 2 x {c['rekey']} third-party keys", f"= {c['config_weight']}", ""]]
        for x in p["lines"]:
            wrows.append([x["label"], plu(x["count"], x["unit"], x["plural"]), fmt(x["low"]) + "-" + fmt(x["high"]), x["basis"]])
        wrows.append(["**Total before buffer**", "", f"**{rng(half(p['low']), half(p['high']))}**", ""])
        add(table(["Step", "Count", "Hours (low-high)", "Basis"], wrows))
        add("")
    add("")

    add("## 10. What one more environment adds")
    add("")
    tv = [x for p in sols for x in p["lines"] if x["work_item"] == "validation_cutover"]
    vc = {}
    for x in tv:
        vc.setdefault(x["id"], [x["label"], 0, 0.0, 0.0])
        vc[x["id"]][1] += x["count"]
        vc[x["id"]][2] += x["low"]
        vc[x["id"]][3] += x["high"]
    vc_low = sum(v[2] for v in vc.values())
    vc_high = sum(v[3] for v in vc.values())
    extra = (round(vc_low * (1 + pct / 100)), round(vc_high * (1 + pct / 100)))  # rounded as build_doc.py section 10 does
    extra_dd = (half(extra[0] / day), half(extra[1] / day))
    add("Each extra environment with the same deployables adds the test-launch and cutover lines again:")
    add("")
    for lid, (lbl, cnt, lo, hi) in vc.items():
        add(f"- {lbl}: {cnt} units across all solutions, {rng(lo, hi)} h before buffer.")
    add("")
    add(f"That is {rng(vc_low, vc_high)} hours before the buffer and **{rng(*extra)} hours with it** ({rng(*extra_dd)} dev-days).")
    add("")
    add("Not counted for an extra environment: its own configuration values and secrets, which are not priced per environment. "
        "Add them by hand if the dev team has to set them up.")
    add("")

    add("## 11. How to change a rate")
    add("")
    add(f"1. Open `{SKILL_NAME}/scripts/data/hours.json`. Each line has `rate` (low and high hours per unit), `basis` and `label`. "
        "The configuration task has `anchors` instead: weight and hours pairs.")
    add("2. Change the numbers only. Keep `basis` at sample only for a rate the reference in section 4 calibrates. Otherwise use inferred.")
    add("3. Rerun from the workspace, in this order: "
        f"`py {SKILL_NAME}/scripts/estimate_hours.py`, then `py {SKILL_NAME}/scripts/build_doc.py`, then "
        f"`py {SKILL_NAME}/scripts/verify_doc.py`, then `py {SKILL_NAME}/scripts/build_estimate_explainer.py`.")
    add("4. Counts change the same way: rerun the scan and solution steps listed by `context.py`, then `estimate_hours.py` and the rest.")
    add("5. This file refuses to write if hours.json no longer matches the rates in estimate.json. That means step 3 was skipped.")
    add("")

    add("## 12. Changes since the previous draft")
    add("")
    for line in changes:
        add(line)
        add("")
    add("## 13. Questions you may be asked")
    add("")
    add("**Why a range and not one number?** Every task has a low and a high because the work depends on what turns up in each solution. "
        "The lows and highs are summed separately, so the total is wide on purpose. It is planning-grade, not a quote.")
    add("")
    add("**How accurate is it?** Not proven. The model matches the reference it was calibrated to (section 4). Accuracy needs actual hours "
        "from a finished project.")
    add("")
    add(f"**Which part is least certain?** The inferred lines, {pc(raw_inf_share[0] * 100)}-{pc(raw_inf_share[1] * 100)}% of the total (section 7).")
    add("")
    add("**What would move it most?** The number of solutions and deployables, the number of environments (section 10), and real hours for the inferred tasks.")
    add("")
    add("**Why is a work item missing?** Only the work items selected in the intake are priced (section 3).")
    add("")

    add("## 14. Self-check")
    add("")
    add(f"Passed. {n_lines} estimate lines were recomputed (count x rate = hours) and {nsol} solutions were checked (weight = sum of inputs, "
        "line sums). The subtotal, buffer, total, dev-days, work item totals, and the sample and inferred split all agree with estimate.json. "
        "hours.json gives the same rates that were applied. If any check fails, this file is not written.")
    add("")
    add(f"*Generated by build_estimate_explainer.py on {today} from assessment/estimate.json.*")
    add("")

    md_text = "\n".join(md)
    md_path = os.path.join(out, f"{slug(client)}-effort-estimate-explained.md")
    html_path = write_pair(md_path, md_text, title=None, brand=bool((cfg.get("docx_template") or "").strip()))

    # ---- history: this draft replaces its own entry, earlier drafts are kept
    if rev is not None:
        drafts[str(rev)] = cur_entry
        history["_doc"] = ("Last estimate per draft number, kept by build_estimate_explainer.py (totals, work items, solutions and rates). "
                           "Used for 'Changes since the previous draft'. Safe to delete; the next run starts a new history.")
        write_json(hist_path, history)

    print(f"wrote {md_path} and {html_path}")
    print(f"TOTAL {rng(tot['low'], tot['high'])} dev hours incl. {pct}% buffer ({rng(*dd)} dev days) · {rev_txt} · {status}")
    print(f"self-check passed: {n_lines} lines, {nsol} solutions, totals and rates agree with estimate.json")
    print(f"history: {len(drafts)} draft(s) in {hist_path}" if rev is not None else "history: not updated (no draft number)")


if __name__ == "__main__":
    main()
