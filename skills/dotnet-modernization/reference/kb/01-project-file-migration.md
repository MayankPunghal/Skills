# 01 – Project File and SDK Migration

## Overview
Migrating a .NET Framework 4.5–4.8 MVC or Web API project to modern .NET begins with modernizing the project file.  
Legacy `.csproj` files are verbose, MSBuild-heavy XML configurations.  
Modern .NET introduces **SDK-style projects**, which are simpler, more portable, and designed for cross-platform builds.

**Key Principle:** 
- **Application projects** (executables) target specific runtime versions like `net8.0` or `net10.0`
- **Library projects** target `netstandard2.0` for maximum compatibility across .NET Framework 4.6.1+, .NET Core 2.0+, and modern .NET

> **Target framework (.NET 8 or .NET 10):** Use whichever TFM the toolkit is upgrading to — `net8.0` for .NET 8 or `net10.0` for .NET 10. The `net8.0` values in the examples below are placeholders; substitute `net10.0` when targeting .NET 10. Framework-tied package versions (`Microsoft.AspNetCore.*`, `Microsoft.Extensions.*`) must match the target runtime major (`8.0.x` for .NET 8, `10.0.x` for .NET 10).

---

## Step 1: Remove Legacy Metadata
### Example: Old `.csproj` (before)
```xml
<Project ToolsVersion="15.0" DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion>
    <OutputType>Library</OutputType>
    <AssemblyName>MyApp</AssemblyName>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="System.Web" />
    <Reference Include="System.Net.Http" />
  </ItemGroup>
</Project>
```

### Example: New `.csproj` (after - Application)
```xml
<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <OutputType>Exe</OutputType>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>

  <ItemGroup>
    <!-- Use the version matching the target runtime: 8.0.x for net8.0, 10.0.x for net10.0 -->
    <PackageReference Include="Microsoft.AspNetCore.Mvc.Razor.RuntimeCompilation" Version="8.0.0" />
  </ItemGroup>
</Project>
```

### Example: New `.csproj` (after - Library)
```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.0</TargetFramework>
    <Nullable>enable</Nullable>
    <LangVersion>latest</LangVersion>
  </PropertyGroup>
</Project>
```

### Key Changes
- Remove `ToolsVersion`, `Import`, and explicit `Reference Include="System.*"` elements — these are resolved by the SDK.
- Replace `<TargetFrameworkVersion>` with `<TargetFramework>`.
- Remove any `<HintPath>` references to GAC assemblies.
- Use `Microsoft.NET.Sdk.Web` for MVC/Web API projects.

---

## Step 2: Use the Right SDK and Target Framework

### SDK Selection
| App Type | SDK |
|-----------|-----|
| MVC / Razor | `Microsoft.NET.Sdk.Web` |
| Web API | `Microsoft.NET.Sdk.Web` |
| Shared Libraries | `Microsoft.NET.Sdk` |
| Unit Tests | `Microsoft.NET.Sdk` |

### Target Framework Selection
| Project Type | Target Framework | Reason |
|--------------|------------------|--------|
| **Application Projects** (MVC, Web API, Console with `<OutputType>Exe</OutputType>` or `<OutputType>WinExe</OutputType>`) | `net8.0` or `net10.0` | Applications target specific runtime versions |
| **Library Projects** (`<OutputType>Library</OutputType>` or no OutputType) | `netstandard2.0` | Maximum compatibility across .NET Framework 4.6.1+, .NET Core 2.0+, and modern .NET |
| **Test Projects** | Same as application being tested | Tests should target the same framework as the application |

### Example: Library Project
```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.0</TargetFramework>
    <Nullable>enable</Nullable>
    <LangVersion>latest</LangVersion>
  </PropertyGroup>
</Project>
```

### Example: Application Project
```xml
<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>
</Project>
```

### Detection Rules
- If `<OutputType>Exe</OutputType>` or `<OutputType>WinExe</OutputType>` → Application → Use `net8.0` or `net10.0`
- If `<OutputType>Library</OutputType>` or no `<OutputType>` → Library → Use `netstandard2.0`
- If project references `Microsoft.NET.Test.Sdk` → Test Project → Match application target framework

---

## Step 3: Migrate NuGet Packages
Legacy projects use `packages.config`; modern projects use inline `<PackageReference>` items.

### Before
```xml
<packages>
  <package id="Newtonsoft.Json" version="10.0.3" targetFramework="net472" />
</packages>
```

### After
```xml
<ItemGroup>
  <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
</ItemGroup>
```

### Steps
1. Delete `packages.config` and the `/packages` folder.
2. Run:
   ```bash
   dotnet restore
   ```
3. Confirm packages are restored with:
   ```bash
   dotnet list package
   ```

---

## Step 4: Enable Multi-Targeting (Optional)
If you need to maintain both .NET Framework and modern .NET temporarily:

### For Application Projects
```xml
<TargetFrameworks>net8.0;net472</TargetFrameworks>
```

### For Library Projects
```xml
<TargetFrameworks>netstandard2.0;net472</TargetFrameworks>
```

Wrap code conditionally:
```csharp
#if NETSTANDARD2_0
    // .NET Standard 2.0 compatible code
#elif NET8_0_OR_GREATER
    using Microsoft.AspNetCore.Builder;
#else
    using System.Web;
#endif
```

---

## Step 5: Centralize Shared Configurations
Use `Directory.Build.props` for solution-wide settings.

Example:
```xml
<Project>
  <PropertyGroup>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <LangVersion>latest</LangVersion>
  </PropertyGroup>
</Project>
```

This reduces duplication and enforces consistent compiler options.

---

## Step 6: Clean Up Redundant Properties
Remove or simplify:
- `<AssemblyName>` (optional if it matches folder name)
- `<RootNamespace>` (optional)
- `<OutputPath>` (use default `bin/Debug/net8.0` — or `bin/Debug/net10.0` for .NET 10 — for apps, `bin/Debug/netstandard2.0` for libraries)
- `<TargetFrameworkProfile>` (obsolete)

Set `<GenerateAssemblyInfo>` based on the symptom (these are the two branches of the *same* knob — apply exactly one):
- **Assembly metadata missing** after conversion → `<GenerateAssemblyInfo>true</GenerateAssemblyInfo>`.
- **`CS0579` "Duplicate 'System.Reflection.Assembly*Attribute'"** → the SDK is auto-generating assembly attributes that clash with an existing `Properties/AssemblyInfo.cs`. Fix with **`<GenerateAssemblyInfo>false</GenerateAssemblyInfo>`** (keep the existing file) **or** delete `Properties/AssemblyInfo.cs` (let the SDK generate them) — do one, not both.

**Important for Library Projects:**
- Keep `<OutputType>Library</OutputType>` explicit if migrating from old format
- Ensure `<TargetFramework>netstandard2.0</TargetFramework>` is set correctly

---

## Step 7: Use the Right Tools

### Option 1: try-convert
Install the official conversion tool:
```bash
dotnet tool install -g try-convert
```
Run conversion:
```bash
try-convert -w ./MyLegacyApp.sln
```
This updates `.csproj` files to SDK-style automatically.

### Option 2: Upgrade Assistant
Microsoft’s guided migration CLI:
```bash
dotnet tool install -g upgrade-assistant
upgrade-assistant upgrade ./MyApp.sln
```
It automates project conversion, package upgrades, and analyzer integration.

---

## Step 8: Validate the Migration
After conversion, run:
```bash
dotnet build
dotnet list package --outdated
```

Fix any:
- Missing NuGet references
- Framework-specific dependencies (e.g., `System.Web`)
- API usage warnings (using `dotnet build /warnaserror`)

---

## Step 9: Resolve NETSDK1022 (Duplicate Default Items)

`NETSDK1022` — *"Duplicate 'Content' items were included. The .NET SDK includes 'Content' items from your project directory by default."* — is one of the most common errors immediately after converting to an SDK-style project. It also appears for `Compile`, `EmbeddedResource`, and `None` items with the same wording.

**Cause:** SDK-style projects automatically include items from the project directory using default globs (controlled by `EnableDefaultCompileItems`, `EnableDefaultContentItems`, `EnableDefaultEmbeddedResourceItems`, `EnableDefaultNoneItems`, all `true` by default). Legacy `.csproj` files — and the output of `try-convert` — often still list those same files explicitly, so each one is now included twice.

### Before (duplicates the default glob)
```xml
<ItemGroup>
  <Compile Include="Controllers\HomeController.cs" />
  <Content Include="wwwroot\css\site.css" />
  <Content Include="appsettings.json" />
</ItemGroup>
```

### After (preferred fix — delete the explicit items)
Let the SDK glob pick them up. In most projects the entire `<ItemGroup>` of explicit `Compile`/`Content` items can simply be removed:
```xml
<!-- No explicit Compile/Content items: the SDK includes them automatically. -->
```

### Setting metadata without re-including
If you only listed an item to attach metadata (for example `CopyToOutputDirectory`), use `Update` — not `Include` — so you modify the already-globbed item instead of adding a duplicate:
```xml
<ItemGroup>
  <Content Update="appsettings.json">
    <CopyToOutputDirectory>PreserveNewest</CopyToOutputDirectory>
  </Content>
</ItemGroup>
```
Use `Remove` to exclude a file the default glob would otherwise pick up:
```xml
<ItemGroup>
  <Content Remove="notes.txt" />
</ItemGroup>
```

### Escape hatch — disable the default glob
Only when a project genuinely needs a fully hand-curated item list, turn off the relevant default and then list items explicitly with `Include`:
```xml
<PropertyGroup>
  <EnableDefaultContentItems>false</EnableDefaultContentItems>
  <!-- also available: EnableDefaultCompileItems, EnableDefaultEmbeddedResourceItems, EnableDefaultNoneItems -->
</PropertyGroup>
```
Prefer deleting the duplicate `Include` items over disabling the glob — disabling it is easy to get subtly wrong (files silently dropped from the build).

---

## Step 10: Common Pitfalls and Fixes

| Issue | Cause | Fix |
|-------|--------|-----|
| `System.Web` missing | Legacy ASP.NET dependency | Will be migrated to ASP.NET Core abstractions |
| Build errors on `packages.config` | Legacy format | Use `<PackageReference>` instead |
| MSBuild import errors | Custom `.targets` or `.props` | Inline into SDK project or remove |
| Missing assembly info | Disabled auto-generation | Add `<GenerateAssemblyInfo>true</GenerateAssemblyInfo>` |
| `CS0579` duplicate assembly attributes | SDK auto-gen clashes with existing `Properties/AssemblyInfo.cs` | Set `<GenerateAssemblyInfo>false</GenerateAssemblyInfo>` **or** delete `Properties/AssemblyInfo.cs` (not both) |
| `NETSDK1022` duplicate Content/Compile items | Explicit items duplicate the SDK default glob | Delete the explicit `Include` items; use `Update` for metadata, or `EnableDefault*Items=false` to hand-curate |

---

## Step 11: Final Validation Checklist
✅ Project builds with `dotnet build`  
✅ No references to `System.Web` (for application projects)  
✅ Application projects use `Microsoft.NET.Sdk.Web` and target `net8.0` or `net10.0`  
✅ Library projects use `Microsoft.NET.Sdk` and target `netstandard2.0`  
✅ Test projects target same framework as application  
✅ Package references modernized  
✅ Nullable and implicit usings enabled (applications)  
✅ LangVersion set to `latest` (libraries)  
✅ Runs on Linux with `dotnet run` (applications)

---

## See Also
- [02-systemweb-migration.md](./02-systemweb-migration.md)
- [05-hosting-deployment-migration.md](./05-hosting-deployment-migration.md)
- [06-package-migrations.md](./06-package-migrations.md)
