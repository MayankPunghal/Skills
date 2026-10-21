# 21 – System.Drawing.Common Migration (.NET 8 / .NET 10)

## Overview
`System.Drawing.Common` worked everywhere on .NET Framework. On modern .NET it is **Windows-only** — calling it on Linux or macOS throws `PlatformNotSupportedException` at runtime. Server-side image processing (thumbnails, watermarks, format conversion) running in a Linux container is the most common breakage. The migration target is either `SkiaSharp` or `SixLabors.ImageSharp`, depending on licensing and feature requirements.

For Windows-only apps (WinForms, WPF, services running on Windows), `System.Drawing.Common` continues to work — no migration needed.

> **Package versions:** `SkiaSharp` and `SixLabors.ImageSharp` are third-party packages versioned independently of the .NET runtime — they are **not** tied to the `net8.0`/`net10.0` major. The versions below are the latest stable at the time of writing and work on both .NET 8 and .NET 10; use the current latest stable when you migrate.

---

## Step 1: Identify the platform constraint

Check whether the project actually deploys on a non-Windows platform. The decision tree:

| Deployment | Action |
|---|---|
| Windows desktop (WinForms / WPF) | Keep `System.Drawing.Common`; no change |
| Windows server (IIS, Windows Service) | Keep `System.Drawing.Common`; no change |
| Linux container / Linux VM | Migrate to `SkiaSharp` or `SixLabors.ImageSharp` |
| macOS | Migrate to `SkiaSharp` (which has a native macOS build) or `SixLabors.ImageSharp` |
| AWS Lambda | Migrate (Lambda runs Linux); `SkiaSharp` is the safer choice for cold-start size |

---

## Step 2: Replace the package reference

### Before
```xml
<PackageReference Include="System.Drawing.Common" Version="6.0.0" />
```

### After (SkiaSharp)
```xml
<ItemGroup>
  <PackageReference Include="SkiaSharp" Version="4.150.1" />
  <PackageReference Include="SkiaSharp.NativeAssets.Linux" Version="4.150.1" />     <!-- only if deploying to Linux -->
</ItemGroup>
```

### After (ImageSharp)
```xml
<PackageReference Include="SixLabors.ImageSharp" Version="3.1.5" />
```

> **Default to SkiaSharp for automated / unattended migrations.** `SkiaSharp` is **MIT**-licensed with no build-time gating, so it always builds in CI without extra configuration. Only choose ImageSharp when a specific ImageSharp feature is required and the licensing below has been handled.

Notes on ImageSharp licensing:
- **Split License:** `SixLabors.ImageSharp` (3.x and 4.x) is distributed under the **Six Labors Split License** — free for open-source projects and small organizations, but a paid commercial license is required for organizations above their published revenue threshold. Check `https://sixlabors.com/pricing/` before adopting.
- **Build-time license key (4.0+):** ImageSharp **4.0** is the first release to *enforce* a license key at **build time** for projects that reference it directly. In an automated migration with no key configured, a `4.0.0` reference fails the build. This guide therefore pins the **3.1.x** line, which carries no build-time key requirement. Only move to 4.x if a Six Labors commercial license key is already provisioned and wired into the build.

---

## Step 3: Translate the most common `System.Drawing` operations

### Before (System.Drawing)
```csharp
using System.Drawing;
using System.Drawing.Imaging;

using var src = Image.FromFile("input.png");
using var thumb = new Bitmap(src, new Size(128, 128));
thumb.Save("thumb.jpg", ImageFormat.Jpeg);
```

### After (SkiaSharp)
```csharp
using SkiaSharp;

using var input = SKBitmap.Decode("input.png");
// SKFilterQuality is obsolete in modern SkiaSharp (removed in v4) — use SKSamplingOptions.
// SKCubicResampler.Mitchell is the high-quality equivalent of the old SKFilterQuality.High.
using var resized = input.Resize(new SKImageInfo(128, 128), new SKSamplingOptions(SKCubicResampler.Mitchell));
using var img = SKImage.FromBitmap(resized);
using var data = img.Encode(SKEncodedImageFormat.Jpeg, 90);
using var fs = File.OpenWrite("thumb.jpg");
data.SaveTo(fs);
```

### After (ImageSharp)
```csharp
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Processing;

using var image = await Image.LoadAsync("input.png");
image.Mutate(x => x.Resize(128, 128));
await image.SaveAsJpegAsync("thumb.jpg");
```

---

## Step 4: Validation Checklist

✅ Migration decision recorded — "Migrate `System.Drawing.Common` call sites to SkiaSharp" or "to ImageSharp" — with the rationale (deployment target / licensing)  
✅ For Windows-only deployments: no migration required; `System.Drawing.Common` is still in `<PackageReference>` and the integration tests pass on Windows  
✅ For cross-platform deployments: every call site to `System.Drawing.*` is rewritten; integration tests run on Linux (or the deployment platform) and produce visually-identical output  
✅ No obsolete `SKFilterQuality` usage remains (SkiaSharp path); resizing uses `SKSamplingOptions`  
✅ Native assets package (`SkiaSharp.NativeAssets.Linux`) is referenced when Linux is a target platform

---

## See Also
- [00-prebuild-cleanup-and-bulk-fixes.md](./00-prebuild-cleanup-and-bulk-fixes.md) – Prebuild cleanup and bulk fixes
- [19-linux-containerization.md](./19-linux-containerization.md) – Why Windows-only APIs break in Linux containers
- [06-package-migrations.md](./06-package-migrations.md) – NuGet package replacements
