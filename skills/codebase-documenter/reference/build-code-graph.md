# build-code-graph — knowledge graph with graphify

The graph is the map of the codebase: files, classes, methods, tables and their `calls`, `references`, `imports`, `inherits`, `implements`, `reads_from` edges, clustered into communities. It makes a large system navigable in minutes and feeds the reference (calls into / called by). It is a **map, not evidence**: confirm every fact in the source; never state an INFERRED edge as fact.

Full command catalogue: [graphify-commands.md](graphify-commands.md).

## Steps

1. **Check**: `python <skill>/scripts/code_graph.py check` — graphify installed? LLM keys available?
   - Not installed: `uv tool install "graphifyy[sql,openai]"` (or `pip install "graphifyy[sql,openai]"`). The `sql` extra parses `.sql`; `openai` enables OpenAI-compatible backends (OpenRouter, vLLM, LM Studio…).
   - Optional, for graph-aware agents in this workspace: `graphify install --platform claude` (skill) and `graphify claude install` (CLAUDE.md section + PreToolUse hook). Other platforms: `graphify <platform> install` (codex, cursor, gemini, copilot, vscode, kiro …).
2. **Build** (AST only, no key, no cost): `python <skill>/scripts/code_graph.py build`
   - Wraps `graphify extract <source_root> --code-only --out .` → `csharp_resolve.py` → `graphify cluster-only . --no-label` → `csharp_resolve.py` again (graphify keeps an undirected simple graph, so clustering merges A→B into an existing B→A) → `community_names.py` (heuristic names, free). `sql_graph.py` runs beside each resolver pass.
   - **Vendored libraries excluded**: `code_graph.py build` passes `--exclude` patterns from `scripts/vendor_files.py` (vendor folders, files named after a declared client-side package such as `jquery-3.4.1.js`, IntelliSense copies, files with a library / NuGet licence banner) so copied-in jQuery, Bootstrap or WebForms scripts do not bury the project's own communities and hubs. `python scripts/vendor_files.py <source root>` lists what is excluded.
   - **Database layer** (`scripts/sql_graph.py`, also `code_graph.py resolve`): graphify extracts nothing from `.sql` files and does not read SQL inside strings. This adds, with `_origin: "sql-parse"`, a node per table / view / procedure / function / trigger / type / sequence / synonym (Microsoft's T-SQL parser), and edges routine → table `reads_from` / `writes_to` (operation in metadata), routine → routine / function `calls`, trigger → table, foreign keys, and C# method → table / procedure from the SQL embedded in that method (`embedded SQL`) or the procedure name it passes (`name in code`). Writes `sql-graph.json` (counts, unresolved names). `graphify affected "<table>"` then reaches the code.
   - **C# call resolver** (`scripts/csharp_resolve.py`, also `code_graph.py resolve`): adds, with `_origin: "csharp-resolve"` and INFERRED / AMBIGUOUS confidence, the calls graphify's syntax pass cannot see — DI registrations (MS DI incl. keyed, open generics, factories, decorators, Scrutor scans; Autofac, Unity, Ninject, Simple Injector, StructureMap / Lamar, Windsor), interfaces with several implementers, abstract / virtual overrides, keyed injection, MediatR / MassTransit / NServiceBus / Rebus / Brighter / Wolverine-style messages, calls on typed locals (`foreach` items, `GetRequiredService<T>()`, `new T()`, casts), events and delegates, delegates stored in objects and dispatch tables, method groups, Hangfire / Quartz jobs, `RedirectToAction`, filter attributes. It also writes `graphify-out/csharp-resolve.json` (registrations per host, consumers, messages, pipeline, options, findings) for the `generic-di` adapter. No build needed; works on .NET Framework and .NET. Idempotent.
   - `--semantic` adds LLM extraction of docs / papers / images in the repo (needs a key; costs tokens); `--deep` for aggressive INFERRED edges (research aid only).
   - `--postgres <DSN>` adds a live PostgreSQL schema (tables, views, functions, FKs).
   - Huge graphs (> 5,000 nodes): `--no-viz` skips graph.html at clustering time; `export` still produces the other views.
3. **Name communities.** `build` already gave every community a unique heuristic name and a one-line summary (`community_names.py`: TF-IDF over hub / class / method / file / namespace / folder words + the role read from class suffixes, clashes broken by project and next distinguishing word; no LLM, no cost). They are written to `.graphify_labels.json` (graphify exports, reference pages) and `community-summaries.json` (graph summary, communities page, RAG cards). Upgrade them with an LLM when a key exists (optional): `python <skill>/scripts/code_graph.py label` (`--engine heuristic` to stay free, `--only-missing` after an update)
   - What the LLM receives per community, in independent batches of 25 (no conversation history): size, hub members with their kind, top namespaces and folders, role, the heuristic name as a hint — and the other communities of the batch, so names differ. It returns a 2-5 word name and a one-sentence summary. A last request re-asks only for names that still clash, side by side. ~10k tokens for 100 communities.
   - Uses the first key found (process env, or the Windows user env set with `setx`). OpenRouter is mapped to graphify's OpenAI backend with `OPENAI_BASE_URL=https://openrouter.ai/api/v1`; pick a cheap fast model in `codebase-docs.json` → `graph.model`.
   - **No key yet: suggest one before skipping.** Recommend OpenRouter with **GLM 5.3 Flash** (`z-ai/glm-5.3-flash`), the owner's preferred cheap model for this job. They create a key at openrouter.ai/keys, then run `setx OPENROUTER_API_KEY "<key>"` (Windows) or export it; `install_prerequisites.py` offers to save it. Only if they decline, fall back as below.
   - **Model choice, first match wins:** `--model <id>` → `codebase-docs.json` `graph.model` → the `CODEBASE_DOCS_LLM_MODEL` environment variable (a per-machine preference) → the default for the key (OpenRouter: `z-ai/glm-5.3-flash`; other providers: graphify's default). Any OpenRouter model ID works, e.g. a stronger model for a large estate.
   - **Fallback order:** any other key in `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY` (or a custom OpenAI-compatible endpoint: `graph.base_url` + `graph.api_key_env`) → no key: keep generated names and name the important areas yourself in the notes. `code_graph.py check` shows which key and model will be used.
   - `--engine graphify` keeps the old path: `graphify label . --missing-only --batch-size=2` in rounds (12 bare member names per community, no folders).
   - Review: `code_graph.py labels-review` lists one-word and duplicated names; fix the important ones by hand: `code_graph.py rename <id> "<Meaningful Name>"` (kept across regenerations).
   - Raw `Community N` labels must never appear in written pages (verify-docs checks); heuristic names prevent them, but name business areas yourself in the notes.
4. **Export**: `python <skill>/scripts/code_graph.py export` → wiki (`graphify-out/wiki/`, one page per class / community, agent-readable), `graph.html`, `CALLFLOW.html` (Mermaid call-flow), `GRAPH_TREE.html` (folder tree). Optional `--obsidian`, `--graphml`, `--svg`. For graph databases: `graphify export neo4j|falkordb` (password via env var, never argv).
5. **Summarise**: `python <skill>/scripts/code_graph.py summary` → `docs/_notes/01-graph.md` (size, relations, confidence, god nodes, largest communities with folders, `graphify benchmark` token-reduction figures, multigraph diagnosis) and `graph-communities.json` (feeds the survey's research areas).
6. **Keep current** (when the repo is a git checkout): `code_graph.py hook` installs post-commit / post-checkout hooks (`graphify hook install`); otherwise `graphify update .` after code changes (AST only, free), `graphify watch <path>` while developing.

One-shot: `code_graph.py all [--label]` = build → label → export → summary.

## Using the graph during research (token economy)

| Need | Command | Instead of |
| --- | --- | --- |
| Where does a topic live? | `code_graph.py ask "<topic>" --budget 800` (`graphify query`) | grepping the tree |
| What is this class / table? | `graphify explain "<Name>"` | opening many files |
| How does A reach B? | `graphify path "<A>" "<B>"` | tracing calls by hand |
| What breaks if X changes? | `graphify affected "<X>" --depth 2 [--relation calls]` | guessing impact |
| Architectural hubs | `graphify god-nodes --top 20` | reading everything |
| Learn from past answers | `graphify save-result --question … --answer … --nodes … --outcome useful|dead_end|corrected`, then `graphify reflect` → `graphify-out/reflections/LESSONS.md` | repeating dead ends |
| Bring an external spec into the graph | `graphify add <url>` (saved to `./raw`, graph updated) | pasting documents |
| Several repositories | `graphify merge-graphs g1.json g2.json --out merged.json` or `graphify global add …` | separate silos |

Always read the source file that the graph points to before writing anything down.
