# .NET Framework → .NET 8 / .NET 10 Migration Knowledge Base

**Scope:** ASP.NET MVC 5, ASP.NET Web API 2, and ASP.NET Web Forms apps, OWIN-only middleware, Razor views, Linux containers, data access via EF6, Dapper, NHibernate, deployment to ASP.NET Core on modern .NET (**.NET 8 or .NET 10**, whichever the toolkit is targeting).  
**Goal:** Let the Kiro CLI complete a **full, buildable** migration with **zero** compilation errors by searching these files and applying the patterns.

---

## 🎯 Target Framework (.NET 8 or .NET 10)

This toolkit upgrades to **either .NET 8 or .NET 10**, depending on the configured target (`net8.0` or `net10.0`). Apply these rules everywhere in this knowledge base:

- **TFM placeholder:** Where a document shows `net8.0` (or an output path like `bin/Debug/net8.0`), treat it as a stand-in for the **target you are upgrading to**. Use `net10.0` when the target is .NET 10.
- **Framework-tied packages must match the target runtime major.** Anything under `Microsoft.AspNetCore.*`, `Microsoft.EntityFrameworkCore.*`, and `Microsoft.Extensions.*` ships in lockstep with the runtime: use `8.0.x` for .NET 8 and `10.0.x` for .NET 10. A version like `8.0.4` in an example means "the latest `8.0.x` patch for .NET 8, or the equivalent `10.0.x` for .NET 10."
- **Docker base images match the target:** `mcr.microsoft.com/dotnet/aspnet:8.0` / `sdk:8.0` for .NET 8, `:10.0` for .NET 10.
- **Third-party packages are runtime-independent.** Newtonsoft.Json, Dapper, NHibernate, Autofac, Serilog, WebOptimizer, AngleSharp, etc. use their own latest compatible version regardless of the .NET major.
- **Libraries** stay on `netstandard2.0` for maximum compatibility (unchanged by the target).

---

## 🧭 Conflict-Resolution Precedence

When more than one file could apply to the same problem, resolve overlaps with these rules. Each decision has a **single owning file**; other files link to it rather than restating it.

1. **Full migration beats keep-and-patch.** Prefer migrating to the modern equivalent (e.g. `log4net` → `Microsoft.Extensions.Logging`, see [12](./12-logging-migration.md)) over keeping and patching a legacy package. Keep-and-patch (e.g. bump to a non-vulnerable version) only when a full migration is out of scope for this pass.
2. **Built-in framework feature beats third-party shim.** Prefer built-in DI over `Autofac.Extensions.DependencyInjection` (see [13](./13-dependency-injection-migration.md)), and `System.Text.Json` over `Newtonsoft.Json` (see [06](./06-package-migrations.md) Step 6) — unless the app has heavy existing investment in the third-party option.
3. **Framework-tied packages match the target runtime major** (`8.0.x` / `10.0.x`), per the rules above.

This repository is designed to be **indexed by the Kiro CLI knowledge-base feature**. Each file focuses on **one** part of the migration and contains:

- detection patterns (what to search for in legacy code),
- transformation rules (what to change it to in modern .NET, targeting .NET 8 or .NET 10),
- code templates/snippets,
- gotchas for SmartStore-like apps (System.Web virtual file system, packaging, old Html/Cache APIs),
- pre-build cleanup rules (to avoid the recurring `[Index] is not an attribute class` problem).

---

## 🚨 MANDATORY FIRST STEP

**ALWAYS start with [00-prebuild-cleanup-and-bulk-fixes.md](./00-prebuild-cleanup-and-bulk-fixes.md)** before attempting any build.  
This eliminates 50-80% of initial compilation errors and prevents cascading failures.

**Estimated Time:** 5-10 minutes (automated)  
**Error Prevention:** 88-160 compilation errors

---

## Migration File Index

### Pre-Build (MANDATORY)

- **[00-prebuild-cleanup-and-bulk-fixes.md](./00-prebuild-cleanup-and-bulk-fixes.md)** – Remove Index attributes, fix using statements, add missing packages, comment incompatible code

### Core Migration

- **[01-project-file-migration.md](./01-project-file-migration.md)** – SDK-style .csproj, package references
- **[02-systemweb-migration.md](./02-systemweb-migration.md)** – System.Web → ASP.NET Core (HttpContext, Cache, etc.)
- **[03-mvc-migration.md](./03-mvc-migration.md)** – MVC controllers, routing, Razor
- **[04-webapi-migration.md](./04-webapi-migration.md)** – Web API → ASP.NET Core controllers
- **[05-hosting-deployment-migration.md](./05-hosting-deployment-migration.md)** – Kestrel, IIS, configuration
- **[06-package-migrations.md](./06-package-migrations.md)** – NuGet package replacements
- **[07-data-access-migration.md](./07-data-access-migration.md)** – General data access patterns
- **[08-auth-security-migration.md](./08-auth-security-migration.md)** – Authentication, authorization, MVC filters
- **[09-bundling-minification.md](./09-bundling-minification.md)** – WebOptimizer, static assets
- **[10-global-asax-migration.md](./10-global-asax-migration.md)** – Global.asax → Program.cs
- **[11-configuration-migration.md](./11-configuration-migration.md)** – Web.config → appsettings.json
- **[12-logging-migration.md](./12-logging-migration.md)** – Logging patterns
- **[13-dependency-injection-migration.md](./13-dependency-injection-migration.md)** – DI patterns
- **[14-middleware-migration.md](./14-middleware-migration.md)** – HTTP modules → middleware
- **[15-views-static-files-migration.md](./15-views-static-files-migration.md)** – Razor views, static files

### Data Access

- **[16-ef6-to-efcore-migration.md](./16-ef6-to-efcore-migration.md)** – Entity Framework 6 → EF Core
- **[17-dapper-migration.md](./17-dapper-migration.md)** – Dapper modernization
- **[18-nhibernate-migration.md](./18-nhibernate-migration.md)** – NHibernate for modern .NET (8/10)

### Deployment

- **[19-linux-containerization.md](./19-linux-containerization.md)** – Docker, Linux deployment

### Framework & Library Migrations

- **[20-wcf-to-corewcf-migration.md](./20-wcf-to-corewcf-migration.md)** – WCF → CoreWCF (server) + System.ServiceModel client packages
- **[21-system-drawing-migration.md](./21-system-drawing-migration.md)** – System.Drawing.Common → SkiaSharp / ImageSharp (Linux-safe imaging)
- **[22-crypto-migration.md](./22-crypto-migration.md)** – Cryptography: BouncyCastle rename, `*CryptoServiceProvider` → factory APIs
- **[23-swagger-swashbuckle-migration.md](./23-swagger-swashbuckle-migration.md)** – Swashbuckle 5.x → Swashbuckle.AspNetCore
- **[24-test-stack-migration.md](./24-test-stack-migration.md)** – MSTest / NUnit / xUnit / Moq; RhinoMocks removal
- **[28-dotnet-remoting-migration.md](./28-dotnet-remoting-migration.md)** – .NET Remoting → gRPC / named pipes / queues (+ AppDomain and BinaryFormatter removal)

### Web Forms Migration

- **[25-webforms-to-razor-migration.md](./25-webforms-to-razor-migration.md)** – Web Forms → ASP.NET Core Razor Pages / MVC (+ target-decision matrix)
- **[26-webforms-to-blazor-migration.md](./26-webforms-to-blazor-migration.md)** – Web Forms → Blazor

### Build Integrity

- **[27-blocked-packages-and-build-integrity.md](./27-blocked-packages-and-build-integrity.md)** – NU1701 framework-fallback packages, NU1605/NU1608 version conflicts, NU1902/NU1903 vulnerability advisories

---

## Error Code to File Mapping

| Error Code | Description                | Relevant Files    |
| ---------- | -------------------------- | ----------------- |
| CS0234     | Missing namespace/type     | 00, 02, 06, 28    |
| CS0246     | Type not found             | 00, 02, 06, 08, 28 |
| CS0103     | Name not in current context | 28               |
| CS0117     | Member not on type         | 28                |
| CS0616     | Not an attribute class     | 00, 07            |
| CS0672     | Overrides obsolete member  | 28                |
| CS1069     | Type forwarded to assembly | 06                |
| SYSLIB0010 | Remoting APIs obsolete     | 28                |
| SYSLIB0011 | BinaryFormatter obsolete (error) | 28          |
| SYSLIB0024 | AppDomain.CreateDomain obsolete | 28           |
| SYSLIB0050/0051 | Formatter-based serialization obsolete | 28 |
| NETSDK1022 | Duplicate Content items    | 01                |

---

## Migration Workflow

1. **Pre-Build Cleanup** (00) – MANDATORY FIRST STEP
2. **Project Structure** (01) – Convert to SDK-style
3. **Package Updates** (06) – Update all NuGet references
4. **System.Web Migration** (02) – Replace legacy types
5. **MVC/WebAPI Migration** (03, 04) – Update controllers
6. **Data Access** (16, 17, 18) – Migrate EF6/Dapper/NHibernate
7. **Authentication** (08) – Update auth/filters
8. **Configuration** (10, 11) – Global.asax → Program.cs
9. **Framework & Library** (20-24, 28) – WCF, System.Drawing, crypto, Swagger/Swashbuckle, test stack, .NET Remoting
10. **Web Forms** (25, 26) – Web Forms → Razor Pages/MVC or Blazor (only if the app uses Web Forms)
11. **Build Integrity** (27) – Resolve NU\*/NETSDK\* package and vulnerability warnings
12. **Deployment** (19) – Containerization

---

## Estimated Time by Area

| Area               | Time          | Error Reduction    |
| ------------------ | ------------- | ------------------ |
| Pre-Build Cleanup  | 5-10 min      | 88-160 errors      |
| Project Files      | 10-15 min     | 10-20 errors       |
| Package Migrations | 10-15 min     | 20-40 errors       |
| System.Web         | 30-60 min     | 30-50 errors       |
| MVC/WebAPI         | 30-45 min     | 15-25 errors       |
| Data Access        | 45-90 min     | 20-30 errors       |
| Authentication     | 30-60 min     | 10-15 errors       |
| Framework & Library (20-24) | 60-120 min | 30-50 errors  |
| .NET Remoting (28) \*\*    | 90-240 min    | 15-40 errors       |
| Build Integrity (27) | 15-30 min   | NU\*/NETSDK\* warnings |
| **TOTAL**          | **4-7 hours** | **223-390 errors** |

> \*\* **.NET Remoting (28)** is a **re-architecture, not a port** — there is no CoreWCF-style replacement, so the range depends entirely on the Step-1 classification: cross-AppDomain and `RealProxy`-AOP usage is a cheap local refactor (near the low end), while cross-machine RPC requires standing up a new gRPC/queue transport and reworking `BinaryFormatter` DTOs (well above the high end for large surfaces). Excluded from the headline total because most apps have no remoting at all.

> \* **Web Forms rewrite (25-26)** is additive and highly page-count dependent — budget **2-8 hours on top of the total** when the app uses Web Forms (a per-page rewrite to Razor Pages/MVC or Blazor). It is excluded from the headline total because most MVC / Web API apps skip it entirely.
