# Playbook: startup, middleware, session and hosting

**Rules:** CFG-WEBCONFIG-APP (residue); LNX-HOST-*, LNX-WEB-GLOBAL-ASAX, LNX-WEB-SESSION-INPROC, LNX-NET-* (Linux readiness).
**Engines:** DevTx KB 05, 10, 13, 14 and AWS Transform create `Program.cs` and move Global.asax and middleware; Claude checks ordering, hosting behind the ALB and state.

## Program.cs

1. **Global.asax events → startup and middleware:** `Application_Start` → service registration and startup code in `Program.cs`; `Application_BeginRequest`/`EndRequest` → a middleware; `Application_Error` → `UseExceptionHandler` + logging; `Session_Start` → first access in a middleware or service.
2. **Static singletons and service locators → DI.** Register what the code `new`s today; lifetimes: per request = scoped, shared = singleton (thread-safe), cheap = transient. No `BuildServiceProvider()` inside registration.
3. **Configuration** from `appsettings.json` + environment variables + Parameter Store / Secrets Manager ([config-and-secrets.md](config-and-secrets.md)).
4. **Middleware order** (the usual one): forwarded headers → exception handler → HSTS (only where the app terminates TLS) → static files → routing → CORS → authentication → authorization → session → endpoints. Every web.config `<httpModules>`/`<modules>` entry and `<httpHandlers>` maps to one of these or to an endpoint ([http-handlers-and-modules.md](http-handlers-and-modules.md)).
5. **Health endpoint**: `app.MapHealthChecks("/health")` with checks for the database and caches the app cannot run without (the container gate and the ALB call it).

## Behind the AWS load balancer

- `UseForwardedHeaders` with `XForwardedFor | XForwardedProto`, `KnownNetworks`/`KnownProxies` cleared or set to the VPC range; without it client IPs, `https` redirects and absolute URLs are wrong.
- TLS ends at the ALB: no `UseHttpsRedirection` loop; listen on `8080` (`ASPNETCORE_HTTP_PORTS`), the default of the .NET 8+ images.
- Request limits moved from web.config (`maxRequestLength`, `maxAllowedContentLength`, `executionTimeout`) → Kestrel `Limits` and `FormOptions`; the ALB idle timeout (60 s default) bounds long requests.
- IIS URL Rewrite rules → `UseRewriter` or the ALB listener rules; custom error pages → `UseStatusCodePagesWithReExecute`.

## IIS settings in web.config

Kestrel reads none of the `system.web` / `system.webServer` sections. Go through the old web.config section by section; each line below is one Linux readiness check (`LNX-HOST-IIS-*`, `LNX-WEB-*`, `LNX-CFG-SYSTEM-NET-SECTION`, `LNX-CUL-WEBCONFIG-GLOBALIZATION`).

| web.config | Re-create as |
|---|---|
| `<authorization>` deny rules, `<location path>` | Authorization policies (`[Authorize]`, `RequireAuthorization()`, a fallback policy); test anonymous access to every path the rules protected |
| `<httpProtocol><customHeaders>`, `removeServerHeader` | Header middleware or CloudFront response headers; `AddServerHeader = false` |
| `<ipSecurity>` | Security groups, ALB listener rules or AWS WAF IP sets |
| `<requestFiltering>` (verbs, extensions, hidden segments) | Routing constraints or AWS WAF rules |
| `maxAllowedContentLength`, `maxRequestLength`, `maxQueryString` | `KestrelServerOptions.Limits`, `[RequestSizeLimit]`, `FormOptions.MultipartBodyLengthLimit` |
| `executionTimeout`, `requestTimeout` | A queue and worker for long work; ALB idle timeout; `RequestTimeouts` middleware |
| `<staticContent>` (`<mimeMap>`, `<clientCache>`), `<defaultDocument>` | `FileExtensionContentTypeProvider`, `OnPrepareResponse`, `UseDefaultFiles`; or S3 behind CloudFront |
| `<urlCompression>`, `<httpCompression>` | CloudFront compression or `UseResponseCompression` (the ALB does not compress) |
| `<httpErrors>`, `<customErrors>` | `UseExceptionHandler`, `UseStatusCodePagesWithReExecute` |
| `<modules>`, `<handlers>`, `<httpModules>`, `<httpHandlers>` | Middleware and endpoints ([http-handlers-and-modules.md](http-handlers-and-modules.md)) |
| `<sessionState>` with mode `StateServer` or `SQLServer` | `AddSession` over `IDistributedCache` (ElastiCache or DynamoDB); old session data does not carry over |
| `<globalization culture=...>` | `UseRequestLocalization` with an explicit default culture |
| `<system.net>` (`mailSettings`, `defaultProxy`, `connectionManagement`) | Values from configuration set in code (SmtpClient, `HTTP(S)_PROXY`, `MaxConnectionsPerServer`), or Amazon SES for mail |
| `applicationInitialization`, app pool recycling | Warm-up in start-up with an ECS health check grace period; memory watched per task |
| Sub-application path (`/app`) | `UsePathBase` from configuration and an ALB path rule |

ASP.NET Core has no request validation: pages that relied on it (or switched it off with `ValidateRequest="false"`) need output encoding checked and, where HTML is allowed, a sanitiser.

## Static assets and bundles

The ASP.NET bundler (`System.Web.Optimization`, `BundleConfig`, `Scripts.Render`) has no port. Replace it with a build step:

1. **Pick one bundler and record the choice.** esbuild is the usual pick for plain JavaScript and CSS. Use webpack, Vite or Rollup when the front end already uses them. The old `dotnet bundle` tool is not maintained.
2. **Build the bundles into `wwwroot/dist/`** as part of the build or the publish. Commit the source, not generated bundles, unless the pipeline needs them.
3. **Reference the bundles** with `asp-append-version="true"`. On .NET 10, `MapStaticAssets` replaces `UseStaticFiles` for these files and gives fingerprinted paths to reference.
4. **Cache by type.** Fingerprinted files can be cached for a long time, and `MapStaticAssets` sets that caching and pre-compresses the files (gzip and brotli). Files that keep a fixed name need a short `Cache-Control` set in `StaticFileOptions.OnPrepareResponse`, or users run old scripts after a deploy.

## State

- **In-process session** does not survive several tasks or a restart: `AddStackExchangeRedisCache` (ElastiCache) behind `AddSession`, or remove the dependency. Session stores strings and bytes only.
- `Application[...]` state → a singleton service; anything that must be shared across tasks → the cache or the database.
- Output caching (`OutputCache` directive) → `AddOutputCache` / response caching.
- Data protection keys persisted to a shared store when there is more than one task (cookies, antiforgery, TempData).

## Done when

The app starts in the container with only environment variables and secrets injected; `/health` answers; requests through the ALB see the client IP and scheme; no in-process state where the service runs more than one task.
