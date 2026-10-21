> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Audit Linux readiness coverage

agent aa1a19a208ab785a2

Read-only audit. No files were created, edited or deleted.

Verdict: the 240-check catalogue covers the bulk of the list (ICU/culture, time zones, path case and separators, processes/shell, DPAPI, Windows auth, IIS hosting, registry/EventLog/PerfCounter, System.Drawing, CA1416, containers, ALB forwarded headers, read-only root). Consistency checks pass: both copies of linux_readiness.json and linux_readiness.py are byte-identical; the counts match the doc (130 block / 91 warn / 19 info; 221 automated; 91 K-sourced). Partial only: Environment.NewLine (split only), Console I/O (ReadKey only), health endpoint presence, ephemeral local writes (the assessment has FILE-LOCAL-WRITE; the catalogue does not), Unix socket path length (no check, low).

Missing checks (highest impact first)

1. Kestrel bound to loopback. block. `ASPNETCORE_URLS` or `UseUrls` set to localhost/127.0.0.1 means the ALB cannot reach the app. Detect: `ASPNETCORE_URLS\s*[=:]\s*"?http://(localhost|127\.0\.0\.1)` in Dockerfile, yml, task JSON, appsettings; `UseUrls\(\s*"http://(localhost|127\.0\.0\.1)` in cs. Source: https://learn.microsoft.com/en-us/aspnet/core/fundamentals/servers/kestrel/endpoints (localhost binds the IPv4 and IPv6 loopback only).
2. Long-lived HttpClient without PooledConnectionLifetime. warn. Stale DNS after ALB, RDS or task IP changes. Detect: cs file with `new\s+HttpClient\(|SocketsHttpHandler`, `unless_in_file: PooledConnectionLifetime`. Source: https://learn.microsoft.com/en-us/dotnet/fundamentals/networking/http/httpclient-guidelines ("HttpClient only resolves DNS entries when a connection is created").
3. ECS on EC2 bridge mode with IMDS hop limit 1. warn. Detect: task JSON `"networkMode"\s*:\s*"bridge"` plus cs `169\.254\.169\.254` or instance-profile credential use; the hop limit itself is a checklist item. Source: https://www.latacora.com/blog/2025/10/02/ecs-on-ec2-covering-gaps-in-imds-hardening/ (secondary; I did not fetch the AWS IMDS page).
4. No init process (zombie reaping, signal forwarding). warn. Detect: task JSON container without `"initProcessEnabled"\s*:\s*true`; Dockerfile without an init. Source: https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_LinuxParameters.html. The page does not state Fargate support: verify.
5. Case-sensitive search patterns. warn. `Directory.GetFiles`/`EnumerateFiles` with an uppercase or mixed-case extension (`*.XML`) matches nothing on Linux, because MatchCasing defaults to the temp folder's case sensitivity. Detect: `(GetFiles|EnumerateFiles)\([^;]*"[^"]*\.[^"]*[A-Z][^"]*"`. Sources: https://learn.microsoft.com/en-us/dotnet/api/system.io.enumerationoptions.matchcasing and https://learn.microsoft.com/en-us/dotnet/api/system.io.directory.getfiles. The three-character prefix match (`*.xls` also matching `.xlsx`) was .NET Framework only; info-level migration note.
6. LDAP via System.DirectoryServices.Protocols needs OpenLDAP libldap in the image. warn, verify. Detect: cs `System\.DirectoryServices\.Protocols|LdapConnection`; Dockerfile `file_lacks: libldap`. No official Microsoft source found; the only evidence is community material, so treat as inference.

Wrong or out of date

- LNX-CTR-LIBGDIPLUS: `System.Drawing.EnableUnixSupport` existed only in .NET 6 and was removed in .NET 7, so on .NET 7+ libgdiplus is not a fix. The rule should say "replace with SkiaSharp/ImageSharp" for .NET 7+. Source: https://learn.microsoft.com/en-us/dotnet/core/compatibility/core-libraries/6.0/system-drawing-common-windows-only
- LNX-CUL-INVARIANT-MODE: the text "CultureInfo("de-DE") behaves as invariant" does not match the docs, which say invariant mode restricts culture creation (PredefinedCulturesOnly). Reword. Source: https://learn.microsoft.com/en-us/dotnet/core/runtime-config/globalization
- Invariant env-var detection (CUL-INVARIANT-MODE) only scans df and yml, so ECS task-definition JSON (`"name": "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT", "value": "1"`) is missed. Add a task-JSON file kind.
- LNX-HOST-PORT-80 is `automated: false` even though it has patterns with no file types, so the block never fires. Add file types for Dockerfile, yml and task JSON.
- LNX-PROC-NO-HOST-LIFETIME: the detect text says "Program.cs with no IHost", but the regex flags any `while (true)` and `Console.ReadLine()` in any .cs file. Implement the stated condition or lower the noise.
- LNX-API-DLLIMPORT-DLL-SUFFIX is sourced as "K". The Microsoft native-library-loading page covers it (https://learn.microsoft.com/en-us/dotnet/standard/native-interop/native-library-loading): on Linux the runtime tries `name.dll.so`, `libname.dll.so`, `name.dll`, then `libname.dll`. The rule holds; give it an S-number.
- Playbook time-and-culture.md says "Alpine and chiseled images lack tzdata (and chiseled lacks ICU)". Per https://github.com/dotnet/dotnet-docker/blob/main/documentation/image-variants.md, neither Alpine nor chiseled includes ICU or tzdata by default; only the -extra variants do.
- linux-pitfalls.md cites `FILE-CASE-MISMATCH`, which does not exist in modernization-assessment rules.json (the case checks are LNX-FS-CASE-* in linux_readiness.json only).
