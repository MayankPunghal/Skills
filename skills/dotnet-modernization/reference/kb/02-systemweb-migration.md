# 02 – System.Web Migration

## Overview

`System.Web` is one of the most significant barriers when upgrading from .NET Framework MVC or Web API to modern .NET (**.NET 8 or .NET 10**).  
ASP.NET Core completely removes `System.Web`, replacing it with lightweight, modular middleware and dependency injection.

This guide helps you migrate common `System.Web` usage patterns to ASP.NET Core equivalents (identical for .NET 8 and .NET 10).

---

## Step 1: Understand the Architectural Shift

| Legacy Component               | ASP.NET Core Equivalent (.NET 8/10)     |
| ------------------------------ | --------------------------------------- |
| `System.Web.HttpApplication`   | `Program.cs` startup pipeline           |
| `Global.asax` events           | `WebApplication` and middleware         |
| `HttpContext.Current`          | `IHttpContextAccessor`                  |
| `HttpModules` / `HttpHandlers` | Middleware components                   |
| `Web.config`                   | `appsettings.json` + code configuration |

---

## Step 2: Replace `HttpContext.Current`

### Before

```csharp
var userAgent = HttpContext.Current.Request.UserAgent;
```

### After

```csharp
public class ExampleController : Controller
{
    public IActionResult Index([FromServices] IHttpContextAccessor accessor)
    {
        var userAgent = accessor.HttpContext?.Request.Headers["User-Agent"];
        return Ok(userAgent);
    }
}
```

Register the accessor in `Program.cs`:

```csharp
builder.Services.AddHttpContextAccessor();
```

---

## Step 3: Missing HttpContext and HttpRequest Classes

- Replace all `HttpContextBase` → `HttpContext`
- Replace all `HttpRequest` → `HttpRequest` from `Microsoft.AspNetCore.Http`
- Ensure `using Microsoft.AspNetCore.Http;` is added.
- Replace `Server.MapPath("~/...")` → inject `IWebHostEnvironment` and combine paths against `ContentRootPath` (app files) or `WebRootPath` (`wwwroot` assets).
- Replace `Request.Files` (`HttpFileCollection` / `HttpPostedFileBase`) → `IFormFile` / `IFormFileCollection` bound from the request.
- Replace `IHostingEnvironment` → `IWebHostEnvironment` (from `Microsoft.AspNetCore.Hosting`). The legacy `IHostingEnvironment` is **obsolete (`CS0618`)** and, when both `Microsoft.AspNetCore.Hosting` and `Microsoft.Extensions.Hosting` are imported, **ambiguous (`CS0104`)** — remove the `Microsoft.Extensions.Hosting` using and keep `Microsoft.AspNetCore.Hosting`. `ContentRootPath`, `WebRootPath`, and `IsDevelopment()` all exist on `IWebHostEnvironment`.

```csharp
public class UploadController : Controller
{
    private readonly IWebHostEnvironment _env;
    public UploadController(IWebHostEnvironment env) => _env = env;

    // Server.MapPath("~/App_Data/orders.json") becomes:
    // Path.Combine(_env.ContentRootPath, "App_Data", "orders.json")

    [HttpPost]
    public IActionResult Upload(IFormFile file)   // was: Request.Files[0] / HttpPostedFileBase
    {
        var target = Path.Combine(_env.ContentRootPath, "App_Data", file.FileName);
        // save file...
        return Ok();
    }
}
```

---

## Step 4: Convert Global.asax

### Before

```csharp
public class Global : HttpApplication
{
    protected void Application_Start()
    {
        RouteConfig.RegisterRoutes(RouteTable.Routes);
    }
}
```

### After

```csharp
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllersWithViews();

var app = builder.Build();
app.UseRouting();
app.MapDefaultControllerRoute();
app.Run();
```

The `App_Start/` helpers collapse into `Program.cs`: `RouteConfig` → `MapControllerRoute`, `FilterConfig` → `AddControllersWithViews(o => o.Filters.Add(...))`, `WebApiConfig` → `AddControllers()` + attribute routing, and `BundleConfig` → a build-time bundler (see [09-bundling-minification.md](./09-bundling-minification.md)).

---

## Step 5: Replace HttpModules and HttpHandlers

### Before

```csharp
public class MyModule : IHttpModule
{
    public void Init(HttpApplication context)
    {
        context.BeginRequest += (src, e) => { /* logic */ };
    }
}
```

### After

```csharp
public class MyMiddleware
{
    private readonly RequestDelegate _next;

    public MyMiddleware(RequestDelegate next) => _next = next;

    public async Task InvokeAsync(HttpContext context)
    {
        // custom logic
        await _next(context);
    }
}
```

Register in the pipeline:

```csharp
app.UseMiddleware<MyMiddleware>();
```

---

## Step 6: Web.config Migration

Replace XML-based configuration with JSON-based settings.

### Before (Web.config)

```xml
<appSettings>
  <add key="ApiKey" value="12345" />
</appSettings>
```

### After (appsettings.json)

```json
{
  "AppSettings": {
    "ApiKey": "12345"
  }
}
```

Access in code:

```csharp
var apiKey = builder.Configuration["AppSettings:ApiKey"];
```

---

## Step 7: Web Forms, Server Controls, and ViewState

ASP.NET Core MVC uses Razor Views — no ViewState or server controls exist.

- Replace `runat="server"` controls with Razor syntax (`@model`, `@Html.TextBoxFor`, etc.).
- Client state is managed via hidden fields, cookies, or APIs.

**Web Forms is a rewrite, not a port.** `Microsoft.AspNet.WebForms` has no modern-.NET equivalent, so each `.aspx` / `.ascx` page is re-authored as an MVC view, a Razor Page, or a Blazor component:
- Code-behind (`Page_Load`, `Button_Click`) → controller actions / Razor Page handlers / Blazor event handlers.
- Server controls (`<asp:GridView>`, `<asp:Repeater>`) → Razor `@foreach` markup, tag helpers, or Blazor components.
- Postbacks / ViewState → explicit form posts (MVC / Razor Pages) or component state + event handlers (Blazor).

This is per-page work with no automated converter — budget accordingly.

---

## Step 8: URL Routing and Rewrite

### Before

```csharp
routes.MapPageRoute("Default", "{controller}/{action}/{id}", "~/index.aspx");
```

### After

```csharp
app.MapControllerRoute(
    name: "default",
    pattern: "{controller=Home}/{action=Index}/{id?}");
```

Use `Microsoft.AspNetCore.Rewrite` for URL rewriting.

---

## Step 9: Session and Caching

| Feature                       | Replacement                           |
| ----------------------------- | ------------------------------------- |
| `HttpContext.Current.Session` | `ISession` (requires middleware)      |
| `HttpRuntime.Cache`           | `IMemoryCache` or `IDistributedCache` |

Register:

```csharp
builder.Services.AddDistributedMemoryCache();
builder.Services.AddSession();
app.UseSession();
```

---

## Step 10: Output Caching

ASP.NET Core (7+, including .NET 8 and .NET 10) includes native output caching:

```csharp
builder.Services.AddOutputCache();
app.UseOutputCache();
```

Annotate endpoints:

```csharp
[OutputCache(Duration = 30)]
public IActionResult Index() => View();
```

---

## Step 11: Validation Checklist

✅ No `System.Web` namespaces remain  
✅ Middleware replaces modules/handlers  
✅ Configuration uses `appsettings.json`  
✅ Global.asax logic migrated to `Program.cs`  
✅ Web Forms pages are rewritten as Razor views/pages or Blazor components (see [25-webforms-to-razor-migration.md](./25-webforms-to-razor-migration.md) / [26-webforms-to-blazor-migration.md](./26-webforms-to-blazor-migration.md)), not left as `.aspx`

---

## See Also

- [03-mvc-migration.md](./03-mvc-migration.md)
- [05-hosting-deployment-migration.md](./05-hosting-deployment-migration.md)
- [10-global-asax-migration.md](./10-global-asax-migration.md)
---

## 12. SmartStore.NET-specific ASP.NET replacements

SmartStore ships a **lot** of code that assumes full `System.Web` + MVC5. In modern .NET (8/10) / ASP.NET Core you must neutralize these:

1. **HttpContextBase → HttpContext**
   - Find: `using System.Web;`, `HttpContextBase`, `HttpRequestBase`, `HttpResponseBase`
   - Replace:
     ```csharp
     using Microsoft.AspNetCore.Http;

     public class SomeService
     {
         private readonly IHttpContextAccessor _httpContextAccessor;
         public SomeService(IHttpContextAccessor httpContextAccessor)
         {
             _httpContextAccessor = httpContextAccessor;
         }

         public HttpContext HttpContext => _httpContextAccessor.HttpContext!;
     }
     ```
   - Then update all usages of `HttpContext.Current` and `new HttpContextWrapper(...)`.

2. **GlobalFilters / MVC5 pipeline hooks**
   - Legacy pattern:
     ```csharp
     using System.Web.Mvc;

     GlobalFilters.Filters.Add(new HandleErrorAttribute());
     ```
   - ASP.NET Core:
     ```csharp
     builder.Services.AddControllersWithViews(options =>
     {
         options.Filters.Add(new Microsoft.AspNetCore.Mvc.Filters.ExceptionFilterAttribute());
     });
     ```

3. **HtmlTextWriter / WebForms dependencies**
   - SmartStore still contains helpers like `HtmlTextWriterExtensions`.
   - If they’re only used by legacy features → comment them out.
   - If really needed, reimplement them using TagHelpers / `IHtmlContent`.

4. **Cache / CacheDependency → IMemoryCache / IDistributedCache**
   - Replace:
     ```csharp
     using System.Web.Caching;
     ```
     with
     ```csharp
     using Microsoft.Extensions.Caching.Memory;
     ```
   - For `CacheDependency` or `VirtualPathProvider`-based invalidation, comment it out and replace with `IChangeToken` (see `Microsoft.Extensions.FileProviders`).

5. **Virtual paths**
   - Replace:
     ```csharp
     public interface IVirtualPathProvider { ... }
     ```
     with:
     ```csharp
     using Microsoft.Extensions.FileProviders;

     public interface IAppFileProvider
     {
         IFileProvider Files { get; }
     }
     ```

6. **IRegisteredObject**
   - Code like:
     ```csharp
     public class AsyncRunner : IRegisteredObject { ... }
     ```
     should be wrapped:
     ```csharp
     // TODO net8: migrate to IHostedService / BackgroundService
     #if false
     public class AsyncRunner : IRegisteredObject { ... }
     #endif
     ```

7. **System.Web.Routing → Endpoint Routing**
   - Convert custom routes to the ASP.NET Core pattern:
     ```csharp
     app.MapControllerRoute(
         name: "default",
         pattern: "{controller=Home}/{action=Index}/{id?}");
     ```

This section exists because SmartStore’s build log showed **dozens** of missing `System.Web.*` types; applying the 7 transformations above eliminates most of the CS0234/CS0246 errors earlier in the pipeline.
