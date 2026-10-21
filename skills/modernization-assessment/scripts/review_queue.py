"""List what the reviewer must look at, with evidence and graph blast radius (keeps review reading targeted).

    python <skill>/scripts/review_queue.py --repo NAME [--all-likely] [--limit 60]
    python <skill>/scripts/review_queue.py --decisions          # draft 7R decisions to confirm/override (JSON on stdout)

Queue = Blocker/High findings that are not Confirmed and have no verdict, then (with --all-likely) Medium Likely/Needs
verification ones. For each: finding id, rule, title, evidence file:line and how many other files depend on that file
(graphify analysis). Copy ids into assessment/reviews/<repo>.json with a verdict (references/review-findings.md).
"""
import argparse
import json
import os

from _common import OUT, load_config, read_json, utf8_stdout
import _findings as F


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--all-likely", action="store_true")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--decisions", action="store_true")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    if a.decisions:
        cls = read_json(os.path.join(OUT, "classification.json"))
        dec = read_json(os.path.join(OUT, "decisions.json"), {}) or {}
        draft = {x["id"]: {"name": x["name"], "r7": x["r7"], "target": x["target"], "rationale": x["rationale"], "options": x.get("options", []),
                           "by": "", "date": ""} for x in cls["applications"] if x["id"] not in dec}
        print(json.dumps(draft, indent=1))
        return
    repos = [a.repo] if a.repo else F.repos(root)
    for repo in repos:
        inv = F.load_inventory(root, repo)
        fs = F.assign_apps(F.load(root, repo), inv)
        impact = (read_json(os.path.join(OUT, "graphs", repo, "analysis.json"), {}) or {}).get("file_impact", {})
        q = [f for f in fs if not f.get("review") and ((f["severity"] in ("Blocker", "High") and f["confidence"] != "Confirmed") or
                                                       (a.all_likely and f["severity"] == "Medium" and f["confidence"] != "Confirmed"))]
        q.sort(key=F.sort_key)
        print(f"# {repo}: {len(q)} to review" + (f" (showing {a.limit})" if len(q) > a.limit else ""))
        for f in q[:a.limit]:
            ev = f.get("evidence", [])[:3]
            br = max((impact.get(e.get("file"), 0) for e in ev), default=0)
            print(f"{f['id']}\n   {f['severity']}/{f['confidence']} {f['title']} · {f.get('occurrences')}x · blast radius {br} file(s)")
            for e in ev:
                print(f"   {F.evidence_ref(e)}  {F.short(e.get('text'), 110)}")


if __name__ == "__main__":
    main()
