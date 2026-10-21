"""Report text of the hours calculator (lift-and-shift track), shared by build_report.py and landing_report.py (standard library only).

Every function takes the `hours` block of assessment/estimate.json (the output of estimate_hours.py, merged by estimate_effort.py) and
returns Markdown. Numbers are copied from that block; nothing is recomputed here except sums of lines already in it.
"""
import math

BASIS_LABEL = {"sample": "calibrated to the sample", "inferred": "inferred by the skill"}


def half(x):
    return math.ceil(x * 2 - 1e-9) / 2


def g(x):
    return f"{x:g}"


def rng(lo, hi, unit=" h"):
    return f"{g(lo)}–{g(hi)}{unit}"


def esc(s):
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def table(cols, rows):
    if not rows:
        return "_None._"
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    out += ["| " + " | ".join(esc(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def is_hours(est):
    return (est or {}).get("basis") == "hours" and bool((est or {}).get("hours"))


def total_text(h):
    t = h["total"]
    return f"{rng(t['low'], t['high'])} incl. {g(h['contingency_pct'])}% buffer ({rng(h['days_low'], h['days_high'], ' dev days')} of {g(h['day_hours'])} h)"


def basis_text(h):
    s, i = h["sample_basis"], h["inferred_share"]
    return f"{rng(s['low'], s['high'])} calibrated to the sample estimate; {rng(i['low'], i['high'])} inferred by the skill (no sample behind it yet)"


def headline_rows(h):
    rows = [("Effort (developer hours, AI-assisted)", total_text(h)),
            ("Of which", basis_text(h))]
    if h.get("environments_assumed"):
        rows.append(("Environments", "UNKNOWN: one environment per solution is assumed until the client confirms the list"))
    return rows


def by_item(h):
    """work item -> {label, low, high, sample_low, sample_high, inferred_low, inferred_high} before the buffer, summed from the per-solution lines
    and rounded up to half an hour at the end (so a sample part and an inferred part never add to more than the item)."""
    raw = {k: {"label": v["label"], "low": 0.0, "high": 0.0, "sample_low": 0.0, "sample_high": 0.0} for k, v in h["by_work_item"].items()}
    for p in h["solutions"]:
        for x in p["lines"]:
            if x["work_item"] in raw:
                r = raw[x["work_item"]]
                r["low"] += x["low"]
                r["high"] += x["high"]
                if x["basis"] == "sample":
                    r["sample_low"] += x["low"]
                    r["sample_high"] += x["high"]
    out = {}
    for k, r in raw.items():
        out[k] = {"label": r["label"], "low": half(round(r["low"], 6)), "high": half(round(r["high"], 6)),
                  "sample_low": half(round(r["sample_low"], 6)), "sample_high": half(round(r["sample_high"], 6)),
                  "inferred_low": half(round(r["low"] - r["sample_low"], 6)), "inferred_high": half(round(r["high"] - r["sample_high"], 6))}
    return out


def estimate_md(h):
    pct = h["contingency_pct"]
    items = by_item(h)
    parts = [f"**Total: {total_text(h)}.** {basis_text(h).capitalize()}. Status: {h['status']}.\n"]
    rows = [(v["label"], rng(v["low"], v["high"]), rng(v["sample_low"], v["sample_high"]), rng(v["inferred_low"], v["inferred_high"])) for v in items.values()]
    rows.append(("**Subtotal (before the buffer)**", f"**{rng(h['subtotal']['low'], h['subtotal']['high'])}**", "", ""))
    rows.append((f"{g(pct)}% buffer", rng(h["contingency"]["low"], h["contingency"]["high"]), "", ""))
    rows.append(("**Total**", f"**{rng(h['total']['low'], h['total']['high'])}**", f"**{rng(h['sample_basis']['low'], h['sample_basis']['high'])}** (with buffer)",
                 f"**{rng(h['inferred_share']['low'], h['inferred_share']['high'])}** (with buffer)"))
    parts += ["**By work item** (hours before the buffer; the last two columns split each item by evidence):\n",
              table(["Work item", "Hours (low–high)", "Calibrated to the sample", "Inferred"], rows), ""]
    srows = []
    for p in h["solutions"]:
        c = p["counts"]
        srows.append((p["id"], c["projects"], c["solution_deployables"], c["workloads"] if not p["environments_assumed"] else f"{c['workloads']} (environments UNKNOWN)",
                      rng(half(p["low"]), half(p["high"])), rng(half(p["low"] * (1 + pct / 100)), half(p["high"] * (1 + pct / 100)))))
    parts += ["**By solution** (each solution is estimated on its own; a project shared by two solutions is counted once):\n",
              table(["Solution", "Projects", "Deployables", "Workloads", "Hours before buffer", f"Hours incl. {g(pct)}% buffer"], srows),
              "\nRows are rounded up to half an hour, so they can differ from the total by a few tenths of an hour.\n"]
    drows = []
    for p in h["solutions"]:
        for x in p["lines"]:
            drows.append((p["id"], items[x["work_item"]]["label"], x["label"], f"{g(x['count'])} {x['unit']}", rng(x["rate"][0], x["rate"][1], " h each"),
                          rng(x["low"], x["high"]), BASIS_LABEL.get(x["basis"], x["basis"])))
    parts += ["**Every line** (count found in the code × rate of `scripts/data/hours.json`):\n",
              table(["Solution", "Work item", "Line", "Counted", "Rate", "Hours", "Evidence"], drows)]
    return "\n".join(parts)


def method_md(h):
    pct = h["contingency_pct"]
    return "\n".join([
        "The estimate is a **developer-hours calculator**, not a model of lines of code. It counts things the scan found in each solution and multiplies each count by a "
        "[low, high] hours rate (`scripts/data/hours.json`):",
        "",
        "```text\nsolution hours = Σ over the selected work items and their lines of  count × rate [low, high]\n"
        f"total = Σ solutions × (1 + {g(pct)}% buffer);   days = total ÷ {g(h['day_hours'])} h\n```",
        "",
        "- **Hours are developer working hours, AI-assisted** (the dev team uses coding agents and assistants; the rates already include that).",
        "- **Counts** come from the code (`solutions.py`, `third_party.py`): environment variables read, config files with hard-coded values, internal addresses, "
        "licensed components and integrations that need a new key, projects, deployables, projects whose framework changes, and workloads (solution × environment).",
        "- **Evidence of each rate.** *Calibrated to the sample*: the rate was set so the sample estimate of the reference (the manager's estimate, 72–108 h) is reproduced. "
        "*Inferred*: the skill's own figure where the sample has no line (pipeline, build check, retarget); it is shown separately so the reader can see how much of the total rests on judgment.",
        "- **Work items** are chosen in the intake; only the selected ones are estimated. Server build, network, domain, VM or database migration, the client's QA, project management "
        "and any modernization are not in these hours.",
        "- **Unknowns stay unknown.** An environment list the client has not given counts one environment per deployable and is flagged UNKNOWN; "
        "an intake answer of 'unknown' is carried into the open questions, never replaced by a guess.",
        "- **Draft.** Nothing is final until the user says so; every rate can be revised in `scripts/data/hours.json` and the estimate rerun.",
    ])


def future_md(h):
    """Short statement for the sections that have no calendar plan under this model."""
    return (f"The hours calculator gives effort, not a calendar: {rng(h['days_low'], h['days_high'], ' developer days')} of {g(h['day_hours'])} h in total. "
            "The calendar follows the number of developers and the deployment waves agreed with DevOps and the client, which are not part of the estimate.")
