"""Check and install everything codebase-documenter needs, at user level (no admin rights, no system changes).

    python <skill>/scripts/install_prerequisites.py            # check, then install what is missing
    python <skill>/scripts/install_prerequisites.py --check    # report only; exit 1 if something required is missing

Python itself cannot be installed from here (this script needs it): reference/install-prerequisites.md gives the
per-OS commands for that step. Runs from any folder; does not need codebase-docs.json.

Required:  Python 3.10+, pip, MkDocs Material (site), graphify (code graph; installed with uv, else pip --user)
Optional:  git (change detection, graphify hooks), an LLM key in the environment (community naming)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import run, tool_exe, utf8_stdout  # noqa: E402

GRAPHIFY_PKG = "graphifyy[sql,openai]"
KEY_VARS = ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
PY = [sys.executable]


def has_pip():
    return run(PY + ["-m", "pip", "--version"])[0] == 0


def has_mkdocs():
    return run(PY + ["-c", "import mkdocs, material"])[0] == 0


def has_graphify():
    return run(["graphify", "--help"])[0] == 0


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


def report():
    ok_py = sys.version_info >= (3, 10)
    rows = [("python 3.10+", ok_py, f"{sys.version.split()[0]} at {sys.executable}", True),
            ("pip", has_pip(), "", True),
            ("mkdocs-material", has_mkdocs(), "", True),
            ("graphify", has_graphify(), tool_exe("graphify") or "", True),
            ("git", bool(tool_exe("git")), "optional: change detection, graphify hooks", False)]
    keys = [k for k in KEY_VARS if os.environ.get(k)]
    for name, ok, detail, required in rows:
        print(f"{'ok     ' if ok else ('MISSING' if required else 'absent ')}  {name:<16} {detail}")
    print(f"{'ok     ' if keys else 'absent '}  {'LLM key':<16} {', '.join(keys) if keys else 'optional: none set, communities keep default names'}")
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
    a = ap.parse_args()
    state = report()
    if not state["python 3.10+"]:
        sys.exit("\nPython 3.10 or newer is required. Install it (reference/install-prerequisites.md), then rerun this script with it.")
    missing = [k for k in ("pip", "mkdocs-material", "graphify") if not state[k]]
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
    print()
    state = report()
    still = [k for k in ("pip", "mkdocs-material", "graphify") if not state[k]]
    if still:
        sys.exit(f"\nNOT READY: {', '.join(still)} still missing; see the output above and reference/install-prerequisites.md.")
    offer_llm_key(a.no_key_prompt)
    print("\nREADY: all required prerequisites are installed."
          + ("" if __import__("shutil").which("graphify") else
             f"\nNote: graphify is installed at {tool_exe('graphify')} but not on this shell's PATH; the skill's scripts find it anyway. "
             "New terminals will see it after a restart."))


if __name__ == "__main__":
    main()
