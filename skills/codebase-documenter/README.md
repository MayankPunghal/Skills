# codebase-documenter

A Claude Code skill that documents any existing codebase end to end (any language, any stack, any project), to software-studio standard, and makes the result usable by people **and** coding agents.

It does what a senior business analyst, architect and technical writer would do, with deterministic scripts for everything mechanical:

0. **Prepare**: checks and installs its own prerequisites (Python, MkDocs Material, graphify) at user level.
1. **Map**: builds a graphify knowledge graph of the code, optionally with LLM-named communities, then surveys stacks, folders and the largest files.
2. **Research**: reads every area against the code and writes verified notes. Nothing is invented and no secrets are copied.
3. **Reference**: generates an exhaustive, cross-linked catalogue: classes and functions with callers and callees, a method map (every method's parameters, what it calls and what calls it), project and package dependencies (layers, cycles, version drift), files, communities, tables, procedures, config keys. For ASP.NET MVC and SSDT it also covers controllers and actions, views, seeds and SSRS reports.
4. **Narrative**: writes the narrative pages:
   - architecture (C4);
   - business modules;
   - workflows and state machines, plus interactive business-flow charts (swimlanes; click a step for its code);
   - integrations;
   - data model;
   - security findings register;
   - defects;
   - glossary.
5. **Site**: builds an offline, searchable MkDocs Material site with zero broken links, plus a coverage report.
6. **Quality gates**: unresolved links, unfinished sections, coverage, build warnings, secret leaks, open research, page hygiene.
7. **Agent layer**: `AGENTS.md`, a project Q&A skill (`<product>-docs`), `llms.txt`, an entity index and `lookup.py` (prints clickable `doc:` / `src:` `path:line` locations, with `--find` inside source files).
8. **Package**: one zip with a single README that any agent can follow to install the project skill.

## Install

```bash
python install.py
```

```bash
python install.py --project /path/to/workspace
```

```bash
python install.py --check
```

- The first command installs for all projects, under `~/.claude/skills/codebase-documenter`.
- The second installs for one workspace only.
- The third only checks the prerequisites.

Installing also installs the prerequisites that are missing (`--no-prereqs` skips this):
- MkDocs Material, with pip at user level;
- graphify, with uv (installed first if needed), else pip.

Only Python 3.10+ must already exist. If it doesn't, open Claude Code anyway and say *"document this codebase"*: the skill's `install-prerequisites` step installs Python with the platform package manager (winget, Homebrew, apt), after asking you, and then the rest. `reference/install-prerequisites.md` lists the commands.

Optional: an LLM key in an environment variable (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `GEMINI_API_KEY`), used to name graph communities.

## Use

In Claude Code, opened in the folder where the documentation should live (the repository or an analysis folder next to the code):

- *"Document this codebase"* or `/codebase-documenter full-run`;
- `/codebase-documenter` with no argument shows the state and the recommended next step;
- individual stages: `install-prerequisites`, `setup-workspace`, `build-code-graph`, `survey-codebase`, `research-area <id>`, `generate-reference`, `write-pages <section>`, `build-site`, `verify-docs`, `make-agent-skill`, `package-docs`, `update-docs`, `resume`.

Long jobs survive interruptions. Notes and `docs/_notes/PROGRESS.md` are saved after every step; `/codebase-documenter resume` continues.

## Structure

```
codebase-documenter/
├── SKILL.md                 router: principles, setup, command table
├── README.md, install.py
├── reference/               one playbook per command + supporting guides
│   ├── full-run.md  install-prerequisites.md  setup-workspace.md  build-code-graph.md  survey-codebase.md  research-area.md
│   ├── generate-reference.md  write-pages.md  build-site.md  verify-docs.md  make-agent-skill.md
│   ├── package-docs.md  update-docs.md  resume.md  routing.md
│   └── graphify-commands.md  quality-standards.md  page-patterns.md  adapters.md  lessons.md
├── scripts/                 deterministic tools (stdlib Python)
│   ├── context.py           session state, missing prerequisites, NEXT step (run once per session)
│   ├── install_prerequisites.py  pip, MkDocs Material, graphify (user level); git / LLM key report
│   ├── setup_workspace.py   config, page scaffold, PROGRESS, mkdocs.yml, runtime tools
│   ├── code_graph.py        graphify: check, build, label, labels-review, rename, export, summary, ask, hook, all
│   ├── survey_codebase.py   stacks, languages, folders, largest files, config files, research areas
│   ├── research_notes.py    plan / new / done / status / correct (notes + PROGRESS)
│   ├── build_site.py        adapters → link resolution → nav → agent index → MkDocs
│   ├── verify_docs.py       quality gates (exit code)
│   ├── make_agent_skill.py  AGENTS.md, CLAUDE.md block, <slug>-docs skill, llms.txt, index
│   ├── package_docs.py      README + website + repo-kit, zip, secret scan
│   ├── runtime/             build_docs.py, gen_agent_index.py, lookup.py (travel with the docs)
│   └── adapters/
│       ├── generic/         graph_reference.py, sql_reference.py, config_reference.py, area_map.py
│       └── aspnet-mvc-ssdt/ gen_reference.py, gen_seeds.py, gen_inventory.py, gen_ssrs.py, _options.py
└── templates/               pages.json scaffold, mkdocs.yml, theme, PROGRESS, note, AGENTS, CLAUDE block,
                             project skill, package README, setup guide
```

## Not tied to any project

Nothing in the skill names a product, folder or database. `setup-workspace` writes everything project-specific into the workspace's `codebase-docs.json` (product, source root, adapters, coverage kinds). The generic adapters work on any language graphify parses plus any `.sql` DDL and common config formats. The `aspnet-mvc-ssdt` adapter auto-detects the web project, SSDT databases, EDMX, seed folder and reports. Other stacks add a small custom adapter for their routes or endpoints (`reference/adapters.md`).

## Origin

This skill was extracted from documenting a 5,000-file ASP.NET MVC and SQL Server system to 100 % coverage. That system had 461 tables, 844 routines, 232 controllers, 1,865 actions and 66 reports. `reference/lessons.md` records what that project taught.
