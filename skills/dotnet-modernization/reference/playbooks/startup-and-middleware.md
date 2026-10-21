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

## State

- **In-process session** does not survive several tasks or a restart: `AddStackExchangeRedisCache` (ElastiCache) behind `AddSession`, or remove the dependency. Session stores strings and bytes only.
- `Application[...]` state → a singleton service; anything that must be shared across tasks → the cache or the database.
- Output caching (`OutputCache` directive) → `AddOutputCache` / response caching.
- Data protection keys persisted to a shared store when there is more than one task (cookies, antiforgery, TempData).

## Done when

The app starts in the container with only environment variables and secrets injected; `/health` answers; requests through the ALB see the client IP and scheme; no in-process state where the service runs more than one task.
