> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Extract KB detectable items 00-09

agent afa49c9e2568ea93b

00-prebuild-cleanup-and-bulk-fixes.md
- [attr] [Index] / [IndexAttribute] | remove EF6 index attributes; use Fluent HasIndex | blocks-linux-or-build: Y
- [attr] [AllowHtml] | remove MVC5 attribute, unsupported on .NET 8/10 | blocks-linux-or-build: Y
- [attr] [assembly: PreApplicationStartMethod] | remove legacy assembly-level attribute | blocks-linux-or-build: Y
- [attr] [UIHint("RichEditor")] | remove MVC5 attribute | blocks-linux-or-build: Y
- [ns] using System.Web; | replace with Microsoft.AspNetCore.Http | blocks-linux-or-build: Y
- [ns] using System.Web.Mvc; | replace with Microsoft.AspNetCore.Mvc | blocks-linux-or-build: Y
- [ns] using System.Web.Routing; | replace with Microsoft.AspNetCore.Routing | blocks-linux-or-build: Y
- [ns] using System.Web.Caching; | replace with Microsoft.Extensions.Caching.Memory | blocks-linux-or-build: Y
- [ns] using System.Web.Hosting; | replace with Microsoft.AspNetCore.Hosting | blocks-linux-or-build: Y
- [ns] using System.Web.Security; | replace with Microsoft.AspNetCore.Identity | blocks-linux-or-build: Y
- [ns] using System.Web.Http; | replace with Microsoft.AspNetCore.Mvc | blocks-linux-or-build: Y
- [ns] using System.Web.Http.Filters; | replace with Microsoft.AspNetCore.Mvc.Filters | blocks-linux-or-build: Y
- [ns] using System.Web.Optimization; | replace with WebOptimizer namespace | blocks-linux-or-build: Y
- [ns] using System.Data.Entity; | replace with Microsoft.EntityFrameworkCore | blocks-linux-or-build: Y
- [ns] System.Web.Compilation / UI / Modules / Handlers / Profile / Management | delete lines containing these namespaces | blocks-linux-or-build: Y
- [api] IRegisteredObject | comment out; replace later with IHostedService | blocks-linux-or-build: Y
- [api] CacheDependency | comment out; replace with IChangeToken | blocks-linux-or-build: Y
- [api] VirtualPathProvider | comment out; replace with IChangeToken or IFileProvider | blocks-linux-or-build: Y
- [api] FakeHttpContext / FakeHttpRequest / FakeHttpResponse / FakeController | comment out MVC test fakes | blocks-linux-or-build: Y
- [api] GlobalFilterCollection | comment out references | blocks-linux-or-build: Y
- [api] HtmlTextWriter | comment out utilities | blocks-linux-or-build: Y
- [api] AspNetHostingPermissionLevel | comment out references | blocks-linux-or-build: Y
- [wcf-asmx-remoting] System.Runtime.Remoting.* | do not bulk-comment; classify each usage first | blocks-linux-or-build: Y
- [pkg] NuGet.Core | remove PackageReference | blocks-linux-or-build: Y
- [pkg] Autofac.Mvc5 | remove PackageReference | blocks-linux-or-build: Y
- [pkg] System.Web.Optimization | remove PackageReference | blocks-linux-or-build: Y
- [pkg] Microsoft.AspNet.Mvc / Microsoft.AspNet.WebApi | remove PackageReference | blocks-linux-or-build: Y

01-project-file-migration.md
- [proj-marker] ToolsVersion="15.0" | remove legacy attribute; SDK resolves tooling | blocks-linux-or-build: Y
- [proj-marker] xmlns="http://schemas.microsoft.com/developer/msbuild/2003" | legacy non-SDK csproj header; convert to SDK style | blocks-linux-or-build: Y
- [proj-marker] TargetFrameworkVersion v4.x | replace with TargetFramework net8.0 or net10.0 | blocks-linux-or-build: Y
- [proj-marker] TargetFrameworkProfile | remove obsolete property | blocks-linux-or-build: Y
- [proj-marker] Reference Include="System.Web" | remove; SDK resolves framework references | blocks-linux-or-build: Y
- [proj-marker] HintPath to GAC assemblies | remove | blocks-linux-or-build: Y
- [proj-marker] Import / custom .targets / .props | inline into SDK project or remove | blocks-linux-or-build: Y
- [proj-marker] Reference Include="System.Net.Http" | remove explicit framework reference | blocks-linux-or-build: N
- [proj-marker] Compile Include / Content Include (explicit items) | delete; SDK default globs include them | blocks-linux-or-build: Y
- [build] NETSDK1022 | duplicate Content, Compile, EmbeddedResource or None items; delete Include or use Update | blocks-linux-or-build: Y
- [proj-marker] Content Update / Content Remove | set metadata or exclude without duplicating | blocks-linux-or-build: N
- [proj-marker] EnableDefaultContentItems (and other EnableDefault*Items) | escape hatch; disable only for hand-curated lists | blocks-linux-or-build: N
- [build] CS0579 Duplicate 'System.Reflection.Assembly*Attribute' | set GenerateAssemblyInfo false or delete AssemblyInfo.cs | blocks-linux-or-build: Y
- [proj-marker] GenerateAssemblyInfo | set true when assembly metadata is missing | blocks-linux-or-build: N
- [proj-marker] OutputType Exe / WinExe / Library | app (net8.0/net10.0) vs library (netstandard2.0) choice | blocks-linux-or-build: N
- [proj-marker] Microsoft.NET.Test.Sdk | test project; match application target framework | blocks-linux-or-build: N
- [proj-marker] TargetFrameworks net8.0;net472 | temporary multi-targeting only | blocks-linux-or-build: N
- [proj-marker] #if NETSTANDARD2_0 / NET8_0_OR_GREATER / #else using System.Web | conditional compile guards for legacy code | blocks-linux-or-build: N
- [pkg] packages.config and /packages folder | delete; move to PackageReference | blocks-linux-or-build: Y
- [proj-marker] Sdk="Microsoft.NET.Sdk.Web" | use for MVC and Web API applications | blocks-linux-or-build: N

02-systemweb-migration.md
- [api] HttpContext.Current | replace with IHttpContextAccessor | blocks-linux-or-build: Y
- [api] HttpContextBase / HttpRequestBase / HttpResponseBase / HttpContextWrapper | replace with HttpContext, HttpRequest, HttpResponse | blocks-linux-or-build: Y
- [api] Server.MapPath("~/...") | use IWebHostEnvironment ContentRootPath or WebRootPath | blocks-linux-or-build: Y
- [api] Request.Files / HttpFileCollection / HttpPostedFileBase | use IFormFile or IFormFileCollection | blocks-linux-or-build: Y
- [api] IHostingEnvironment | obsolete CS0618; use IWebHostEnvironment | blocks-linux-or-build: Y
- [ns] Microsoft.Extensions.Hosting using beside Microsoft.AspNetCore.Hosting | CS0104 ambiguity; remove one using | blocks-linux-or-build: Y
- [global-asax] Global.asax / HttpApplication / Application_Start | move startup into Program.cs | blocks-linux-or-build: Y
- [api] RouteConfig.RegisterRoutes / RouteTable.Routes | replace with MapControllerRoute | blocks-linux-or-build: Y
- [api] FilterConfig / GlobalFilters.Filters.Add | register via AddControllersWithViews options | blocks-linux-or-build: Y
- [api] WebApiConfig / BundleConfig | replace with AddControllers and build-time bundler | blocks-linux-or-build: Y
- [api] IHttpModule / HttpApplication.BeginRequest | replace with middleware class | blocks-linux-or-build: Y
- [api] IHttpHandler / HttpHandlers | replace with middleware or endpoint | blocks-linux-or-build: Y
- [api] IRegisteredObject | wrap in #if false; use IHostedService or BackgroundService | blocks-linux-or-build: Y
- [api] HtmlTextWriter / HtmlTextWriterExtensions | comment out or reimplement with TagHelpers | blocks-linux-or-build: Y
- [api] HttpRuntime.Cache | replace with IMemoryCache or IDistributedCache | blocks-linux-or-build: Y
- [api] CacheDependency | replace with IChangeToken | blocks-linux-or-build: Y
- [api] IVirtualPathProvider | replace with IFileProvider-based interface | blocks-linux-or-build: Y
- [api] HandleErrorAttribute | replace with ASP.NET Core ExceptionFilterAttribute | blocks-linux-or-build: Y
- [api] HttpContext.Current.Session | replace with ISession after AddSession and UseSession | blocks-linux-or-build: Y
- [webforms] runat="server" | rewrite as Razor markup or Blazor components | blocks-linux-or-build: Y
- [webforms] .aspx / .ascx pages / Microsoft.AspNet.WebForms | re-author as views, Razor Pages or Blazor | blocks-linux-or-build: Y
- [webforms] Page_Load / Button_Click code-behind | convert to actions, Razor Page handlers or event handlers | blocks-linux-or-build: Y
- [webforms] asp:GridView / asp:Repeater | replace with Razor foreach or tag helpers | blocks-linux-or-build: Y
- [webforms] ViewState / postbacks | replace with explicit form posts or component state | blocks-linux-or-build: Y
- [webforms] MapPageRoute / index.aspx | replace with MapControllerRoute | blocks-linux-or-build: Y
- [config-key] appSettings / web.config | move to appsettings.json and code configuration | blocks-linux-or-build: N

03-mvc-migration.md
- [ns] using System.Web.Mvc; | replace with Microsoft.AspNetCore.Mvc | blocks-linux-or-build: Y
- [mvc] ActionResult return type | prefer IActionResult; interchangeable with ActionResult | blocks-linux-or-build: N
- [ns] System.Web.Mvc.Filters | replace with Microsoft.AspNetCore.Mvc.Filters | blocks-linux-or-build: Y
- [mvc] IActionFilter / ActionExecutingContext / ActionExecutedContext | same names; confirm Core namespace | blocks-linux-or-build: N
- [mvc] Submit(MyModel model) | add [FromForm] or other From* binding attribute | blocks-linux-or-build: N
- [attr] [FromBody] / [FromQuery] / [FromRoute] / [FromHeader] | ASP.NET Core binding source attributes | blocks-linux-or-build: N
- [api] routes.MapRoute(..., new { id = UrlParameter.Optional }) | replace with MapControllerRoute and {id?} | blocks-linux-or-build: Y
- [attr] [Route("api/[controller]")] | attribute routing on controllers | blocks-linux-or-build: N
- [mvc] @using System.Web.Mvc | remove from Razor views | blocks-linux-or-build: Y
- [mvc] @addTagHelper *, Microsoft.AspNetCore.Mvc.TagHelpers | register tag helpers in _ViewImports | blocks-linux-or-build: N
- [api] AreaRegistration.RegisterAllAreas() | delete; areas discovered by convention | blocks-linux-or-build: Y
- [attr] [Authorize(Roles="Admin")] | same syntax; configure auth in Program.cs | blocks-linux-or-build: N
- [api] ViewBag / ViewData / TempData | still supported; avoid heavy use | blocks-linux-or-build: N
- [api] AddControllersWithViews | required service registration in Program.cs | blocks-linux-or-build: N

04-webapi-migration.md
- [ns] using System.Web.Http; | replace with Microsoft.AspNetCore.Mvc | blocks-linux-or-build: Y
- [api] ApiController base class | replace with ControllerBase | blocks-linux-or-build: Y
- [api] IHttpActionResult | replace with IActionResult | blocks-linux-or-build: Y
- [pkg] System.Web.Http* packages | remove all PackageReference entries | blocks-linux-or-build: Y
- [api] GlobalConfiguration.Configuration.DependencyResolver | remove; use built-in DI | blocks-linux-or-build: Y
- [ns] System.Web.Http.Filters | replace with Microsoft.AspNetCore.Mvc.Filters | blocks-linux-or-build: Y
- [api] ExceptionHandler / ExceptionHandlerContext / InternalServerErrorResult | replace with UseExceptionHandler or custom middleware | blocks-linux-or-build: Y
- [attr] [RoutePrefix] | merge into single controller [Route] | blocks-linux-or-build: Y
- [attr] [Route("{id}")] on action | use [HttpGet("{id}")] on the action | blocks-linux-or-build: Y
- [pkg] Microsoft.AspNetCore.Mvc.Versioning | deprecated; use Asp.Versioning.* packages | blocks-linux-or-build: Y
- [api] AddApiVersioning / ApiVersion | use Asp.Versioning namespace | blocks-linux-or-build: N
- [pkg] Microsoft.AspNetCore.Mvc.NewtonsoftJson | add only for Newtonsoft-dependent behavior | blocks-linux-or-build: N
- [api] AddNewtonsoftJson / ReferenceLoopHandling | Newtonsoft-specific settings; otherwise System.Text.Json | blocks-linux-or-build: N
- [api] JObject / custom converters | signal Newtonsoft dependency | blocks-linux-or-build: N

05-hosting-deployment-migration.md
- [global-asax] Global.asax / Application_Start | replace with Program.cs top-level statements | blocks-linux-or-build: Y
- [api] Startup.ConfigureServices | move calls to builder.Services | blocks-linux-or-build: Y
- [api] Startup.Configure(IApplicationBuilder, IWebHostEnvironment) | move middleware after builder.Build | blocks-linux-or-build: Y
- [api] WebHost.CreateDefaultBuilder / UseStartup<Startup> | obsolete ASPDEPR008; use WebApplication.CreateBuilder | blocks-linux-or-build: Y
- [api] IWebHost / IWebHostBuilder.Build() | obsolete ASPDEPR008; remove | blocks-linux-or-build: Y
- [build] ASPDEPR008 | obsolete-API diagnostic for the WebHost pattern | blocks-linux-or-build: Y
- [api] IVirtualPathProvider / IVirtualFolder | obsolete; use IWebHostEnvironment.WebRootFileProvider or IFileProvider | blocks-linux-or-build: Y
- [api] System.Diagnostics.Trace | replace with built-in ILogger | blocks-linux-or-build: Y
- [api] ConfigurationManager.AppSettings | replace with IConfiguration | blocks-linux-or-build: Y
- [config-key] web.config | replace with appsettings.json and environment variables | blocks-linux-or-build: N
- [config-key] Kestrel:Endpoints:Http:Url | Kestrel endpoint configuration in appsettings.json | blocks-linux-or-build: N
- [config-key] ConnectionStrings__DefaultConnection | environment variable form of connection string | blocks-linux-or-build: N
- [build] mcr.microsoft.com/dotnet/aspnet:8.0 | container base image tag must match target runtime | blocks-linux-or-build: N
- [build] dotnet publish -r linux-x64 | Linux publish target for self-hosted deployment | blocks-linux-or-build: N
- [api] UseForwardedHeaders | needed behind IIS or Nginx reverse proxy | blocks-linux-or-build: N

06-package-migrations.md
- [pkg] System.Web.Mvc | replace with Microsoft.AspNetCore.Mvc | blocks-linux-or-build: Y
- [pkg] Microsoft.AspNet.WebApi.Core | replace with Microsoft.AspNetCore.Mvc.Core | blocks-linux-or-build: Y
- [pkg] Microsoft.Owin.* | replace with Microsoft.AspNetCore.* middleware | blocks-linux-or-build: Y
- [pkg] Microsoft.Owin.Security.* | replace with Microsoft.AspNetCore.Authentication.* | blocks-linux-or-build: Y
- [pkg] Microsoft.Owin.Host.SystemWeb | remove; OWIN host on System.Web | blocks-linux-or-build: Y
- [pkg] System.Net.Http.Formatting | replace with built-in Microsoft.AspNetCore.Mvc.Formatters | blocks-linux-or-build: Y
- [pkg] Microsoft.AspNet.Web.Optimization | remove; use build-time bundler | blocks-linux-or-build: Y
- [pkg] EntityFramework | replace with Microsoft.EntityFrameworkCore | blocks-linux-or-build: Y
- [ef6] System.Data.Entity | DbContext namespace; replace with Microsoft.EntityFrameworkCore | blocks-linux-or-build: Y
- [pkg] Autofac.Mvc5 | remove PackageReference | blocks-linux-or-build: Y
- [pkg] System.Web.Optimization | remove PackageReference | blocks-linux-or-build: Y
- [pkg] Microsoft.AspNet.Mvc / Microsoft.AspNet.WebApi.* | remove PackageReference | blocks-linux-or-build: Y
- [pkg] NuGet.Core | remove PackageReference | blocks-linux-or-build: Y
- [pkg] System.Web (assembly reference) | remove manually if still referenced | blocks-linux-or-build: Y
- [pkg] System.Data.SqlClient | replace with Microsoft.Data.SqlClient in imports | blocks-linux-or-build: Y
- [build] HtmlSanitizer 8.1.870 requires AngleSharp (= 0.17.1) | NuGet diamond conflict; pin AngleSharp or upgrade HtmlSanitizer | blocks-linux-or-build: Y
- [pkg] packages.config | delete; migrate entries to PackageReference | blocks-linux-or-build: Y
- [other] dotnet migrate packages.config | tool command; manual move also works | blocks-linux-or-build: N
- [pkg] Dapper | works unchanged; use latest compatible version | blocks-linux-or-build: N
- [pkg] NHibernate | version 5.4 or later supports net8.0 and net10.0 | blocks-linux-or-build: N
- [pkg] Microsoft.EntityFrameworkCore.SqlServer / Tools / Design | add EF Core packages matching runtime major | blocks-linux-or-build: N
- [pkg] Autofac.Extensions.DependencyInjection | add only when retaining Autofac modules | blocks-linux-or-build: N
- [pkg] WebOptimizer.Core | add as bundler replacement when needed | blocks-linux-or-build: N

07-data-access-migration.md
- [ef6] System.Data.Entity | replace with Microsoft.EntityFrameworkCore | blocks-linux-or-build: Y
- [ef6] Database.SqlQuery<T> | replace with FromSqlRaw or FromSqlInterpolated | blocks-linux-or-build: Y
- [attr] [Index] / [Index("...")] / IndexAttribute | delete; define index in OnModelCreating HasIndex | blocks-linux-or-build: Y
- [ef6] DbEntityEntry | replace with EntityEntry from context.Entry | blocks-linux-or-build: Y
- [ef6] ObjectContext | replace with EF Core equivalents | blocks-linux-or-build: Y
- [ef6] SmartStore.Core.Data.IDbContext / IDbContext | update interface to EF Core types | blocks-linux-or-build: Y
- [ns] System.Data.SqlServerCe | delete using and provider; namespace does not exist | blocks-linux-or-build: Y
- [config-key] SQL CE provider entries in web.config | delete provider registration | blocks-linux-or-build: Y
- [api] NuGet.Core / Packaging.disabled | comment out implementation; keep interfaces | blocks-linux-or-build: Y
- [ns] System.Data.SqlClient | replace with Microsoft.Data.SqlClient | blocks-linux-or-build: Y
- [dapper] Dapper QueryAsync<T> | works unchanged; prefer async APIs | blocks-linux-or-build: N
- [dapper] ConfigurationManager.ConnectionStrings | replace with IConfiguration | blocks-linux-or-build: Y
- [nhibernate] cfg.DataBaseIntegration | NHibernate setup; provider moves to Microsoft.Data.SqlClient | blocks-linux-or-build: N
- [nhibernate] MsSql2012Dialect / db.Dialect<T>() | SQL Server dialect selection | blocks-linux-or-build: N
- [nhibernate] BuildSessionFactory | session factory init; run under async-safe context | blocks-linux-or-build: N
- [config-key] ConnectionStrings:DefaultConnection | move to appsettings.json; no secrets in source | blocks-linux-or-build: N
- [ef6] Password=<secret> in connection string | move to configuration or secret store | blocks-linux-or-build: N
- [ns] System.ComponentModel.DataAnnotations.Schema | remove using once no longer needed | blocks-linux-or-build: N

08-auth-security-migration.md
- [pkg] Microsoft.Owin / Microsoft.Owin.Security / .Cookies / .OAuth | replace with Microsoft.AspNetCore.Authentication.* | blocks-linux-or-build: Y
- [pkg] Microsoft.Owin.Host.SystemWeb | remove | blocks-linux-or-build: Y
- [pkg] Microsoft.AspNet.Identity.EntityFramework / Identity.Owin | replace with Microsoft.AspNetCore.Identity.EntityFrameworkCore | blocks-linux-or-build: Y
- [auth] Owin.IAppBuilder / ConfigureAuth(IAppBuilder) | replace with AddAuthentication in Program.cs | blocks-linux-or-build: Y
- [auth] Startup.Auth.cs | delete; partial Startup auth wiring is OWIN-only | blocks-linux-or-build: Y
- [auth] app.UseCookieAuthentication(CookieAuthenticationOptions) | replace with AddCookie or ConfigureApplicationCookie | blocks-linux-or-build: Y
- [auth] DefaultAuthenticationTypes.ApplicationCookie | remove OWIN auth-type constant | blocks-linux-or-build: Y
- [auth] CookieAuthenticationProvider / OnValidateIdentity | OWIN hook; rewrite as ASP.NET Core wiring | blocks-linux-or-build: Y
- [auth] SecurityStampValidator.OnValidateIdentity | OWIN validation hook; rewrite as Core config | blocks-linux-or-build: Y
- [auth] IdentityUser / IdentityDbContext<T> (Microsoft.AspNet.Identity.EntityFramework) | use Microsoft.AspNetCore.Identity namespaces | blocks-linux-or-build: Y
- [auth] DbContext : base("ContosoConnection") | constructor must take DbContextOptions<T> | blocks-linux-or-build: Y
- [auth] HttpContext.GetOwinContext().GetUserManager<T>() | constructor-inject UserManager and SignInManager | blocks-linux-or-build: Y
- [auth] UserManager.FindAsync(email, password) | use SignInManager.PasswordSignInAsync | blocks-linux-or-build: Y
- [auth] app.UseOAuthBearerAuthentication(OAuthBearerAuthenticationOptions) | replace with AddJwtBearer | blocks-linux-or-build: Y
- [auth] AntiForgeryConfig.UniqueClaimTypeIdentifier | remove; no ASP.NET Core equivalent | blocks-linux-or-build: Y
- [attr] [ValidateAntiForgeryToken] | optional: AutoValidateAntiforgeryToken globally | blocks-linux-or-build: N
- [mvc] @Html.AntiForgeryToken() / Html.BeginForm() | use form tag helpers | blocks-linux-or-build: N
- [auth] ClaimsAuthenticationManager / Authenticate override | replace with IClaimsTransformation | blocks-linux-or-build: Y
- [auth] UserManager.CreateIdentityAsync | replace with IUserClaimsPrincipalFactory | blocks-linux-or-build: Y
- [auth] ClaimsPrincipal.Current | absent in ASP.NET Core; use User | blocks-linux-or-build: Y
- [config-key] system.webServer modules add name="Saml2" | remove HttpModule registration | blocks-linux-or-build: Y
- [config-key] sustainsys.saml2 section | move to AddSaml2 options in Program.cs | blocks-linux-or-build: Y
- [pkg] Sustainsys.Saml2.HttpModule / Sustainsys.Saml2.Owin | replace with Sustainsys.Saml2.AspNetCore2 | blocks-linux-or-build: Y
- [crypto] X509CertificateLoader.LoadPkcs12FromFile | .NET 9+ only; use new X509Certificate2 on net8.0 | blocks-linux-or-build: Y
- [crypto] signingCertificate fileName | certificate file path; move to config or secret store | blocks-linux-or-build: N
- [config-key] Saml2:SpCertPath / Saml2:SpCertPassword | certificate path and password; keep in <secret> store | blocks-linux-or-build: N
- [config-key] Auth:Authority / Auth:Audience | JWT bearer settings from configuration | blocks-linux-or-build: N
- [other] AspNetUsers.LockoutEndDateUtc | rename to LockoutEnd and convert to datetimeoffset | blocks-linux-or-build: N
- [other] NormalizedUserName / NormalizedEmail / NormalizedName | backfill existing rows before cutover | blocks-linux-or-build: N

09-bundling-minification.md
- [pkg] Microsoft.AspNet.Web.Optimization | remove; no ASP.NET Core successor | blocks-linux-or-build: Y
- [api] BundleConfig.RegisterBundles | delete App_Start/BundleConfig.cs | blocks-linux-or-build: Y
- [bundling] ScriptBundle / StyleBundle | replace with esbuild, webpack, vite or rollup output | blocks-linux-or-build: Y
- [bundling] BundleTable.Bundles | remove registration from Global.asax.cs | blocks-linux-or-build: Y
- [bundling] @Scripts.Render("~/bundles/...") | replace with script tag to wwwroot/dist file | blocks-linux-or-build: Y
- [bundling] @Styles.Render("~/Content/css") | replace with link tag to dist bundle | blocks-linux-or-build: Y
- [bundling] dotnet bundle (BundlerMinifier) | unmaintained; do not adopt for new migration | blocks-linux-or-build: N
- [bundling] asp-append-version | cache-busting attribute on link or script tags | blocks-linux-or-build: N
- [build] Target Name="EsbuildBundle" BeforeTargets="Build" | run npm install and build before dotnet build | blocks-linux-or-build: N
- [build] Exec Command="npm run build" | MSBuild step invoking npm bundler | blocks-linux-or-build: N
- [config-key] package.json "scripts" build | esbuild bundling command | blocks-linux-or-build: N
- [api] UseStaticFiles(StaticFileOptions) | serve dist with immutable cache headers on .bundle. files | blocks-linux-or-build: N
- [api] MapStaticAssets | .NET 10 fingerprinting and gzip/brotli serving; replaces UseStaticFiles | blocks-linux-or-build: N
- [api] AddResponseCompression / UseResponseCompression | .NET 8 in-process compression; not automatic | blocks-linux-or-build: N

TOTAL ITEMS: 200
