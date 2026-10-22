"""Server-hosted services to AWS managed services: what the code uses and the code-side work to switch.

    py -X utf8 aws_native.py --root <repo> [--library-source <dir> ...] [--facts <facts.json>]
                             [--choices '{"aerospike": "dynamodb"}'] [--factors '{"code": [0.3, 0.5], "redesign": [0.7, 1.0]}']
                             --out <dir> [--name <key>]

For each service in aws_native.json (Redis, Memcached, Aerospike, Elasticsearch, SMTP, SFTP/FTP, file shares, MongoDB,
RabbitMQ, Kafka, MSMQ, hosted logging, session state) it finds:
  - packages and binary references that are clients for it;
  - provider files: code that calls the client library directly (the wrapper), in the repository or in a shared
    library whose source is given with --library-source (then the wrapper's work is counted with that library);
  - consumer sites: code lines that call the wrapper (its service-named types, the methods that hold the client
    calls, or identifiers that name the service);
  - configuration entries (key names only, never values) and external config files named after the service;
  - hosts from facts.json whose role is the service.
Hours per AWS target option = fixed + provider files + consumer sites + config entries, manual-equivalent, then the
AI factor (code or redesign) as for all other coding work. Writes <out>/aws-native.json, aws-native.md and aws-native.html.
Read-only: nothing under --root or --library-source is changed.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import mask  # noqa: E402
from _mdhtml import write_pair  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOGUE = next((p for p in (os.path.join(HERE, "aws_native.json"), os.path.join(HERE, "data", "aws_native.json")) if os.path.exists(p)),
                 os.path.join(HERE, "aws_native.json"))
CODE_EXT = (".cs", ".vb")
CONFIG_EXT = (".config",)
SKIP_DIRS = {"bin", "obj", ".vs", ".git", "node_modules", "testresults", "graphify-out", "web references", "service references", "connected services"}
SKIP_NAMES = {"reference.cs", "reference.vb", "packages.config"}
GENERATED = (".designer.cs", ".designer.vb", ".g.cs", ".g.i.cs", ".assemblyinfo.cs")
BINDING = re.compile(r"assemblyIdentity|bindingRedirect|dependentAssembly|codeBase|<package\s|PackageReference|<Reference\s|HintPath", re.I)
DEFAULT_FACTORS = {"code": [0.3, 0.5], "redesign": [0.7, 1.0]}
# method names too generic to count as calls into a mail / transfer wrapper
GENERIC = {"get", "set", "add", "put", "send", "run", "execute", "process", "main", "init", "load", "save", "dispose", "tostring", "equals",
           "page_load", "application_start", "write", "read", "log", "error", "info", "debug", "handle", "create", "update", "delete",
           "getinstance", "instance", "writexml", "readxml", "getschema", "serialize", "deserialize", "validate", "configure", "build"}

_TOK = re.compile(r'@"(?:[^"]|"")*"|\$?"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)\'|(?P<c>//[^\n]*|/\*.*?\*/)', re.S)
_TYPE = re.compile(r"\b(?:class|interface|enum|struct)\s+([A-Za-z_]\w*)")
_METHOD = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:(?:public|private|protected|internal|static|async|override|virtual|sealed|partial|extern|new|unsafe)\s+)+"
                     r"[\w<>\[\],.?\s]+?\s+([A-Za-z_]\w*)\s*(?:<[^>()]*>)?\s*\(")
_CFG_NAME = re.compile(r'\b(?:key|name)\s*=\s*"([^"]+)"', re.I)
_CFG_TAG = re.compile(r"<\s*([A-Za-z_][\w.:-]*)")
_CFG_VAL = re.compile(r'\b(?:value|connectionString|host|server|address|url|uri|configSource)\s*=\s*"([^"]*)"', re.I)


def read(path):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            with open(path, encoding=enc) as fh:
                return fh.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    return ""


def views(text):
    """(comments blanked, comments and strings blanked); line numbers kept."""
    blank = lambda s: re.sub(r"[^\n]", " ", s)
    no_comments = _TOK.sub(lambda m: blank(m.group(0)) if m.group("c") else m.group(0), text)
    no_strings = _TOK.sub(lambda m: blank(m.group(0)) if m.group("c") else (m.group(0)[0] + blank(m.group(0)[1:-1]) + m.group(0)[-1]
                                                                            if len(m.group(0)) > 1 else m.group(0)), text)
    return no_comments.splitlines(), no_strings.splitlines()


def nuget_folder(path):
    try:
        return any(n.lower().endswith(".nupkg") for _, _, fs in os.walk(path) for n in fs)
    except OSError:
        return False


def walk(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIRS and not x.startswith(".")
                   and not (x.lower() == "packages" and nuget_folder(os.path.join(d, x)))]
        for fn in files:
            yield os.path.join(d, fn)


def rel(path, root):
    return os.path.relpath(path, root).replace("\\", "/")


def packages_in(root):
    """{id: [files]} from packages.config, PackageReference and binary References."""
    out = {}
    for f in walk(root):
        low = f.lower()
        if low.endswith("packages.config") or low.endswith((".csproj", ".vbproj")):
            t = read(f)
            for m in re.finditer(r'<package\s+id="([^"]+)"|<PackageReference\s+Include="([^"]+)"|<Reference\s+Include="([^",]+)', t):
                pid = next(g for g in m.groups() if g)
                out.setdefault(pid, set()).add(rel(f, root))
    return {k: sorted(v) for k, v in out.items()}


class Source:
    """One scanned tree (the repository or a shared library's source)."""

    def __init__(self, root, name):
        self.root, self.name = root, name
        self.code, self.config = {}, {}
        for f in walk(root):
            low = os.path.basename(f).lower()
            if low in SKIP_NAMES or low.endswith(GENERATED) or os.path.getsize(f) > 2_000_000:
                continue
            if low.endswith(CODE_EXT):
                raw = read(f)
                self.code[rel(f, root)] = views(raw)
            elif low.endswith(CONFIG_EXT) or (low.startswith("appsettings") and low.endswith(".json")):
                self.config[rel(f, root)] = read(f).splitlines()


def kw_rx(keyword):
    return re.compile(r"\b\w*(?:" + keyword + r")\w*\b", re.I)


def providers(src, det):
    """Files that call the client library directly: {file: {lines, loc, legacy, types, methods}}."""
    client = re.compile(det["client"])
    in_str = re.compile(det["client_in_strings"]) if det.get("client_in_strings") else None
    legacy = re.compile(det["legacy"]) if det.get("legacy") else None
    kw = re.compile(det["keyword"], re.I)
    out = {}
    for f, (nc, ns) in src.code.items():
        hits = [i for i, line in enumerate(ns) if client.search(line)] + ([i for i, line in enumerate(nc) if in_str.search(line)] if in_str else [])
        if not [i for i in hits if not ns[i].lstrip().startswith(("using ", "Imports "))]:
            continue  # only imports the client namespace (for a result type): a caller, not the wrapper
        hits = sorted(set(hits))
        types = _TYPE.findall("\n".join(ns))
        methods = set()
        for i in hits:
            for j in range(i, max(-1, i - 400), -1):
                m = _METHOD.match(ns[j])
                if m:
                    # only when the hit is inside that method's body: a hit after the method has closed (a nested class with
                    # the client's attributes, a field) does not make the method above it a wrapper
                    if j == i or sum(ns[k].count("{") - ns[k].count("}") for k in range(j, i)) > 0:
                        methods.add(m.group(1))
                    break
        service_named = bool(kw.search(os.path.basename(f)))
        out[f] = {"lines": [i + 1 for i in hits][:50], "client_lines": len(hits), "loc": sum(1 for x in ns if x.strip()),
                  "legacy": bool(legacy and any(legacy.search(x) for x in ns)),
                  "types": types if service_named else [t for t in types if kw.search(t)],
                  "methods": sorted(m for m in methods if m.lower() not in GENERIC and len(m) > 4) if not service_named else []}
    return out


def service_types(src, det):
    """Types declared anywhere in a library whose name names the service (AerospikeResult, MemCacheManager...)."""
    kw = re.compile(det["keyword"], re.I)
    return {t for f, (nc, ns) in src.code.items() for t in _TYPE.findall("\n".join(ns)) if kw.search(t)}


def consumers(src, det, provider_files, types, methods):
    """Code lines outside the wrapper that use it: [(file, line, text)]."""
    kw = kw_rx(det["keyword"])
    trx = re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, types))) + r")\b") if types else None
    mrx = re.compile(r"(?<![\w.]\s)\b(?:" + "|".join(sorted(map(re.escape, methods))) + r")\s*\(") if methods else None
    sites = []
    for f, (nc, ns) in src.code.items():
        if f in provider_files:
            continue
        for i, line in enumerate(ns):
            s = line.strip()
            if not s or s.startswith(("using ", "Imports ", "namespace ", "#")):
                continue
            if _METHOD.match(line) and mrx and mrx.search(line) and not re.search(r"=|return|await", line.split("(")[0]):
                continue  # a declaration, not a call
            if (trx and trx.search(line)) or (mrx and mrx.search(line)) or kw.search(line):
                sites.append((f, i + 1, nc[i].strip()[:160]))
    return sites


def config_entries(src, det):
    """[(file, line, entry name)]: configuration lines for the service; values are never kept."""
    krx, vrx = re.compile(det["config_keys"]), (re.compile(det["config_values"]) if det.get("config_values") else None)
    kw = re.compile(det["keyword"], re.I)
    out = []
    for f, lines in src.config.items():
        named_file = bool(kw.search(os.path.basename(f)))
        for i, line in enumerate(lines):
            s = line.strip()
            if not s or s.startswith("<!--") or BINDING.search(s) or s.startswith("</"):
                continue
            names = " ".join(_CFG_NAME.findall(s) + _CFG_TAG.findall(s) + re.findall(r"\s([A-Za-z_][\w.:-]*)\s*=", _CFG_VAL.sub("", s)))
            vals = " ".join(_CFG_VAL.findall(s))
            hit = krx.search(names) or (vrx and vrx.search(vals)) or (named_file and "=" in s and s.startswith("<") and not s.startswith("<?"))
            if hit:
                name = (_CFG_NAME.findall(s) or _CFG_TAG.findall(s) or ["?"])[0]
                out.append((f, i + 1, name))
    return out


def n_settings(cfg):
    """Distinct settings to re-point: the same key repeated in Web.config and its transforms (Debug, Release, ...) or
    in several attributes of one element counts once per file family; unnamed lines count one each."""
    fam = lambda f: re.sub(r"\.(debug|release|staging|prod\w*|qa|uat|dev\w*|test)(?=\.config$)", "", f.replace("\\", "/").lower())  # noqa: E731
    named = {(os.path.dirname(fam(f)), n) for f, _, n in cfg if n != "?"}
    return len(named) + sum(1 for _, _, n in cfg if n == "?")


def hours(target, n_prov, legacy, n_cons, n_cfg, with_fixed, consumer_fixed):
    pp = target.get("legacy_per_provider_file", target["per_provider_file"]) if legacy else target["per_provider_file"]
    fx = target["fixed"] if with_fixed else (consumer_fixed if (n_cons or n_cfg) else [0, 0])
    return [round(fx[i] + n_prov * pp[i] + n_cons * target["per_consumer_site"][i] + n_cfg * target["per_config_key"][i], 1) for i in (0, 1)]


def assisted(manual, target, factors):
    f = factors[target.get("factor", "code")]
    return [round(manual[i] * f[i], 1) for i in (0, 1)]


def scan(root, library_sources=(), facts=None, choices=None, factors=None, catalogue=None):
    cat = catalogue or json.load(open(CATALOGUE, encoding="utf-8"))
    choices, factors = choices or {}, factors or DEFAULT_FACTORS
    repo = Source(root, os.path.basename(os.path.normpath(root)))
    libs = [Source(p, os.path.basename(os.path.normpath(p))) for p in library_sources if os.path.isdir(p)]
    pkgs = packages_in(root)
    roles = {}
    for n in (facts or {}).get("network", []):
        roles.setdefault((n.get("role") or "").lower(), []).append(f"{n['host']}:{n.get('port') or ''}".rstrip(":"))
    cfix = cat.get("consumer_repo_fixed", [1, 2])
    out = []
    for svc in cat["services"]:
        det = svc["detect"]
        prx = re.compile(det["packages"], re.I)
        found_pkgs = sorted(p for p in pkgs if prx.match(p))
        prov = providers(repo, det)
        lib_prov = {l.name: providers(l, det) for l in libs}
        types = {t for p in prov.values() for t in p["types"]}
        methods = {m for p in prov.values() for m in p["methods"]}
        lib_types = {l.name: (service_types(l, det) | {t for p in lib_prov[l.name].values() for t in p["types"]}) for l in libs}
        sites = consumers(repo, det, set(prov), types | set().union(*lib_types.values()) if libs else types, methods)
        cfg = config_entries(repo, det)
        label_kw = re.compile(det["keyword"], re.I)
        hosts = sorted({h for r, hs in roles.items() if label_kw.search(r) or svc["label"].lower().split()[0] in r for h in hs})
        if not (found_pkgs or prov or sites or cfg):
            continue
        def calls_into(lib):
            ts = lib_types[lib.name]
            rx = re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, ts))) + r")\b") if ts else None
            return bool(rx and any(rx.search(t) for _, _, t in sites))
        # a library's wrapper counts when this repository calls into it, or (no wrapper here) only configures it
        used_libs = [l for l in libs if lib_prov[l.name] and (calls_into(l) or (not prov and cfg))]
        legacy = any(p["legacy"] for p in prov.values())
        if prov:
            where = "in this repository"
        elif used_libs:
            where = "in " + ", ".join(l.name for l in used_libs) + " (shared library)"
        elif sites:
            where = "call sites name the service; no client code here (a binary library or a configured appender)"
        else:
            where = "packages / configuration only, no code uses it"
        options = []
        chosen = choices.get(svc["id"]) or svc["targets"][0]["id"]
        for t in svc["targets"]:
            man = hours(t, len(prov), legacy, len(sites), n_settings(cfg), bool(prov), cfix)
            lib_work = []
            for l in used_libs:
                lp = lib_prov[l.name]
                lm = hours(t, len(lp), any(p["legacy"] for p in lp.values()), 0, 0, True, cfix)
                lib_work.append({"library": l.name, "provider_files": len(lp), "provider_loc": sum(p["loc"] for p in lp.values()),
                                 "manual_hours": lm, "hours": assisted(lm, t, factors)})
            options.append({"id": t["id"], "aws": t["aws"], "change": t["change"], "work": t["work"], "factor": t.get("factor", "code"),
                            "manual_hours": man, "hours": assisted(man, t, factors), "library_work": lib_work, "chosen": t["id"] == chosen})
        out.append({
            "id": svc["id"], "label": svc["label"], "kind": svc["kind"], "client_code": where,
            "packages": found_pkgs, "hosts": hosts,
            "provider_files": [{"file": f, "loc": p["loc"], "client_lines": p["client_lines"], "first_lines": p["lines"][:8], "legacy_api": p["legacy"]}
                               for f, p in sorted(prov.items())],
            "library_provider_files": {l.name: [{"file": f, "loc": p["loc"], "client_lines": p["client_lines"], "legacy_api": p["legacy"]}
                                                for f, p in sorted(lib_prov[l.name].items())] for l in used_libs},
            "wrapper_types": sorted(types | (set().union(*(lib_types[l.name] for l in used_libs)) if used_libs else set())),
            "wrapper_methods": sorted(methods),
            "consumer_sites": len(sites), "consumer_files": len({s[0] for s in sites}),
            "consumer_examples": [{"file": f, "line": n, "text": mask(t)} for f, n, t in sites[:12]],
            "config_entries": n_settings(cfg), "config_lines": len(cfg), "config_names": sorted({n for _, _, n in cfg}),
            "config_files": sorted({f for f, _, _ in cfg}),
            "legacy_api": legacy, "options": options, "chosen": chosen, "supersedes_optional": svc.get("supersedes_optional", [])})
    return {"root": root, "libraries": [l.name for l in libs], "factors": factors, "services": out,
            "total_hours": [round(sum(o["hours"][i] for s in out for o in s["options"] if o["chosen"]), 1) for i in (0, 1)],
            "total_manual_hours": [round(sum(o["manual_hours"][i] for s in out for o in s["options"] if o["chosen"]), 1) for i in (0, 1)],
            "library_hours": [round(sum(w["hours"][i] for s in out for o in s["options"] if o["chosen"] for w in o["library_work"]), 1) for i in (0, 1)]}


def optional_rows(res):
    """One row per service in the shape of modernization-assessment's optional modernizations (estimate_effort.py, report 7.3).
    manual_hours + factor let the caller apply its own AI factors; supersedes names the generic optional items this replaces."""
    rows = []
    for s in res["services"]:
        o = next(x for x in s["options"] if x["chosen"])
        files = [{"file": p["file"], "line": (p["first_lines"] or [1])[0]} for p in s["provider_files"]] or \
                [{"file": c["file"], "line": c["line"]} for c in s["consumer_examples"]]
        rows.append({"id": "AWS-" + s["id"].upper(), "title": f"{s['label']} ({o['change']})", "aws": o["aws"],
                     "why": f"{o['work']} Wrapper: {s['client_code']}.", "count": max(len(s["provider_files"]) + s["consumer_files"], 1),
                     "files": files[:5], "manual_hours": o["manual_hours"], "factor": o["factor"], "supersedes": s.get("supersedes_optional", []),
                     "evidence": {"packages": s["packages"], "wrapper_files": len(s["provider_files"]), "call_sites": s["consumer_sites"],
                                  "config_entries": s["config_entries"]},
                     "alternatives": [{"id": x["id"], "aws": x["aws"], "change": x["change"], "manual_hours": x["manual_hours"]} for x in s["options"] if not x["chosen"]]})
    return rows


def render(res, name):
    L = [f"# Server-hosted services to AWS managed services: {name}", "",
         "Code-side work only. Creating the AWS resources, networking, DNS, verified mail domains and data migration are DevOps work and are not included. "
         f"Hours: manual-equivalent, then the AI factor (code {res['factors']['code'][0]}-{res['factors']['code'][1]}, redesign "
         f"{res['factors']['redesign'][0]}-{res['factors']['redesign'][1]}).", "",
         f"**This repository: {res['total_hours'][0]:g}-{res['total_hours'][1]:g} h** with the chosen options "
         f"(manual-equivalent {res['total_manual_hours'][0]:g}-{res['total_manual_hours'][1]:g} h)."]
    if any(o["library_work"] for s in res["services"] for o in s["options"] if o["chosen"]):
        L.append(f"Wrappers in shared libraries: {res['library_hours'][0]:g}-{res['library_hours'][1]:g} h, counted once with the library, not in the figure above.")
    L += ["", "| Service | Client code lives | Evidence | Chosen AWS target | Change | Hours (this repo) | Library wrapper hours |", "|---|---|---|---|---|---|---|"]
    for s in res["services"]:
        o = next(x for x in s["options"] if x["chosen"])
        ev = []
        if s["packages"]:
            ev.append(f"{len(s['packages'])} package(s)")
        if s["provider_files"]:
            ev.append(f"{len(s['provider_files'])} wrapper file(s)")
        if s["consumer_sites"]:
            ev.append(f"{s['consumer_sites']} call sites in {s['consumer_files']} files")
        if s["config_entries"]:
            ev.append(f"{s['config_entries']} config entries")
        if s["hosts"]:
            ev.append("hosts " + ", ".join(s["hosts"]))
        lw = "; ".join(f"{w['library']}: {w['provider_files']} files, {w['hours'][0]:g}-{w['hours'][1]:g} h" for w in o["library_work"]) or "-"
        L.append(f"| {s['label']} | {s['client_code']} | {'; '.join(ev)} | {o['aws']} | {o['change']} | {o['hours'][0]:g}-{o['hours'][1]:g} | {lw} |")
    for s in res["services"]:
        L += ["", f"## {s['label']}", ""]
        if s["packages"]:
            L.append("- Packages: " + ", ".join(s["packages"]))
        if s["provider_files"]:
            L.append("- Wrapper files here: " + ", ".join(f"`{p['file']}` ({p['client_lines']} client lines{', legacy API' if p['legacy_api'] else ''})" for p in s["provider_files"]))
        for lib, fs in s["library_provider_files"].items():
            L.append(f"- Wrapper files in {lib}: {len(fs)} ({sum(p['loc'] for p in fs):,} lines): " + ", ".join(f"`{p['file']}`" for p in fs[:8]) + (" ..." if len(fs) > 8 else ""))
        if s["wrapper_types"] or s["wrapper_methods"]:
            L.append("- Wrapper entry points: " + ", ".join(s["wrapper_types"][:15] + [m + "()" for m in s["wrapper_methods"][:10]]))
        if s["consumer_examples"]:
            L.append(f"- Call sites: {s['consumer_sites']} in {s['consumer_files']} files, e.g. " + "; ".join(f"`{c['file']}:{c['line']}`" for c in s["consumer_examples"][:6]))
        if s["config_entries"]:
            L.append(f"- Configuration: {s['config_entries']} entries in " + ", ".join(f"`{f}`" for f in s["config_files"]) + " (names: " + ", ".join(s["config_names"][:12]) + ")")
        L += ["", "| Option | AWS target | Change | What changes in the code | Hours here | Library wrapper |", "|---|---|---|---|---|---|"]
        for o in s["options"]:
            lw = "; ".join(f"{w['library']} {w['hours'][0]:g}-{w['hours'][1]:g} h" for w in o["library_work"]) or "-"
            L.append(f"| {'**' + o['id'] + '** (chosen)' if o['chosen'] else o['id']} | {o['aws']} | {o['change']} | {o['work']} | {o['hours'][0]:g}-{o['hours'][1]:g} | {lw} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--library-source", nargs="*", default=[])
    ap.add_argument("--facts")
    ap.add_argument("--choices", default="{}")
    ap.add_argument("--factors")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name")
    a = ap.parse_args()
    facts = json.load(open(a.facts, encoding="utf-8")) if a.facts else None
    res = scan(a.root, a.library_source, facts, json.loads(a.choices), json.loads(a.factors) if a.factors else None)
    os.makedirs(a.out, exist_ok=True)
    json.dump(res, open(os.path.join(a.out, "aws-native.json"), "w", encoding="utf-8"), indent=1)
    name = a.name or os.path.basename(os.path.normpath(a.root))
    write_pair(os.path.join(a.out, "aws-native.md"), render(res, name))
    for s in res["services"]:
        o = next(x for x in s["options"] if x["chosen"])
        print(f"{s['id']:22} {s['client_code'][:40]:40} sites {s['consumer_sites']:4} cfg {s['config_entries']:3} -> {o['id']:22} {o['hours']}")
    print("total", res["total_hours"], "library", res["library_hours"])


if __name__ == "__main__":
    main()
