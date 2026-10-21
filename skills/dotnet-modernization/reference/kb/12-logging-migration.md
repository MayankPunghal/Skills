# 12 – Logging Migration

## Overview
Legacy logging frameworks like `log4net` and `NLog` are migrated to the built-in **Microsoft.Extensions.Logging** system (optionally with Serilog) in modern .NET (.NET 8 and .NET 10).

**Preferred:** migrate off `log4net`/`NLog` entirely — this also clears vulnerable-package advisories (e.g. the `log4net` 2.0.10 `NU1902` warning). **Interim only**, if a full migration is out of scope for this pass: keep the library but bump it to a non-vulnerable version and bridge it through a logging provider. (This is the single owner for logging decisions — other files should link here rather than recommend a competing approach.)

---

## Step 1: Built-in Logging

Minimal configuration in `Program.cs`:

```csharp
builder.Logging.ClearProviders();
builder.Logging.AddConsole();
builder.Logging.AddDebug();
```

---

## Step 2: Configure via `appsettings.json`

```json
"Logging": {
  "LogLevel": {
    "Default": "Information",
    "Microsoft": "Warning"
  }
}
```

---

## Step 3: Structured Logging with Serilog

```bash
dotnet add package Serilog.AspNetCore
dotnet add package Serilog.Sinks.Console
dotnet add package Serilog.Sinks.File
```

```csharp
Log.Logger = new LoggerConfiguration()
    .WriteTo.Console()
    .WriteTo.File("Logs/app.log")
    .CreateLogger();

builder.Host.UseSerilog();
```

---

## Step 4: Migration Tips

| Legacy | Modern | Notes |
|--------|---------|-------|
| `log4net` | Serilog or built-in logging | Use structured output |
| `NLog` | NLog.Extensions.Logging | Compatible via provider |
| `System.Diagnostics.Trace` | `ILogger` | Wrap with logger abstraction |

---

## Step 5: Accessing the Logger

```csharp
public class HomeController : Controller
{
    private readonly ILogger<HomeController> _logger;
    public HomeController(ILogger<HomeController> logger) => _logger = logger;
}
```

---

## See Also
- [11-configuration-migration.md](./11-configuration-migration.md)
- [14-middleware-migration.md](./14-middleware-migration.md)
