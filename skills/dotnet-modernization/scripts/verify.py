"""Verification gates for a ported solution (run, do not read).

    python scripts/verify.py baseline <solution.sln|project|folder> [--out <dir>]
    python scripts/verify.py target   <solution.sln|project|folder> [--db-target sqlserver|postgresql|dual] [--tfm net8.0|net10.0|both]
                                      [--waivers waivers.json] [--dockerfile Dockerfile --health /health --port 8080]
                                      [--goldens <dir> [--masks masks.json] [--base-url URL]]
                                      [--outputs cases.json --output-goldens <dir>] [--security]
                                      [--skip tests,container,...] [--linux-only] [--out <dir>]
    python scripts/verify.py record-outputs <solution|folder> --outputs cases.json --output-goldens <dir> [--masks masks.json]

baseline (before any change, on the original): builds with MSBuild for a .NET Framework solution (found with vswhere)
  or dotnet build, runs the tests it can, and records the result in <out>/baseline.json. It never fails: it is the
  reference that "no worse than before" is judged against.
target (after the engine and the clean-up): the gates, in order. A gate that did not run stays in the report as
  "not run" with its reason, so the report shows what was not proven:
  build        dotnet build -c Release; every project targets the plan's framework (--tfm net8.0, net10.0 or both, the
               default; netstandard2.0 is accepted for a shared library); NU1701, NU1605 or NU1608 in the build log fail it
  tests        dotnet test -c Release --no-build, when a test project exists
  residue      residue_scan.py: no blocking port residue open (waivers allowed, listed)
  linux        linux_readiness.py: no blocking Linux readiness hit open (337 checks: paths and case, time zones,
               culture, Windows-only APIs and packages, container image, IIS hosting ...); --linux-only skips the
               residue gate (an application already on modern .NET)
  container    docker build of the Dockerfile, run, GET the health path until 200 (60 s), then stop
  parity       parity.py replay against the running container (or --base-url) when --goldens is given
  outputs      console apps, Windows services, workers, batch jobs: runs each case of --outputs and compares the files it
               writes with --output-goldens (recorded by record-outputs against the original build)
  database     manual, never run by this script (reference/verification.md, Database gate). --db-target selects the
               residue rules for that database target and nothing else
  security     optional, with --security: dotnet list package --vulnerable --include-transitive
  performance  optional, manual: no load test runs here (reference/verification.md, Optional gates)
Writes <out>/verify.json and verify.md with its .html twin (default <out> = <folder>/.modernization).
Exit 1 when any gate that ran failed, or when no gate ran. Needs the .NET 10 SDK; Docker for the container gate.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mdhtml import write_pair  # noqa: E402
import linux_readiness  # noqa: E402
import parity  # noqa: E402
import residue_scan  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
NU_BLOCKED = ("NU1701", "NU1605", "NU1608")
BUILD_CODE = re.compile(r"\b(?:warning|error)\s+((?:CS|VB|MSB|CA|SYSLIB|NETSDK|NU|ASPDEPR|BC)\d{3,5})\b[^\r\n]*")


def sh(cmd, cwd=None, timeout=1800):
    t = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        out, rc = (p.stdout or "") + (p.stderr or ""), p.returncode
    except FileNotFoundError as e:
        out, rc = str(e), 127
    except subprocess.TimeoutExpired:
        out, rc = f"timed out after {timeout} s", 124
    return {"cmd": " ".join(cmd), "rc": rc, "seconds": round(time.time() - t), "tail": "\n".join(out.strip().splitlines()[-25:]), "out": out}


def target_of(path):
    """(build target, folder): a .sln/.slnx/.csproj or the single solution in a folder."""
    p = os.path.abspath(path)
    if os.path.isfile(p):
        return p, os.path.dirname(p)
    sl = glob.glob(os.path.join(p, "*.sln")) + glob.glob(os.path.join(p, "*.slnx"))
    if len(sl) == 1:
        return sl[0], p
    pr = glob.glob(os.path.join(p, "*.csproj")) + glob.glob(os.path.join(p, "*.vbproj"))
    if len(pr) == 1:
        return pr[0], p
    raise SystemExit(f"{path}: give the .sln or project file ({len(sl)} solutions, {len(pr)} projects in the folder)")


def projects(folder):
    out = []
    for p in glob.glob(os.path.join(folder, "**", "*.*proj"), recursive=True):
        if os.path.splitext(p)[1] in (".csproj", ".vbproj", ".fsproj") and not re.search(r"[\\/](bin|obj)[\\/]", p):
            out.append(p)
    return out


def counts(out):
    w = len(set(re.findall(r"warning [A-Z]+\d+[^\r\n]*", out)))
    e = len(set(re.findall(r"error [A-Z]+\d+[^\r\n]*", out)))
    return w, e


def build_codes(out):
    """Distinct build messages per code (CS, VB, MSB, CA, SYSLIB, NETSDK, NU, ASPDEPR, BC), as {code: count}."""
    seen = {}
    for m in BUILD_CODE.finditer(out):
        seen[m.group(0)] = m.group(1)
    return Counter(seen.values())


def tfm_check(folder, allowed):
    """Projects whose target frameworks are not the plan's (netstandard2.0 is always accepted, for a shared library)."""
    bad = []
    for p in projects(folder):
        t = open(p, encoding="utf-8-sig", errors="replace").read()
        fw = [x.strip() for g in re.findall(r"<TargetFrameworks?>([^<]+)<", t) for x in g.split(";") if x.strip()]
        if not fw or not all(x in allowed or x == "netstandard2.0" for x in fw):
            bad.append(os.path.relpath(p, folder).replace("\\", "/") + f" ({', '.join(fw) or 'no TargetFramework: legacy project'})")
    return bad


def msbuild():
    vw = os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe")
    if os.path.exists(vw):
        r = sh([vw, "-latest", "-products", "*", "-requires", "Microsoft.Component.MSBuild", "-find", r"MSBuild\**\Bin\MSBuild.exe"], timeout=60)
        if r["rc"] == 0 and r["out"].strip():
            return r["out"].strip().splitlines()[0]
    return shutil.which("msbuild")


def is_test(p):
    t = open(p, encoding="utf-8-sig", errors="replace").read()
    return bool(re.search(r"Microsoft\.NET\.Test\.Sdk|xunit|NUnit|MSTest", t)) or re.search(r"Tests?\.\w+proj$", p)


def baseline(a):
    tgt, folder = target_of(a.path)
    projs = projects(folder)
    legacy = any(re.search(r"<TargetFrameworkVersion>v4|ToolsVersion=", open(p, encoding="utf-8-sig", errors="replace").read()) for p in projs)
    steps = []
    mb = msbuild() if legacy else None
    if legacy and mb:
        steps.append({"gate": "build", **sh([mb, tgt, "/restore", "/p:Configuration=Release", "/m", "/v:minimal", "/nologo"], cwd=folder)})
    else:
        steps.append({"gate": "build", **sh(["dotnet", "build", tgt, "-c", "Release", "-nologo"], cwd=folder)})
        if legacy:
            steps[-1]["note"] = "MSBuild (Visual Studio Build Tools) not found: dotnet build of a .NET Framework solution often fails; record the original build from its CI instead"
    if any(is_test(p) for p in projs) and steps[0]["rc"] == 0:
        steps.append({"gate": "tests", **sh(["dotnet", "test", tgt, "-c", "Release", "--no-build", "-nologo"], cwd=folder)})
    for s in steps:
        s["warnings"], s["errors"] = counts(s.pop("out"))
        s["passed"] = s["rc"] == 0
    res = {"kind": "baseline", "target": tgt, "legacy": legacy, "projects": len(projs), "steps": steps}
    return res


def wait_health(url, seconds=60):
    end = time.time() + seconds
    last = None
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return True, "200"
                last = str(r.status)
        except Exception as e:  # noqa: BLE001  (connection refused while the app starts)
            last = str(e)
        time.sleep(2)
    return False, last


def first_line_diff(old, new):
    crlf_old, crlf_new = old.count("\r\n"), new.count("\r\n")
    if crlf_old != crlf_new:
        return f"line endings differ (CRLF lines: {crlf_old} golden, {crlf_new} port)"
    a, b = old.splitlines(), new.splitlines()
    for i, (x, y) in enumerate(zip(a, b), 1):
        if x != y:
            return f"line {i}: {x[:70]!r} vs {y[:70]!r}"
    return f"{len(a)} lines golden vs {len(b)} port"


def same_output(new, old, masks):
    """Exact bytes first; then text after the parity masks (GUIDs, timestamps, tokens)."""
    if new == old:
        return True, "identical"
    try:
        n, o = new.decode("utf-8"), old.decode("utf-8")
    except UnicodeDecodeError:
        return False, "binary content differs"
    if parity.masked(n, masks) == parity.masked(o, masks):
        return True, "equal after masks"
    return False, first_line_diff(o, n)


def run_cases(cases_path, folder, goldens, masks_path, record):
    """Run each output case; compare the files it writes (and its exit code) with the goldens, or write the goldens
    when record is True. A case path is relative to the solution folder. Returns the rows, the problems and a verdict."""
    cases = json.load(open(cases_path, encoding="utf-8"))
    masks = list(parity.DEFAULT_MASKS)
    if masks_path:
        masks += [m for m in json.load(open(masks_path, encoding="utf-8")) if m.get("regex")]
    rows, problems = [], []
    for c in cases:
        name = c["name"]
        cmd = list(c["cmd"])
        if os.path.exists(os.path.join(folder, cmd[0])):
            cmd[0] = os.path.join(folder, cmd[0])
        cwd = os.path.join(folder, c.get("cwd", "."))
        stdin = open(os.path.join(folder, c["stdin_file"]), "rb").read() if c.get("stdin_file") else None
        try:
            p = subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True, timeout=c.get("timeout", 600))
        except (OSError, subprocess.TimeoutExpired) as e:
            problems.append(f"{name}: did not run ({e})")
            continue
        gdir = os.path.join(goldens, name)
        code_file = os.path.join(gdir, "exit_code.txt")
        if record:
            os.makedirs(gdir, exist_ok=True)
            open(code_file, "w", encoding="utf-8").write(str(p.returncode))
            rows.append({"case": name, "output": "(exit code)", "match": True, "detail": f"recorded {p.returncode}"})
        else:
            golden_rc = open(code_file, encoding="utf-8").read().strip() if os.path.exists(code_file) else None
            ok = golden_rc == str(p.returncode)
            detail = "identical" if ok else ("no golden: record the original first" if golden_rc is None
                                              else f"exit {golden_rc} golden vs {p.returncode} port")
            rows.append({"case": name, "output": "(exit code)", "match": ok, "detail": detail})
        for outp in c.get("outputs", []):
            produced = os.path.join(cwd, outp)
            golden = os.path.join(gdir, outp)
            if not os.path.exists(produced):
                rows.append({"case": name, "output": outp, "match": False, "detail": "output not written"})
                continue
            new = open(produced, "rb").read()
            if record:
                os.makedirs(os.path.dirname(golden), exist_ok=True)
                shutil.copyfile(produced, golden)
                rows.append({"case": name, "output": outp, "match": True, "detail": "recorded"})
            elif not os.path.exists(golden):
                rows.append({"case": name, "output": outp, "match": False, "detail": "no golden: record the original first"})
            else:
                ok, detail = same_output(new, open(golden, "rb").read(), masks)
                rows.append({"case": name, "output": outp, "match": ok, "detail": detail})
    total = len(rows)
    matched = sum(1 for r in rows if r["match"])
    return {"passed": not problems and total > 0 and matched == total, "rows": rows, "problems": problems,
            "matched": matched, "total": total}


def target(a):
    tgt, folder = target_of(a.path)
    skip = set((a.skip or "").split(",")) - {""}
    out = a.out or os.path.join(folder, ".modernization")
    allowed = {"net8.0", "net10.0"} if a.tfm == "both" else {a.tfm}
    steps = []

    def add(gate, passed, **kw):
        steps.append({"gate": gate, "passed": passed, **kw})
        return passed

    def not_run(gate, note):
        steps.append({"gate": gate, "passed": None, "note": note})

    build_ok = False
    if "build" in skip:
        not_run("build", "skipped (--skip build)")
    else:
        r = sh(["dotnet", "build", tgt, "-c", "Release", "-nologo"], cwd=folder)
        text = r.pop("out")
        w, e = counts(text)
        codes = build_codes(text)
        tfm_bad = tfm_check(folder, allowed)
        blocked = [c for c in NU_BLOCKED if codes.get(c)]
        build_ok = r["rc"] == 0 and not tfm_bad and not blocked
        add("build", build_ok, warnings=w, errors=e, blocked_codes=blocked, tfm_not_allowed=tfm_bad, not_net10=tfm_bad,
            codes=dict(codes.most_common(40)), **r)
    test_projs = [p for p in projects(folder) if is_test(p)]
    if "tests" in skip:
        not_run("tests", "skipped (--skip tests)")
    elif not test_projs:
        not_run("tests", "no test project")
    elif not build_ok:
        not_run("tests", "build did not pass")
    else:
        r = sh(["dotnet", "test", tgt, "-c", "Release", "--no-build", "-nologo"], cwd=folder)
        r.pop("out")
        add("tests", r["rc"] == 0, **r)
    wv = json.load(open(a.waivers, encoding="utf-8")) if a.waivers else []
    os.makedirs(out, exist_ok=True)
    if "residue" in skip:
        not_run("residue", "skipped (--skip residue)")
    elif a.linux_only:
        not_run("residue", "--linux-only: application already on modern .NET, port residue gate not applied")
    else:
        res = residue_scan.scan(folder, a.db_target, wv)
        json.dump(res, open(os.path.join(out, "residue.json"), "w", encoding="utf-8"), indent=1)
        write_pair(os.path.join(out, "residue.md"), residue_scan.render(res))
        add("residue", res["passed"], **res["summary"])
    if "linux" in skip:
        not_run("linux readiness", "skipped (--skip linux)")
    else:
        lr = linux_readiness.scan(folder, "info", wv)
        json.dump(lr, open(os.path.join(out, "linux-readiness.json"), "w", encoding="utf-8"), indent=1)
        write_pair(os.path.join(out, "linux-readiness.md"), linux_readiness.render(lr))
        add("linux readiness", lr["passed"], **{k: lr["summary"][k] for k in ("block_open", "block_waived", "warn")})
    container_url = None
    name = None
    if "container" in skip:
        not_run("container", "skipped (--skip container)")
    elif not a.dockerfile:
        not_run("container", "no --dockerfile given")
    else:
        tag = "modernization-verify:" + re.sub(r"[^a-z0-9]", "", os.path.basename(folder).lower())[:40]
        r = sh(["docker", "build", "-f", a.dockerfile, "-t", tag, "."], cwd=folder, timeout=3600)
        r.pop("out")
        ok = r["rc"] == 0
        health = None
        if ok:
            name = "mv-" + str(int(time.time()))
            run = sh(["docker", "run", "-d", "--rm", "--name", name, "-p", f"{a.port}:{a.port}", "-e", f"ASPNETCORE_URLS=http://+:{a.port}", tag], timeout=120)
            ok = run["rc"] == 0
            if ok:
                container_url = f"http://localhost:{a.port}"
                ok, health = wait_health(container_url + a.health)
                if not ok:
                    r["tail"] = sh(["docker", "logs", "--tail", "40", name], timeout=30)["out"][-3000:]
        add("container", ok, health=health, image=tag, **r)
    if "parity" in skip:
        not_run("parity", "skipped (--skip parity)")
    elif not a.goldens:
        not_run("parity", "no --goldens given (record the original's responses with parity.py record)")
    else:
        base = a.base_url or container_url
        if not base:
            not_run("parity", "no --base-url and no running container")
        else:
            cmd = [sys.executable, os.path.join(HERE, "parity.py"), "replay", "--base-url", base, "--goldens", a.goldens, "--out", out]
            if a.masks:
                cmd += ["--masks", a.masks]
            r = sh(cmd, timeout=1800)
            r.pop("out")
            add("parity", r["rc"] == 0, **r)
    if "outputs" in skip:
        not_run("outputs", "skipped (--skip outputs)")
    elif not a.outputs:
        not_run("outputs", "no --outputs cases (console, service, worker and batch apps need this gate)")
    elif not a.output_goldens:
        not_run("outputs", "no --output-goldens (record the original's outputs with record-outputs)")
    else:
        ro = run_cases(a.outputs, folder, a.output_goldens, a.masks, record=False)
        json.dump(ro, open(os.path.join(out, "outputs.json"), "w", encoding="utf-8"), indent=1)
        bad = [f"{r['case']} {r['output']}: {r['detail']}" for r in ro["rows"] if not r["match"]] + ro["problems"]
        add("outputs", ro["passed"], note=f"{ro['matched']} of {ro['total']} outputs match", tail="\n".join(bad)[-3000:])
    if a.db_target == "sqlserver":
        not_run("database", "not applicable: SQL Server target (the tests cover the one engine)")
    else:
        not_run("database", f"manual, not run by verify.py: the {a.db_target} database gate in reference/verification.md")
    if "security" in skip:
        not_run("security", "skipped (--skip security)")
    elif not a.security:
        not_run("security", "optional: add --security (dotnet list package --vulnerable; needs NuGet access)")
    else:
        r = sh(["dotnet", "list", tgt, "package", "--vulnerable", "--include-transitive"], cwd=folder, timeout=900)
        text = r.pop("out")
        vuln = len(re.findall(r"has the following vulnerable packages", text, re.I))
        add("security", r["rc"] == 0 and vuln == 0, note=f"{vuln} project(s) list vulnerable packages", **r)
    not_run("performance", "optional, manual: no load test run here (k6 or JMeter against the container; reference/verification.md)")
    if name:
        sh(["docker", "stop", name], timeout=60)
    return {"kind": "target", "target": tgt, "db_target": a.db_target, "steps": steps, "out": out}


def render(res, base):
    L = [f"# Verification: {os.path.basename(res['target'])} ({res['kind']})", ""]
    ran = [s for s in res["steps"] if s.get("passed") is not None]
    ok = bool(ran) and all(s["passed"] for s in ran)
    if res["kind"] == "target":
        L += [f"**{'PASS' if ok else 'FAIL'}**: {sum(1 for s in ran if s['passed'])} of {len(ran)} gates that ran passed; "
              f"{len(res['steps']) - len(ran)} not run.", ""]
    else:
        L += ["Baseline of the original solution, before any change. It is the reference, not a gate.", ""]
    L += ["| Gate | Result | Detail | Command |", "|---|---|---|---|"]
    for s in res["steps"]:
        r = "not run" if s.get("passed") is None else ("pass" if s["passed"] else "fail")
        det = []
        for k in ("warnings", "errors", "blocked_codes", "block_open", "block_waived", "warn", "health", "note"):
            if s.get(k) not in (None, "", []):
                det.append(f"{k} {s[k]}")
        if s.get("tfm_not_allowed"):
            det.append("target framework not allowed: " + "; ".join(s["tfm_not_allowed"][:5]))
        L.append(f"| {s['gate']} | {r} | {', '.join(map(str, det)).replace('|', '/')} | `{s.get('cmd', '')[:120]}` |")
    if base and res["kind"] == "target":
        b = {s["gate"]: s for s in base.get("steps", [])}
        L += ["", "## Against the baseline", ""]
        for s in res["steps"]:
            o = b.get(s["gate"])
            if o:
                L.append(f"- {s['gate']}: baseline {'pass' if o['passed'] else 'fail'} ({o.get('warnings', 0)} warnings), now "
                         f"{'pass' if s.get('passed') else 'fail' if s.get('passed') is False else 'not run'} ({s.get('warnings', '-')} warnings)")
    for s in res["steps"]:
        if s.get("passed") is False and s.get("tail"):
            L += ["", f"## {s['gate']}: last lines", "", "```", s["tail"], "```"]
    return "\n".join(L) + "\n", ok


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kind", choices=["baseline", "target", "record-outputs"])
    ap.add_argument("path")
    ap.add_argument("--db-target", choices=["sqlserver", "postgresql", "dual"], default="sqlserver",
                    help="selects the residue rules for that database target; the database gate itself is manual (not run)")
    ap.add_argument("--tfm", choices=["net8.0", "net10.0", "both"], default="both", help="the plan's target framework (both = net8.0 or net10.0)")
    ap.add_argument("--waivers")
    ap.add_argument("--dockerfile")
    ap.add_argument("--health", default="/health")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--goldens")
    ap.add_argument("--masks")
    ap.add_argument("--base-url")
    ap.add_argument("--outputs", help="output-diff cases (JSON list of name, cmd, cwd, stdin_file, outputs, timeout)")
    ap.add_argument("--output-goldens", help="folder of the original's outputs (written by record-outputs, read by target)")
    ap.add_argument("--security", action="store_true", help="optional: dotnet list package --vulnerable --include-transitive")
    ap.add_argument("--skip")
    ap.add_argument("--linux-only", action="store_true", help="application already on modern .NET: skip the port residue gate, keep the Linux readiness gate")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.kind == "record-outputs":
        if not (a.outputs and a.output_goldens):
            raise SystemExit("record-outputs needs --outputs <cases.json> and --output-goldens <dir>")
        _, folder = target_of(a.path)
        rec = run_cases(a.outputs, folder, a.output_goldens, a.masks, record=True)
        print(f"record-outputs: {rec['matched']} of {rec['total']} recorded -> {a.output_goldens}")
        for p in rec["problems"]:
            print("  did not run: " + p)
        sys.exit(0 if rec["passed"] else 1)
    res = baseline(a) if a.kind == "baseline" else target(a)
    out = a.out or res.get("out") or os.path.join(target_of(a.path)[1], ".modernization")
    os.makedirs(out, exist_ok=True)
    name = "baseline" if a.kind == "baseline" else "verify"
    json.dump(res, open(os.path.join(out, name + ".json"), "w", encoding="utf-8"), indent=1)
    base = None
    if a.kind == "target" and os.path.exists(os.path.join(out, "baseline.json")):
        base = json.load(open(os.path.join(out, "baseline.json"), encoding="utf-8"))
    md, ok = render(res, base)
    hp = write_pair(os.path.join(out, name + ".md"), md)
    print(f"{name}: {'PASS' if ok else 'FAIL'} " + ", ".join(f"{s['gate']} {'-' if s.get('passed') is None else 'ok' if s['passed'] else 'FAIL'}" for s in res["steps"]) + f" -> {hp}")
    sys.exit(0 if (ok or a.kind == "baseline") else 1)


if __name__ == "__main__":
    main()
