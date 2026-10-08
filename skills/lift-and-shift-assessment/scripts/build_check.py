"""Can each solution be built on a clean build agent? Static readiness first, then (after approval) a real build.

    python <skill>/scripts/build_check.py                       static readiness of every solution (reads project files only)
    python <skill>/scripts/build_check.py --toolchain           what is installed here: MSBuild, dotnet, targeting packs
    python <skill>/scripts/build_check.py --run --approve-downloads   real restore + build of a COPY of each solution
    python <skill>/scripts/build_check.py --run --solution ID --approve-downloads

Static readiness reads the .sln and project files and reports what a clean agent needs and what is missing (project files, reference DLLs
that are not in the repository, web build targets, installer projects that MSBuild cannot build). It never changes a client repository.
The real build copies the repository to assessment/build/work/<repo>/ and builds the copy, so bin/ and obj/ never appear in the client's
code. Restore downloads NuGet packages: it runs only with --approve-downloads, which the agent passes only after the user said yes. If MSBuild
is missing the real build is reported as NOT RUN and nothing is installed. A build must pass before artifacts are produced.
Status: READY, PREREQUISITES (builds once the listed tools are on the agent), BLOCKED (something in the repository is missing).
"""
import argparse
import glob
import os
import re
import shutil
import time

from _common import OUT, SOURCE_DIR_SKIP, load_config, mark_step, read_json, run, slug, tool_exe, utf8_stdout, write_json
import intake as I

HINT = re.compile(r"<HintPath>([^<]+)</HintPath>", re.I)
PROJREF = re.compile(r'<ProjectReference\s+Include="([^"]+)"', re.I)
IMPORT = re.compile(r'<Import\s+Project="([^"]+)"', re.I)
ERROR = re.compile(r"(?i)\)?:\s*(?:fatal\s+)?error\s*(?:[A-Z]+\d+)?\s*:")
INSTALLER_EXT = (".vdproj", ".wixproj", ".vdproj", ".isproj")


def toolchain():
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft Visual Studio", "Installer", "vswhere.exe")
    msbuild = None
    if os.path.exists(vswhere):
        code, out = run([vswhere, "-latest", "-products", "*", "-requires", "Microsoft.Component.MSBuild", "-find", r"MSBuild\**\Bin\MSBuild.exe"], timeout=60)
        msbuild = next((l.strip() for l in out.splitlines() if l.strip().lower().endswith("msbuild.exe")), None) if code == 0 else None
    msbuild = msbuild or tool_exe("msbuild")
    pack_dirs = glob.glob(os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Reference Assemblies", "Microsoft", "Framework", ".NETFramework", "v4*"))
    return {"msbuild": msbuild, "nuget": tool_exe("nuget"), "dotnet": tool_exe("dotnet"),
            "netfx_targeting_packs": sorted(os.path.basename(p) for p in pack_dirs)}


def project_text(path):
    try:
        return open(path, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return None


def static_check(root, sol, inv):
    """Issues and prerequisites for one solution from its files. Returns (status, issues, prerequisites)."""
    by_path = {p["path"]: p for p in inv.get("projects", [])}
    issues, pre = [], set()
    sln = os.path.join(root, sol["solution_file"]) if sol["solution_file"] else None
    if sln and not os.path.exists(sln):
        issues.append(f"solution file {sol['solution_file']} not found")
    for p in sol["projects"]:
        full = os.path.join(root, p["path"])
        text = project_text(full)
        if text is None:
            issues.append(f"{p['name']}: project file missing")
            continue
        base = os.path.dirname(full)
        if p["path"].lower().endswith(INSTALLER_EXT):
            issues.append(f"{p['name']}: installer project, MSBuild cannot build it (needs Visual Studio devenv or WiX)")
        for h in HINT.findall(text):
            h = h.strip()
            if "$(" in h and not h.lower().startswith("$(solutiondir)") and not h.lower().startswith("$(projectdir)"):
                continue
            resolved = os.path.normpath(os.path.join(base, h.replace("$(SolutionDir)", os.path.dirname(sln or full) + os.sep).replace("$(ProjectDir)", base + os.sep)))
            if re.match(r"^[A-Za-z]:[\\/]", h) or h.startswith("\\\\"):
                issues.append(f"{p['name']}: reference outside the repository ({os.path.basename(h)} at an absolute path)")
            elif not os.path.exists(resolved) and not h.replace("\\", "/").lower().startswith(("..\\packages", "../packages", "packages/", "..\\..\\packages")) and "/packages/" not in h.replace("\\", "/").lower():
                issues.append(f"{p['name']}: reference DLL not in the repository ({os.path.basename(h)})")
        for r in PROJREF.findall(text):
            if not os.path.exists(os.path.normpath(os.path.join(base, r.replace("\\", os.sep)))):
                issues.append(f"{p['name']}: project reference {r} not found")
        for i in IMPORT.findall(text):
            if "WebApplication.targets" in i or "WebPublishing" in i:
                pre.add("Visual Studio Build Tools: Web development build tools (WebApplication.targets)")
        fw = ",".join(p.get("frameworks") or [])
        if p.get("family") == "netfx":
            pre.add("Visual Studio Build Tools: MSBuild + .NET Framework " + (fw.replace("v", "") or "targeting pack"))
            if os.path.exists(os.path.join(base, "packages.config")):
                pre.add("NuGet restore of packages.config: nuget.exe (msbuild -restore skips packages.config projects) and access to the NuGet feed")
        else:
            pre.add("dotnet SDK for " + (fw or "the target framework"))
            pre.add("restore: access to the NuGet feed")
    status = "BLOCKED" if issues else "PREREQUISITES" if pre else "READY"
    return status, sorted(set(issues)), sorted(pre)


def copy_repo(src, dst):
    if os.path.exists(dst):
        return
    skip = shutil.ignore_patterns(".git", "bin", "obj", "node_modules", ".vs", "packages")
    shutil.copytree(src, dst, ignore=skip)


def real_build(root, sol, inv, tc, approved, repo_root):
    if not approved:
        return {"status": "NOT RUN", "detail": "restore downloads NuGet packages: run with --approve-downloads after the user said yes"}
    if not tc["msbuild"]:
        return {"status": "NOT RUN", "detail": "MSBuild not found on this machine; install Visual Studio Build Tools (needs the user's approval) and run again"}
    work = os.path.abspath(os.path.join(OUT, "build", "work", sol["repo"]))
    copy_repo(repo_root, work)
    target = os.path.join(work, sol["solution_file"]) if sol["solution_file"] else None
    if not target or not os.path.exists(target):
        return {"status": "NOT RUN", "detail": "no solution file to build"}
    started = time.time()
    if any(os.path.exists(os.path.join(dp, "packages.config")) for dp, _, fs in os.walk(work) if "packages.config" in fs) and not tc["nuget"]:
        return {"status": "NOT RUN", "detail": "the repo uses packages.config, which needs nuget.exe to restore; nuget.exe is not on this machine (download needs the user's approval)"}
    if tc["nuget"]:
        rc, rout = run([tc["nuget"], "restore", target, "-NonInteractive"], cwd=work, timeout=3600)
        if rc != 0:
            return {"status": "FAIL", "stage": "restore", "errors": [l.strip() for l in rout.splitlines() if l.strip()][-8:], "error_count": 1, "seconds": round(time.time() - started)}
    code, out = run([tc["msbuild"], target, "-restore", "-t:Build", "-p:Configuration=Release", "-m", "-nologo", "-v:minimal"], cwd=work, timeout=3600)
    errs = [l.strip() for l in out.splitlines() if ERROR.search(l)]
    return {"status": "PASS" if code == 0 else "FAIL", "stage": "build", "errors": sorted(set(errs))[:15], "error_count": len(set(errs)), "seconds": round(time.time() - started)}


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--toolchain", action="store_true")
    ap.add_argument("--run", action="store_true", help="real restore and build of a copy")
    ap.add_argument("--approve-downloads", action="store_true", help="the user approved the NuGet downloads of the restore")
    ap.add_argument("--solution", help="only this solution id")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    tc = toolchain()
    if a.toolchain:
        print(f"MSBuild: {tc['msbuild'] or 'NOT FOUND'}\nnuget.exe (optional): {tc['nuget'] or 'not found'}\ndotnet: {tc['dotnet'] or 'NOT FOUND'}\n"
              f".NET Framework targeting packs: {', '.join(tc['netfx_targeting_packs']) or 'none found'}")
        return
    import intake as _intake
    _intake.require(cfg, root, ["before_scan", "after_scan"], "build_check.py")
    idx = read_json(os.path.join(OUT, "solutions", "index.json"))
    if not idx:
        raise SystemExit("run solutions.py first")
    prev = {s["id"]: s for s in (read_json(os.path.join(OUT, "build", "index.json"), {}) or {}).get("solutions", [])}
    rows = []
    for s in idx["solutions"]:
        inv = read_json(os.path.join(OUT, "inventory", s["repo"] + ".json"))
        repo_root = inv["root"]
        status, issues, pre = static_check(repo_root, s, inv)
        old = prev.get(s["id"], {}).get("real", {"status": "NOT RUN", "detail": "not attempted yet"})
        real = old
        if a.run and (not a.solution or a.solution == s["id"]):
            real = real_build(root, s, inv, tc, a.approve_downloads, repo_root)
        rows.append({"id": s["id"], "static": {"status": status, "issues": issues, "prerequisites": pre}, "real": real})
    write_json(os.path.join(OUT, "build", "index.json"), {"toolchain": tc, "solutions": rows})
    mark_step(root, "build_static")
    if a.run:
        mark_step(root, "build_real", "done" if all(r["real"]["status"] in ("PASS", "FAIL") for r in rows) else "partial")
    for r in rows:
        print(f"{r['id']}: static {r['static']['status']} · real build {r['real']['status']}" + (f" ({r['real'].get('detail', '')})" if r["real"].get("detail") else ""))
        for i in r["static"]["issues"][:8]:
            print("    ISSUE " + i)
        for p in r["static"]["prerequisites"]:
            print("    needs " + p)
    if not any(r["real"]["status"] in ("PASS", "FAIL") for r in rows):
        print("REAL BUILD NOT RUN: it is mandatory before artifacts are produced. Ask the user to approve the NuGet downloads"
              + ("" if tc["msbuild"] else " and the install of Visual Studio Build Tools (MSBuild is not on this machine)") + ".")


if __name__ == "__main__":
    main()
