"""Headline numbers of the generated reference, for the [[n:area.key]] tag in hand-written pages.

Each adapter calls stat("db-access", sites=401, objects=93, ...) once; the values land in docs/agent/stats.json and
build_docs.py replaces [[n:db-access.sites]] with the current number on every build. A page that types "455 call sites"
goes stale the next time the code (or a scanner fix) changes the count; a tag cannot.
"""
import json
import os


def stat(area, **values):
    cfg = json.load(open("codebase-docs.json", encoding="utf-8")) if os.path.exists("codebase-docs.json") else {}
    p = os.path.join(cfg.get("docs_dir", "docs"), "agent", "stats.json")
    data = {}
    if os.path.exists(p):
        try:
            data = json.load(open(p, encoding="utf-8"))
        except ValueError:
            data = {}
    data[area] = {k: v for k, v in values.items()}
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8", newline="\n").write(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
