"""Validate every skill in skills/ against Anthropic's skill authoring best practices and this repo's CONVENTIONS.md.

Usage:
    python scripts/validate_skills.py [skills_dir] [--skill NAME ...] [--strict] [--json] [--quiet]

    --strict   warnings also fail the run (exit 1)
    --json     machine-readable report on stdout
    --quiet    only skills with findings, no INFO lines

Exit code: 1 if any ERROR (or any WARN with --strict), else 0.

Levels
    ERROR  breaks loading, discovery or portability: must be fixed before publishing
    WARN   departs from the best practices: fix unless there's a reason
    INFO   worth knowing, never fails a run

Checks (source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices,
        https://code.claude.com/docs/en/skills, CONVENTIONS.md)
  Frontmatter   present and parseable; name (<=64, [a-z0-9-], no "anthropic"/"claude", = folder);
                description (non-empty, <=1,024, no XML, third person, "Use when" trigger, listing <=1,536 with
                when_to_use); unknown keys; disable-model-invocation; boolean fields are booleans
  Body          SKILL.md body <500 lines; Contents list on long SKILL.md and on reference files >100 lines;
                time-sensitive wording; Windows-style paths; machine-specific paths
  Links         relative links resolve; links stay inside the skill; reference -> reference chains;
                reference files SKILL.md never mentions; scripts named in docs exist
  Code          Python parses; JSON parses; JS/MJS passes `node --check` (when Node is available);
                third-party Python imports need scripts/install_prerequisites.py
  Hygiene       secrets; tool caches and junk files; large files; total size
"""
import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys

# ---- limits (each from the published guidance; see the module docstring) ----
NAME_MAX = 64
DESC_MAX = 1024           # hard limit: longer descriptions are rejected on upload
DESC_ROOMY = 500          # Claude Code docs: under ~500 survives listing truncation best
LISTING_MAX = 1536        # Claude Code truncates description + when_to_use here
BODY_MAX_LINES = 500      # SKILL.md body budget
BODY_MAX_WORDS = 5000     # the whole body loads every time the skill triggers
TOC_THRESHOLD = 100       # files longer than this need a Contents list near the top
TOC_SEARCH_LINES = 40
BIG_FILE = 5 * 1024 * 1024
BIG_SKILL = 25 * 1024 * 1024

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
KNOWN_KEYS = {
    "name", "description", "when_to_use", "argument-hint", "arguments", "disable-model-invocation", "user-invocable",
    "allowed-tools", "disallowed-tools", "model", "effort", "context", "agent", "background", "paths", "shell",
    "hooks", "license", "compatibility", "metadata", "version",
}
BOOL_KEYS = {"disable-model-invocation", "user-invocable", "background"}
SKIP_DIRS = {"__pycache__", "node_modules", ".git"}
CACHE_DIRS = {".impeccable", ".pytest_cache", ".mypy_cache", ".venv", "venv", ".idea", ".vscode"}
JUNK_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
SAMPLE_DIRS = {"samples", "fixtures", "testdata"}  # example output: not style-linted, still scanned for secrets
TEXT_EXT = {".md", ".py", ".mjs", ".js", ".json", ".txt", ".yml", ".yaml", ".toml", ".html", ".css", ".ps1", ".bat",
            ".cmd", ".sh", ".tmpl", ".csv", ".template", ""}

SECRETS = [
    ("Google API key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("OpenAI / OpenRouter key", r"\bsk-(?:or-|proj-)?[A-Za-z0-9_\-]{24,}"),
    ("Anthropic key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    ("AWS access key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("Slack token", r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    ("Private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
LOCAL_PATH = re.compile(r"\b[A-Za-z]:\\{1,2}Users\\{1,2}[A-Za-z]|(?<![\w.~])/Users/[a-z]|(?<![\w.~])/home/[a-z][\w-]*/")
WIN_PATH = re.compile(r"(?<![\w\\%])(?:scripts|reference|references|templates|tools|engine|assets)\\[\w.-]+")
TIME_SENSITIVE = re.compile(
    r"\b(?:before|after|until|starting|as of)\s+(?:(?:\d{1,2}\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+)?20\d\d\b",
    re.I)
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SCRIPT_MENTION = re.compile(r"(?<![\w/.-])(scripts/[\w./-]+\.(?:py|mjs|js|sh|ps1))(?![\w.])")
RUN_CONTEXT = re.compile(r"\b(?:python3?|py|node|bash|sh|pwsh|run|runs|execute)\b", re.I)
FIRST_PERSON = re.compile(r"^\s*(?:I|I'm|I'll|We|You|Your|Let me|This skill (?:will|can) help you)\b")
TRIGGER = re.compile(r"\b(?:Use|Used|Invoke|Trigger)\w*\b[^.]{0,60}?\b(?:when|for|whenever|if|on|any)\b", re.I)


# ---------------- frontmatter ----------------
def parse_frontmatter(text):
    """Small YAML subset: key: value, quoted values, block scalars (> |), '- item' lists, nested maps (kept raw).
    Returns (fields, body, error)."""
    m = re.match(r"^﻿?---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    if not m:
        return None, text, "SKILL.md must start with a YAML frontmatter block (--- … ---)"
    raw, body = m.group(1), text[m.end():]
    fields, state = {}, {"key": None, "mode": None, "buf": []}

    def flush():
        k, mode, buf = state["key"], state["mode"], state["buf"]
        if k is None:
            return
        if mode == "list":
            fields[k] = list(buf)
        elif mode == "folded":
            fields[k] = " ".join(b.strip() for b in buf if b.strip())
        elif mode == "literal":
            fields[k] = "\n".join(b.strip() for b in buf).strip()
        elif mode in ("map", "pending"):
            fields[k] = {"_raw": "\n".join(buf)}

    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        km = re.match(r"^([A-Za-z_][\w-]*):(?:\s+(.*))?$", line)
        if km and not line[0].isspace():
            flush()
            k, val = km.group(1), (km.group(2) or "").strip()
            state.update(key=k, buf=[])
            if val in (">", ">-", ">+"):
                state["mode"] = "folded"
            elif val in ("|", "|-", "|+"):
                state["mode"] = "literal"
            elif val == "":
                state["mode"] = "pending"
            else:
                state["mode"] = "scalar"
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                fields[k] = val
            continue
        if state["key"] is None:
            return None, body, f"frontmatter line not understood: {line.strip()[:60]}"
        s = line.strip()
        if state["mode"] == "pending":
            state["mode"] = "list" if s.startswith("- ") else "map"
        if state["mode"] == "list" and s.startswith("- "):
            state["buf"].append(s[2:].strip().strip("\"'"))
        elif state["mode"] in ("folded", "literal", "map"):
            state["buf"].append(line)
        elif state["mode"] == "scalar":
            fields[state["key"]] = (fields[state["key"]] + " " + s).strip()
    flush()
    return fields, body, None


# ---------------- helpers ----------------
def walk(path):
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        yield root, dirs, sorted(files)


def rel(p, base):
    return os.path.relpath(p, base).replace(os.sep, "/")


def is_sample(relpath):
    return any(part in SAMPLE_DIRS for part in relpath.split("/"))


def has_toc(lines):
    head = "\n".join(lines[:TOC_SEARCH_LINES])
    return bool(re.search(r"(?im)^(#+\s*|<!--\s*guide:\s*)(table of )?contents\b", head))


def read_text(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except (UnicodeDecodeError, OSError):
        return None


NODE = shutil.which("node")


# ---------------- per-skill checks ----------------
def check_frontmatter(fields, folder, add):
    name, desc = str(fields.get("name", "")), str(fields.get("description", ""))
    if not name:
        add("ERROR", "frontmatter: name is missing")
    else:
        if len(name) > NAME_MAX:
            add("ERROR", f"name is {len(name)} chars (max {NAME_MAX})")
        if not NAME_RE.match(name):
            add("ERROR", "name must be lowercase letters, numbers and single hyphens")
        if "anthropic" in name or "claude" in name:
            add("ERROR", 'name contains a reserved word ("anthropic" / "claude")')
        if name != folder:
            add("WARN", f"name '{name}' differs from the folder '{folder}' (installers and /commands use the folder)")
    if not desc:
        add("ERROR", "frontmatter: description is missing")
    else:
        if len(desc) > DESC_MAX:
            add("ERROR", f"description is {len(desc)} chars (max {DESC_MAX})")
        elif len(desc) > DESC_ROOMY:
            add("INFO", f"description is {len(desc)} chars; under {DESC_ROOMY} survives listing truncation best")
        if re.search(r"<[A-Za-z/][^>]*>", desc):
            add("ERROR", "description contains an XML/HTML tag")
        if FIRST_PERSON.search(desc) or re.search(r"\b(I can|I will|you can|You can)\b", desc):
            add("WARN", "description is not in third person ('Processes…', not 'I/You…')")
        if not TRIGGER.search(desc):
            add("WARN", "description has no 'Use when …' clause saying when to pick the skill")
    if len(desc) + len(str(fields.get("when_to_use", ""))) > LISTING_MAX:
        add("WARN", f"description + when_to_use over {LISTING_MAX} chars: truncated in Claude Code's listing")
    for k in fields:
        if k not in KNOWN_KEYS:
            add("WARN", f"frontmatter: unknown key '{k}' (ignored by agents; put custom data under metadata:)")
    for k in BOOL_KEYS & set(fields):
        if str(fields[k]).lower() not in ("true", "false", "yes", "no", "on", "off", "1", "0"):
            add("ERROR", f"frontmatter: {k} must be a boolean, got '{fields[k]}'")
    if str(fields.get("disable-model-invocation", "")).lower() in ("true", "yes", "on", "1"):
        add("WARN", "disable-model-invocation is set: Claude won't pick this skill on its own")
    if str(fields.get("user-invocable", "")).lower() in ("false", "no", "off", "0"):
        add("INFO", "user-invocable: false hides the skill from the / menu")


def check_files(path, add):
    """Hygiene, code validity and portability for every file. Returns {relpath: text} for Markdown files."""
    md_files, total = {}, 0
    for root, dirs, files in walk(path):
        for d in dirs:
            if d in CACHE_DIRS:
                add("ERROR", f"{rel(os.path.join(root, d), path)}/: tool cache inside the skill (delete it)")
        dirs[:] = [d for d in dirs if d not in CACHE_DIRS]
        for f in files:
            p = os.path.join(root, f)
            r = rel(p, path)
            size = os.path.getsize(p)
            total += size
            if f in JUNK_FILES:
                add("ERROR", f"{r}: OS/editor junk file (delete it)")
                continue
            if size > BIG_FILE:
                add("WARN", f"{r}: {size // (1024 * 1024)} MB (large files slow every install)")
            ext = os.path.splitext(f)[1].lower()
            if ext not in TEXT_EXT:
                continue
            t = read_text(p)
            if t is None:
                continue
            lines = t.splitlines()
            for i, line in enumerate(lines, 1):
                for label, pat in SECRETS:
                    if re.search(pat, line):
                        add("ERROR", f"{r}:{i}: possible {label} (move it to an environment variable)")
            sample = is_sample(r)
            if ext == ".py" and not sample:
                try:
                    ast.parse(t, filename=r)
                except SyntaxError as e:
                    add("ERROR", f"{r}:{e.lineno}: Python syntax error: {e.msg}")
            elif ext == ".json" and not sample:
                try:
                    json.loads(t)
                except ValueError as e:
                    add("ERROR", f"{r}: invalid JSON ({e})")
            elif ext in (".mjs", ".js") and not sample and NODE and "{{" not in t:
                res = subprocess.run([NODE, "--check", p], capture_output=True, text=True)
                if res.returncode != 0:
                    msg = next((l for l in res.stderr.splitlines() if "Error" in l), "syntax error")
                    add("ERROR", f"{r}: JS syntax error ({msg.strip()[:120]})")
            if ext == ".md":
                md_files[r] = t
            if sample or ext in (".bat", ".cmd", ".ps1"):
                continue
            in_code = False
            for i, line in enumerate(lines, 1):
                if ext == ".md" and line.lstrip().startswith("```"):
                    in_code = not in_code
                if LOCAL_PATH.search(line):
                    add("WARN", f"{r}:{i}: machine-specific path (a skill must work on any machine)")
                if ext == ".md" and WIN_PATH.search(line):
                    add("WARN", f"{r}:{i}: Windows-style path '{WIN_PATH.search(line).group(0)}' (use forward slashes)")
                if ext == ".md" and not in_code and TIME_SENSITIVE.search(line):
                    add("INFO", f"{r}:{i}: time-bound wording '{TIME_SENSITIVE.search(line).group(0)}' "
                                "(keep current facts in one place, superseded ones under 'Old patterns')")
    if total > BIG_SKILL:
        add("WARN", f"skill is {total // (1024 * 1024)} MB in total")
    return md_files


def check_markdown(path, md_files, add):
    skill_text = md_files.get("SKILL.md", "")
    for r, t in md_files.items():
        if r == "SKILL.md" or is_sample(r) or r.lower().endswith(("readme.md", "changelog.md")):
            continue
        lines = t.splitlines()
        if len(lines) > TOC_THRESHOLD and not has_toc(lines):
            add("WARN", f"{r}: {len(lines)} lines with no '## Contents' list near the top")
    for r, t in md_files.items():
        if is_sample(r):
            continue
        base = os.path.dirname(os.path.join(path, r))
        in_code = False
        for i, line in enumerate(t.splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            for target in LINK.findall(re.sub(r"`[^`]*`", "", line)):
                if re.match(r"^(https?:|mailto:|#|<|\{|\$)", target) or "<" in target:
                    continue
                tgt = target.split("#")[0]
                if not tgt:
                    continue
                if "\\" in tgt:
                    add("WARN", f"{r}:{i}: backslash in link '{target}' (use forward slashes)")
                    tgt = tgt.replace("\\", "/")
                full = os.path.normpath(os.path.join(base, tgt))
                if os.path.commonpath([full, os.path.normpath(path)]) != os.path.normpath(path):
                    add("WARN", f"{r}:{i}: link leaves the skill folder ({target}); a skill must be self-contained")
                    continue
                if not os.path.exists(full):
                    add("ERROR", f"{r}:{i}: broken link '{target}'")
                    continue
                src_top, dst = r.split("/")[0], rel(full, path)
                if src_top in ("reference", "references") and dst.endswith(".md") and dst.split("/")[0] in ("reference", "references"):
                    add("INFO", f"{r}:{i}: links another reference file ({dst}); keep essential content one level from SKILL.md")
    for r in md_files:
        parts = r.split("/")
        if parts[0] in ("reference", "references") and len(parts) == 2:
            stem = parts[1][:-3]
            if parts[1] not in skill_text and not re.search(rf"\b{re.escape(stem)}\b", skill_text):
                add("WARN", f"{r}: never mentioned in SKILL.md, so Claude won't know to open it")
    for r, t in md_files.items():
        if is_sample(r):
            continue
        for i, line in enumerate(t.splitlines(), 1):
            if not RUN_CONTEXT.search(line):
                continue  # only lines that tell Claude to run something must point at a real script
            for mention in SCRIPT_MENTION.findall(line):
                if "*" not in mention and not os.path.exists(os.path.join(path, mention)):
                    add("WARN", f"{r}:{i}: says to run {mention}, which isn't in the skill")


def check_imports(path, add):
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    if not stdlib:
        return
    third = {}
    for root, dirs, files in walk(path):
        if is_sample(rel(root, path)):
            continue
        local = {f[:-3] for f in files if f.endswith(".py")} | set(dirs)
        for f in files:
            if not f.endswith(".py"):
                continue
            try:
                tree = ast.parse(read_text(os.path.join(root, f)) or "")
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    mods = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                    mods = [n.module]
                else:
                    continue
                for mod in mods:
                    top = mod.split(".")[0]
                    if top not in stdlib and top not in local and not top.startswith("_"):
                        third.setdefault(top, set()).add(rel(os.path.join(root, f), path))
    if not third:
        return
    if os.path.exists(os.path.join(path, "scripts", "install_prerequisites.py")):
        add("INFO", "third-party Python imports: " + ", ".join(sorted(third)) + " (scripts/install_prerequisites.py installs them)")
    else:
        add("WARN", "third-party Python imports (" + ", ".join(sorted(third)) + ") but no scripts/install_prerequisites.py to install them")


def check_skill(path, folder):
    F = {"ERROR": [], "WARN": [], "INFO": []}
    add = lambda lvl, msg: F[lvl].append(msg)
    text = read_text(os.path.join(path, "SKILL.md")) or ""
    fields, body, err = parse_frontmatter(text)
    if err:
        add("ERROR", err)
        return F
    check_frontmatter(fields, folder, add)
    body_lines = body.splitlines()
    if len(body_lines) >= BODY_MAX_LINES:
        add("ERROR", f"SKILL.md body is {len(body_lines)} lines (keep under {BODY_MAX_LINES}; move detail to reference files)")
    if len(text.splitlines()) > TOC_THRESHOLD and len(re.findall(r"^## ", body, re.M)) >= 3 and not has_toc(body_lines):
        add("WARN", "SKILL.md is over 100 lines with several sections but no '## Contents' list")
    if fields.get("argument-hint") and not re.search(r"(?i)no (argument|command)|bare `/|help", body):
        add("WARN", "command-style skill (argument-hint) doesn't say what a bare /" + folder + " does (show state + menu, start nothing)")
    words = len(re.findall(r"\S+", body))
    if words > BODY_MAX_WORDS:
        add("WARN", f"SKILL.md body is ~{words} words: all of it loads whenever the skill triggers")
    md_files = check_files(path, add)
    check_markdown(path, md_files, add)
    check_imports(path, add)
    for lvl in F:
        F[lvl] = list(dict.fromkeys(F[lvl]))  # de-duplicate, keep order
    return F


# ---------------- runner ----------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skills_dir", nargs="?", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills"))
    ap.add_argument("--skill", action="append", help="only this skill (repeatable)")
    ap.add_argument("--strict", action="store_true", help="warnings fail the run too")
    ap.add_argument("--json", action="store_true", help="print a JSON report")
    ap.add_argument("--quiet", action="store_true", help="hide INFO lines and clean skills")
    a = ap.parse_args()
    root = os.path.abspath(a.skills_dir)
    if not os.path.isdir(root):
        print(f"No skills folder at {root}")
        return 1
    report = {}
    for folder in sorted(os.listdir(root)):
        p = os.path.join(root, folder)
        if os.path.isfile(os.path.join(p, "SKILL.md")) and (not a.skill or folder in a.skill):
            report[folder] = check_skill(p, folder)
    if a.json:
        print(json.dumps(report, indent=2))
    else:
        for folder, F in report.items():
            status = "FAIL" if F["ERROR"] else ("WARN" if F["WARN"] else "PASS")
            if a.quiet and status == "PASS":
                continue
            print(f"[{status}] {folder}")
            for lvl in ("ERROR", "WARN") + (() if a.quiet else ("INFO",)):
                for msg in F[lvl]:
                    print(f"   {lvl:<5} {msg}")
        e = sum(len(F["ERROR"]) for F in report.values())
        w = sum(len(F["WARN"]) for F in report.values())
        print(f"\n{len(report)} skill(s) · {e} error(s) · {w} warning(s)")
    failed = any(F["ERROR"] or (a.strict and F["WARN"]) for F in report.values())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
