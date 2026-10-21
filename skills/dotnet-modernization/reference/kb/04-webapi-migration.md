# 04 – Web API Migration Guide

## Overview
ASP.NET Web API merges into ASP.NET Core MVC — unified under a single model.  
This guide focuses on migrating your REST controllers and configuration.

---

## Step 1: Replace NuGet Packages
Remove all `System.Web.Http*` packages.

Add:
```bash
dotnet add package Microsoft.AspNetCore.Mvc.Core
dotnet add package Microsoft.AspNetCore.Mvc.NewtonsoftJson
```

---

## Step 2: Controllers
### Before
```csharp
using System.Web.Http;

public class ProductsController : ApiController
{
    public IHttpActionResult Get(int id) => Ok(_repo.Get(id));
}
```
### After
```csharp
using Microsoft.AspNetCore.Mvc;

[ApiController]
[Route("api/[controller]")]
public class ProductsController : ControllerBase
{
    [HttpGet("{id}")]
    public IActionResult Get(int id) => Ok(_repo.Get(id));
}
```

Use `ControllerBase` for pure APIs.

---

## Step 3: JSON Serialization
**`System.Text.Json` is the default** (faster, built-in) — see [06-package-migrations.md](./06-package-migrations.md) Step 6. Only add `Microsoft.AspNetCore.Mvc.NewtonsoftJson` when the API depends on Newtonsoft-specific behavior (e.g. reference-loop handling, custom converters, `JObject`), then configure it in `Program.cs`:
```csharp
builder.Services.AddControllers()
    .AddNewtonsoftJson(options =>
        options.SerializerSettings.ReferenceLoopHandling = Newtonsoft.Json.ReferenceLoopHandling.Ignore);
```

---

## Step 4: Attribute Routing
Mandatory for APIs. Example:
```csharp
[ApiController]
[Route("api/[controller]")]
public class UsersController : ControllerBase
{
    [HttpGet("{id}")]
    public IActionResult GetUser(int id) => Ok();
}
```

Web API 2's `[RoutePrefix("api/orders")]` on the controller (plus `[Route("{id}")]` on the action) collapses into a single `[Route("api/orders")]` on the controller and `[HttpGet("{id}")]` on the action.

---

## Step 5: Filters
`System.Web.Http.Filters` → `Microsoft.AspNetCore.Mvc.Filters`.

Example:
```csharp
public class ApiLoggingFilter : IActionFilter
{
    public void OnActionExecuting(ActionExecutingContext context) { }
    public void OnActionExecuted(ActionExecutedContext context) { }
}
```

Register globally:
```csharp
builder.Services.AddControllers(options => options.Filters.Add<ApiLoggingFilter>());
```

---

## Step 6: Exception Handling
### Before
```csharp
public class GlobalExceptionHandler : ExceptionHandler
{
    public override void Handle(ExceptionHandlerContext context) => context.Result = new InternalServerErrorResult();
}
```
### After
Use middleware:
```csharp
app.UseExceptionHandler("/error");
```

Or create a custom one:
```csharp
public class ApiExceptionMiddleware
{
    private readonly RequestDelegate _next;
    public async Task InvokeAsync(HttpContext context)
    {
        try { await _next(context); }
        catch (Exception ex)
        {
            context.Response.StatusCode = 500;
            await context.Response.WriteAsJsonAsync(new { error = ex.Message });
        }
    }
}
```

Register:
```csharp
app.UseMiddleware<ApiExceptionMiddleware>();
```

---

## Step 7: Dependency Injection
ASP.NET Core has built-in DI — no `GlobalConfiguration.Configuration.DependencyResolver` needed.

```csharp
builder.Services.AddScoped<IProductService, ProductService>();
```

---

## Step 8: Versioning (Optional)
Use the maintained **`Asp.Versioning.*`** packages. The older `Microsoft.AspNetCore.Mvc.Versioning` package is **deprecated** — do not use it on .NET 8 or .NET 10. These packages are runtime-independent; use the latest version on either target.
```bash
dotnet add package Asp.Versioning.Mvc
dotnet add package Asp.Versioning.Mvc.ApiExplorer
```

Configure (note the `Asp.Versioning` namespace):
```csharp
using Asp.Versioning;

builder.Services.AddApiVersioning(opt =>
{
    opt.AssumeDefaultVersionWhenUnspecified = true;
    opt.DefaultApiVersion = new ApiVersion(1, 0);
    opt.ReportApiVersions = true;
})
.AddMvc();
```

---

## Step 9: Validation Checklist
✅ Uses `[ApiController]` and `ControllerBase`  
✅ Attribute routing applied  
✅ JSON serialization configured  
✅ Filters and exception handling converted  
✅ DI used for dependencies  

---

## See Also
- [03-mvc-migration.md](./03-mvc-migration.md)
- [11-configuration-migration.md](./11-configuration-migration.md)
