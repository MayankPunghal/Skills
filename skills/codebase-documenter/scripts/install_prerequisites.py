"""Check and install everything codebase-documenter (and migration-assessment, which builds on it) needs, at user level
(no admin rights, no system changes).

    python <skill>/scripts/install_prerequisites.py              # check, then install what is missing
    python <skill>/scripts/install_prerequisites.py --check      # report only; exit 1 if something required is missing
    python <skill>/scripts/install_prerequisites.py --no-dotnet  # never download the .NET SDK (SQL falls back to sqlglot)

Python itself cannot be installed from here (this script needs it): reference/install-prerequisites.md gives the
per-OS commands for that step. Runs from any folder; does not need codebase-docs.json.

Required:  Python 3.10+, pip, MkDocs Material (site), graphify (code graph; uv, else pip --user),
           sqlglot (SQL parser fallback + PostgreSQL preview; pip --user),
           .NET SDK 8+ (Microsoft's T-SQL parser for .sql files and SQL in C#; also Linux build checks in the
           assessment; installed per user with Microsoft's dotnet-install script), the ScriptDom helper (built once
           from scripts/sqlscan, restores one NuGet package from nuget.org)
Optional:  git (change detection, merge-risk analysis), Docker or WSL (assessment: real Linux builds), network access to
           api.nuget.org (assessment --online package facts), an LLM key in the environment (community naming)
"""
import argparse
import os
import platform
import shutil
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import run, tool_exe, utf8_stdout  # noqa: E402

GRAPHIFY_PKG = "graphifyy[sql,openai]"
SQLGLOT_PKG = "sqlglot"
KEY_VARS = ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
DOTNET_SCRIPT = {"nt": "https://dot.net/v1/dotnet-install.ps1", "posix": "https://dot.net/v1/dotnet-install.sh"}
REQUIRED = ("pip", "mkdocs-material", "graphify", "sqlglot", ".NET SDK 8+", "ScriptDom helper")
PY = [sys.executable]


def has_pip():
    return run(PY + ["-m", "pip", "--version"])[0] == 0


def has_module(*mods):
    return run(PY + ["-c", "import " + ", ".join(mods)])[0] == 0


def has_graphify():
    return run(["graphify", "--help"])[0] == 0


def sql_parse():
    import sql_parse as sp
    return sp


def pip_install(*pkgs):
    args = PY + ["-m", "pip", "install", "--upgrade", "--disable-pip-version-check"]
    if sys.prefix == sys.base_prefix:  # not a virtualenv: install for this user only
        args.append("--user")
    code, out = run(args + list(pkgs), timeout=1800)
    if code and "externally-managed" in out:
        print("  this Python is managed by the OS (PEP 668): create a virtual environment and rerun with its python:\n"
              "    python3 -m venv ~/.venvs/codebase-documenter && ~/.venvs/codebase-documenter/bin/python " + os.path.abspath(__file__))
    elif code:
        print(out[-1500:])
    return code == 0


def install_graphify():
    if not tool_exe("uv"):
        print("  installing uv (Python package manager used for graphify) ...")
        pip_install("uv")
    if tool_exe("uv") or run(PY + ["-m", "uv", "--version"])[0] == 0:
        uv = [tool_exe("uv")] if tool_exe("uv") else PY + ["-m", "uv"]
        code, out = run(uv + ["tool", "install", "--force", GRAPHIFY_PKG], timeout=1800)
        if code == 0:
            run(uv + ["tool", "update-shell"])  # adds the uv tool folder to PATH for future shells
            return True
        print(out[-1500:])
    print("  uv route failed; trying pip ...")
    return pip_install(GRAPHIFY_PKG)


def install_dotnet():
    """Current LTS .NET SDK for this user only, with Microsoft's official dotnet-install script (no admin, no MSI)."""
    url = DOTNET_SCRIPT["nt" if os.name == "nt" else "posix"]
    tmp = os.path.join(tempfile.gettempdir(), os.path.basename(url))
    print(f"  downloading {url} ...")
    try:
        urllib.request.urlretrieve(url, tmp)
    except OSError as ex:
        print(f"  download failed ({ex}); install the .NET SDK yourself: https://dotnet.microsoft.com/download")
        return False
    if os.name == "nt":
        target = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Microsoft", "dotnet")
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp, "-Channel", "LTS", "-InstallDir", target]
    else:
        target = os.path.join(os.path.expanduser("~"), ".dotnet")
        cmd = ["bash", tmp, "--channel", "LTS", "--install-dir", target]
    print(f"  installing the .NET SDK (LTS) into {target} (a few minutes) ...", flush=True)
    code, out = run(cmd, timeout=3600)
    if code:
        print(out[-1500:])
        return False
    if os.name == "nt":  # make it visible to new terminals: add the folder to the user PATH once
        cur = run(["powershell", "-NoProfile", "-Command", "[Environment]::GetEnvironmentVariable('Path','User')"])[1].strip()
        if target.lower() not in cur.lower():
            run(["powershell", "-NoProfile", "-Command",
                 f"[Environment]::SetEnvironmentVariable('Path', '{target};' + [Environment]::GetEnvironmentVariable('Path','User'), 'User')"])
    else:
        print(f"  add to your shell profile:  export DOTNET_ROOT={target}; export PATH=$PATH:{target}")
    return True


def nuget_reachable():
    try:
        with urllib.request.urlopen("https://api.nuget.org/v3/index.json", timeout=8):
            return True
    except OSError:
        return False


def report(verbose=True):
    sp = sql_parse()
    dm = sp.dotnet_major()
    ok_py = sys.version_info >= (3, 10)
    docker = tool_exe("docker") or tool_exe("podman")
    wsl = os.name == "nt" and run(["wsl", "--status"])[0] == 0
    rows = [("python 3.10+", ok_py, f"{sys.version.split()[0]} at {sys.executable}", True),
            ("pip", has_pip(), "", True),
            ("mkdocs-material", has_module("mkdocs", "material"), "documentation site", True),
            ("graphify", has_graphify(), tool_exe("graphify") or "code graph", True),
            ("sqlglot", sp.has_sqlglot() or has_module("sqlglot"), "SQL parser fallback, PostgreSQL preview", True),
            (".NET SDK 8+", dm >= sp.MIN_DOTNET, f"found {dm}" if dm else "Microsoft T-SQL parser; Linux build checks", True),
            ("ScriptDom helper", bool(sp.helper_dll()), sp.helper_dll() or "built from scripts/sqlscan on first use", True),
            ("git", bool(tool_exe("git")), "optional: change detection, merge-risk analysis", False),
            ("docker / WSL", bool(docker or wsl), "optional: real Linux builds in the assessment", False),
            ("api.nuget.org", nuget_reachable(), "optional: online package facts (assessment --online)", False)]
    keys = [k for k in KEY_VARS if os.environ.get(k)]
    if verbose:
        for name, ok, detail, required in rows:
            print(f"{'ok     ' if ok else ('MISSING' if required else 'absent ')}  {name:<17} {detail}")
        print(f"{'ok     ' if keys else 'absent '}  {'LLM key':<17} {', '.join(keys) if keys else 'optional: none set, communities keep generated names'}")
    return {name: ok for name, ok, _, _ in rows}


def offer_llm_key(no_prompt):
    """Suggest OpenRouter + GLM 5.3 Flash for community naming; optionally save a pasted key (user-level env)."""
    if any(os.environ.get(k) for k in KEY_VARS):
        return
    print("\nOptional: community naming uses an LLM. Recommended: OpenRouter + GLM 5.3 Flash (z-ai/glm-5.3-flash, cheap).")
    print("  Key: https://openrouter.ai/keys   Other providers and models: reference/build-code-graph.md (step 3).")
    if no_prompt or not sys.stdin.isatty():
        print("  Set it later:  setx OPENROUTER_API_KEY \"<key>\"  (Windows)   or  export OPENROUTER_API_KEY=<key>")
        return
    import getpass
    key = getpass.getpass("  Paste an OpenRouter key to save it (input hidden; Enter to skip): ").strip()
    if not key:
        print("  Skipped: communities will keep generated names until a key is set.")
        return
    if os.name == "nt":
        ok = run(["setx", "OPENROUTER_API_KEY", key])[0] == 0
        print("  Saved to your Windows user environment; new terminals will see it." if ok else "  Could not save it; set it with setx yourself.")
    else:
        print("  Add this line to your shell profile (~/.bashrc or ~/.zshrc), then open a new terminal:")
        print("    export OPENROUTER_API_KEY=<the key you pasted>")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only")
    ap.add_argument("--no-key-prompt", action="store_true", help="never ask for an LLM key")
    ap.add_argument("--no-dotnet", action="store_true", help="do not download the .NET SDK (SQL parsing falls back to sqlglot)")
    a = ap.parse_args()
    print(f"platform: {platform.system()} {platform.release()} ({platform.machine()})")
    state = report()
    if not state["python 3.10+"]:
        sys.exit("\nPython 3.10 or newer is required. Install it (reference/install-prerequisites.md), then rerun this script with it.")
    missing = [k for k in REQUIRED if not state[k]]
    if a.check or not missing:
        if not missing:
            print("\nREADY: all required prerequisites are installed.")
            if not a.check:
                offer_llm_key(a.no_key_prompt)
        sys.exit(1 if missing else 0)
    print(f"\ninstalling: {', '.join(missing)}")
    if "pip" in missing:
        run(PY + ["-m", "ensurepip", "--upgrade", "--user"], timeout=600)
    if "mkdocs-material" in missing:
        print("  mkdocs-material ...")
        pip_install("mkdocs-material")
    if "graphify" in missing:
        print("  graphify ...")
        install_graphify()
    if "sqlglot" in missing:
        print("  sqlglot ...")
        pip_install(SQLGLOT_PKG)
    if ".NET SDK 8+" in missing:
        if a.no_dotnet:
            print("  .NET SDK: skipped (--no-dotnet); SQL is parsed with sqlglot only (procedural T-SQL partly unparsed)")
        else:
            install_dotnet()
    sp = sql_parse()
    if not sp.helper_dll() and sp.dotnet_major() >= sp.MIN_DOTNET:
        print("  ScriptDom helper ...")
        sp.build(verbose=True)
    print()
    state = report()
    still = [k for k in REQUIRED if not state[k] and not (a.no_dotnet and k in (".NET SDK 8+", "ScriptDom helper"))]
    if still:
        sys.exit(f"\nNOT READY: {', '.join(still)} still missing; see the output above and reference/install-prerequisites.md.")
    offer_llm_key(a.no_key_prompt)
    print("\nREADY: all required prerequisites are installed."
          + ("" if shutil.which("graphify") else
             f"\nNote: graphify is installed at {tool_exe('graphify')} but not on this shell's PATH; the skill's scripts find it anyway. "
             "New terminals will see it after a restart."))


if __name__ == "__main__":
    main()
