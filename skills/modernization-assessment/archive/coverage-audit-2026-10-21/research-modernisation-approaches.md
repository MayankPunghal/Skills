> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# .NET Framework to .NET 10 (Linux/AWS): modernisation approaches

Date: 2026-10-21. Purpose: guidance input for two skills (assess, then carry out). Read-only research. No client repositories or GitLab were touched.

Verification legend used throughout:
- **[V]** the primary page was opened and read.
- **[S]** only a search-result snippet was seen. Treat as a lead, not a verified fact.
- **[K]** general engineering knowledge, not sourced here. Verify before relying on it.

---

## 0. Key findings

- Upgrade Assistant is deprecated. Microsoft points to the GitHub Copilot app modernization agent for new work. [V](https://learn.microsoft.com/en-us/dotnet/core/porting/)
- AWS Transform for .NET lists the widest project set: class libraries, MVC, Web API, Web Forms, WCF, ASMX, WinForms/WPF, tests, targeting .NET 8 or .NET 10. Since Dec 2025 it also ports Web Forms UI to Blazor Server, with a documented unsupported list. [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html), [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html)
- Web Forms has no ASP.NET Core counterpart. Every route off Web Forms rewrites the UI layer. [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html)
- System.Web adapters let one shared library serve both .NET Framework and ASP.NET Core callers during transition. They are a bridge, not an end state. [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/inc/systemweb-adapters), [V](https://devblogs.microsoft.com/dotnet/incremental-asp-net-to-asp-net-core-migration/)
- WCF server on modern .NET means CoreWCF (ASP.NET Core hosted). WCF clients use dotnet-svcutil and the client packages. [V](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable), [V](https://learn.microsoft.com/en-us/dotnet/core/additional-tools/dotnet-svcutil-guide)
- WPF and WinForms are Windows-only on .NET. Realistic Linux paths are a rewrite, or keep them on Windows. [V](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/overview/)
- MongoDB: the driver upgrade is a multi-hop change (1.x, then 2.x, then 2.30, then 3.x), not a connection string edit. DocumentDB is mostly configuration, but the operator and write-semantics list matters. [V](https://www.mongodb.com/docs/drivers/csharp/current/reference/upgrade/v3/), [V](https://docs.aws.amazon.com/documentdb/latest/developerguide/functional-differences.html)
- The largest risks are rarely compile errors. They are session, ViewState and machineKey state, auth cookies, legacy GUID/BSON representation, and WCF wire contracts.

---

## 1. The 7 Rs

### 1.1 AWS definitions

Primary source: [AWS Prescriptive Guidance, About the migration strategies](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html) [V]. The 2016 "6 strategies" blog has no relocate and is historical only: [Orban, 2016](https://aws.amazon.com/blogs/enterprise-strategy/6-strategies-for-migrating-applications-to-the-cloud/) [V].

| R | AWS definition (paraphrased; key phrase quoted) | What it means for a .NET app |
|---|---|---|
| Retire | Decommission or archive applications no longer needed | Shut down the IIS site and DB, archive data |
| Retain | Keep in the source environment; not ready, or postponed | Keep Web Forms on .NET Framework on-prem for now |
| Rehost | Lift and shift; move "without making any changes to the application" | .NET Framework app on EC2 Windows, unchanged |
| Relocate | Hypervisor-level move to a cloud version of the same platform | VM estates to VMware Cloud on AWS; rarely an app-code decision |
| Repurchase | Switch to a different product, typically SaaS | Replace a commodity app (CMS, LMS, reporting) with a SaaS |
| Replatform | Move with some optimisation ("lift, tinker, and shift") | AWS's own example: port .NET Framework to .NET so it runs on Linux; containerise; SQL Server to RDS |
| Refactor / re-architect | Change architecture to use cloud-native features | Rewrite UI or service layer, split a monolith |

AWS advises against refactor in large migrations: rehost, relocate or replatform first, then modernise after cutover. [V](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html)

### 1.2 Per-R guidance

**Retire**
- Criteria (AWS): no business value; cost to host; unsupported OS or components; "zombie" apps (average CPU and memory under 5 percent); "idle" apps (5 to 20 percent over 90 days); no inbound connection for 90 days. [V](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html)
- Evidence to collect: IIS logs (last hit per app and path), SQL last-access stats for the DB, scheduled-task and job callers, WCF/ASMX consumer list, monitoring data. Confirm with the business owner. [K]
- Next steps: name the replacement (none, SaaS, another app, or read-only archive). Export data with a retention rule. Decommission: stop the site, remove DNS and load-balancer entries, revoke service accounts, delete secrets, remove monitoring and firewall rules, keep a final backup for the retention period. [K]
- Sign-off (suggested): app owner, business owner, security or compliance (data retention), DBA (DB retirement). [K]
- Risks: hidden consumers (batch jobs, partner WCF callers), regulatory retention, shared DB dependencies.

**Retain**
- Criteria (AWS): data residency or compliance; high risk needing a plan first; dependencies that must migrate first; recently upgraded; no business value; SaaS replacement planned; physical or specialised hardware; mainframe or mid-range. [V](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html)
- Evidence: data classification, contracts, dependency map (shared DB, shared library consumers), date of last investment. [K]
- Next steps: set a re-review date and exit criteria. Keep the framework patched. Record which other apps are blocked by this one. [K]
- Risks: retain becomes forever; security debt; a retained app that shares a DB or library blocks other moves.

**Rehost**
- Criteria: fast exit from the data centre, no code change allowed, deadline-driven. .NET Framework runs on EC2 Windows, so this is the only zero-code path for a Windows-only app. [K]
- Evidence: Windows and IIS version; machine-level dependencies (MSMQ, GAC, certificates, ODBC DSNs, COM, registry); config secrets in web.config. [K]
- Next steps: AWS tools named by AWS include AWS Application Migration Service (MGN), Cloud Migration Factory and VM Import/Export. [V](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html) Move secrets to Secrets Manager or SSM before cutover. [K]
- Risks: keeps Windows and SQL Server licence cost; no Linux; debt stays.

**Relocate**
- Criteria: whole server or VM estates to the same platform (for example VMware Cloud on AWS); moving RDS instances between VPCs, accounts or Regions. AWS states it needs no new hardware and no rewrite. [V](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html)
- Evidence: hypervisor and VMware licence position. [K]
- Next steps: infrastructure team work; no app-code change.
- Risks: licence cost and dedicated-host scaling limits [K]. Relocate is rarely the answer for an app-level modernisation decision.

**Repurchase**
- Criteria: commodity function (CRM, HR, LMS, CMS, reporting), SaaS covers the required features, licence plus maintenance exceeds SaaS cost. [V](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html)
- Evidence: feature inventory against the SaaS; data export capability; every integration point (especially WCF and ASMX consumers). [K]
- Next steps (AWS): train users, migrate data, integrate authentication (for example AD or SSO), configure networking. The vendor usually helps. [V](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html)
- Risks: data migration, integrations, customisations, lock-in.

**Replatform**
- Criteria: a concrete gain without changing core architecture. Examples: managed DB, containers, Graviton, or a .NET port to run on Linux. [V](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html)
- Evidence: Windows-only API scan (the assessment skill's job), IIS features, Windows auth, local file writes, SMTP, MSMQ. [K]
- Next steps: port to .NET 10 with mechanical changes, run in Linux containers, move the DB to a managed service.
- Risks: behaviour drift (path case sensitivity, culture, time zones, line endings). No refactor is done, so the risk is in the port itself. [K]

**Refactor / re-architect**
- Criteria (AWS): the legacy app can no longer meet demand or is expensive to run; monolith blocks delivery; nobody knows the code; test coverage is very low; a DB must be split. [V](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html)
- Evidence: change lead time, defect rate, test coverage, bus factor, cross-project and cross-schema coupling. [K]
- Port or rewrite:
  - Port when domain logic is valuable, tests exist or can be written, and the platform is the only blocker.
  - Rewrite the UI slice when the UI framework has no counterpart (Web Forms). Even under a replatform plan, the UI slice is effectively a refactor. [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html)
  - Microsoft: in-place migration can work for small apps with few dependencies. Incremental is safer for large apps, apps with heavy System.Web use, or unknown dependencies. [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/)
- How to do it incrementally: strangler fig with YARP; move one route at a time; libraries first; characterisation tests before change; keep the shared DB until the seams are clear. [V](https://devblogs.microsoft.com/dotnet/incremental-asp-net-to-asp-net-core-migration/)
- Risks: second-system effect, scope creep, parallel-run cost, business-rule drift. The archived benchmark note (~\.claude\research-archive\dotnet-migration-effort-benchmarks.md) cites QSM data: conversion projects with under 5 percent new function have a worse productivity index than new builds. Treat conversion effort as not automatically cheaper than a rewrite.

### 1.3 Decision tree

```
Is the app still needed (usage, owners, consumers)?
  NO  -> RETIRE: archive data, decommission, sign-off
  YES
    Commodity function with a SaaS fit, and integrations/data export acceptable?
      YES -> REPURCHASE
      NO
        Hard blocker to moving now (compliance, vendor, hardware, unresolved deps)?
          YES -> RETAIN (set re-review date and exit criteria)
          NO
            Must leave the data centre fast with zero code change?
              YES -> REHOST (EC2 Windows via MGN); VM estate on VMware? -> RELOCATE
              NO
                Is the platform the only blocker (Windows-only, IIS, SQL Server licence)?
                  YES -> REPLATFORM (port to .NET 10, Linux containers, managed DB)
                  NO  -> REFACTOR / RE-ARCHITECT (strangler, incremental)

Overlay: if the UI framework has no .NET 10 counterpart (Web Forms), that UI slice is a
REFACTOR regardless of the app-level answer.
```

---

## 2. ASP.NET Web Forms: coupling and move to Blazor or Razor

### 2.1 Coupling inventory (per page, including its .ascx, .master and code-behind)

| Layer | Coupling | Why it matters | Detection (grep, [K]) | Target |
|---|---|---|---|---|
| .aspx markup | `runat="server"`, `<asp:*>` controls, data-bound controls, master pages, user controls | Each control maps to a component or a helper | `runat="server"`, `<asp:`, `EnableViewState` | Blazor components (see BlazorWebFormsComponents) |
| Code-behind | `Page_Load`, `IsPostBack`, control event handlers (Click, SelectedIndexChanged) | Event model changes | `IsPostBack`, `_Click`, `_SelectedIndexChanged` | Component event callbacks or endpoints |
| ViewState | Serialised server state in a hidden field, protected by machineKey | Cannot be carried across; must become fields or a state service | `ViewState[`, `__VIEWSTATE` | Component fields, scoped services |
| UpdatePanel / ScriptManager | Partial postbacks driven by JS | Replaced by Blazor rendering. BlazorWebFormsComponents has shims for both. [V](https://github.com/FritzAndFriends/BlazorWebFormsComponents) | `UpdatePanel`, `ScriptManager` | Blazor rendering, or a JS interop helper |
| `__doPostBack` and client JS | Postback by control ID; JS reads `ClientID` in the DOM | Generated IDs change (`ctl00$...`), so selectors break | `__doPostBack`, `ClientID`, `getElementById('<%=`, `$get(` | Stable element IDs, JS interop |
| PageMethods / AJAX web methods | Static methods called from JS | Becomes an endpoint | `PageMethods`, `[WebMethod]` | Minimal API or controller |
| Server-emitted JS | `ClientScript.RegisterStartupScript`, validators, menus, tree views emitting script | Behaviour is silently lost unless replaced | `RegisterStartupScript`, `RegisterClientScriptBlock` | Blazor equivalents, or BlazorWebFormsComponents |
| Request and Response | `Request.Form["ctl00$..."]`, `Server.Transfer`, `Response.Redirect`, query strings | Form field names change | `Request.Form`, `Server.Transfer` | Named parameters or model binding |
| Handlers and modules | `.ashx`, `.asmx`, `.svc`, Global.asax, HttpModules | AWS UI porting does not handle `.ashx`, `.svc`, `.asmx` [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html) | file-type scan | Middleware, endpoints, CoreWCF |
| Auth and state | Forms auth, membership, Session, machineKey | Cookie and data-protection compatibility (section 7) | `Session[`, `FormsAuthentication`, `machineKey` | Shared data protection or re-login; session strategy (2.3) |

Form field names (`ctl00$MainContent$txtName`) must be captured. Parity tests and any UI automation use them.

### 2.2 Target options

| Option | What it is | Fits | Cost or risk | Source |
|---|---|---|---|---|
| Blazor Interactive Server | Components run on the server; events go over a real-time circuit | Stateful forms, closest to Web Forms server model. AWS UI porting targets this. | One circuit per connected user (server memory); connection loss; no offline | [V](https://learn.microsoft.com/en-us/aspnet/core/blazor/components/render-modes) (circuit description), [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html) |
| Blazor Static SSR | Server-rendered, no interactivity; forms post normally | Read-heavy pages, simple forms | Interactivity must be added per component | [V](https://learn.microsoft.com/en-us/aspnet/core/blazor/components/render-modes) |
| Blazor WebAssembly, Interactive Auto | Client-side .NET in the browser; Auto starts on server, then moves to WASM | Client-heavy UI, offline-ish | Download size; API boundary; security model shifts to the client | [V](https://learn.microsoft.com/en-us/aspnet/core/blazor/components/render-modes) |
| Razor Pages or MVC | Request and response with models; no component state | Simple CRUD and form-heavy pages | Event model becomes HTTP endpoints; more JS for rich UI [K] | [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/) (general) |
| BlazorWebFormsComponents | Blazor components named after Web Forms controls, plus a `webforms-to-blazor` CLI for the first phase | Control-heavy pages; keeps markup vocabulary | Not automatic. DataSource controls, skins and themes not converted. Ajax Toolkit has render-mode requirements. The CLI covers phase one only. [V](https://github.com/FritzAndFriends/BlazorWebFormsComponents) | MIT licence, active project |
| AWS Transform UI porting | Converts .aspx/.ascx to .razor, .master to layout.razor, Web.config to appsettings.json, Global.asax to Program.cs, to Blazor Server | First pass over a large estate | Unsupported list (section 8). The blog's build succeeded, but runtime errors needed AI-assisted fixes. ViewState, JS and code-behind behaviour are not documented. [V](https://aws.amazon.com/blogs/dotnet/modernize-asp-net-web-forms-ui-to-blazor-with-aws-transform) | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html) |

The Microsoft e-book "Blazor for ASP.NET Web Forms Developers" is an introduction, not a migration guide. The Learn copy is the v8.0 edition, so it predates .NET 10. [V](https://learn.microsoft.com/en-us/dotnet/architecture/blazor-for-web-forms-developers) Reference app: [eShopOnBlazor](https://github.com/dotnet-architecture/eshoponblazor) (linked from the e-book).

### 2.3 Incremental approach (strangler, adapters, session)

- **Front door.** A new ASP.NET Core app becomes the entry point, using YARP. Anything it cannot match is proxied to the legacy app. The URL stays the same. [V](https://devblogs.microsoft.com/dotnet/incremental-asp-net-to-asp-net-core-migration/)
- **Shared HttpContext.** SystemWebAdapters lets libraries and the legacy app keep System.Web-style code. [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/inc/systemweb-adapters)
- **Session.** Three options [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/areas/session):

| Approach | Code change | Sharing | Note |
|---|---|---|---|
| Built-in ASP.NET Core session | High; rewrite session access | None | Best performance; `byte[]` values; no locking; keys case-sensitive |
| Wrapped session (adapters) | Low | None | Migrated pages keep session patterns; legacy app unaffected |
| Remote app session (adapters) | Low | Full, both ways | Core app queries the legacy app over HTTP with an API key; readonly is a GET; writable keeps the GET open and sends a PUT; every session key must be registered with a type; JSON serialiser; "performance and security" caveat stated by Microsoft |

- **Auth and machineKey.** Both apps must share a data-protection application name and key store (a UNC share, Redis or Blob storage in production). The legacy app uses the FrameworkServices package and the compatibility data protector. [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/areas/machine-key)
- **Order.** Libraries first, then routes (MVC and Web API controllers, Web Forms pages, handlers), then shared code. A route can run in both apps for A/B testing. Remove adapters at the end. [V](https://devblogs.microsoft.com/dotnet/incremental-asp-net-to-asp-net-core-migration/)
- **Proxy effects.** The legacy app becomes downstream of a reverse proxy. Enable forwarded headers and expect side effects. [V](https://devblogs.microsoft.com/dotnet/incremental-asp-net-to-asp-net-core-migration/)
- **Key discovery.** Microsoft notes that finding session keys is hard when session use is ad hoc. Grep the code for `Session[` first. [V](https://devblogs.microsoft.com/dotnet/incremental-asp-net-to-asp-net-core-migration/)

### 2.4 Single-page method (step by step)

1. **Pick the page.** Low coupling, high business value, and an existing or cheap-to-write test path.
2. **Inventory.** Run the 2.1 grep set over the page, its .ascx and .master files, its code-behind, and its JS and CSS. Record: server control IDs used by JS or CSS; Session and ViewState keys; event handlers; data sources (SqlDataSource, ObjectDataSource); form field names.
3. **Golden master.** Script every path in the legacy app: load, postback, validation errors, empty data, paging and sorting, error pages. Save rendered HTML, form field names, POST payloads, redirects, and DB side effects. [K]
4. **Libraries.** Confirm the shared libraries the page uses are adapter-enabled or multi-targeted (section 3). Do this before moving the page.
5. **Pick the target mode.** Static SSR for read-only pages. Interactive Server for stateful forms. Razor Pages for simple CRUD.
6. **Build the page.** Convert markup to components (or to BlazorWebFormsComponents for control-heavy pages). Move event handlers into methods. Replace ViewState with component fields. Replace Session with a scoped service if it is not shared, or use remote-app session if the legacy app still reads it.
7. **Replace JS.** Rewrite `__doPostBack` and `ClientID` selectors to stable element IDs or JS interop. Remove UpdatePanel. Recheck validation messages.
8. **Route.** Add the YARP route for this page to the new app. Keep the legacy route for rollback.
9. **Parity.** Run the golden scripts against both apps with the same seed data. Diff the rendered text, form data and DB side effects. Only documented differences are allowed.
10. **Cut over.** Feature-flag or canary, then retire the legacy route. Remove unused adapters later.

### 2.5 Parity testing checklist [K]

- Same seed data in both apps; compare DB writes, not just screens.
- Validation messages, redirects, status codes, cookies, antiforgery tokens, session expiry.
- Concurrency: Framework session locks per session; ASP.NET Core session does not. Test double-submits. [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/areas/session)
- Browser automation (for example Playwright) against both apps, with DOM and form-field diffs.

---

## 3. HttpContext in shared class libraries

### 3.1 System.Web adapters

| Package | Targets | Used by | Source |
|---|---|---|---|
| Microsoft.AspNetCore.SystemWebAdapters | .NET Standard 2.0, .NET Framework 4.5+, .NET 5+ | Supporting libraries | [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/inc/systemweb-adapters) |
| ...SystemWebAdapters.FrameworkServices | .NET Framework only | The legacy app | same |
| ...SystemWebAdapters.CoreServices | .NET 6+ | The ASP.NET Core app | same |
| ...SystemWebAdapters.Abstractions | Supporting | Session serialisation and similar | same |

- Conversion: implicit cast, `AsSystemWeb()` and `AsAspNetCore()`. Both are cached for the request. [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/inc/systemweb-adapters)
- If the only System.Web dependency is HttpContext, a library can target .NET Standard 2.0. [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/inc/systemweb-adapters)
- Request-scoped: the adapter wraps the request, so copy values into a POCO if they are needed later. [S](https://learn.microsoft.com/en-gb/aspnet/core/migration/inc/usage_guidance?view=aspnetcore-6.0)
- Adapters are a bridge. The stated goal is to remove them once migration completes. [V](https://devblogs.microsoft.com/dotnet/incremental-asp-net-to-asp-net-core-migration/)
- Testing: anything touching `HttpRuntime` needs the adapters' test host. xUnit collections must set `DisableParallelization`. [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/inc/systemweb-adapters)
- Coverage gap: I did not verify the adapters' full System.Web API list. Check it before relying on a specific type.

### 3.2 Abstraction approach [K]

- Do not pass HttpContext down the stack. Pass explicit values or DTOs at the boundary.
- For reads such as user identity, request headers and tenant ID, define a small interface in the library (for example `ICurrentRequest`).
- Implement it twice: one for .NET Framework (wraps `HttpContext.Current`), one for ASP.NET Core (wraps `IHttpContextAccessor`).
- Registration happens in each host. Libraries never reference `HttpContext.Current` directly.

### 3.3 Multi-targeting and ordering

- Order: a dependency graph, leaves first. Microsoft says libraries must be upgraded in post-order depth-first order. [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/)
- Targets during transition: `netstandard2.0` if the adapters are the only blocker; otherwise multi-target `net48;net10.0` (or `net8.0`) [K for the multi-target pattern]. Microsoft notes libraries must support every framework version the app targets. [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/)
- Windows-only APIs: the Windows Compatibility Pack covers registry, EventLog, WMI, DirectoryServices, Configuration, Drawing and others. It suits code that stays on Windows. [V](https://learn.microsoft.com/en-us/dotnet/core/porting/windows-compat-pack)
- Linux: use the platform compatibility analyzer to find Windows-only API calls. [V](https://learn.microsoft.com/en-us/dotnet/core/porting/windows-compat-pack)
- Gate each library on a clean build with the analyzers on, plus its unit tests.
- The dedicated Microsoft "porting libraries" page was not retrieved. The netstandard2.0 point above comes from the adapters doc.

---

## 4. WCF, ASMX and client proxies

### 4.1 Server side: CoreWCF

- What: the service side of WCF, ported to .NET Core. [V](https://github.com/CoreWCF/CoreWCF)
- Frameworks: the template targets net8.0 by default; net6.0, net48, net472, net462 are accepted. [V](https://github.com/CoreWCF/CoreWCF)
- Bindings: the template exposes BasicHttpBinding (HTTPS by default). Packages exist for NetTcp, NetNamedPipe, WebHttp, Http, MSMQ, RabbitMQ, Kafka, UnixDomainSocket. WSHttpBinding and NetHttpBinding are not confirmed on the page. [V](https://github.com/CoreWCF/CoreWCF)
- Linux: NetNamedPipe is Windows-only [K]. Avoid it on Linux targets.
- WS-* security and transactions: not stated on the page. Test them. [V](https://github.com/CoreWCF/CoreWCF)
- Support: CoreWCF 1.9 (April 2026) is listed as supporting .NET 10, with end of support in November 2028. [S](https://dotnet.microsoft.com/ja-jp/platform/support/policy/corewcf)
- Why CoreWCF: WCF server cannot be hosted on modern .NET without the CoreWCF packages. [V](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable)
- Config: web.config WCF settings move to code or appsettings.json. [S](https://learn.microsoft.com/en-sg/answers/questions/2243231/how-to-convert-soap-wcf-services-4-8-to-net-core-8)
- Upgrade tool: Microsoft's CoreWCF upgrade path uses a legacy Upgrade Assistant version (0.4.421302). Projects must create a `ServiceHost` in code with config; `.svc`-hosted projects are not supported. [S](https://learn.microsoft.com/en-in/dotnet/core/porting/upgrade-assistant-wcf) Upgrade Assistant is deprecated [V](https://learn.microsoft.com/en-us/dotnet/core/porting/).
- WIF is not supported. Microsoft's guidance is JWT or other token approaches. [S](https://mobilize.net/blog/consuming-wcf-services-in-dotnet8)

### 4.2 Client side

- dotnet-svcutil: cross-platform .NET tool. It generates a `ClientBase`-derived proxy. `-u` regenerates from `ConnectedService.json`. [V](https://learn.microsoft.com/en-us/dotnet/core/additional-tools/dotnet-svcutil-guide)
- Client packages in dotnet/wcf: Primitives, Http (BasicHttp), NetTcp, NetNamedPipe, Federation (WS-Federation), System.Web.Services.Description. Duplex and Security packages are deprecated (6.0 was the last release). The aim is parity with the Windows Store libraries, and some features are still in progress. [V](https://github.com/dotnet/wcf)
- Practical reading: BasicHttp and NetTcp clients are workable on .NET 10. Message-level WS-Security needs a specific test. [K]

### 4.3 ASMX and Web References

- AWS Transform lists ASMX web services as a supported project type. [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) Its UI porting does not handle `.asmx` or service and web references. [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html)
- I did not find a Microsoft page on ASMX-to-CoreWCF or on replacing SoapHttpClientProtocol. [gap]
- ASMX does not run on modern .NET. [K]
- Options:
  - Server: rewrite the `.asmx` as a CoreWCF service that matches the existing WSDL (wire-compatible). [K for effort]
  - Keep the `.asmx` on a .NET Framework host (rehost) until the consumers move. [K]
  - Build a new REST or gRPC API and keep ASMX only for legacy consumers. [K]
- Client Web References: regenerate with dotnet-svcutil (or Connected Services). The generated proxy shape changes, so call sites change. [K]

### 4.4 Wire compatibility for external callers

| Element | Risk | Mitigation |
|---|---|---|
| Endpoint URL (`.asmx`, `.svc` paths) | Callers break | Keep the same path (YARP route or CoreWCF service path) |
| SOAP version and WSDL | Generated stubs break | Diff WSDL before and after; pin the binding [K] |
| Namespaces, operation and action names | Callers break | Contract snapshot tests |
| Serialisation (XmlSerializer in ASMX vs DataContractSerializer in WCF) | Element order, nullability, enum values differ | Recorded-XML contract tests; use XmlSerializer-style attributes where needed [K] |
| Faults | Client error handling breaks | Keep the same SOAP fault codes [K] |
| Auth (Windows or Kerberos, WS-Security, certificates) | Integrated auth is hard on Linux | Confirm with each consumer; consider mTLS or tokens [K] |
| Binding (basicHttp vs wsHttp) | Client config breaks | Keep basicHttp where possible |
| Limits (timeouts, message size) | Large payloads fail | Set the same limits explicitly |
| Consumers | Unknown callers | Dual-run both endpoints, log caller identity, set a deprecation date |

---

## 5. WPF and WinForms desktop apps

- WPF is Windows-only on .NET. [V](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/overview/)
- Windows Forms is a UI framework for Windows desktop apps; the .NET version runs on .NET. [V](https://learn.microsoft.com/en-us/dotnet/desktop/winforms/overview/)
- The .NET Framework 4 WinForms does not support passing controls across AppDomains. Modern .NET drops AppDomains. [V](https://learn.microsoft.com/en-us/dotnet/desktop/winforms/overview/)

| Option | What it is | Pros | Cons | Source |
|---|---|---|---|---|
| Keep on Windows, port to .NET 10 | WinForms or WPF on .NET 10, run on Windows | Least change; Windows APIs stay available | Windows licence and hosts; not Linux | [V](https://learn.microsoft.com/en-us/dotnet/core/porting/windows-compat-pack) (stays on Windows) |
| Amazon WorkSpaces applications (formerly AppStream 2.0) | Stream desktop apps from Windows images to a browser | No code change; users need no install | Per-session cost; GPU options; Windows images [K] | [V](https://aws.amazon.com/appstream2/) |
| Rewrite to Blazor (web) | UI rebuilt as Blazor; view models reused | Linux-hostable | Full UI rewrite | [K] |
| MAUI or Blazor Hybrid | Cross-platform .NET UI | Hybrid reuses Razor components | MAUI desktop is not Linux [K] | [K] |
| Avalonia (third party) | XAML-like UI with Linux desktop support | Closest to WPF on Linux | Third-party; rewrite of views [K] | [K] |

Challenges [K]: Windows-only APIs (registry, printing, COM), third-party control licences, XAML and WinForms designer tooling, DPI scaling, and deployment (ClickOnce or MSI).

AWS Transform: the English docs list Desktop (WinForms, WPF) as supported project types. [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) A Portuguese copy listed them as preview. [S] Check the current English page before claiming either.

---

## 6. MongoDB: legacy C# driver to 2.x or 3.x, and DocumentDB

### 6.1 Driver upgrade

Upgrade path [V](https://www.mongodb.com/docs/drivers/csharp/current/reference/upgrade/v3/):
- Move to 2.30 first, then address the 3.0 breaking changes.
- The legacy 1.x API shipped as the `mongocsharpdriver` package in 2.x. It was removed in 3.0. You must migrate to the new API.

Key 3.x changes [V](https://www.mongodb.com/docs/drivers/csharp/current/reference/upgrade/v3/):

| Change | Impact |
|---|---|
| `MongoClient`, `MongoDatabase`, `MongoCollection` are sealed; use `IMongoClient`, `IMongoDatabase`, `IMongoCollection<T>` | Type signatures change |
| LINQ2 removed; LINQ3 only. Client-side projections need `EnableClientSideProjections`. | LINQ queries may fail |
| `IMongoQueryable` replaced by `IQueryable` | Find and replace |
| GUID representation: V3 only; `BsonBinaryData(Guid)` removed; `GuidRepresentation` property removed | Data written with legacy representation may read back wrong. Highest-risk item. |
| Decimal128 and DateTimeOffset default serialisation changed | Stored values change format on write |
| TimeOnly default serialisation changed to int64 ticks | Same |
| JSON output default is Relaxed Extended JSON | Affects anything that parses ToJson() output |
| MONGODB-CR auth removed | Old auth settings fail |
| TLS 1.0 and 1.1 removed | Needs TLS 1.2+ |
| Obsolete BsonValue, BsonDocument and Bson methods removed | Compile errors |
| Server floor: 4.0+ in 3.0; 4.2+ in 3.5; 4.4+ in 3.10 | Check the server version first |
| .NET floor: .NET Framework 4.7.2+, .NET Core 3.x+ | Fine for .NET 10 |

The upgrade page lists breaking changes up to 3.10. Check the compatibility matrix for the version you pin. [V](https://www.mongodb.com/docs/drivers/csharp/current/upgrade/)

Other version notes:
- 2.14 dropped server 3.4 and below, and .NET Framework 4.5.2. [V](https://www.mongodb.com/docs/drivers/csharp/current/reference/upgrade/v2/)
- 2.19 restricts `ObjectSerializer` to safe types by default. [V](https://www.mongodb.com/docs/drivers/csharp/current/reference/upgrade/v2/)

Write semantics (important for a 1.x app):
- The legacy `MongoServer` path defaulted to Unacknowledged writes. [S](https://jira.mongodb.org/browse/CSHARP-664)
- The modern driver changed the default to acknowledged writes. [S](https://jira.mongodb.org/browse/CSHARP-614)
- Unacknowledged writes can fail silently. The guidance is to avoid them unless silent failure is acceptable. A 2.10.0 and 2.10.1 bug with retryable writes is noted. [S](https://jira.mongodb.org/browse/CSHARP-2960)

Legacy API mapping (from driver knowledge, [K]; verify against the v2 guide):

| Legacy 1.x | Modern |
|---|---|
| `MongoServer.Create` / `GetServer` | `MongoClient` / `IMongoClient` |
| `MongoCollection<T>` | `IMongoCollection<T>` |
| `Insert` | `InsertOne` / `InsertMany` |
| `Update` / `Save` | `UpdateOne` / `UpdateMany` / `ReplaceOne` with upsert |
| `Remove` | `DeleteOne` / `DeleteMany` |
| `FindOne` / `FindAs` | `Find(...).FirstOrDefault()` / `Find(...)` |
| `SafeMode` / `WriteConcern.Unacknowledged` | Explicit `WriteConcern` on the collection settings |

Sizing (estimate, [K]). The code change is usually the smaller part. Time goes to data-representation checks and write-semantics checks.

| App profile | Driver call sites | Custom serialisers, GUIDs, unacknowledged writes | Effort |
|---|---|---|---|
| Small | Under ~50 | None | 2 to 4 days, plus tests |
| Medium | ~50 to 300 | Some | 1 to 3 weeks |
| Large | 300+ | Many | 4 to 8+ weeks, including a GUID data check |

AWS Transform for .NET does not document MongoDB driver upgrades. Treat it as a manual or AI-assisted task unless verified. [gap]

### 6.2 Amazon DocumentDB compatibility

Supported API versions: MongoDB 3.6, 4.0, 5.0 and 8.0. [V](https://docs.aws.amazon.com/documentdb/latest/developerguide/mongo-apis.html)

Connection and TLS [V](https://docs.aws.amazon.com/documentdb/latest/developerguide/connect_programmatically.html):
- TLS is on by default.
- Download `global-bundle.pem` and pass it as `tlsCAFile`.
- Example string: `mongodb://...?tls=true&tlsCAFile=global-bundle.pem&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false`.
- The AWS .NET sample imports the CA into the Windows Root store. That does not apply on Linux. Use the CA file path or the OS trust store on Linux. [V sample; Linux mechanism K]

Retryable writes [V](https://docs.aws.amazon.com/documentdb/latest/developerguide/functional-differences.html):
- Supported from engine 8.0.2.
- On earlier engines, set `retryWrites=false`. Otherwise writes fail with "Retryable writes are not supported" (code 301).
- Most current drivers enable retryable writes by default.

Notable gaps [V](https://docs.aws.amazon.com/documentdb/latest/developerguide/mongo-apis.html), [V](https://docs.aws.amazon.com/documentdb/latest/developerguide/functional-differences.html):

| Area | Status |
|---|---|
| `$where` | Not supported |
| `getLastError`, `getPrevError`, `resetError` | Not supported (matters for legacy SafeMode code) |
| Capped collections | Not supported |
| Hashed and wildcard indexes | Not supported |
| Admin and local databases | Not supported |
| Reverse `$natural` scan | Not supported |
| `mapReduce` | Only on engine 8.0 |
| Transactions | Supported from 4.0 |
| Change streams | Supported |
| `$text` | From 5.0 |
| Collation | Only `cursor.collation` on 8.0; case-insensitive indexes on 8.0 |
| Result ordering | Not guaranteed; the app must sort explicitly |
| Network compression | `snappy` only |
| `$lookup` correlated subqueries | From 8.0.2 |
| Index builds | One build per collection at a time |

Verdict [K]: most of a driver app moves with configuration (connection string, TLS CA, `retryWrites=false` below 8.0.2). Exceptions: any use of the gaps above, reliance on natural order, or legacy write-concern patterns. Small apps: 1 to 3 days. Medium apps: 1 to 2 weeks, mostly regression.

---

## 7. Other common challenges (one line each, with replacement)

| Challenge | Why it bites | Replacement or approach | Source |
|---|---|---|---|
| AppDomains (`CreateDomain`) | Throws `PlatformNotSupportedException` | Separate processes or containers; `AssemblyLoadContext` for dynamic loading | [V](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable) |
| .NET Remoting | Not supported; `BeginInvoke`/`EndInvoke` throw | In-process: pipes or memory-mapped files. Cross-machine: HTTP (Kestrel) or gRPC. StreamJsonRpc for JSON or MessagePack. | [V](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable) |
| Code Access Security, security transparency | Not a security boundary; not supported | OS boundaries: containers, least-privilege accounts | [V](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable) |
| System.EnterpriseServices (COM+) | Not supported | Redesign (queue or service) [K] | [V](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable) |
| Windows Workflow Foundation | Not supported | CoreWF (UiPath) or a state-machine library | [V](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable) |
| Reflection.Emit `AssemblyBuilder.Save` | Not in .NET 8 and earlier; back in .NET 9 as `PersistedAssemblyBuilder` | Upgrade to .NET 9+ API | [V](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable) |
| Multi-module assemblies | Not supported | Merge modules into one assembly | [V](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable) |
| XSLT script blocks (`msxsl:script`) | Not supported | Extension objects in C# [K] | [V](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable) |
| WCF server | Not built in | CoreWCF | [V](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable) |
| Windows-only APIs (registry, EventLog, WMI, DirectoryServices, Configuration, Drawing, Services, perf counters) | Windows-only | Windows Compatibility Pack if staying on Windows; otherwise replace (Microsoft.Extensions.Configuration; cross-platform imaging library) [K] | [V](https://learn.microsoft.com/en-us/dotnet/core/porting/windows-compat-pack) |
| EF6 (EDMX designer, some features) | EF Core is not a drop-in; EDMX has no planned support | Keep EF6 on stable code (EF6.4 runs on .NET Core); port to EF Core where data access is evolving. Lazy loading exists in EF Core from 2.1. | [V](https://learn.microsoft.com/en-us/ef/efcore-and-ef6/) |
| Crystal Reports, ReportViewer (WebForms, WinForms RDLC) | No official .NET port found | Third-party ReportViewerCore is not supported by Microsoft [S](https://www.nuget.org/packages/ReportViewerCore.WinForms/); otherwise replace the reporting engine [K] | [S](https://learn.microsoft.com/en-us/answers/questions/2283533/how-can-i-display-rdlc-reports-in-a-net-8-winforms) |
| SSRS paginated reports | Not researched | Host separately or replace [K] | [K] |
| Session state | In-proc vs serialised; no locking in Core; case-sensitive keys; BinaryFormatter-era serialisation | Built-in, wrapped or remote-app session; JSON with registered keys | [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/areas/session) |
| Forms auth, machineKey, ViewState protection | Cookies and ViewState not compatible across apps | Shared data protection (app name and key store) or forced re-login | [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/areas/machine-key) |
| Global.asax | No equivalent | Program.cs (AWS maps Global.asax to Program.cs) | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html) |
| HTTP modules and handlers | Replaced by middleware | ASP.NET Core middleware and endpoints | [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/areas/) (areas list) and [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/) (architecture differences) |
| Web.config settings | Not used | appsettings.json (AWS maps this) | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html) |
| Membership, ClaimsPrincipal.Current, OWIN | Areas exist in Microsoft's guide | ASP.NET Core Identity; `HttpContext.User`; middleware [K] | [V](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/areas/) (existence) |
| ASP.NET MVC and Web API 2 | System.Web.Mvc namespaces | ASP.NET Core MVC or Web API; AWS ports Razor views in place | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html) |
| Bundling and minification (System.Web.Optimization) | Not available | Static asset pipeline or a bundler [K] | [K] |
| BinaryFormatter | Removed in .NET 9 | JSON or MessagePack [K] | [K] |
| Windows integrated auth (Kerberos, NTLM) on Linux | Not native | Kerberos keytabs, or OIDC or SAML through an identity provider [K] | [K] |
| Connection strings and secrets in web.config | Secret exposure | Secrets Manager or SSM Parameter Store [K] | [K] |

---

## 8. AWS Transform for .NET

| Area | Fact | Source |
|---|---|---|
| Sources | .NET Framework 3.5; .NET Core 3.1; .NET 5.x through .NET 10 | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) |
| Targets | .NET 8, .NET 10, .NET Standard (class libraries) | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) |
| Languages | C#, VB.NET | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) |
| Project types | Class libraries; console; ASP.NET (MVC, Web API, Web Forms); unit tests (NUnit, xUnit, MSTest); WCF services; desktop (WinForms, WPF); Xamarin; ASMX | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) |
| Not transformed | Win32 DLLs without core-compatible libraries; repos without .NET solutions; Web Site projects without a project file | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) |
| Source control | Azure Repos, Bitbucket, GitHub, GitLab | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) |
| Surfaces | Web app; Visual Studio IDE; MCP server for AI code companions | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) |
| Workflow | Connect repo; assess; review and edit plan; transform; build and unit-test validation; review and accept; report and next steps | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) |
| Human steps | Connector setup; plan validation; upload missing NuGet packages; accept transformed code | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) |
| Web Forms UI | UI port to Blazor Server, Web Forms only as a job setting. Unsupported: `.svc`, `.ashx`, `.asmx`, service and web references, mixed `.aspx` and `.cshtml`, third-party UI controls, Web Site projects | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html) |
| MVC Razor UI | Ported in place to ASP.NET Core Razor Views | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet-porting-ui.html) |
| Dec 2025 additions | Web Forms to Blazor UI porting; Entity Framework ORM porting; VS 2026 and 2022 toolkit with editable plan, time estimate, live progress, rerun with revised plan; Next Steps document (includes Linux readiness) | [V](https://aws.amazon.com/about-aws/whats-new/2025/12/transform-net-transformation-developer-experience) |
| Non-.NET UI | Web Forms to React (and similar) is out of scope; use AWS Transform custom | [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html) |
| Quotas and limits | See the quotas page linked from the .NET docs (not opened) | [gap](https://docs.aws.amazon.com/transform/latest/userguide/transform-limits.html) |
| Vendor benchmarks | Caribbean Examinations Council: 143 KLOC in under 2 days, about 270 dev hours saved. Vendor claim. | Archived note (dotnet-migration-effort-benchmarks.md) |
| "Version upgrade toolkit" or DevTx | Not found in this research | [gap] |

Notes:
- AWS Transform for .NET is .NET to .NET. Non-.NET targets use AWS Transform custom. [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html)
- It can also update modern .NET apps to later versions. [V](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html)
- It does not document MongoDB driver upgrades, WCF client proxy regeneration for Web References, or ViewState and JS behaviour after Web Forms porting. Verify each before relying on it.

---

## 9. Implications for the two skills

Assess skill:
- Classify each app with the decision tree (1.3). Record the evidence for each branch: usage logs, consumers, coupling, test coverage.
- Flag Web Forms, WCF, ASMX, WinForms and WPF as the high-effort items. Flag MongoDB 1.x and DocumentDB operator gaps.
- Flag machineKey and session dependencies, and any System.Web use in shared libraries.
- Flag Crystal Reports and ReportViewer as blockers with no official port.

Carry-out skill:
- Libraries first (section 3), then routes (section 2.3), one page at a time (section 2.4).
- Keep WCF contracts pinned with snapshot tests (section 4.4) before any service change.
- Do the MongoDB GUID and write-concern checks before the driver upgrade (section 6.1).
- Use AWS Transform for the mechanical port, and add manual work for the unsupported list.

---

## 10. Gaps and what to verify

- MongoDB 2.x MongoServer removal: only a JIRA snippet was seen. [S]
- CoreWCF 1.9 and .NET 10 support: snippet only. [S]
- ASMX on modern .NET and a replacement path: no Microsoft page retrieved. [gap]
- Web Forms ViewState, UpdatePanel and JS behaviour after conversion: no Microsoft page retrieved. BlazorWebFormsComponents covers names only. [gap]
- Crystal Reports and SSRS: no official route found. [gap]
- AWS Transform limits and quotas page: linked, not opened. [gap]
- System.Web adapters usage guidance: snippet only. [S]
- Upgrade Assistant WCF specifics: snippet only. [S]
- The Blazor e-book is the v8.0 edition. Check .NET 10 specifics elsewhere. [V]
- Nothing was written to the research archive; the request was for this output file only. The global CLAUDE.md archive step can be run on request.
