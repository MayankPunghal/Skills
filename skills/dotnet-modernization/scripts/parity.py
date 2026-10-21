"""Behaviour parity: record request/response pairs from the running original, replay them against the port (run, do not read).

    python scripts/parity.py record --base-url http://old-host:8080 --requests requests.json --goldens <dir>
    python scripts/parity.py replay --base-url http://localhost:8080 --goldens <dir> [--masks masks.json] [--out <dir>]

requests.json: a list of {"name": "search-hotels", "method": "POST", "path": "/xml/gateway.ashx",
  "headers": {"Content-Type": "text/xml"}, "body": "<xml .../>" | "body_file": "req/search.xml", "timeout": 60}.
  Paths are replayed as they are unless "path_new" gives the port's route (an .ashx moved to an endpoint).
Record calls the original (a test environment, never production) and saves one golden per request.
Replay sends the same requests to the port and compares status code and body after normalising:
  - JSON and XML are parsed and compared structurally (key / attribute order and whitespace do not matter);
  - masks (regex list, default: GUIDs, ISO and /Date()/ timestamps, session-like tokens) replace volatile values
    with <masked> on both sides; masks.json may add {"regex": "...", "why": "..."} entries or {"xml_path"/"json_key"}
    names whose values are ignored.
  - the raw response is compared as well, exactly: the charset in Content-Type, the XML declaration (version and
    encoding) and a leading byte order mark. A changed charset or declaration is a difference, not a formatting detail.
Writes <out>/parity.json and parity.md with its .html twin (default <out> = the goldens folder's parent). Exit 1 on any
difference. Standard library only.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mdhtml import write_pair  # noqa: E402

DEFAULT_MASKS = [
    {"regex": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "why": "GUID"},
    {"regex": r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?", "why": "timestamp"},
    {"regex": r"/Date\(\d+([+-]\d{4})?\)/", "why": "MS JSON date"},
    {"regex": r"(?i)(session|token|nonce|requestid|correlationid)([\"'=:>\s]+)[A-Za-z0-9+/=_-]{8,}", "why": "session-like token", "keep": r"\1\2"},
]


def call(base, req, path_key="path"):
    body = req.get("body")
    if req.get("body_file"):
        body = open(req["body_file"], "rb").read()
    elif isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    elif isinstance(body, str):
        body = body.encode("utf-8")
    url = base.rstrip("/") + (req.get(path_key) or req["path"])
    r = urllib.request.Request(url, data=body, method=req.get("method", "POST" if body else "GET"), headers=req.get("headers") or {})
    t = time.time()
    try:
        with urllib.request.urlopen(r, timeout=req.get("timeout", 60)) as resp:
            status, ctype, data = resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as e:
        status, ctype, data = e.code, e.headers.get("Content-Type", ""), e.read()
    except (urllib.error.URLError, OSError) as e:
        return {"status": None, "error": str(e), "ms": round((time.time() - t) * 1000)}
    return {"status": status, "content_type": ctype, "body": data.decode("utf-8", "replace"), "ms": round((time.time() - t) * 1000)}


def masked(text, masks):
    for m in masks:
        text = re.sub(m["regex"], m.get("keep", "") + "<masked>" if m.get("keep") else "<masked>", text)
    return text


def _xml(e, ignore):
    tag = e.tag.split("}")[-1]
    if tag in ignore:
        return (tag, "<ignored>")
    attrs = tuple(sorted((k.split("}")[-1], "<ignored>" if k.split("}")[-1] in ignore else v) for k, v in e.attrib.items()))
    return (tag, attrs, (e.text or "").strip(), tuple(_xml(c, ignore) for c in e))


def _json(v, ignore):
    if isinstance(v, dict):
        return {k: ("<ignored>" if k in ignore else _json(x, ignore)) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [_json(x, ignore) for x in v]
    return v


def normal(body, masks, ignore):
    b = masked(body or "", masks).strip()
    try:
        return "json", _json(json.loads(b), ignore)
    except ValueError:
        pass
    try:
        return "xml", _xml(ET.fromstring(b), ignore)
    except ET.ParseError:
        return "text", " ".join(b.split())


def charset(ctype):
    m = re.search(r"charset\s*=\s*\"?([^;\"\s]+)", ctype or "", re.I)
    return m.group(1).lower() if m else None


def xml_declaration(body):
    """(version, encoding) of a leading XML declaration, or None when the body has none."""
    m = re.match(r"\s*<\?xml\s+([^?]*)\?>", (body or "").lstrip("﻿"))
    if not m:
        return None
    attrs = dict(re.findall(r"(\w+)\s*=\s*[\"']([^\"']*)[\"']", m.group(1)))
    enc = attrs.get("encoding")
    return attrs.get("version"), enc.lower() if enc else None


def raw_diff(old, new):
    """Checks on the raw response that the structural compare ignores: charset, XML declaration, byte order mark."""
    co, cn = charset(old.get("content_type")), charset(new.get("content_type"))
    if co != cn:
        return f"Content-Type charset {co} (golden) vs {cn} (port)"
    bo, bn = (old.get("body") or "").startswith("﻿"), (new.get("body") or "").startswith("﻿")
    if bo != bn:
        return f"byte order mark {'present' if bo else 'absent'} in golden, {'present' if bn else 'absent'} in port"
    xo, xn = xml_declaration(old.get("body")), xml_declaration(new.get("body"))
    if xo != xn:
        return f"XML declaration {xo} (golden) vs {xn} (port)"
    return None


def first_diff(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: only in {'golden' if k in a else 'port'}"
            d = first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return f"{path}: {len(a)} items vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {str(a)[:80]!r} vs {str(b)[:80]!r}"


def record(a):
    reqs = json.load(open(a.requests, encoding="utf-8"))
    os.makedirs(a.goldens, exist_ok=True)
    for q in reqs:
        r = call(a.base_url, q)
        json.dump({"request": q, "response": r}, open(os.path.join(a.goldens, q["name"] + ".json"), "w", encoding="utf-8"), indent=1)
        print(f"{q['name']}: {r.get('status') or r.get('error')} {r['ms']} ms")


def replay(a):
    masks = DEFAULT_MASKS[:]
    ignore = set()
    if a.masks:
        for m in json.load(open(a.masks, encoding="utf-8")):
            if m.get("regex"):
                masks.append(m)
            ignore.update(x for x in (m.get("xml_path"), m.get("json_key")) if x)
    rows = []
    for fn in sorted(os.listdir(a.goldens)):
        if not fn.endswith(".json"):
            continue
        g = json.load(open(os.path.join(a.goldens, fn), encoding="utf-8"))
        q, old = g["request"], g["response"]
        new = call(a.base_url, q, "path_new" if q.get("path_new") else "path")
        diff = None
        if new.get("status") != old.get("status"):
            diff = f"status {old.get('status')} vs {new.get('status') or new.get('error')}"
        else:
            ko, vo = normal(old.get("body"), masks, ignore)
            kn, vn = normal(new.get("body"), masks, ignore)
            diff = f"body format {ko} vs {kn}" if ko != kn else first_diff(vo, vn)
            diff = diff or raw_diff(old, new)
        rows.append({"name": q["name"], "path": q.get("path_new") or q["path"], "status_old": old.get("status"), "status_new": new.get("status"),
                     "ms_old": old.get("ms"), "ms_new": new.get("ms"), "match": diff is None, "diff": diff})
    out = a.out or os.path.dirname(os.path.abspath(a.goldens))
    os.makedirs(out, exist_ok=True)
    res = {"base_url": a.base_url, "goldens": os.path.abspath(a.goldens), "masks": [m.get("why") or m["regex"] for m in masks],
           "ignored_names": sorted(ignore), "total": len(rows), "matched": sum(r["match"] for r in rows), "rows": rows}
    res["passed"] = res["total"] > 0 and res["matched"] == res["total"]
    json.dump(res, open(os.path.join(out, "parity.json"), "w", encoding="utf-8"), indent=1)
    L = ["# Parity replay", "", f"{res['matched']} of {res['total']} recorded requests match at `{a.base_url}`. "
         f"**{'PASS' if res['passed'] else 'FAIL'}**.", "", f"Masked: {', '.join(res['masks'])}. Ignored names: {', '.join(res['ignored_names']) or 'none'}. "
         "Raw checks: Content-Type charset, XML declaration, byte order mark.", "",
         "| Request | Path | Status (old / new) | ms (old / new) | Match | First difference |", "|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['name']} | `{r['path']}` | {r['status_old']} / {r['status_new']} | {r['ms_old']} / {r['ms_new']} | "
                 f"{'yes' if r['match'] else 'no'} | {(r['diff'] or '').replace('|', '/')} |")
    hp = write_pair(os.path.join(out, "parity.md"), "\n".join(L) + "\n")
    print(f"parity: {res['matched']}/{res['total']} match -> {hp}")
    return res["passed"]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--base-url", required=True)
    r.add_argument("--requests", required=True)
    r.add_argument("--goldens", required=True)
    p = sub.add_parser("replay")
    p.add_argument("--base-url", required=True)
    p.add_argument("--goldens", required=True)
    p.add_argument("--masks")
    p.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "record":
        record(a)
    else:
        sys.exit(0 if replay(a) else 1)


if __name__ == "__main__":
    main()
