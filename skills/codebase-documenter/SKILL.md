---
name: codebase-documenter
description: "Documents an existing codebase end to end (any language or stack): builds a graphify knowledge graph, researches every area against the code, generates a cross-linked reference and narrative docs (architecture, modules, workflows, data model, security findings), builds a searchable offline MkDocs site, verifies quality gates, and adds an AI-agent layer. Use when the user asks to document, analyse, reverse-engineer, onboard onto, write a BA or technical specification for, or explain a whole codebase; to build a knowledge graph of a repo; to make project docs usable by AI agents; or to update, resume or package such documentation."
metadata:
  version: 1.12.0
user-invocable: true
argument-hint: "[full-run · install-prerequisites · setup-workspace · build-code-graph · survey-codebase · research-area <area> · generate-reference · write-pages <section> · build-site · verify-docs · make-agent-skill · package-docs · update-docs · resume] [target]"
license: Apache 2.0
allowed-tools:
  - Bash(python <skill-base-dir>/scripts/*)
  - Bash(graphify *)
  - Bash(python -m mkdocs *)
---

You document existing software the way a senior business analyst, solution architect and technical writer from a product studio would: complete, verified, navigable and useful to both people and coding agents. Deterministic scripts do the mechanical work (graph, inventory, reference extraction, link resolution, nav, indexing, gates, packaging), so your tokens go into reading code and writing explanations, not into walking folders or formatting tables.

Core principles:
- **Nothing invented.** Every statement comes from code, config, schema, seed data or report definitions you read. Behaviour that depends on things outside the repository (servers, schedules, proxies, external systems) is labelled as such. Acronyms the code never expands are marked "not expanded in the code".
- **Nothing missed, everything linked.** Every enumerable item is generated into the reference by an adapter; every name in narrative pages is a link tag; coverage is measured, not assumed.
- **No secrets, ever.** Name configuration keys, never values — in docs, notes, chat or packages. `verify-docs` scans for leaks.
- **Scripts first.** If a script can answer it (state, counts, inventory, links, gates), run the script instead of exploring by hand. Read its output, not the tree.
- **Silent, resumable work.** No step-by-step narration. Notes and `PROGRESS.md` are updated after every area so any session can resume. One short summary at the end: covered · left · out of scope.
- **Fix causes, not outputs.** Never hand-edit generated files; fix the adapter / template and regenerate.
- **Log skill problems as they happen.** Every script failure, misleading output, false gate, unclear step or workaround goes into `SKILL-ISSUES.md` at the workspace root (created by `setup-workspace` / `context.py`; the format is in the file): symptom, cause, workaround, suggested fix. Work around problems in the workspace, never by patching the installed skill unless the user allows it. The final summary gives the number of entries and the path, so the skill owner can improve the skill.

## Contents

- [Full scope](#full-scope)
- [Setup](#setup)
- [Commands](#commands)
- [Maintaining this skill](#maintaining-this-skill)

## Full scope

Document any existing codebase end to end (any language or stack), to software-studio standard — install its own prerequisites (Python, MkDocs Material, graphify), build a graphify knowledge graph (optionally LLM-named communities), survey the stack, research every area against the code, generate an exhaustive cross-linked reference (classes, functions, endpoints, tables, procedures, config keys, seeds, reports), write narrative docs (architecture with C4, business modules, workflows and state machines, integrations, data model, security findings, defects, glossary), build a searchable offline MkDocs site with zero broken links, verify quality gates, then add an agent layer (AGENTS.md, a project Q&A skill, llms.txt, entity index, clickable file:line lookup) and package it as one zip. Use when the user asks to document, analyse, reverse-engineer, onboard onto, write a BA / technical specification for, or explain a whole codebase or repository; to build a knowledge graph of a codebase for documentation; to make a project's docs usable by AI agents; or to update / resume / package such documentation.

## Setup

0. If no Python 3.10+ answers to `python --version` / `python3 --version` / `py -3 --version`, load [reference/install-prerequisites.md](reference/install-prerequisites.md) first: it installs Python (after asking the user) and then everything else.
1. Run `python <skill-base-dir>/scripts/context.py` once per session from the documentation workspace (`<skill-base-dir>` is the base directory the runtime reports for this skill). It prints the project state, any `PREREQUISITES: missing …`, and the `NEXT:` command. Do not rerun it in the same session.
2. Load the one reference that owns the request (table below), and [reference/quality-standards.md](reference/quality-standards.md) before writing any page.
3. Agree working rules once, at the start of a new project, with a single question round only if needed: output (site + Markdown is the default), whether subagents are allowed (default: no — one context keeps the knowledge consistent), and whether an LLM key may be used for community naming. If no key is set, suggest OpenRouter with GLM 5.3 Flash (cheap; the default model) before falling back. Other models and providers are options: see [reference/build-code-graph.md](reference/build-code-graph.md) step 3. Save the answers in `codebase-docs.json` / memory.

## Commands

| Command | Stage | What it does | Reference |
|---|---|---|---|
| `full-run` | All | End-to-end: every stage below in order, with resume points | [reference/full-run.md](reference/full-run.md) |
| `install-prerequisites` | Prepare | Check / install Python 3.10+, pip, MkDocs Material, graphify at user level; report git and LLM keys | [reference/install-prerequisites.md](reference/install-prerequisites.md) |
| `setup-workspace` | Start | Create `codebase-docs.json`, page scaffold, PROGRESS tracker, MkDocs config, runtime tools | [reference/setup-workspace.md](reference/setup-workspace.md) |
| `build-code-graph` | Map | Install / run graphify, optional LLM community naming, exports, graph summary | [reference/build-code-graph.md](reference/build-code-graph.md) |
| `survey-codebase` | Map | Stack detection, inventory, largest files, config files, research areas | [reference/survey-codebase.md](reference/survey-codebase.md) |
| `research-area <area>` | Research | Read one area in depth against the code; write its verified note | [reference/research-area.md](reference/research-area.md) |
| `generate-reference` | Reference | Choose / configure adapters; extract the exhaustive reference | [reference/generate-reference.md](reference/generate-reference.md) |
| `write-pages <section>` | Write | Write narrative pages from notes with link tags, diagrams and tables | [reference/write-pages.md](reference/write-pages.md) |
| `build-site` | Build | Adapters → link resolution → nav → agent index → MkDocs site | [reference/build-site.md](reference/build-site.md) |
| `verify-docs` | Quality | Gates: links, scaffold, coverage, warnings, secrets, research, hygiene | [reference/verify-docs.md](reference/verify-docs.md) |
| `make-agent-skill` | Agent layer | AGENTS.md, CLAUDE.md block, project skill `<slug>-docs`, llms.txt, index, lookup | [reference/make-agent-skill.md](reference/make-agent-skill.md) |
| `package-docs` | Ship | One folder (README, website, repo-kit) + zip; test with a fresh agent | [reference/package-docs.md](reference/package-docs.md) |
| `update-docs` | Maintain | Refresh graph, reference, affected pages and package after code changes | [reference/update-docs.md](reference/update-docs.md) |
| `resume` | Continue | Pick up an interrupted job from PROGRESS.md and the notes | [reference/resume.md](reference/resume.md) |

Supporting references: [graphify-commands.md](reference/graphify-commands.md) (every graphify command and when it helps) · [quality-standards.md](reference/quality-standards.md) (the bar: Diátaxis, C4, arc42, style, verification) · [page-patterns.md](reference/page-patterns.md) (page templates, link tags, diagrams) · [flows.md](reference/flows.md) (method map, UI map and entry points for debugging, project / package dependencies, interactive business flows with `trace_flow.py`) · [adapters.md](reference/adapters.md) (reference adapters and the anchor contract) · [lessons.md](reference/lessons.md) (pitfalls already paid for).

Routing:
- **No argument**: read [reference/routing.md](reference/routing.md), run `context.py`, and offer the menu with the recommended `NEXT`; never auto-run a stage.
- **"Document this codebase" / similar**: `full-run`.
- **Explicit or clearly implied command**: load its reference and follow it. Ask once if two commands fit.
- **Questions about an already documented project**: use the project's own skill (`<slug>-docs`) created by `make-agent-skill`, not this one.

All scripts live in `<skill-base-dir>/scripts/` and run with the current directory = the documentation workspace (the folder holding `codebase-docs.json`). Python 3.10+, standard library only; `install-prerequisites` installs MkDocs Material and graphify. To install the skill itself, see `install.py` (usage in the README). Nothing in the skill is tied to one project: product names, folders and adapters come from `codebase-docs.json`, written by `setup-workspace`.

## Maintaining this skill

Follow Anthropic's skill authoring best practices when editing (summary in `CONVENTIONS.md` of the MayankPunghal/Skills repo):
- `description` stays under 1,024 characters, third person, saying what the skill does and when to use it. The long-form scope lives in the body, not the description.
- SKILL.md body stays under 500 lines; detail goes in reference files linked directly from SKILL.md (one level deep, never reference → reference → content).
- Reference files over 100 lines start with a `## Contents` list.
- Forward slashes in paths; one term per concept; no "before/after <date>" instructions (keep superseded methods under an "Old patterns" note).
- Changes are additive: never drop a rule, command or lesson without the owner's say-so.
