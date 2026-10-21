# 18 – NHibernate Migration (from .NET Framework to .NET 8 / .NET 10)

## Overview
NHibernate remains compatible with modern .NET (as of version **5.4+**), making migration primarily about updating dependencies, configuration, and ensuring proper ADO.NET provider usage.  
This guide focuses on modernizing NHibernate for MVC and Web API projects that are being ported to modern .NET (**.NET 8 or .NET 10**). NHibernate is runtime-independent — use the latest 5.4+ release on either target.

---

## Step 1: Update Packages

Replace legacy packages with the latest compatible versions:

```bash
dotnet add package NHibernate
dotnet add package NHibernate.Mapping.Attributes
dotnet add package Microsoft.Data.SqlClient
```

Ensure that you remove any `System.Data.SqlClient` references — all ADO.NET usage must migrate to `Microsoft.Data.SqlClient`.

---

## Step 2: Replace ConfigurationManager-Based Setup

### Before (.NET Framework)
```csharp
var cfg = new Configuration();
cfg.Configure(); // reads hibernate.cfg.xml
cfg.AddAssembly(typeof(User).Assembly);
var sessionFactory = cfg.BuildSessionFactory();
```

### After (modern .NET — .NET 8 / .NET 10)
```csharp
var cfg = new Configuration();
cfg.DataBaseIntegration(db =>
{
    db.ConnectionString = builder.Configuration.GetConnectionString("DefaultConnection");
    db.Dialect<MsSql2012Dialect>();
    db.Driver<MicrosoftDataSqlClientDriver>();
});
cfg.AddAssembly(typeof(User).Assembly);
var sessionFactory = cfg.BuildSessionFactory();
```

> ✅ Tip: Explicitly configure dialect and driver in code to avoid XML parsing issues in cross-platform environments.

---

## Step 3: Update Driver and Dialect

### Recommended for SQL Server:
```csharp
db.Dialect<MsSql2012Dialect>();
db.Driver<MicrosoftDataSqlClientDriver>();
```
### Recommended for PostgreSQL:
```csharp
db.Dialect<PostgreSQL83Dialect>();
db.Driver<NpgsqlDriver>();
```
Make sure your dialect matches your target database engine.

---

## Step 4: Session Factory Registration (DI Integration)

You can now integrate NHibernate’s session factory with ASP.NET Core’s dependency injection system.

```csharp
builder.Services.AddSingleton<ISessionFactory>(sp =>
{
    var cfg = new Configuration();
    cfg.DataBaseIntegration(db =>
    {
        db.ConnectionString = sp.GetRequiredService<IConfiguration>().GetConnectionString("DefaultConnection");
        db.Dialect<MsSql2012Dialect>();
        db.Driver<MicrosoftDataSqlClientDriver>();
    });
    cfg.AddAssembly(typeof(User).Assembly);
    return cfg.BuildSessionFactory();
});

builder.Services.AddScoped(sp =>
    sp.GetRequiredService<ISessionFactory>().OpenSession());
```

Now you can inject `ISession` directly into repositories or services.

---

## Step 5: Async Support

NHibernate supports async session APIs since v5.3+. Prefer async operations:

```csharp
using var session = sessionFactory.OpenSession();
using var tx = session.BeginTransaction();
await session.SaveAsync(new User { Name = "Alice" });
await tx.CommitAsync();
```

---

## Step 6: Mapping Adjustments

If you used **HBM XML mappings**, ensure files are marked as **Embedded Resources**.  
For **Fluent NHibernate** users, upgrade to **FluentNHibernate v3.0+** which supports modern .NET (.NET 8 / .NET 10).

**Example (Attributes Mapping):**
```csharp
[Class(Table = "Users")]
public class User
{
    [Id(Name = "Id", Column = "Id")]
    [Generator(1, Class = "native")]
    public virtual int Id { get; set; }

    [Property]
    public virtual string Name { get; set; }
}
```

---

## Step 7: Transactions and Unit of Work Pattern

In ASP.NET Core, manage sessions per request using middleware or filters:

```csharp
public class NHibernateMiddleware
{
    private readonly RequestDelegate _next;

    public NHibernateMiddleware(RequestDelegate next)
    {
        _next = next;
    }

    public async Task InvokeAsync(HttpContext context, ISession session)
    {
        using var tx = session.BeginTransaction();
        try
        {
            await _next(context);
            await tx.CommitAsync();
        }
        catch
        {
            await tx.RollbackAsync();
            throw;
        }
    }
}
```
Register:
```csharp
app.UseMiddleware<NHibernateMiddleware>();
```

---

## Step 8: Logging and Diagnostics

NHibernate integrates with `Microsoft.Extensions.Logging`.  
Enable SQL logging by configuring the log provider:

```csharp
LogProvider.SetCurrentLogProvider(new ConsoleLogProvider());
```

Or use Serilog/NLog integrations via the standard .NET logging pipeline.

---

## Step 9: Migrations (Schema Evolution)

NHibernate doesn’t have built-in migrations like EF Core.  
You can use **FluentMigrator**, **RoundhousE**, or **DbUp** for schema management.

Example using FluentMigrator:
```bash
dotnet add package FluentMigrator.Runner
```

Configure in `Program.cs`:
```csharp
builder.Services.AddFluentMigratorCore()
    .ConfigureRunner(runner => runner
        .AddSqlServer()
        .WithGlobalConnectionString(builder.Configuration.GetConnectionString("DefaultConnection"))
        .ScanIn(typeof(Program).Assembly).For.Migrations())
    .AddLogging(lb => lb.AddFluentMigratorConsole());
```

---

## Step 10: Common Pitfalls

| Symptom | Cause | Fix |
|----------|--------|-----|
| `System.Data.SqlClient` assembly not found | Using legacy driver | Switch to `Microsoft.Data.SqlClient` |
| Configuration file not found | Working directory change | Use explicit configuration path or code setup |
| Lazy loading exceptions | Missing virtual properties | Ensure navigations are `virtual` |
| Session leaks | Sessions not disposed | Use DI or middleware pattern |
| No async APIs | Using NHibernate < 5.3 | Upgrade to 5.4+ |

---

## Step 11: Linux Deployment Notes

NHibernate is fully compatible with Linux. Ensure:
- Use `Microsoft.Data.SqlClient` v5.1+ for cross-platform TLS.
- Avoid case-sensitive path issues in mapping files.
- Use UTF-8 encoding in XML mappings if applicable.

---

## Step 12: Migration Validation Checklist

✅ Updated to NHibernate v5.4+  
✅ Replaced `System.Data.SqlClient` with `Microsoft.Data.SqlClient`  
✅ Integrated via dependency injection  
✅ Verified session lifecycle per request  
✅ Updated dialects and driver setup  
✅ Tested async CRUD operations  
✅ Verified logging and schema migrations  

---

## See Also
- [17-dapper-migration.md](./17-dapper-migration.md)
- [19-linux-containerization.md](./19-linux-containerization.md)
