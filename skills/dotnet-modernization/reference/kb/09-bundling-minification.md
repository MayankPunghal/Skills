# 09 – Bundling and Static Assets Migration (.NET 8 / .NET 10)

## Overview
ASP.NET's `Microsoft.AspNet.Web.Optimization` package (`BundleConfig.cs`, `<%: Scripts.Render(...) %>`) was never ported to ASP.NET Core. The replacement is an explicit front-end build step using a JS-ecosystem bundler (esbuild, webpack, vite, rollup), producing pre-built static assets that ASP.NET Core's static-files middleware serves directly.

This is the canonical example of a "toolchain change" — there is no NuGet drop-in; the build pipeline itself moves from runtime bundling to compile-time bundling.

---

## Step 1: Pick a bundler

| Option | When it fits |
|---|---|
| esbuild (fastest) | **Default choice.** When the front-end is straightforward (JS + CSS, no React/TypeScript build) |
| webpack (most flexible) | When the front-end already uses npm dependencies or transpilation (TypeScript, Babel, JSX) |
| vite | When the front-end is moving to ES modules / a modern dev-server experience |
| rollup | Library-style bundling of ES modules |
| `dotnet bundle` (BundlerMinifier) | **Not recommended — unmaintained.** BundlerMinifier is community-maintained, archived, and was removed from the .NET templates; it is no longer supported. Only keep an existing setup limping along short-term — do not adopt it for a new migration. |

For most line-of-business migrations from Web Forms / MVC 5, `esbuild` is the lowest-friction choice. Treat this as a pick-one decision and record the choice (with rationale) in the upgrade analysis open questions.

---

## Step 2: Remove `Microsoft.AspNet.Web.Optimization` and `BundleConfig.cs`

### Before
```csharp
// App_Start/BundleConfig.cs
public class BundleConfig
{
    public static void RegisterBundles(BundleCollection bundles)
    {
        bundles.Add(new ScriptBundle("~/bundles/jquery").Include(
            "~/Scripts/jquery-{version}.js"));

        bundles.Add(new StyleBundle("~/Content/css").Include(
            "~/Content/bootstrap.css",
            "~/Content/site.css"));
    }
}

// Global.asax.cs
BundleConfig.RegisterBundles(BundleTable.Bundles);
```

```html
<!-- _Layout.cshtml -->
@Scripts.Render("~/bundles/jquery")
@Styles.Render("~/Content/css")
```

### After
```
src/Contoso.Web/wwwroot/dist/jquery.bundle.min.js     (built by esbuild / webpack)
src/Contoso.Web/wwwroot/dist/site.bundle.min.css      (built by esbuild / webpack)
```

```html
<!-- _Layout.cshtml -->
<link rel="stylesheet" href="~/dist/site.bundle.min.css" asp-append-version="true" />
<script src="~/dist/jquery.bundle.min.js" asp-append-version="true"></script>
```

The `asp-append-version` tag helper appends a content-hash query string for cache busting — replacing the `?v=...` query string the runtime bundler used to generate.

---

## Step 3: Wire the bundler into the .NET build

The bundler runs as a pre-build step so `dotnet build` and CI both produce a deployable site without a separate manual step.

### Example (esbuild via npm script)
```xml
<!-- Contoso.Web.csproj -->
<Target Name="EsbuildBundle" BeforeTargets="Build">
  <Exec Command="npm install" WorkingDirectory="$(MSBuildProjectDirectory)" />
  <Exec Command="npm run build" WorkingDirectory="$(MSBuildProjectDirectory)" />
</Target>
```

```json
// package.json
{
  "scripts": {
    "build": "esbuild src/site.js --bundle --minify --outfile=wwwroot/dist/site.bundle.min.js"
  },
  "devDependencies": {
    "esbuild": "0.24.0"
  }
}
```

---

## Step 4: Configure ASP.NET Core to serve static files

`UseStaticFiles` is added to `Program.cs` if it isn't there already. Cache control should be tuned for the hashed-asset output of the bundler.

### After
```csharp
// Program.cs
var app = builder.Build();

app.UseStaticFiles(new StaticFileOptions
{
    OnPrepareResponse = ctx =>
    {
        // dist/* assets are content-hashed by the bundler; safe to cache aggressively
        if (ctx.File.Name.Contains(".bundle."))
        {
            ctx.Context.Response.Headers.Append("Cache-Control", "public, max-age=31536000, immutable");
        }
    }
});

app.UseRouting();
// ...
```

> `UseStaticFiles` on its own does **not** compress responses — it only serves bytes with the headers you set. Compression must be configured separately (below).

### .NET 10 target — prefer `MapStaticAssets`
On .NET 10, replace `UseStaticFiles` for framework-served assets with `MapStaticAssets`. At publish time it fingerprints each asset and emits **precompressed gzip + brotli** copies, then serves them with `Content-Encoding` negotiation and immutable caching automatically — so you don't hand-roll `OnPrepareResponse` cache headers or a separate compression step:
```csharp
// Program.cs (.NET 10)
var app = builder.Build();
app.MapStaticAssets();   // fingerprinting + gzip/brotli precompression + immutable caching, automatic
app.UseRouting();
// ...
```
With `MapStaticAssets`, reference assets through the generated fingerprinted paths (the `@Assets[...]` helper / import map) instead of `asp-append-version`.

### .NET 8 target — compression is not automatic
`UseStaticFiles` on .NET 8 does not compress. Either serve precompressed `.gz`/`.br` files, add Response Compression middleware, or — most common in production — let the reverse proxy / CDN (nginx, CloudFront, etc.) do it. In-process option:
```csharp
// Program.cs (.NET 8)
builder.Services.AddResponseCompression(o => o.EnableForHttps = true);
// ...
app.UseResponseCompression();
app.UseStaticFiles(/* cache headers as above */);
```
Text assets (JS/CSS) compress well; leave already-compressed formats (png, woff2) as-is.

---

## Step 5: Validation Checklist

✅ `Microsoft.AspNet.Web.Optimization` is removed from every `<PackageReference>`; `BundleConfig.cs` is deleted  
✅ A bundler choice is recorded (upgrade analysis open questions): `esbuild`, `webpack`, `vite`, or `rollup` (not `dotnet bundle` — unmaintained)  
✅ The bundler runs as part of `dotnet build` (no separate manual step required for CI or developers)  
✅ Bundled assets are emitted under `wwwroot/dist/` (or another path served by `UseStaticFiles`) and referenced via `<link>` / `<script>` tags with `asp-append-version`  
✅ Browser DevTools confirm assets are content-hashed and served with `Cache-Control: public, max-age=31536000, immutable`  
✅ Compression is configured and confirmed in DevTools (`Content-Encoding: br` or `gzip`): automatic via `MapStaticAssets` on .NET 10, or via Response Compression middleware / reverse proxy / CDN on .NET 8

---

## See Also
- [15-views-static-files-migration.md](./15-views-static-files-migration.md) – Razor views and static files
- [06-package-migrations.md](./06-package-migrations.md) – removing legacy packages
- [01-project-file-migration.md](./01-project-file-migration.md) – SDK-style project and build targets
