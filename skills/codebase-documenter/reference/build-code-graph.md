# build-code-graph — knowledge graph with graphify

The graph is the map of the codebase: files, classes, methods, tables and their `calls`, `references`, `imports`, `inherits`, `implements`, `reads_from` edges, clustered into communities. It makes a large system navigable in minutes and feeds the reference (calls into / called by). It is a **map, not evidence**: confirm every fact in the source; never state an INFERRED edge as fact.

Full command catalogue: [graphify-commands.md](graphify-commands.md).

## Steps

1. **Check**: `python <skill>/scripts/code_graph.py check` — graphify installed? LLM keys available?
   - Not installed: `uv tool install "graphifyy[sql,openai]"` (or `pip install "graphifyy[sql,openai]"`). The `sql` extra parses `.sql`; `openai` enables OpenAI-compatible backends (OpenRouter, vLLM, LM Studio…).
   - Optional, for graph-aware agents in this workspace: `graphify install --platform claude` (skill) and `graphify claude install` (CLAUDE.md section + PreToolUse hook). Other platforms: `graphify <platform> install` (codex, cursor, gemini, copilot, vscode, kiro …).
2. **Build** (AST only, no key, no cost): `python <skill>/scripts/code_graph.py build`
   - Wraps `graphify extract <source_root> --code-only --out .` then `graphify cluster-only . --no-label`.
   - `--semantic` adds LLM extraction of docs / papers / images in the repo (needs a key; costs tokens); `--deep` for aggressive INFERRED edges (research aid only).
   - `--postgres <DSN>` adds a live PostgreSQL schema (tables, views, functions, FKs).
   - Huge graphs (> 5,000 nodes): `--no-viz` skips graph.html at clustering time; `export` still produces the other views.
3. **Name communities** (optional; only with a key): `python <skill>/scripts/code_graph.py label`
   - Uses the first key found (process env, or the Windows user env set with `setx`). OpenRouter is mapped to graphify's OpenAI backend with `OPENAI_BASE_URL=https://openrouter.ai/api/v1`; pick a cheap fast model in `codebase-docs.json` → `graph.model`.
   - **No key yet: suggest one before skipping.** Recommend OpenRouter with **GLM 5.3 Flash** (`z-ai/glm-5.3-flash`), the owner's preferred cheap model for this job. They create a key at openrouter.ai/keys, then run `setx OPENROUTER_API_KEY "<key>"` (Windows) or export it; `install_prerequisites.py` offers to save it. Only if they decline, fall back as below.
   - **Model choice, first match wins:** `--model <id>` → `codebase-docs.json` `graph.model` → the `CODEBASE_DOCS_LLM_MODEL` environment variable (a per-machine preference) → the default for the key (OpenRouter: `z-ai/glm-5.3-flash`; other providers: graphify's default). Any OpenRouter model ID works, e.g. a stronger model for a large estate.
   - **Fallback order:** any other key in `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY` (or a custom OpenAI-compatible endpoint: `graph.base_url` + `graph.api_key_env`) → no key: keep generated names and name the important areas yourself in the notes. `code_graph.py check` shows which key and model will be used.
   - Runs `graphify label . --missing-only --batch-size=2` in rounds until no `Community N` placeholders remain (small batches avoid malformed responses).
   - Review: `code_graph.py labels-review` lists one-word and duplicated names; fix the important ones by hand: `code_graph.py rename <id> "<Meaningful Name>"`.
   - No key: skip. Raw `Community N` labels must never appear in written pages (verify-docs checks); name areas yourself in the notes instead.
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
