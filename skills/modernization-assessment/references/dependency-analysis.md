# Dependency analysis: what depends on what

Report sections 4.5 to 4.8 (and the **Dependencies** tab of the HTML report) answer four questions from the client's code alone. They come from `scripts/_dependencies.py` and `map_graphs.py` (`analysis.json` → `database`), are rebuilt by `build_report.py`, and carry the assessor's judgment through the `dependencies` narrative.

## Contents

- [The four views](#the-four-views)
- [How workflows are traced](#how-workflows-are-traced)
- [Precision rules and known blind spots](#precision-rules-and-known-blind-spots)
- [What the assessor adds](#what-the-assessor-adds)
- [Using it in the plan](#using-it-in-the-plan)

## The four views

| Section | Answers | Source |
| --- | --- | --- |
| 4.5 Project interdependencies | Which project references which (direct and transitive), who is affected when one changes, the build / port order (layer 0 = references nothing), circular references, references to projects outside the repository | `<ProjectReference>` entries in the inventory |
| 4.6 Workflow dependencies | For every entry point (minimal-API route, MVC / API action, Web Forms page or handler, hosted / background service, console job method, process `Main`): the projects it reaches, database objects it touches, external and on-premises systems it calls, and the findings (F-nnn) on that path | graphify call graph + string literals + scan results |
| 4.7 Database object dependencies | Object to object (a procedure that reads, writes or calls a table, function or procedure; triggers, foreign keys, synonyms, security policies) and object to workflow (which entry points depend on it); objects with no detected dependency | Parsed T-SQL (Microsoft's parser) + the workflow trace |
| 4.8 Shared database objects | Objects used by more than one project (who reads, writes, executes), tables written by several projects (`DB-MULTI-WRITER`), objects no code uses | The code graph's database layer (`sql_graph.py`) |

## How workflows are traced

1. **Entry points** are found by pattern in source (not via the graph): `app.MapGet/Post/...`, public action methods on `*Controller` classes (HTTP verb from `[HttpPost]` etc.), `*.aspx.cs` / `.ashx.cs` / `.asmx.cs`, WCF service operations (public methods of a class implementing a `[ServiceContract]` interface found anywhere in the repository), Blazor routable components (`.razor` with `@page`, plus their `.razor.cs`), Razor Pages handlers (`OnGet` / `OnPost…` on a `PageModel`), classes deriving `BackgroundService` / `IHostedService`, public methods of job-style classes (`*Job`, `*Worker`, `*Batch`, `*Processor`, ...) in executable projects, and `Main`.
2. **Seeds**: graph nodes inside the entry point's line range, plus the targets of call sites inside that range (so lambdas and top-level statements work).
2b. **Unlinked calls**: the graph cannot type calls through injected lambda parameters (`app.MapGet("/x", (Svc q) => q.GetStockAsync())`). A `x.Name(` call in the entry's own lines that has no graph edge is resolved by name when `Name` is at least 8 characters and exactly one method of that name exists in a project the entry can reference.
   An entry point is listed under the application whose own project holds it; only when no application owns that project is it listed under every application that includes it.
3. **Reach**: breadth-first over `calls`, `indirect_call`, `dispatches_to`, `inherits` and `implements` edges, depth 5. For C#, `map_graphs.py` runs the codebase-documenter's `csharp_resolve.py` first, which adds the edges graphify misses (DI registration to implementation, decorators, keyed services, overrides, MediatR / bus handlers, events, method groups, stored delegates, Hangfire / Quartz jobs, redirects, filters, local-variable calls), so a workflow follows the class the container actually injects. Interface to implementation edges are added so DI-style calls resolve. Nodes with more than 40 outgoing edges (service locators, runners) are reached but not expanded. A hop is only followed into projects the entry project can actually reference (itself plus its transitive project references): a name-based hop anywhere else is a collision, not a dependency.
4. **What is read from the reached code**: only the line span of each reached method (from its line to the next node in the file). Database objects come from the SQL statements embedded in those spans, parsed with Microsoft's T-SQL parser (tables read and written, procedures executed), and from procedure / type names passed as a whole string literal; each then adds one level of its own dependencies (the tables a procedure touches). A word in a comment or `ORDER BY` never counts as a table. External systems and findings use the same spans.
5. With no code graph the trace falls back to the entry project's transitive project references and says so in the `basis` field.

## Precision rules and known blind spots

Treat the tables as strong leads to confirm, never as proof. Not visible to the scanner:
- reflection (listed in report section 4.2 "Run-time wiring" and as `DI-REFLECTION` findings, but not followed)
- DI by assembly scanning whose filter the resolver cannot read (it resolves `AssignableTo`, `Name.EndsWith/StartsWith` and `As*` conventions; others are listed as conventions to check), registrations made in another repository or from configuration
- explicit registrations, decorators, keyed services, overrides, MediatR / bus handlers, events, method groups, stored delegates and Hangfire / Quartz jobs **are** followed for C# (resolver edges); they are regular-expression leads, not compiler facts
- the run-time parts of dynamic SQL (concatenations are joined and parsed; a name that only exists at run time is marked dynamic, not guessed); SQL nested inside `sp_executesql` string arguments; EF-generated SQL (entity to table mapping needs reading `DbContext` / `OnModelCreating`)
- stored procedures called through a variable or configuration value
- SQL Agent jobs, Windows scheduled tasks, IIS settings and anything outside the repositories (always an open question)
- calls between repositories (use `map_graphs.py --merge` and `graphify path` on `estate-graph.json`)

An object with no workflow and no object dependent is "unused or reached only through EF / dynamic SQL": check before deleting it from the port scope.

## What the assessor adds

Write `assessment/narrative/dependencies.md` (it must not contain `PENDING:`; `verify_report.py` gate 8 also fails when a section or application is missing):
1. The critical shared projects (largest "change impact") and the port order.
2. The business workflows (order-to-cash, nightly close, reporting, integrations) that cross several projects, database objects or external systems, in business terms, with the riskiest ones named (cite F-nnn and `file:line`).
3. Dependencies the scanner cannot see, each paired with a question for the client.
4. Which workflows must be regression-tested together, and which database objects make them move together (they must change in sync in the dual-database scenario).
5. For an application with no detected entry points, describe its workflows manually and name the application in the narrative.

Verify two or three traces per application with `graphify path "<entry class>" "<repository class>" --graph assessment/graphs/<repo>/graphify-out/graph.json` before relying on them.

## Using it in the plan

- **Port order**: layer 0 first; a project multi-targeted to `netstandard2.0` unblocks both a retained .NET Framework app and the new .NET 10 apps (hybrid path).
- **Test scope**: the "change impact" column and the workflows a changed database object feeds define the regression set after each change.
- **Database migration**: workflows that depend on the same procedures or tables are migrated and cut over together; objects with a CLR, cross-database or Service Broker finding (F-nnn on the path) are the cut-over risks.
- **Estimate**: a shared library with many dependents carries more regression and merge risk than its size suggests: say so in the risks narrative.
