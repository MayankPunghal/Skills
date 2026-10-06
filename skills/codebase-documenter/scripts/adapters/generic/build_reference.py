"""Build and run facts for the runbook, read from build, container and pipeline files (key names only, never values).

Writes docs/reference/build-and-run.md (anchors run-…), the evidence behind operations/runbook.md:
  toolchain      global.json, .nvmrc / .node-version, .python-version, .tool-versions
  commands       .NET solutions, runnable and test projects (dotnet build / test / run, msbuild for legacy projects),
                 package.json scripts (package manager from the lock file), Makefile / justfile targets, Python entry points
  run locally    launchSettings.json profiles (URLs, environment variable names)
  containers     Dockerfiles (base images, exposed ports, entry point), docker-compose services (image / build, ports, env names)
  pipelines      GitHub Actions, Azure Pipelines, GitLab CI, Jenkinsfile, Bitbucket: triggers, jobs / stages, commands
  environments   appsettings.<Env>.json, .env.<env>, config transforms (Web.<Env>.config): names only
  operations     health-check endpoints, hosted / background services, scheduled jobs (cron, Hangfire, Quartz)
Options (adapter_options.generic-build): skip_regex, max_commands (default 40 per pipeline).
"""
import json
import os
import re
from collections import defaultdict

import sys

from _scan import BACK, ROOT, esc, line_at, options, read, slug, walk, write_page

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import scheduled_jobs as SJ  # noqa: E402

OPT = options("generic-build")
MAXC = OPT.get("max_commands", 40)
SECRETISH = re.compile(r"(?i)(password|pwd|secret|token|apikey|api_key|connectionstring|key=)")
sections = defaultdict(list)  # section -> markdown lines


def cmd(s):
    s = re.sub(r"\s+", " ", s.strip())
    return "(command hidden: contains a credential-like word)" if SECRETISH.search(s) and "secrets." not in s else s[:160]


def item(section, title, path, lines):
    sections[section] += ["", f'<a id="{slug("run", section, title)}"></a>', "", f"### {title}", "", f"File: `{path}` · {BACK}", ""] + lines


def toolchain():
    for path, full in walk(exts=None, names=re.compile(r"^(global\.json|\.nvmrc|\.node-version|\.python-version|\.tool-versions|rust-toolchain(\.toml)?)$")):
        t = read(full).strip()
        if path.endswith("global.json"):
            try:
                sdk = (json.loads(t).get("sdk") or {})
                t = f".NET SDK {sdk.get('version', '?')}" + (f" (rollForward: {sdk['rollForward']})" if sdk.get("rollForward") else "")
            except ValueError:
                t = "unparseable"
        item("toolchain", os.path.basename(path), path, [f"- {esc(x)}" for x in t.splitlines()[:8]])


def dotnet():
    projs = list(walk(exts={".csproj", ".vbproj", ".fsproj"}))
    for path, full in walk(exts={".sln", ".slnx"}):
        item("commands", f"Solution {os.path.basename(path)}", path, [f"- Restore and build: `dotnet build \"{path}\"`",
                                                                      f"- Test: `dotnet test \"{path}\"`"])
    for path, full in projs:
        t = read(full)
        name = os.path.splitext(os.path.basename(path))[0]
        sdk = re.search(r'<Project\s+Sdk="([^"]+)"', t)
        legacy = not sdk
        lines = []
        if re.search(r"Microsoft\.NET\.Test\.Sdk|<IsTestProject>\s*true", t, re.I):
            lines.append(f"- Test: `dotnet test \"{path}\"`" if not legacy else "- Test: build with msbuild, run with vstest.console")
        elif (sdk and "Web" in sdk.group(1)) or re.search(r"<OutputType>\s*(Exe|WinExe)", t, re.I):
            lines.append(f"- Run: `dotnet run --project \"{path}\"`" if not legacy else
                         "- Run: legacy .NET Framework project; build with msbuild / Visual Studio and host in IIS or run the exe")
        if legacy:
            lines.append("- Build: `msbuild` (not SDK-style; `dotnet build` may not work, Windows only)")
        if lines:
            item("commands", name, path, lines)


def node():
    for path, full in walk(exts=None, names=re.compile(r"^package\.json$")):
        try:
            d = json.loads(read(full) or "{}")
        except ValueError:
            continue
        scripts = d.get("scripts") or {}
        if not scripts:
            continue
        folder = os.path.dirname(full)
        pm = "pnpm" if os.path.exists(os.path.join(folder, "pnpm-lock.yaml")) else "yarn" if os.path.exists(os.path.join(folder, "yarn.lock")) else "npm"
        lines = [f"- Install: `{pm} install`"] + [f"- `{pm} run {esc(k)}` → `{esc(cmd(v))}`" for k, v in list(scripts.items())[:MAXC]]
        item("commands", f"{d.get('name') or os.path.basename(folder)} (package.json)", path, lines)


def make():
    for path, full in walk(exts=None, names=re.compile(r"^(Makefile|makefile|GNUmakefile|justfile|Justfile)$")):
        targets = [t for t in re.findall(r"(?m)^([A-Za-z][\w.-]*)\s*:(?!=)", read(full)) if not t.startswith(".")]
        if targets:
            tool = "just" if "just" in path.lower() else "make"
            item("commands", os.path.basename(path), path, [f"- `{tool} {esc(t)}`" for t in targets[:MAXC]])


def python():
    for path, full in walk(exts=None, names=re.compile(r"^(pyproject\.toml|manage\.py|requirements\.txt)$")):
        t = read(full)
        if path.endswith("manage.py"):
            item("commands", f"Django ({os.path.dirname(path) or '.'})", path, ["- Run: `python manage.py runserver`", "- Migrate: `python manage.py migrate`",
                                                                               "- Test: `python manage.py test`"])
        elif path.endswith("requirements.txt"):
            item("commands", f"Python requirements ({os.path.dirname(path) or '.'})", path, [f"- Install: `pip install -r {path}`"])
        else:
            scripts = re.search(r"(?ms)^\[project\.scripts\]\s*(.*?)(?=^\[|\Z)", t)
            lines = ["- Install: `pip install -e .`"] + [f"- Entry point `{esc(n)}` → `{esc(v)}`" for n, v in
                                                         re.findall(r'(?m)^([\w.-]+)\s*=\s*"([^"]+)"', scripts.group(1) if scripts else "")]
            item("commands", f"Python project ({os.path.dirname(path) or '.'})", path, lines)


def launch():
    for path, full in walk(exts=None, names=re.compile(r"^launchSettings\.json$")):
        try:
            d = json.loads(read(full))
        except ValueError:
            continue
        lines = []
        for name, p in (d.get("profiles") or {}).items():
            env = p.get("environmentVariables") or {}
            envs = ", ".join(f"`{k}`" + (f" = {v}" if k in ("ASPNETCORE_ENVIRONMENT", "DOTNET_ENVIRONMENT") else "") for k, v in env.items())
            lines.append(f"- **{esc(name)}** ({p.get('commandName', '')}): {esc(p.get('applicationUrl', '') or '—')}" + (f"; env: {envs}" if envs else ""))
        item("run locally", os.path.dirname(os.path.dirname(path)) or path, path, lines or ["- no profiles"])


def containers():
    for path, full in walk(exts=None, names=re.compile(r"^(Dockerfile(\.\w+)?|\w+\.Dockerfile|Containerfile)$")):
        t = read(full)
        lines = [f"- Base image{'s' if len(re.findall(r'(?im)^FROM', t)) > 1 else ''}: " + ", ".join(f"`{x}`" for x in re.findall(r"(?im)^FROM\s+(\S+)", t))]
        ports = re.findall(r"(?im)^EXPOSE\s+(.+)$", t)
        if ports:
            lines.append("- Exposes: " + ", ".join(ports))
        ep = re.findall(r"(?im)^(?:ENTRYPOINT|CMD)\s+(.+)$", t)
        if ep:
            lines.append(f"- Starts with: `{esc(cmd(ep[-1]))}`")
        lines.append(f"- Build: `docker build -f \"{path}\" .`")
        item("containers", path, path, lines)
    for path, full in walk(exts=None, names=re.compile(r"^(docker-)?compose([.\w-]*)\.ya?ml$")):
        t = read(full)
        body = re.search(r"(?ms)^services:\s*\n(.*?)(?=^\S|\Z)", t)
        lines = [f"- Start: `docker compose -f \"{path}\" up`"]
        if body:
            for name, block in re.findall(r"(?m)^  ([\w.-]+):[ \t]*\r?\n((?:^(?:    |[ \t]*\r?$)[^\n]*\n?)*)", body.group(1)):
                img = re.search(r"(?m)^\s+image:\s*(\S+)", block)
                build = re.search(r"(?m)^\s+build:", block)
                ports = re.findall(r"(?m)^\s+-\s*['\"]?(\d+:\d+)", block)
                env_block = re.search(r"(?m)^    environment:[ \t]*\r?\n((?:^      [^\n]*\n?)*)", block)
                eb = env_block.group(1) if env_block else ""
                envs = re.findall(r"(?m)^\s+-\s*([\w.]+)=", eb) + re.findall(r"(?m)^\s+([\w.]+)\s*:", eb)  # names only
                lines.append(f"- **{esc(name)}**: " + (f"image `{img.group(1)}`" if img else "built from source" if build else "—")
                             + (f"; ports {', '.join(ports)}" if ports else "") + (f"; env: {', '.join('`' + e + '`' for e in sorted(set(envs)))}" if envs else ""))
        item("containers", path, path, lines)


def pipelines():
    files = list(walk(exts=None, names=re.compile(r"^(azure-pipelines[\w.-]*\.ya?ml|\.gitlab-ci\.yml|Jenkinsfile|bitbucket-pipelines\.yml)$"),
                      skip=re.compile(r"(^|/)(node_modules|bin|obj|vendor)(/|$)")))
    gh = os.path.join(ROOT, ".github", "workflows")
    if os.path.isdir(gh):
        files += [(f".github/workflows/{f}", os.path.join(gh, f)) for f in sorted(os.listdir(gh)) if f.endswith((".yml", ".yaml"))]
    for path, full in files:
        t = read(full)
        lines = []
        if path.endswith("Jenkinsfile"):
            lines.append("- Stages: " + (", ".join(re.findall(r"stage\s*\(\s*['\"]([^'\"]+)", t)) or "—"))
            cmds = re.findall(r"\b(?:sh|bat|powershell)\s+['\"]([^'\"]+)", t)
        else:
            name = re.search(r"(?m)^name:\s*(.+)$", t)
            if name:
                lines.append(f"- Name: {esc(name.group(1).strip())}")
            trig = re.search(r"(?ms)^(?:on|trigger|pr|schedules|workflow):\s*(.*?)(?=^\S)", t + "\nx")
            if trig:
                keys = re.findall(r"(?m)^\s{2}([\w-]+):", trig.group(1)) or re.findall(r"[\w-]+", trig.group(1))[:6]
                lines.append(f"- Triggers: {esc(', '.join(dict.fromkeys(keys)))}")
            cron = re.findall(r"cron:\s*['\"]([^'\"]+)", t)
            if cron:
                lines.append("- Schedule: " + ", ".join(f"`{c}`" for c in cron))
            jobs = re.search(r"(?ms)^(?:jobs|stages):\s*\n(.*?)(?=^\S|\Z)", t)
            if jobs:
                names = re.findall(r"(?m)^  (?:- (?:job|stage):\s*)?([\w.-]+):?\s*$", jobs.group(1))
                if names:
                    lines.append("- Jobs / stages: " + ", ".join(dict.fromkeys(names)))
            cmds = [c for c in re.findall(r"(?m)^\s*(?:-\s*)?(?:run|script|bash|pwsh|powershell):\s*[|>]?\s*(.*)$", t) if c.strip()]
            cmds += re.findall(r"(?m)^\s*-?\s*task:\s*(\S+)", t)
        lines += [f"- `{esc(cmd(c))}`" for c in cmds[:MAXC]] + ([f"- … {len(cmds) - MAXC} more"] if len(cmds) > MAXC else [])
        item("pipelines", path, path, lines)


def environments():
    envs = defaultdict(set)
    for path, _ in walk(exts=None, names=re.compile(r"^(appsettings\.[\w-]+\.json|\.env\.[\w-]+|[Ww]eb\.[\w-]+\.config|application-[\w-]+\.(ya?ml|properties))$")):
        m = re.match(r"(?:appsettings|\.env|[Ww]eb|application)[.-]([\w-]+?)\.?(?:json|config|ya?ml|properties)?$", os.path.basename(path))
        if m and m.group(1).lower() not in ("example", "sample", "template"):
            envs[m.group(1)].add(path)
    if envs:
        sections["environments"] += ["", "| Environment | Files (values never copied) |", "| --- | --- |"] + [
            f'| <a id="{slug("run", "env", e)}"></a>{esc(e)} | ' + ", ".join(f"`{p}`" for p in sorted(ps)) + " |" for e, ps in sorted(envs.items())]


def operations():
    rows = []
    for path, full in walk(exts={".cs", ".vb", ".java", ".kt", ".py", ".js", ".ts", ".go"}):
        t = read(full)
        for m in re.finditer(r"MapHealthChecks\(\s*\"([^\"]+)\"", t):
            rows.append(("health check", m.group(1).strip(), path, line_at(t, m.start())))
    if rows:
        sections["operations"] += ["", "| What | Name | Source |", "| --- | --- | --- |"] + [
            f'| <a id="{slug("run", w, n)}"></a>{w} | `{esc(n)}` | `{p}:{ln}` |' for w, n, p, ln in sorted(rows)]
    # scheduled and background jobs (scripts/scheduled_jobs.py, shared with migration-assessment): what runs when, configured how
    jobs = SJ.scan(ROOT, OPT.get("exclude_dirs"))
    if jobs:
        sections["operations"] += ["", f"**Scheduled and background jobs** ({len(jobs)}; {sum(1 for j in jobs if j['windows_only'])} on a Windows-only "
                                   "scheduler). Jobs triggered from outside the repository are invisible: confirm the full list with the operations team.",
                                   "", "| Job | Scheduler | Schedule | Runs | Configured by | Windows-only | Source |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for j in jobs:
            sections["operations"].append(
                f'| <a id="{slug("run", "job", j["scheduler"], j["name"] or j["file"], j["line"])}"></a>{esc(j["name"] or "-")} | {esc(j["scheduler"])} | '
                f'{esc(j["schedule"] or "-")} | {("`" + esc(j["target"]) + "`") if j["target"] else "-"} | {esc(j["configured_by"] or "-")} | '
                f'{"yes" if j["windows_only"] else "no"} | `{j["file"]}:{j["line"]}` |')


TITLES = [("toolchain", "Toolchain"), ("commands", "Build, test and run commands"), ("run locally", "Run locally (launch profiles)"),
          ("containers", "Containers"), ("pipelines", "CI / CD pipelines"), ("environments", "Environments"),
          ("operations", "Health checks, background services and schedules")]


def main():
    for f in (toolchain, dotnet, node, make, python, launch, containers, pipelines, environments, operations):
        f()
    if not sections:
        print("build-and-run: nothing found")
        return
    out = ["# Build and run", "",
           "Facts for setting up, building, running and deploying, read from the build, container and pipeline files. "
           "Configuration and environment variables are listed by name only; values are never copied. "
           "The narrative runbook (operations / runbook) explains these in order and adds what files cannot show "
           "(servers, access, release approvals).", "", '<a id="index"></a>', "",
           "| Section | Items |", "| --- | ---: |"]
    out += [f"| [{t}](#{slug('run', k)}) | {sum(1 for l in sections[k] if l.startswith(('### ', '| <a')))} |" for k, t in TITLES if sections.get(k)]
    for k, t in TITLES:
        if sections.get(k):
            out += ["", f'<a id="{slug("run", k)}"></a>', "", f"## {t}", "", BACK] + sections[k]
    write_page("build-and-run.md", out)
    print("build-and-run: " + ", ".join(f"{k} {sum(1 for l in sections[k] if l.startswith(('### ', '| <a')))}" for k, t in TITLES if sections.get(k)))


if __name__ == "__main__":
    main()
