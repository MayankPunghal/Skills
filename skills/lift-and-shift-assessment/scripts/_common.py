"""Shared helpers for lift-and-shift-assessment scripts (standard library only, Python 3.10+).

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
    "client": "",                    # client name as it should appear in the documents
    "engagement": "AWS Lift-and-Shift Assessment",
    "prepared_by": os.environ.get("ASSESSMENT_PREPARED_BY", ""),  # author shown in the document control table
    "estate_roots": [],              # folders that hold the client's repositories / solutions (read-only)
    "company_domains": [],           # the client's own web domains (detected from the code when empty)
    "current_hosting": "",           # what the client told us: "Hyper-V", "on-prem VMware", "Proxmox", "colo"
    "online_package_lookup": True,   # query api.nuget.org for package licences / deprecation (package ids and versions leave the machine); --offline to stop
    "git_activity_days": 180,
    "exclude_dirs": ["bin", "obj", "packages", "node_modules", ".git", ".vs", "TestResults", "dist", "wwwroot/lib", "bower_components"],
    "skip_repos": [],
    "intake": {},                    # questionnaire answers (intake.py): work items, environments, DevOps notes, status
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


SECRET_WORDS = r"(?:password|passwd|pwd|user\s*id|uid|secret|api[_-]?key|access[_-]?key|token|client[_-]?secret|account[_-]?key|sharedaccesskey|decryptionkey|validationkey|credential|private[_-]?key)"
# identifier containing a secret word (TokenValue, dbPassword, ApiKeySecret) followed by = or : and a value (C#, VB, config, JSON, connection strings)
SECRET_VALUE = re.compile(r"(?i)(\b\w*" + SECRET_WORDS + r"\w*\s*[=:]\s*@?)(\"[^\"]*\"|'[^']*'|[^;\"'\s<>,)]+)")
# SQL seed rows: ('Group', 'SomeTokenKey', 'value') -> mask the value that follows a secret-like key
SQL_SECRET_PAIR = re.compile(r"(?i)('[^']*" + SECRET_WORDS + r"[^']*'\s*,\s*N?')([^']*)(')")
XML_SECRET_ATTR = re.compile(r'(?i)((?:password|pwd|secret|apikey|api_key|token|decryptionKey|validationKey|accountKey|connectionString)\s*=\s*")([^"]*)(")')
APPSETTING_SECRET = re.compile(r'(?i)(<add\s+key="[^"]*(?:pass|pwd|secret|token|apikey|api_key|key|credential)[^"]*"\s+value=")([^"]*)(")')


URL_USERINFO = re.compile(r"(?i)(\b[a-z][a-z0-9+.\-]*://[^\s/:@\"'<>]+:)([^\s/@\"'<>]+)(@)")  # scheme://user:password@host
URL_USER_CONCAT = re.compile(r"(?i)(\b[a-z][a-z0-9+.\-]*://[^\s/:@\"'<>]+:\"\s*\+\s*[\w.]*\(\s*)(\"[^\"]*\")")  # "ftp://user:" + Encode("password") + "@host"


def mask(line):
    """Remove secret VALUES from an evidence snippet, keep the key names. Snippets never carry credentials."""
    line = URL_USER_CONCAT.sub(lambda m: m.group(1) + '"***"', URL_USERINFO.sub(lambda m: m.group(1) + "***" + m.group(3), line))
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


ISSUES_LOG = "SKILL-ISSUES.md"  # run issues log for the skill owner, at the workspace root (never part of the report)


def issues_log(root, client=""):
    """Create SKILL-ISSUES.md from the template when missing; return (entries, open entries)."""
    p = os.path.join(root, ISSUES_LOG)
    if not os.path.exists(p):
        ver = re.search(r"(?m)^\s*version:\s*[\"']?([\w.\-]+)", read_text(os.path.join(SKILL_DIR, "SKILL.md")) or "")
        t = read_text(os.path.join(SKILL_DIR, "templates", "SKILL-ISSUES.md.tmpl")) or ""
        for k, v in (("skill", "lift-and-shift-assessment"), ("version", ver.group(1) if ver else "unknown"),
                     ("product", client or "this estate")):
            t = t.replace("{{" + k + "}}", v)
        write_text(p, t)
    t = re.sub(r"<!--.*?-->", "", read_text(p) or "", flags=re.S)  # the entry format example is a comment
    return (len(re.findall(r"(?m)^## ISSUE-\d+", t)),
            len(re.findall(r"(?m)^\| ISSUE-\d+ \|.*\|\s*open\s*\|\s*$", t)))
