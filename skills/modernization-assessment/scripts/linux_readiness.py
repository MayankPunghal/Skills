"""Linux readiness check (run, do not read): a thin entry point to the linux-readiness skill, which owns the scanner.

    python scripts/linux_readiness.py <repo-or-solution-folder> [--out <dir>] [--waivers waivers.json]
                                      [--level block|warn|info] [--gate] [--title NAME]
    python scripts/linux_readiness.py --all    (in an assessment workspace: every inventoried repository,
                                                output to assessment/linux/<repo>/)
    python scripts/linux_readiness.py <folder-or-Dockerfile> --dockerfile-only [--out <dir>] [--gate]
    python scripts/linux_readiness.py --explain [LNX-ID | id prefix | words]   (no scan: what a check looks for and why)

The scanner and its catalogue (scripts/data/linux_readiness.json, 337 checks) exist once, in the linux-readiness
skill; this file finds that skill and runs it, so the skills that use the check cannot drift apart. Options and
output are the linux-readiness skill's (its reference/linux-readiness.md).

Where it looks, in order: the LINUX_READINESS_DIR environment variable, a sibling folder named linux-readiness (the
installer puts it next to this skill), ~/.claude/skills/linux-readiness, ~/.agents/skills/linux-readiness.
Imported as a module, it exposes the scanner's functions (scan, render, load_rules, ...). Standard library only.
"""
import importlib.util
import os

_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def skill_dir():
    """The linux-readiness skill folder, or None."""
    home = os.path.expanduser("~")
    for d in (os.environ.get("LINUX_READINESS_DIR"), os.path.join(os.path.dirname(_SKILL_DIR), "linux-readiness"),
              os.path.join(home, ".claude", "skills", "linux-readiness"), os.path.join(home, ".agents", "skills", "linux-readiness")):
        if d and os.path.isfile(os.path.join(d, "scripts", "linux_readiness.py")):
            return os.path.abspath(d)
    return None


def catalogue_path():
    """scripts/data/linux_readiness.json of the linux-readiness skill, or None."""
    d = skill_dir()
    p = os.path.join(d, "scripts", "data", "linux_readiness.json") if d else None
    return p if p and os.path.isfile(p) else None


def _load():
    d = skill_dir()
    if not d:
        raise SystemExit("linux-readiness skill not found. Install it next to this skill (the skill installer adds it "
                         "automatically) or set LINUX_READINESS_DIR to its folder.")
    spec = importlib.util.spec_from_file_location("_linux_readiness_impl", os.path.join(d, "scripts", "linux_readiness.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_impl = _load()
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__") and k not in ("skill_dir", "catalogue_path")})

if __name__ == "__main__":
    _impl.main()
