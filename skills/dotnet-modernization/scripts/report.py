"""Run log and execution report for one work package (run, do not read).

    python scripts/report.py log --dir <folder>/.modernization --step port --engine devtx --status done \
                                 [--note "Kiro run 3, build green"] [--branch modernize/orderservice] [--commit abc123]
    python scripts/report.py build --dir <folder>/.modernization [--plan assessment/execution-plan.json] [--package NAME]

log appends one line to <dir>/run-log.jsonl (UTC time, step, engine, status, note, branch, commit). Steps follow the
workflow: intake, baseline, port, db, cleanup:<playbook>, aws-native:<service>, verify, review, handover.
Engines: aws-transform, devtx, claude, db-agent, human.
build writes <dir>/execution-report.md and its .html twin from what is in <dir>: run-log.jsonl, baseline.json,
verify.json, residue.json, parity.json, waivers (in residue.json), and, with --plan, the package's planned items from the
modernization-assessment execution plan, each marked done / open by whether its playbook still has residue hits.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mdhtml import write_pair  # noqa: E402


def rd(d, name):
    p = os.path.join(d, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def log(a):
    os.makedirs(a.dir, exist_ok=True)
    e = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "step": a.step, "engine": a.engine, "status": a.status,
         "note": a.note or "", "branch": a.branch or "", "commit": a.commit or ""}
    with open(os.path.join(a.dir, "run-log.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(e) + "\n")
    print(f"logged {e['step']} {e['status']} ({e['engine']})")


def build(a):
    d = a.dir
    runs = []
    if os.path.exists(os.path.join(d, "run-log.jsonl")):
        runs = [json.loads(x) for x in open(os.path.join(d, "run-log.jsonl"), encoding="utf-8") if x.strip()]
    base, ver, res, par = rd(d, "baseline.json"), rd(d, "verify.json"), rd(d, "residue.json"), rd(d, "parity.json")
    pkg = None
    if a.plan:
        plan = json.load(open(a.plan, encoding="utf-8"))
        cands = [p for p in plan.get("packages", []) if not a.package or p["name"] == a.package]
        pkg = cands[0] if cands else None
    title = (pkg or {}).get("name") or os.path.basename(os.path.dirname(os.path.abspath(d)))
    L = [f"# Execution report: {title}", ""]
    if ver:
        ran = [s for s in ver["steps"] if s.get("passed") is not None]
        ok = all(s["passed"] for s in ran)
        L += [f"**Gates: {'PASS' if ok else 'FAIL'}** ({sum(1 for s in ran if s['passed'])} of {len(ran)} that ran; "
              f"not run: {', '.join(s['gate'] for s in ver['steps'] if s.get('passed') is None) or 'none'}).", ""]
    else:
        L += ["**Gates: not run yet** (verify.py target).", ""]
    if pkg:
        L += [f"Planned: {pkg.get('kind')}, {pkg.get('r7') or ''} {pkg.get('mode') or ''}, likely {pkg.get('likely_hours')} h. "
              f"Playbooks: {', '.join(pkg.get('playbooks') or []) or '-'}.", ""]
    L += ["## Run log", ""]
    if runs:
        L += ["| When (UTC) | Step | Engine | Status | Note | Branch / commit |", "|---|---|---|---|---|---|"]
        for r in runs:
            L.append(f"| {r['at']} | {r['step']} | {r['engine']} | {r['status']} | {r['note'].replace('|', '/')} | {r['branch']} {r['commit'][:10]} |")
        by = Counter(r["engine"] for r in runs if r["status"] == "done")
        L += ["", "Steps done by engine: " + ", ".join(f"{k} {v}" for k, v in by.most_common()) + "."]
    else:
        L.append("Nothing logged (report.py log).")
    L += ["", "## Gates", ""]
    if ver:
        L += ["| Gate | Result | Detail |", "|---|---|---|"]
        for s in ver["steps"]:
            r = "not run" if s.get("passed") is None else ("pass" if s["passed"] else "fail")
            det = ", ".join(f"{k} {s[k]}" for k in ("warnings", "errors", "block_open", "block_waived", "warn", "note") if s.get(k) not in (None, "", []))
            L.append(f"| {s['gate']} | {r} | {det} |")
        if base:
            bb = {s["gate"]: s for s in base["steps"]}
            L += ["", "Baseline (original, before changes): " + ", ".join(
                f"{g} {'pass' if s['passed'] else 'fail'} ({s.get('warnings', 0)} warnings)" for g, s in bb.items()) + "."]
    else:
        L.append("Not run.")
    open_by_pb = defaultdict(int)
    if res:
        for h in res["hits"]:
            if h["level"] == "block" and not h["waived"]:
                open_by_pb[res["rules"][h["rule"]]["playbook"]] += 1
        wv = [h for h in res["hits"] if h["waived"]]
        L += ["", "## Residue", "", f"{res['summary']['block_open']} blocking open, {res['summary']['block_waived']} waived, "
              f"{res['summary']['warn']} to review. Full list: residue.md."]
        if wv:
            L += ["", "Waivers:", ""] + sorted({f"- {h['rule']} `{h['file']}`: {h['waiver']}" for h in wv})
    if par:
        L += ["", "## Parity", "", f"{par['matched']} of {par['total']} recorded requests match. Masked: {', '.join(par['masks'])}."]
        for r in par["rows"]:
            if not r["match"]:
                L.append(f"- {r['name']} `{r['path']}`: {r['diff']}")
    if pkg:
        L += ["", "## Planned items", "", "Done = the playbook has no blocking residue left (the gate decides, not this table).", "",
              "| Rule | Finding | Owner | Playbook | Status |", "|---|---|---|---|---|"]
        for i in sorted(pkg.get("items", []), key=lambda x: (x["owner"], x["playbook"])):
            st = "-" if not res else ("open" if open_by_pb.get(i["playbook"]) else "done")
            if i["owner"] in ("dba", "devops", "decision"):
                st = f"outside code ({i['owner']})"
            L.append(f"| {i['rule']} | {i['title']} | {i['owner']} | {i['playbook']} | {st} |")
    hp = write_pair(os.path.join(d, "execution-report.md"), "\n".join(L) + "\n")
    print(f"execution report -> {hp}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("log")
    lg.add_argument("--dir", required=True)
    lg.add_argument("--step", required=True)
    lg.add_argument("--engine", required=True, choices=["aws-transform", "devtx", "claude", "db-agent", "human"])
    lg.add_argument("--status", required=True, choices=["started", "done", "failed", "skipped"])
    lg.add_argument("--note")
    lg.add_argument("--branch")
    lg.add_argument("--commit")
    b = sub.add_parser("build")
    b.add_argument("--dir", required=True)
    b.add_argument("--plan")
    b.add_argument("--package")
    a = ap.parse_args()
    log(a) if a.cmd == "log" else build(a)


if __name__ == "__main__":
    main()
