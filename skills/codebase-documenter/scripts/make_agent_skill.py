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
    if os.path.exists(os.path.join(docs, "reference", "dependency-injection.md")):
        tasks.append(f"| What actually runs behind an interface, base class, message, event or delegate; DI lifetimes per host | "
                     f"`{docs}/reference/dependency-injection.md` (data: `{docs}/agent/di.json`)"
                     + (f", `{docs}/architecture/dependency-injection.md`" if os.path.exists(os.path.join(docs, "_src", "architecture", "dependency-injection.md")) else "") + " |")
    if os.path.exists(os.path.join(docs, "reference", "db-routines.md")):
        tasks.append(f"| What a procedure / function / trigger reads, writes and calls; which code runs it | "
                     f"`{docs}/reference/db-routines.md`, `{docs}/reference/db-tables.md`, `{docs}/reference/db-access.md` "
                     f"(data: `{docs}/agent/db.json`, `{docs}/agent/db-access.json`; parsed with Microsoft's T-SQL parser) |")
    if os.path.exists(os.path.join(docs, "reference", "db-postgres.md")):
        tasks.append(f"| What converts to PostgreSQL automatically, what needs a rewrite, what has no equivalent | `{docs}/reference/db-postgres.md` |")
    if os.path.exists(os.path.join(docs, "reference", "dependencies.md")):
        tasks.append(f"| Which project depends on which, build / port order, package versions, licences, Windows-only packages | "
                     f"`{docs}/reference/dependencies.md` (data: `{docs}/agent/dependencies.json`) |")
    if os.path.exists(os.path.join(docs, "reference", "views-and-pages.md")):
        tasks.append(f"| How many screens / views / pages there are, per kind and project; a screen's route, model, layout, code-behind | "
                     f"`{docs}/reference/views-and-pages.md` (data: `{docs}/agent/views.json`) |")
    if os.path.exists(os.path.join(docs, "reference", "platform-portability.md")):
        tasks.append(f"| What breaks on Linux / modern .NET (Windows-only APIs, removed APIs, Windows paths, time zones) and where | "
                     f"`{docs}/reference/platform-portability.md` (data: `{docs}/agent/portability.json`) |")
    if os.path.exists(os.path.join(docs, "reference", "entry-points.md")):
        tasks.append(f"| What starts a method; which tables a screen or endpoint changes | `{docs}/reference/entry-points.md`, `{docs}/reference/ui-map.md` |")
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
