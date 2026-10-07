"""Generic configuration reference: every configuration KEY NAME (never a value) per config file, with the code files
that read it. Formats: web.config / app.config (appSettings, connectionStrings), appsettings*.json and other *.json
config, .env*, application.properties, *.yml / *.yaml (keys by indentation), *.toml, settings.py (UPPER_CASE names).

Also lists configuration the code reads by literal name ("Read in code", anchors cfg-code-<key>): environment variables
(Environment.GetEnvironmentVariable with its target, wrappers that pass their parameter to it, os.environ / getenv /
process.env), AppSettings["X"], ConnectionStrings["X"], IConfiguration["X"]; option env_helpers names more wrappers.

Also lists credentials written into the source itself, comments included ("Credentials written in the source", anchor
cfg-credentials): kind, file:line and whether the line is a comment, NEVER the value. Repository access then means access
to the credential, so each one is a security finding to confirm (rotate it, remove it from the file and its history).

Writes docs/reference/configuration.md (anchors cfg-<file>-<key>), docs/agent/config-reads.json and
docs/agent/source-credentials.json. Run by build_site.py (cwd = workspace root).
"""
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
import sys
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from code_text import strip_comments  # noqa: E402

# languages whose comments strip_comments understands (// and /* */; VB ' and REM)
C_COMMENTS = (".cs", ".vb", ".java", ".kt", ".scala", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go", ".fs", ".swift", ".php")

CFG = json.load(open("codebase-docs.json", encoding="utf-8"))
ROOT = os.environ.get("DOCS_SOURCE_ROOT") or CFG.get("source_root", ".")
OUT = os.path.join(CFG.get("docs_dir", "docs"), "reference")
OPT = CFG.get("adapter_options", {}).get("generic-config", {})
SKIP = {"bin", "obj", "node_modules", "packages", ".git", "dist", "build", "vendor", "graphify-out", ".vs", "__pycache__"}
CONFIG = re.compile(r"(?i)^(web|app)\.config$|^appsettings.*\.json$|^\.env(\..+)?$|^application(-\w+)?\.(properties|ya?ml)$|"
                    r"^(config|settings)(\.\w+)?\.(json|ya?ml|toml)$|^settings\.py$|^docker-compose.*\.ya?ml$")
CODE_EXT = (".cs", ".vb", ".cshtml", ".vbhtml", ".razor", ".aspx", ".ascx", ".asax", ".master", ".py", ".ts", ".tsx", ".js",
            ".jsx", ".java", ".kt", ".go", ".rb", ".php", ".rs")
# keys the .NET host or framework reads itself (no code names them): said so instead of "no reader found"
FRAMEWORK = re.compile(r"(?i)^(Logging|AllowedHosts|Kestrel|Urls|DetailedErrors|HostFilteringOptions|HttpsRedirection|ForwardedHeaders|"
                       r"ASPNETCORE_\w+|DOTNET_\w+|ValidationSettings:UnobtrusiveValidationMode|webpages:\w+|aspnet:\w+|"
                       r"ClientValidationEnabled|UnobtrusiveJavaScriptEnabled)\b")


# credentials recognisable by their shape; the value itself is never kept, only kind, file and line
CREDENTIALS = [
    (re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{10,}"), "Stripe live secret key"),
    (re.compile(r"\b(?:sk|rk)_test_[A-Za-z0-9]{10,}"), "Stripe test secret key"),
    (re.compile(r"\bwhsec_[A-Za-z0-9]{10,}"), "Stripe webhook signing secret"),
    (re.compile(r"\bpk_(?:live|test)_[A-Za-z0-9]{10,}"), "Stripe publishable key (public by design; names the account)"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "Google API key"),
    (re.compile(r"\bSG\.[\w-]{16,}\.[\w-]{16,}"), "SendGrid API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "GitHub token"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"), "API key (sk-...)"),
    (re.compile(r"(?i)\b(?:password|pwd)\s*=\s*(?!['\"]?\s*[;'\"]|\{|\$|<|\*|@|\+)([^;'\"\s<>]{3,})"), "password in a connection string"),
    (re.compile(r"(?i)\b(?:api[_-]?key|secret|token|client[_-]?secret)\w*\s*[=:]\s*['\"]([A-Za-z0-9_\-./+=]{16,})['\"]"), "key / secret literal"),
]
PLACEHOLDER = re.compile(r"(?i)^(?:x+|\*+|\.+|password|passwd|pwd|changeme|secret|your\w*|example\w*|dummy\w*|test|none|null|"
                         r"string\.empty|\w+\.(?:password|pwd)\w*|\w*(?:password|pwd)\w*\))$")
CONN_PART = re.compile(r"(?i)\b(?:server|data source|user id|uid|initial catalog|database|host)\s*=")
COMMENT_LINE = re.compile(r"^\s*(?://|/\*|\*|'|REM\b|#|<!--|@\*)")


def source_credentials(files):
    """[(kind, file, line, in_comment)] for every credential-shaped text in code, config and script files."""
    out = []
    for r, text in files:
        if r.endswith((".md", ".map")):
            continue
        # a line whose credential disappears once comments are blanked sits in a comment (block comments included)
        bare = strip_comments(text, vb=r.lower().endswith(".vb")).split("\n") if r.lower().endswith(C_COMMENTS) else None
        for ln, line in enumerate(text.split("\n"), 1):
            if len(line) > 2000:  # minified / generated
                continue
            for rx, kind in CREDENTIALS:
                m = rx.search(line)
                if not m:
                    continue
                val = m.group(1) if m.groups() else m.group(0)
                if PLACEHOLDER.match(val.strip()):
                    continue
                if kind.startswith("password") and not CONN_PART.search(line):  # user.Password = hashed; is code, not a credential
                    continue
                in_comment = bool(COMMENT_LINE.match(line)) or (bare is not None and ln <= len(bare) and m.group(0) not in bare[ln - 1])
                out.append((kind, r, ln, in_comment))
                break
    return sorted(set(out), key=lambda x: (x[1], x[2]))


def git_tracked():
    """Paths git tracks under the source root (relative, forward slashes), or None when it is not a git checkout: a credential
    in an ignored local file (appsettings.Development.json kept out of git) is not in the repository."""
    import subprocess
    try:
        top = subprocess.run(["git", "-C", ROOT, "rev-parse", "--show-prefix"], capture_output=True, text=True, timeout=60)
        if top.returncode:
            return None
        ls = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return {p.replace("\\", "/") for p in ls.stdout.split("\0") if p} if ls.returncode == 0 else None


def slug(*p):
    return re.sub(r"[^a-z0-9]+", "-", "-".join(p).lower()).strip("-")


def read(p):
    return open(p, encoding="utf-8-sig", errors="replace").read()


def keys_of(path):
    name = os.path.basename(path).lower()
    text = read(path)
    if name.endswith(".config"):
        try:
            r = ET.fromstring(text)
        except ET.ParseError:
            return []
        return ([("appSetting", a.get("key")) for a in r.findall("./appSettings/add") if a.get("key")] +
                [("connectionString", a.get("name")) for a in r.findall("./connectionStrings/add") if a.get("name")])
    if name.endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError:
            return []
        out = []

        def walk(o, pre):
            if isinstance(o, dict):
                for k, v in o.items():
                    p = f"{pre}:{k}" if pre else k
                    if isinstance(v, dict) and len(pre.split(":")) < 4:
                        walk(v, p)
                    else:
                        out.append(("key", p))
        walk(data, "")
        return out
    if name.startswith(".env") or name.endswith(".properties"):
        return [("key", m) for m in re.findall(r"^\s*([A-Za-z_][\w.\-]*)\s*[=:]", text, re.M)]
    if name.endswith((".yml", ".yaml")):
        out, stack = [], []
        for line in text.splitlines():
            m = re.match(r"^(\s*)([A-Za-z_][\w.\-]*)\s*:", line)
            if not m or line.lstrip().startswith("#"):
                continue
            ind = len(m.group(1))
            while stack and stack[-1][0] >= ind:
                stack.pop()
            stack.append((ind, m.group(2)))
            if len(stack) <= 4:
                out.append(("key", ".".join(s[1] for s in stack)))
        return out
    if name.endswith(".toml"):
        sec, out = "", []
        for line in text.splitlines():
            s = re.match(r"^\s*\[([^\]]+)\]", line)
            if s:
                sec = s.group(1)
                continue
            k = re.match(r"^\s*([A-Za-z_][\w\-]*)\s*=", line)
            if k:
                out.append(("key", f"{sec}.{k.group(1)}" if sec else k.group(1)))
        return out
    if name == "settings.py":
        return [("setting", m) for m in re.findall(r"^([A-Z][A-Z0-9_]+)\s*=", text, re.M)]
    return []


def readers(cfg_path, kind, key, code, cfg_text):
    """(files that read the key, note). Evidence must name the key, not just its last word: "Default" or "AspNetCore"
    (from Logging:LogLevel:Microsoft.AspNetCore) occur in almost every file."""
    name = os.path.basename(cfg_path).lower()
    if name.startswith("docker-compose"):
        env = re.match(r"services\.[^.]+\.environment\.(.+)$", key)
        if not env:
            return [], "Docker Compose setting"
        svc = key.split(".")[1]
        users, note = readers(cfg_path.replace(name, "appsettings.json"), "key", env.group(1).replace("__", ":"), code, cfg_text)
        return users, note or ("" if users else f"environment variable of compose service `{svc}` (read by that container or its image)")
    if name.startswith(".env"):
        used = sorted(r for r, t in cfg_text.items() if r != cfg_path and re.search(r"\$\{?" + re.escape(key) + r"\b", t))
        k = re.escape(key)
        users = sorted(fp for fp, t in code if re.search(r"(GetEnvironmentVariable|getenv|environ(?:\.get)?|process\.env)\W{1,3}" + k + r"\b", t))
        users += sorted(fp for fp, t in SCRIPTS if re.search(r"['\"]" + k + r"['\"]|\$env:" + k + r"\b|%" + k + r"%|\$\{?" + k + r"\b", t))
        return users, ("used by " + ", ".join(f"`{u}`" for u in used[:4]) + " (`${" + key + "}`)") if used else ""
    parts = re.split(r":|__", key) if kind != "setting" else [key]
    leaf = parts[-1]
    pats = [re.escape(f'"{key}"'), re.escape(f"'{key}'")]
    if "__" in key or ":" in key:
        alt = key.replace(":", "__") if ":" in key else key.replace("__", ":")
        pats += [re.escape(f'"{alt}"')]
    if kind == "connectionString" or (len(parts) == 2 and parts[0].lower() == "connectionstrings"):
        pats.append(r"(?:GetConnectionString|ConnectionStrings)\s*[\[(]\s*(?:\w+\s*\.\s*)?\"" + re.escape(leaf) + r"\"")
    if kind == "appSetting":
        pats.append(r"AppSettings\s*(?:\[|\.Get\s*\()\s*\"" + re.escape(key) + r"\"")
    if kind == "setting":  # settings.py: settings.NAME
        pats.append(r"\bsettings\." + re.escape(key) + r"\b")
    if name.endswith((".properties", ".yml", ".yaml")):  # Spring: @Value("${a.b}"), @ConfigurationProperties
        pats.append(r"\$\{" + re.escape(key) + r"[}:]")
    rx = re.compile("|".join(pats))
    users = {fp for fp, t in code if rx.search(t)}
    if len(parts) > 1:  # GetSection("Fulfillment")["AppUser"], GetSection("A:B").GetValue<int>("Leaf"), section bound to an options class
        sec = ":".join(parts[:-1])
        srx = re.compile(r"GetSection\s*\(\s*\"" + re.escape(sec) + r"\"\s*\)")
        for fp, t in code:
            if fp not in users and srx.search(t):
                if re.search(r"[\[(<,]\s*\"" + re.escape(leaf) + r"\"", t):
                    users.add(fp)
                elif re.search(srx.pattern + r"[\s\S]{0,80}?(Bind|Configure|Get<)", t) or re.search(r"(Configure|Bind)\w*\s*(<[^>]*>)?\s*\([^)]*" + srx.pattern, t):
                    users.add(fp + " (section bound to options)")
    note = "read by the .NET host / framework" if not users and FRAMEWORK.search(key) else ""
    return sorted(users), note


SCRIPTS = []  # (path, text) of shell / PowerShell / batch scripts: they read .env variables too

# configuration read in code by literal name: (regex with the name in group "k", source label)
CODE_READS = [
    (r"\bEnvironment\s*\.\s*GetEnvironmentVariable\s*\(\s*\"(?P<k>[^\"]+)\"\s*(?:,\s*EnvironmentVariableTarget\s*\.\s*(?P<t>\w+))?",
     "environment variable"),
    (r"\b(?:os\.environ\s*(?:\[|\.get\s*\()|os\.getenv\s*\(|System\.getenv\s*\(|os\.Getenv\s*\(|ENV\s*\[|getenv\s*\()\s*[\"'](?P<k>[^\"']+)[\"']",
     "environment variable"),
    (r"\bprocess\.env(?:\.(?P<k>[A-Za-z_]\w*)|\[\s*[\"'](?P<k2>[^\"']+)[\"']\s*\])", "environment variable"),
    (r"\bAppSettings\s*(?:\[|\.Get\s*\()\s*\"(?P<k>[^\"]+)\"", "appSettings"),
    (r"\bConnectionStrings\s*\[\s*\"(?P<k>[^\"]+)\"|\bGetConnectionString\s*\(\s*\"(?P<k2>[^\"]+)\"", "connection string"),
    (r"\b(?:_?[cC]onfig(?:uration)?|_?[cC]fg)\s*\[\s*\"(?P<k>[^\"]+)\"\s*\]|\bGetValue\s*<[^>]+>\s*\(\s*\"(?P<k2>[^\"]+)\"", "IConfiguration"),
]
MEMBER = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:(?:public|private|protected|internal|static|readonly|const|async|override|virtual|"
                    r"Public|Private|Friend|Shared|ReadOnly|def|function|func)\s+)+[\w<>\[\],.? ]*?\b(\w+)\s*(?:\(|\{|=>|=|$)")


def member_at(text, pos):
    """Name of the member (method, property, field) declared nearest above pos: the code that reads the key."""
    lines = text[:pos].splitlines()[-40:]
    for ln in reversed(lines):
        m = MEMBER.match(ln)
        if m:
            return m.group(1)
    return ""


def env_helpers(code):
    """{method name: target} for wrappers that pass their string parameter straight to Environment.GetEnvironmentVariable
    (static string Env(string name) => Environment.GetEnvironmentVariable(name, EnvironmentVariableTarget.Machine))."""
    out = {}
    rx = re.compile(r"\b(\w+)\s*\(\s*string\s+(\w+)[^)]*\)\s*(?:=>|\{)[^{}]{0,400}?Environment\s*\.\s*GetEnvironmentVariable\s*\(\s*(\w+)"
                    r"\s*(?:,\s*EnvironmentVariableTarget\s*\.\s*(\w+))?")
    for _, t in code:
        if "GetEnvironmentVariable" in t:
            for m in rx.finditer(t):
                if m.group(2) == m.group(3):
                    out[m.group(1)] = (m.group(4) or "").lower()
    return out


def code_reads(code):
    """{(key, source): [(file, line, member)]} for configuration read in code by literal name."""
    found = defaultdict(list)
    helpers = env_helpers(code)
    pats = [(re.compile(p), s) for p, s in CODE_READS]
    if helpers:
        pats.append((re.compile(r"(?<![\w.])(?P<h>" + "|".join(map(re.escape, helpers)) + r")\s*\(\s*\"(?P<k>[^\"]+)\"\s*\)"),
                     "environment variable"))
    extra = OPT.get("env_helpers", [])  # adapter option: more wrapper names whose first string argument is a variable name
    if extra:
        pats.append((re.compile(r"(?<![\w.])(?:" + "|".join(map(re.escape, extra)) + r")\s*\(\s*\"(?P<k>[^\"]+)\""), "environment variable"))
    for fp, t in code:
        for rx, src in pats:
            for m in rx.finditer(t):
                gd = m.groupdict()
                k = gd.get("k") or gd.get("k2")
                if not k or len(k) > 120:
                    continue
                target = gd.get("t") or (helpers.get(gd["h"]) if gd.get("h") else "")
                label = src + (f" ({target.lower()})" if target else "")
                found[(k, label)].append((fp, t.count("\n", 0, m.start()) + 1, member_at(t, m.start())))
    return found


def main():
    from _scan import vendored  # copied libraries (highcharts reads NODE_ENV) are not the application's configuration
    lib = vendored()
    from _scan import kit_dirs  # the skill's own output inside the repository is not project code
    kits = kit_dirs()
    cfgs, code, raw = [], [], []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")
                   and os.path.relpath(os.path.join(d, x), ROOT).replace("\\", "/").lower() not in kits]
        for f in files:
            p = os.path.join(d, f)
            r = os.path.relpath(p, ROOT).replace("\\", "/")
            if CONFIG.search(f) and "/Views/" not in r:
                cfgs.append((r, p))
            elif f.lower().endswith((".ps1", ".psm1", ".sh", ".bash", ".bat", ".cmd")):
                try:
                    SCRIPTS.append((r, read(p)))
                except OSError:
                    pass
            elif f.endswith(CODE_EXT) and not re.search(r"\.min\.js$|\.designer\.cs$", f, re.I) and r not in lib:
                try:
                    t = read(p)
                    raw.append((r, t))
                    if f.lower().endswith(C_COMMENTS):  # a commented-out GetEnvironmentVariable(...) is not a reader
                        t = strip_comments(t, vb=f.lower().endswith(".vb"))
                    code.append((r, t))
                except OSError:
                    pass
    cfg_text = {r: read(p) for r, p in cfgs}
    creds = source_credentials(raw + list(cfg_text.items()) + SCRIPTS)
    tracked = git_tracked() if creds else None
    out = ["# Configuration keys", "",
           "Every configuration key found in the source tree, with the code files that read it. **Values are never "
           "reproduced**: configuration often holds credentials, which belong in a secret store, not in documentation. "
           "A file is listed as a reader only when it names the whole key (`\"Section:Key\"`, `AppSettings[\"Key\"]`), "
           "the connection-string name (`GetConnectionString(\"Name\")`), or the section and the key together; keys the "
           ".NET host reads itself, compose settings and `.env` variables used by other config files are labelled as such.", "",
           '<a id="index"></a>', "", "| File | Keys |", "| --- | ---: |"]
    body, total = [], 0
    for r, p in sorted(cfgs):
        ks = keys_of(p)
        if not ks:
            continue
        total += len(ks)
        out.append(f"| [`{r}`](#{slug('cfgfile', r)}) | {len(ks)} |")
        body += ["", f'<a id="{slug("cfgfile", r)}"></a>', "", f"## {r}", "", f"File: `{r}` · [↑ Back to index](#index)", "",
                 "| Key | Type | Read by |", "| --- | --- | --- |"]
        for kind, k in ks:
            users, note = readers(r, kind, k, code, cfg_text)
            shown = ", ".join(f"`{u.split('/')[-1]}`" for u in users[:6]) + (f" (+{len(users) - 6})" if len(users) > 6 else "")
            shown = "; ".join(x for x in (shown, note) if x)
            body.append(f'| <a id="{slug("cfg", r, k)}"></a>`{k}` | {kind} | {shown or "_no reader found in code_ (a framework, deployment tool or reflection may still read it)"} |')
    # configuration the code reads by name: environment variables above all, which no config file in the repository lists
    in_files = defaultdict(list)
    for r, p in cfgs:
        for _, k in keys_of(p):
            in_files[k.lower()].append(r)
            in_files[re.split(r":|__|\.", k)[-1].lower()].append(r)
    # keys a config file declares already have their readers in that file's table: keep env vars and undeclared keys only
    reads = {ks: v for ks, v in code_reads(code).items() if ks[1].startswith("environment") or ks[0].lower() not in in_files}
    if reads:
        env = sum(1 for k, s in reads if s.startswith("environment"))
        out.append(f"| [Read in code](#cfg-code) | {len(reads)} |")
        body += ["", '<a id="cfg-code"></a>', "", "## Read in code", "", "[↑ Back to index](#index)", "",
                 f"Configuration the code reads by literal name ({env} environment variables). Environment variables live on the "
                 "server (the target in brackets: machine, user or process), not in the repository: the deployment has to set "
                 "every one of them. \"Also in\" names config files of the repository that declare the same key.", "",
                 "| Key | Source | Read by | Also in |", "| --- | --- | --- | --- |"]
        for (k, src), sites in sorted(reads.items(), key=lambda kv: (not kv[0][1].startswith("environment"), kv[0][0].lower())):
            shown = ", ".join(f"`{f.split('/')[-1]}:{ln}`" + (f" ({m})" if m else "") for f, ln, m in sites[:4])
            shown += f" (+{len(sites) - 4})" if len(sites) > 4 else ""
            also = sorted(set(in_files.get(k.lower(), []) or in_files.get(re.split(r":|__", k)[-1].lower(), [])))
            body.append(f'| <a id="{slug("cfg-code", k)}"></a>`{k}` | {src} | {shown} | '
                        + (", ".join(f"`{a}`" for a in also[:3]) or "—") + " |")
        total += len(reads)
    if creds:
        out.append(f"| [Credentials written in the source](#cfg-credentials) | {len(creds)} |")
        body += ["", '<a id="cfg-credentials"></a>', "", "## Credentials written in the source", "", "[↑ Back to index](#index)", "",
                 f"{len(creds)} places where a credential appears to be written into a file of the repository, found by its shape "
                 "(key prefixes such as `sk_live_` / `whsec_` / `AKIA`, `Password=` in a connection string, quoted secret "
                 "literals). **Values are not reproduced.** A commented-out credential is still readable by anyone with the "
                 "repository or its history. Confirm each one in code: a real one is a security finding (rotate it, move it to "
                 "the secret store, remove it from the file and from version-control history). *In git* says whether git tracks "
                 "the file: `no` is a local file kept out of the repository (still worth checking on shared machines), `unknown` "
                 "means the source is not a git checkout.", "",
                 "| Kind | Where | In a comment | In git |", "| --- | --- | --- | --- |"]
        body += [f"| {kind} | `{f}:{ln}` | {'yes' if com else 'no'} | {'unknown' if tracked is None else 'yes' if f in tracked else 'no'} |"
                 for kind, f, ln, com in creds]
    agent = os.path.join(CFG.get("docs_dir", "docs"), "agent")
    os.makedirs(agent, exist_ok=True)
    open(os.path.join(agent, "source-credentials.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(
        [{"kind": k, "file": f, "line": ln, "comment": c, "in_git": None if tracked is None else f in tracked}
         for k, f, ln, c in creds], ensure_ascii=False, indent=1))
    open(os.path.join(agent, "config-reads.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(
        [{"key": k, "source": s, "reads": [{"file": f, "line": ln, "member": m} for f, ln, m in v]} for (k, s), v in sorted(reads.items())],
        ensure_ascii=False, indent=1))
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "configuration.md"), "w", encoding="utf-8", newline="\n").write("\n".join(out + body) + "\n")
    env_n = sum(1 for k, s in reads if s.startswith("environment"))
    stat("configuration", keys=total, files=len(cfgs), env_vars=env_n, read_in_code=len(reads), source_credentials=len(creds))
    print(f"config-reference: {total} keys in {sum(1 for _ in cfgs)} files" + (f"; {len(reads)} read in code ({env_n} environment variables)" if reads else "")
          + (f"; {len(creds)} credentials written in the source (values not shown)" if creds else ""))


if __name__ == "__main__":
    main()
