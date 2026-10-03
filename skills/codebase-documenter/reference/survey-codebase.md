# survey-codebase — inventory and research plan

## Steps

1. `python <skill>/scripts/survey_codebase.py` → `docs/_notes/00-survey.md`: stacks detected (with evidence files), files and code lines by type, folders, the 30 largest code files, configuration files, suggested adapters. Creates `docs/_notes/areas.json` (candidate research areas from code volume, enriched with graph communities).
2. Read `00-survey.md` and `01-graph.md` together (≈2 minutes). Then **edit `areas.json`** so each area is one coherent business or technical topic:
   - merge folders that form one feature (UI + service + data for "Orders");
   - split giant areas (a 100k-line web project = several business modules);
   - add cross-cutting areas the folder view misses: `00-foundation` (startup, routing, auth, base classes), `11-<core engine>` (pricing, rules), `60-misc`, `70-shared-libs`, `71-db-logic` (procedures, triggers, validation), `80-other-projects` (APIs, schedulers, ETL, reports, tests);
   - give stable ids (`10-orders`, `20-billing` …) and business titles.
3. `python <skill>/scripts/research_notes.py plan` → one note file per area from the note template, one line per area in PROGRESS.md.
4. Write the **foundation** note first (`research-area 00-foundation`): it settles vocabulary, architecture and conventions that every later note reuses.

## What good areas look like

| Good | Bad |
| --- | --- |
| "Orders — creation, pricing, approvals" | "Areas/Order/Controllers" |
| One note ≈ 50–250 lines of verified facts | One note per file, or one note for everything |
| Covers UI → service → data → integration for one topic | Splits a flow across five notes without cross-links |

Record the survey's surprises (unused projects, two project files for one app, generated code, test shells) in `00-foundation` — they become operations and technical-debt content.
