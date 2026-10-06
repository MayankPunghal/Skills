"""Generic configuration reference: every configuration KEY NAME (never a value) per config file, with the code files
that read it. Formats: web.config / app.config (appSettings, connectionStrings), appsettings*.json and other *.json
config, .env*, application.properties, *.yml / *.yaml (keys by indentation), *.toml, settings.py (UPPER_CASE names).

Writes docs/reference/configuration.md (anchors cfg-<file>-<key>). Run by build_site.py (cwd = workspace root).
"""
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

CFG = json.load(open("codebase-docs.json", encoding="utf-8"))
ROOT = os.environ.get("DOCS_SOURCE_ROOT") or CFG.get("source_root", ".")
OUT = os.path.join(CFG.get("docs_dir", "docs"), "reference")
SKIP = {"bin", "obj", "node_modules", "packages", ".git", "dist", "build", "vendor", "graphify-out", ".vs", "__pycache__"}
CONFIG = re.compile(r"(?i)^(web|app)\.config$|^appsettings.*\.json$|^\.env(\..+)?$|^application(-\w+)?\.(properties|ya?ml)$|"
                    r"^(config|settings)(\.\w+)?\.(json|ya?ml|toml)$|^settings\.py$|^docker-compose.*\.ya?ml$")
CODE_EXT = (".cs", ".vb", ".cshtml", ".vbhtml", ".razor", ".aspx", ".ascx", ".asax", ".master", ".py", ".ts", ".tsx", ".js",
            ".jsx", ".java", ".kt", ".go", ".rb", ".php", ".rs")
# keys the .NET host or framework reads itself (no code names them): said so instead of "no reader found"
FRAMEWORK = re.compile(r"(?i)^(Logging|AllowedHosts|Kestrel|Urls|DetailedErrors|HostFilteringOptions|HttpsRedirection|ForwardedHeaders|"
                       r"ASPNETCORE_\w+|DOTNET_\w+|ValidationSettings:UnobtrusiveValidationMode|webpages:\w+|aspnet:\w+|"
                       r"ClientValidationEnabled|UnobtrusiveJavaScriptEnabled)\b")


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


def main():
    cfgs, code = [], []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
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
            elif f.endswith(CODE_EXT) and not re.search(r"\.min\.js$|\.designer\.cs$", f, re.I):
                try:
                    code.append((r, read(p)))
                except OSError:
                    pass
    cfg_text = {r: read(p) for r, p in cfgs}
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
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "configuration.md"), "w", encoding="utf-8", newline="\n").write("\n".join(out + body) + "\n")
    stat("configuration", keys=total, files=len(cfgs))
    print(f"config-reference: {total} keys in {sum(1 for _ in cfgs)} files")


if __name__ == "__main__":
    main()
