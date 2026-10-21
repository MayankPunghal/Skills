"""Linux build validation and platform-analyzer pass (brief item: "run the app on Linux / WSL" as validation).

    python <skill>/scripts/validate_linux_build.py --repo NAME            # plan only: expected outcome + exact commands (no downloads)
    python <skill>/scripts/validate_linux_build.py --repo NAME --run      # execute (restores NuGet packages; may pull a container image)
        [--runner auto|local|wsl|docker] [--image mcr.microsoft.com/dotnet/sdk:10.0]

What it does per project:
  legacy (non-SDK) project      -> not buildable with the .NET SDK on Linux (needs SDK-style conversion first); recorded as such
  SDK-style, .NET Framework TFM -> builds on Linux only with reference assemblies (Microsoft.NETFramework.ReferenceAssemblies) and
                                   never runs there; recorded
  SDK-style, .NET 5+ TFM        -> `dotnet build` on Linux (WSL distro with dotnet, a container, or a Linux host); errors and
                                   CA1416 platform-compatibility warnings (Windows-only API calls) become evidence
--run with --runner local on Windows still yields CA1416 warnings (compile-time analysis), but not a Linux build result.
Results: assessment/scan/<repo>.linux-build.json (read by build_report.py, tooling section).
Downloads (container images, NuGet packages) happen only with --run: ask the user before running it.
"""
import argparse
import datetime
import os
import platform
import re
import sys

from _common import OUT, load_config, read_json, run, utf8_stdout, write_json

WARN = re.compile(r"^(?P<file>[^(\r\n]+)\((?P<line>\d+),\d+\): (?P<kind>warning|error) (?P<code>[A-Z]+\d+): (?P<msg>.*?)(?: \[.*\])?$", re.M)


def pick_runner(want):
    if want != "auto":
        return want
    if platform.system() == "Linux":
        return "local"
    code, out = run(["wsl", "-l", "-q"])
    distros = [d.strip().replace("\x00", "") for d in out.splitlines() if d.strip().replace("\x00", "") and "docker" not in d.lower()]
    if code == 0 and distros:
        c2, _ = run(["wsl", "-d", distros[0], "--", "bash", "-lc", "command -v dotnet"])
        if c2 == 0:
            return f"wsl:{distros[0]}"
    if run(["docker", "info"])[0] == 0:
        return "docker"
    return "local"


def to_wsl_path(p):
    p = os.path.abspath(p).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    return f"/mnt/{m.group(1).lower()}/{m.group(2)}" if m else p


def command(runner, repo_root, proj, image):
    rel = proj.replace("\\", "/")
    if runner == "local":
        return ["dotnet", "build", os.path.join(repo_root, proj), "-nologo", "-clp:NoSummary", "-v:q"]
    if runner.startswith("wsl:"):
        return ["wsl", "-d", runner[4:], "--", "bash", "-lc", f"cd '{to_wsl_path(repo_root)}' && dotnet build '{rel}' -nologo -clp:NoSummary -v:q"]
    return ["docker", "run", "--rm", "-v", f"{os.path.abspath(repo_root)}:/src", "-w", "/src", image, "dotnet", "build", rel, "-nologo", "-clp:NoSummary", "-v:q"]


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--runner", default="auto")
    ap.add_argument("--image", default="mcr.microsoft.com/dotnet/sdk:10.0")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    inv = read_json(os.path.join(OUT, "inventory", f"{a.repo}.json"))
    if not inv:
        sys.exit("run discover_estate.py first")
    runner = pick_runner(a.runner) if a.run else (a.runner if a.runner != "auto" else "docker")
    results = []
    for p in inv["projects"]:
        if p["type"] == "database" or p.get("error"):
            continue
        fam = p.get("framework_family", "")
        entry = {"project": p["path"], "type": p["type"], "tfms": p.get("target_frameworks", []), "sdk_style": bool(p.get("sdk_style"))}
        if not p.get("sdk_style"):
            entry.update(status="not-buildable", detail="Legacy project format: the .NET SDK cannot build it on Linux until it is converted to SDK-style.")
        elif "netcore" not in fam:
            entry.update(status="framework-only", detail=f"Targets {', '.join(entry['tfms'])}: may compile on Linux with reference assemblies but cannot run there.")
        elif any(t.endswith("-windows") for t in entry["tfms"]):
            entry.update(status="windows-target", detail="Targets a -windows TFM (WinForms/WPF/Windows APIs): Windows-only by design.")
        else:
            cmd = command(runner, inv["root"], p["path"], a.image)
            entry["command"] = " ".join(cmd)
            if not a.run:
                entry.update(status="planned", detail="Run with --run to build on Linux and collect CA1416 / build errors.")
            else:
                code, out = run(cmd, timeout=3600)
                diags = [m.groupdict() for m in WARN.finditer(out)]
                ca1416 = [d for d in diags if d["code"] == "CA1416"]
                errors = [d for d in diags if d["kind"] == "error"]
                entry.update(status="built" if code == 0 else "failed", runner=runner, exit_code=code,
                             errors=[{k: d[k] for k in ("file", "line", "code", "msg")} for d in errors[:50]],
                             ca1416=[{k: d[k] for k in ("file", "line", "msg")} for d in ca1416[:200]],
                             detail=(f"{len(errors)} errors, {len(ca1416)} CA1416 warnings" if diags else out[-400:].strip()))
        results.append(entry)
        print(f"{entry['status']:<15} {p['path']}  {entry.get('detail', '')[:120]}")
    write_json(os.path.join(OUT, "scan", f"{a.repo}.linux-build.json"), {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                                                                           "runner": runner if a.run else "plan", "executed": a.run, "projects": results})
    if not a.run:
        print("plan written; nothing was downloaded or built. Re-run with --run after the user approves downloads (container image / NuGet restore).")


if __name__ == "__main__":
    main()
