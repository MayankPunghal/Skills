# 00 – Prebuild Cleanup and Bulk Fixes

This file defines the **mandatory pre-compilation operations** for SmartStore.NET migrations from .NET Framework to modern .NET (**.NET 8 or .NET 10**, per the toolkit's target framework).

It ensures that legacy System.Web, EF6, MVC5, and OWIN patterns are sanitized **before** Kiro CLI performs the structured migration process.

---

## Objectives

- Eliminate all `System.Web` dependencies before migration.
- Normalize EF6 attributes and legacy ASP.NET annotations.
- Remove or comment out incompatible constructs.
- Prepare solution for the first `dotnet build` to succeed or fail cleanly.

---

## 1. EF6 and ASP.NET Attribute Cleanup

Remove the following **attributes** across all entity and MVC model classes:

```bash
[Index]
[IndexAttribute]
[AllowHtml]
[assembly: PreApplicationStartMethod]
[UIHint("RichEditor")]
```

These come from `System.ComponentModel.DataAnnotations.Schema` or MVC5.  
They are **not supported** in modern .NET (.NET 8 / .NET 10).

Replacements are handled via Fluent API — see `07-data-access-migration.md`.

---

## 2. Remove or Replace ASP.NET Legacy Namespaces

Perform global replacements using `fs_read` and `fs_write`:

```bash
fs_read -g "using System.Web;" | fs_write --replace "using Microsoft.AspNetCore.Http;"
fs_read -g "using System.Web.Mvc;" | fs_write --replace "using Microsoft.AspNetCore.Mvc;"
fs_read -g "using System.Web.Routing;" | fs_write --replace "using Microsoft.AspNetCore.Routing;"
fs_read -g "using System.Web.Caching;" | fs_write --replace "using Microsoft.Extensions.Caching.Memory;"
fs_read -g "using System.Web.Hosting;" | fs_write --replace "using Microsoft.AspNetCore.Hosting;"
fs_read -g "using System.Web.Security;" | fs_write --replace "using Microsoft.AspNetCore.Identity;"
fs_read -g "using System.Web.Http;" | fs_write --replace "using Microsoft.AspNetCore.Mvc;"
fs_read -g "using System.Web.Http.Filters;" | fs_write --replace "using Microsoft.AspNetCore.Mvc.Filters;"
fs_read -g "using System.Web.Optimization;" | fs_write --replace "using WebOptimizer;"
fs_read -g "using System.Data.Entity;" | fs_write --replace "using Microsoft.EntityFrameworkCore;"
```

Then remove any lines containing:

```bash
System.Web.Compilation
System.Web.UI
System.Web.Modules
System.Web.Handlers
System.Web.Profile
System.Web.Management
```

---

## 3. Add Missing Modern Usings

Ensure these are present where applicable:

```csharp
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.ChangeTracking;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.FileProviders;
```

---

## 4. Comment Out Incompatible Code

The following must be commented out entirely:

- Classes implementing `IRegisteredObject` → replace later with `IHostedService`.
- `CacheDependency` or `VirtualPathProvider` → replace later with `IChangeToken` and `IFileProvider`.
- MVC test fakes:
  - `FakeHttpContext`
  - `FakeHttpRequest`
  - `FakeHttpResponse`
  - `FakeController`
- `GlobalFilterCollection` references.
- `HtmlTextWriter` utilities.
- `AspNetHostingPermissionLevel` references.

> ⚠️ **Do NOT bulk-comment `System.Runtime.Remoting.*` code here.** Remoting has no drop-in replacement, and commenting it out silently removes the app's communication layer. It requires per-usage classification first — see [28-dotnet-remoting-migration.md](./28-dotnet-remoting-migration.md).

Example:

```bash
fs_read -g "FakeHttpContext" | fs_write --comment
fs_read -g "IRegisteredObject" | fs_write --comment
fs_read -g "CacheDependency" | fs_write --comment
fs_read -g "GlobalFilterCollection" | fs_write --comment
fs_read -g "HtmlTextWriter" | fs_write --comment
```

---

## 5. Validate and Clean Project Files (.csproj)

Ensure SDK-style projects and correct target frameworks.

### Add if missing

```xml
<!-- Match the version to the target runtime major: 8.0.x for net8.0, 10.0.x for net10.0 -->
<PackageReference Include="System.ServiceModel.Syndication" Version="8.0.0" />
<PackageReference Include="Microsoft.Extensions.Caching.Memory" Version="8.0.1" />
```

### Remove if present

```xml
<PackageReference Include="NuGet.Core" />
<PackageReference Include="Autofac.Mvc5" />
<PackageReference Include="System.Web.Optimization" />
<PackageReference Include="Microsoft.AspNet.Mvc" />
<PackageReference Include="Microsoft.AspNet.WebApi" />
```

---

## 6. Final Verification Commands

After applying all the above:

```bash
dotnet clean
dotnet build
```

Expected results:

- The number of compilation errors should drop **significantly**.
- All `System.Web`, `EF6`, and MVC5 namespaces should now resolve through modern .NET (8/10) or be safely commented out.

> Proceed to `01-project-file-migration.md` for detailed instructions on migrating legacy .net framework csproj project files.
