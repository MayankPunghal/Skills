# 17 – Dapper Migration (from .NET Framework to .NET 8 / .NET 10)

## Overview
Dapper is a lightweight micro-ORM commonly used in MVC and Web API apps for performance and simplicity.  
Migrating from .NET Framework to modern .NET (**.NET 8 or .NET 10**) requires minimal changes, but connection management, async usage, and dependency injection patterns must be updated. Dapper is runtime-independent, so the same latest package works on either target.

---

## Step 1: Update Package Reference

Remove old Dapper package from `packages.config` or `.csproj` and install the modern NuGet package:

```bash
dotnet add package Dapper
```

Verify that your version is **≥ 2.1.0**, which supports modern .NET (.NET 8 / .NET 10) and modern ADO.NET APIs.

---

## Step 2: Replace Configuration-Based Connection Strings

### Before (.NET Framework)
```csharp
using (var connection = new SqlConnection(ConfigurationManager.ConnectionStrings["DefaultConnection"].ConnectionString))
{
    var users = connection.Query<User>("SELECT * FROM Users");
}
```

### After (modern .NET — .NET 8 / .NET 10)
```csharp
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection");
using var connection = new SqlConnection(connectionString);
var users = connection.Query<User>("SELECT * FROM Users");
```

---

## Step 3: Use Dependency Injection for Database Connections

You can register a connection factory or repository in `Program.cs`:

```csharp
builder.Services.AddTransient<IDbConnection>(sp =>
{
    var config = sp.GetRequiredService<IConfiguration>();
    return new SqlConnection(config.GetConnectionString("DefaultConnection"));
});
```

Then inject into repositories or services:

```csharp
public class UserRepository
{
    private readonly IDbConnection _db;
    public UserRepository(IDbConnection db) => _db = db;

    public IEnumerable<User> GetAll() =>
        _db.Query<User>("SELECT * FROM Users");
}
```

---

## Step 4: Embrace Async Methods

In modern .NET (8/10), prefer async I/O to maximize scalability.

### Before
```csharp
var users = connection.Query<User>("SELECT * FROM Users");
```

### After
```csharp
var users = await connection.QueryAsync<User>("SELECT * FROM Users");
```

---

## Step 5: Transaction Handling

```csharp
using var connection = new SqlConnection(connectionString);
await connection.OpenAsync();

using var transaction = connection.BeginTransaction();
await connection.ExecuteAsync("INSERT INTO Logs(Message) VALUES(@msg)", new { msg = "Started" }, transaction);

transaction.Commit();
```

---

## Step 6: Migrate Type Handlers and Custom Mapping

If you used `SqlMapper.AddTypeHandler`, move these registrations into startup:

```csharp
SqlMapper.AddTypeHandler(new MyCustomTypeHandler());
```

Register early in `Program.cs` or `StartupExtensions.cs`.

---

## Step 7: Compatibility Notes

| Topic | EF6/Dapper in .NET Framework | Dapper in modern .NET (8/10) |
|-------|-------------------------------|------------------|
| Connection management | Often manual | Can be DI-based |
| Async | Limited support | Fully supported |
| Mapping | Attribute-based or manual | Attribute + convention supported |
| Transactions | `TransactionScope` | `BeginTransaction()` preferred |
| Logging | Custom trace | Use .NET logging abstraction |

---

## Step 8: Logging Integration

You can integrate Dapper with `ILogger`:

```csharp
public class LoggingConnection : IDbConnection
{
    private readonly IDbConnection _inner;
    private readonly ILogger<LoggingConnection> _logger;

    public LoggingConnection(IDbConnection inner, ILogger<LoggingConnection> logger)
    {
        _inner = inner;
        _logger = logger;
    }

    // Wrap Execute/Query calls for logging
}
```

---

## Step 9: Test in Linux Containers

Ensure your SQL Server connection string supports `Server=tcp,1433;` and your Docker network allows connectivity.

```bash
docker run -e "ConnectionStrings__DefaultConnection=Server=sql;Database=App;User Id=sa;Password=<password>;" app:latest
```

---

## Step 10: Recommended Patterns

- Keep repositories small and SQL explicit.
- Use async everywhere.
- Inject `IDbConnection` instead of manually instantiating.
- Manage connection lifetimes via DI.
- Use minimal mapping, rely on Dapper’s default conventions.

---

## See Also
- [16-ef6-to-efcore-migration.md](./16-ef6-to-efcore-migration.md)
- [18-nhibernate-migration.md](./18-nhibernate-migration.md)
