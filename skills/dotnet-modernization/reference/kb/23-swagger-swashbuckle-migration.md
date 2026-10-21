# 23 – Swagger / Swashbuckle Migration (.NET 8 / .NET 10)

## Overview
Web API 2 projects documented their APIs with **Swashbuckle 5.x** (`Swashbuckle.Core`, configured in
`App_Start/SwaggerConfig.cs` against `System.Web.Http`) and often added
`Swashbuckle.Examples` (the `SwaggerResponseExample` / `SwaggerRequestExample` /
`IExamplesProvider` attributes). Neither runs on ASP.NET Core. The replacements are
`Swashbuckle.AspNetCore` (core generator + annotations) and `Swashbuckle.AspNetCore.Filters`
(examples). The attribute names survive but their **signatures changed**, which is why a blind
port produces `CS1739 does not have a parameter named 'jsonConverter'` and
`CS0305 IExamplesProvider<T> requires 1 type argument`.

---

## Step 1: Replace the packages

### Before
```xml
<PackageReference Include="Swashbuckle.Core" Version="5.6.0" />
<PackageReference Include="Swashbuckle.Examples" Version="4.1.0" />
```
### After
```xml
<PackageReference Include="Swashbuckle.AspNetCore" Version="8.0.10" />
<PackageReference Include="Swashbuckle.AspNetCore.Annotations" Version="8.0.10" />
<PackageReference Include="Swashbuckle.AspNetCore.Filters" Version="8.0.2" />
```

> **Version note:** the pins above are illustrative. Use versions that support the configured target
> framework (see the README "🎯 Target Framework (.NET 8 or .NET 10)" section). `Swashbuckle.AspNetCore`
> tracks the SDK closely; `Swashbuckle.AspNetCore.Filters` is third-party — pin it to a release that
> declares support for the target TFM. If none exists for `net10.0`, treat it as a blocked/incompatible
> package (see [06-package-migrations.md](./06-package-migrations.md)) and fall back to built-in
> `[ProducesResponseType]`.

---

## Step 2: `SwaggerConfig.cs` → `Program.cs`

### Before
```csharp
// App_Start/SwaggerConfig.cs
GlobalConfiguration.Configuration
    .EnableSwagger(c => c.SingleApiVersion("v1", "My API"))
    .EnableSwaggerUi();
```
### After
```csharp
// Program.cs
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new() { Title = "My API", Version = "v1" });
    c.EnableAnnotations();                 // for [SwaggerOperation]/[SwaggerResponse]
    c.ExampleFilters();                    // for Swashbuckle.AspNetCore.Filters examples
});
builder.Services.AddSwaggerExamplesFromAssemblyOf<Program>();

var app = builder.Build();
app.UseSwagger();
app.UseSwaggerUI();
```

---

## Step 3: `[SwaggerResponse]` — `HttpStatusCode` → `int`

The ASP.NET Core annotation takes an `int` status code, not the `System.Net.HttpStatusCode`
enum. Either switch to the built-in `[ProducesResponseType]` (recommended) or use the annotations
attribute with an int.

### Before
```csharp
[SwaggerResponse(HttpStatusCode.OK, "Ok", typeof(PaymentInitResponse))]
[SwaggerResponse(HttpStatusCode.BadRequest, "BadRequest", typeof(ApiErrorResponse))]
```
### After — built-in (preferred)
```csharp
using Microsoft.AspNetCore.Http;
[ProducesResponseType(typeof(PaymentInitResponse), StatusCodes.Status200OK)]
[ProducesResponseType(typeof(ApiErrorResponse), StatusCodes.Status400BadRequest)]
```
### After — annotations attribute (if you keep `[SwaggerResponse]`)
```csharp
using Swashbuckle.AspNetCore.Annotations;
[SwaggerResponse(200, "Ok", typeof(PaymentInitResponse))]
[SwaggerResponse(400, "BadRequest", typeof(ApiErrorResponse))]
```

---

## Step 4: Examples — drop `jsonConverter`, make `IExamplesProvider<T>` generic

`Swashbuckle.Examples` (old) had `SwaggerResponseExample(HttpStatusCode, Type, jsonConverter: ...)`
and a **non-generic** `IExamplesProvider`. `Swashbuckle.AspNetCore.Filters` uses an `int` status
code, has **no `jsonConverter` parameter**, and requires `IExamplesProvider<T>`.

### Before
```csharp
[SwaggerResponseExample(HttpStatusCode.BadRequest, typeof(BadRequestExample), jsonConverter: typeof(StringEnumConverter))]
public IHttpActionResult Post(...) { ... }

public class BadRequestExample : IExamplesProvider
{
    public object GetExamples() => new ApiErrorResponse { /* ... */ };
}
```
### After
```csharp
using Swashbuckle.AspNetCore.Filters;

[SwaggerRequestExample(typeof(PaymentInitRequest), typeof(PaymentInitRequestExample))]
[SwaggerResponseExample(400, typeof(BadRequestExample))]   // int status, no jsonConverter
public IActionResult Post(...) { ... }

public class BadRequestExample : IExamplesProvider<ApiErrorResponse>   // generic
{
    public ApiErrorResponse GetExamples() => new() { /* ... */ };
}
```

Notes:
- The removed `jsonConverter:` argument (used to force `StringEnumConverter`) has no per-attribute
  equivalent. Configure enum-as-string **globally** instead:
  ```csharp
  builder.Services.AddControllers()
      .AddJsonOptions(o => o.JsonSerializerOptions.Converters.Add(new JsonStringEnumConverter()));
  ```
  (or the Newtonsoft equivalent via `AddNewtonsoftJson`).
- `GetExamples()` now returns the concrete `T`, not `object`.
- Register example providers once with `AddSwaggerExamplesFromAssemblyOf<...>()` and enable with
  `c.ExampleFilters()` (Step 2).

---

## Step 5: Other annotation renames

| Old (`Swashbuckle` 5.x) | New (`Swashbuckle.AspNetCore.Annotations`) |
|---|---|
| `[SwaggerOperation("Id")]` | `[SwaggerOperation(OperationId = "Id")]` |
| `[ResponseType(typeof(X))]` (Web API 2) | `[ProducesResponseType(typeof(X), 200)]` |
| `[SwaggerResponseRemoveDefaults]` | not needed — remove |
| XML-doc comments via `c.IncludeXmlComments(path)` | same API on `AddSwaggerGen` |

---

## Step 6: Validation Checklist

✅ `Swashbuckle.Core` / `Swashbuckle.Examples` removed; `Swashbuckle.AspNetCore(.Annotations/.Filters)` added at TFM-compatible versions  
✅ `SwaggerConfig.cs` deleted; generation configured in `Program.cs` with `AddSwaggerGen` + `UseSwagger` / `UseSwaggerUI`  
✅ No `[SwaggerResponse(HttpStatusCode.…)]` — status codes are `int` or use `[ProducesResponseType]`  
✅ No `jsonConverter:` arguments on example attributes; enum-as-string configured globally  
✅ All `IExamplesProvider` implementations are `IExamplesProvider<T>` returning `T`  
✅ `ExampleFilters()` enabled and `AddSwaggerExamplesFromAssemblyOf<>()` registered  
✅ `/swagger` renders and the app builds with Razor/view compilation ON

---

## See Also
- [04-webapi-migration.md](./04-webapi-migration.md) – Web API → ASP.NET Core controllers
- [06-package-migrations.md](./06-package-migrations.md) – NuGet package replacements (Newtonsoft ↔ System.Text.Json, blocked/incompatible packages)
- [03-mvc-migration.md](./03-mvc-migration.md) – MVC controllers and result APIs
