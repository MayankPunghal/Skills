# Playbook: Windows-only APIs (and desktop apps)

**Rules:** API-COM, API-REGISTRY, API-PERFCOUNTER, API-PINVOKE, API-DRAWING, API-WEAK-CRYPTO, API-ENTERPRISESERVICES (residue); LNX-API-*, LNX-CRY-*, LNX-IPC-* (Linux readiness).
**Engines:** both engines move packages and flag CA1416; DevTx KB 21 (System.Drawing) and 22 (crypto) guide replacements. Choosing what replaces a Windows feature is Claude's job, with the user where it is a decision.

## The rule

Code that must run in a Linux container cannot call a Windows-only API, even behind a package that compiles (the Windows Compatibility Pack compiles everywhere and throws `PlatformNotSupportedException` at run time). Turn on the platform analyzer (CA1416 is on by default for `net5.0+`) and treat its warnings as errors in the ported projects. `OperatingSystem.IsWindows()` guards are for code that genuinely runs on both, not a way to silence the analyzer.

## Replacements

| Windows feature | Linux replacement |
|---|---|
| Registry (`Microsoft.Win32.Registry`) | Configuration (`appsettings.json`, environment variables, Parameter Store) |
| COM interop, `Type.GetTypeFromProgID`, Office automation | A managed library (Open XML SDK, ClosedXML for Excel), a vendor SDK, or a separate Windows service called over HTTP (decision) |
| COM+ / `System.EnterpriseServices` | Redesign: plain classes; transactions per connection; queue work through SQS |
| P/Invoke to Windows DLLs (`kernel32`, `user32`, `advapi32`) | The managed API that does the same (`Environment`, `Process`, `File`), or a Linux build of the native library |
| `PerformanceCounter` | `System.Diagnostics.Metrics` / EventCounters, exported to CloudWatch (OpenTelemetry) |
| `EventLog` | Structured logs to stdout ([logging.md](logging.md)) |
| WMI (`System.Management`) | `/proc` and `Environment` data, or drop it (container metadata comes from ECS) |
| System.Drawing (GDI+) | SkiaSharp or ImageSharp (licence check); install fonts in the image ([linux-and-containers.md](linux-and-containers.md)) |
| `DPAPI` (`ProtectedData`), machine certificate store | ASP.NET Core Data Protection with keys in S3/SSM + KMS; certificates from files or Secrets Manager |
| `RSACng`, `CngKey`, `DESCryptoServiceProvider`, RC2, weak hashes | `RSA.Create()`, `Aes.Create()`; data encrypted with DES/3DES/RC2 needs a decrypt-old / encrypt-new plan agreed with the owner |
| `RSACryptoServiceProvider` (from a cast of `X509Certificate2.PrivateKey`), `SHA256Managed`, `AesManaged`, `RijndaelManaged`, `RNGCryptoServiceProvider` | `cert.GetRSAPrivateKey()` (dispose the key), `SHA256.Create()`, `Aes.Create()`, `RandomNumberGenerator` |
| `Rfc2898DeriveBytes` (PBKDF2) | `Rfc2898DeriveBytes.Pbkdf2(...)` with the same hash algorithm, iteration count and salt. The constructors that do not name a hash use SHA-1 and are obsolete (verify) |
| Named mutexes / semaphores, named pipes, memory-mapped files across processes | In one container: in-process primitives; across tasks: a distributed lock (ElastiCache, DynamoDB) or a queue |
| `ServiceBase` (Windows services) | `BackgroundService` ([background-work.md](background-work.md)) |
| Windows identity, impersonation | [auth.md](auth.md) |

Stored values keep working only if the parameters match. Keep the old hash, iteration count, salt and key for data already stored, and use the new calls for new data. Passwords are rehashed on the next successful login ([auth.md](auth.md)).

**Image libraries.** ImageSharp 4 and ImageSharp.Web 4 need a Six Labors licence key at build time, and the build fails without one. Keep the key in the CI secret store, pass it at build time, and never commit it. Core 4.x is reported to fail Release builds without a key (verify). For SkiaSharp, the `SKFilterQuality` overloads are obsolete: use `SKSamplingOptions` (check the version you pin).

## Desktop apps (WinForms, WPF)

Windows-only on every .NET version. Options for the plan, a decision for the client: port to .NET 10 and keep on Windows (least change); stream to a browser with Amazon WorkSpaces Applications (formerly AppStream 2.0) with no code change; rewrite the UI for the web (Blazor), reusing view models and services; Avalonia for a Linux desktop. Shared libraries they use still move to `netstandard2.0`/`net10.0` so the web side can use them.

**Deployment.** ClickOnce publishing for .NET 5 and later desktop apps is available from Visual Studio 2019 16.8 onward (verify in the current Visual Studio docs). A legacy sample page says the `ApplicationDeployment` API is not available on .NET 5 and later, so update checks written against it need a redesign (verify). Installers (WiX, MSI) and Authenticode signing are Windows tools: plan the build machine for them.

**Other desktop resources.** Satellite resource assemblies: check that the publish output keeps each culture folder next to the main assembly. Serial ports: `System.IO.Ports` works on Linux, but port names change (`COM3` becomes a device path such as `/dev/ttyUSB0`), so test on the target hardware. Named pipes: Windows pipe security does not carry over, so test the permissions on each platform.

## Done when

No API-* residue in code that runs on Linux; CA1416 clean as errors; each replaced feature has a test or a replayed golden; desktop apps have a recorded decision.
