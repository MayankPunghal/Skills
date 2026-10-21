# 27 – Blocked Packages and Build Integrity (.NET 8 / .NET 10)

## Overview
When a project's `TargetFramework` moves to `net8.0`/`net10.0` but legacy `.NET Framework` packages remain, `dotnet restore`/`build` emits a family of `NU****` warnings. Left in place they are not just noise — the packages often don't work at runtime on modern .NET, and the version conflicts they drag in can mask real errors. This file is the **single owner for restore/build-integrity `NU` warnings** (NU1701 framework fallback, NU1605/NU1608 version conflicts, NU1902/NU1903 vulnerabilities). For the *replacement* of a specific package, follow the owning file it links to.

> **Precedence (see the README "Conflict-Resolution Precedence"):** prefer removing/replacing a legacy package over silencing the warning; keep-and-patch only when a full migration is out of scope for this pass.

---

## Step 1: `NU1701` — package restored using a .NET Framework fallback

**Symptom**
```
warning NU1701: Package 'Autofac.Mvc5 4.0.2' was restored using '.NETFramework,Version=v4.6.1, … , v4.8.1'
instead of the project target framework 'net10.0'. This package may not be fully compatible with your project.
```

**Meaning:** the package has **no `net8.0`/`net10.0` (or `netstandard`) target**, so NuGet fell back to its `.NETFramework` assets. On a modern-.NET project this usually means the package is a .NET-Framework-only web-stack component that must be **removed or replaced**, not merely tolerated.

**Common offenders seen in real MVC/Web Forms migrations, and what to do:**

| Package | Action | Owner |
|---|---|---|
| `Microsoft.AspNet.Mvc` (MVC5) | Remove — replaced by `Microsoft.AspNetCore.Mvc` (in the framework) | [03](./03-mvc-migration.md) |
| `Microsoft.AspNet.WebApi.*` | Remove — unified into ASP.NET Core MVC | [04](./04-webapi-migration.md) |
| `Microsoft.AspNet.Razor`, `Microsoft.AspNet.WebPages` | Remove — Razor is built into the Web SDK | [15](./15-views-static-files-migration.md) |
| `Microsoft.Web.Infrastructure` | Remove — no longer needed | [06](./06-package-migrations.md) |
| `System.Web.Optimization` / `WebGrease` | Remove — replaced by a build-time bundler | [09](./09-bundling-minification.md) |
| `Autofac.Mvc5`, `Autofac.WebApi2` | Remove — use built-in DI, or `Autofac.Extensions.DependencyInjection` if retaining Autofac | [13](./13-dependency-injection-migration.md) |
| `Antlr` (3.x, MVC5 bundling dep) | Remove with the bundling stack; if still needed use the maintained `Antlr4` | [06](./06-package-migrations.md) |
| `NuGet.Core` | Remove — no modern equivalent; comment out dependent code | [07](./07-data-access-migration.md) §9 |

**Rule:** if an `NU1701` package has no modern replacement and no code depends on it, delete the `<PackageReference>`. If code depends on it, migrate that code per the owning file first, then delete the reference.

---

## Step 2: `NU1608` / `NU1605` — version conflict and package downgrade

**Symptoms**
```
warning NU1608: Detected package version outside of dependency constraint:
Autofac.Mvc5 4.0.2 requires Autofac (>= 4.0.1 && < 5.0.0) but version Autofac 6.1.0 was resolved.
warning NU1605: Detected package downgrade: System.Diagnostics.DiagnosticSource from 4.7.1 to 4.5.1 …
```

**Meaning:** a **legacy package pins an old version range** of a shared/transitive dependency, which conflicts with (or forces a downgrade of) the version a modern package needs.

**Fix, in order of preference:**
1. **Remove the legacy package causing the constraint** (Step 1). Most `NU1608`/`NU1605` chains disappear once the `NU1701` offender (e.g. `Autofac.Mvc5`) is gone.
2. If the package must stay, **add a direct top-level `<PackageReference>`** to the transitive dependency pinned to the required higher version — a direct reference wins over a transitive one:
   ```xml
   <PackageReference Include="System.Diagnostics.DiagnosticSource" Version="8.0.0" />
   ```
   (Match framework-tied packages to the target runtime major — `8.0.x` / `10.0.x`.)
3. Do **not** "fix" a downgrade by pinning framework-tied packages *below* the target runtime major — that reintroduces `NU1605`. See [08](./08-auth-security-migration.md) for the runtime-major rule.

---

## Step 3: `NU1902` / `NU1903` — vulnerable package advisories

**Symptom**
```
warning NU1902: Package 'log4net' 2.0.10 has a known moderate severity vulnerability …
warning NU1903: Package 'Newtonsoft.Json' 12.0.1 has a known high severity vulnerability …
```

**This file does not re-decide these — it defers to the owning file** (per the README precedence: full migration beats keep-and-patch):

- **`log4net` / `NLog`** → migrate to `Microsoft.Extensions.Logging` per **[12-logging-migration.md](./12-logging-migration.md)** (which removes the vulnerable package entirely). Keep-and-bump only as the interim path documented there.
- **`Newtonsoft.Json`** → prefer `System.Text.Json` per **[06-package-migrations.md](./06-package-migrations.md) Step 6**. If Newtonsoft is retained, bump to a non-vulnerable release (≥ `13.0.1`; the examples in this KB use `13.0.3`).
- **Any other advisory** → bump to the lowest non-vulnerable version of that package, or migrate off it if an owning file recommends a replacement.

---

## Step 4: Validation Checklist

✅ No `NU1701` warnings remain — every .NET-Framework-fallback package is removed or replaced with a modern equivalent  
✅ No `NU1608`/`NU1605` version-conflict or downgrade warnings remain (resolved by removing the legacy package or adding a pinned direct reference at the target runtime major)  
✅ No `NU1902`/`NU1903` advisories remain — vulnerable packages are migrated off (preferred) or bumped to a non-vulnerable version  
✅ `dotnet restore` and `dotnet build` complete with these `NU` warnings cleared (remaining warnings, if any, are intentional and documented)

---

## See Also
- [06-package-migrations.md](./06-package-migrations.md) – NuGet package mappings and removals
- [12-logging-migration.md](./12-logging-migration.md) – owner of the log4net/NLog decision
- [13-dependency-injection-migration.md](./13-dependency-injection-migration.md) – Autofac vs built-in DI
- [01-project-file-migration.md](./01-project-file-migration.md) – SDK-style project and package references
