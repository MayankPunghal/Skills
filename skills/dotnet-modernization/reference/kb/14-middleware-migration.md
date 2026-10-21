# 14 – OWIN to ASP.NET Core Middleware Migration

## Overview
ASP.NET Core unifies OWIN concepts through a native middleware pipeline using `Use()`, `Map()`, and endpoint routing.

---

## Step 1: Compare Pipelines

| OWIN | ASP.NET Core |
|------|----------------|
| `app.Use(async (ctx, next) => { ... });` | `app.Use(async (ctx, next) => { ... });` |
| `app.UseStageMarker()` | N/A (use routing order) |
| `IAppBuilder` | `WebApplication` |

---

## Step 2: Typical Migration Example

### Before (OWIN Startup)
```csharp
public void Configuration(IAppBuilder app)
{
    app.UseCors(CorsOptions.AllowAll);
    app.UseOAuthBearerAuthentication(...);
    app.UseWebApi(config);
}
```

### After (ASP.NET Core `Program.cs`)
```csharp
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddCors();
builder.Services.AddAuthentication("Bearer").AddJwtBearer(...);
builder.Services.AddControllers();

var app = builder.Build();
app.UseCors(x => x.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod());
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();
app.Run();
```

---

## Step 3: Middleware Order

1. Exception handling  
2. Static files  
3. Routing  
4. Authentication  
5. Authorization  
6. Endpoints  

---

## Step 4: Replace `UseWebApi()`
Replace with:
```csharp
app.MapControllers();
```

---

## Step 5: Custom Middleware

### Before
```csharp
public class LogMiddleware : OwinMiddleware
{
    public override async Task Invoke(IOwinContext context)
    {
        await Next.Invoke(context);
    }
}
```

### After
```csharp
public class LogMiddleware
{
    private readonly RequestDelegate _next;
    public LogMiddleware(RequestDelegate next) => _next = next;

    public async Task InvokeAsync(HttpContext context)
    {
        await _next(context);
    }
}
app.UseMiddleware<LogMiddleware>();
```

---

## See Also
- [13-dependency-injection-migration.md](./13-dependency-injection-migration.md)
- [15-views-static-files-migration.md](./15-views-static-files-migration.md)
