"""Shared helpers for migration-assessment scripts (standard library only, Python 3.10+).

Every script runs with the current directory = the assessment workspace (the folder holding assessment.json).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(SKILL_DIR, "scripts", "data")
CONFIG_NAME = "assessment.json"
OUT = "assessment"  # all generated files live under <workspace>/assessment/

DEFAULTS = {
    "client": "",                    # client name as it should appear in the report
    "engagement": "AWS Migration & Modernization Assessment",
    "prepared_by": os.environ.get("ASSESSMENT_PREPARED_BY", ""),  # consultancy name on the report: --prepared-by, or set ASSESSMENT_PREPARED_BY once per machine
    "estate_roots": [],              # folders that hold the client's repositories / solutions
    "target_dotnet": "net10.0",      # .NET 10 LTS (support to Nov 2028); .NET 8 ends 10 Nov 2026
    "target_os": "linux",
    "compliance": [],                # e.g. ["HIPAA", "PCI DSS", "SOC 2"]: drives security findings and questions
    "data_residency": "",           # e.g. "EU only"
    "current_hosting": "",          # what the client told us: "on-prem VMware", "Proxmox", "Hyper-V", "colo"
    "online_package_lookup": False,  # query api.nuget.org for TFMs / deprecation / vulnerabilities / licence
    "git_activity_days": 180,
    "exclude_dirs": ["bin", "obj", "packages", "node_modules", ".git", ".vs", "TestResults", "dist", "wwwroot/lib", "bower_components"],
    "skip_repos": [],
    "scenario": {"hosting": "modernize", "database": "auto"},  # hosting: modernize | linux-lift | windows-rehost; database: auto | rds-sqlserver | babelfish | postgresql | dual | ec2-sqlserver
}

SOURCE_DIR_SKIP = {"bin", "obj", "packages", "node_modules", ".git", ".vs", "testresults", "bower_components", ".idea", "dist"}


def utf8_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def ws_root(start=None):
    d = os.path.abspath(start or os.getcwd())
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
            sys.exit(f"No {CONFIG_NAME} found here or above. Run setup_assessment.py first (cwd = assessment workspace).")
        return None, dict(DEFAULTS)
    cfg = dict(DEFAULTS)
    cfg.update(json.load(open(os.path.join(root, CONFIG_NAME), encoding="utf-8")))
    return root, cfg


def save_config(root, cfg):
    with open(os.path.join(root, CONFIG_NAME), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")


def data(name):
    return json.load(open(os.path.join(DATA_DIR, name), encoding="utf-8"))


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    return json.load(open(path, encoding="utf-8"))


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)  # atomic: a crash never leaves a half-written state file


def write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read_text(path):
    """Source files come in UTF-8, UTF-8 BOM, UTF-16 or Windows-1252; never fail on one."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "x"


def tool_exe(name):
    """Full path of a CLI tool: PATH first, then the folders user-level installers use (uv / pipx / pip --user)."""
    found = shutil.which(name)
    if found:
        return found
    dirs = [os.path.join(os.path.expanduser("~"), ".local", "bin"), sysconfig.get_path("scripts"), os.path.dirname(sys.executable),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "dotnet")]
    try:
        dirs.append(sysconfig.get_path("scripts", f"{os.name}_user"))
    except KeyError:
        pass
    for d in dirs:
        hit = d and shutil.which(name, path=d)
        if hit:
            return hit
    return None


def run(cmd, cwd=None, timeout=None, env=None):
    """Run a command list; returns (code, stdout+stderr). Code 127 when the program is missing."""
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", DOTNET_CLI_TELEMETRY_OPTOUT="1")
    if env:
        e.update(env)
    if cmd and os.sep not in cmd[0] and "/" not in cmd[0]:
        cmd = [tool_exe(cmd[0]) or cmd[0]] + list(cmd[1:])
    try:
        p = subprocess.run(cmd, cwd=cwd, env=e, text=True, encoding="utf-8", errors="replace",
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    except OSError as ex:
        return 127, f"{cmd[0]} not found ({ex})"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(cmd)}"
    return p.returncode, p.stdout or ""


def documenter_dir():
    """The codebase-documenter skill this skill builds on (sibling install, personal install, or env var)."""
    for d in (os.environ.get("CODEBASE_DOCUMENTER_DIR"), os.path.join(os.path.dirname(SKILL_DIR), "codebase-documenter"),
              os.path.join(os.path.expanduser("~"), ".claude", "skills", "codebase-documenter")):
        if d and os.path.exists(os.path.join(d, "SKILL.md")):
            return d
    return None


SECRET_WORDS = r"(?:password|passwd|pwd|user\s*id|uid|secret|api[_-]?key|access[_-]?key|token|client[_-]?secret|account[_-]?key|sharedaccesskey|decryptionkey|validationkey|credential|private[_-]?key)"
# identifier containing a secret word (TokenValue, dbPassword, ApiKeySecret) followed by = or : and a value (C#, VB, config, JSON, connection strings)
SECRET_VALUE = re.compile(r"(?i)(\b\w*" + SECRET_WORDS + r"\w*\s*[=:]\s*@?)(\"[^\"]*\"|'[^']*'|[^;\"'\s<>,)]+)")
# SQL seed rows: ('Group', 'SomeTokenKey', 'value') -> mask the value that follows a secret-like key
SQL_SECRET_PAIR = re.compile(r"(?i)('[^']*" + SECRET_WORDS + r"[^']*'\s*,\s*N?')([^']*)(')")
XML_SECRET_ATTR = re.compile(r'(?i)((?:password|pwd|secret|apikey|api_key|token|decryptionKey|validationKey|accountKey|connectionString)\s*=\s*")([^"]*)(")')
APPSETTING_SECRET = re.compile(r'(?i)(<add\s+key="[^"]*(?:pass|pwd|secret|token|apikey|api_key|key|credential)[^"]*"\s+value=")([^"]*)(")')


def mask(line):
    """Remove secret VALUES from an evidence snippet, keep the key names. Snippets never carry credentials."""
    s = APPSETTING_SECRET.sub(lambda m: m.group(1) + ("***" if m.group(2) else "") + m.group(3), line)
    s = XML_SECRET_ATTR.sub(lambda m: m.group(1) + (_mask_conn(m.group(2)) if m.group(1).lower().startswith("connectionstring") else ("***" if m.group(2) else "")) + m.group(3), s)
    s = SQL_SECRET_PAIR.sub(lambda m: m.group(1) + "***" + m.group(3), s)
    s = SECRET_VALUE.sub(lambda m: m.group(1) + "***", s)
    return s.strip()[:220]


def _mask_conn(cs):
    return SECRET_VALUE.sub(lambda m: m.group(1) + "***", cs)


def rel(path, start):
    return os.path.relpath(path, start).replace("\\", "/")


def state_path(root):
    return os.path.join(root, OUT, "state.json")


def load_state(root):
    return read_json(state_path(root), {"repos": {}, "steps": {}})


def save_state(root, st):
    write_json(state_path(root), st)


def mark(root, repo, step, status="done", **extra):
    """Record per-repo progress so a large estate can be assessed across sessions."""
    st = load_state(root)
    r = st["repos"].setdefault(repo, {})
    r[step] = status
    r.update(extra)
    save_state(root, st)


def mark_step(root, step, status="done"):
    st = load_state(root)
    st["steps"][step] = status
    save_state(root, st)
