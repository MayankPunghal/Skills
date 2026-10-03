"""Install the codebase-documenter skill for Claude Code, then its prerequisites.

    python install.py                 # personal install: ~/.claude/skills/codebase-documenter (all projects)
    python install.py --project DIR   # project install: DIR/.claude/skills/codebase-documenter
    python install.py --check         # only check prerequisites
    python install.py --no-prereqs    # copy the skill only

Copies this folder (minus caches), then runs scripts/install_prerequisites.py, which installs MkDocs Material and
graphify at user level if they are missing. Needs Python 3.10+ (see reference/install-prerequisites.md if absent).
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "codebase-documenter"
PREREQS = os.path.join(HERE, "scripts", "install_prerequisites.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-prereqs", action="store_true")
    a = ap.parse_args()
    if sys.version_info < (3, 10):
        sys.exit(f"Python 3.10+ needed (this is {sys.version.split()[0]}); see reference/install-prerequisites.md")
    if a.check:
        sys.exit(subprocess.call([sys.executable, PREREQS, "--check"]))
    base = os.path.join(os.path.abspath(a.project), ".claude", "skills") if a.project else os.path.join(os.path.expanduser("~"), ".claude", "skills")
    dst = os.path.join(base, NAME)
    if os.path.abspath(dst) != HERE:
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"installed: {dst}")
    code = 0 if a.no_prereqs else subprocess.call([sys.executable, PREREQS])
    print(f"\nStart a new Claude Code session and type /{NAME} (or ask: 'document this codebase')."
          + ("" if code == 0 else "\nPrerequisites are incomplete; the skill will offer install-prerequisites first."))


if __name__ == "__main__":
    main()
