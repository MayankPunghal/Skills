"""Compare the installed prerequisite tools with the versions this skill was tested with, and report newer releases.

    python <skill>/scripts/tool_updates.py             # report (also run by `npx -y github:MayankPunghal/Skills update`)
    python <skill>/scripts/tool_updates.py --offline   # installed vs tested only, no lookups on pypi.org / npmjs.org

Nothing is installed here. A tool older or newer than the tested version: `install_prerequisites.py --update` moves it to
the tested version. A newer release than the tested one is reported only: it becomes the tested version after it has
been tried with both skills (scripts/data/tool_versions.json). The result is cached in
~/.cache/codebase-documenter/tool-updates.json, and context.py repeats its one-line summary at the start of a session.
The lookups send only the public package names (graphifyy, mkdocs-material, sqlglot, mermaid).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import run, utf8_stdout  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
VERSIONS = os.path.join(HERE, "data", "tool_versions.json")
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "codebase-documenter")
CACHE = os.path.join(CACHE_DIR, "tool-updates.json")
MAX_AGE_DAYS = 30  # an older report is not repeated by context.py


def tested():
    return json.load(open(VERSIONS, encoding="utf-8"))["tools"]


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4])


def installed(name, spec):
    """Installed version of a tool, or None."""
    if name == "graphify":  # its own environment (uv tool or pip): ask the command
        m = re.search(r"\d+(?:\.\d+)+", run(["graphify", "--version"])[1])
        return m.group(0) if m else None
    if name == "mermaid":
        import offline_mermaid
        return offline_mermaid.cached_version()
    code, out = run([sys.executable, "-c", f"import importlib.metadata as m; print(m.version({spec['package']!r}))"])
    return out.strip() if code == 0 and out.strip() else None


def latest(spec):
    """Latest published version, or None when the registry cannot be reached."""
    url = (f"https://pypi.org/pypi/{spec['package']}/json" if spec["source"] == "pypi"
           else f"https://registry.npmjs.org/{spec['package']}/latest")
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.load(r)
    except (OSError, ValueError):
        return None
    return (data.get("info") or {}).get("version") if spec["source"] == "pypi" else data.get("version")


def status(inst, test, new):
    if not inst:
        return "missing"
    if vtuple(inst) < vtuple(test):
        return "older than tested"
    if vtuple(inst) > vtuple(test):
        return "newer than tested"
    return "newer release, untested" if new and vtuple(new) > vtuple(test) else "ok"


def check(offline=False):
    try:  # an offline check keeps the latest releases the last online one found
        before = json.load(open(CACHE, encoding="utf-8")).get("tools") or {}
    except (OSError, ValueError):
        before = {}
    out = {}
    for name, spec in tested().items():
        inst = installed(name, spec)
        new = (before.get(name) or {}).get("latest") if offline else latest(spec)
        out[name] = {"installed": inst, "tested": spec["tested"], "latest": new, "status": status(inst, spec["tested"], new)}
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump({"checked_at": time.time(), "tools": out}, fh, indent=1)
    return out


def summary(tools):
    """One line for context.py, or None when nothing needs attention."""
    fix = [f"{n} {t['installed']} (tested {t['tested']})" for n, t in tools.items()
           if t["status"] in ("older than tested", "newer than tested")]
    new = [f"{n} {t['latest']} (tested {t['tested']})" for n, t in tools.items() if t["status"] == "newer release, untested"]
    parts = []
    if fix:
        parts.append("not the tested version: " + ", ".join(fix) + " -> install_prerequisites.py --update")
    if new:
        parts.append("newer releases not yet tested with this skill (left alone): " + ", ".join(new))
    return "TOOLS: " + "; ".join(parts) if parts else None


def cached_summary():
    """The summary of the last check, if it is recent; never touches the network."""
    try:
        data = json.load(open(CACHE, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - data.get("checked_at", 0) > MAX_AGE_DAYS * 86400:
        return None
    return summary(data.get("tools") or {})


def print_report(tools, offline=False):
    print("Prerequisite tool versions (installed / tested with this skill / latest release):")
    for n, t in tools.items():
        print(f"  {n:<16} {t['installed'] or '-':<10} {t['tested']:<10} {t['latest'] or ('-' if offline else 'unknown'):<10} {t['status']}")
    print(summary(tools) or "TOOLS: all at the tested versions.")
    if any(t["status"] == "missing" for t in tools.values()):
        print("Missing tools: run install_prerequisites.py.")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="no registry lookups")
    a = ap.parse_args()
    print_report(check(a.offline), a.offline)


if __name__ == "__main__":
    main()
