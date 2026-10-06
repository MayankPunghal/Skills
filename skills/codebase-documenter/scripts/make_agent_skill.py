"""Create the agent layer for the documented project (deterministic, from templates):

    python <skill>/scripts/make_agent_skill.py

Writes (re-runnable; regenerates generated parts, keeps hand edits outside the marked blocks):
  AGENTS.md                                  rules for every coding agent (Codex, Cursor, Copilot, Claude …)
  CLAUDE.md                                  appends / refreshes a "<product> documentation" block
  .claude/skills/<slug>-docs/SKILL.md        the project's Q&A / change-planning skill (named after the product)
  docs/_tools/*.py                           runtime tools (build_docs, gen_agent_index, gen_rag_cards, lookup, trace_calls) refreshed
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


NAV_PREFIXES = {"index", "kind", "letter", "area", "proj", "project", "group", "section", "by", "top", "summary"}
TAG_OF_PREFIX = {"tbl": "table", "sp": "proc"}


def db_facts(docs, graph_dir):
    """What the database reference and the graph really hold, so the templates never promise parsed SQL or graph nodes
    that a code-only repository does not have."""
    import json
    dbj = os.path.join(docs, "agent", "db.json")
    db = json.load(open(dbj, encoding="utf-8")) if os.path.exists(dbj) else {}
    routines = db.get("routines", [])
    parsed = bool(db.get("tables")) or any(r.get("defined", True) is not False for r in routines)
    code_only = sum(1 for r in routines if r.get("defined") is False)
    sg = os.path.join(graph_dir, "sql-graph.json")
    sgj = json.load(open(sg, encoding="utf-8")) if os.path.exists(sg) else {}
    return parsed, code_only, sgj.get("objects", 0), sgj.get("code_only_calls", 0)


def tag_kinds(docs):
    """Link-tag kinds that resolve in this project: the anchor prefixes the reference pages really carry."""
    ref = os.path.join(docs, "reference")
    seen = set()
    for f in (os.listdir(ref) if os.path.isdir(ref) else []):
        if f.endswith(".md"):
            for p in re.findall(r'<a id="([a-z]+)-', open(os.path.join(ref, f), encoding="utf-8").read()):
                if p not in NAV_PREFIXES:
                    seen.add(TAG_OF_PREFIX.get(p, p))
    first = [k for k in ("table", "proc", "cls", "mth", "ctl", "act", "ep", "enum") if k in seen]
    return ", ".join(f"`[[{k}:X]]`" for k in first + sorted(seen - set(first))[:8] + ["page", "n"])


def survey_stack(docs, stack):
    """The configured stack plus anything the survey detected that it does not mention (databases, main frameworks)."""
    import json
    p = os.path.join(docs, "_notes", "survey.json")
    if not os.path.exists(p):
        return stack
    extra = [x for x in json.load(open(p, encoding="utf-8")).get("stack_summary", []) if x.lower() not in (stack or "").lower()]
    return ", ".join(x for x in [stack] + extra if x)


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
    parsed, code_only, graph_objects, graph_code_only = db_facts(docs, cfg.get("graph_dir", "graphify-out"))
    db_pages = [f"`{docs}/reference/{p}`" for p in ("db-routines.md", "db-tables.md", "db-code-routines.md", "db-access.md")
                if os.path.exists(os.path.join(docs, "reference", p))]
    db_data = [f"`{docs}/agent/{p}`" for p in ("db.json", "db-access.json") if os.path.exists(os.path.join(docs, "agent", p))]
    if parsed and db_pages:
        tasks.append(f"| What a procedure / function / trigger reads, writes and calls; which code runs it | {', '.join(db_pages)} "
                     f"(data: {', '.join(db_data)}; parsed with Microsoft's T-SQL parser) |")
    elif code_only and db_pages:
        tasks.append(f"| Which stored procedures the code runs and from where (definitions are not in the repository: "
                     f"parameters and tables are unknown) | {', '.join(db_pages)}" + (f" (data: {', '.join(db_data)})" if db_data else "") + " |")
    if graph_objects:
        db_graph_note = ("Database objects are graph nodes too (parsed SQL): `graphify affected \"<table or procedure>\"` lists the "
                         "routines and C# methods that read, write or run it.")
        db_graph_skill_note = ("The graph also holds the database layer (nodes for tables, procedures, functions, triggers; edges "
                               "`reads_from` / `writes_to` / `calls` from routines and from the C# methods whose SQL or procedure names "
                               "reach them, context `embedded SQL` / `name in code`), so `graphify affected \"<table or procedure>\"` "
                               "shows the code a schema change hits.")
    elif graph_code_only:
        db_graph_note = ("The repository holds no SQL: procedures the code runs by name are graph nodes without a definition "
                         "(`graphify affected \"<procedure>\"` lists the C# methods that run it), but tables are not, so table-level "
                         f"impact needs the schema. `{docs}/reference/db-access.md` lists every call site.")
        db_graph_skill_note = db_graph_note
    else:
        db_graph_note = ("The graph holds no database objects for this project; use the database pages above "
                         f"(`{docs}/reference/db-access.md` when present) for which code reaches which table or procedure.")
        db_graph_skill_note = db_graph_note
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
            "description": cfg.get("description") or "", "stack": survey_stack(docs, cfg.get("stack") or ""), "docs_dir": docs,
            "db_graph_note": db_graph_note, "db_graph_skill_note": db_graph_skill_note, "tag_kinds": tag_kinds(docs),
            "source_root": cfg["source_root"], "kinds": ", ".join(f"`{k}`" for k in kinds) or "`table`, `routine`, `class`, `page`, `section`",
            "task_rows": "\n".join(tasks), "sensitive": ", ".join(f"`{docs}/{s}`" for s in cfg.get("sensitive", [])) or "none",
            "skill_name": f"{slug}-docs"}
    write("AGENTS.md", render("AGENTS.md.tmpl", vals))
    upsert_block("CLAUDE.md", render("CLAUDE.block.md.tmpl", vals))
    sk = os.path.join(".claude", "skills", f"{slug}-docs", "SKILL.md")
    write(sk, render("project-skill.md.tmpl", vals))
    os.makedirs(os.path.join(docs, "_tools"), exist_ok=True)
    for f in ("build_docs.py", "gen_agent_index.py", "gen_rag_cards.py", "lookup.py", "trace_calls.py"):
        shutil.copy2(os.path.join(SKILL_DIR, "scripts", "runtime", f), os.path.join(docs, "_tools", f))
    code, out = run([sys.executable, os.path.join(docs, "_tools", "gen_agent_index.py")])
    print(out.strip()[:200])
    print(run([sys.executable, os.path.join(docs, "_tools", "gen_rag_cards.py")])[1].strip()[-200:])
    code2, out2 = run([sys.executable, os.path.join(docs, "_tools", "lookup.py"), "index", "--kind", "page", "--list", "--limit", "1"])
    if code2 == 0:  # the topic search reads the cards just written
        code2, out2 = run([sys.executable, os.path.join(docs, "_tools", "lookup.py"), "--search", cfg.get("product") or "index", "--limit", "1"])
    print(f"AGENTS.md, CLAUDE.md block, {sk} written; lookup smoke test: {'ok' if code2 == 0 else 'FAILED'}")
    if code2:
        print(out2[-800:])
    else:
        tick(cfg, "make-agent-skill")


if __name__ == "__main__":
    main()
