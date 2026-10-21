"""Workarounds for a failed build, applied to the BUILD COPY only (assessment/build/work/<repo>); a client repository is never changed.

autofix(work, out, tc) reads the MSBuild output of a failed build, fixes what is safe to fix in the copy and returns what it did, so the build
can run again. A solution that then passes is a "contingent pass": it builds only with these workarounds, and the workbook (sheet Build) says
which files are missing from the repository and what we did instead.

Handled (each one is recorded as {kind, item, action}):
  - Properties\\AssemblyInfo.cs listed in the project but not in the repository: recreated as a stub (assembly name and version only).
  - A project listed in the .sln but not in the repository: removed from the solution in the copy.
  - A content file listed in the project but not in the repository: an empty placeholder, so the copy step of the build passes.
  - DocumentationFile on a fixed drive that does not exist here (for example D:\\Projects\\...): pointed at bin\\.
  - A wildcard assembly version (1.0.*) that the current compiler refuses in a deterministic build: the property Deterministic=false.
  - A reference to another repository's bin\\Debug output (build order across repositories): copied from the other repository's build copy.
  - An Office COM reference (Outlook, Excel, Word, PowerPoint) that is not registered here: the primary interop assembly from NuGet instead.
"""
import os
import re
import shutil
import subprocess


def nuget_folder(path):
    """A restored NuGet packages folder (repositories.config, or packages/<Id>.<version>/*.nupkg), not application source in a folder named Packages."""
    try:
        if os.path.exists(os.path.join(path, "repositories.config")):
            return True
        for sub in os.listdir(path)[:8]:
            q = os.path.join(path, sub)
            if os.path.isdir(q) and any(f.lower().endswith(".nupkg") for f in os.listdir(q)):
                return True
    except OSError:
        pass
    return False


def skip_dir(parent, name, skip, fold=True):
    """True when a walk should not enter folder `name` under `parent`: its name is in `skip`. A folder named packages is skipped only when it
    is a NuGet restore folder: application source can live in a folder of that name."""
    if name.lower() == "packages":
        return "packages" in skip and nuget_folder(os.path.join(parent, name))
    return (name.lower() if fold else name) in skip

GIF = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")
ASSEMBLYINFO = """using System.Reflection;
using System.Runtime.InteropServices;

[assembly: AssemblyTitle("{n}")]
[assembly: AssemblyProduct("{n}")]
[assembly: ComVisible(false)]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
"""
OFFICE_PIA = {"Outlook": "Microsoft.Office.Interop.Outlook", "Excel": "Microsoft.Office.Interop.Excel", "Word": "Microsoft.Office.Interop.Word", "PowerPoint": "Microsoft.Office.Interop.PowerPoint"}


def _inside(path, work):
    try:
        return os.path.commonpath([os.path.abspath(path), work]) == work
    except ValueError:
        return False


def _rel(path, work):
    return os.path.relpath(path, work).replace("/", "\\")


def _read(p):
    return open(p, encoding="utf-8-sig", errors="replace").read()


def _write(p, s):
    open(p, "w", encoding="utf-8").write(s)


def autofix(work, out, tc):
    work = os.path.abspath(work)
    workroot = os.path.dirname(work)
    fixes, props = [], []

    def add(kind, item, action):
        fixes.append({"kind": kind, "item": item, "action": action})

    # 1. Properties\AssemblyInfo.cs
    for m in re.finditer(r"error CS2001: Source file '([^']+)' could not be found[^\n]*?(?:\[([^\]\n]+)\])?\s*$", out, re.M):
        path = m.group(1)
        if path.lower().endswith("assemblyinfo.cs") and _inside(path, work) and not os.path.exists(path):
            name = os.path.splitext(os.path.basename(m.group(2) or ""))[0] or "Assembly"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _write(path, ASSEMBLYINFO.format(n=name))
            add("file missing from the repository", _rel(path, work), "recreated as a stub (assembly name and version only)")

    # 2. project listed in the solution but not in the repository
    for m in re.finditer(r'The project file "([^"]+)" was not found', out):
        base = os.path.basename(m.group(1))
        for dp, dn, fs in os.walk(work):
            dn[:] = [d for d in dn if not skip_dir(dp, d, (".git", "node_modules", "bin", "obj", "packages"), fold=False)]
            for f in fs:
                if not f.lower().endswith(".sln"):
                    continue
                sp = os.path.join(dp, f)
                text = _read(sp)
                pm = re.search(r'Project\("\{[^}]+\}"\) = "[^"]*", "([^"]*%s)", "(\{[^}]+\})"\r?\nEndProject\r?\n' % re.escape(base), text, re.I)
                if pm:
                    text = text.replace(pm.group(0), "")
                    text = "\n".join(l for l in text.split("\n") if pm.group(2) not in l)
                    _write(sp, text)
                    add("project missing from the repository", pm.group(1), f"listed in {f} but not in the repository; removed from the solution in the build copy")

    # 3. content file listed in the project, not in the repository
    for m in re.finditer(r'error MSB3030: Could not copy the file "([^"]+)" because it was not found', out):
        path = m.group(1)
        if _inside(path, work) and not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").write(GIF if path.lower().endswith(".gif") else b"")
            add("file missing from the repository", _rel(path, work), "listed as content in the project; placeholder created so the copy step passes")

    # 4. DocumentationFile on a fixed drive
    for m in re.finditer(r"error CS0016: Could not write to output file '([A-Za-z]:\\[^']+)'", out):
        target = m.group(1)
        for dp, dn, fs in os.walk(work):
            dn[:] = [d for d in dn if not skip_dir(dp, d, (".git", "node_modules", "bin", "obj", "packages"), fold=False)]
            for f in fs:
                if f.lower().endswith(".csproj"):
                    p = os.path.join(dp, f)
                    text = _read(p)
                    if target.lower() in text.lower():
                        text = re.sub(re.escape(target), "bin\\\\" + os.path.basename(target).replace("\\", "\\\\"), text, flags=re.I)
                        _write(p, text)
                        add("setting points outside the repository", _rel(p, work), f"DocumentationFile pointed at {target[:2]}\\... (a fixed drive); changed to bin\\")

    # 5. wildcard assembly version
    m = re.search(r"([^\s(]+\.cs)\(\d+,\d+\): error CS8357", out)
    if m and "-p:Deterministic=false" not in props:
        props.append("-p:Deterministic=false")
        add("build setting", _rel(m.group(1), work) if _inside(m.group(1), work) else os.path.basename(m.group(1)), "assembly version has a wildcard (1.0.*); build property Deterministic=false on the build agent")

    # 6. another repository's bin output (build order across repositories)
    for dp, dn, fs in os.walk(work):
        dn[:] = [d for d in dn if not skip_dir(dp, d, (".git", "node_modules", "bin", "obj", "packages"), fold=False)]
        for f in fs:
            if not f.lower().endswith(".csproj"):
                continue
            for hint in re.findall(r"<HintPath>([^<]+)</HintPath>", _read(os.path.join(dp, f)), re.I):
                if not re.search(r"(?i)[\\/]bin[\\/](debug|release)[\\/]", hint) or not hint.startswith(".."):
                    continue
                resolved = os.path.normpath(os.path.join(dp, hint.replace("\\", os.sep)))
                if os.path.exists(resolved) or not _inside(resolved, workroot):
                    continue
                rel = os.path.relpath(resolved, workroot).split(os.sep)
                if len(rel) < 5 or rel[0] == os.path.basename(work):
                    continue
                proj, tail = rel[1], rel[2:]
                for other in sorted(os.listdir(workroot)):
                    src = os.path.join(workroot, other, proj, *tail[:-1])
                    if other != rel[0] and os.path.isdir(src) and os.path.exists(os.path.join(src, tail[-1])):
                        dst = os.path.dirname(resolved)
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                        add("another repository's build output", "\\".join(rel[:2] + tail), f"output of {other}\\{proj} copied from that repository's build copy (build order: that repository must be built first)")
                        break

    # 7. Office COM reference
    for m in re.finditer(r"error CS0234: The type or namespace name '(\w+)' does not exist in the namespace 'Microsoft\.Office\.Interop'[^\n]*\[([^\]\n]+\.csproj)\]", out):
        name, proj = m.group(1), m.group(2)
        pkg = OFFICE_PIA.get(name)
        nuget = tc.get("nuget")
        if not pkg or not nuget or not os.path.exists(proj):
            continue
        text = _read(proj)
        cm = re.search(r'\s*<COMReference Include="Microsoft\.Office\.Interop\.%s">.*?</COMReference>' % name, text, re.S)
        if not cm:
            continue
        pdir = os.path.join(work, "packages")
        os.makedirs(pdir, exist_ok=True)
        subprocess.run([nuget, "install", pkg, "-OutputDirectory", pdir, "-NonInteractive"], capture_output=True, text=True, timeout=1800)
        dlls = [os.path.join(dp, f) for dp, _, fs in os.walk(pdir) for f in fs if f.lower() == pkg.lower() + ".dll" and os.sep + "net" in dp.lower()]
        dlls.sort(key=lambda x: (("net20" not in x.lower()), x))
        if not dlls:
            continue
        hp = os.path.relpath(dlls[0], os.path.dirname(proj))
        ref = f'\n    <Reference Include="{pkg}">\n      <HintPath>{hp}</HintPath>\n      <EmbedInteropTypes>False</EmbedInteropTypes>\n    </Reference>'
        _write(proj, text.replace(cm.group(0), ref))
        add("COM reference not available on the build agent", _rel(proj, work), f"COM reference to Office {name} replaced by the NuGet primary interop assembly {pkg}; the application still needs Office {name} at run time")
    return fixes, props
