"""Estimate the repositories we could not assess, from the ones we did (sample-based estate estimate).

    python <skill>/scripts/extrapolate_estate.py [--list PATH] [--total N]

Run after estimate_effort.py when only part of the estate's code is available (intake answer code_access = sample).
Inputs:
  assessment/estimate.json            hours per work package of the assessed repositories (the sample)
  assessment/inventory/<repo>.json    size and application types of the assessed repositories
  the estate list (intake estate_list or --list): CSV, JSON (list of objects) or .xlsx; one row per repository.
      Recognised columns (any case): name / repo / repository / project; group / namespace; type / project type /
      .NET project types; framework / .NET version / .NET frameworks; lines / loc / total lines / kloc.
  the estate size (intake estate_total or --total): repositories beyond the list are counted with no facts at all.
Method (deterministic, no guessing beyond what the numbers say):
  1. Every assessed repository gets an archetype from its deployable application types (web on .NET Framework, web on
     modern .NET, service / worker, console / batch, desktop, library only) and its P10 / P50 / P90 hours.
  2. A repository from the list that was not assessed gets the archetype read from its type / framework text.
     With a size, hours = size x the hours-per-KLOC range of assessed repositories of that archetype; without a size,
     the hours range of those repositories. With no assessed repository of that archetype (or no type known), the range of
     the whole sample, widened (low x 0.5, high x 2), marked Low confidence.
  3. Repositories counted in the estate size but missing from the list get the widened whole-sample range.
Writes assessment/extrapolation.json and assessment/report/estate-extrapolation.csv; build_report.py shows them.
"""
import argparse
import csv
import json
import os
import re
import statistics
import zipfile
import xml.etree.ElementTree as ET

from _common import OUT, load_config, read_json, slug, utf8_stdout, write_json
import _findings as F

ARCH = [("web-netfx", "Web app on .NET Framework (Web Forms / MVC / Web API / WCF)"), ("web-modern", "Web app on modern .NET (ASP.NET Core)"),
        ("service", "Windows service / worker"), ("console", "Console / batch job"), ("desktop", "Desktop client (WinForms / WPF)"),
        ("library", "Library only (no deployable application)"), ("unknown", "Type not known")]
ARCH_LABEL = dict(ARCH)
TYPE_ARCH = {"aspnet-webforms": "web-netfx", "aspnet-mvc": "web-netfx", "aspnet-webapi": "web-netfx", "wcf-service": "web-netfx", "website": "web-netfx",
             "aspnet-core": "web-modern", "windows-service": "service", "netcore-worker": "service", "console": "console",
             "netcore-console": "console", "wpf": "desktop", "winforms": "desktop"}
WIDEN = (0.5, 2.0)


def arch_of_text(text, framework=""):
    t = f"{text} {framework}".lower()
    if not t.strip():
        return "unknown"
    if re.search(r"web\s*forms|webforms|\.aspx|wcf|asmx", t):
        return "web-netfx"
    if re.search(r"asp\.?net core|aspnetcore|blazor|razor pages|minimal api", t) or (re.search(r"\b(web|api|mvc)\b", t) and re.search(r"net\s?(core|[5-9]|1\d)\b|net[5-9]\.0|net1\d\.0", t)):
        return "web-modern"
    if re.search(r"\b(mvc|web\s*api|webapi|asp\.?net|web app|website|iis)\b", t):
        return "web-netfx"
    if re.search(r"service|worker|daemon", t):
        return "service"
    if re.search(r"console|batch|job|scheduler|exe\b|cli\b", t):
        return "console"
    if re.search(r"wpf|winforms|windows forms|desktop", t):
        return "desktop"
    if re.search(r"library|class lib|nuget|package", t):
        return "library"
    return "unknown"


def read_rows(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        d = json.load(open(path, encoding="utf-8"))
        return d if isinstance(d, list) else d.get("repositories") or d.get("projects") or []
    if ext == ".csv":
        return list(csv.DictReader(open(path, encoding="utf-8-sig")))
    if ext == ".xlsx":
        return xlsx_rows(path)
    raise SystemExit(f"estate list must be .csv, .json or .xlsx: {path}")


def xlsx_rows(path):
    """First sheet that has a repository-name column, as a list of dicts (standard library only)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    z = zipfile.ZipFile(path)
    shared = [("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"]))) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns)] \
        if "xl/sharedStrings.xml" in z.namelist() else []
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", ns):
        target = rels[sh.get("{%s}id" % ns["r"])].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        grid = []
        for row in ET.fromstring(z.read(target)).iter("{%s}row" % ns["m"]):
            vals = {}
            for c in row.findall("m:c", ns):
                v = c.find("m:v", ns)
                if c.get("t") == "s" and v is not None:
                    val = shared[int(v.text)]
                elif c.get("t") == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
                else:
                    val = v.text if v is not None else ""
                vals[re.sub(r"\d", "", c.get("r"))] = val
            grid.append(vals)
        for i, hdr in enumerate(grid[:5]):
            if any(col(h) == "name" for h in hdr.values()):
                keys = {k: h for k, h in hdr.items() if h}
                return [{keys[k]: v for k, v in r.items() if k in keys} for r in grid[i + 1:] if any(r.values())]
    return []


def col(h):
    h = str(h or "").strip().lower()
    for key, pats in (("name", r"^(name|repo|repository|project|project name|repository name)$"), ("group", r"^(group|namespace|group / namespace)$"),
                      ("type", r"^(type|project type|project types|\.net project types|application type|app type)$"),
                      ("framework", r"^(framework|\.net version|\.net frameworks|target framework|runtime)$"),
                      ("kloc", r"^kloc$"), ("lines", r"^(lines|loc|total lines|lines of code)$")):
        if re.match(pats, h):
            return key
    return None


def normal(row):
    out = {}
    for k, v in row.items():
        c = col(k)
        if c and v not in (None, "") and c not in out:
            out[c] = v
    kloc = None
    try:
        kloc = float(out["kloc"]) if "kloc" in out else (float(str(out["lines"]).replace(",", "")) / 1000.0 if "lines" in out else None)
    except ValueError:
        kloc = None
    return {"name": str(out.get("name", "")).strip(), "group": str(out.get("group", "")).strip(), "type": str(out.get("type", "")),
            "framework": str(out.get("framework", "")), "kloc": kloc}


def sample(root, est):
    """Assessed repositories: archetype, KLOC, P10/P50/P90 hours (applications + selected database work)."""
    per = {}
    for w in est.get("work_packages", []):
        r = per.setdefault(w["repo"], [0.0, 0.0, 0.0])
        lo, hi = w.get("total_hours") or [0, 0]
        r[0] += lo
        r[1] += w.get("likely_hours", 0)
        r[2] += hi
    for d in est.get("databases", []):
        if d.get("selected") and d["selected"] != "none" and d["options"].get(d["selected"]):
            o = d["options"][d["selected"]]
            r = per.setdefault(d["repo"], [0.0, 0.0, 0.0])
            r[0] += o["hours"][0]
            r[1] += o.get("likely_hours", 0)
            r[2] += o["hours"][1]
    out = []
    for repo in F.repos(root):
        inv = F.load_inventory(root, repo)
        if not inv or repo not in per:
            continue
        types = [a["type"] for a in inv.get("applications", [])]
        arch = max((TYPE_ARCH.get(t, "unknown") for t in types), key=lambda a: sum(1 for t in types if TYPE_ARCH.get(t) == a), default="library") if types else "library"
        kloc = max(sum((p.get("loc_handwritten") or p.get("loc_code") or 0) for p in inv["projects"] if p.get("type") not in ("test",)) / 1000.0, 0.1)
        out.append({"repo": repo, "archetype": arch, "kloc": round(kloc, 1), "hours": [round(x) for x in per[repo]]})
    return out


def rng(vals):
    return [min(vals), statistics.median(vals), max(vals)]


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", help="estate list (.csv / .json / .xlsx); default: intake estate_list")
    ap.add_argument("--total", type=int, help="repositories in the whole estate; default: intake estate_total")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    est = read_json(os.path.join(OUT, "estimate.json"))
    if not est:
        raise SystemExit("run estimate_effort.py first")
    intake = cfg.get("intake") or {}
    lst = a.list or intake.get("estate_list")
    if str(lst or "").strip().lower() in ("", "unknown", "none"):  # the intake records "unknown" when the client has no list
        lst = None
    if lst and not os.path.isabs(lst):
        lst = os.path.join(root, lst)
    total = a.total or (intake.get("estate_total") if isinstance(intake.get("estate_total"), int) else None)
    smp = sample(root, est)
    if not smp:
        raise SystemExit("no assessed repository with an estimate: nothing to extrapolate from")
    assessed = {s["repo"] for s in smp}
    rows = [normal(r) for r in read_rows(lst)] if lst and os.path.exists(lst) else []
    rows = [r for r in rows if r["name"] and len(r["name"].split()) < 5]  # drop notes and footers ("Source: ... excluded.") in the name column
    if lst and not os.path.exists(lst):
        print(f"WARN estate list not found: {lst}")
    by_arch = {}
    for s in smp:
        by_arch.setdefault(s["archetype"], []).append(s)
    all_h = [[s["hours"][i] for s in smp] for i in range(3)]
    base_all = [min(all_h[0]) * WIDEN[0], statistics.median(all_h[1]), max(all_h[2]) * WIDEN[1]]
    items = []
    seen = set()
    for r in rows:
        if not r["name"]:
            continue
        key = slug(r["name"].rstrip("/").split("/")[-1].removesuffix(".git"))  # "group/repo" or a clone URL -> the repo folder name
        if key in assessed or key in seen:
            continue
        seen.add(key)
        arch = arch_of_text(r["type"], r["framework"])
        peers = by_arch.get(arch, [])
        if peers and r["kloc"]:
            per_k = [[s["hours"][i] / s["kloc"] for s in peers] for i in range(3)]
            h = [min(per_k[0]) * r["kloc"], statistics.median(per_k[1]) * r["kloc"], max(per_k[2]) * r["kloc"]]
            basis, conf = f"{r['kloc']:.1f} KLOC x hours/KLOC of {len(peers)} assessed {ARCH_LABEL[arch].lower()} repo(s)", "Medium" if len(peers) > 1 else "Low"
        elif peers:
            h = [min(s["hours"][0] for s in peers), statistics.median(s["hours"][1] for s in peers), max(s["hours"][2] for s in peers)]
            basis, conf = f"hours range of {len(peers)} assessed {ARCH_LABEL[arch].lower()} repo(s); size unknown", "Low"
        else:
            h = list(base_all)
            basis, conf = f"whole-sample range widened x{WIDEN[0]}–x{WIDEN[1]}: no assessed repo of this kind ({ARCH_LABEL[arch].lower()})", "Low"
        items.append({"repo": r["name"], "group": r["group"], "archetype": arch, "archetype_label": ARCH_LABEL[arch], "type": r["type"],
                      "framework": r["framework"], "kloc": r["kloc"], "hours": [round(x) for x in h], "basis": basis, "confidence": conf})
    unlisted = max(0, (total or 0) - len(assessed) - len(items))
    if unlisted:
        items.append({"repo": f"{unlisted} repositories not in the list", "group": "", "archetype": "unknown", "archetype_label": ARCH_LABEL["unknown"],
                      "type": "", "framework": "", "kloc": None, "count": unlisted, "hours": [round(x * unlisted) for x in base_all],
                      "basis": f"estate size {total} minus assessed and listed; whole-sample range widened, per repository", "confidence": "Low"})
    ex = [sum(i["hours"][k] for i in items) for k in range(3)]
    sm = [sum(s["hours"][k] for s in smp) for k in range(3)]
    res = {"scenario": est.get("scenario", {}), "sample": smp, "extrapolated": items, "estate_total": total,
           "list": os.path.relpath(lst, root) if lst and os.path.exists(lst) else None,
           "totals": {"assessed_hours": [round(x) for x in sm], "extrapolated_hours": [round(x) for x in ex],
                      "estate_hours": [round(sm[k] + ex[k]) for k in range(3)], "assessed_repos": len(smp),
                      "extrapolated_repos": len([i for i in items if "count" not in i]) + unlisted},
           "method": "Sample-based: per-archetype hours (or hours per KLOC) of the assessed repositories applied to the rest; "
                     "low = sum of lows, likely = sum of medians, high = sum of highs (extremes, not a forecast)."}
    write_json(os.path.join(OUT, "extrapolation.json"), res)
    os.makedirs(os.path.join(OUT, "report"), exist_ok=True)
    with open(os.path.join(OUT, "report", "estate-extrapolation.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["repository", "group", "assessed", "archetype", "type (as listed)", "framework (as listed)", "kloc", "hours_low", "hours_likely", "hours_high", "basis", "confidence"])
        for s in smp:
            w.writerow([s["repo"], "", "yes", ARCH_LABEL[s["archetype"]], "", "", s["kloc"], *s["hours"], "assessed (estimate_effort.py)", "per estimate"])
        for i in items:
            w.writerow([i["repo"], i["group"], "no", i["archetype_label"], i["type"], i["framework"], i["kloc"] or "", *i["hours"], i["basis"], i["confidence"]])
    t = res["totals"]
    print(f"sample: {t['assessed_repos']} repos, {t['assessed_hours'][1]} h likely · extrapolated: {t['extrapolated_repos']} repos, "
          f"{t['extrapolated_hours'][0]}-{t['extrapolated_hours'][2]} h (likely {t['extrapolated_hours'][1]}) · estate likely {t['estate_hours'][1]} h")


if __name__ == "__main__":
    main()
