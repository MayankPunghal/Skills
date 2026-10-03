# graphify command catalogue (for documentation work)

`graphify --help` is the source of truth for flags; this table says **when each command helps a documentation job**. Set `PYTHONIOENCODING=utf-8` on Windows consoles (the `code_graph.py` wrapper does).

## Build & maintain

| Command | Use it to | Notes |
| --- | --- | --- |
| `graphify extract <path> --code-only` | Build the code graph from AST (free) | `--out DIR` chooses where `graphify-out/` goes; `--force` full re-scan; `--max-workers N` |
| `graphify extract <path> --backend B [--mode deep]` | Also extract docs, papers, images semantically | Needs an LLM key; costs tokens; INFERRED edges = leads, not facts |
| `graphify extract … --postgres DSN` | Add a live PostgreSQL schema | Tables, views, functions, FKs (no column detail) |
| `graphify extract … --cargo` | Rust crate dependencies | |
| `graphify extract … --google-workspace` | Include Google Docs/Sheets/Slides shortcuts | Via `gws` |
| `graphify cluster-only <path> [--no-label] [--no-viz]` | (Re)cluster and regenerate the report | `--no-viz` for > 5,000 nodes |
| `graphify label <path> [--missing-only] [--backend --model --batch-size --max-concurrency]` | Name communities with an LLM | Optional; review names afterwards |
| `graphify update <path> [--force] [--no-cluster]` | Re-extract code after changes (no LLM) | `--force` after refactors that delete code |
| `graphify watch <path>` | Rebuild on file changes while working | |
| `graphify check-update <path>` | Cron-safe: is semantic re-extraction pending? | |
| `graphify hook install / status / uninstall` | Git hooks keep the graph current | post-commit / post-checkout |
| `graphify add <url> [--author --contributor --dir]` | Pull a web page / spec into `./raw` and the graph | Requirements, API docs |
| `graphify clone <github-url>` | Clone a repo to document | Prints the local path |
| `graphify merge-graphs <g1> <g2> --out <path>` | One graph across repositories | Microservices, front + back end |
| `graphify global add/remove/list/path` | Machine-wide multi-repo graph | |
| `graphify merge-driver …` | Git union-merge of graph.json | Set up by hooks |
| `graphify provider list/show/add/remove` | Custom LLM providers | |

## Explore & analyse

| Command | Use it to | Notes |
| --- | --- | --- |
| `graphify query "<question>" [--budget N] [--dfs] [--context C]` | Find the code relevant to a topic, scoped | Default budget 2000 tokens; 400–800 is usually enough |
| `graphify explain "<Name>"` | Plain-language summary of a node and its neighbours | First stop for any class / table |
| `graphify path "<A>" "<B>"` | Shortest relationship between two nodes | Controller → table, API → integration |
| `graphify affected "<Name>" [--depth N] [--relation R]` | Reverse impact: what depends on X | Impact sections, change plans |
| `graphify god-nodes [--top N] [--json]` | Architectural hubs | Base classes, contexts, repositories |
| `graphify diagnose multigraph [--json]` | Check edge-collapse risk | Reported in `01-graph.md` |
| `graphify benchmark [graph.json]` | Token reduction vs reading the corpus | Reported in `01-graph.md` |
| `graphify save-result --question --answer --nodes --outcome [--correction]` | Record a Q&A as graph memory | `useful`, `dead_end`, `corrected` |
| `graphify reflect [--out]` | Turn saved results into `LESSONS.md` | Feed lessons back into research |
| `graphify prs` | PR / CI dashboard with worktree mapping | Maintenance phase |

## Views & exports

| Command | Output | Audience |
| --- | --- | --- |
| `graphify export wiki` | `graphify-out/wiki/` (index + page per class / community) | Agents and humans; navigation |
| `graphify export html [--node-limit N]` | `graph.html` interactive graph | Humans |
| `graphify export callflow-html [--lang en] [--max-sections N]` | `CALLFLOW.html` Mermaid architecture / call flows | Architecture pages (verify before reuse) |
| `graphify tree --root <src> --label <name>` | `GRAPH_TREE.html` collapsible folder tree | Solution-structure page |
| `graphify export obsidian --dir <d>` | Obsidian vault + canvas | Personal exploration |
| `graphify export svg` / `graphml` | Static image / GraphML for Gephi, yEd | Reports |
| `graphify export neo4j|falkordb [--push URI --user U]` | Cypher or push to a graph DB | Password via `NEO4J_PASSWORD` / `FALKORDB_PASSWORD`, never argv |

## Agent integration

`graphify install --platform <p>` copies the graphify skill (claude, codex, cursor, gemini, copilot, …); `graphify <platform> install` writes the always-on rule (e.g. `graphify claude install` → CLAUDE.md section + PreToolUse hook that nudges agents to query the graph before grepping). `graphify uninstall [--purge]` removes them.
