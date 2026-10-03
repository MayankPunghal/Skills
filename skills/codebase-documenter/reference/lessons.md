# Lessons already paid for

From documenting a 5,000-file ASP.NET MVC + SQL Server system (342 + 54 + 65 tables, 844 routines, 232 controllers, 1,865 actions, 66 reports) to 100 % coverage.

## Research

- The graph speeds orientation by an order of magnitude, but INFERRED edges and community names are hypotheses. Every documented fact was re-read in code.
- Integration **direction** is the most common mistake (e.g. a status arriving via an event stream, not an inbound API). Trace who calls whom.
- A custom `[AllowAnonymous]` attribute skipped *both* login and permission checks — always read what security attributes actually do.
- "Unused" needs a caller search; procedures that are no-ops still get called after every edit.
- Status ids differ between enums and seed data (inactive statuses, renamed ones): document both.
- Notes per area + a progress file let the job survive usage limits and context resets without re-reading code.

## Reference generation

- Generate everything enumerable; hand lists drift and miss items.
- Regex blind spots found the hard way: `Controller1` suffixes, `void` actions, API controllers outside `Controllers/`, partial classes, overloads, ORM aliases, pseudo-tables in seed scripts.
- Duplicate anchors and links to missing anchors must be fixed centrally (build step), not per page.
- Resolve names by exact class name first (`Sales_RegionController` ≠ `RegionController`).

## Site and links

- Explicit `<a id>` anchors + an index table at the top + "back to index" made reference pages genuinely navigable.
- A tag resolver (`[[kind:name]]`) means authors never hand-write a reference link and unresolved names fail loudly.
- Zero-warning MkDocs builds are achievable; every warning had a root cause in a generator.
- `use_directory_urls: false` + the offline plugin = the site opens from a zip without a server.

## Agent layer

- Agents need `path:line`, not `#anchor`; and they must run lookup from the workspace root.
- Docs get unpacked in unexpected layouts: search order + pinned docs root.
- Index individual seed rows (messages, statuses) — agents ask about them by id.
- Test with a fresh agent, read its process log, close the gaps it reveals.

## Packaging

- One root folder, one README; everything else inside `repo-kit/` and `website/`.
- Keep single sources and assert copies are identical; hand packaging drifts.
- Never ship the graph cache or machine-specific graphs; ship rebuild instructions.

## Working style

- No progress chatter; one final summary. Ask only real decisions, once.
- Never paste or echo API keys; read them from environment variables (including Windows user env).
- Security findings about real systems are sensitive: package privately, don't auto-publish.
