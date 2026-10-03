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

CFG = json.load(open("codebase-docs.json", encoding="utf-8"))
ROOT = os.environ.get("DOCS_SOURCE_ROOT") or CFG.get("source_root", ".")
OUT = os.path.join(CFG.get("docs_dir", "docs"), "reference")
SKIP = {"bin", "obj", "node_modules", "packages", ".git", "dist", "build", "vendor", "graphify-out", ".vs", "__pycache__"}
CONFIG = re.compile(r"(?i)^(web|app)\.config$|^appsettings.*\.json$|^\.env(\..+)?$|^application(-\w+)?\.(properties|ya?ml)$|"
                    r"^(config|settings)(\.\w+)?\.(json|ya?ml|toml)$|^settings\.py$|^docker-compose.*\.ya?ml$")
CODE_EXT = (".cs", ".vb", ".cshtml", ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".kt", ".go", ".rb", ".php", ".rs")


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


def main():
    cfgs, code = [], []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
        for f in files:
            p = os.path.join(d, f)
            r = os.path.relpath(p, ROOT).replace("\\", "/")
            if CONFIG.search(f) and "/Views/" not in r:
                cfgs.append((r, p))
            elif f.endswith(CODE_EXT) and not re.search(r"\.min\.js$|\.designer\.cs$", f, re.I):
                try:
                    code.append((r, read(p)))
                except OSError:
                    pass
    out = ["# Configuration keys", "",
           "Every configuration key found in the source tree, with the code files that read it. **Values are never "
           "reproduced**: configuration often holds credentials, which belong in a secret store, not in documentation.", "",
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
            leaf = re.split(r"[:.]", k)[-1]
            users = sorted({fp for fp, t in code if f'"{leaf}"' in t or f"'{leaf}'" in t or re.search(rf"\b{re.escape(leaf)}\b", t) and len(leaf) > 5})
            shown = ", ".join(f"`{u.split('/')[-1]}`" for u in users[:6]) + (f" (+{len(users) - 6})" if len(users) > 6 else "")
            body.append(f'| <a id="{slug("cfg", r, k)}"></a>`{k}` | {kind} | {shown or "_not referenced by name in code_"} |')
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "configuration.md"), "w", encoding="utf-8", newline="\n").write("\n".join(out + body) + "\n")
    print(f"config-reference: {total} keys in {sum(1 for _ in cfgs)} files")


if __name__ == "__main__":
    main()
