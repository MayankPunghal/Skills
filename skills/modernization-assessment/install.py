"""Install the migration-assessment skill (and the codebase-documenter skill it builds on) for Claude Code.

    python install.py                 # personal install: ~/.claude/skills/ (all projects)
    python install.py --project DIR   # project install: DIR/.claude/skills/
    python install.py --check         # only check prerequisites
    python install.py --no-prereqs    # copy only

Copies this folder, and a sibling ../codebase-documenter folder when present (the package ships both), then runs the
codebase-documenter prerequisite installer (MkDocs Material, graphify at user level). Needs Python 3.10+.
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "migration-assessment"
SIBLING = os.path.join(os.path.dirname(HERE), "codebase-documenter")


def copy(src, base, name):
    dst = os.path.join(base, name)
    if os.path.abspath(dst) != os.path.abspath(src):
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"installed: {dst}")
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-prereqs", action="store_true")
    a = ap.parse_args()
    if sys.version_info < (3, 10):
        sys.exit(f"Python 3.10+ needed (this is {sys.version.split()[0]}).")
    base = os.path.join(os.path.abspath(a.project), ".claude", "skills") if a.project else os.path.join(os.path.expanduser("~"), ".claude", "skills")
    doc = SIBLING if os.path.exists(os.path.join(SIBLING, "SKILL.md")) else os.path.join(base, "codebase-documenter")
    prereq = os.path.join(doc, "scripts", "install_prerequisites.py")
    if a.check:
        if not os.path.exists(prereq):
            sys.exit("codebase-documenter not found next to this folder or in the skills folder: install it first.")
        sys.exit(subprocess.call([sys.executable, prereq, "--check"]))
    os.makedirs(base, exist_ok=True)
    copy(HERE, base, NAME)
    if os.path.exists(os.path.join(SIBLING, "SKILL.md")):
        doc = copy(SIBLING, base, "codebase-documenter")
        prereq = os.path.join(doc, "scripts", "install_prerequisites.py")
    elif not os.path.exists(prereq):
        print("WARNING: codebase-documenter is not installed; install it for prerequisites and documentation features.")
    code = 0 if a.no_prereqs or not os.path.exists(prereq) else subprocess.call([sys.executable, prereq])
    print(f"\nStart a new Claude Code session and type /{NAME} (or ask: 'assess this .NET code base for AWS migration')."
          + ("" if code == 0 else "\nPrerequisites are incomplete; context.py will list what is missing."))


if __name__ == "__main__":
    main()
