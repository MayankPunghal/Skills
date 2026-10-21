# DevTx knowledge base: errata

The files in [kb/](kb/README.md) are a verbatim copy of the DevTx knowledge base and stay unchanged. This page lists the places where the KB is wrong, out of date or contradicts itself, with what to do instead. Read it before using the KB as rules (DevTx runs, or Claude as the porting engine). Where this page and the KB disagree, this page and the playbooks win.

## Contents
- [Wrong or out of date](#wrong-or-out-of-date)
- [Contradictions](#contradictions)
- [Unchecked versions and names](#unchecked-versions-and-names)

## Wrong or out of date

| KB (file:line) | The KB says | Do this instead |
|---|---|---|
| 00:23, 00:31, 07 (~122-141), 16:151 | `[Index]` is not supported in modern .NET | EF Core 5+ has `[Index]` (`Microsoft.EntityFrameworkCore.IndexAttribute`); CS0616 usually means a missing `using`. Keep the attribute or use `HasIndex`, and keep the index names. |
| 00:51 | Replace `System.Data.Entity` with `Microsoft.EntityFrameworkCore` everywhere | Map type by type ([raw-sql-and-data-access.md](playbooks/raw-sql-and-data-access.md)); `System.Data.Entity.Validation` and `.Infrastructure` have no one-to-one names. |
| 07:16, 16:201-204 | `Database.SqlQuery<T>` becomes `FromSqlRaw`; keyless DTOs via `Set<Dto>().FromSqlRaw` | `FromSqlRaw` / `FromSqlInterpolated` only for entity types; non-entity results use `Database.SqlQueryRaw<T>` / `SqlQuery<T>` (EF Core 7+). |
| 02:60 | `IHostingEnvironment` and `IHostEnvironment` clash with CS0104 | They have different names and do not clash. Replace the obsolete `IHostingEnvironment` with `IWebHostEnvironment` (or `IHostEnvironment`). |
| 02:304 | `new ExceptionFilterAttribute()` | The class is abstract: derive from it, or implement `IExceptionFilter` / `IAsyncExceptionFilter` ([mvc.md](playbooks/mvc.md)). |
| 03:143 | Areas are discovered by convention | ASP.NET Core needs an explicit area route (`{area:exists}`) and `[Area]` on the controllers ([mvc.md](playbooks/mvc.md)). |
| 06:14 | `dotnet migrate packages.config` | No such command. Use Visual Studio's "Migrate packages.config to PackageReference", Upgrade Assistant, or convert by hand to SDK-style ([build-and-packages.md](playbooks/build-and-packages.md)). |
| 06:190 | Package `WebOptimizer.Core` | The package ID is `LigerShark.WebOptimizer.Core`. |
| 08:252 | Read the antiforgery token from the cookie and send it in the header | **Security.** The cookie holds the cookie token, not the request token. Get the request token from `IAntiforgery.GetAndStoreTokens(HttpContext).RequestToken` (or a deliberately JS-readable request-token cookie you set yourself) and send it in the header ([auth.md](playbooks/auth.md)). |
| 09:122-131 | `MapStaticAssets` is a .NET 10 feature | It shipped in .NET 9 and works on .NET 10. |
| 09:85 vs 09:109-111 | Bundles are "immutable" | The esbuild command shown writes no content hash, so long cache lifetimes serve stale files. Use `asp-append-version` or hashed file names ([startup-and-middleware.md](playbooks/startup-and-middleware.md)). |
| 10:10 | Register global MVC filters with `IStartupFilter` | `IStartupFilter` configures the middleware pipeline. Add global filters with `AddControllersWithViews(o => o.Filters.Add(...))`. |
| 13:13 | `AddSingleton<ICache, MemoryCache>()` | `MemoryCache` does not implement your own `ICache`: register `AddMemoryCache()` and wrap `IMemoryCache` in an adapter. |
| 17:148, 19:60, 19:80, 19:122 | Passwords in `docker run -e` / `ENV` | Secrets come from Secrets Manager as ECS task secrets; never in the image or its history ([linux-and-containers.md](playbooks/linux-and-containers.md)). |
| 19:87 | `SA_PASSWORD=Pass123` | Fails SQL Server's password complexity, so the container exits. Use a strong generated value, outside the file. |
| 19:136, 19:185, 19:230-235 | `HEALTHCHECK CMD curl`; no `USER`; migrations in the entrypoint | The .NET runtime images have no curl; add `USER $APP_UID`; run migrations as a one-off task, not in every container ([linux-readiness.md](linux-readiness.md#what-aws-transform-and-devtx-do-and-do-not-cover)). |
| 20:4 | CoreWCF is "officially supported by Microsoft" | CoreWCF is a .NET Foundation project with a Microsoft support policy for specific versions; use 1.9 (targets .NET 10; 1.8 ends 24 Oct 2026) ([wcf-services.md](playbooks/wcf-services.md)). |
| 20:40 | CoreWCF 1.6.0 | Out of date: use 1.9. |
| 26:53-54 | `protected override async Task OnInitializedAsync() => _orders = await ...;` | Use a block body: `{ _orders = await ...; }`. |
| 28:221, 28:712 | `Uri` is an in-box `MarshalByRefObject` descendant | It is not. Check each type with the compiler, not the list ([ambient-context-and-remoting.md](playbooks/ambient-context-and-remoting.md)). |
| 01:221 | Upgrade Assistant as the current tool | Deprecated by Microsoft (KB 28:674 agrees). Use it only as an optional first mechanical pass ([engines.md](engines.md)). |

## Contradictions

| Topic | KB | This skill |
|---|---|---|
| Library target framework | 01:10, 01:82: libraries always `netstandard2.0` | `net10.0`, unless the library is still shared with .NET Framework callers ([build-and-packages.md](playbooks/build-and-packages.md)) |
| log4net / NLog | 12:6: migrate off them | They can stay as providers behind `ILogger`; moving off is optional ([logging.md](playbooks/logging.md)) |
| Migrations in the entrypoint | 19 | A one-off task ([linux-and-containers.md](playbooks/linux-and-containers.md)) |
| WCF source changes | 20:161 says the source does not change; 20:181 shows a constructor change | Expect small changes; replay the SOAP goldens |
| Remoting artefacts | 28:141 "three artefacts survive" against a table of about eight | Use the classification tree in [ambient-context-and-remoting.md](playbooks/ambient-context-and-remoting.md) |

## Unchecked versions and names

Not verified; check before relying on them: NHibernate driver and dialect names (18:40, 18:55, 18:77) and async versions (18:94 vs 18:206); `LogProvider.SetCurrentLogProvider` (18:169); System.ServiceModel.Primitives 8.1.0 (20:171); the SkiaSharp version (21:36); package pins in 08:23 and 23:24-26; NUnit 4.x claims (24:33, 24:38); `migrations add --ignore-changes` (16:144); Unity "direct mapping" (13:36); the CVE status at 28:600. Pin the versions you test, not the KB's.
