# 06 – NuGet Package and Dependency Migration

## Overview
Migrating packages is critical for modernizing MVC and Web API projects to modern .NET (**.NET 8 or .NET 10**, per the toolkit's target). Legacy projects often rely on outdated or incompatible assemblies (e.g., `System.Web.Mvc`, `Microsoft.Owin`, `Newtonsoft.Json`, etc.).  
> **Package versions:** framework-tied packages (`Microsoft.AspNetCore.*`, `Microsoft.EntityFrameworkCore.*`, `Microsoft.Extensions.*`) must match the target runtime major — use `8.0.x` for .NET 8 or `10.0.x` for .NET 10. The `8.0.x` versions shown below are examples for .NET 8. Third-party packages (Newtonsoft.Json, Dapper, NHibernate, Autofac, WebOptimizer, etc.) are runtime-independent — use their own latest compatible version.
This guide covers identifying, replacing, and upgrading them safely.

---

## Step 1: Remove Legacy `packages.config`
Delete `packages.config` and migrate all dependencies to `<PackageReference>` format.

```bash
dotnet migrate packages.config
```

or manually move entries into your `.csproj` file.

Example:
```xml
<ItemGroup>
  <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
  <!-- Match to target runtime major: 8.0.x for net8.0, 10.0.x for net10.0 -->
  <PackageReference Include="Microsoft.AspNetCore.Mvc.NewtonsoftJson" Version="8.0.0" />
</ItemGroup>
```

---

## Step 2: Common Package Mappings

| Old Package | New Package | Notes |
|--------------|-------------|-------|
| `System.Web.Mvc` | `Microsoft.AspNetCore.Mvc` | Core MVC framework |
| `Microsoft.AspNet.WebApi.Core` | `Microsoft.AspNetCore.Mvc.Core` | Unified MVC + Web API stack |
| `Microsoft.Owin.*` | `Microsoft.AspNetCore.*` | Middleware-based Core pipeline |
| `Microsoft.Owin.Security.*` | `Microsoft.AspNetCore.Authentication.*` | Modern authentication framework |
| `System.Net.Http.Formatting` | `Microsoft.AspNetCore.Mvc.Formatters.*` | Use built-in JSON or XML formatters |
| `Microsoft.AspNet.Web.Optimization` | — | Use middleware or bundlers like Webpack |
| `EntityFramework` | `Microsoft.EntityFrameworkCore` | Modern EF Core ORM |
| `Dapper` | `Dapper` | Works without change |
| `NHibernate` | `NHibernate` | Works with modern .NET (8/10); ensure latest version |

---

## Step 3: Entity Framework 6 to EF Core Migration

1. **Install EF Core**  
   ```bash
   dotnet add package Microsoft.EntityFrameworkCore.SqlServer
   dotnet add package Microsoft.EntityFrameworkCore.Tools
   ```

2. **Update `DbContext`**  
   Replace `System.Data.Entity` with:
   ```csharp
   using Microsoft.EntityFrameworkCore;
   ```

3. **Connection Configuration**
   ```csharp
   builder.Services.AddDbContext<AppDbContext>(options =>
       options.UseSqlServer(builder.Configuration.GetConnectionString("DefaultConnection")));
   ```

4. **Migrations**
   ```bash
   dotnet ef migrations add InitialCreate
   dotnet ef database update
   ```

---

## Step 4: Dapper Migration
Dapper works in modern .NET (8/10) without modification. Just ensure:
```bash
dotnet add package Dapper
dotnet add package Microsoft.Data.SqlClient
```

Replace old `System.Data.SqlClient` with `Microsoft.Data.SqlClient` in imports.

---

## Step 5: NHibernate Migration
NHibernate >= 5.4 supports modern .NET (.NET 8 and .NET 10).

### Install
```bash
dotnet add package NHibernate
```

### Configuration
Update configuration to use `Microsoft.Data.SqlClient` and ensure session factory initialization runs under async-safe context.

---

## Step 6: Newtonsoft.Json and System.Text.Json
Use `System.Text.Json` by default; it’s faster and integrated.

If backward compatibility with old JSON behaviors is required:
```bash
dotnet add package Microsoft.AspNetCore.Mvc.NewtonsoftJson
```
Then:
```csharp
builder.Services.AddControllers().AddNewtonsoftJson();
```

---

## Step 7: Validation
Check outdated or conflicting packages:
```bash
dotnet list package --outdated
dotnet restore
```

Remove any `System.Web.*` assemblies manually if still referenced.

---

## Step 8: Common Pitfalls

| Symptom | Cause | Fix |
|----------|--------|-----|
| `System.Web` not found | Legacy dependency | Replace with ASP.NET Core equivalents |
| `EntityFramework` namespace missing | EF6 deprecated | Use EF Core |
| JSON serialization mismatch | Default serializer change | Use `AddNewtonsoftJson()` |

---

## See Also
- [03-mvc-migration.md](./03-mvc-migration.md)
- [07-data-access-migration.md](./07-data-access-migration.md)
- [12-logging-migration.md](./12-logging-migration.md)
---

## 7. HtmlSanitizer / AngleSharp conflict resolution

Your build output showed:

> HtmlSanitizer 8.1.870 requires AngleSharp (= 0.17.1) but AngleSharp 1.1.0 was resolved.

This is a **classic** NuGet diamond dependency when migrating old MVC apps. Fix it with **one** of these strategies:

1. **Pin AngleSharp to 0.17.1** (quickest)
   ```xml
   <ItemGroup>
     <PackageReference Include="AngleSharp" Version="0.17.1" />
     <PackageReference Include="AngleSharp.Css" Version="0.17.0" />
   </ItemGroup>
   ```

2. **Or upgrade HtmlSanitizer** (preferred if the app actually uses it)
   - Check the HtmlSanitizer release that supports AngleSharp 1.x
   - Bump HtmlSanitizer and remove explicit AngleSharp references

3. **Or drop HtmlSanitizer** (if only used in legacy MVC helpers)
   - Some legacy features used it only to protect rich-text fields rendered by System.Web MVC  
   - If you’ve moved to ASP.NET Core TagHelpers or a different editor, remove it.

---

## 8. Remove legacy ASP.NET 4.x packages

From the same build log we saw these assemblies implicitly referenced:

- `Autofac.Mvc5`
- `Microsoft.AspNet.Mvc` 5.x
- `Microsoft.AspNet.WebApi.*`
- `System.Web.Optimization`
- `NuGet.Core`

These must be removed or replaced:

```xml
<ItemGroup>
  <!-- REMOVE: -->
  <!--<PackageReference Include="Autofac.Mvc5" Version="*"/>-->
  <!--<PackageReference Include="System.Web.Optimization" Version="*"/>-->
  <!--<PackageReference Include="Microsoft.AspNet.Mvc" Version="*"/>-->
  <!--<PackageReference Include="Microsoft.AspNet.WebApi" Version="*"/>-->
  <!--<PackageReference Include="NuGet.Core" Version="*"/>-->

  <!-- ADD (framework-tied packages must match the target runtime major: 8.0.x for net8.0, 10.0.x for net10.0): -->
  <!-- Autofac.Extensions.DependencyInjection ONLY if retaining Autofac modules; otherwise prefer built-in DI (see 13-dependency-injection-migration.md) -->
  <PackageReference Include="Autofac.Extensions.DependencyInjection" Version="9.0.0" />
  <PackageReference Include="Microsoft.AspNetCore.Mvc.Razor.RuntimeCompilation" Version="8.0.1" />
  <PackageReference Include="WebOptimizer.Core" Version="3.2.0" />
</ItemGroup>
```

---

## 9. EF / data helper packages

If you migrated EF6 → EF Core, make sure these are present **somewhere** in the solution:

```xml
<!-- EF Core ships in lockstep with the runtime: use 8.0.x for net8.0, 10.0.x for net10.0 -->
<ItemGroup>
  <PackageReference Include="Microsoft.EntityFrameworkCore" Version="8.0.4" />
  <PackageReference Include="Microsoft.EntityFrameworkCore.Relational" Version="8.0.4" />
  <PackageReference Include="Microsoft.EntityFrameworkCore.Design" Version="8.0.4">
    <PrivateAssets>all</PrivateAssets>
  </PackageReference>
  <PackageReference Include="Microsoft.EntityFrameworkCore.Tools" Version="8.0.4">
    <PrivateAssets>all</PrivateAssets>
  </PackageReference>
</ItemGroup>
```

This removes the need for references to `System.Data.Entity` and fixes many `DbEntityEntry`/`ObjectContext`-related missing types.
