# Lessons already paid for

From documenting a 5,000-file ASP.NET MVC + SQL Server system (342 + 54 + 65 tables, 844 routines, 232 controllers, 1,865 actions, 66 reports) to 100 % coverage.

## Research

- The graph speeds orientation by an order of magnitude, but INFERRED edges and community names are hypotheses. Every documented fact was re-read in code.
- Integration **direction** is the most common mistake (e.g. a status arriving via an event stream, not an inbound API). Trace who calls whom.
- A custom `[AllowAnonymous]` attribute skipped *both* login and permission checks — always read what security attributes actually do.
- "Unused" needs a caller search; procedures that are no-ops still get called after every edit.
- Status ids differ between enums and seed data (inactive statuses, renamed ones): document both.
- Notes per area + a progress file let the job survive usage limits and context resets without re-reading code.

## Code graph (graphify on C#)

- SQL is parsed, never pattern-matched (owner's decision: "regex always messes up something or the other"). The regex adapters took a CTE or a word in a comment for a table, cut `[Invoice Summary]` to `Invoice`, counted a table created inside another database's dynamic SQL, and missed SQL in C# strings entirely. `sql_parse.py` runs ScriptDom (the SSDT parser) and keeps only string literals that parse as complete statements, so UI text such as "Select an item" or "Delete a customer" is never taken for SQL.
- Graphify resolves a call through a field to the declaring type's method and joins an interface to its *only* implementer. Everything else was cut until `csharp_resolve.py`: interfaces with 2+ implementations, keyed services, decorators, abstract / virtual overrides, MediatR / bus messages, locals (`foreach` items, `GetRequiredService<T>()` results), events and delegates, delegates stored in objects (`Scenario.Run`) and dispatch tables, method groups (`Select(Format)`, `MapGet("/x", Health)`), Hangfire / Quartz jobs, `RedirectToAction`, filter attributes. On a real 79-file solution the resolver lifted method-to-method calls 369 → 577 and methods reachable from an entry point 113 → 310.
- Graphify stores an **undirected simple** graph: an added A→B merges into an existing B→A (decorator → service → decorator). Re-apply resolved edges after `cluster-only` and before adapters read the graph.
- Minimal-API lambdas live in top-level `Program.cs`, which has no method node: link the endpoint to the first method the lambda calls, or the endpoint reaches nothing.
- Registering concrete classes (`AddScoped<OrderRepository>()`) hides the DI gap; interface-heavy solutions expose it. Test the resolver on both.
- Partial classes: graphify reads one file at a time, so a call on a field declared in the *other* part (`_orders.PlaceAsync()` in `Importer.Placement.cs`, field in `Importer.cs`) gets no edge. The resolver looks fields up across all parts ("partial class field" edges) and lists every partial type with its parts on the DI page; describe a partial class only after reading every part.
- Agents (and people) assume the first implementation they find is the one that runs. Labelling every run-time-bound hop (`[di registration]`, `[override]`, `[message]` …) in the method map, `trace_flow.py` and the RAG cards removes that guess.
- Community names: hub-only names repeat ("Order …" everywhere) and placeholders leak into pages. TF-IDF over member / namespace / folder words plus the class-suffix role gives unique, readable names for free; an LLM given the same profile (plus a clash re-ask) only polishes them.

## Reference generation

- Generate everything enumerable; hand lists drift and miss items.
- Regex blind spots found the hard way: `Controller1` suffixes, `void` actions, API controllers outside `Controllers/`, partial classes, overloads, ORM aliases, pseudo-tables in seed scripts.
- Duplicate anchors and links to missing anchors must be fixed centrally (build step), not per page.
- Resolve names by exact class name first (`Sales_RegionController` ≠ `RegionController`).
- MVC areas come in four registration styles:
  - `Areas/<Name>` folders. MVC 5 controllers there carry no `[Area]` attribute; missing this style drops the area prefix from every route.
  - `AreaRegistration` classes (MVC 5).
  - `[Area]` attributes and `MapAreaControllerRoute` (ASP.NET Core).
  - Plugin projects routed as one area with `MapRoute(…).DataTokens["area"] = <constant>` (SmartStore, nopCommerce).
- `@page` is a directive only when it stands alone on its line: `@pager` in a view is not a Razor Page.

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
