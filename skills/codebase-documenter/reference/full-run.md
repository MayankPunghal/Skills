# full-run — document a codebase end to end

The whole job, in order. Each stage has its own reference; this page is the spine and the resume map. Expect it to span several sessions on a large system: everything is saved as you go.

## 0. Agree the brief (one question round, only what you cannot default)

| Decision | Default |
| --- | --- |
| Output | MkDocs site + Markdown + agent layer + zip package |
| Subagents | **No** — one reader keeps facts consistent across pages |
| LLM key for community naming / semantic extraction | Use one if an env var is present (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`…); never ask the user to paste a key |
| Language / spelling | Match the user (en-GB or en-US), consistently |
| Progress chatter | None; one final summary |

Save non-default answers to `codebase-docs.json` and memory.

## 1. Stages

| # | Stage | Command | Done when |
| ---: | --- | --- | --- |
| 0 | Prerequisites | `install-prerequisites` | `install_prerequisites.py --check` prints `READY` (Python 3.10+, pip, MkDocs Material, graphify) |
| 1 | Workspace | `setup-workspace` | `codebase-docs.json`, scaffold, PROGRESS, mkdocs.yml exist |
| 2 | Graph | `build-code-graph` | graph built, communities named (if key) and reviewed, exports, `01-graph.md` |
| 3 | Survey | `survey-codebase` | `00-survey.md`, `areas.json` reviewed and edited, `research_notes.py plan` run |
| 4 | Research | `research-area <id>` for every area | every area ticked in PROGRESS, notes verified |
| 5 | Reference | `generate-reference` | adapters configured; `build_site.py` runs clean |
| 6 | Narrative | `write-pages <section>` for every section (C#: `architecture/dependency-injection.md` from the generic-di reference; module pages say what runs behind each interface, message and event); one business-flow spec per important journey (`trace_flow.py <Class.Method> --draft <id>`, [flows.md](flows.md)), which becomes an interactive flow chart | 0 TODO markers, 0 unresolved tags; verify-docs notes a site with no flows |
| 7 | Site | `build-site` | 0 MkDocs warnings |
| 8 | Quality | `verify-docs` | all gates PASS |
| 9 | Agent layer | `make-agent-skill` | AGENTS.md, project skill, llms.txt, index; lookup smoke test ok |
| 10 | Package | `package-docs` | zip built; fresh-agent setup test passed |

Order matters: research before writing (pages are written from notes, not from memory); reference before narrative (tags need anchors to resolve); agent layer after the site (the index reads the final pages).

## 2. Rhythm per session

1. `context.py` → read `NEXT`.
2. Do one stage (or one research area / one section) completely.
3. Update notes / PROGRESS (`research_notes.py done <id>`, `research_notes.py correct "…"` for any fact you had to fix).
4. Continue with the next item. If the usage limit approaches: finish the item in hand, save, stop.

## 3. Final summary to the user (short)

- Covered: counts (pages, reference entries, coverage per kind, gates).
- Where: site path, zip path, how to install the skill.
- Sensitive: which pages.
- Left / out of scope: things outside the repository, runtime verification, any gaps.
- Skill issues: the number of entries in `SKILL-ISSUES.md` (workspace root) and its path, for the skill owner. It is not part of the package.
