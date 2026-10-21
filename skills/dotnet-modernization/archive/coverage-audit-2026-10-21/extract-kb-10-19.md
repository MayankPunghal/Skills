> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Extract KB detectable items 10-19

agent ab421e3818c343ab0

All 10 KB files were read in full (each is under 300 lines, so one read per file covered the whole file). Items are listed per file in the requested format. Credential values are written as <secret>.

10-global-asax-migration.md
- [global-asax] GlobalFilterCollection | comment out usages; use attribute filters or IStartupFilter | blocks-linux-or-build: Y
- [global-asax] Application_Start | move startup logic into builder.Services or app.Use* calls | blocks-linux-or-build: Y
- [global-asax] Global.asax | remove file; centralize pipeline in Program.cs | blocks-linux-or-build: Y

11-configuration-migration.md
- [config-key] web.config | replace with appsettings.json | blocks-linux-or-build: Y
- [config-key] connectionStrings | move to ConnectionStrings section of appsettings.json | blocks-linux-or-build: Y
- [config-key] appSettings | move to AppSettings section of appsettings.json | blocks-linux-or-build: Y
- [config-key] providerName | System.Data.SqlClient provider attribute, dropped in JSON conversion | blocks-linux-or-build: Y
- [config-key] Integrated Security=True | Windows auth in connection string; unusable on Linux | blocks-linux-or-build: Y
- [config-key] Password=<secret> | plaintext DB password; move to user-secrets or environment | blocks-linux-or-build: N
- [api] ConfigurationManager.AppSettings | replace with builder.Configuration["AppSettings:Key"] | blocks-linux-or-build: Y
- [config-key] custom web.config section | replace with typed options via Configure<T> | blocks-linux-or-build: Y
- [config-key] ASPNETCORE_ENVIRONMENT | selects appsettings.{Environment}.json at runtime | blocks-linux-or-build: N
- [config-key] appsettings.Development.json | environment-specific settings file | blocks-linux-or-build: N
- [config-key] appsettings.Production.json | environment-specific settings file | blocks-linux-or-build: N
- [config-key] Logging:LogLevel | Default and Microsoft log levels in appsettings.json | blocks-linux-or-build: N
- [build] dotnet user-secrets | dev-only secret store; init and set values | blocks-linux-or-build: N

12-logging-migration.md
- [pkg] log4net | migrate to Microsoft.Extensions.Logging or Serilog; interim bump only | blocks-linux-or-build: N
- [pkg] log4net 2.0.10 | vulnerable version, NU1902 advisory; upgrade or remove | blocks-linux-or-build: N
- [pkg] NLog | use NLog.Extensions.Logging provider | blocks-linux-or-build: N
- [pkg] NLog.Extensions.Logging | compatible provider bridge for NLog | blocks-linux-or-build: N
- [api] System.Diagnostics.Trace | wrap with ILogger abstraction | blocks-linux-or-build: N
- [pkg] Serilog.AspNetCore | structured logging via builder.Host.UseSerilog | blocks-linux-or-build: N
- [pkg] Serilog.Sinks.Console | Serilog console sink | blocks-linux-or-build: N
- [pkg] Serilog.Sinks.File | Serilog file sink | blocks-linux-or-build: N
- [path] Logs/app.log | file log path; needs writable container path | blocks-linux-or-build: N
- [api] builder.Host.UseSerilog | wire Serilog into the host | blocks-linux-or-build: N
- [api] builder.Logging.ClearProviders | reset default providers in Program.cs | blocks-linux-or-build: N
- [api] builder.Logging.AddConsole | console logging provider | blocks-linux-or-build: N
- [api] builder.Logging.AddDebug | debug logging provider | blocks-linux-or-build: N
- [api] ILogger<T> | inject logger through constructor | blocks-linux-or-build: N
- [config-key] Logging:LogLevel | log levels in appsettings.json | blocks-linux-or-build: N

13-dependency-injection-migration.md
- [pkg] Autofac | replace with built-in DI; optional bridge package | blocks-linux-or-build: N
- [pkg] Autofac.Extensions.DependencyInjection | optional bridge to built-in container | blocks-linux-or-build: N
- [pkg] Ninject | replace with built-in DI container | blocks-linux-or-build: N
- [pkg] Unity | replace with built-in DI; direct mapping supported | blocks-linux-or-build: N
- [api] AddTransient / AddScoped / AddSingleton | target registrations in builder.Services | blocks-linux-or-build: N
- [api] builder.Environment.IsDevelopment | conditional registration by environment | blocks-linux-or-build: N
- [api] controller constructor injection | take services via constructor parameters | blocks-linux-or-build: N

14-middleware-migration.md
- [api] IAppBuilder | OWIN type; replace with WebApplication builder | blocks-linux-or-build: Y
- [api] Configuration(IAppBuilder app) | OWIN Startup entry point; move into Program.cs | blocks-linux-or-build: Y
- [api] CorsOptions.AllowAll | OWIN CORS option; use AddCors and a UseCors policy | blocks-linux-or-build: Y
- [auth] UseOAuthBearerAuthentication | replace with AddAuthentication and AddJwtBearer | blocks-linux-or-build: Y
- [api] UseWebApi(config) | replace with app.MapControllers() | blocks-linux-or-build: Y
- [api] app.UseStageMarker | no equivalent; rely on routing order | blocks-linux-or-build: Y
- [api] OwinMiddleware | base class; replace with RequestDelegate-based middleware | blocks-linux-or-build: Y
- [api] IOwinContext | replace with HttpContext in InvokeAsync | blocks-linux-or-build: Y
- [api] Next.Invoke(context) | replace with _next(context) in InvokeAsync | blocks-linux-or-build: Y
- [api] app.UseMiddleware<T> | register class-based middleware in pipeline | blocks-linux-or-build: N
- [other] middleware order | exception, static files, routing, auth, authz, endpoints | blocks-linux-or-build: N

15-views-static-files-migration.md
- [ns] System.Web.Mvc | Razor base namespace; use Microsoft.AspNetCore.Mvc.Razor | blocks-linux-or-build: Y
- [mvc] System.Web.Mvc.WebViewPage | view base class in .cshtml files; replace | blocks-linux-or-build: Y
- [pkg] Microsoft.AspNetCore.Mvc.Razor.RuntimeCompilation | optional runtime view recompilation package | blocks-linux-or-build: N
- [api] AddRazorRuntimeCompilation | opt-in call on AddControllersWithViews | blocks-linux-or-build: N
- [mvc] /Views folder | .cshtml views stay under Views | blocks-linux-or-build: N
- [path] Content folder | move static content into wwwroot | blocks-linux-or-build: Y
- [path] Scripts folder | move scripts into wwwroot | blocks-linux-or-build: Y
- [path] wwwroot/ | default static root for css, js, images | blocks-linux-or-build: N
- [api] app.UseStaticFiles | serve wwwroot through middleware | blocks-linux-or-build: Y
- [bundling] bundling and minification | replace with Webpack or Vite | blocks-linux-or-build: Y
- [ns] Microsoft.AspNetCore.Mvc.TagHelpers | @addTagHelper import in _ViewImports.cshtml | blocks-linux-or-build: N
- [other] _ViewImports.cshtml | shared Razor directives file | blocks-linux-or-build: N
- [mvc] Html.TextBoxFor | replace with asp-for input tag helper | blocks-linux-or-build: N
- [other] _Layout.cshtml | script include order for client validation | blocks-linux-or-build: N
- [bundling] jquery.validate, jquery.unobtrusive | client validation libs; keep inclusion order | blocks-linux-or-build: N

16-ef6-to-efcore-migration.md
- [ns] System.Data.Entity | replace with Microsoft.EntityFrameworkCore | blocks-linux-or-build: Y
- [ef6] DbContext base("DefaultConnection") | connection-name constructor; use DbContextOptions<T> | blocks-linux-or-build: Y
- [pkg] EntityFramework | remove EF6 package references | blocks-linux-or-build: Y
- [pkg] Microsoft.EntityFrameworkCore.SqlServer | install version matching target: 8.0.x or 10.0.x | blocks-linux-or-build: N
- [pkg] Microsoft.EntityFrameworkCore.Design | design-time package for migrations tooling | blocks-linux-or-build: N
- [pkg] Microsoft.EntityFrameworkCore.Proxies | only needed for lazy-loading proxies | blocks-linux-or-build: N
- [ef6] virtual navigation properties | lazy loading needs virtual navigations and proxies | blocks-linux-or-build: N
- [api] UseLazyLoadingProxies | opt-in lazy loading; requires proxies package | blocks-linux-or-build: N
- [ef6] modelBuilder.Entity<T>().Map(...) | replace with ToTable() in OnModelCreating | blocks-linux-or-build: Y
- [ef6] Add-Migration / Update-Database | EF6 package manager commands; move to dotnet ef | blocks-linux-or-build: N
- [build] dotnet ef migrations add | EF Core CLI replacement for Add-Migration | blocks-linux-or-build: N
- [attr] [Timestamp] | maps to RowVersion; still valid in EF Core | blocks-linux-or-build: N
- [attr] [ConcurrencyCheck] | optimistic concurrency attribute; supported in EF Core | blocks-linux-or-build: N
- [ef6] EF6 interceptors | replace with ISaveChangesInterceptor or IDbCommandInterceptor | blocks-linux-or-build: N
- [ef6] initializer patterns | inventory EF6 initializers; replace with HasData or seeding service | blocks-linux-or-build: N
- [ef6] EXEC dbo.* raw SQL | use FromSqlRaw / ExecuteSqlRaw; keyless DTOs via HasNoKey | blocks-linux-or-build: N
- [ef6] Relational:MaxIdentifierLength | migration annotation adjustment if needed | blocks-linux-or-build: N
- [build] --ignore-changes | baseline empty migration pattern for existing database | blocks-linux-or-build: N
- [api] DbUpdateConcurrencyException | handle using Entries current and database values | blocks-linux-or-build: N
- [api] ExecuteUpdate / ExecuteDelete | bulk operations available in newer EF Core | blocks-linux-or-build: N
- [api] AsNoTracking | use for read-only queries | blocks-linux-or-build: N
- [api] EF.CompileAsyncQuery | compiled queries for hotspots | blocks-linux-or-build: N
- [pkg] Testcontainers | SQL Server integration tests with WebApplicationFactory | blocks-linux-or-build: N

17-dapper-migration.md
- [pkg] Dapper | update to 2.1.0 or later | blocks-linux-or-build: N
- [proj-marker] packages.config | remove legacy reference; use PackageReference | blocks-linux-or-build: Y
- [dapper] ConfigurationManager.ConnectionStrings | replace with builder.Configuration.GetConnectionString | blocks-linux-or-build: Y
- [config-key] DefaultConnection | connection string name read via GetConnectionString | blocks-linux-or-build: N
- [dapper] connection.Query<T> | synchronous call; switch to QueryAsync<T> | blocks-linux-or-build: N
- [dapper] connection.Execute | synchronous call; switch to ExecuteAsync | blocks-linux-or-build: N
- [dapper] TransactionScope | replace with connection.BeginTransaction() | blocks-linux-or-build: Y
- [dapper] SqlMapper.AddTypeHandler | move type handler registration into startup | blocks-linux-or-build: N
- [dapper] IDbConnection | register via AddTransient factory; inject into repositories | blocks-linux-or-build: N
- [dapper] LoggingConnection | IDbConnection wrapper that logs via ILogger | blocks-linux-or-build: N
- [config-key] Server=tcp,1433 | SQL port in connection string; check container networking | blocks-linux-or-build: N

18-nhibernate-migration.md
- [nhibernate] NHibernate | upgrade to 5.4 or later | blocks-linux-or-build: N
- [nhibernate] NHibernate.Mapping.Attributes | attribute mapping package | blocks-linux-or-build: N
- [pkg] System.Data.SqlClient | remove; move ADO.NET usage to Microsoft.Data.SqlClient | blocks-linux-or-build: Y
- [pkg] Microsoft.Data.SqlClient | target driver; v5.1+ for cross-platform TLS | blocks-linux-or-build: N
- [nhibernate] Configuration.Configure() | reads hibernate.cfg.xml; replace with code configuration | blocks-linux-or-build: Y
- [config-key] hibernate.cfg.xml | XML config file; replace with DataBaseIntegration code | blocks-linux-or-build: Y
- [nhibernate] DataBaseIntegration | code-based connection, dialect and driver setup | blocks-linux-or-build: N
- [nhibernate] MsSql2012Dialect | SQL Server dialect; must match target database | blocks-linux-or-build: N
- [nhibernate] PostgreSQL83Dialect | PostgreSQL dialect; must match target database | blocks-linux-or-build: N
- [nhibernate] MicrosoftDataSqlClientDriver | explicit ADO.NET driver in code | blocks-linux-or-build: N
- [nhibernate] NpgsqlDriver | PostgreSQL driver in code | blocks-linux-or-build: N
- [pkg] FluentNHibernate | upgrade to v3.0 or later | blocks-linux-or-build: N
- [attr] [Class] [Id] [Generator] [Property] | NHibernate attribute mapping; verify usage | blocks-linux-or-build: N
- [other] HBM XML mapping files | must be marked Embedded Resource | blocks-linux-or-build: Y
- [path] mapping file paths | case-sensitive on Linux; fix casing | blocks-linux-or-build: Y
- [nhibernate] ISessionFactory | singleton registration in DI | blocks-linux-or-build: N
- [nhibernate] OpenSession | session per request scope | blocks-linux-or-build: N
- [nhibernate] SaveAsync / CommitAsync | async session APIs, NHibernate 5.3 or later | blocks-linux-or-build: N
- [nhibernate] LogProvider.SetCurrentLogProvider | NHibernate logging setup | blocks-linux-or-build: N
- [pkg] FluentMigrator.Runner | schema migration runner; AddFluentMigratorCore | blocks-linux-or-build: N
- [pkg] RoundhousE / DbUp | alternative schema management tools | blocks-linux-or-build: N
- [nhibernate] NHibernateMiddleware | per-request session and transaction middleware | blocks-linux-or-build: N
- [other] UTF-8 XML mappings | encode mapping files as UTF-8 | blocks-linux-or-build: N

19-linux-containerization.md
- [global-asax] Global.asax | must be removed before containerizing | blocks-linux-or-build: Y
- [container] Dockerfile | multi-stage build producing a Linux image | blocks-linux-or-build: N
- [container] mcr.microsoft.com/dotnet/sdk:8.0 | build-stage image; use 10.0 for .NET 10 | blocks-linux-or-build: N
- [container] mcr.microsoft.com/dotnet/aspnet:8.0 | runtime image; use 10.0 for .NET 10 | blocks-linux-or-build: N
- [container] ENV ASPNETCORE_URLS=http://+:8080 | container listen address and port | blocks-linux-or-build: N
- [container] EXPOSE 8080 | container port | blocks-linux-or-build: N
- [container] ENTRYPOINT ["dotnet", "MyApp.dll"] | must match published assembly name | blocks-linux-or-build: N
- [container] docker-compose.yml | app plus SQL Server multi-container setup | blocks-linux-or-build: N
- [container] mcr.microsoft.com/mssql/server:2022-latest | SQL Server container image | blocks-linux-or-build: N
- [config-key] ASPNETCORE_ENVIRONMENT | environment name for config file selection | blocks-linux-or-build: N
- [config-key] ConnectionStrings__DefaultConnection | env-var override using __ separator | blocks-linux-or-build: N
- [config-key] SA_PASSWORD | SQL SA password in compose; supply as <secret> | blocks-linux-or-build: N
- [config-key] ASPNETCORE_Kestrel__Certificates__Default__Password | HTTPS cert password env var; use <secret> | blocks-linux-or-build: N
- [config-key] ASPNETCORE_Kestrel__Certificates__Default__Path | Kestrel certificate path env var | blocks-linux-or-build: N
- [crypto] mycert.pfx | PFX certificate copied into image; source from secret store | blocks-linux-or-build: N
- [path] /https/mycert.pfx | in-container certificate mount path | blocks-linux-or-build: N
- [path] wwwroot/ | static files must be served from here | blocks-linux-or-build: N
- [api] app.UseStaticFiles | required or static files return 404 | blocks-linux-or-build: N
- [api] app.MapGet("/health") | health endpoint returning 200 | blocks-linux-or-build: N
- [container] HEALTHCHECK CMD curl | Docker healthcheck calling curl on port 8080 | blocks-linux-or-build: N
- [build] dotnet publish -c Release -o /app/publish | publish output for container image | blocks-linux-or-build: N
- [proj-marker] src/Presentation/SmartStore.Web/SmartStore.Web.csproj | publish only the web host project | blocks-linux-or-build: N
- [proj-marker] ExcludeFromSingleFile | csproj property to exclude legacy code from output | blocks-linux-or-build: N
- [pkg] Microsoft.EntityFrameworkCore.Design | must not resolve at runtime; bloats image | blocks-linux-or-build: N
- [build] dotnet SmartStore.Web.dll migrate --apply | run migrations from container entrypoint | blocks-linux-or-build: N
- [other] .github/workflows/docker-build.yml | CI workflow that builds and pushes image | blocks-linux-or-build: N
- [other] DOCKER_PASSWORD | CI secret for registry login; never hardcode | blocks-linux-or-build: N
- [container] AWS ECS / Fargate | deploy via ECR and task definitions | blocks-linux-or-build: N
- [other] systemd | on-prem Linux service management with Docker | blocks-linux-or-build: N
- [config-key] Server=db | container DNS hostname in connection string | blocks-linux-or-build: N
- [config-key] DOTNET_ENVIRONMENT | runtime environment setting | blocks-linux-or-build: N
- [path] volume mounts and USER directive | file permissions for mounted volumes | blocks-linux-or-build: N

TOTAL ITEMS: 157
