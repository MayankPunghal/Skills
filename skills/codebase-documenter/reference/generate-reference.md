# generate-reference — exhaustive, anchored reference pages

Everything enumerable is generated, never hand-typed: that is what makes "nothing missed" true and checkable. Narrative pages then link into these entries with tags.

## Steps

1. Pick adapters from the survey's "Suggested adapters" and set them in `codebase-docs.json`:

   ```json
   "adapters": ["generic-graph", "generic-sql", "generic-config", "generic-areas"]
   ```

   | Adapter | Produces | Needs |
   | --- | --- | --- |
   | `generic-graph` | `components.md` (classes / types, functions: file:line, members, calls into, called by, inherits), `modules.md` (files), `communities.md` | graph built |
   | `generic-sql` | `db-tables.md` (columns, keys, FKs, referenced by) and `db-routines.md` (params, tables touched, SQL callers, application callers) per database | `.sql` DDL / SSDT |
   | `generic-config` | `configuration.md`: every config key name per file + code that reads it (never values) | config files |
   | `generic-areas` | `_src/appendices/code-map.md`: every class / table / routine placed in a business area (narrative, counts for coverage) | run last |
   | `aspnet-mvc-ssdt` | controllers & actions (verbs, routes, anonymous flags), views, components, models, custom JS, enums, SSDT tables / routines with EF aliases, seed data, SSRS reports, config, NuGet | ASP.NET MVC (+ SSDT) |
   | `custom:<path>` | anything else (routes for Express / Django / Spring, OpenAPI endpoints, GraphQL schema, message contracts …) | see [adapters.md](adapters.md) |

   Use `aspnet-mvc-ssdt` *instead of* `generic-graph` + `generic-sql` + `generic-config` for ASP.NET MVC + SSDT solutions (it is richer and writes its own `configuration.md`); keep `generic-areas`. Adapters that write the same page overwrite each other: the later one wins.
2. Configure options (`adapter_options`) only where auto-detection is wrong: database folders / page names, EDMX path, web project, seed folder (the `aspnet-mvc-ssdt` options are all auto-detected; see `scripts/adapters/aspnet-mvc-ssdt/_options.py`), area rules (`generic-areas.rules`: `[{"area": "Orders", "regex": "order|invoice"}]`).
3. Set `coverage` to the kinds that must be 100 % discussed in narrative pages (e.g. controllers, classes, routines, tables) and `seed_row_tables` for status / message tables whose rows agents should find one by one.
4. Run `python <skill>/scripts/build_site.py --no-site`. Fix any adapter `FAIL` at the adapter or its options, then rerun.

## Missing a kind of item?

If the stack has something enumerable that no adapter covers (routes, endpoints, events, feature flags, cron jobs, migrations), write a small custom adapter (≈50–150 lines) following the anchor contract in [adapters.md](adapters.md). Rule of thumb: if you would otherwise list more than ~20 items of a kind by hand, write the adapter.
