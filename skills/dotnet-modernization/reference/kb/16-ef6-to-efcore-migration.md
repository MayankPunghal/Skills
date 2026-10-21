# 16 – Entity Framework 6 (Code-First) → EF Core Migration (.NET 8 / .NET 10)

## Overview
This document guides a **code-first** migration from Entity Framework 6 (EF6) used in .NET Framework MVC/Web API apps to **Entity Framework Core** on modern .NET — **EF Core 8 for .NET 8, or EF Core 10 for .NET 10** (match the EF Core major to the target runtime). It focuses on practical, repeatable steps, code examples, common pitfalls, and verification steps — optimized for incremental migration in real projects.

> Scope: **Code-first only** (no EDMX/database-first).

---

## 1. Key Differences (High Level)
- **Namespaces:** `System.Data.Entity` → `Microsoft.EntityFrameworkCore`
- **DbContext constructor pattern:** EF Core prefers `DbContextOptions<T>` injection.
- **Lazy loading:** Configured differently; proxies require package and opt-in.
- **Mappings & Conventions:** Some EF6 conventions (e.g., pluralization) differ.
- **Migrations:** `Add-Migration` / `Update-Database` move to `dotnet ef` tooling.
- **Query behavior:** LINQ translations and client evaluation rules tightened.
- **Batch updates/deletes:** EF Core supports `ExecuteUpdate`/`ExecuteDelete` in newer versions (useful for bulk ops).
- **Change tracking:** Slight differences in behavior; be explicit where required.

---

## 2. Preparation Checklist
- Backup database and source code; work on a feature branch.
- Ensure solution builds under current .NET Framework state.
- Add comprehensive unit/integration tests before migration where possible.
- Identify the DbContext(s) and all entity classes.
- Inventory EF6-specific behaviors (custom conventions, interceptors, initializer patterns).

---

## 3. Add EF Core Packages
Install EF Core packages in the target project(s). **Match the EF Core version to the target runtime major: `8.0.x` for `net8.0`, `10.0.x` for `net10.0`.**
```bash
# .NET 8 shown below; for .NET 10 use --version 10.0.0 (or the latest 10.0.x)
dotnet add package Microsoft.EntityFrameworkCore.SqlServer --version 8.0.0
dotnet add package Microsoft.EntityFrameworkCore.Design --version 8.0.0
dotnet add package Microsoft.EntityFrameworkCore.Tools --version 8.0.0
```
Optional (if you need lazy-loading proxies):
```bash
dotnet add package Microsoft.EntityFrameworkCore.Proxies --version 8.0.0
```

---

## 4. Update DbContext
### EF6 (before)
```csharp
using System.Data.Entity;

public class AppContext : DbContext
{
    public AppContext() : base("DefaultConnection") { }

    public DbSet<User> Users { get; set; }
}
```
### EF Core (after)
```csharp
using Microsoft.EntityFrameworkCore;

public class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

    public DbSet<User> Users { get; set; }
}
```
Register in `Program.cs`:
```csharp
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseSqlServer(builder.Configuration.GetConnectionString("DefaultConnection")));
```

**Notes:**
- Replace the parameterless constructor with `DbContextOptions<T>` for DI friendliness.
- Prefer `AddDbContext` with scoped lifetime (default).

---

## 5. Entity Class Changes
Most POCO classes translate as-is, but watch for:
- `virtual` navigation properties for lazy loading (requires proxies).
- `DataAnnotations` differences — most attributes remain valid.
- `Timestamp` attribute maps to `RowVersion` (`[Timestamp]` still valid).

Example:
```csharp
public class User
{
    public int Id { get; set; }

    public string? Name { get; set; }

    // navigation
    public virtual ICollection<Order> Orders { get; set; } = new List<Order>();
}
```

To enable lazy loading with proxies:
```csharp
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseSqlServer(conn)
           .UseLazyLoadingProxies());
```

---

## 6. Fluent API & ModelBuilder
EF Core’s `OnModelCreating` is similar but API has differences.
### EF6 style
```csharp
modelBuilder.Entity<User>()
    .Property(u => u.Name)
    .IsRequired()
    .HasMaxLength(200);
```
### EF Core style (same intention)
```csharp
protected override void OnModelCreating(ModelBuilder modelBuilder)
{
    modelBuilder.Entity<User>(entity =>
    {
        entity.Property(u => u.Name).IsRequired().HasMaxLength(200);
    });
}
```
**Tips:**
- Replace `modelBuilder.Entity<T>().Map(...)` (EF6 table mapping) with `ToTable()` in EF Core.
- Composite keys: use `HasKey(e => new { e.Key1, e.Key2 })` (same approach).
- Sequence mapping, value generation, and computed columns have EF Core equivalents but APIs differ — consult docs when using advanced mappings.

---

## 7. Migrations (dotnet-ef)
Enable EF Core CLI tools and add an initial migration (after wiring DbContext):
```bash
dotnet tool install --global dotnet-ef
dotnet ef migrations add InitialCreate
dotnet ef database update
```
**Notes:**
- If migrating an existing database, use `dotnet ef migrations add BringYourOwnDatabase` and create an initial blank migration (scaffold with `-o` and mark as applied) or use `Migrations` with `HasAnnotation("Relational:MaxIdentifierLength", ...)` adjustments if necessary.
- When transitioning from EF6 code-first to EF Core, it’s common to create a **baseline empty migration** that represents the current DB schema (so future migrations can be incremental). Use `dotnet ef migrations add Initial_EmptyMigration --ignore-changes` pattern (or add a migration and then remove operations).

---

## 8. Data Seeding
EF Core supports data seeding via `HasData()` in `OnModelCreating`:
```csharp
modelBuilder.Entity<Role>().HasData(new Role { Id = 1, Name = "Admin" });
```
For complex seeding prefer startup scripts or a dedicated seeding service that uses `IServiceScopeFactory` to ensure scoped DbContext usage.

---

## 9. Query Translation and LINQ Changes
EF Core enforces stricter translation rules:
- Avoid methods that cannot be translated server-side (e.g., certain CLR functions). Use `AsEnumerable()` to force client evaluation **only** when acceptable.
- `Include()` / `ThenInclude()` for eager loading (more explicit than EF6).
- `Select` with anonymous types works similarly but beware of subtle differences in SQL generated.
- Use `AsNoTracking()` for read-only queries to improve performance.

Example eager load:
```csharp
var orders = await context.Orders
    .Include(o => o.OrderLines)
    .ThenInclude(ol => ol.Product)
    .Where(o => o.Status == "Open")
    .ToListAsync();
```

---

## 10. Transactions & SaveChanges
EF Core's `SaveChangesAsync()` supports cancellation tokens and returns the number of affected entries. Use explicit transactions for multi-context operations:
```csharp
using var transaction = await context.Database.BeginTransactionAsync();
try
{
    // multiple operations
    await context.SaveChangesAsync();
    await transaction.CommitAsync();
}
catch
{
    await transaction.RollbackAsync();
    throw;
}
```

---

## 11. Handling Stored Procedures & Raw SQL
EF Core provides `FromSqlRaw` / `ExecuteSqlRaw` APIs:
```csharp
var users = await context.Users.FromSqlRaw("EXEC dbo.GetUsers").ToListAsync();
await context.Database.ExecuteSqlRawAsync("EXEC dbo.UpdateSomething @p0", param);
```

For non-entity results, map to DTOs via `Set<Dto>().FromSqlRaw(...)` using keyless entity types:
```csharp
modelBuilder.Entity<UserDto>().HasNoKey();
```

---

## 12. Concurrency Control
EF Core supports `[ConcurrencyCheck]` and `[Timestamp]` attributes. For optimistic concurrency, handle `DbUpdateConcurrencyException` similarly to EF6 but APIs return `Entries` with current and database values.

---

## 13. Interceptors and Logging
EF Core supports interceptors (`ISaveChangesInterceptor`, `IDbCommandInterceptor`). Replace EF6-style interceptors with EF Core equivalents and use `ILogger` integration for SQL logging:
```csharp
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseSqlServer(conn)
           .LogTo(Console.WriteLine, LogLevel.Information));
```

---

## 14. Performance Tips
- Use `AsNoTracking()` for read-only queries.
- Batch operations with `ExecuteUpdate` / `ExecuteDelete` where applicable.
- Careful with eager loading — only include what you need.
- Use compiled queries for hotspots:
```csharp
private static readonly Func<AppDbContext, int, Task<User?>> _getUserCompiled =
    EF.CompileAsyncQuery((AppDbContext ctx, int id) => ctx.Users.FirstOrDefault(u => u.Id == id));
```

---

## 15. Common Pitfalls & Fixes

| Symptom | Cause | Fix |
|--------|-------|-----|
| NULL behavior differences | Client vs server eval | Review LINQ expressions; add explicit null checks |
| Migration conflicts | Manual DB changes vs migrations | Use baseline empty migration or scaffold from DB |
| Lazy loading not working | Proxies not enabled OR navigation not virtual | Enable proxies or use explicit loading |
| Change tracking surprises | Detached entities | Attach entities via `context.Attach(entity)` before modifying |

---

## 16. Testing & Validation
- Add integration tests using `WebApplicationFactory<T>` and `Testcontainers` for SQL Server or use ephemeral in-memory providers for basic tests.
- Verify migrations on a copy of production DB.
- Run performance benchmarks for critical queries before and after migration.

---

## 17. Rollout Strategies
- **Parallel deployment:** Keep EF6 app running while rolling out EF Core service pointing to same DB read-only (careful with writes).
- **Feature flags:** Introduce EF Core modules behind feature flags.
- **Big bang:** Only if you can afford downtime and have tested migration scripts thoroughly.

---

## 18. Example Migration Plan (step-by-step)

1. Add EF Core packages and create `AppDbContext` (DI-enabled).  
2. Wire `AppDbContext` in `Program.cs`.  
3. Create baseline migration (empty) representing current DB.  
4. Convert entity classes and Fluent API mappings.  
5. Run tests and verify model validation.  
6. Migrate small read-only endpoints and validate.  
7. Incrementally migrate write paths, using dual-writing if necessary.  
8. Remove EF6 references and package dependencies.  
9. Finalize by cleaning EF6 artifacts and updating docs.

---

## 19. References
- EF Core docs: https://learn.microsoft.com/ef/core/  
- Migration guidance: https://learn.microsoft.com/ef/core/what-is-new/ef-core-8.0/

---

## See Also
- [07-data-access-migration.md](./07-data-access-migration.md)
- [06-package-migrations.md](./06-package-migrations.md)
