# 07 – Data Access Migration (EF6, Dapper, NHibernate)

## Overview
Data access modernization is one of the most impactful changes when upgrading to modern .NET (**.NET 8 or .NET 10**, per the toolkit's target).  
This document focuses on migrating **Entity Framework 6**, **Dapper**, and **NHibernate** for MVC and Web API applications. Match the EF Core major to the target runtime (`8.0.x` for .NET 8, `10.0.x` for .NET 10); Dapper and NHibernate are runtime-independent — use their latest compatible versions.

---

## 1. Entity Framework 6 → EF Core

### Key Namespace Changes
| From | To |
|------|----|
| `System.Data.Entity` | `Microsoft.EntityFrameworkCore` |
| `DbSet<T>` | `DbSet<T>` (same) |
| `Database.SqlQuery<T>` | `FromSqlRaw` / `FromSqlInterpolated` |

### Migration Steps

#### a. Install EF Core Packages
```bash
dotnet add package Microsoft.EntityFrameworkCore.SqlServer
dotnet add package Microsoft.EntityFrameworkCore.Tools
```

#### b. Modify `DbContext`
Before:
```csharp
public class AppContext : DbContext
{
    public DbSet<User> Users { get; set; }
}
```
After:
```csharp
public class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }
    public DbSet<User> Users => Set<User>();
}
```

#### c. Configure in `Program.cs`
```csharp
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseSqlServer(builder.Configuration.GetConnectionString("DefaultConnection")));
```

#### d. Run Migration
```bash
dotnet ef migrations add Init
dotnet ef database update
```

---

## 2. Dapper Migration

Dapper continues to work without breaking changes.

### Setup
```bash
dotnet add package Dapper
dotnet add package Microsoft.Data.SqlClient
```

### Example
```csharp
using (var connection = new SqlConnection(connStr))
{
    var users = await connection.QueryAsync<User>("SELECT * FROM Users");
}
```

### Notes
- Replace `System.Data.SqlClient` with `Microsoft.Data.SqlClient`.
- Ensure `async` APIs are used for performance.
- Avoid `ConfigurationManager.ConnectionStrings` — use `IConfiguration` instead.

---

## 3. NHibernate Migration

NHibernate 5.4+ supports modern .NET (.NET 8 and .NET 10).

### Example Configuration
```csharp
var cfg = new Configuration();
cfg.DataBaseIntegration(db =>
{
    db.ConnectionString = builder.Configuration.GetConnectionString("DefaultConnection");
    db.Dialect<MsSql2012Dialect>();
});
var sessionFactory = cfg.BuildSessionFactory();
```

### Notes
- Replace `System.Data.SqlClient` provider with `Microsoft.Data.SqlClient`.
- Use `async` operations where available.
- Consider migrating to EF Core for long-term support.

---

## 4. Connection Strings
Move connection strings to `appsettings.json`:

```json
{
  "ConnectionStrings": {
    "DefaultConnection": "Server=localhost;Database=AppDb;User Id=sa;Password=<password>;TrustServerCertificate=True"
  }
}
```

---

## See Also
- [06-package-migrations.md](./06-package-migrations.md)
- [11-configuration-migration.md](./11-configuration-migration.md)
---

## 6. Remove EF6 attributes from entity classes

Your failing build contained errors like:

> `error CS0616: 'Index' is not an attribute class`

That happens because EF6 let you put `[Index]` (and variations) on POCOs, while EF Core **does not**.  
Fix:

1. **Delete all `[Index]` / `[Index(...)]` / `IndexAttribute` usages** from your entity classes:
   ```csharp
   // BEFORE
   [Index("IX_MenuRecord_ParentId_Order")]
   public int ParentId { get; set; }

   // AFTER – in DbContext
   protected override void OnModelCreating(ModelBuilder modelBuilder)
   {
       modelBuilder.Entity<MenuRecord>()
           .HasIndex(x => new { x.ParentId, x.Order });
   }
   ```

2. **Remove the using** if it now has no purpose:
   ```csharp
   // remove
   using System.ComponentModel.DataAnnotations.Schema;
   ```

3. **Move all relational configuration into Fluent API** (`OnModelCreating`) – this keeps your entity classes clean and avoids non-supported attributes in EF Core (.NET 8 / .NET 10).

---

## 7. EF Core replacements for EF6 types

Your log also showed missing:
- `DbEntityEntry`
- `ObjectContext`
- `System.Data.Entity`

Map them like this:

```csharp
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.ChangeTracking;

// EF6: DbEntityEntry
EntityEntry entry = context.Entry(entity);

// EF6: context.Set<TEntity>().Add(entity);
await context.Set<TEntity>().AddAsync(entity);
```

If you see `IDbContext` / `SmartStore.Core.Data.IDbContext` abstractions that depend on EF6 types, update the interface to use EF Core equivalents:

```csharp
public interface IAppDbContext
{
    DbSet<TEntity> Set<TEntity>() where TEntity : class;
    EntityEntry Entry(object entity);
    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
}
```

---

## 8. SQL Server Compact / SqlServerCe

The build had:

> `System.Data.SqlServerCe does not exist in the namespace 'System.Data'`

This is legacy – remove it:

- Delete / comment any `using System.Data.SqlServerCe;`
- Delete any providers registered for SQL CE in old `web.config`
- If you need lightweight local dev, use **SQLite** via EF Core:

```csharp
services.AddDbContext<AppDbContext>(options =>
    options.UseSqlite(configuration.GetConnectionString("DefaultConnection")));
```

---

## 9. NuGet-based packaging APIs in data layer

SmartStore had `Packaging.disabled` code pulling in `NuGet.Core` – that won’t work on modern .NET (8/10).  
Do this:

```csharp
#if false
// TODO net8: NuGet-based package update (was using NuGet.Core)
#endif
```

Keep the interfaces but comment the impl so the project can **compile**.
