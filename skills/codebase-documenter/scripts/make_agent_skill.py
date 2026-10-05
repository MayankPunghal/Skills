"""Create the agent layer for the documented project (deterministic, from templates):

    python <skill>/scripts/make_agent_skill.py

Writes (re-runnable; regenerates generated parts, keeps hand edits outside the marked blocks):
  AGENTS.md                                  rules for every coding agent (Codex, Cursor, Copilot, Claude …)
  CLAUDE.md                                  appends / refreshes a "<product> documentation" block
  .claude/skills/<slug>-docs/SKILL.md        the project's Q&A / change-planning skill (named after the product)
  docs/_tools/*.py                           runtime tools (build_docs, gen_agent_index, gen_rag_cards, lookup) refreshed
and then runs gen_agent_index.py (docs/llms.txt + docs/agent/entities.jsonl) and gen_rag_cards.py (docs/agent/cards.jsonl).
"""
import os
import re
import shutil
import sys

from _common import SKILL_DIR, load_config, render, run, tick, utf8_stdout, write

BEGIN, END = "<!-- codebase-documenter:begin -->", "<!-- codebase-documenter:end -->"


def upsert_block(path, block):
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    wrapped = f"{BEGIN}\n{block.strip()}\n{END}\n"
    if BEGIN in text and END in text:
        text = text[:text.index(BEGIN)] + wrapped + text[text.index(END) + len(END) + 1:]
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + wrapped
    write(path, text)


def main():
    utf8_stdout()
    root, cfg = load_config()
    os.chdir(root)
    docs = cfg["docs_dir"]
    slug = cfg["slug"]
    kinds = sorted({k for k in re.findall(r'"kind": "([\w-]+)"', open(os.path.join(docs, "agent", "entities.jsonl"), encoding="utf-8").read())}) \
        if os.path.exists(os.path.join(docs, "agent", "entities.jsonl")) else []
    tasks = []
    for d, label in (("modules", "Business behaviour of a module"), ("workflows", "End-to-end flows and status changes"),
                     ("integrations", "External systems, inbound API, scheduled jobs"), ("data", "Data model, databases, codes & statuses"),
                     ("security", "Authentication, authorisation, security findings"), ("architecture", "Architecture, configuration, jobs"),
                     ("appendices", "Glossary, defects & technical debt")):
        if os.path.isdir(os.path.join(docs, "_src", d)):
            tasks.append(f"| {label} | `{docs}/{d}/` |")
    vals = {"product": cfg["product"] or slug, "code_name": cfg.get("code_name") or cfg["product"], "slug": slug,
            "description": cfg.get("description") or "", "stack": cfg.get("stack") or "", "docs_dir": docs,
            "source_root": cfg["source_root"], "kinds": ", ".join(f"`{k}`" for k in kinds) or "`table`, `routine`, `class`, `page`, `section`",
            "task_rows": "\n".join(tasks), "sensitive": ", ".join(f"`{docs}/{s}`" for s in cfg.get("sensitive", [])) or "none",
            "skill_name": f"{slug}-docs"}
    write("AGENTS.md", render("AGENTS.md.tmpl", vals))
    upsert_block("CLAUDE.md", render("CLAUDE.block.md.tmpl", vals))
    sk = os.path.join(".claude", "skills", f"{slug}-docs", "SKILL.md")
    write(sk, render("project-skill.md.tmpl", vals))
    os.makedirs(os.path.join(docs, "_tools"), exist_ok=True)
    for f in ("build_docs.py", "gen_agent_index.py", "gen_rag_cards.py", "lookup.py"):
        shutil.copy2(os.path.join(SKILL_DIR, "scripts", "runtime", f), os.path.join(docs, "_tools", f))
    code, out = run([sys.executable, os.path.join(docs, "_tools", "gen_agent_index.py")])
    print(out.strip()[:200])
    print(run([sys.executable, os.path.join(docs, "_tools", "gen_rag_cards.py")])[1].strip()[-200:])
    code2, out2 = run([sys.executable, os.path.join(docs, "_tools", "lookup.py"), "index", "--kind", "page", "--list", "--limit", "1"])
    print(f"AGENTS.md, CLAUDE.md block, {sk} written; lookup smoke test: {'ok' if code2 == 0 else 'FAILED'}")
    if code2:
        print(out2[-800:])
    else:
        tick(cfg, "make-agent-skill")


if __name__ == "__main__":
    main()
