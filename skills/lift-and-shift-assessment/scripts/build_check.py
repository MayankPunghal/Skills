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

from _common import skip_dir, OUT, SOURCE_DIR_SKIP, load_config, mark_step, read_json, run, slug, tool_exe, utf8_stdout, write_json
import intake as I
import _buildfix as BF

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


REF_ASM = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Reference Assemblies", "Microsoft", "Framework", ".NETFramework")
CACHE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "lift-and-shift-assessment")
PACK_VERSION = "1.0.3"
TFV = re.compile(r"<TargetFrameworkVersion>\s*(v\d(?:\.\d)+)\s*</TargetFrameworkVersion>", re.I)


def pack_installed(ver):
    """True when this machine has the real reference assemblies for .NET Framework `ver` (some installs keep only the .xml files)."""
    return os.path.exists(os.path.join(REF_ASM, ver, "mscorlib.dll"))


def needed_frameworks(work):
    found = set()
    for dp, dn, fs in os.walk(work):
        dn[:] = [d for d in dn if not skip_dir(dp, d, ("packages", "node_modules", "bin", "obj"), fold=False)]
        for f in fs:
            if f.lower().endswith((".csproj", ".vbproj")):
                found.update(v.lower() for v in TFV.findall(project_text(os.path.join(dp, f)) or ""))
            elif f.lower().endswith(".sln"):
                text = project_text(os.path.join(dp, f)) or ""
                found.update(v.lower() for v in re.findall(r"Version%3D(v\d(?:\.\d)+)", text))
                if "E24C65DC-7377-472B-9ABA-BC803B73C61A" in text.upper():
                    found.add("v4.0")  # a Web Site project: MSBuild wraps it in a .metaproj that targets 4.0
    return sorted(found)


def ensure_nuget(tc, approved):
    """nuget.exe: on PATH, else the tool cache; downloaded into the cache under the NuGet download approval (never installed system-wide)."""
    if tc["nuget"] or not approved:
        return tc["nuget"]
    exe = os.path.join(CACHE, "tools", "nuget.exe")
    if not os.path.exists(exe):
        import urllib.request
        os.makedirs(os.path.dirname(exe), exist_ok=True)
        urllib.request.urlretrieve("https://dist.nuget.org/win-x86-commandline/latest/nuget.exe", exe)
    tc["nuget"] = exe
    return exe


def framework_root(versions, tc):
    """A TargetFrameworkRootPath that holds every .NET Framework version the solution needs: the installed packs by junction, the missing old
    ones (4.0 to 4.6.2) from the Microsoft.NETFramework.ReferenceAssemblies NuGet packages, downloaded into the tool cache (no installer, no admin;
    delete the folder to remove). Returns (root or None, versions that could not be provided)."""
    missing = [v for v in versions if not pack_installed(v)]
    if not missing:
        return None, []
    root = os.path.join(CACHE, "netfx-root")
    pkgs = os.path.join(CACHE, "netfx-packs")
    failed = []
    for v in versions:
        dest = os.path.join(root, ".NETFramework", v)
        if os.path.exists(os.path.join(dest, "mscorlib.dll")):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if pack_installed(v):
            if not os.path.exists(dest):
                code, _ = run(["cmd", "/c", "mklink", "/J", dest, os.path.join(REF_ASM, v)], timeout=60)
                if code != 0:
                    shutil.copytree(os.path.join(REF_ASM, v), dest)
            continue
        pid = "Microsoft.NETFramework.ReferenceAssemblies.net" + v[1:].replace(".", "")
        src = os.path.join(pkgs, f"{pid}.{PACK_VERSION}", "build", ".NETFramework", v)
        if not os.path.exists(os.path.join(src, "mscorlib.dll")) and tc["nuget"]:
            run([tc["nuget"], "install", pid, "-Version", PACK_VERSION, "-OutputDirectory", pkgs, "-NonInteractive"], timeout=1800)
        if os.path.exists(os.path.join(src, "mscorlib.dll")):
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            failed.append(v)
    return root + os.sep, failed


def project_text(path):
    try:
        return open(path, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return None


def _sibling(root, resolved):
    """Top-level folder beside the repository that holds a referenced file (the shared library folder, another repo), or None."""
    group = os.path.dirname(root)
    rel = os.path.relpath(resolved, group)
    return None if rel.startswith("..") else rel.replace("\\", "/").split("/")[0]


STAGE = {"dir": None, "aliases": {}}  # optional folder that acts as the group folder (Library, DLL Cache ...) when the sibling checkout has a different layout


def _staged(rel):
    """Path inside the staging folder for a repo-relative path (e.g. Library/filemanager/x.dll), or None."""
    if not STAGE["dir"]:
        return None
    p = os.path.join(STAGE["dir"], rel.replace("/", os.sep))
    return p if os.path.exists(p) else None


def static_check(root, sol, inv):
    """Issues and prerequisites for one solution from its files. Returns (status, issues, prerequisites, siblings)."""
    by_path = {p["path"]: p for p in inv.get("projects", [])}
    issues, pre, siblings = [], set(), {}
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
            hl = h.replace("\\", "/").lower()
            if re.match(r"^[A-Za-z]:[\\/]", h) or h.startswith("\\\\"):
                if "reference assemblies" in hl or "/windows/" in hl:
                    pre.add("the .NET Framework targeting pack (the project points at it by absolute path)")
                else:
                    issues.append(f"{p['name']}: reference outside the repository ({os.path.basename(h)} at an absolute path)")
            elif "/packages/" in hl or hl.startswith(("packages/", "../packages")):
                continue  # NuGet restore creates it
            elif os.path.exists(resolved):
                outside = os.path.relpath(resolved, root)
                if outside.startswith(".."):
                    sib = _sibling(root, resolved)
                    if sib:
                        siblings.setdefault(sib, set()).add(os.path.relpath(resolved, os.path.dirname(root)).replace("\\", "/"))
            elif _staged(os.path.relpath(resolved, os.path.dirname(root)).replace(chr(92), "/")):
                rel = os.path.relpath(resolved, os.path.dirname(root)).replace(chr(92), "/")
                siblings.setdefault(rel.split("/")[0], set()).add(rel)
                top = "/".join(rel.split("/")[:2])
                if top in STAGE["aliases"]:
                    pre.add(f"{rel.split('/')[0]}: '{top}' is not at that path in the current repository; tested with the path pointed at {STAGE['aliases'][top]}")
            elif re.search(r"/bin/(debug|release)/", hl):
                pre.add(f"build order: {p['name']} reads {os.path.basename(h)} from another project's bin folder; that project must be built first, and the build runs in Debug")
            else:
                issues.append(f"{p['name']}: reference DLL not found ({os.path.basename(h)} expected at {os.path.relpath(resolved, os.path.dirname(root)).replace(chr(92), '/')})")
        for r in PROJREF.findall(text):
            if not os.path.exists(os.path.normpath(os.path.join(base, r.replace("\\", os.sep)))):
                issues.append(f"{p['name']}: project reference {r} not found")
        for i in IMPORT.findall(text):
            if "WebApplication.targets" in i or "WebPublishing" in i:
                pre.add("Visual Studio Build Tools: Web development build tools (WebApplication.targets)")
        fw = ",".join(p.get("frameworks") or [])
        if p.get("family") == "netfx":
            fw = re.sub(r"\bnet(4)(\d)(\d)?\b(?!\.)", lambda m: ".".join(g for g in m.groups() if g), fw)  # SDK-style monikers (net472) -> 4.7.2
            pre.add("Visual Studio Build Tools: MSBuild + .NET Framework " + (fw.replace("v", "") or "targeting pack"))
            if os.path.exists(os.path.join(base, "packages.config")):
                pre.add("NuGet restore of packages.config: nuget.exe (msbuild -restore skips packages.config projects) and access to the NuGet feed")
        else:
            pre.add("dotnet SDK for " + (fw or "the target framework"))
            pre.add("restore: access to the NuGet feed")
    for sib, files in sorted(siblings.items()):
        pre.add(f"repository folder '{sib}' checked out beside this repository ({len(files)} referenced file(s), e.g. {sorted(files)[0]})")
    status = "BLOCKED" if issues else "PREREQUISITES" if pre else "READY"
    return status, sorted(set(issues)), sorted(pre), {k: sorted(v) for k, v in siblings.items()}


def copy_repo(src, dst):
    if os.path.exists(dst):
        return
    skip = shutil.ignore_patterns(".git", "bin", "obj", "node_modules", ".vs")  # not "packages": a source folder can have that name, and a committed NuGet folder is harmless
    shutil.copytree(src, dst, ignore=skip)


def build_configuration(work, sol):
    """Debug when a project reads another project's output from a bin/Debug folder (a Release build would not find it), else Release."""
    for p in sol["projects"]:
        text = project_text(os.path.join(work, p["path"])) or ""
        if any(re.search(r"(?i)[\\/]bin[\\/]debug[\\/]", h) for h in HINT.findall(text)):
            return "Debug"
    return "Release"


def stage_siblings(siblings, repo_root, work):
    """Copy the files a repository references outside itself (e.g. ..\\..\\Library\\x.dll) next to the build copy, in the same relative layout.
    Only the referenced files and the files beside them are copied; the client folders are only read."""
    src_group, dst_group = os.path.dirname(repo_root), os.path.dirname(work)
    n = 0
    for files in siblings.values():
        for rel in files:
            src = os.path.join(src_group, rel.replace("/", os.sep))
            if not os.path.exists(src) and _staged(rel):
                src = _staged(rel)
            dst = os.path.join(dst_group, rel.replace("/", os.sep))
            for f in os.listdir(os.path.dirname(src)):
                fs, fd = os.path.join(os.path.dirname(src), f), os.path.join(os.path.dirname(dst), f)
                if os.path.isfile(fs) and not os.path.exists(fd):
                    os.makedirs(os.path.dirname(fd), exist_ok=True)
                    shutil.copy2(fs, fd)
                    n += 1
    return n


def restore_hint_packages(work, tc):
    """Projects that point at a local packages folder (HintPath or Import: packages\\Id.1.2.3\\... one level or more above the project) that is not in
    the repository: install exactly that package version from NuGet into that folder. Returns the packages restored (NuGet downloads only, the standing approval)."""
    rx = re.compile(r"(?i)((?:\.\.[\\/])+)packages[\\/]([A-Za-z0-9_\-]+(?:\.[A-Za-z_][A-Za-z0-9_\-]*)*)\.(\d+(?:\.\d+){1,3}(?:-[A-Za-z0-9.\-]+)?)[\\/]")
    wanted = {}
    for dp, dn, fs in os.walk(work):
        dn[:] = [d for d in dn if d not in (".git", "node_modules", "bin", "obj")]
        for f in fs:
            if f.lower().endswith((".csproj", ".vbproj", ".props", ".targets")):
                try:
                    text = open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                for m in rx.finditer(text):
                    pkgdir = os.path.abspath(os.path.join(dp, m.group(1).replace("/", os.sep), "packages"))
                    wanted[(pkgdir, m.group(2), m.group(3))] = True
    done = []
    for pkgdir, pid, ver in sorted(wanted):
        if os.path.isdir(os.path.join(pkgdir, f"{pid}.{ver}")) or not tc.get("nuget"):
            continue
        os.makedirs(pkgdir, exist_ok=True)
        rc, _ = run([tc["nuget"], "install", pid, "-Version", ver, "-OutputDirectory", pkgdir, "-NonInteractive"], cwd=work, timeout=1800)
        if rc == 0:
            done.append(f"{pid} {ver}")
    return done


def work_base(root):
    """Where the build copies go. Default assessment/build/work. MSBuild tools such as SGEN still fail on Windows paths over 260 characters,
    and a deep workspace (a temp or OneDrive folder) plus a deep repository breaks the build for no reason of the client's. So when the
    workspace path is long, the copies go to a short folder in the tool cache instead (%LOCALAPPDATA%/lsa/<6-character id of the
    workspace>); assessment.json -> build_work_dir overrides both. build/index.json records the folder used."""
    cfg = read_json(os.path.join(root, "assessment.json"), {}) or {}
    if (cfg.get("build_work_dir") or "").strip():
        return os.path.abspath(cfg["build_work_dir"])
    default = os.path.abspath(os.path.join(root, OUT, "build", "work"))
    if os.name == "nt" and len(default) > 60:
        import hashlib
        tag = hashlib.sha1(os.path.abspath(root).lower().encode()).hexdigest()[:6]
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "lsa", tag)
    return default


def real_build(root, sol, inv, tc, approved, repo_root, siblings=None):
    if not approved:
        return {"status": "NOT RUN", "detail": "restore downloads NuGet packages: run with --approve-downloads after the user said yes"}
    if not tc["msbuild"]:
        return {"status": "NOT RUN", "detail": "MSBuild not found on this machine; install Visual Studio Build Tools (needs the user's approval) and run again"}
    work = os.path.join(work_base(root), sol["repo"])
    copy_repo(repo_root, work)
    if siblings:
        stage_siblings(siblings, repo_root, work)
    target = os.path.join(work, sol["solution_file"]) if sol["solution_file"] else None
    if not target or not os.path.exists(target):
        return {"status": "NOT RUN", "detail": "no solution file to build"}
    started = time.time()
    config = build_configuration(work, sol)
    ensure_nuget(tc, approved)
    if any(os.path.exists(os.path.join(dp, "packages.config")) for dp, _, fs in os.walk(work) if "packages.config" in fs) and not tc["nuget"]:
        return {"status": "NOT RUN", "detail": "the repo uses packages.config, which needs nuget.exe to restore; nuget.exe is not on this machine (download needs the user's approval)"}
    if tc["nuget"]:
        rc, rout = run([tc["nuget"], "restore", target, "-NonInteractive"], cwd=work, timeout=3600)
        if rc != 0:
            return {"status": "FAIL", "stage": "restore", "errors": [l.strip() for l in rout.splitlines() if l.strip()][-8:], "error_count": 1, "seconds": round(time.time() - started)}
    restored = restore_hint_packages(work, tc)
    fw_root, fw_failed = framework_root(needed_frameworks(work), tc)
    extra = [f"-p:TargetFrameworkRootPath={fw_root}"] if fw_root else []
    workarounds, props = [], []
    for _round in range(8):  # a failed build may be fixable in the copy (see _buildfix.py); fix, then build again
        code, out = run([tc["msbuild"], target, "-restore", "-t:Build", f"-p:Configuration={config}", *extra, *props, "-m", "-nologo", "-v:minimal"], cwd=work, timeout=3600)
        errs = [l.strip() for l in out.splitlines() if ERROR.search(l)]
        if code == 0 or not errs or all("MSB3644" in e for e in errs):
            break
        fixed, new_props = BF.autofix(work, out, tc)
        if not fixed and not new_props:
            break
        workarounds += fixed
        props += new_props
    if code != 0 and errs and all("MSB3644" in e for e in errs):
        return {"status": "NOT RUN", "detail": "the .NET Framework reference assemblies for " + ", ".join(fw_failed or needed_frameworks(work)) + " are not on this machine and could not be fetched; the build says nothing about the code"}
    res = {"status": "PASS" if code == 0 else "FAIL", "stage": "build", "configuration": config, "errors": sorted(set(errs))[:15], "error_count": len(set(errs)), "seconds": round(time.time() - started), "packages_installed": restored}
    if workarounds:
        res["workarounds"] = workarounds  # PASS plus workarounds = a contingent pass; FAIL plus workarounds = what was tried
    return res


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--toolchain", action="store_true")
    ap.add_argument("--run", action="store_true", help="real restore and build of a copy")
    ap.add_argument("--approve-downloads", action="store_true", help="the user approved the NuGet downloads: packages, nuget.exe and the old .NET Framework reference-assembly packages (tool cache only)")
    ap.add_argument("--solution", help="only this solution id")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    tc = toolchain()
    STAGE["dir"] = cfg.get("library_stage")
    if STAGE["dir"] and os.path.exists(os.path.join(STAGE["dir"], "aliases.json")):
        STAGE["aliases"] = read_json(os.path.join(STAGE["dir"], "aliases.json"), {}) or {}
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
    statics = {}
    for s in idx["solutions"]:
        inv = read_json(os.path.join(OUT, "inventory", s["repo"] + ".json"))
        statics[s["id"]] = (inv, inv["root"]) + static_check(inv["root"], s, inv)
    reals = {}
    todo = [s for s in idx["solutions"] if a.run and (not a.solution or a.solution == s["id"])]
    todo.sort(key=lambda s: any("build order" in p for p in statics[s["id"]][4]))  # a solution that reads another repository's bin output is built after the others
    for s in todo:
        inv, repo_root, status, issues, pre, siblings = statics[s["id"]]
        reals[s["id"]] = real_build(root, s, inv, tc, a.approve_downloads, repo_root, siblings)
    rows = []
    for s in idx["solutions"]:
        inv, repo_root, status, issues, pre, siblings = statics[s["id"]]
        real = reals.get(s["id"]) or prev.get(s["id"], {}).get("real", {"status": "NOT RUN", "detail": "not attempted yet"})
        rows.append({"id": s["id"], "static": {"status": status, "issues": issues, "prerequisites": pre, "sibling_folders": siblings}, "real": real})
    write_json(os.path.join(OUT, "build", "index.json"), {"toolchain": tc, "work_dir": work_base(root), "solutions": rows})
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
