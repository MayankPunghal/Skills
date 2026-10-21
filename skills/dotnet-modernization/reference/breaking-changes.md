# .NET 10 breaking changes that matter for a port

A port from .NET Framework lands on .NET 10 directly, so the earlier .NET Core and .NET 5-9 changes are covered by the playbooks. This file lists the .NET 10 changes that are likely to affect a ported web app, service or desktop app, with what to do. A port that starts from .NET 8 or 9 should also read the .NET 9 list. Microsoft's pages are the full list, and the .NET one says it is still a work in progress.

## Contents
- Support dates
- ASP.NET Core
- Runtime and libraries
- Cryptography and globalization
- Serialization and networking
- SDK, NuGet and build
- Containers
- Windows Forms and WPF
- Sources

## Support dates

- .NET 8 and .NET 9 both reach end of support on 10 November 2026. An application already on 8 or 9 is not "done": plan its move to 10.
- .NET 10 is the LTS release.
- CoreWCF 1.8 reaches end of support on 24 October 2026. Use CoreWCF 1.9, which targets .NET 10 ([wcf-services.md](playbooks/wcf-services.md)).

## ASP.NET Core

| Change | Type | What to do |
|---|---|---|
| Cookie login redirects disabled for known API endpoints | Behavioral | API endpoints now return 401 or 403 instead of redirecting to the login page. Check any client or page script that followed the redirect ([auth.md](playbooks/auth.md), [web-api.md](playbooks/web-api.md)). |
| `WithOpenApi` extension method deprecated | Source | Use the built-in OpenAPI operation transformers (`AddOpenApiOperationTransformer`). The built-in generator writes OpenAPI 3.1 by default ([web-api.md](playbooks/web-api.md)). |
| `IncludeOpenAPIAnalyzers` property and MVC API analyzers deprecated | Source | Remove the property. |
| `Microsoft.Extensions.ApiDescription.Client` package deprecated | Source | Generate clients with another tool (NSwag, Kiota, openapi-generator). |
| Razor runtime compilation obsolete | Source | Use Hot Reload in development and precompiled views in the image ([mvc.md](playbooks/mvc.md)). |
| `WebHostBuilder`, `IWebHost` and `WebHost` obsolete | Source | Use `WebApplication.CreateBuilder` or the generic host ([startup-and-middleware.md](playbooks/startup-and-middleware.md)). |
| `IActionContextAccessor` and `ActionContextAccessor` obsolete | Source / behavioral | Use `IHttpContextAccessor` and endpoint metadata. |
| `IPNetwork` and `ForwardedHeadersOptions.KnownNetworks` obsolete | Source | Use `System.Net.IPNetwork` and `KnownIPNetworks` in the ALB forwarded-headers set-up. |
| Exception diagnostics suppressed when `TryHandleAsync` returns true | Behavioral | An `IExceptionHandler` that handles an exception no longer emits the diagnostics event or log. Log inside the handler if operations rely on it ([logging.md](playbooks/logging.md)). |

## Runtime and libraries

| Change | Type | What to do |
|---|---|---|
| The runtime no longer provides default termination signal handlers | Behavioral | **Verify the details.** Apps on the generic host keep their SIGTERM handling. A console app or worker without the host that relied on the runtime's default handling must register its own (`PosixSignalRegistration`). Test that the container stops cleanly ([background-work.md](playbooks/background-work.md)). |
| `DriveInfo.DriveFormat` returns Linux filesystem types | Behavioral | Code comparing it to `"NTFS"` changes. |
| `BufferedStream.WriteByte` no longer flushes implicitly | Behavioral | Call `Flush` where the old code relied on it. |
| `System.Linq.AsyncEnumerable` included in the core libraries | Source | Remove the `System.Linq.Async` package, or resolve the ambiguous calls. |
| Default trace context propagator is W3C | Behavioral | Distributed traces that used another header format need configuring ([logging.md](playbooks/logging.md)). |
| LDAP `DirectoryControl` parsing is stricter | Behavioral | Test LDAP queries that use controls (paging, sorting) ([auth.md](playbooks/auth.md)). |
| `GnuTarEntry` and `PaxTarEntry` no longer include atime and ctime by default | Behavioral | Matters only if tar output is compared byte for byte. |
| C# 14 overload resolution with span parameters | Behavioral | Rebuild and rerun the tests; calls may bind to span overloads. |
| API obsoletions (new SYSLIB IDs) | Source | Fix the warnings rather than suppressing them. |

## Cryptography and globalization

| Change | Type | What to do |
|---|---|---|
| OpenSSL 1.1.1 or later required on Unix | Behavioral | The .NET images meet it. Custom base images must too. |
| `X500DistinguishedName` validation is stricter | Behavioral | Test certificate subject parsing. |
| `X509Certificate` and `PublicKey` key parameters can be null | Behavioral / source | Add null checks where key parameters are read. |
| Environment variables renamed to `DOTNET_OPENSSL_VERSION_OVERRIDE` and `DOTNET_ICU_VERSION_OVERRIDE` | Behavioral | Update any Dockerfile or task definition that set the old names ([time-and-culture.md](playbooks/time-and-culture.md)). |

## Serialization and networking

| Change | Type | What to do |
|---|---|---|
| `XmlSerializer` no longer ignores properties marked `[Obsolete]` | Behavioral | Such properties now appear on the wire. Mark them `[XmlIgnore]` to keep the old XML, and replay the SOAP and XML goldens ([wcf-services.md](playbooks/wcf-services.md), [asmx-and-soap-clients.md](playbooks/asmx-and-soap-clients.md)). |
| System.Text.Json checks for property name conflicts | Behavioral | Types with two members mapping to the same JSON name now throw. Fix them with `[JsonPropertyName]` or `[JsonIgnore]`. |
| `MailAddress` enforces validation for consecutive dots | Behavioral | Addresses that parsed before may throw. Validate input before sending ([aws-managed-services.md](playbooks/aws-managed-services.md), SES). |
| `Uri` length limits removed | Behavioral | Add your own limit where the old one protected you. |
| HTTP/3 disabled by default with `PublishTrimmed` | Source | Only for trimmed apps that need HTTP/3. |

## SDK, NuGet and build

| Change | Type | What to do |
|---|---|---|
| `dotnet restore` audits transitive packages | Behavioral | New NU1901-NU1904 vulnerability warnings appear. With warnings-as-errors the build fails, so fix the packages ([build-and-packages.md](playbooks/build-and-packages.md)). |
| A `PackageReference` without a version raises an error | Behavioral | Give every reference a version, or use central package management. |
| NU1510 raised for direct references pruned by NuGet | Source | Remove the references the framework already provides. |
| NuGet audit sources no longer allow insecure HTTP by default | Behavioral | Move private feeds to HTTPS. |
| `dotnet new sln` creates `.slnx` | Behavioral | Tools that expect `.sln` (some CI scripts, DevTx) need an `.sln`. Pass `--format sln`. |
| `project.json` not supported in `dotnet restore` | Source | Convert any leftover `project.json`. |
| `DefineConstants` for target frameworks not available at evaluation time | Behavioral | Check project conditions that test TFM constants. |

## Containers

| Change | Type | What to do |
|---|---|---|
| Default .NET images use Ubuntu | Behavioral | Tags without a distro now pull Ubuntu. Package names in `apt-get` lines, and image size, change. Pin the distro tag you tested ([linux-and-containers.md](playbooks/linux-and-containers.md)). |

## Windows Forms and WPF

| Change | Type | What to do |
|---|---|---|
| System.Drawing `OutOfMemoryException` changed to `ExternalException` | Behavioral | Update `catch` blocks around image loading. |
| Apps referencing both WPF and WinForms must disambiguate `MenuItem` and `ContextMenu` | Source | Fully qualify the types. |
| `StatusStrip` uses the System render mode by default | Behavioral | Visual check. |
| WPF: empty `ColumnDefinitions` and `RowDefinitions` disallowed | Source | Remove the empty elements. |
| WPF: incorrect `DynamicResource` usage crashes the app | Source / behavioral | Fix the resource references the compiler now reports. |

## Sources

- [Breaking changes in ASP.NET Core 10](https://learn.microsoft.com/en-us/aspnet/core/breaking-changes/10/overview)
- [Breaking changes in .NET 10](https://learn.microsoft.com/en-us/dotnet/core/compatibility/10)
- [.NET support policy](https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core)
- [CoreWCF support policy](https://dotnet.microsoft.com/en-us/platform/support/policy/corewcf)
