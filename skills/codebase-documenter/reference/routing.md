# Routing (no argument given)

1. Run `python <skill-base-dir>/scripts/context.py` (once per session). It prints `STATE`/`NEXT` lines.
2. Show the user a short menu, recommended item first, based on `NEXT`:

| If context says | Offer first |
| --- | --- |
| `PREREQUISITES: missing …` | `install-prerequisites` |
| no `codebase-docs.json` | `full-run` (new project) or `setup-workspace` |
| graph none | `build-code-graph` |
| no survey | `survey-codebase` |
| research areas open | `research-area <next open area>` or `resume` |
| no reference pages | `generate-reference` |
| TODO markers / pages missing | `write-pages <section>` |
| everything written | `verify-docs` → `make-agent-skill` → `package-docs` |
| code changed since the docs | `update-docs` |

3. Never auto-run a stage from the menu. One line per option, no essays.
