# Quality standards — the bar for every page

The documentation must read like the product docs of a software studio: accurate, complete, navigable, consistent. These standards are the floor, not the goal.

## Frameworks applied

| Standard | How it shows up |
| --- | --- |
| **Diátaxis** (explanation · reference · how-to · tutorial) | Narrative sections *explain* (why / how it works); `reference/` is generated, exhaustive and dry; how-to pages only where a task recurs (e.g. "add a validation rule"); no tutorials unless asked |
| **C4 model** | Architecture pages: L1 system context (users + external systems), L2 containers (deployables, databases, jobs), L3 components of the main application. Mermaid diagrams, labelled with real names |
| **arc42** (selected chapters) | Context & scope, solution strategy, building blocks, runtime view (request lifecycle, workflows), deployment view, cross-cutting concepts (auth, logging, config), risks & technical debt, glossary |
| **Docs-as-code** | Markdown sources in version control, generated reference, build with 0 warnings, link checking, regenerate on change |
| **Microsoft / Google developer style** | Plain language, second person sparingly, active voice, sentence-case headings, consistent terms, no marketing |
| **Risk registers** | Security findings `SEC-nn` (severity Critical/High/Medium/Low, where, what, impact, recommendation); defects `DEF-nn` (priority, area, effect, where); debt `TD-nn` |

## Accuracy rules (non-negotiable)

1. Verified in code: every rule, number, id, status, flag, default, threshold and integration direction.
2. Out-of-repository facts are labelled (schedules, servers, SSO proxies, SQL Agent jobs, external system behaviour).
3. Unknown expansions say "not expanded in the code"; never guess acronyms or intent.
4. Status / code tables come from enums **and** seed data; when they disagree, say so.
5. "Unused", "only", "always", "never" require a caller search first.
6. Security claims name the file and the exploit condition; no exploit recipes beyond what a reviewer needs.
7. No secret values anywhere (config keys by name only).

## Writing rules

- Lead with what the reader needs: purpose → behaviour → rules → data → integrations → permissions → known issues.
- Business language first, technical names linked (tags) next to it.
- Tables for rules, catalogues, statuses, mappings; numbered lists for sequences; Mermaid for flows (sequence, state, flowchart, ER).
- Admonitions (`!!! warning`, `!!! note`, `!!! danger`) for risks and caveats — sparingly.
- One H1 per page; headings are sentence case and unique within the page; no empty sections; no "TBD".
- Short paragraphs (≤ 5 lines); one idea per paragraph.
- Consistent terms: define them in the glossary and use exactly those.
- Every page links onward (related modules, reference entries, findings).

## Completeness rules

- Coverage report: 100 % of the configured kinds discussed (controllers / endpoints, classes, routines, tables) — the code & data map counts, but non-trivial items deserve real narrative.
- Every module page answers: what it is for, who uses it, every screen / endpoint, every rule, statuses, data, integrations, permissions, known issues.
- Every integration page answers: direction, trigger, configuration keys, payload builder, authentication, response handling, logging, failure modes, known issues.
- Every status set has a state machine; every automatic transition names the code that performs it.
- Security: authentication, authorisation algorithm, complete list of anonymous / unauthenticated entry points, findings register.
- Appendices: glossary, defects & debt, coverage, document control (method, regeneration, conventions, agent access, out of scope).

## Professional finish

- Site: Material theme, logo, accent colour, search, offline, tabs, Mermaid, permalinks, 0 warnings.
- Navigation: index pages per section with a "pages in this section" table; breadcrumbs; reference index tables with back-links.
- Consistency pass at the end: terms, capitalisation, number formats, date formats, link labels.
