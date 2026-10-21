# Playbook: Windows-only APIs (and desktop apps)

> Copied from the dotnet-modernization skill (`reference/playbooks/windows-only-apis.md`) as related reading for the fix guide in SKILL.md. Rule IDs other than `LNX-*` (residue, assessment) belong to the other skills; `verify.py` is the dotnet-modernization gate runner. Keep this copy in step with the original.

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
| `EventLog` | Structured logs to stdout (the logging playbook of the dotnet-modernization skill) |
| WMI (`System.Management`) | `/proc` and `Environment` data, or drop it (container metadata comes from ECS) |
| System.Drawing (GDI+) | SkiaSharp or ImageSharp (licence check); install fonts in the image ([linux-and-containers.md](linux-and-containers.md)) |
| `DPAPI` (`ProtectedData`), machine certificate store | ASP.NET Core Data Protection with keys in S3/SSM + KMS; certificates from files or Secrets Manager |
| `RSACng`, `CngKey`, `DESCryptoServiceProvider`, RC2, weak hashes | `RSA.Create()`, `Aes.Create()`; data encrypted with DES/3DES/RC2 needs a decrypt-old / encrypt-new plan agreed with the owner |
| Named mutexes / semaphores, named pipes, memory-mapped files across processes | In one container: in-process primitives; across tasks: a distributed lock (ElastiCache, DynamoDB) or a queue |
| `ServiceBase` (Windows services) | `BackgroundService` (the background-work playbook of the dotnet-modernization skill) |
| Windows identity, impersonation | [auth.md](auth.md) |

## Desktop apps (WinForms, WPF)

Windows-only on every .NET version. Options for the plan, a decision for the client: port to .NET 10 and keep on Windows (least change); stream to a browser with Amazon WorkSpaces Applications (formerly AppStream 2.0) with no code change; rewrite the UI for the web (Blazor), reusing view models and services; Avalonia for a Linux desktop. Shared libraries they use still move to `netstandard2.0`/`net10.0` so the web side can use them.

## Done when

No API-* residue in code that runs on Linux; CA1416 clean as errors; each replaced feature has a test or a replayed golden; desktop apps have a recorded decision.
