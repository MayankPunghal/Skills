# update-docs — keep documentation current after code changes

1. `python <skill>/scripts/context.py` — confirm workspace and source root.
2. Refresh the graph: `graphify update <source_root>` (AST only, free; `--force` after large deletions), then `python <skill>/scripts/code_graph.py resolve` (graphify update rewrites graph.json without the resolved C# calls; `build_site.py` also re-applies them when `generic-di` is configured), `python <skill>/scripts/community_names.py` (fresh heuristic names; LLM / hand names whose hubs are unchanged are kept) and `code_graph.py summary`. Optional: `code_graph.py label --only-missing` to LLM-name only new communities (key needed).
3. Find what changed: `git diff --stat <last-docs-commit>..HEAD` (or compare file dates); for each changed area run `graphify affected "<changed class>" --depth 2` to see which pages' subjects are touched.
4. Regenerate the reference: `python <skill>/scripts/build_site.py --no-site`. New `UNRESOLVED` names = renamed / deleted items referenced by narrative pages → fix the pages.
5. Re-verify and update the affected notes and narrative pages (same rules as research: read the code). Log corrections.
6. `python <skill>/scripts/verify_docs.py` → all PASS.
7. `python <skill>/scripts/make_agent_skill.py` (refreshes index, llms.txt, runtime tools) and `package_docs.py` if a new package is needed.
8. Update `document-control.md` (date, scope of the update).

Automate the cheap part: `code_graph.py hook` installs git hooks that keep the graph current on every commit.
