"""Verification gates for a ported solution (run, do not read).

    python scripts/verify.py baseline <solution.sln|project|folder> [--out <dir>]
    python scripts/verify.py target   <solution.sln|project|folder> [--db-target sqlserver|postgresql|dual]
                                      [--waivers waivers.json] [--dockerfile Dockerfile --health /health --port 8080]
                                      [--goldens <dir> [--masks masks.json] [--base-url URL]] [--skip tests,container,...] [--linux-only]
                                      [--out <dir>]

baseline (before any change, on the original): builds with MSBuild for a .NET Framework solution (found with vswhere)
  or dotnet build, runs the tests it can, and records the result in <out>/baseline.json. It never fails: it is the
  reference that "no worse than before" is judged against.
target (after the engine and the clean-up): the gates, in order, each recorded with its command and log tail:
  build      dotnet build -c Release; every project must target net10.0 (or netstandard2.0 for a shared library)
  tests      dotnet test -c Release --no-build, when a test project exists (skip shows as "not run", never as passed)
  residue    residue_scan.py: no blocking port residue open (waivers allowed, listed)
  linux      linux_readiness.py: no blocking Linux readiness hit open (240 checks: paths and case, time zones,
             culture, Windows-only APIs and packages, container image, IIS hosting ...); --linux-only skips the
             residue gate (an application already on modern .NET)
  container  docker build of the Dockerfile, run, GET the health path until 200 (60 s), then stop
  parity     parity.py replay against the running container (or --base-url) when --goldens is given
Writes <out>/verify.json and verify.md with its .html twin (default <out> = <folder>/.modernization).
Exit 1 when any gate that ran failed. Needs the .NET 10 SDK; Docker for the container gate.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mdhtml import write_pair  # noqa: E402
import linux_readiness  # noqa: E402
import residue_scan  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


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


def target(a):
    tgt, folder = target_of(a.path)
    skip = set((a.skip or "").split(",")) - {""}
    out = a.out or os.path.join(folder, ".modernization")
    steps = []

    def add(gate, passed, **kw):
        steps.append({"gate": gate, "passed": passed, **kw})
        return passed

    if "build" not in skip:
        r = sh(["dotnet", "build", tgt, "-c", "Release", "-nologo"], cwd=folder)
        w, e = counts(r.pop("out"))
        tfm_bad = []
        for p in projects(folder):
            t = open(p, encoding="utf-8-sig", errors="replace").read()
            fw = re.findall(r"<TargetFrameworks?>([^<]+)<", t)
            if not fw or not any(re.search(r"net(10|\d{2})\.0|netstandard2\.[01]", x) for x in fw) or any(re.search(r"\bnet4\d", x) for x in fw):
                tfm_bad.append(os.path.relpath(p, folder).replace("\\", "/") + f" ({', '.join(fw) or 'no TargetFramework: legacy project'})")
        add("build", r["rc"] == 0 and not tfm_bad, warnings=w, errors=e, not_net10=tfm_bad, **r)
    test_projs = [p for p in projects(folder) if is_test(p)]
    if "tests" not in skip:
        if test_projs and steps and steps[0]["passed"]:
            r = sh(["dotnet", "test", tgt, "-c", "Release", "--no-build", "-nologo"], cwd=folder)
            r.pop("out")
            add("tests", r["rc"] == 0, **r)
        else:
            add("tests", None, note="no test project" if not test_projs else "build failed")
    wv = json.load(open(a.waivers, encoding="utf-8")) if a.waivers else []
    os.makedirs(out, exist_ok=True)
    if "residue" not in skip and not a.linux_only:
        res = residue_scan.scan(folder, a.db_target, wv)
        json.dump(res, open(os.path.join(out, "residue.json"), "w", encoding="utf-8"), indent=1)
        write_pair(os.path.join(out, "residue.md"), residue_scan.render(res))
        add("residue", res["passed"], **res["summary"])
    if "linux" not in skip:
        lr = linux_readiness.scan(folder, "info", wv)
        json.dump(lr, open(os.path.join(out, "linux-readiness.json"), "w", encoding="utf-8"), indent=1)
        write_pair(os.path.join(out, "linux-readiness.md"), linux_readiness.render(lr))
        add("linux readiness", lr["passed"], **{k: lr["summary"][k] for k in ("block_open", "block_waived", "warn")})
    container_url = None
    name = None
    if a.dockerfile and "container" not in skip:
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
    if a.goldens and "parity" not in skip:
        base = a.base_url or container_url
        if not base:
            add("parity", None, note="no --base-url and no running container")
        else:
            cmd = [sys.executable, os.path.join(HERE, "parity.py"), "replay", "--base-url", base, "--goldens", a.goldens, "--out", out]
            if a.masks:
                cmd += ["--masks", a.masks]
            r = sh(cmd, timeout=1800)
            r.pop("out")
            add("parity", r["rc"] == 0, **r)
    if name:
        sh(["docker", "stop", name], timeout=60)
    return {"kind": "target", "target": tgt, "db_target": a.db_target, "steps": steps, "out": out}


def render(res, base):
    L = [f"# Verification: {os.path.basename(res['target'])} ({res['kind']})", ""]
    ran = [s for s in res["steps"] if s.get("passed") is not None]
    ok = all(s["passed"] for s in ran)
    if res["kind"] == "target":
        L += [f"**{'PASS' if ok else 'FAIL'}**: {sum(1 for s in ran if s['passed'])} of {len(ran)} gates that ran passed; "
              f"{len(res['steps']) - len(ran)} not run.", ""]
    else:
        L += ["Baseline of the original solution, before any change. It is the reference, not a gate.", ""]
    L += ["| Gate | Result | Detail | Command |", "|---|---|---|---|"]
    for s in res["steps"]:
        r = "not run" if s.get("passed") is None else ("pass" if s["passed"] else "fail")
        det = []
        for k in ("warnings", "errors", "block_open", "block_waived", "warn", "health", "note"):
            if s.get(k) not in (None, "", []):
                det.append(f"{k} {s[k]}")
        if s.get("not_net10"):
            det.append("not net10: " + "; ".join(s["not_net10"][:5]))
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
    ap.add_argument("kind", choices=["baseline", "target"])
    ap.add_argument("path")
    ap.add_argument("--db-target", choices=["sqlserver", "postgresql", "dual"], default="sqlserver")
    ap.add_argument("--waivers")
    ap.add_argument("--dockerfile")
    ap.add_argument("--health", default="/health")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--goldens")
    ap.add_argument("--masks")
    ap.add_argument("--base-url")
    ap.add_argument("--skip")
    ap.add_argument("--linux-only", action="store_true", help="application already on modern .NET: skip the port residue gate, keep the Linux readiness gate")
    ap.add_argument("--out")
    a = ap.parse_args()
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
