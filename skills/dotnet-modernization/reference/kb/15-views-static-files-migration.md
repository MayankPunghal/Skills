# 15 – Razor Views and Static Files Migration

## Overview
Razor views continue to work in modern .NET (.NET 8 and .NET 10) with improved performance and tooling. Static files (CSS, JS, images) are now served through middleware instead of IIS-managed handlers.

---

## Step 1: Razor View Migration

### Before
- `.cshtml` in `/Views` folder
- Uses `System.Web.Mvc.WebViewPage`
- Compiled by Razor engine at runtime

### After
- `.cshtml` files remain under `/Views`
- Uses `Microsoft.AspNetCore.Mvc.Razor`
- Optional runtime recompilation via package

```bash
dotnet add package Microsoft.AspNetCore.Mvc.Razor.RuntimeCompilation
```

Enable in `Program.cs`:
```csharp
builder.Services.AddControllersWithViews().AddRazorRuntimeCompilation();
```

---

## Step 2: Layouts and Partials

Use `_ViewImports.cshtml` for shared directives:

```razor
@using MyApp.Models
@addTagHelper *, Microsoft.AspNetCore.Mvc.TagHelpers
```

---

## Step 3: Static Files

Enable static file serving:

```csharp
app.UseStaticFiles();
```

Default path is `wwwroot/`.  
Move `Content` and `Scripts` folders there.

---

## Step 4: Bundling and Minification

Use modern tools like Webpack or Vite.

Example folder structure:
```
wwwroot/
  css/
  js/
  images/
```

---

## Step 5: Tag Helpers

Replace old HTML helpers with tag helpers where possible.

Before:
```razor
@Html.TextBoxFor(m => m.Name)
```

After:
```razor
<input asp-for="Name" class="form-control" />
```

---

## Step 6: Validation

Client-side validation uses the same `jquery.validate` and `jquery.unobtrusive` libraries, but ensure proper inclusion order via `_Layout.cshtml`.

---

## See Also
- [09-bundling-minification.md](./09-bundling-minification.md)
- [14-middleware-migration.md](./14-middleware-migration.md)
