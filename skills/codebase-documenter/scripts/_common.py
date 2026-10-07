"""Shared helpers for codebase-documenter scripts (stdlib only).

Every script runs with the current directory = the documentation workspace root (the folder holding
codebase-docs.json). Paths in codebase-docs.json are relative to that root.
"""
import json
import os
import re
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(SKILL_DIR, "templates")
ADAPTERS = os.path.join(SKILL_DIR, "scripts", "adapters")
CONFIG_NAME = "codebase-docs.json"

DEFAULTS = {
    "product": "",                 # display name, e.g. "Acme Orders"
    "code_name": "",               # e.g. "AcmeOrders"
    "slug": "",                    # short id used for the project skill name: <slug>-docs
    "description": "",             # one sentence: what the system is
    "stack": "",                   # e.g. "ASP.NET MVC 5, SQL Server"
    "source_root": ".",            # folder that contains the code
    "source_markers": [],          # sub-folders/files that identify the source root (lookup.py)
    "docs_dir": "docs",
    "graph_dir": "graphify-out",
    "adapters": ["generic-graph", "generic-deps", "generic-sql", "generic-config", "generic-build", "generic-api",
                 "generic-errors", "generic-di", "generic-tests", "generic-dbaccess", "generic-trace", "generic-views",
                 "generic-portability", "generic-endpoints", "generic-flows", "generic-areas"],
                                             # generic-di / generic-views / generic-portability: .NET only; no-ops elsewhere
    "adapter_options": {},
    "coverage": [
        {"title": "Classes", "prefix": "cls-", "page": "components.md"},
        {"title": "Routines", "prefix": "sp-", "page": "db-routines.md"},
        {"title": "Tables", "prefix": "tbl-", "page": "db-tables.md"},
    ],
    "seed_row_tables": [],
    "site": {"name": "", "accent_hex": "#0b6e74", "language": "en"},
    "sensitive": ["security/findings.md"],
    "graph": {"label": "auto", "backend": "openai", "model": "", "base_url": "", "api_key_env": "",
              "batch_size": 2},
}


def ws_root():
    """Folder containing codebase-docs.json (searching upwards from the current folder)."""
    d = os.path.abspath(os.getcwd())
    while True:
        if os.path.exists(os.path.join(d, CONFIG_NAME)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def load_config(required=True):
    root = ws_root()
    if not root:
        if required:
            sys.exit(f"codebase-documenter: no {CONFIG_NAME} found here or above. Run the init command first.")
        return None, dict(DEFAULTS)
    cfg = json.loads(open(os.path.join(root, CONFIG_NAME), encoding="utf-8").read())
    merged = json.loads(json.dumps(DEFAULTS))
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return root, merged


def save_config(root, cfg):
    with open(os.path.join(root, CONFIG_NAME), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def slug(*parts):
    return re.sub(r"[^a-z0-9]+", "-", "-".join(str(p) for p in parts).lower()).strip("-")


def utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def tool_exe(name):
    """Full path of a CLI tool (graphify, uv, git ...): PATH first, then the folders user-level installers use
    (uv tool / pipx bin, pip --user scripts), which a fresh install often leaves off PATH. None if not found."""
    import shutil
    import sysconfig
    found = shutil.which(name)
    if found:
        return found
    dirs = [os.path.join(os.path.expanduser("~"), ".local", "bin"), os.path.join(os.path.expanduser("~"), ".cargo", "bin"),
            sysconfig.get_path("scripts"), os.path.dirname(sys.executable),
            # .NET SDK: dotnet-install.sh/.ps1 user folders, then the system-wide installs
            os.path.join(os.path.expanduser("~"), ".dotnet"), os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "dotnet"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "dotnet"), "/usr/share/dotnet", "/usr/local/share/dotnet",
            "/usr/lib/dotnet"]
    try:
        dirs.append(sysconfig.get_path("scripts", f"{os.name}_user"))
    except KeyError:
        pass
    for d in dirs:
        hit = d and shutil.which(name, path=d)
        if hit:
            return hit
    return None


def run(cmd, env=None, cwd=None, check=False, capture=True, timeout=None):
    """Run a command (list), UTF-8 safe on Windows. Returns (code, stdout+stderr); code 127 if the program is missing."""
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if env:
        e.update({k: v for k, v in env.items() if v is not None})
    if cmd and os.sep not in cmd[0] and "/" not in cmd[0]:
        cmd = [tool_exe(cmd[0]) or cmd[0]] + list(cmd[1:])
    try:
        p = subprocess.run(cmd, env=e, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                           stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None,
                           timeout=timeout)
    except OSError as ex:
        if check:
            sys.exit(f"cannot run {cmd[0]}: {ex}. Run: python <skill>/scripts/install_prerequisites.py")
        return 127, f"{cmd[0]} not found ({ex}); run install_prerequisites.py"
    if check and p.returncode:
        sys.exit(f"command failed ({p.returncode}): {' '.join(cmd)}\n{(p.stdout or '')[-2000:]}")
    return p.returncode, p.stdout or ""


def render(template_name, values):
    """Fill {{key}} placeholders in a template file."""
    text = open(os.path.join(TEMPLATES, template_name), encoding="utf-8").read()
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values.get(m.group(1), m.group(0))), text)


def write(path, text, overwrite=True):
    if not overwrite and os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return True


def rel(path, start=None):
    try:
        r = os.path.relpath(path, start or os.getcwd())
        path = os.path.abspath(path) if r.startswith("..") else r
    except ValueError:
        pass
    return path.replace("\\", "/")


def step(msg, since=None):
    """One timestamped progress line, flushed at once (long runs are otherwise silent until the end)."""
    import time
    took = f" ({time.time() - since:.0f}s)" if since else ""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}{took}", flush=True)


LOCK_NAME = ".building"
LOCK_STALE_HOURS = 12


def _pid_alive(pid):
    if os.name == "nt":  # os.kill(pid, 0) terminates the process on Windows: ask tasklist instead
        code, out = run(["tasklist", "/FI", f"PID eq {pid}", "/NH"])
        return code == 0 and str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def graph_busy(cfg):
    """The build marker in the graph folder while `code_graph.py build` rewrites graph.json, else None (a marker whose
    process has ended, or older than LOCK_STALE_HOURS, is stale and ignored)."""
    import time
    p = os.path.join(cfg.get("graph_dir", "graphify-out"), LOCK_NAME)
    try:
        info = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - os.path.getmtime(p) > LOCK_STALE_HOURS * 3600 or not _pid_alive(int(info.get("pid", 0))):
        return None
    return info


class GraphLock:
    """`with GraphLock(cfg, "build"):` writes the marker that build_site.py waits for, and removes it on exit."""

    def __init__(self, cfg, what):
        self.path = os.path.join(cfg.get("graph_dir", "graphify-out"), LOCK_NAME)
        self.what = what

    def __enter__(self):
        import time
        write(self.path, json.dumps({"pid": os.getpid(), "step": self.what, "started": time.strftime("%Y-%m-%d %H:%M:%S")}))
        return self

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass


def tick(cfg, startswith):
    """Mark the PROGRESS.md checklist item that starts with the given text as done (no-op if absent)."""
    p = os.path.join(cfg.get("docs_dir", "docs"), "_notes", "PROGRESS.md")
    if not os.path.exists(p):
        return
    t = open(p, encoding="utf-8").read()
    t2 = re.sub(r"- \[ \] (" + re.escape(startswith) + ")", r"- [x] \1", t, count=1)
    if t2 != t:
        write(p, t2)


def note_problems(path):
    """Why a research note is not finished yet ([] when it is): missing file, the template's "Status: in progress" header,
    or most of the template's section comments still unchanged (sections never written)."""
    if not os.path.exists(path):
        return ["note file missing"]
    text = open(path, encoding="utf-8").read()
    tmpl = open(os.path.join(TEMPLATES, "note.md.tmpl"), encoding="utf-8").read()
    left = [c for c in re.findall(r"<!--.*?-->", tmpl) if c in text]
    out = []
    if "Status: in progress" in text:
        out.append('header still says "Status: in progress" (set "Status: done")')
    if len(left) * 2 > len(re.findall(r"<!--.*?-->", tmpl)):
        out.append(f"{len(left)} template section comments still unchanged")
    return out
