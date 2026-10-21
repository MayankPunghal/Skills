# Playbook: System.Web residue (HttpContext, Server.MapPath, HttpRuntime)

**Rules:** WEB-SYSTEMWEB-NS, WEB-HTTPCONTEXT-CURRENT, FILE-MAPPATH (residue); LNX-WEB-SYSTEMWEB, LNX-WEB-HTTPCONTEXT-CURRENT (Linux readiness).
**Engines:** DevTx KB 02 and AWS Transform rewrite most direct uses inside the web project. What they leave: uses inside shared class libraries, `HttpRuntime.Cache`, `HostingEnvironment`, `HttpContext.Current` read from deep call stacks. Claude does those.

## Decide per library first

`System.Web.HttpContext` inside a shared library is the expensive part when several applications use it. Do not convert it use by use in every library and every caller. Per library, in order of preference:

1. **Pass what is needed.** The library takes the values (user id, tenant, headers, client IP) as arguments or through a small interface (`ICurrentRequest`) that each host implements once. The library then targets `netstandard2.0` with no web dependency.
2. **System.Web adapters** (`Microsoft.AspNetCore.SystemWebAdapters`) while .NET Framework callers remain: one `System.Web.HttpContext` type that compiles on both runtimes. The legacy host registers `...FrameworkServices`, the new host `...CoreServices` (`builder.Services.AddSystemWebAdapters()`, `app.UseSystemWebAdapters()`). A bridge: put its removal in the plan.
3. **`IHttpContextAccessor`** in libraries used only by ASP.NET Core hosts (inject it; never a static).

## Replacements inside the web project

| .NET Framework | ASP.NET Core |
|---|---|
| `HttpContext.Current` | Inject `IHttpContextAccessor`, or take `HttpContext` from the controller / endpoint / middleware |
| `HttpContext.Current.Items` as a per-request bag | `HttpContext.Items`, or a scoped service; ambient use → [ambient-context-and-remoting.md](ambient-context-and-remoting.md) |
| `Request.QueryString`, `Request.Form`, `Request.Params` | `Request.Query`, `Request.Form` (async `ReadFormAsync` outside MVC), model binding; `Params` has no equivalent: pick the source |
| `Request.UserHostAddress`, `ServerVariables["REMOTE_ADDR"]` | `Connection.RemoteIpAddress` **after** `UseForwardedHeaders` (behind the ALB the raw address is the load balancer) |
| `Request.Url`, `RawUrl` | `Request.GetDisplayUrl()`, `Request.Path` + `QueryString` |
| `Response.Redirect`, `Response.End` | `Results.Redirect` / `RedirectResult`; `End` has no equivalent: return |
| `Server.MapPath("~/x")` | `IWebHostEnvironment.ContentRootPath` / `WebRootPath` + `Path.Combine`; writable data goes to a mounted volume or S3, never the app folder |
| `HttpRuntime.Cache`, `System.Web.Caching.Cache`, `CacheDependency` | `IMemoryCache` (per instance) or `IDistributedCache` (ElastiCache) when several tasks must agree; file dependencies → explicit invalidation ([aws-managed-services.md](aws-managed-services.md)) |
| `HttpRuntime.AppDomainAppPath`, `HostingEnvironment.MapPath` | `IWebHostEnvironment.ContentRootPath` |
| `HostingEnvironment.QueueBackgroundWorkItem` | `BackgroundService` + a queue ([background-work.md](background-work.md)) |
| `HttpUtility.HtmlEncode` / `UrlEncode` | `System.Net.WebUtility`, `HtmlEncoder.Default`; `HttpUtility.ParseQueryString` still exists in `System.Web.HttpUtility` on .NET |
| `HttpCookie`, `Request.Cookies[...]` | `Request.Cookies["x"]` (string), `Response.Cookies.Append` with `CookieOptions` |
| `Session[...]` | `ISession` (strings and bytes only: serialise objects); store in ElastiCache when there are several tasks ([startup-and-middleware.md](startup-and-middleware.md)) |

## System.Web namespace map

| System.Web type or namespace | ASP.NET Core |
|---|---|
| `System.Web.Caching` (`Cache`, `CacheDependency`) | `IMemoryCache` or `IDistributedCache`. File dependencies → `IChangeToken` |
| `System.Web.Hosting.IRegisteredObject` | `IHostedService` ([background-work.md](background-work.md)) |
| `System.Web.Hosting.VirtualPathProvider` | `IFileProvider` |
| `System.Web.Hosting.HostingEnvironment` | `IWebHostEnvironment` |
| `System.Web.Security` (`FormsAuthentication`, `Membership`, `Roles`) | [auth.md](auth.md) |
| `System.Web.Routing` | Endpoint routing (`MapControllerRoute`, `MapGet`) |
| `System.Web.Optimization` | A build-time bundler ([startup-and-middleware.md](startup-and-middleware.md)) |
| `HttpPostedFileBase`, `Request.Files` | `IFormFile`, from `Request.Form.Files` or a model property |
| `System.Web.Mvc`, `System.Web.Http` | `Microsoft.AspNetCore.Mvc` ([mvc.md](mvc.md), [web-api.md](web-api.md)) |

## Gotchas

- ASP.NET Core has no synchronisation context: code that relied on `HttpContext.Current` after an `await` on another thread now gets null from a static accessor. Pass the context or the values.
- `HttpContext` must not be captured into background work: copy the values first.
- Framework session locks per session; ASP.NET Core session does not. Test double submits.

## Done when

No WEB-SYSTEMWEB-NS / WEB-HTTPCONTEXT-CURRENT residue outside files that use the adapters on purpose (waived, with the removal planned); libraries build for `netstandard2.0` or `net10.0`; every page and endpoint that read request data replays.
