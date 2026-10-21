# 11 – Configuration and Settings Migration

## Overview
Legacy MVC and Web API apps store configuration in `web.config`. In modern .NET (.NET 8 and .NET 10), configuration is JSON-based and environment-driven, supporting hierarchical overrides and secrets.

---

## Step 1: Replace `web.config` with `appsettings.json`

### Before (`web.config`)
```xml
<configuration>
  <connectionStrings>
    <add name="DefaultConnection" connectionString="Server=.;Database=MyApp;Integrated Security=True" providerName="System.Data.SqlClient" />
  </connectionStrings>
  <appSettings>
    <add key="Environment" value="Production" />
  </appSettings>
</configuration>
```

### After (`appsettings.json`)
```json
{
  "ConnectionStrings": {
    "DefaultConnection": "Server=.;Database=MyApp;Integrated Security=True"
  },
  "AppSettings": {
    "Environment": "Production"
  }
}
```

---

## Step 2: Environment-specific Files
Modern .NET (8/10) automatically loads environment variants.

Example:
```bash
appsettings.Development.json
appsettings.Production.json
```

`Program.cs` automatically picks the right file based on `ASPNETCORE_ENVIRONMENT`.

---

## Step 3: Access Configuration in Code

```csharp
var configValue = builder.Configuration["AppSettings:Environment"];
```

Or inject `IConfiguration` into services:
```csharp
public class MyService
{
    private readonly IConfiguration _config;
    public MyService(IConfiguration config) => _config = config;
}
```

---

## Step 4: Secret Management

Use `dotnet user-secrets` for local development:

```bash
dotnet user-secrets init
dotnet user-secrets set "ConnectionStrings:DefaultConnection" "Server=.;Database=AppDb;User Id=sa;Password=<password>"
```

---

## Step 5: Replace `ConfigurationManager.AppSettings`

### Before
```csharp
var env = ConfigurationManager.AppSettings["Environment"];
```

### After
```csharp
var env = builder.Configuration["AppSettings:Environment"];
```

---

## Step 6: Replace `web.config` Custom Sections

Use typed configuration objects:

```csharp
builder.Services.Configure<MySettings>(builder.Configuration.GetSection("MySettings"));
```

```csharp
public class MySettings
{
    public string Key { get; set; }
}
```

---

## Step 7: Logging Configuration Integration

`appsettings.json` also configures logging providers (see [12-logging-migration.md](./12-logging-migration.md)).

```json
"Logging": {
  "LogLevel": {
    "Default": "Information",
    "Microsoft": "Warning"
  }
}
```

---

## See Also
- [10-global-asax-migration.md](./10-global-asax-migration.md)
- [12-logging-migration.md](./12-logging-migration.md)
