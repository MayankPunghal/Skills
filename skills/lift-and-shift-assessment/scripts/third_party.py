"""Third-party packages, integrations and server-to-server connections, per solution.

    python <skill>/scripts/third_party.py

Reads assessment/solutions/index.json, the scan results and the NuGet licence data (online lookups happen in scan_repo.py; offline runs
use the vendor list only), and writes assessment/solutions/third_party.json:
  licensed        packages or assemblies that need a commercial licence key or a vendor account (data/commercial_packages.json,
                  plus licence texts that say commercial or proprietary)
  integrations    third-party services the code calls: SDK packages (data/service_sdks.json), vendor-named environment variables or
                  settings, and external hosts called from server-side code (JavaScript and view files are the browser's calls, not the server's)
  server_to_server  internal addresses and host names each solution connects to, with what runs there
An item needs a re-key (new key or credential on AWS) when there is evidence of a key: a key-named variable, a licence key or an account.
Items without key evidence only need outbound access from the AWS instance and add no hours.
"""
import os
import re

from _common import OUT, data, load_config, load_state, mark_step, read_json, utf8_stdout, write_json
from solutions import keys

CODE_EXT = (".cs", ".vb", ".config", ".asax", ".ashx", ".svc")
KEYISH = re.compile(r"(?i)(KEY|SECRET|TOKEN|PASSWORD|PWD|LICEN[SC]E|CREDENTIAL)")
COMMERCIAL_TEXT = re.compile(r"(?i)commercial licen|proprietary licen|paid licen|requires a licen|licen[sc]e key required|per[- ]developer")  # a link to a vendor EULA page is not enough
STOP = {"KEY", "PRIMARY", "SECONDARY", "SECRET", "ENDPOINT", "REGION", "TEST", "PUBLIC", "PRIVATE", "API", "PASSWORD", "USER", "ID", "TOKEN"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def pretty(key):
    return " ".join(w.capitalize() if len(w) > 3 else w.upper() if w in ("ms", "aws") else w.capitalize() for w in key.split("_"))


def licence_text(pk):
    n = pk.get("nuget") or {}
    parts = [n.get("licence") or "", str(n.get("licence_info") or "")]
    for m in n.get("versions_meta") or []:
        if m.get("v") in (pk.get("versions") or []):
            parts.append(m.get("lic_label") or "")
    return " ".join(parts)


def var_groups(names, cfgv):
    """Environment variable names -> {vendor key: [names]}; the shared application prefix is dropped."""
    names = [n for n in names if "_" in n]
    if not names:
        return {}
    first = {}
    for n in names:
        first[n.split("_")[0]] = first.get(n.split("_")[0], 0) + 1
    top, hits = max(first.items(), key=lambda x: x[1])
    prefix = top if hits >= max(3, 0.6 * len(names)) else ""
    skip = set(cfgv["skip"])
    out = {}
    for n in names:
        toks = n.split("_")[1:] if prefix and n.startswith(prefix + "_") else n.split("_")
        if not toks or toks[0].upper() in skip:
            continue
        end = 1
        if toks[0].upper() in cfgv["two_word"]:  # AZURE_PHOTO_DNA_PRIMARY_KEY -> AZURE_PHOTO_DNA
            while end < len(toks) and toks[end].upper() not in STOP:
                end += 1
            end = max(end, min(2, len(toks)))
        out.setdefault("_".join(toks[:end]).upper(), []).append(n)
    return out


def main():
    utf8_stdout()
    root, cfg = load_config()
    os.chdir(root)
    st = load_state(root)
    idx = read_json(os.path.join(OUT, "solutions", "index.json"))
    if not idx:
        raise SystemExit("run solutions.py first")
    comp_data = data("commercial_packages.json")
    comps = [(re.compile("(?i)^(?:" + c["match"] + ")$"), c) for c in comp_data["components"]]
    sdks = [(re.compile("(?i)^(?:" + s["match"] + ")$"), s) for s in data("service_sdks.json")["sdks"]]
    ignore = re.compile("(?i)" + comp_data["ignore_hosts"])
    company = [d.lower() for d in cfg.get("company_domains") or []]
    scans = {r: read_json(os.path.join(OUT, "scan", r + ".json"), {}) for r in {s["repo"] for s in idx["solutions"]}}
    invs = {r: read_json(os.path.join(OUT, "inventory", r + ".json"), {}) for r in scans}
    infra = {r: read_json(os.path.join(OUT, "infra", r + ".json"), {}) for r in scans}
    result = []
    for s in idx["solutions"]:
        repo = s["repo"]
        names = set()
        for p in s["projects"]:
            names |= keys(p)
        refs = {}  # package id or assembly name -> info
        for pr in invs[repo].get("projects", []):
            if pr["path"] in {p["path"] for p in s["projects"]}:
                for r in pr.get("references") or []:
                    refs.setdefault(r, {"id": r, "versions": [], "nuget": None})
        for pk in scans[repo].get("packages") or []:
            if {x.lower() for x in pk.get("projects") or []} & names:
                refs[pk["id"]] = pk
        licensed, integ = [], {}
        for pid, pk in sorted(refs.items()):
            hit = next((c for rx, c in comps if rx.match(pid)), None)
            text = licence_text(pk) if pk.get("nuget") else ""
            if hit or COMMERCIAL_TEXT.search(text):
                licensed.append({"package": pid, "versions": pk.get("versions") or [], "vendor": hit["vendor"] if hit else "see licence text",
                                 "kind": hit["kind"] if hit else "licensed", "note": hit["note"] if hit else text.strip()[:120],
                                 "source": "vendor list" if hit else "NuGet licence text"})
            sd = next((x for rx, x in sdks if rx.match(pid)), None)
            if sd:
                svc = re.sub(r"\{(\d)\}", lambda m: (re.match(sd["match"], pid, re.I).group(int(m.group(1))) or ""), sd["service"])
                integ.setdefault(norm(svc), {"name": svc, "via": [], "key_vars": [], "hosts": [], "package": pid, "aws": sd.get("aws", "")})["via"].append("package " + pid)
        for key, vs in var_groups(s["env_vars"], comp_data["integration_key_groups"]).items():
            m = next((v for k, v in integ.items() if norm(key) in k or k in norm(key)), None)
            if m is None:
                m = integ.setdefault(norm(key), {"name": pretty(key), "via": [], "key_vars": [], "hosts": [], "package": "", "aws": ""})
            m["via"].append("variables " + ", ".join(vs))
            m["key_vars"] += [v for v in vs if KEYISH.search(v)]
        for o in (scans[repo].get("network") or {}).get("outbound", []):
            if o.get("kind") != "external" or ignore.search(o["host"]) or any(o["host"].lower().endswith(d) for d in company):
                continue
            if not ({x.lower() for x in o.get("projects") or []} & names):
                continue
            if not any(f.lower().endswith(CODE_EXT) for f in o.get("files", [])):
                continue
            m = next((v for k, v in integ.items() if k and k in norm(o["host"])), None)
            if m is None:
                m = integ.setdefault(norm(o["host"]), {"name": o["host"], "via": [], "key_vars": [], "hosts": [], "package": "", "aws": ""})
            m["hosts"].append(o["host"])
            m["via"].append("call to " + o["host"] + " in " + o["files"][0])
        for l in licensed:  # a licence key variable ties a licensed component to its key (SELECTPDF_KEY -> SelectPdf)
            for k, v in list(integ.items()):
                if k and (k in norm(l["package"]) or k in norm(l["vendor"])):
                    l["key_vars"] = v["key_vars"]
                    l["has_key"] = bool(v["key_vars"])
                    integ.pop(k)
            l.setdefault("has_key", l["kind"] == "saas")
        merged = {}
        for l in licensed:
            m = merged.setdefault(l["vendor"], dict(l, package=[]))
            m["package"].append(l["package"])
            m["has_key"] = m.get("has_key") or l.get("has_key")
            m["key_vars"] = m.get("key_vars") or l.get("key_vars") or []
        licensed = [dict(m, package=", ".join(m["package"])) for m in merged.values()]
        items = []
        for l in licensed:
            items.append({"name": l["package"], "kind": "licensed component" if l["kind"] == "licensed" else "service account", "vendor": l["vendor"],
                          "evidence": l["source"] + (("; " + ", ".join(l["key_vars"])) if l.get("key_vars") else ""), "rekey": bool(l["has_key"]),
                          "note": l["note"]})
        for v in integ.values():
            items.append({"name": v["name"], "kind": "integration", "vendor": "", "evidence": "; ".join(v["via"])[:200],
                          "rekey": bool(v["key_vars"]), "note": ("Key in " + ", ".join(sorted(set(v["key_vars"])))) if v["key_vars"] else "No key found: outbound access only"})
        host_type = {}
        for d in infra[repo].get("dependencies", []):
            for h in d.get("hosts", []):
                host_type[str(h.get("host", "")).lower()] = d["label"]
        s2s = [{"to": e["destination"], "kind": host_type.get(e["destination"].lower(), e["class"]), "projects": e["projects"]} for e in s["endpoints"]]
        result.append({"id": s["id"], "licensed_and_integrations": items, "server_to_server": s2s,
                       "rekey_count": sum(1 for i in items if i["rekey"])})
    write_json(os.path.join(OUT, "solutions", "third_party.json"), {"solutions": result, "online_licence_data": bool(cfg.get("online_package_lookup"))})
    mark_step(root, "third_party")
    for r in result:
        print(f"{r['id']}: {len(r['licensed_and_integrations'])} licensed components / integrations ({r['rekey_count']} need a re-key), {len(r['server_to_server'])} internal connections")
        for i in r["licensed_and_integrations"]:
            print(f"    {i['kind']:<19} {i['name']:<40} {'RE-KEY' if i['rekey'] else 'access only'}")


if __name__ == "__main__":
    main()
