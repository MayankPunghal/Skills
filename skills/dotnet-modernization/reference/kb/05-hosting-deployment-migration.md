# 05 – Hosting and Deployment Migration

## Overview

ASP.NET Core apps run **self-hosted** via Kestrel and can be containerized for Linux.  
This replaces IIS-based hosting and `web.config`-driven configuration.

---

## Step 1: Hosting Model

| Legacy          | Modern                                   |
| --------------- | ---------------------------------------- |
| IIS, System.Web | Kestrel + reverse proxy (IIS, Nginx)     |
| web.config      | appsettings.json + environment variables |

---

## Step 2: Entry Point

### Before

`Global.asax` → `Application_Start`

### After

`Program.cs` (top-level statements):

```csharp
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllersWithViews();

var app = builder.Build();
app.UseStaticFiles();
app.UseRouting();
app.MapDefaultControllerRoute();
app.Run();
```

**Legacy `WebHost` / `Startup` pattern → minimal hosting.** Some upgrades (or Upgrade Assistant output) leave the older ASP.NET Core hosting pattern: a `Program.Main` calling `WebHost.CreateDefaultBuilder(args).UseStartup<Startup>()` plus a separate `Startup.cs`. On .NET 8/10 these APIs are obsolete (**`ASPDEPR008`**: `WebHost`, `IWebHost`, `IWebHostBuilder.Build()`). Convert to the single-file `WebApplication` model shown above:

- `Startup.ConfigureServices(IServiceCollection)` → `builder.Services.…` calls.
- `Startup.Configure(IApplicationBuilder, IWebHostEnvironment)` → `app.…` middleware calls after `builder.Build()`.
- Delete `Startup.cs` and the `WebHost.CreateDefaultBuilder` bootstrap; everything lives in `Program.cs`.

```csharp
// Legacy (obsolete on .NET 8/10 — ASPDEPR008)
public class Program
{
    public static void Main(string[] args) =>
        WebHost.CreateDefaultBuilder(args).UseStartup<Startup>().Build().Run();
}
// → replaced by the WebApplication.CreateBuilder(args) Program.cs shown above.
```

---

## Step 3: Kestrel Configuration

In `appsettings.json`:

```json
"Kestrel": {
  "Endpoints": {
    "Http": { "Url": "http://0.0.0.0:8080" }
  }
}
```

---

## Step 4: Docker Support

Create a `Dockerfile`:

```dockerfile
# Use the tag matching the target runtime: 8.0 for .NET 8, 10.0 for .NET 10
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app
EXPOSE 8080

FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish -c Release -o /app/publish

FROM base AS final
WORKDIR /app
COPY --from=build /app/publish .
ENTRYPOINT ["dotnet", "MyApp.dll"]
```

Build and run:

```bash
docker build -t myapp .
docker run -p 8080:8080 myapp
```

---

## Step 5: Environment Variables

ASP.NET Core automatically binds configuration from environment variables.  
No need for `ConfigurationManager.AppSettings`.

Example:

```bash
export ConnectionStrings__DefaultConnection="Server=..."
```

Access in code:

```csharp
builder.Configuration.GetConnectionString("DefaultConnection");
```

---

## Step 6: Logging and Monitoring

Built-in logging replaces `System.Diagnostics.Trace`.

```csharp
var logger = app.Services.GetRequiredService<ILogger<Program>>();
logger.LogInformation("App started");
```

Add third-party loggers:

```bash
dotnet add package Serilog.AspNetCore
```

---

## Step 7: Deployment

### Option 1: Docker

Deploy containerized image to AWS ECS, Azure App Service, or Kubernetes.

### Option 2: Direct Publish

```bash
dotnet publish -c Release -r linux-x64 --self-contained false
```

Output is a standalone folder ready for deployment.

---

## Step 8: HTTPS and Reverse Proxy

Use `app.UseHttpsRedirection();` for HTTPS.  
When behind a reverse proxy (Nginx/IIS):

```csharp
app.UseForwardedHeaders(new ForwardedHeadersOptions
{
    ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto
});
```

---

## Step 9: Health Checks

Add health endpoints:

```csharp
builder.Services.AddHealthChecks();
app.MapHealthChecks("/health");
```

---

## Step 10:

Replacing IVirtualPathProvider / IVirtualFolder
These interfaces are obsolete. Replace with:

- `IWebHostEnvironment.WebRootFileProvider` for static resources
- `IFileProvider` from Microsoft.Extensions.FileProviders
- For custom virtual filesystem logic, use `PhysicalFileProvider` or `CompositeFileProvider`
- Ensure all web root and content root paths are resolved using dependency-injected `IWebHostEnvironment`.

---

## Step 10: Validation Checklist

✅ Uses `Program.cs` entry point  
✅ Runs with `dotnet run` on Linux  
✅ Uses Kestrel as web server  
✅ Environment variables replace Web.config  
✅ Containerization tested with Docker

---

## See Also

- [01-project-file-migration.md](./01-project-file-migration.md)
- [11-configuration-migration.md](./11-configuration-migration.md)
