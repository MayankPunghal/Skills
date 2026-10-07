"""Research-note bookkeeping (deterministic): note files from the template and the PROGRESS.md checklist.

    python <skill>/scripts/research_notes.py plan               # areas.json -> one note file + one PROGRESS line per area
    python <skill>/scripts/research_notes.py new 45-billing "Billing" --paths src/Billing,src/Invoices
    python <skill>/scripts/research_notes.py done 45-billing    # tick the area in PROGRESS.md
    python <skill>/scripts/research_notes.py status             # which areas are open, note sizes
    python <skill>/scripts/research_notes.py correct "<what was wrong → what is right (evidence file)>"   # corrections log
"""
import argparse
import json
import os
import re

import sys

from _common import load_config, note_problems, render, utf8_stdout, write

BEGIN, END = "<!-- docs:areas -->", "<!-- /docs:areas -->"


def progress_path(cfg):
    return os.path.join(cfg["docs_dir"], "_notes", "PROGRESS.md")


def set_areas(cfg, areas):
    p = progress_path(cfg)
    text = open(p, encoding="utf-8").read()
    old = {m.group(2): m.group(1) == "x" for m in re.finditer(r"- \[( |x)\] research ([\w-]+)", text)}
    lines = [f"- [{'x' if old.get(a['id']) else ' '}] research {a['id']} — {a['title']}" for a in areas]
    i, j = text.index(BEGIN) + len(BEGIN), text.index(END)
    write(p, text[:i] + "\n" + "\n".join(lines) + "\n" + text[j:])


def make_note(cfg, area):
    path = os.path.join(cfg["docs_dir"], "_notes", f"{area['id']}.md")
    return write(path, render("note.md.tmpl", {"id": area["id"], "title": area["title"],
                                               "paths": ", ".join(f"`{p}`" for p in area.get("paths", [])) or "?",
                                               "communities": ", ".join(area.get("communities", [])) or "?"}), overwrite=False)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("plan")
    n = sp.add_parser("new")
    n.add_argument("id")
    n.add_argument("title")
    n.add_argument("--paths", default="")
    d = sp.add_parser("done")
    d.add_argument("id")
    sp.add_parser("status")
    c = sp.add_parser("correct")
    c.add_argument("text")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    ajson = os.path.join(cfg["docs_dir"], "_notes", "areas.json")
    areas = json.load(open(ajson, encoding="utf-8")) if os.path.exists(ajson) else []
    if a.cmd == "plan":
        made = sum(make_note(cfg, ar) for ar in areas)
        set_areas(cfg, areas)
        print(f"{len(areas)} areas in PROGRESS.md; {made} new note files")
    elif a.cmd == "new":
        ar = {"id": a.id, "title": a.title, "paths": [x for x in a.paths.split(",") if x], "communities": []}
        areas = [x for x in areas if x["id"] != a.id] + [ar]
        areas.sort(key=lambda x: x["id"])
        write(ajson, json.dumps(areas, indent=1, ensure_ascii=False))
        make_note(cfg, ar)
        set_areas(cfg, areas)
        print(f"added area {a.id}")
    elif a.cmd == "done":
        bad = note_problems(os.path.join(cfg["docs_dir"], "_notes", f"{a.id}.md"))
        if bad:
            print(f"not ticked: note {a.id}.md is not finished: " + "; ".join(bad), file=sys.stderr)
            sys.exit(1)
        p = progress_path(cfg)
        t = open(p, encoding="utf-8").read()
        t2 = re.sub(rf"- \[ \] (research {re.escape(a.id)}\b)", r"- [x] \1", t)
        write(p, t2)
        print("ticked" if t2 != t else f"no open line for {a.id}")
    elif a.cmd == "correct":
        p = progress_path(cfg)
        t = open(p, encoding="utf-8").read().rstrip() + f"\n- {a.text}\n"
        write(p, t)
        print("logged correction")
    else:
        t = open(progress_path(cfg), encoding="utf-8").read()
        for m in re.finditer(r"- \[( |x)\] research ([\w-]+) — (.+)", t):
            f = os.path.join(cfg["docs_dir"], "_notes", m.group(2) + ".md")
            size = sum(1 for _ in open(f, encoding="utf-8")) if os.path.exists(f) else 0
            bad = note_problems(f)
            flag = ("  TICKED BUT NOT FINISHED: " if m.group(1) == "x" else "  ") + "; ".join(bad) if bad else ""
            print(f"[{'x' if m.group(1) == 'x' else ' '}] {m.group(2):<32} {size:>4} lines{flag}")


if __name__ == "__main__":
    main()
