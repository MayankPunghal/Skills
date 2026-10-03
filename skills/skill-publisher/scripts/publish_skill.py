"""Mechanical half of the skill publisher: stage, scan, validate, publish, install. Standard library only.

    python publish_skill.py prepare <skill-folder | zip | skill-name> [--name NAME]   (a name stages the repo copy, to edit it)
    python publish_skill.py check <name>
    python publish_skill.py publish <name> [--to personal|public] [--message "..."]
    python publish_skill.py install <name>

prepare  brings the managed repo clone (~/.mayank-skills/repo) up to date, copies the skill into a clean staging folder
         (~/.mayank-skills/staging/<name>) without caches/secrets/zips, then prints the scan + validator report.
check    re-runs the secret scan and the validator on the staged copy (use after every refactor pass).
publish  refuses while check fails; otherwise copies staging into the target repo's skills/ (personal by default, or
         where the skill already lives; --to public for shareable skills), adds a README row, commits, pushes.
install  installs the published skill on this machine into the same folders as the other skills, with prerequisites.

The source folder is never modified.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".mayank-skills")
REPO = os.path.join(ROOT, "repo")          # public Skills repo: also holds CONVENTIONS.md, the validator and the installer
PERSONAL = os.path.join(ROOT, "personal")  # private Skills-Personal repo: skills only for the owner's machines
PERSONAL_URL = "https://github.com/MayankPunghal/Skills-Personal.git"
STAGING = os.path.join(ROOT, "staging")
# <clone>.pending exists while a commit in that clone is not on GitHub yet; the installer won't reset over it
def pending(repo):
    return repo + ".pending"
REPO_URL = "https://github.com/MayankPunghal/Skills.git"

# Never copied into the repo: caches, VCS data, build output, local secrets, superseded copies.
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".secrets", "_old", ".venv", "venv", ".pytest_cache", ".mypy_cache", ".impeccable", ".idea", ".vscode"}
SKIP_FILES = {".DS_Store", "Thumbs.db", ".env"}
SKIP_EXT = {".pyc", ".pyo", ".zip", ".log"}
BIG_FILE = 5 * 1024 * 1024  # GitHub warns above 50 MB; anything over 5 MB in a skill is almost always an accident

# Secret patterns: report file:line and the pattern name only, never the matched value.
SECRETS = [
    ("Google API key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("OpenAI / OpenRouter key", r"sk-(?:or-)?[A-Za-z0-9_\-]{20,}"),
    ("Anthropic key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("GitHub token", r"gh[pousr]_[A-Za-z0-9]{30,}"),
    ("AWS access key", r"AKIA[0-9A-Z]{16}"),
    ("Private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("Password in connection string", r"(?i)(?:password|pwd)\s*=\s*[^;\"'<>{}\s$%]{4,}"),
    ("Bearer token", r"(?i)bearer\s+[A-Za-z0-9\-_\.=]{30,}"),
]


def say(msg=""):
    print(msg, flush=True)


def run(cmd, cwd=None, check=False):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        say(f"FAILED: {' '.join(cmd)}\n{r.stderr.strip() or r.stdout.strip()}")
        sys.exit(1)
    return r


def sync_repo(repo=REPO, url=REPO_URL, required=True):
    """Clone or refresh a managed clone. Local work (uncommitted or unpushed) is kept, never reset away.
    Returns False when an optional repo (personal) can't be reached."""
    quiet_env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    if not os.path.isdir(os.path.join(repo, ".git")):
        os.makedirs(ROOT, exist_ok=True)
        say(f"Cloning {url} -> {repo}")
        r = subprocess.run(["git", "clone", "--depth", "1", "-q", url, repo], capture_output=True, text=True,
                           env=None if required else quiet_env)
        if r.returncode != 0:
            if required:
                say(f"FAILED: git clone {url}\n{r.stderr.strip()}")
                sys.exit(1)
            shutil.rmtree(repo, ignore_errors=True)
            return False
        return True
    r = run(["git", "-C", repo, "fetch", "--depth", "1", "-q", "origin", "main"], check=required)
    if r.returncode != 0:
        return False
    dirty = run(["git", "-C", repo, "status", "--porcelain"]).stdout.strip()
    if dirty or os.path.exists(pending(repo)):
        say(f"NOTE: {repo} has local work not on GitHub (uncommitted: {bool(dirty)}, unpushed commit: {os.path.exists(pending(repo))}). Keeping it.")
        if not dirty:
            r = run(["git", "-C", repo, "rebase", "-q", "origin/main"])
            if r.returncode != 0:
                run(["git", "-C", repo, "rebase", "--abort"])
                say("NOTE: could not rebase the local commit onto GitHub's main; publish will report the push result.")
        return True
    run(["git", "-C", repo, "reset", "--hard", "-q", "origin/main"], check=True)
    return True


def sync_all():
    sync_repo()
    ok = sync_repo(PERSONAL, PERSONAL_URL, required=False)
    if not ok:
        say("NOTE: Skills-Personal isn't reachable from this machine (no access or offline): only --to public is possible.")
    return ok


def where(name):
    """'public' / 'personal' if the skill already lives in that repo, else None."""
    for label, repo in (("personal", PERSONAL), ("public", REPO)):
        if os.path.isdir(os.path.join(repo, "skills", name)):
            return label
    return None


def frontmatter_name(skill_md):
    try:
        text = open(skill_md, encoding="utf-8").read()
    except OSError:
        return None
    m = re.search(r"^name:\s*['\"]?([^'\"\n]+)", text, re.M)
    return m.group(1).strip() if m else None


def find_skill_root(path):
    """The folder holding SKILL.md: the given folder, or the single sub-folder that has one (zips often nest)."""
    if os.path.isfile(os.path.join(path, "SKILL.md")):
        return path
    hits = [os.path.dirname(os.path.join(d, "SKILL.md")) for d, _, files in os.walk(path) if "SKILL.md" in files]
    hits = sorted(hits, key=lambda p: p.count(os.sep))
    return hits[0] if hits else None


def copy_clean(src, dst):
    skipped = []
    for d, dirs, files in os.walk(src):
        rel = os.path.relpath(d, src)
        keep = []
        for x in dirs:
            (skipped.append(os.path.join(rel, x) + "/") if x in SKIP_DIRS else keep.append(x))
        dirs[:] = keep
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            if f in SKIP_FILES or os.path.splitext(f)[1].lower() in SKIP_EXT:
                skipped.append(os.path.join(rel, f))
                continue
            shutil.copy2(os.path.join(d, f), os.path.join(dst, rel, f))
    return [s.replace(os.sep, "/").lstrip("./") for s in skipped]


def scan(folder):
    secrets, big = [], []
    for d, _, files in os.walk(folder):
        for f in files:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, folder).replace(os.sep, "/")
            if os.path.getsize(p) > BIG_FILE:
                big.append(f"{rel} ({os.path.getsize(p) // (1024 * 1024)} MB)")
                continue
            try:
                lines = open(p, encoding="utf-8").read().splitlines()
            except (UnicodeDecodeError, OSError):
                continue  # binary file
            for i, line in enumerate(lines, 1):
                for label, pat in SECRETS:
                    if re.search(pat, line):
                        secrets.append(f"{rel}:{i}  {label}")
    return secrets, big


def validate(name):
    """Run the repo's validator on the staged skill only. Returns (errors, output)."""
    tmp = os.path.join(ROOT, "validate-tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    shutil.copytree(os.path.join(STAGING, name), os.path.join(tmp, name))
    r = run([sys.executable, os.path.join(REPO, "scripts", "validate_skills.py"), tmp])
    shutil.rmtree(tmp, ignore_errors=True)
    out = r.stdout.strip()
    return out.count("ERROR"), out


def report(name):
    staged = os.path.join(STAGING, name)
    secrets, big = scan(staged)
    errors, vout = validate(name)
    say("\n--- validator ---")
    say(vout)
    say("\n--- secret scan ---")
    say("\n".join(f"  SECRET?  {s}" for s in secrets) if secrets else "  none found")
    if big:
        say("\n--- large files ---")
        say("\n".join(f"  BIG  {b}" for b in big))
    status = {"name": name, "staged": staged, "errors": errors, "secrets": len(secrets), "big_files": len(big),
              "ready": errors == 0 and not secrets and not big}
    say("\nSTATUS " + json.dumps(status))
    return status


def cmd_prepare(a):
    has_personal = sync_all()
    src = os.path.abspath(os.path.expanduser(a.source))
    if not os.path.exists(src):
        # Not a path: treat it as the name of a skill already in the collection and stage the repo copy to edit.
        name_guess = re.sub(r"[^a-z0-9-]+", "-", a.source.lower()).strip("-")
        loc = where(name_guess)
        if not loc:
            say(f"Not found: {a.source} is neither a folder/zip nor a skill in the collection.")
            sys.exit(1)
        src = os.path.join(PERSONAL if loc == "personal" else REPO, "skills", name_guess)
        say(f"EDITING  the {loc} repo's copy of {name_guess}: apply the requested changes to the STAGED copy, then check and publish.")
    if zipfile.is_zipfile(src):
        unz = os.path.join(ROOT, "unzip-tmp")
        shutil.rmtree(unz, ignore_errors=True)
        zipfile.ZipFile(src).extractall(unz)
        src = unz
    root = find_skill_root(src)
    if not root:
        say(f"No SKILL.md found in {src}. A skill folder must contain SKILL.md at its top level.")
        sys.exit(1)
    fm = frontmatter_name(os.path.join(root, "SKILL.md"))
    name = a.name or fm or os.path.basename(root.rstrip("/\\"))
    name = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:64]
    shutil.rmtree(STAGING, ignore_errors=True)
    skipped = copy_clean(root, os.path.join(STAGING, name))
    loc = where(name)
    existing = os.path.join(PERSONAL if loc == "personal" else REPO, "skills", name)
    say(f"SOURCE   {root}  (left untouched)")
    say(f"STAGED   {os.path.join(STAGING, name)}")
    say(f"NAME     {name}" + (f"   (frontmatter says '{fm}' — set it to '{name}')" if fm and fm != name else ""))
    say(f"REPO     {REPO}   conventions: {os.path.join(REPO, 'CONVENTIONS.md')}")
    if loc:
        say(f"EXISTING skills/{name} is already in the {loc} repo: this is an UPDATE. Merge, never drop what the repo version has.")
        say(f"         repo copy: {existing}")
        say(f"TARGET   {loc} (publish keeps it where it is; --to moves it)")
    else:
        say("EXISTING no — this is a NEW skill.")
        say("TARGET   personal by default (private: only your machines). Use --to public only when the user says it is shareable."
            + ("" if has_personal else "  [personal unavailable here]"))
    if skipped:
        say("SKIPPED  " + ", ".join(skipped[:15]) + (" …" if len(skipped) > 15 else ""))
    report(name)


def cmd_check(a):
    if not os.path.isdir(os.path.join(STAGING, a.name)):
        say(f"Nothing staged as {a.name}. Run prepare first.")
        sys.exit(1)
    st = report(a.name)
    sys.exit(0 if st["ready"] else 1)


def readme_row(name, repo=REPO):
    """Add the skill to the README skills table (if missing) and keep the skill-count badge right."""
    readme = os.path.join(repo, "README.md")
    text = open(readme, encoding="utf-8").read()
    changed = False
    if f"(skills/{name}/SKILL.md)" not in text:
        skill_md = open(os.path.join(repo, "skills", name, "SKILL.md"), encoding="utf-8").read()
        m = re.search(r"^description:\s*(.+)$", skill_md, re.M)
        desc = (m.group(1) if m else "").strip().strip("\"'")
        first = re.split(r"(?<=\.)\s", desc)[0].replace("|", "/")
        row = f"| [**{name}**](skills/{name}/SKILL.md) | {first} | — |"
        rows = [l for l in text.splitlines() if re.match(r"\| \[\*\*[a-z0-9-]+\*\*\]\(skills/", l)]
        # keep the table alphabetical: insert before the first row that sorts after this name
        after = [l for l in rows if re.search(r"\*\*([a-z0-9-]+)\*\*", l).group(1) > name]
        if after:
            text = text.replace(after[0], row + "\n" + after[0], 1)
        elif rows:
            text = text.replace(rows[-1], rows[-1] + "\n" + row, 1)
        changed = True
    count = len([d for d in os.listdir(os.path.join(repo, "skills")) if os.path.isfile(os.path.join(repo, "skills", d, "SKILL.md"))])
    new = re.sub(r"badge/skills-\d+-", f"badge/skills-{count}-", text)
    if new != text or changed:
        open(readme, "w", encoding="utf-8", newline="\n").write(new)
    return changed


def cmd_publish(a):
    staged = os.path.join(STAGING, a.name)
    if not os.path.isdir(staged):
        say(f"Nothing staged as {a.name}. Run prepare first.")
        sys.exit(1)
    st = report(a.name)
    if not st["ready"]:
        say("\nNOT PUBLISHED: fix the errors / secrets / large files above, then run publish again.")
        sys.exit(1)
    has_personal = sync_all()
    loc = where(a.name)
    target = a.to or loc or "personal"
    if target == "personal" and not has_personal:
        say("NOT PUBLISHED: Skills-Personal isn't reachable here. Sign Git in to GitHub, or use --to public if the skill is shareable.")
        sys.exit(1)
    repo = PERSONAL if target == "personal" else REPO
    if loc and loc != target:
        say(f"MOVING {a.name} from {loc} to {target}.")
        old_repo = PERSONAL if loc == "personal" else REPO
        shutil.rmtree(os.path.join(old_repo, "skills", a.name))
        readme = os.path.join(old_repo, "README.md")
        if os.path.exists(readme):
            lines = open(readme, encoding="utf-8").read().split("\n")
            open(readme, "w", encoding="utf-8", newline="\n").write(
                "\n".join(l for l in lines if f"(skills/{a.name}/SKILL.md)" not in l))
        _fix_badge(old_repo)
        _commit_push(old_repo, f"Move skill {a.name} to the {target} repo")
    dest = os.path.join(repo, "skills", a.name)
    is_update = os.path.isdir(dest)
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(staged, dest)
    added_row = readme_row(a.name, repo)
    msg = a.message or f"{'Update' if is_update else 'Add'} skill: {a.name}"
    body = "\n\nPublished with skill-publisher." + ("\nREADME: added to the skills table." if added_row else "")
    head = _commit_push(repo, msg + body)
    if head:
        say(f"PUBLISHED skills/{a.name} @ {head} -> github.com/MayankPunghal/{'Skills-Personal' if target == 'personal' else 'Skills'} ({target})")


def _fix_badge(repo):
    readme = os.path.join(repo, "README.md")
    if not os.path.exists(readme):
        return
    count = len([d for d in os.listdir(os.path.join(repo, "skills")) if os.path.isfile(os.path.join(repo, "skills", d, "SKILL.md"))])
    text = open(readme, encoding="utf-8").read()
    open(readme, "w", encoding="utf-8", newline="\n").write(re.sub(r"badge/skills-\d+-", f"badge/skills-{count}-", text))


def _commit_push(repo, msg):
    run(["git", "-C", repo, "add", "-A"], check=True)
    if not run(["git", "-C", repo, "status", "--porcelain"]).stdout.strip():
        say("No changes: the repo already has exactly this version.")
        return None
    run(["git", "-C", repo, "commit", "-q", "-m", msg], check=True)
    r = run(["git", "-C", repo, "push", "-q", "origin", "HEAD:main"])
    if r.returncode != 0:
        open(pending(repo), "w").write(msg)
        say(f"COMMITTED locally but the push failed (kept in {repo}; the installer won't discard it):")
        say(r.stderr.strip())
        sys.exit(1)
    if os.path.exists(pending(repo)):
        os.remove(pending(repo))
    return run(["git", "-C", repo, "rev-parse", "--short", "HEAD"]).stdout.strip()


def cmd_install(a):
    manifest = os.path.join(ROOT, "manifest.json")
    installer = os.path.join(REPO, "install.mjs")
    node = shutil.which("node")
    if not node:
        say("Node is not on PATH; install it, then run: npx -y github:MayankPunghal/Skills update")
        sys.exit(1)
    has_installs = os.path.isfile(manifest) and json.load(open(manifest, encoding="utf-8")).get("installs")
    if has_installs:
        # update refreshes everything installed and adds this skill wherever the others live, with prerequisites
        args = [node, installer, "update", "--yes", "--no-sync", f"--skills={a.name}"]
    else:
        args = [node, installer, "--yes", "--no-sync", f"--skills={a.name}"]
    sys.exit(subprocess.run(args).returncode)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("source"); p.add_argument("--name")
    p = sub.add_parser("check"); p.add_argument("name")
    p = sub.add_parser("publish"); p.add_argument("name"); p.add_argument("--message")
    p.add_argument("--to", choices=["personal", "public"], help="target repo (default: where the skill already is, else personal)")
    p = sub.add_parser("install"); p.add_argument("name")
    a = ap.parse_args()
    if shutil.which("git") is None:
        say("git is not on PATH. Install Git (Windows: winget install --id Git.Git -e), then rerun.")
        sys.exit(1)
    {"prepare": cmd_prepare, "check": cmd_check, "publish": cmd_publish, "install": cmd_install}[a.cmd](a)


if __name__ == "__main__":
    main()
