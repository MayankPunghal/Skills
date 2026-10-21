# 03 – MVC Migration Guide

## Overview
Migrating from ASP.NET MVC 4/5 to ASP.NET Core MVC involves replatforming to a fully modular and cross-platform framework.  
This guide covers key differences and step-by-step adjustments.

---

## Step 1: Project Setup
Install MVC dependencies:
```bash
dotnet add package Microsoft.AspNetCore.Mvc.Razor.RuntimeCompilation
dotnet add package Microsoft.AspNetCore.Mvc.TagHelpers
```

Add to `Program.cs`:
```csharp
builder.Services.AddControllersWithViews()
                .AddRazorRuntimeCompilation();
var app = builder.Build();
app.UseStaticFiles();
app.UseRouting();
app.MapDefaultControllerRoute();
app.Run();
```

---

## Step 2: Controllers
Controllers inherit from `Controller` in `Microsoft.AspNetCore.Mvc`.

### Before
```csharp
using System.Web.Mvc;
public class HomeController : Controller
{
    public ActionResult Index() => View();
}
```
### After
```csharp
using Microsoft.AspNetCore.Mvc;
public class HomeController : Controller
{
    public IActionResult Index() => View();
}
```

`ActionResult` and `IActionResult` are interchangeable; prefer `IActionResult`.

---

## Step 3: Filters
Replace `System.Web.Mvc.Filters` with ASP.NET Core equivalents:
```csharp
public class LogActionFilter : IActionFilter
{
    public void OnActionExecuting(ActionExecutingContext context) { }
    public void OnActionExecuted(ActionExecutedContext context) { }
}
```
Register globally:
```csharp
builder.Services.AddControllersWithViews(options =>
{
    options.Filters.Add<LogActionFilter>();
});
```

---

## Step 4: Model Binding
Model binding is more flexible and supports DI.

### Before
```csharp
public ActionResult Submit(MyModel model) { }
```
### After
```csharp
[HttpPost]
public IActionResult Submit([FromForm] MyModel model) { }
```

Use `[FromBody]`, `[FromQuery]`, `[FromRoute]`, `[FromHeader]` as needed.

---

## Step 5: Routing
Routes are attribute-based or defined globally.

### Before
```csharp
routes.MapRoute("Default", "{controller}/{action}/{id}", new { id = UrlParameter.Optional });
```
### After
```csharp
app.MapControllerRoute("default", "{controller=Home}/{action=Index}/{id?}");
```

Attribute routing:
```csharp
[Route("api/[controller]")]
public class ProductsController : Controller { }
```

---

## Step 6: TempData, ViewBag, ViewData
These concepts remain but are implemented differently.  
Avoid heavy use — prefer strongly-typed models.

```csharp
TempData["Message"] = "Saved";
ViewData["User"] = "John";
ViewBag.Role = "Admin";
```

All require `services.AddControllersWithViews()`.

---

## Step 7: Filters and Authorization
Replace `[Authorize(Roles="Admin")]` with Core’s `[Authorize]` (same syntax).  
Configure authentication/authorization in `Program.cs`.

---

## Step 8: Razor Views
- Razor syntax (`.cshtml`) remains compatible.  
- Remove `@using System.Web.Mvc`.  
- Add tag helpers via:
  ```cshtml
  @addTagHelper *, Microsoft.AspNetCore.Mvc.TagHelpers
  ```

---

## Step 9: Areas
Area structure is unchanged, but registration is automatic.

### Before
`AreaRegistration.RegisterAllAreas();`
### After
No action required — discovered by convention.

---

## Step 10: Validation Checklist
✅ Controllers use `Microsoft.AspNetCore.Mvc`  
✅ Views use Razor syntax  
✅ Routing uses endpoint routing  
✅ Filters converted to Core equivalents  
✅ No `System.Web.Mvc` references  

---

## See Also
- [04-webapi-migration.md](./04-webapi-migration.md)
- [08-auth-security-migration.md](./08-auth-security-migration.md)
