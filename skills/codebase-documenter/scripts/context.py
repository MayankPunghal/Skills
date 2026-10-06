"""Print the documentation project's state and the next command. Run once per session, first.

    python <skill>/scripts/context.py

Deterministic and cheap: reads codebase-docs.json, PROGRESS.md, graph and build artefacts, and prints a compact
status block so the agent does not have to explore the workspace to find out where the job stands.
"""
import glob
import json
import os
import re
import sys

from _common import load_config, utf8_stdout, run


def missing_tools():
    """Required tools that are not installed (empty list = ready)."""
    miss = [] if sys.version_info >= (3, 10) else ["python 3.10+"]
    if run([sys.executable, "-c", "import mkdocs, material"])[0]:
        miss.append("mkdocs-material")
    if run(["graphify", "--help"])[0]:
        miss.append("graphify")
    try:
        import sql_parse
        if not sql_parse.has_sqlglot():
            miss.append("sqlglot")
        if sql_parse.dotnet_major() < sql_parse.MIN_DOTNET:
            miss.append(".NET SDK 8+ (T-SQL parser)")
    except ImportError:
        miss.append("sql_parse.py")
    return miss


def main():
    utf8_stdout()
    root, cfg = load_config(required=False)
    miss = missing_tools()
    if miss:
        print(f"PREREQUISITES: missing {', '.join(miss)}")
    if not root:
        print("STATE: no codebase-docs.json — new documentation project.\nNEXT: " + ("install-prerequisites, then " if miss else "") + "setup-workspace (or full-run)")
        return
    os.chdir(root)
    docs, graph = cfg["docs_dir"], cfg["graph_dir"]
    lines = [f"WORKSPACE: {root}", f"PRODUCT: {cfg['product'] or '?'} ({cfg['code_name'] or '?'}) · stack: {cfg['stack'] or '?'}",
             f"SOURCE ROOT: {cfg['source_root']} ({'ok' if os.path.isdir(cfg['source_root']) else 'MISSING'})",
             f"ADAPTERS: {', '.join(cfg['adapters'])}"]
    has_graphify = "graphify" not in miss
    gj = os.path.join(graph, "graph.json")
    if os.path.exists(gj):
        size = os.path.getsize(gj) / 1e6
        labels = os.path.join(graph, ".graphify_labels.json")
        named = "?"
        if os.path.exists(labels):
            v = list(json.load(open(labels, encoding="utf-8")).values())
            placeholder = re.compile(r"(?i)^community \d+$")
            n_named = sum(1 for x in v if not placeholder.match(str(x)))
            named = f"{n_named}/{len(v)} named"
        lines.append(f"GRAPH: {gj} ({size:.0f} MB, communities {named}); wiki: {'yes' if os.path.isdir(os.path.join(graph, 'wiki')) else 'no'}")
    else:
        lines.append(f"GRAPH: none (graphify {'installed' if has_graphify else 'NOT installed'})")
    notes = sorted(glob.glob(os.path.join(docs, "_notes", "[0-9]*.md")))
    lines.append(f"NOTES: {len(notes)} ({', '.join(os.path.basename(n)[:-3] for n in notes[:12])}{' …' if len(notes) > 12 else ''})")
    prog = os.path.join(docs, "_notes", "PROGRESS.md")
    todo = []
    if os.path.exists(prog):
        t = open(prog, encoding="utf-8").read()
        done, total = len(re.findall(r"- \[x\]", t)), len(re.findall(r"- \[[ x]\]", t))
        todo = re.findall(r"- \[ \] (.+)", t)
        lines.append(f"PROGRESS: {done}/{total} items done" + (f"; next: {todo[0]}" if todo else ""))
    srcs = glob.glob(os.path.join(docs, "_src", "**", "*.md"), recursive=True)
    refs = glob.glob(os.path.join(docs, "reference", "*.md"))
    lines.append(f"PAGES: {len(srcs)} narrative sources · {len(refs)} reference pages")
    cov = os.path.join(docs, "appendices", "coverage.md")
    if os.path.exists(cov):
        lines.append("COVERAGE: " + "; ".join(re.findall(r"(\d+ of \d+) are discussed", open(cov, encoding="utf-8").read())))
    idx = os.path.join(docs, "agent", "entities.jsonl")
    lines.append(f"AGENT INDEX: {'yes' if os.path.exists(idx) else 'no'} · SITE: {'built' if os.path.exists('site/index.html') else 'not built'}")
    print("\n".join(lines))
    # next step heuristic (real state first; optional items never block)
    open_research = re.findall(r"- \[ \] research ([\w-]+)", open(prog, encoding="utf-8").read()) if os.path.exists(prog) else []
    todo_markers = 0
    for p in srcs:
        todo_markers += open(p, encoding="utf-8").read().count("docs:todo")
    if miss:
        nxt = "install-prerequisites"
    elif not os.path.exists(gj):
        nxt = "build-code-graph"
    elif not os.path.exists(os.path.join(docs, "_notes", "00-survey.md")) or not os.path.exists(os.path.join(docs, "_notes", "areas.json")):
        nxt = "survey-codebase"
    elif open_research:
        nxt = f"research-area {open_research[0]}  ({len(open_research)} areas open)"
    elif not refs:
        nxt = "generate-reference"
    elif todo_markers:
        nxt = f"write-pages  ({todo_markers} unfinished sections)"
    elif not os.path.exists(idx):
        nxt = "make-agent-skill"
    elif not os.path.exists("publish"):
        nxt = "verify-docs, then make-agent-skill and package-docs"
    else:
        nxt = "done — update-docs after code changes"
    issues_log(cfg)
    print(f"NEXT: {nxt}")


def issues_log(cfg):
    """The run issues log for the skill owner (SKILL-ISSUES.md at the workspace root): created when missing (workspaces
    made by an older version), counted, and the rule repeated so every session keeps it."""
    p = "SKILL-ISSUES.md"
    if not os.path.exists(p):
        import setup_workspace as SW
        from _common import render
        open(p, "w", encoding="utf-8", newline="\n").write(render("SKILL-ISSUES.md.tmpl", {
            "skill": "codebase-documenter", "version": SW.skill_version(), "product": cfg.get("product") or "this project"}))
    t = re.sub(r"<!--.*?-->", "", open(p, encoding="utf-8").read(), flags=re.S)  # the entry format example is a comment
    n = len(re.findall(r"(?m)^## ISSUE-\d+", t))
    still = len(re.findall(r"(?m)^\| ISSUE-\d+ \|.*\|\s*open\s*\|\s*$", t))
    print(f"SKILL ISSUES: {n} logged ({still} open) in {p}. Log every script failure, misleading output, false gate, unclear "
          "step or workaround there as it happens (symptom, cause, workaround, suggested fix).")


if __name__ == "__main__":
    main()
