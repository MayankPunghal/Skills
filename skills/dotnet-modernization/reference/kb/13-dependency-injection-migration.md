# 13 – Dependency Injection Migration

## Overview
ASP.NET MVC used tools like Autofac, Ninject, or Unity for DI. Modern .NET (.NET 8 and .NET 10) has a first-class DI container built into the framework.

---

## Step 1: Register Services

```csharp
builder.Services.AddTransient<IMailService, SmtpMailService>();
builder.Services.AddScoped<IUserRepository, UserRepository>();
builder.Services.AddSingleton<ICache, MemoryCache>();
```

---

## Step 2: Constructor Injection

```csharp
public class UserController : Controller
{
    private readonly IUserRepository _repo;
    public UserController(IUserRepository repo) => _repo = repo;
}
```

---

## Step 3: Replace Autofac/Ninject/Unity

| Old Framework | Modern Replacement | Notes |
|----------------|--------------------|-------|
| Autofac | Use native DI | Optionally integrate with `Autofac.Extensions.DependencyInjection` |
| Ninject | Use built-in DI | Simpler and more performant |
| Unity | Use built-in DI | Direct mapping supported |

---

## Step 4: Service Scopes

| Lifetime | Behavior |
|-----------|-----------|
| Singleton | Shared across the app |
| Scoped | Shared per web request |
| Transient | New instance each time |

---

## Step 5: Configuration-based Registration

You can also register services conditionally:

```csharp
if (builder.Environment.IsDevelopment())
    builder.Services.AddSingleton<IDebugService, DebugService>();
```

---

## See Also
- [10-global-asax-migration.md](./10-global-asax-migration.md)
- [14-middleware-migration.md](./14-middleware-migration.md)
