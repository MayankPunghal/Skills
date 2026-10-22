"""Check what the lift-and-shift track of modernization-assessment needs on this machine, and install the one optional Python package at user level.

    python <skill>/scripts/install_prerequisites.py            # check, then pip install --user what is missing (pymupdf)
    python <skill>/scripts/install_prerequisites.py --check    # report only; exit 1 if something required is missing

Required:  Python 3.10+, git (core.longpaths on Windows).
For the real build (build_check.py --run): MSBuild from Visual Studio Build Tools with the web development build tools, and the .NET
           SDKs the solutions target. These are NEVER installed from here: installing Build Tools is asked first (SKILL.md). NuGet
           packages, nuget.exe and the old .NET Framework reference-assembly packs are fetched by build_check.py itself.
Optional:  pymupdf (pip --user) plus Microsoft Word on Windows: page numbers in the branded document's table of contents (otherwise
           Word fills them in when the file is opened); a GitLab read token in the environment variable named in assessment.json
           (gitlab_projects.py, clone_repos.py, branch_evidence.py); network access to api.nuget.org (package licences).
Runs from any folder; does not need assessment.json, except to say whether the GitLab token variable is set (never its value).
"""
import argparse
import importlib.util
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_config, run, tool_exe, utf8_stdout  # noqa: E402


def word_installed():
    if os.name != "nt":
        return False
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        for ver in ("root\\Office16", "Office16", "root\\Office15", "Office15"):
            if os.path.exists(os.path.join(base, "Microsoft Office", ver, "WINWORD.EXE")):
                return True
    return False


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only; install nothing")
    a = ap.parse_args()
    rows, missing = [], []

    def line(ok, what, note=""):
        rows.append(f"  {'OK  ' if ok else 'MISS'} {what}" + (f": {note}" if note else ""))

    py_ok = sys.version_info >= (3, 10)
    line(py_ok, f"Python {sys.version.split()[0]}", "" if py_ok else "3.10 or newer is required")
    if not py_ok:
        missing.append("python")
    git = tool_exe("git")
    line(bool(git), "git", git or "install git and put it on PATH")
    if not git:
        missing.append("git")
    elif os.name == "nt":
        code, out = run([git, "config", "--global", "core.longpaths"], timeout=20)
        line(out.strip().lower() == "true", "git core.longpaths", "" if out.strip().lower() == "true" else "clone_repos.py passes it per command; set it globally with: git config --global core.longpaths true")
    from build_check import toolchain  # noqa: E402  (imported late: it reads the Visual Studio installer)
    tc = toolchain()
    line(bool(tc["msbuild"]), "MSBuild (real build)", tc["msbuild"] or "Visual Studio Build Tools with the web development build tools; ask the user before installing")
    line(bool(tc["dotnet"]), "dotnet SDK", tc["dotnet"] or "needed for SDK-style projects; ask the user before installing")
    line(True, ".NET Framework targeting packs", ", ".join(tc["netfx_targeting_packs"]) or "none: build_check.py --run fetches reference-assembly packs (standing approval)")
    has_mu = importlib.util.find_spec("pymupdf") is not None or importlib.util.find_spec("fitz") is not None
    if not has_mu and not a.check:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--user", "--quiet", "pymupdf"], capture_output=True, text=True)
        has_mu = r.returncode == 0
        if not has_mu:
            rows.append("  note: pip install --user pymupdf failed: " + (r.stderr.strip().splitlines() or ["no output"])[-1][:200])
    line(has_mu, "pymupdf (optional)", "" if has_mu else "table-of-contents page numbers fall back to Word's own update on open")
    line(word_installed(), "Microsoft Word (optional)", "" if word_installed() else "without it the table of contents is updated when the file is opened")
    root, cfg = load_config(required=False)
    if root:
        name = ((cfg.get("gitlab") or {}).get("token_env") or "GITLAB_TOKEN")
        have = bool(os.environ.get(name))
        if not have and os.name == "nt":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                    have = bool(winreg.QueryValueEx(k, name)[0])
            except OSError:
                have = False
        line(have, f"GitLab token variable {name} (optional)", "" if have else "needed only for gitlab_projects.py, clone_repos.py, branch_evidence.py")
    print("lift-and-shift track prerequisites:\n" + "\n".join(rows))
    if missing:
        print("REQUIRED MISSING: " + ", ".join(missing))
        sys.exit(1)


if __name__ == "__main__":
    main()
