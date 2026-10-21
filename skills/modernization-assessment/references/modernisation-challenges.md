# Modernisation challenges and how each is handled

What to flag in the assessment and price in the plan; the dotnet-modernization skill's playbooks carry the steps.
Sources are linked per section; items marked *(practice)* are engineering practice, not from a cited page.

## Contents
- Tightly coupled Web Forms (markup, code-behind and JavaScript together)
- System.Web.HttpContext across shared libraries and dependent applications
- Libraries first
- WCF and ASMX: services, clients, wire compatibility
- WPF and WinForms
- MongoDB and Amazon DocumentDB
- Other .NET Framework features with no direct counterpart
- What the porting engines cover

## Tightly coupled Web Forms (markup, code-behind and JavaScript together)

Web Forms has no ASP.NET Core counterpart, so every route off it rewrites the UI layer
([AWS Transform UI porting](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html)). The hard
part is a page whose behaviour is split across `.aspx` markup, `.aspx.cs` code-behind and client script that talks to
server-generated IDs. Inventory each page (with its `.ascx`, `.master`, code-behind, JS and CSS) before choosing a target:

| Coupling | Find it with | Why it bites | Target |
|---|---|---|---|
| Server controls, data-bound controls | `runat="server"`, `<asp:` | each becomes a component or markup + model | Blazor components, Razor tag helpers |
| Event model | `IsPostBack`, `_Click`, `_SelectedIndexChanged`, `AutoPostBack` | postback events disappear | component callbacks (Blazor) or handlers/endpoints (Razor Pages) |
| ViewState | `ViewState[`, `EnableViewState` | no equivalent; protected by machineKey | component fields, scoped services, hidden fields only where needed |
| UpdatePanel / ScriptManager | `UpdatePanel`, `ScriptManager`, `$get(` | partial postbacks driven by script | Blazor rendering; fetch + partials in Razor Pages |
| Script bound to server IDs | `__doPostBack`, `ClientID`, `getElementById('<%=`, `ctl00_` / `ctl00$` | generated IDs change, selectors silently break | stable `id` / `data-*` attributes, JS interop |
| Page methods / AJAX | `PageMethods`, `[WebMethod]` on a page, `[ScriptMethod]` | static methods called from JS | minimal API / controller endpoints |
| Server-emitted script | `RegisterStartupScript`, `RegisterClientScriptBlock`, validators, menus | behaviour lost silently | explicit scripts or components |
| Posted field names | `Request.Form["ctl00$...`, `FindControl(` | names change | model binding with named fields |
| Session and auth | `Session[`, `FormsAuthentication`, `<machineKey` | state and cookies across old and new apps | see below |

**Target per page:** Blazor Static SSR for read-only pages; Blazor Interactive Server for stateful forms (closest to the
Web Forms server model; AWS Transform targets it); Razor Pages for simple CRUD
([render modes](https://learn.microsoft.com/en-us/aspnet/core/blazor/components/render-modes)). BlazorWebFormsComponents
keeps control names for control-heavy pages but converts nothing by itself
([repo](https://github.com/FritzAndFriends/BlazorWebFormsComponents)).

**Method, one page at a time:**
1. pick a low-coupling, high-value page; inventory it with the table above;
2. record a golden master: load, postback, validation errors, empty data, paging and sorting, redirects, database writes;
3. make sure the shared libraries it uses are adapter-enabled or multi-targeted (next section);
4. build the page in the target model: markup to components, handlers to methods, ViewState to fields, Session to a
   scoped service (or remote-app session while the old app still reads it);
5. replace script bound to server IDs with stable IDs or JS interop; remove UpdatePanel; recheck validation messages;
6. route it through YARP in the new app, keep the old route for rollback;
7. replay the golden master against both; only documented differences allowed; then retire the old route.

**Incremental, not big-bang**, for large or heavily coupled apps: YARP front door, remote-app or wrapped session, shared
data protection for auth cookies and machineKey
([incremental migration](https://devblogs.microsoft.com/dotnet/incremental-asp-net-to-asp-net-core-migration/),
[session](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/areas/session),
[machineKey](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/areas/machine-key)). Framework session
locks per session and ASP.NET Core session does not: test double submits.

**Estimate impact:** price pages by coupling, not only by count. A page with `__doPostBack`/`ClientID` script, UpdatePanels
or data source controls costs more than a form; flag those pages in the plan.

## System.Web.HttpContext across shared libraries and dependent applications

Converting `System.Web.HttpContext` to `Microsoft.AspNetCore.Http.HttpContext` use by use, in every library and every
application that calls it, is the expensive way. Options, in order of preference for a shared library:

1. **Pass what is needed**: the library takes the values (user id, tenant, headers) as arguments or through a small
   interface (`ICurrentRequest`) implemented once per host *(practice)*.
2. **System.Web adapters** (`Microsoft.AspNetCore.SystemWebAdapters`): one `System.Web.HttpContext` type that works on
   .NET Framework and ASP.NET Core, so library code compiles unchanged; a library whose only System.Web dependency is
   HttpContext can then target `netstandard2.0`. The legacy app uses `...FrameworkServices`, the new app
   `...CoreServices`. It is a bridge: plan its removal
   ([adapters](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/inc/systemweb-adapters)).
3. **`IHttpContextAccessor`** in libraries used only by ASP.NET Core apps.

`HttpContext.Current` used as a per-request bag (`Items`) or ambient context: see the ambient-context finding (CallContext
→ `AsyncLocal<T>`). Count uses per library and per consuming application; the estimate prices the library once.

## Libraries first

Port class libraries before the applications that use them, leaves of the dependency graph first, simplest first
(Microsoft: libraries upgraded in post-order depth-first order,
[fx-to-core](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/)). While .NET Framework callers remain,
target `netstandard2.0` or multi-target `net48;net10.0`. The execution plan orders work packages this way.

## WCF and ASMX: services, clients, wire compatibility

- **WCF services** → CoreWCF on ASP.NET Core (BasicHttp, NetTcp, WebHttp and others; NetNamedPipe is Windows-only;
  WS-* security and transactions must be tested) ([CoreWCF](https://github.com/CoreWCF/CoreWCF)). WIF is not supported.
- **WCF clients** → `dotnet-svcutil` and the System.ServiceModel.* client packages
  ([svcutil](https://learn.microsoft.com/en-us/dotnet/core/additional-tools/dotnet-svcutil-guide)); generated methods are async.
- **ASMX services** do not run on modern .NET: SoapCore or CoreWCF with the same WSDL and path for external callers;
  REST for internal callers; or keep the `.asmx` on a Windows host until callers move *(practice)*.
- **ASMX "Web References" clients** (`SoapHttpClientProtocol`): regenerate with dotnet-svcutil, or call the service's REST
  API if it has one; call sites change shape.
- **Wire compatibility** for callers that cannot change: same endpoint path, SOAP version and WSDL (diff before and
  after), namespaces and action names, serialiser (XmlSerializer vs DataContractSerializer differ in element order and
  nulls), faults, binding, message size and time-outs. Contract snapshot tests and dual-running endpoints with caller
  logging before switching *(practice)*.

## WPF and WinForms

Windows-only on every .NET version ([WPF](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/overview/)). Options:
keep on Windows and port to .NET 10 (least change); stream to a browser with Amazon WorkSpaces Applications (formerly
AppStream 2.0) with no code change; rewrite to a web UI (Blazor) reusing view models; Avalonia for a Linux desktop
*(practice)*. Challenges: Windows APIs (registry, printing, COM), third-party control licences, designer tooling, DPI,
deployment (ClickOnce / MSI), AppDomains (gone on .NET).

## MongoDB and Amazon DocumentDB

The target change is small; the driver change is not always:

- **DocumentDB itself is mostly configuration**: connection string, TLS with the `global-bundle.pem` CA file (on Linux a
  file path, not the Windows store), `retryWrites=false` below engine 8.0.2. Breaks only if the code uses `$where`,
  `getLastError`, capped collections, hashed/wildcard indexes, reverse `$natural` or relies on natural order
  ([functional differences](https://docs.aws.amazon.com/documentdb/latest/developerguide/functional-differences.html)).
- **The legacy 1.x API** (`MongoServer`, `MongoCollection<T>`, `SafeMode`) was carried by the `mongocsharpdriver`
  package in 2.x and removed in 3.0: move through 2.30 to `IMongoClient` / `IMongoCollection<T>`
  ([v3 upgrade](https://www.mongodb.com/docs/drivers/csharp/current/reference/upgrade/v3/)). Watch the GUID
  representation (data written in the legacy format reads back wrong), Decimal128 / DateTimeOffset serialisation, and
  write concern: legacy code often used unacknowledged writes, the modern default is acknowledged.
- **Size**: a wrapper with a handful of call sites and no custom serialisers is hours, not days; check GUID fields and
  write concern first. A disabled feature is a removal.

## Other .NET Framework features with no direct counterpart

| Feature | Replacement | Source |
|---|---|---|
| AppDomains | separate processes / containers; `AssemblyLoadContext` for plug-ins | [unavailable technologies](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable) |
| .NET Remoting | HTTP / gRPC across processes; pipes in-process; StreamJsonRpc | same |
| Code Access Security | OS boundaries (containers, least privilege) | same |
| EnterpriseServices (COM+) | redesign (queue, service) | same |
| Windows Workflow Foundation | CoreWF or a state-machine library | same |
| XSLT `msxsl:script` | extension objects | same |
| BinaryFormatter (removed in .NET 9) | System.Text.Json / MessagePack | [BinaryFormatter](https://learn.microsoft.com/en-us/dotnet/standard/serialization/binaryformatter-migration-guide/) |
| EF6 / EDMX | EF6.4+ runs on .NET; EF Core where data access is still changing | [EF6 vs EF Core](https://learn.microsoft.com/en-us/ef/efcore-and-ef6/) |
| Crystal Reports, ReportViewer (RDLC) | no official port: replace the reporting engine or host separately (decision) | *(practice)* |
| Forms auth / machineKey / ViewState | shared data protection, or re-login once | [machineKey](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/areas/machine-key) |
| Global.asax, HttpModules, handlers | Program.cs, middleware, endpoints | [fx-to-core](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/) |
| Windows integrated auth | Kerberos keytab on Linux, or OIDC / SAML through an identity provider | *(practice)* |

## What the porting engines cover

One engine per project (the execution plan chooses it):

- **AWS Transform for .NET**: class libraries, console, MVC, Web API, Web Forms (UI to Blazor Server), WCF, ASMX projects,
  WinForms/WPF, tests; targets .NET 8 / 10. Its UI porting does not handle `.svc`, `.ashx`, `.asmx`, service or web
  references, mixed `.aspx`/`.cshtml`, third-party UI controls or Web Site projects; it writes a Next Steps document
  that includes Linux readiness ([AWS Transform for .NET](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html)).
- **AWS DevTx Version Upgrade Toolkit**: Upgrade Assistant (deprecated by Microsoft in favour of the GitHub Copilot app
  modernization agent) then Kiro CLI with a 29-file .NET knowledge base, iterated until the build passes. Its knowledge
  base covers project files, System.Web, MVC, Web API, hosting, packages, data access, auth, config, logging, DI,
  middleware, Linux containers, WCF → CoreWCF, crypto, tests, Web Forms → Razor / Blazor and Remoting; it does not cover
  AWS managed-service swaps, IHttpAsyncHandler plumbing or ASMX Web References.
- Everything the chosen engine leaves is Claude's clean-up (tool_coverage.json maps each finding to its playbook).
