# Playbook: Web Forms UI (.aspx, .ascx, .master with code-behind and script)

**Rules:** WEB-FORMS-FILE (residue); LNX-WEB-* (Linux readiness); the assessment's Web Forms findings and its page inventory.
**Engines:** AWS Transform ports Web Forms UI to Blazor Server (a job setting), but not `.svc`, `.ashx`, `.asmx`, service or web references, mixed `.aspx`/`.cshtml`, third-party UI controls or Web Site projects; ViewState and page-script behaviour are undocumented, so every page is tested. DevTx KB 25 (Razor) and 26 (Blazor) guide the model page by page. Claude finishes each page either way.

## Decide the route per application

| Situation | Route |
|---|---|
| A handful of pages, markup a small part of the code (the assessment's token-UI rule) | Rewrite those pages in the target model inside the port; no separate UI project |
| Admin or internal tool that another application already covers | Ask: retire it into that application (a client decision, never assumed) |
| Many pages, heavy coupling, must stay live during the move | Incremental: YARP in the new app proxies unported routes to the old one; pages move one at a time |
| Engine is AWS Transform | Let it produce the Blazor Server pages, then fix page by page below |

**Target per page:** Blazor Static SSR for read-only pages; Blazor Interactive Server for stateful forms (closest to the Web Forms server model); Razor Pages for simple CRUD. One model per application unless there is a reason.

## One page at a time

1. **Inventory the page** with everything it needs: `.aspx` + `.aspx.cs` + `.designer.cs`, its `.ascx` and `.master`, the JS and CSS it loads, the web methods it calls, the session keys it reads and writes. Count the couplings in the table below; that is its difficulty.
2. **Pin its behaviour**: golden request/response pairs (`parity.py record`) and a smoke script for the main path, on the original.
3. **Shared libraries it uses** must already build for `net10.0`/`netstandard2.0` ([systemweb-residue.md](systemweb-residue.md)).
4. **Build the page in the target model**: server controls → components or markup + model; event handlers → component callbacks (Blazor) or page handlers (Razor Pages); ViewState → component fields or a scoped service (hidden fields only where needed); `Session` → a scoped service or `ISession`.
5. **Fix the script**: replace selectors bound to generated IDs with stable `id` / `data-*` attributes or JS interop; remove UpdatePanel/ScriptManager; turn page methods into endpoints; recheck client validation messages.
6. **Route it**: in the incremental route YARP sends the path to the new page; keep the old route for rollback.
7. **Replay** the goldens against both; only documented differences allowed. Then retire the old route.

| Coupling | Find it with | Becomes |
|---|---|---|
| Server and data-bound controls | `runat="server"`, `<asp:` | Components, tag helpers, a model |
| Postback events | `IsPostBack`, `_Click`, `AutoPostBack` | Callbacks / handlers |
| ViewState | `ViewState[`, `EnableViewState` | Fields, scoped state |
| UpdatePanel, ScriptManager | `UpdatePanel`, `$get(` | Blazor rendering; fetch + partials |
| Script on server IDs | `__doPostBack`, `ClientID`, `<%= x.ClientID %>`, `ctl00_` | Stable IDs, JS interop |
| Page methods | `PageMethods`, `[WebMethod]` on a page | Minimal API / controller |
| Server-emitted script | `RegisterStartupScript`, validators, menus | Explicit scripts, components |
| Posted names | `Request.Form["ctl00$...`, `FindControl(` | Model binding |
| Data source controls | `SqlDataSource`, `ObjectDataSource` | A service call; SQL through the data-access seam ([raw-sql-and-data-access.md](raw-sql-and-data-access.md)) |

## Across old and new during an incremental move

Auth cookies and machineKey: shared data protection keys, or one re-login ([auth.md](auth.md)). Session: remote-app session (System.Web adapters) while the old app still reads it. Static files and bundles: served by the new app once its first page moves.

## Gotchas

- Third-party control suites (Telerik, DevExpress, AjaxControlToolkit) have no automatic port: the vendor's Blazor suite (licence) or plain components.
- `Page_Load` ordering and `Page.IsValid` side effects are easy to lose; the goldens catch the output, the smoke script catches the flow.
- Framework session locks per request; double submits behave differently.

## Done when

No `.aspx`/`.ascx`/`.master` left in the ported project (or waived as out of scope with the decision named); every page replays against its goldens; the smoke script passes on Linux in the container.
