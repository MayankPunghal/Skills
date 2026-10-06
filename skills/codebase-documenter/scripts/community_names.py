"""Community naming for the code graph: unique, meaningful names (and one-line summaries) for graphify's communities.

    python <skill>/scripts/community_names.py                  # heuristic names (no LLM, no cost), always unique
    python <skill>/scripts/community_names.py --llm [--model M] [--batch 25] [--only-missing]
    python <skill>/scripts/community_names.py --show           # print id, size, name, summary

Writes graphify-out/.graphify_labels.json ({id: name}: what graphify's exports and the reference pages read) and
graphify-out/community-summaries.json ({id: {name, summary, source, size, folders, namespaces, hubs, terms}}), which the
graph summary, the RAG cards and agents use.

Heuristic (the default, and the fallback when an LLM call fails): every community gets a profile -- hub members (most
connected), class / method / file names, namespaces and folders -- split into words. Words are ranked by TF-IDF (weighted
by where they come from: class and namespace words count more than method words), so a word every community shares
(the product name, "Async", "Get") sinks and the words that set this community apart rise. The name is the top two
distinguishing words plus the community's role, read from its class-name suffixes (Controllers, Repositories, Tests …):
"Coupon Pricing Repositories". Clashes get the next distinguishing word, then the hub class; a one-member community is
named after its member. The summary lists size, role, hubs and main folder.

LLM (optional, cheap: one short independent request per batch, no conversation history): the same profile is sent -- hub
members with their kind, namespaces, folders, role and the heuristic name as a hint -- with every other community in the
batch alongside, and the model returns a 2-5 word name and a one-sentence summary per community. A final pass re-asks only
for names that still clash, showing the clashing communities side by side. Keys and models: see code_graph.py check.
"""
import argparse
import json
import math
import os
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict

from _common import load_config, utf8_stdout, write

STOP = set("""a an and are as at be by for from get gets set sets has have in into is it of on or the to with without via async
task void bool int string var new old base impl default internal public private protected static class interface record struct
enum value values item items data info object objects helper helpers util utils utility utilities common core shared misc
general manager managers handler handlers service services model models dto dtos entity entities view views page pages
controller controllers repository repositories test tests spec specs fixture fixtures extension extensions program startup
main index src lib app application module modules cs js ts py sql json xml config configuration options option file files
api web mvc http https id ids list lists result results request response context create read update delete remove add
find load save run execute handle process build make init dispose to string equals hash code tostring gethashcode i t
async await cancellation token method methods function functions type types""".split())
ROLE = [("Controller", "Controllers"), ("ApiController", "API"), ("Repository", "Repositories"), ("Queries", "Queries"),
        ("Query", "Queries"), ("Service", "Services"), ("Handler", "Handlers"), ("Consumer", "Consumers"), ("Job", "Jobs"),
        ("Worker", "Workers"), ("Processor", "Processors"), ("Middleware", "Middleware"), ("Filter", "Filters"),
        ("Validator", "Validation"), ("Tests", "Tests"), ("Test", "Tests"), ("Scenarios", "Scenarios"), ("Migration", "Migrations"),
        ("Context", "Data Context"), ("Map", "Mappings"), ("Mapping", "Mappings"), ("Profile", "Mappings"), ("Page", "Pages"),
        ("ViewComponent", "View Components"), ("Hub", "Hubs"), ("Client", "Clients"), ("Options", "Settings"),
        ("Settings", "Settings"), ("Exception", "Errors"), ("Dto", "DTOs"), ("Model", "Models"), ("Entity", "Entities"),
        ("Factory", "Factories"), ("Builder", "Builders"), ("Engine", "Engine"), ("Workflow", "Workflow")]
WEIGHT = {"hub": 4.0, "class": 3.0, "namespace": 2.5, "file": 2.0, "folder": 1.5, "method": 1.0}
ACRONYMS = {"ef", "ef6", "db", "sql", "api", "ui", "nh", "clr", "dal", "dto", "mvc", "bo", "csv", "xml", "json", "http", "url", "aspx",
            "tvf", "ado", "crud", "etl", "ssis", "ssrs", "wcf", "jwt", "otp", "pdf", "vm", "id", "io", "ftp", "smtp", "sms", "erp", "crm",
            "sso", "ldap", "oauth", "rpc", "grpc", "tcp", "dns", "gst", "vat", "kpi", "sla", "faq", "iis", "sp", "udf", "cte", "orm",
            "html", "css", "js", "ts", "vb", "net", "aws", "gcp", "s3", "nhib", "ps1"}
BCL = {"Task", "ValueTask", "List", "IList", "IEnumerable", "IReadOnlyList", "IReadOnlyCollection", "ICollection", "Dictionary",
       "IDictionary", "HashSet", "DateTime", "DateTimeOffset", "DateOnly", "TimeSpan", "Guid", "Func", "Action", "Exception",
       "IActionResult", "ActionResult", "IQueryable", "DbSet", "DbContext", "Controller", "ControllerBase", "SqlConnection",
       "SqlCommand", "SqlParameter", "SqlTransaction", "DataTable", "DataSet", "DataRow", "StringBuilder", "EventArgs", "Page",
       "Button", "Object", "String", "Decimal", "CancellationToken", "ILogger", "IConfiguration", "IServiceProvider", "Fact",
       "Theory", "HttpContext", "ModelBuilder", "DbModelBuilder", "DbContextOptions", "Stream", "Type", "Attribute"}
EXT_ROLE = {".ps1": "Scripts", ".psm1": "Scripts", ".sh": "Scripts", ".bat": "Scripts", ".json": "Settings", ".yml": "Pipeline",
            ".yaml": "Pipeline", ".sql": "Database", ".cshtml": "Views", ".razor": "Components", ".aspx": "Web Forms",
            ".ascx": "Web Forms", ".config": "Settings", ".xml": "Settings", ".csproj": "Projects", ".sln": "Solution"}


def words(ident):
    """'OrderWorkflowAsync' -> ['order', 'workflow', 'async']; 'fn_EmployeeTenure' -> ['fn', 'employee', 'tenure']."""
    ident = re.sub(r"\(.*$", "", str(ident or "")).lstrip(".")
    parts = re.split(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", ident)
    return [p.lower() for p in parts if p and not p.isdigit() and len(p) > 1]


def singular(w):
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def profiles(g, labels_old=None):
    nodes = {n["id"]: n for n in g["nodes"]}
    deg = Counter()
    for e in g["links"]:
        deg[e["source"]] += 1
        deg[e["target"]] += 1
    owner = {e["target"]: e["source"] for e in g["links"] if e.get("relation") == "method"}
    comm = defaultdict(list)
    for n in g["nodes"]:
        if n.get("community") is not None:
            comm[n["community"]].append(n["id"])
    out = {}
    for cid, ids in comm.items():
        ids.sort(key=lambda i: -deg[i])

        def plain(i):
            return re.sub(r"\(\)$", "", nodes[i].get("label") or "").lstrip(".")
        classes = [i for i in ids if nodes[i].get("_callable_class") and plain(i) not in BCL]
        others = [i for i in ids if i not in owner and not nodes[i].get("_callable_class") and plain(i) not in BCL
                  and (nodes[i].get("_callable") or re.search(r"\.\w+$", plain(i)) or nodes[i].get("type") == "namespace")]
        hubs = (classes[:5] + others)[:5] or [i for i in ids if plain(i) not in BCL][:5] or ids[:5]
        exts = Counter(os.path.splitext(nodes[i].get("source_file") or "")[1].lower() for i in ids if nodes[i].get("source_file"))
        files = Counter(os.path.splitext(os.path.basename(nodes[i].get("source_file") or ""))[0] for i in ids if nodes[i].get("source_file"))
        folders = Counter(os.path.dirname((nodes[i].get("source_file") or "").replace("\\", "/")) for i in ids if nodes[i].get("source_file"))
        spaces = Counter((nodes[i].get("metadata") or {}).get("namespace") for i in ids if (nodes[i].get("metadata") or {}).get("namespace"))
        bag = Counter()

        def feed(text, kind, n=1):
            for w in words(text):
                w = singular(w)
                if w not in STOP:
                    bag[w] += WEIGHT[kind] * n

        for i in hubs:
            feed(nodes[i].get("label"), "hub")
        for i in classes:
            feed(nodes[i].get("label"), "class")
        for i in ids:
            if i in owner:
                feed(nodes[i].get("label"), "method")
        for f, c in files.items():
            feed(f, "file", min(c, 3))
        for s, c in spaces.items():
            feed(s.split(".")[-1], "namespace", min(c, 3))
        for d, c in folders.items():
            feed(d.split("/")[-1], "folder", min(c, 3))
        roles = Counter()
        for i in classes:
            lab = re.sub(r"\(.*$", "", nodes[i].get("label") or "")
            for suf, role in ROLE:
                if lab.endswith(suf) and lab != suf:
                    roles[role] += 1
                    break
        role = roles.most_common(1)[0][0] if roles and roles.most_common(1)[0][1] >= max(1, len(classes) * 0.34) else ""
        top_ext = exts.most_common(1)[0][0] if exts else ""
        if not role and top_ext in EXT_ROLE and exts[top_ext] >= 0.5 * sum(exts.values()):
            role = EXT_ROLE[top_ext]
        if not role and all(re.search(r"(^|/)tests?(/|$)|Tests?/", nodes[i].get("source_file") or "", re.I) for i in ids if nodes[i].get("source_file")):
            role = "Tests"
        # word order as it appears in the hub names ("StockMovement" -> stock, movement), for readable names
        order = {}
        for i in hubs + classes:
            for k, w in enumerate(words(plain(i))):
                order.setdefault(singular(w), len(order))
        out[cid] = {"size": len(ids), "bag": bag, "role": role, "order": order,
                    "hubs": [plain(i) for i in hubs],
                    "hub_kinds": ["class/type" if nodes[i].get("_callable_class") else "method" if i in owner else (nodes[i].get("type") or "file/function")
                                  for i in hubs],
                    "folders": [d for d, _ in folders.most_common(3) if d], "namespaces": [s for s, _ in spaces.most_common(3)],
                    "classes": len(classes), "methods": sum(1 for i in ids if i in owner)}
    return out


def heuristic(profs, product_words=()):
    n = len(profs) or 1
    df = Counter()
    for p in profs.values():
        df.update(set(p["bag"]))
    stop = {singular(w) for w in product_words}
    ranked = {}
    for cid, p in profs.items():
        ranked[cid] = [w for w, _ in sorted(((w, s * math.log(1 + n / df[w])) for w, s in p["bag"].items()
                                              if w not in stop and (df[w] <= max(2, 0.6 * n) or n < 4)), key=lambda x: -x[1])]
    names, used = {}, Counter()

    def title(ws, order):
        ws = sorted(ws, key=lambda w: order.get(w, 999))
        return " ".join(w.upper() if w in ACRONYMS else w.capitalize() for w in ws)

    for cid in sorted(profs, key=lambda c: -profs[c]["size"]):
        p, terms = profs[cid], ranked[cid]
        if p["size"] == 1 or not terms:
            base = p["hubs"][0] if p["hubs"] else f"Group {cid}"
            cand = [re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", base)]
        else:
            role_words = {singular(w) for w in words(p["role"])}
            pick = []
            for t in terms:                       # skip the role's own words and near-duplicate stems (pricing / price)
                if t not in role_words and not any(t[:4] == q[:4] for q in pick):
                    pick.append(t)
                if len(pick) == 2:
                    break
            pick = pick or terms[:2]
            suffix = f" {p['role']}" if p["role"] else ""
            cand = [title(pick, p["order"]) + suffix]
            # clash tie-breakers: the project the community lives in, then the next distinguishing words
            proj = next((w for f in p["folders"] for seg in f.split("/")[:2][::-1] for w in reversed(words(seg))
                         if singular(w) not in stop and w not in ("src", "test", "tests") and singular(w) not in pick), None)
            if proj:
                cand.append(f"{proj.upper() if proj in ACRONYMS else proj.capitalize()} {cand[0]}")
            for extra in [t for t in terms if t not in pick and t not in role_words][:3]:
                cand.append(title(pick + [extra], p["order"]) + suffix)
            if p["hubs"]:
                cand.append(f"{cand[0]} ({p['hubs'][0]})")
        name = next((c for c in cand if not used[c.lower()]), f"{cand[0]} {cid}")
        used[name.lower()] += 1
        names[cid] = name
    return names, ranked


def summary_line(p):
    bits = [f"{p['size']} members ({p['classes']} types, {p['methods']} methods)"]
    if p["role"]:
        bits.append(f"mostly {p['role'].lower()}")
    if p["hubs"]:
        bits.append("centred on " + ", ".join(p["hubs"][:3]))
    if p["folders"]:
        bits.append(f"in {p['folders'][0]}")
    return "; ".join(bits) + "."


# ---------------------------------------------------------------- LLM

PROVIDERS = {  # key env var -> (OpenAI-compatible base URL, default model); ANTHROPIC uses its own API
    "OPENROUTER_API_KEY": ("https://openrouter.ai/api/v1", "z-ai/glm-5.3-flash"),
    "OPENAI_API_KEY": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "DEEPSEEK_API_KEY": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "MOONSHOT_API_KEY": ("https://api.moonshot.ai/v1", "kimi-latest"),
    "GEMINI_API_KEY": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    "ANTHROPIC_API_KEY": ("https://api.anthropic.com/v1", "claude-haiku-4-5-20251001"),
}
PROMPT = """You name clusters (communities) of a software system's code graph so developers and AI agents can navigate it.
Each cluster below comes with its most connected members (with their kind), namespaces, folders, its dominant role, and a
machine-made name as a hint. For EVERY cluster return:
- "name": 2-5 words, Title Case, plain business or technical language (e.g. "Order Fulfilment Workflow", "Coupon Pricing
  Rules", "Admin Customer Screens"). Prefer the domain concept over generic words like Core, Utils, Module, Misc, Stuff.
  Every name must be different from every other name in this list; when two clusters are about the same topic, say what
  differs (layer, app, sub-topic).
- "summary": one sentence (max 25 words) saying what the cluster does, using the member names as evidence.
Answer ONLY with a JSON object: {"<cluster id>": {"name": "...", "summary": "..."}, ...}

Clusters:
"""


def env_value(name):
    v = os.environ.get(name)
    if v or os.name != "nt":
        return v
    try:
        import subprocess
        out = subprocess.run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetEnvironmentVariable('{name}','User')"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def pick_provider(cfg, model_arg=None):
    g = cfg.get("graph", {})
    names = [g["api_key_env"]] if g.get("api_key_env") else list(PROVIDERS)
    for n in names:
        key = env_value(n)
        if key:
            base, dflt = PROVIDERS.get(n, (g.get("base_url"), None))
            model = model_arg or g.get("model") or env_value("CODEBASE_DOCS_LLM_MODEL") or dflt
            return {"env": n, "key": key, "base": g.get("base_url") or base, "model": model, "anthropic": n == "ANTHROPIC_API_KEY"}
    return None


def chat(prov, prompt, timeout=120):
    if prov["anthropic"]:
        req = urllib.request.Request(prov["base"] + "/messages", data=json.dumps({
            "model": prov["model"], "max_tokens": 4000, "messages": [{"role": "user", "content": prompt}]}).encode(),
            headers={"x-api-key": prov["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        return "".join(b.get("text", "") for b in d.get("content", [])), d.get("usage", {})
    body = {"model": prov["model"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.2,
            "response_format": {"type": "json_object"}}
    headers = {"Authorization": f"Bearer {prov['key']}", "Content-Type": "application/json"}
    if "openrouter" in prov["base"]:
        headers["X-Title"] = "codebase-documenter"
    req = urllib.request.Request(prov["base"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    return d["choices"][0]["message"]["content"] or "", d.get("usage", {})


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = text.find("{"), text.rfind("}")
    return json.loads(text[i:j + 1]) if i >= 0 and j > i else {}


def describe(cid, p, hint):
    hubs = ", ".join(f"{h} [{k}]" for h, k in zip(p["hubs"], p["hub_kinds"]))
    return (f'- id {cid} ({p["size"]} members): hubs: {hubs}; namespaces: {", ".join(p["namespaces"]) or "-"}; '
            f'folders: {", ".join(p["folders"]) or "-"}; role: {p["role"] or "-"}; hint: {hint}')


def llm_names(prov, profs, hints, ids, batch, log):
    got = {}
    usage = Counter()
    for k in range(0, len(ids), batch):
        part = ids[k:k + batch]
        prompt = PROMPT + "\n".join(describe(c, profs[c], hints[c]) for c in part)
        for attempt in range(2):
            try:
                text, u = chat(prov, prompt)
                usage.update({x: v for x, v in u.items() if isinstance(v, (int, float))})
                data = parse_json(text)
                for c in part:
                    v = data.get(str(c))
                    if isinstance(v, dict) and str(v.get("name", "")).strip():
                        got[c] = {"name": str(v["name"]).strip()[:60], "summary": str(v.get("summary", "")).strip()[:240]}
                break
            except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as e:
                log(f"  batch {k // batch + 1}: attempt {attempt + 1} failed ({str(e)[:160]})")
    return got, usage


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="name with an LLM (falls back to heuristic names per community)")
    ap.add_argument("--model")
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--only-missing", action="store_true", help="LLM only for communities still named by the heuristic")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--graph-dir", help="standalone use (no codebase-docs.json): folder holding graph.json")
    ap.add_argument("--product", default="", help="standalone use: product / repository name (its words never name a community)")
    a = ap.parse_args()
    if a.graph_dir:
        root, cfg = os.getcwd(), {"graph_dir": a.graph_dir, "product": a.product, "graph": {}}
    else:
        root, cfg = load_config()
    os.chdir(root)
    gdir = cfg["graph_dir"]
    g = json.load(open(os.path.join(gdir, "graph.json"), encoding="utf-8"))
    spath = os.path.join(gdir, "community-summaries.json")
    old = json.load(open(spath, encoding="utf-8")) if os.path.exists(spath) else {}
    if a.show:
        for cid, v in sorted(old.items(), key=lambda kv: -kv[1].get("size", 0)):
            print(f"{cid:>4} {v.get('size', 0):>5}  {v['name']:<40} [{v.get('source')}] {v.get('summary', '')}")
        return
    profs = profiles(g)
    product_words = [w for k in ("product", "code_name", "slug") for w in words(cfg.get(k) or "")]
    names, ranked = heuristic(profs, product_words)
    result = {}
    for cid, p in profs.items():
        result[cid] = {"name": names[cid], "summary": summary_line(p), "source": "heuristic", "size": p["size"], "role": p["role"],
                       "hubs": p["hubs"], "folders": p["folders"], "namespaces": p["namespaces"], "terms": ranked[cid][:8]}
        prev = old.get(str(cid))
        if prev and prev.get("source") in ("llm", "manual") and prev.get("hubs", [])[:2] == p["hubs"][:2]:
            result[cid].update(name=prev["name"], summary=prev.get("summary", result[cid]["summary"]), source=prev["source"])
    usage = Counter()
    if a.llm:
        prov = pick_provider(cfg, a.model)
        if not prov:
            print("no LLM key found: heuristic names kept (see `code_graph.py check` for keys)")
        else:
            ids = [c for c in sorted(profs, key=lambda c: -profs[c]["size"]) if profs[c]["size"] > 1
                   and not (a.only_missing and result[c]["source"] != "heuristic")]
            print(f"naming {len(ids)} communities with {prov['model']} (key {prov['env']}), batches of {a.batch}")
            got, usage = llm_names(prov, profs, names, ids, a.batch, print)
            for c, v in got.items():
                result[c].update(name=v["name"], summary=v["summary"] or result[c]["summary"], source="llm")
            # clash pass: re-ask only for names that are still the same, side by side
            clash = defaultdict(list)
            for c, v in result.items():
                clash[v["name"].lower()].append(c)
            dups = [cs for cs in clash.values() if len(cs) > 1]
            if dups:
                flat = [c for cs in dups for c in cs]
                print(f"  {len(dups)} clashing names across {len(flat)} communities: asking again side by side")
                got2, u2 = llm_names(prov, profs, {c: result[c]["name"] for c in flat}, flat, max(a.batch, len(flat)), print)
                usage.update(u2)
                for c, v in got2.items():
                    result[c].update(name=v["name"], summary=v["summary"] or result[c]["summary"], source="llm")
            print(f"  llm named {sum(1 for v in result.values() if v['source'] == 'llm')} · usage: "
                  + ", ".join(f"{k} {v:g}" for k, v in usage.items() if k in ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens", "cost")))
    # final uniqueness guarantee, whatever produced the names
    seen = Counter()
    for c in sorted(result, key=lambda c: -result[c]["size"]):
        n = result[c]["name"]
        if seen[n.lower()]:
            extra = next((t.capitalize() for t in result[c]["terms"] if t not in n.lower()), None)
            n = f"{n} {extra}" if extra and not seen[f"{n} {extra}".lower()] else f"{n} ({result[c]['hubs'][0] if result[c]['hubs'] else c})"
            result[c]["name"] = n
        seen[n.lower()] += 1
    write(os.path.join(gdir, ".graphify_labels.json"), json.dumps({str(c): v["name"] for c, v in sorted(result.items())}, indent=2, ensure_ascii=False))
    write(spath, json.dumps({str(c): v for c, v in sorted(result.items())}, indent=1, ensure_ascii=False))
    src = Counter(v["source"] for v in result.values())
    print(f"community names: {len(result)} ({', '.join(f'{k} {v}' for k, v in src.items())}), all unique -> {gdir}/.graphify_labels.json")


if __name__ == "__main__":
    main()
