# generate-reference — exhaustive, anchored reference pages

Everything enumerable is generated, never hand-typed: that is what makes "nothing missed" true and checkable. Narrative pages then link into these entries with tags.

## Steps

1. Pick adapters from the survey's "Suggested adapters" and set them in `codebase-docs.json`:

   ```json
   "adapters": ["generic-graph", "generic-deps", "generic-sql", "generic-config", "generic-build", "generic-api",
                "generic-errors", "generic-tests", "generic-dbaccess", "generic-trace", "generic-flows", "generic-areas"]
   ```

   | Adapter | Produces | Needs |
   | --- | --- | --- |
   | `generic-graph` | `components.md` (classes / types, functions: file:line, members, calls into, called by, inherits), `modules.md` (files), `communities.md`, and the method map `methods.md` (every method's declaration, calls, called by) | graph built |
   | `generic-methods` | only the method map: add it next to `aspnet-mvc-ssdt` | graph built |
   | `generic-deps` | `dependencies.md`: project graph, layers, cycles, every project and package with versions (drift flagged) | build manifests |
   | `generic-api` | `endpoints.md`: every HTTP endpoint with verb, route, handler, parameters, declared auth (ASP.NET controllers / minimal APIs / conventional MVC, Express, NestJS, Flask, FastAPI, Django, Spring, Go, OpenAPI files) | routes in code |
   | `generic-errors` | `errors.md`: every exception, validation, HTTP and database error message with the method that raises it | source |
   | `generic-tests` | `test-map.md`: production methods reached by tests through the call graph, the ones nothing reaches, database routines named in tests | method map |
   | `generic-dbaccess` | `db-access.md`: for every table and routine, each method that reads, writes or executes it, the operation, and the technology (ADO.NET, Dapper, EF Core / EF6 LINQ or raw SQL, NHibernate, JPA, JDBC, Node / Python / Go drivers), following SQL held in name constants | `generic-sql`, method map |
   | `generic-trace` | `ui-map.md`: what each button, link, form or script calls (endpoint → handler → database objects reached); `entry-points.md`: every endpoint, UI event handler and background job with the methods, database objects, errors and flows it reaches, plus "method → entry points", "who changes each table", "where users meet each error" | method map; richer with `generic-api`, `generic-dbaccess`, `generic-errors` |
   | `generic-build` | `build-and-run.md`: toolchain, build / test / run commands, launch profiles, Docker and compose, CI pipelines, environments, health checks, background jobs (names only, never values); the evidence for `operations/runbook.md` | build files |
   | `generic-flows` | business-flow pages + interactive viewer from `docs/_src/workflows/flows/*.flow.json` (runs late; see [flows.md](flows.md)) | flow specs (optional) |
   | `generic-sql` | `db-tables.md` (columns, keys, FKs, referenced by) and `db-routines.md` (params, tables touched, SQL callers, application callers) per database | `.sql` DDL / SSDT |
   | `generic-config` | `configuration.md`: every config key name per file + code that reads it (never values) | config files |
   | `generic-areas` | `_src/appendices/code-map.md`: every class / table / routine placed in a business area (narrative, counts for coverage) | run last |
   | `aspnet-mvc-ssdt` | controllers & actions (verbs, routes, anonymous flags), views, components, models, custom JS, enums, SSDT tables / routines with EF aliases, seed data, SSRS reports, config, NuGet | ASP.NET MVC (+ SSDT) |
   | `custom:<path>` | anything else (routes for Express / Django / Spring, OpenAPI endpoints, GraphQL schema, message contracts …) | see [adapters.md](adapters.md) |

   Use `aspnet-mvc-ssdt` *instead of* `generic-graph` + `generic-sql` + `generic-config` for ASP.NET MVC + SSDT solutions (it is richer and writes its own `configuration.md`); keep `generic-areas`, and add `generic-methods`, `generic-deps`, `generic-build`, `generic-errors`, `generic-tests`, `generic-dbaccess`, `generic-trace` and `generic-flows` (its own controller pages make `generic-api` optional). Adapters that write the same page overwrite each other: the later one wins.
2. Configure options (`adapter_options`) only where auto-detection is wrong: database folders / page names, EDMX path, web project, seed folder (the `aspnet-mvc-ssdt` options are all auto-detected; see `scripts/adapters/aspnet-mvc-ssdt/_options.py`), area rules (`generic-areas.rules`: `[{"area": "Orders", "regex": "order|invoice"}]`).
3. Set `coverage` to the kinds that must be 100 % discussed in narrative pages (e.g. controllers, classes, routines, tables) and `seed_row_tables` for status / message tables whose rows agents should find one by one.
4. Run `python <skill>/scripts/build_site.py --no-site`. Besides the pages, the build writes the agent toolkit in `docs/agent/`: JSON exports (`methods.json`, `endpoints.json`, `db.json`, `db-access.json`, `errors.json`, `entry-points.json`, `dependencies.json`), `entities.jsonl` for `lookup.py`, and `cards.jsonl` (one self-contained retrieval card per method, endpoint, UI trigger, table, routine, error, project, package, flow and narrative section) for a local RAG index. Fix any adapter `FAIL` at the adapter or its options, then rerun.

## Missing a kind of item?

If the stack has something enumerable that no adapter covers (routes, endpoints, events, feature flags, cron jobs, migrations), write a small custom adapter (≈50–150 lines) following the anchor contract in [adapters.md](adapters.md). Rule of thumb: if you would otherwise list more than ~20 items of a kind by hand, write the adapter.
