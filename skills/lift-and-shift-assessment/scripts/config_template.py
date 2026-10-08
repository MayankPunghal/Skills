"""Configuration templates for a lift-and-shift: which setting holds which address, path or credential, and a tokenised copy of every
configuration file so CI can fill in the AWS values (deterministic, standard library only, client code is only read).

    python <skill>/scripts/config_template.py [--repo NAME] [--token-format "${NAME}"]

What it finds, per repository: every setting whose value changes when the application runs on a new server on AWS:
  connection strings, passwords / keys / tokens, internal IP addresses and host names, company DNS names, UNC shares, folders on other
  drives, certificate thumbprints, machineKey values. Public third-party URLs, C:\\ folders and public IPs are listed as "kept".
What it writes (never inside the client repository):
  assessment/configtpl/<repo>.json                        variables, every replaced occurrence (file, line, setting), kept values, manual cases
  assessment/configtpl/templates/<repo>/<file>.tmpl       the file with each replaceable value swapped for a token such as ${REDIS_HOST}
  assessment/configtpl/ci/render-config.ps1               fills the tokens from CI variables (escapes XML / JSON), fails on a missing one
  assessment/configtpl/ci/variables.example.env           every variable name with an empty value and what it holds
  assessment/configtpl/ci/gitlab-ci.example.yml           a deploy job that runs the script
  assessment/report/config-variables.csv, config-placeholders.csv   (written by build_report.py)
Secret values are replaced by the token and never stored, printed or hashed into any output; a secret that several projects share
becomes one variable (the comparison uses an in-memory hash that is not written anywhere).
"""
import argparse
import hashlib
import json
import os
import re
from collections import OrderedDict, defaultdict

import _config as C
import scan_repo as _scan
from _common import OUT, SOURCE_DIR_SKIP, load_config, mark_step, read_json, read_text, rel, utf8_stdout, write_json

TOKEN_FORMATS = ("${NAME}", "#{NAME}#", "{{NAME}}", "__NAME__", "%NAME%")
DIR = os.path.join(OUT, "configtpl")

EXTRA_SECRET = re.compile(r"(?i)(validationkey|decryptionkey|connectionpassword|privatekey|sharedaccesssignature|sastoken|encryptionkey|signingkey|clientsecret|apikey|api_key|accesskey)")
THUMB_KEY = re.compile(r"(?i)thumbprint")
URL_CRED = re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s/:@\"'<>]+:[^\s/@\"'<>]+@")
CONN_VALUE = re.compile(r"(?i)\b(data source|server|host|initial catalog|database|uid|user id|provider)\s*=")
SIMPLE_VALUE = re.compile(r"(?i)^(true|false|yes|no|on|off|none|null|enabled|disabled|\d{1,4}|)$")
TOKEN_CLASSES = {"private IP": "Server address (internal IP)", "internal host name": "Server address (internal host name)", "company domain": "Company DNS name",
                 "UNC share": "File share (UNC path)", "local drive path": "Folder on another drive", "unix path": "Folder path (Linux)"}
KIND_OWNER = {
    "Database connection string": ("DB team (server, instance and login on AWS)", "devops"),
    "Password, key or token": ("Security (new secret in the secret store); .NET team keeps the setting name", "security"),
    "URL with credentials": ("Security (new credential) and DevOps (target address)", "security"),
    "Server address (internal IP)": ("DevOps (the server's new address, or a route to the old one)", "devops"),
    "Server address (internal host name)": ("DevOps (DNS name that resolves from AWS)", "devops"),
    "Company DNS name": ("DevOps (DNS record for the new address)", "devops"),
    "File share (UNC path)": ("DevOps (file server on AWS, e.g. FSx for Windows)", "devops"),
    "Folder on another drive": (".NET team with DevOps (volume layout on the EC2 host)", "dotnet"),
    "Folder path (Linux)": (".NET team with DevOps (volume layout on the EC2 host)", "dotnet"),
    "Certificate thumbprint": ("DevOps (certificate installed on the EC2 host)", "devops"),
    "Machine key": (".NET team (same value on every server of one application)", "dotnet"),
}
SEARCH_ENGINES = (("mongo", "MongoDB"), ("mysql", "MySQL"), ("npgsql|postgres", "PostgreSQL"), ("oracle", "Oracle"), ("sqlite", "SQLite"))


def fmt_token(fmt, name):
    return fmt.replace("NAME", name)


GENERIC = {"ADD", "ADDRESS", "VALUE", "PASSWORD", "USERNAME", "USER", "HOST", "URL", "CREDENTIALS", "SERVER", "PATH", "KEY", "TOKEN", "SECRET", "NAME", "PORT", "ENDPOINT", "SETTING"}
BASE_FILE = re.compile(r"(?i)^(web|app|appsettings|machine)$")


def var_name(key, prefix="", file_name="", project=""):
    k = re.sub(r"(?i)^(appsettings|connectionstrings)[./:]", lambda m: "CONN_" if m.group(1).lower() == "connectionstrings" else "", key)
    k = re.sub(r"[^A-Za-z0-9]+", "_", k).strip("_").upper() or "VALUE"
    k = re.sub(r"_+", "_", k)
    if k in GENERIC or k.split("_")[0] in ("ADD", "APPLICATIONSETTINGS"):  # 'Password' or 'add@address' alone says nothing: add the file or project it is in
        stem = os.path.splitext(os.path.basename(file_name))[0]
        stem = re.sub(r"[^A-Za-z0-9]+", "_", project if BASE_FILE.match(stem.split(".")[0]) else stem).strip("_").upper()[:24]
        k = (stem + "_" + k) if stem else k
    return (prefix + k)[:64]


def sig_of(value, secret):
    v = value.strip()
    return ("s:" + hashlib.sha1(v.encode("utf-8", "ignore")).hexdigest()[:12]) if secret else ("v:" + v.lower())


def decide(key, value, company, host_kind, private_ip):
    """(kind, replace?, detail) for one setting value; kind None when the value is not environment-specific."""
    v = value.strip()
    if not v or SIMPLE_VALUE.match(v):
        return None, False, ""
    last = re.split(r"[./@:]", key)[-1]
    if C.PLACEHOLDER.search(v) and not C.URL_RX.search(v):
        return "placeholder", False, "already a placeholder filled at deploy time"
    if URL_CRED.search(v):
        return "URL with credentials", True, ""
    if THUMB_KEY.search(last) and re.fullmatch(r"[0-9A-Fa-f ]{20,}", v):
        return "Certificate thumbprint", True, ""
    if re.fullmatch(r"(?i)(validationkey|decryptionkey)", last):
        return "Machine key", True, ""
    if (C.SECRET_KEY.search(last) or EXTRA_SECRET.search(last)) and len(v) >= 3:
        return "Password, key or token", True, ""
    if re.search(r"(?i)@(providername|name|type)$", key):
        return None, False, ""
    if re.match(r"(?i)connectionstrings[./:]", key) and "@" in key and not key.lower().endswith("@connectionstring"):
        return None, False, ""
    if re.match(r"(?i)connectionstrings[./:]", key) or (CONN_VALUE.search(v) and ";" in v):
        eng = next((n for rx, n in SEARCH_ENGINES if re.search(rx, v + " " + key, re.I)), "SQL Server")
        m = C.CONN_HOST.search(v)
        host = m.group(1) if m else ""
        win = bool(re.search(r"(?i)integrated security\s*=\s*(true|sspi|yes)|trusted_connection\s*=\s*(true|yes|sspi)", v))
        return "Database connection string", True, f"{eng}{'; Windows authentication' if win else ''}{('; server ' + host) if host and host != '.' else ''}"
    items = C._items(key, v, "", company, host_kind, private_ip)
    for typ, target, port, scheme, cls in items:
        if cls in TOKEN_CLASSES:
            if cls == "local drive path" and re.match(r"(?i)^c:", target):
                return "kept", False, f"C:\\ folder ({target[:80]}): the same path exists on a Windows EC2 host"
            return TOKEN_CLASSES[cls], True, f"{target}{(':' + str(port)) if port and cls not in ('UNC share', 'local drive path', 'unix path') else ''}"[:160]
    for typ, target, port, scheme, cls in items:
        if cls in ("public IP", "external service"):
            return "kept", False, f"{cls}: {target}{(':' + str(port)) if port else ''} (no change unless the provider allow-lists IP addresses)"
    return None, False, ""


def replace_in_line(line, value, token):
    """Swap the raw value in one text line for the token; None when the value is not found in that form."""
    cands = [value]
    for alt in (value.replace("\\", "\\\\"), json.dumps(value)[1:-1], value.replace("&", "&amp;")):
        if alt not in cands:
            cands.append(alt)
    for cand in cands:
        for q in ('"', "'"):
            needle = q + cand + q
            if needle in line:
                return line.replace(needle, q + token + q, 1)
        if ">" + cand + "<" in line:
            return line.replace(">" + cand + "<", ">" + token + "<", 1)
        s = line.rstrip("\r\n")
        if s.rstrip().endswith(cand) and re.search(r"[=:]\s*" + re.escape(cand) + r"\s*$", s):
            i = s.rstrip().rfind(cand)
            return s[:i] + token + line[len(s.rstrip()):]
    return None


def config_files(repo_root, inv, cfg):
    skip = SOURCE_DIR_SKIP | {s.lower() for s in cfg.get("exclude_dirs", [])}
    oos = [os.path.normpath(os.path.join(repo_root, x)) for x in (inv.get("scope") or {}).get("skip_dirs", [])]
    pdirs = sorted(((os.path.normpath(os.path.dirname(os.path.join(repo_root, p["path"]))), p["name"]) for p in inv["projects"]), key=lambda x: -len(x[0]))
    for d, dirs, fns in os.walk(repo_root):
        dirs[:] = sorted(x for x in dirs if x.lower() not in skip and not x.startswith(".") and os.path.normpath(os.path.join(d, x)) not in oos)
        for fn in sorted(fns):
            ext = os.path.splitext(fn)[1].lower()
            low = fn.lower()
            if not (ext in C.CFG_EXT or low.endswith(".env")) or C.SKIP_FILE.search(fn) or ext == ".pubxml" or low == "nuget.config":
                continue
            if low.startswith(("stylecop", ".editorconfig", "coderabbit", ".coderabbit")):
                continue
            if ext in (".yml", ".yaml") and not re.search(r"(?i)(appsettings|config|settings|compose|application|values|env)", fn):
                continue
            path = os.path.join(d, fn)
            try:
                if os.path.getsize(path) > 800_000:
                    continue
            except OSError:
                continue
            proj = next((nm for pd, nm in pdirs if os.path.normpath(path).startswith(pd + os.sep)), "(repository)")
            yield path, fn, ext, proj


def scan(repo, inv, cfg, fmt):
    root = inv["root"]
    company = [d.lower() for d in cfg.get("company_domains", [])]
    prefix = cfg.get("config_prefix", "")
    files, occ, kept, manual = OrderedDict(), [], [], []
    for path, fn, ext, proj in config_files(root, inv, cfg):
        try:
            text = read_text(path)
        except OSError:
            continue
        gen = C._json_lines(text) if ext == ".json" else C._xml_lines(text) if ext in (".config", ".xml", ".settings") else C._kv_lines(text, ext)
        lines = text.split("\n")
        env = C.env_of(fn)
        env = "" if env == "default" else env  # the base file; Web.Release.config and appsettings.Production.json are environment variants
        todo = []
        for line_no, key, value in gen:
            if C.NOISE_KEY.search(key):
                continue
            kind, replace, detail = decide(key, value, company, _scan.host_kind, _scan.private_ip)
            if kind is None or kind == "placeholder":
                continue
            if not replace:
                kept.append({"project": proj, "file": rel(path, root), "line": line_no, "setting": key[:120], "reason": detail, "environment": env})
                continue
            todo.append((line_no, key, value, kind, detail))
        if not todo:
            continue
        file_rel = rel(path, root)
        n = 0
        for line_no, key, value, kind, detail in todo:
            secret = kind in ("Password, key or token", "URL with credentials", "Machine key", "Database connection string")
            rec = {"project": proj, "file": file_rel, "line": line_no, "setting": key[:120], "kind": kind, "environment": env,
                   "base": var_name(key, prefix, fn, proj), "sig": sig_of(detail if kind in TOKEN_CLASSES.values() and detail else value, secret or kind == "Certificate thumbprint"),
                   "example": "" if secret or kind == "Certificate thumbprint" else detail, "detail": detail if kind == "Database connection string" else "",
                   "line_text": None}
            i = line_no - 1
            if not (0 <= i < len(lines)):
                manual.append({**{k: rec[k] for k in ("project", "file", "line", "setting", "kind", "environment")}, "why": "line not found"})
                continue
            rec["_i"], rec["_value"] = i, value
            occ.append(rec)
            n += 1
        if n:
            files[file_rel] = {"project": proj, "environment": env, "ext": ext, "lines": lines, "path": path}
    return files, occ, kept, manual


def name_variables(occ):
    """Variable names: the setting name; qualified by project when projects hold different values for the same setting."""
    by_base = defaultdict(lambda: defaultdict(set))
    for o in occ:
        by_base[o["base"]][o["project"]].add(o["sig"] if o["environment"] == "" else None)
    common = {}  # the value most projects hold keeps the plain name; a project that holds another value gets its own variable
    for base, projs in by_base.items():
        sets = [frozenset(s - {None}) for s in projs.values() if s - {None}]
        common[base] = max(set(sets), key=sets.count) if sets else frozenset()
    for o in occ:
        mine = frozenset(by_base[o["base"]][o["project"]] - {None})
        differs = bool(mine) and mine != common[o["base"]]
        o["name"] = (re.sub(r"[^A-Za-z0-9]+", "_", o["project"]).strip("_").upper()[:20] + "_" + o["base"]) if differs else o["base"]
    # two different values for one name inside a project's non-environment files: number them
    seen = defaultdict(dict)
    for o in occ:
        if o["environment"] == "":
            d = seen[(o["project"], o["name"])]
            idx = d.setdefault(o["sig"], len(d) + 1)
            if idx > 1:
                o["name"] = f"{o['name']}_{idx}"
    return occ


def build(repo, inv, cfg, fmt):
    files, occ, kept, manual = scan(repo, inv, cfg, fmt)
    occ = name_variables(occ)
    out_dir = os.path.join(DIR, "templates", repo)
    # rewrite lines: one replacement per occurrence
    changed = defaultdict(dict)
    for o in occ:
        f = files[o["file"]]
        lines = f["lines"]
        token = fmt_token(fmt, o["name"])
        new = replace_in_line(changed[o["file"]].get(o["_i"], lines[o["_i"]]), o["_value"], token)
        if new is None:
            manual.append({"project": o["project"], "file": o["file"], "line": o["line"], "setting": o["setting"], "kind": o["kind"], "environment": o["environment"],
                           "why": "value not found in that form on the line (multi-line or escaped): replace by hand"})
            o["done"] = False
            continue
        changed[o["file"]][o["_i"]] = new
        o["done"] = True
    for fr, edits in changed.items():
        f = files[fr]
        lines = list(f["lines"])
        for i, t in edits.items():
            lines[i] = t
        dst = os.path.join(out_dir, *fr.split("/")) + ".tmpl"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(lines))
    done = [o for o in occ if o.get("done")]
    variables = OrderedDict()
    for o in done:
        v = variables.setdefault(o["name"], {"name": o["name"], "kind": o["kind"], "projects": set(), "files": set(), "environments": set(), "example": "", "detail": "", "setting": o["setting"]})
        v["projects"].add(o["project"])
        v["files"].add(o["file"])
        if o["environment"]:
            v["environments"].add(o["environment"])
        if not v["example"] and o["example"] and o["environment"] == "":
            v["example"] = o["example"]
        v["detail"] = v["detail"] or o["detail"]
    vlist = []
    for v in variables.values():
        owner = KIND_OWNER[v["kind"]]
        vlist.append({"name": v["name"], "token": fmt_token(fmt, v["name"]), "kind": v["kind"], "setting": v["setting"], "projects": sorted(v["projects"]), "files": len(v["files"]),
                      "environments": sorted(v["environments"]), "current_target": v["example"], "detail": v["detail"], "supplied_by": owner[0], "owner": owner[1]})
    occ_out = [{k: o[k] for k in ("project", "file", "line", "setting", "kind", "environment", "name")} for o in done]
    res = {"repo": repo, "token_format": fmt, "variables": vlist, "occurrences": occ_out, "kept": kept, "manual": manual,
           "files": sorted({o["file"] for o in done}), "templates_dir": os.path.relpath(out_dir).replace("\\", "/")}
    write_json(os.path.join(DIR, f"{repo}.json"), res)
    return res


PS1 = r'''<#
.SYNOPSIS  Fills the configuration templates with the values of one environment.
.DESCRIPTION
  Reads every *.tmpl file under -TemplateRoot, replaces each token (__FORMAT__) with the CI variable of the same name
  (environment variable, or a KEY=VALUE line in -VariablesFile), and writes the file without the .tmpl suffix under -OutputRoot.
  Values are escaped for the file type (XML / JSON). A token with no value stops the run and lists every missing name.
  Generated by migration-assessment; the values themselves live only in the CI system, never in the repository.
.EXAMPLE   ./render-config.ps1 -TemplateRoot configtpl/templates/ws -OutputRoot publish/ws
#>
param(
  [Parameter(Mandatory)][string]$TemplateRoot,
  [Parameter(Mandatory)][string]$OutputRoot,
  [string]$VariablesFile,
  [switch]$AllowMissing
)
$ErrorActionPreference = 'Stop'
$prefix = '__PREFIX__'
$suffix = '__SUFFIX__'
$pattern = [regex]::Escape($prefix) + '([A-Za-z0-9_]+)' + [regex]::Escape($suffix)
$vars = @{}
if ($VariablesFile) {
  Get-Content -LiteralPath $VariablesFile | Where-Object { $_ -match '^\s*[A-Za-z0-9_]+\s*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; $vars[$k.Trim()] = $v.Trim().Trim('"')
  }
}
function Get-Value([string]$name) {
  if ($vars.ContainsKey($name)) { return $vars[$name] }
  return [Environment]::GetEnvironmentVariable($name)
}
function Protect-Value([string]$value, [string]$ext) {
  switch ($ext) {
    '.json' { return ($value -replace '\\', '\\\\' -replace '"', '\"') }
    default { return [System.Security.SecurityElement]::Escape($value) }
  }
}
$missing = New-Object System.Collections.Generic.HashSet[string]
$files = Get-ChildItem -LiteralPath $TemplateRoot -Recurse -Filter '*.tmpl' -File
$root = (Resolve-Path -LiteralPath $TemplateRoot).Path
$rendered = @{}
foreach ($f in $files) {
  $ext = [IO.Path]::GetExtension([IO.Path]::GetFileNameWithoutExtension($f.Name)).ToLower()
  $text = [IO.File]::ReadAllText($f.FullName)
  $rendered[$f.FullName] = [regex]::Replace($text, $pattern, {
    param($m)
    $name = $m.Groups[1].Value
    $val = Get-Value $name
    if ([string]::IsNullOrEmpty($val)) { [void]$missing.Add($name); return $m.Value }
    return (Protect-Value $val $ext)
  })
}
if ($missing.Count -gt 0 -and -not $AllowMissing) {
  Write-Error ("Missing values for: " + (($missing | Sort-Object) -join ', ') + ". Nothing was written.")
  exit 1
}
foreach ($f in $files) {
  $relative = $f.FullName.Substring($root.Length).TrimStart([char]92, [char]47)
  $target = Join-Path $OutputRoot ($relative -replace '\.tmpl$', '')
  New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
  [IO.File]::WriteAllText($target, $rendered[$f.FullName], (New-Object System.Text.UTF8Encoding($false)))
}
Write-Host "Rendered $($files.Count) file(s) to $OutputRoot"
'''

GITLAB = '''# Example only: adapt stage names, runner tags and paths. The variables are set per environment in GitLab
# (Settings > CI/CD > Variables, scope = environment; mark secrets Masked and Protected).
deploy-aws-config:
  stage: deploy
  tags: [windows]
  script:
    - pwsh -File configtpl/ci/render-config.ps1 -TemplateRoot configtpl/templates/<repo> -OutputRoot publish/<repo>
    # then copy publish/<repo> to the EC2 host with your normal deployment step
  environment:
    name: $CI_ENVIRONMENT_NAME
'''


def write_ci(results, fmt):
    d = os.path.join(DIR, "ci")
    os.makedirs(d, exist_ok=True)
    pre, suf = fmt.split("NAME")
    with open(os.path.join(d, "render-config.ps1"), "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(PS1.replace("__PREFIX__", pre.replace("'", "''")).replace("__SUFFIX__", suf.replace("'", "''")).replace("__FORMAT__", fmt))
    allv = OrderedDict()
    for r in results:
        for v in r["variables"]:
            allv.setdefault(v["name"], v)
    with open(os.path.join(d, "variables.example.env"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# One line per CI variable. Fill the values in the CI system per environment (dev / qa / prod); never commit real values.\n")
        for v in sorted(allv.values(), key=lambda x: (x["kind"], x["name"])):
            fh.write(f"# {v['kind']}: {v['setting']} (supplied by: {v['supplied_by']})\n{v['name']}=\n")
    with open(os.path.join(d, "gitlab-ci.example.yml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(GITLAB)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Tokenised configuration templates and the list of CI variables for a lift-and-shift.")
    ap.add_argument("--repo")
    ap.add_argument("--token-format", help="one of: " + "  ".join(TOKEN_FORMATS) + " (default: assessment.json config_token_format, else ${NAME})")
    a = ap.parse_args()
    root, cfg = load_config()
    C.ensure_company_domains(root, cfg)
    os.chdir(root)
    import intake as _intake
    _intake.require(cfg, root, ['before_scan', 'after_scan'], "config_template.py")
    fmt = a.token_format or cfg.get("config_token_format") or "${NAME}"
    if fmt not in TOKEN_FORMATS:
        raise SystemExit(f"--token-format must be one of {TOKEN_FORMATS}")
    if a.token_format:
        cfg["config_token_format"] = fmt
    state = read_json(os.path.join(OUT, "state.json"), {"repos": {}})
    repos = [a.repo] if a.repo else sorted(r for r, v in state["repos"].items() if v.get("scope") != "out")
    results = []
    for repo in repos:
        inv = read_json(os.path.join(OUT, "inventory", f"{repo}.json"))
        if not inv or not (inv.get("scope") or {}).get("in_scope", True):
            continue
        res = build(repo, inv, cfg, fmt)
        results.append(res)
        kinds = {}
        for v in res["variables"]:
            kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
        print(f"{repo}: {len(res['variables'])} variables in {len(res['files'])} files ({', '.join(f'{k} {n}' for k, n in sorted(kinds.items()))}); "
              f"{len(res['kept'])} values kept, {len(res['manual'])} to replace by hand")
    if results:
        write_ci(results, fmt)
    mark_step(root, "configtpl")
    print(f"templates: {DIR}/templates, CI helpers: {DIR}/ci")


if __name__ == "__main__":
    main()
