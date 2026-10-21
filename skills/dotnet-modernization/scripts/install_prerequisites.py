"""Check (and where it is safe, install) what dotnet-modernization needs, at user level (run, do not read).

    python scripts/install_prerequisites.py            # check, then install the missing .NET global tools
    python scripts/install_prerequisites.py --check    # report only; exit 1 if something required is missing

Required:  Python 3.10+, git, the .NET 10 SDK (dotnet build / test of the port)
Optional:  Docker (container gate), MSBuild / Visual Studio Build Tools (baseline build of a .NET Framework solution),
           upgrade-assistant and dotnet-svcutil (.NET global tools: installed here with `dotnet tool install -g`),
           AWS CLI and the AWS Transform CLI (atx) for AWS Transform runs, Kiro CLI (DevTx toolkit runs locally).
The .NET SDK and Docker are not installed from here (machine-level installers): the report says where to get them.
Standard library only; idempotent.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

TOOLS = [("upgrade-assistant", "upgrade-assistant"), ("dotnet-svcutil", "dotnet-svcutil")]


def out(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    rows, missing = [], False

    def row(name, ok, detail, required):
        nonlocal missing
        rows.append((name, "ok" if ok else ("MISSING" if required else "absent"), detail))
        missing |= required and not ok

    row("python 3.10+", sys.version_info >= (3, 10), sys.version.split()[0], True)
    row("git", bool(shutil.which("git")), shutil.which("git") or "https://git-scm.com/downloads", True)
    rc, sdks = out(["dotnet", "--list-sdks"])
    v10 = [x.split()[0] for x in sdks.splitlines() if re.match(r"(1\d|[2-9]\d)\.", x)]
    row(".NET 10 SDK", bool(v10), ", ".join(v10) or "https://dotnet.microsoft.com/download/dotnet/10.0", True)
    rc, dv = out(["docker", "version", "--format", "{{.Server.Version}}"])
    row("Docker (container gate)", rc == 0, dv.strip()[:60] if rc == 0 else "Docker Desktop / Engine not found or not running", False)
    vw = os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe")
    row("MSBuild (baseline of .NET Framework)", os.path.exists(vw) or bool(shutil.which("msbuild")),
        "Visual Studio Build Tools" if os.name == "nt" else "Windows only; record the baseline from the original CI", False)
    rc, tl = out(["dotnet", "tool", "list", "-g"]) if v10 else (1, "")
    for pkg, cmd in TOOLS:
        have = pkg in tl.lower()
        if not have and v10 and not a.check:
            rc2, _ = out(["dotnet", "tool", "install", "-g", pkg])
            have = rc2 == 0
        row(f"{pkg} (.NET tool)", have, "dotnet tool install -g " + pkg, False)
    row("AWS CLI", bool(shutil.which("aws")), "AWS Transform / CodeBuild runs", False)
    row("AWS Transform CLI (atx)", bool(shutil.which("atx")), "AWS Transform custom runs (see reference/engines.md)", False)
    row("Node.js (DB porting agent scripts)", bool(shutil.which("node")), shutil.which("node") or "https://nodejs.org (only for the DB porting agent)", False)
    row("Kiro CLI", bool(shutil.which("kiro-cli") or shutil.which("kiro")), "local DevTx-style runs (see reference/engines.md)", False)
    w = max(len(r[0]) for r in rows)
    for n, s, d in rows:
        print(f"{n:<{w}}  {s:<8} {d}")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
