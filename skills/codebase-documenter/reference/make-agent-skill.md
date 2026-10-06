# make-agent-skill — make the docs usable by coding agents

Humans browse the site; agents need a fast, exact path from a question to the right page and the right source line. This stage creates that layer.

## Steps

1. Make sure the site builds clean (`build-site`), so the index reads final pages.
2. Run `python <skill>/scripts/make_agent_skill.py`. It writes:

| File | For | Content |
| --- | --- | --- |
| `AGENTS.md` | every agent (Codex, Cursor, Copilot, Claude…) | locate docs & source, resources, lookup order, task → page map, rules, update steps |
| `CLAUDE.md` (marked block) | Claude Code | pointer to AGENTS.md, lookup, skill, graphify rules |
| `.claude/skills/<slug>-docs/SKILL.md` | Claude Code skill named after the product | Step 0 locate docs / source (incl. `PINNED_DOCS_ROOT` for global installs), resources, workflow (lookup → page → reference → graph → verify → cite → change table), task map, rules |
| `docs/llms.txt` | any LLM | one line per page with its first sentence (llms.txt convention) |
| `docs/agent/entities.jsonl` | lookup / agents | every anchor (tables, routines, classes, functions, files, communities, controllers, actions, views, enums, seeds, claims, roles, scripts, reports, config keys, endpoints), every page and section, and individual seed rows of `seed_row_tables` |
| `docs/agent/cards.jsonl` | local RAG index | one self-contained card per method, endpoint, UI trigger, entry point, table, routine, error, project, package, flow and narrative section (heading-bounded, ≤ `rag_card_max_chars`, default 2400): context line + everything the exports know about the item, identifier keys for keyword search, doc and source location, related ids for one-hop expansion. Embed this file, not the HTML site |
| `docs/agent/*.json` | tools / viewer | `methods.json` (with `via`: how each run-time-bound call is dispatched), `endpoints.json`, `db.json`, `db-access.json`, `errors.json`, `entry-points.json`, `dependencies.json`, `di.json` (C#: registrations, services with anchors, consumers, messages, pipeline, jobs, events, stored delegates, findings): the raw exports the cards are built from |
| `docs/_tools/lookup.py` | agents and people | `lookup.py <Name> [--kind K] [--list] [--fuzzy] [--find TEXT] [--src PATH]` → `doc: path:line`, `src: path:line` (declaration line, from the entry's own `path:line` when it has one), entry body, then the code: the declaration (brace / GO / End / dedent bounded, `--code-lines` default 40) or each cited source line, for the first 3 matches (`--no-code` turns it off); a `note:` flags a source file newer than the index; an exact name shows only itself unless `--fuzzy`; finding ids (SEC- / DEF- / TD-) and narrative table rows that link a method / class / endpoint are indexed (`finding`, `narrative-row`); `--find` lists matching source lines, or says "source not available: --find skipped" without code; the first match adds its connections (from its card), the related items with their source and the findings that name it (`--no-related`); `--search "<words>"` ranks the retrieval cards by BM25 for a question in plain words, and a name with no match (or several words naming no item) falls back to it |
| `docs/_tools/trace_calls.py` | agents | `trace_calls.py <Class.Method> [--up] [--entry] [--depth N]` → call tree with clickable `path:line` per method; `--up` callers (impact), `--entry` endpoints / UI events / jobs that reach it with one path each and the buttons that call them. Same code as the skill's `trace_flow.py` (which adds `--draft`) |

3. Test like a stranger (this catches what self-review misses):
   - In a clean folder with only the docs (no code), start a **fresh** agent session and ask a real question through the skill. Check: it found the docs root by itself, ran lookup from the workspace root, cited clickable `path:line` links, said answers are unverified without code.
   - With the code present: ask for a change plan. Check the `src:` lines open at the declaration and the plan ends with the *File · What to change · Why* table.
   - Read the agent's process log for gaps (a name it could not find, a page it had to grep) and close them (seed rows, a missing adapter, a missing narrative sentence). Regenerate.

## Why each piece exists (lessons)

- Agents cd into the docs folder and produce broken relative links → "always run lookup from the workspace root".
- `#anchor` links don't open in editors → `path:line` everywhere.
- Single validation messages / statuses were unfindable → seed rows indexed individually.
- Docs unpacked in a different place than expected → Step 0 search order + `PINNED_DOCS_ROOT`.
- Agents assumed code was present → explicit "no source" behaviour.
