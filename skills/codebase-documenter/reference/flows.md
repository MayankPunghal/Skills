# Business flows, method map, tracing and dependencies

Generated views that make workflow breakdown and debugging cheap: the **method map** (every method with parameters, callers and callees), **tracing** (what each button calls down to the database, what starts each method), **dependencies** (projects, layers, packages) and **business flows** (one interactive swimlane chart per journey, every step linked to code). All but flows are fully generated; flows are short JSON specs you write from research, and the script draws everything.

## Contents

- [Method map (generic-graph / generic-methods)](#method-map-generic-graph--generic-methods)
- [Tracing: UI map and entry points (generic-trace, generic-dbaccess)](#tracing-ui-map-and-entry-points-generic-trace-generic-dbaccess)
- [Dependencies (generic-deps)](#dependencies-generic-deps)
- [Business flows (generic-flows)](#business-flows-generic-flows)
- [Flow spec format](#flow-spec-format)
- [Token economy](#token-economy)

## Method map (generic-graph / generic-methods)

- `reference/methods.md` (split into `methods-<project>.md` above `adapter_options.generic-graph.methods_split`, default 2000 methods): one row per method with its declaration (parameters and return type read from the source line graphify reports), **Calls** and **Called by** at method level. *Italic* calls are graphify INFERRED edges (resolved by name): verify before stating them as fact.
- `docs/agent/methods.json`: the same data for tools (`calls` / `callers` are anchor ids).
- Tags: `[[mth:OrderService.Submit]]`; `lookup.py Submit --kind method` prints doc and source location.
- With `aspnet-mvc-ssdt`, add `generic-methods` to the adapters (it runs only the method map; `generic-graph` would overwrite the ASP.NET component pages).

## Tracing: UI map and entry points (generic-trace, generic-dbaccess)

The debugging questions ("what does this button call?", "what starts this method?", "who writes this table?", "where does a user see this error?") answered without opening files:

| Page | Answers |
| --- | --- |
| `reference/ui-map.md` | per screen file, each trigger (Razor / Razor Pages links, buttons, forms, `Html.BeginForm` / `ActionLink`, Web Forms server-control events, Blazor `@onclick`, XAML `Click`, WinForms designer events, `onclick` / React / Vue / Angular bindings, `fetch` / axios / `$.ajax` / Angular `http`) → endpoint → handler method → database objects reached, with operation and technology. Conditional targets (`@(isNew ? "Create" : "Edit")`) list each branch; targets built at run time are marked dynamic |
| `reference/entry-points.md` | every entry point (endpoint, UI event handler, background job / message handler that nothing in the code calls) with the methods, database objects, errors and flows it reaches; reverse indexes: method → entry points, UI triggers and flows; who changes each table; where users meet each error; entry points that reach more than one database (`#cross-db`) |
| `reference/db-access.md` | per table and routine, every call site: method, operation (read, insert, update, delete, merge, exec) and technology (ADO.NET, Dapper, EF Core / EF6 LINQ or raw SQL, NHibernate, JPA, JDBC …), following SQL held in name constants |

- `trace_flow.py <Class.Method> --entry` prints every entry point that reaches a method, one call path each, and the buttons / links / scripts that call those endpoints: the fastest answer to "how does a user get here?".
- The same call trees ship with the docs as `docs/_tools/trace_calls.py` (callees, `--up`, `--entry`), so an agent answering questions from the package can trace without the skill.
- `methods.json` gains `entry_points` and `flows` per method; `entry-points.json` holds the entries and UI triggers for tools.
- Tags: `[[ui:...]]` is rarely needed in prose; link a screen's actions from its module page with `[[page:reference/ui-map.md|UI map]]` and name endpoints with `[[ep:POST /orders/ship]]`.
- Static analysis: for C#, `generic-di` adds dependency injection, overrides, message buses, events, stored delegates, jobs and filters to the graph; reflection and URLs built at run time are still not followed (sites listed under "Limits" in the dependency-injection reference). "No entry point found" means "not shown by the code" (dead code, or dispatch the scanner cannot see): check before calling it dead.

## Dependencies (generic-deps)

`reference/dependencies.md` from the build manifests (.NET project files with central package versions, package.json workspaces, pyproject / requirements, pom.xml, Gradle, go.mod, Cargo.toml): project graph, **layers** (layer 0 depends on no other project: build, change or port those first), cycles, every project (`[[prj:Orders.Api]]`) and every package (`[[pkg:Newtonsoft.Json]]`) with versions in use; ⚠ marks version drift. Use it for the Solution structure page ("Projects and folders", "Third-party dependencies") instead of hand-written lists.

## Business flows (generic-flows)

One flow = one business journey a BA would walk through (place an order, approve a refund, nightly settlement). Write one per important journey found during research; not one per method.

1. Find the entry point (controller action, endpoint, job, message handler) in the research note or with `lookup.py`. Start from the screen, not from the action that sounds right: the UI map row or a search of the scripts for the button's URL names the action that runs today. An endpoint whose `endpoints.md` note says *no script, view or form in the repository names this URL* is not what a screen calls (old actions stay in the code after a script switches to a newer one); `build_site.py` prints a `WARNING` when a flow's start step points at such an action.
2. `python <skill>/scripts/trace_flow.py <Class.Method> --depth 4` prints the call tree with parameters and file:line (`--up` for callers). Read only the methods whose role is unclear.
3. `trace_flow.py <Class.Method> --draft <flow-id>` writes `docs/_src/workflows/flows/<flow-id>.flow.json` with one step per method. Then edit it into a business flow:
   - rewrite step texts in business language ("Checks the order is paid", not "LockStatusAsync");
   - merge plumbing steps (connections, mapping, logging) into the business step they serve, or drop them;
   - add the decisions (with branch labels), data steps (tables written) and external steps (other systems) the code shows;
   - fill title, module, summary, trigger and outcome.
4. `build_site.py` writes the flow page (summary, embedded interactive chart, Mermaid flowchart as static fallback, optional sequence diagram, step table with link tags), the flows index and `docs/assets/flows/index.html` (offline viewer: search, swimlanes, click a step for its declaration, calls and callers, ← → walk-through, zoom and pan). A `ref` that resolves to nothing fails the adapter: fix the name, never delete the ref to pass.

Generated `.md` files in the flows folder start with a `generated by flow_pages.py` marker: edit the `.flow.json`, never the page. Link flows from module pages with `[[page:workflows/flows/<flow-id>.md|<title>]]`.

## Flow spec format

```json
{
  "id": "ship-order",
  "title": "Ship an order",
  "module": "Orders",
  "summary": "A back-office user ships a paid order; held stock is consumed in one transaction.",
  "trigger": "User clicks Ship on the order page",
  "outcome": "Order is Shipped and stock deducted",
  "lanes": ["Back-office user", "Web app", "Domain", "Database"],
  "sequence": true,
  "steps": [
    {"id": "s1", "lane": "Back-office user", "kind": "start", "text": "Clicks Ship", "ref": "mth:OrdersController.Ship"},
    {"id": "s2", "lane": "Domain", "text": "Reads the order status", "ref": "mth:OrderWorkflow.LockStatusAsync"},
    {"id": "d1", "lane": "Domain", "kind": "decision", "text": "Is it paid?",
     "next": [{"to": "s3", "label": "yes"}, {"to": "e1", "label": "no"}]},
    {"id": "s3", "lane": "Database", "kind": "data", "text": "Deducts held stock", "ref": ["table:StockLevels", "table:StockReservations"],
     "data": "Three UPDATEs in the caller's transaction"},
    {"id": "e1", "lane": "Web app", "kind": "end", "text": "Shows why it cannot ship"}
  ],
  "notes": ["Ship, Deliver and Cancel share one transaction wrapper."]
}
```

| Field | Meaning |
| --- | --- |
| `steps[].kind` | `step` (default), `decision`, `data`, `external`, `start`, `end` |
| `steps[].next` | omitted = the following step (none after an `end` or the last step); list of ids or `{"to", "label"}` |
| `steps[].ref` | one tag or a list: any link-tag kind (`mth`, `act`, `cls`, `fn`, `ep`, `table`, `proc`, `page` …) |
| `steps[].data` / `note` | short text; may contain `[[tags]]` |
| `lanes` | order of the swimlanes (actors, apps, layers, external systems); steps may add new ones |
| `sequence` | `true` adds a Mermaid sequence diagram (consecutive steps in different lanes become messages) |

## Token economy

- Trace instead of reading: `trace_flow.py` gives the call tree for a few hundred tokens; open files only to confirm a rule or a condition.
- Start a flow from its UI: the UI map row for the button names the endpoint and handler, and `--entry` on a deep method shows every journey that reaches it.
- The spec is the only thing you write per flow (typically 30–60 lines); pages, diagrams and the viewer are generated.
- For method questions use `lookup.py <name> --kind method` (one row, bounded), not `methods.md`.
