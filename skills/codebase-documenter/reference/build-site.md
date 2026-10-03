# build-site — resolve, index and build

`python <skill>/scripts/build_site.py` runs, in order:

1. **Adapters** (`codebase-docs.json` → `adapters`; `generic-areas` last) → `docs/reference/*.md`, `docs/_src/appendices/code-map.md`.
2. **Runtime tools refresh** → `docs/_tools/{build_docs,gen_agent_index,lookup}.py` from the skill.
3. **`build_docs.py`** → de-duplicates anchors, unlinks dead reference links, resolves `[[kind:name]]` tags in `docs/_src/**` into `docs/**`, writes `docs/appendices/coverage.md`, regenerates the `mkdocs.yml` nav between `# >>> nav` / `# <<< nav`, counts `docs:todo` markers. Reports `UNRESOLVED <kind>: n` with each name and page.
4. **`gen_agent_index.py`** → `docs/agent/entities.jsonl` and `docs/llms.txt`.
5. **`python -m mkdocs build`** → `site/` (offline, searchable); prints the warning count and the first warnings.

Flags: `--skip-adapters` (narrative-only changes), `--no-site` (fast loop while writing), `--verbose` (full adapter output).

## Fixing problems

| Symptom | Cause | Fix |
| --- | --- | --- |
| `UNRESOLVED table: X` | Typo, view not table, or object missing from reference | Check the code; use the right kind (`proc` for views / functions); fix the adapter if the object exists |
| `UNRESOLVED cls: X` | File name ≠ class name; ORM subtype | Tag the real class / base entity |
| `UNRESOLVED page: path#anchor` | Page not written yet or wrong anchor | Write the page or fix the link; explicit `<a id>` for important anchors |
| MkDocs "anchor not found" in reference | Adapter links to a missing anchor | Handled by `build_docs.py`; if it persists, fix the adapter's anchor format |
| MkDocs "not in nav" | Page outside the generated nav block | Put it under `docs/_src/` (nav is generated) or exclude it |
| Mermaid not rendering | Fence not ` ```mermaid ` or syntax error | Validate at mermaid.live |

Never hand-edit `docs/*.md` outputs of `_src` or `docs/reference/*`: they are overwritten on the next build.
