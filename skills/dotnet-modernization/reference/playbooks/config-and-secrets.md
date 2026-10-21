# Playbook: configuration and secrets

**Rules:** API-CONFIGMANAGER, CFG-TRANSFORMS (engine), CFG-PROTECTED-SECTION, CFG-HARDCODED-SECRET, AUTH-MACHINEKEY,
LS-LOCALHOST-SERVICE, LS-CLIENT-IP-LOGIC (assessment); CFG-WEBCONFIG-APP, CFG-PROTECTED, CFG-CONFIGMANAGER (residue).
**Engines:** DevTx KB 11 and AWS Transform move appSettings / connectionStrings to appsettings.json. Protected sections,
secrets, custom sections and environment layering are Claude's.

## Steps

1. **Map every setting**: appSettings keys, connectionStrings, custom `configSections`, `configSource` / `file=`
   includes, web.config transforms (`Web.Release.config`), and settings read in code that are not in any config file.
2. **Target layout**: `appsettings.json` (defaults, no secrets) → `appsettings.{Environment}.json` → environment variables
   (`Section__Key`) → AWS Secrets Manager / Parameter Store for secrets. Transforms become per-environment files or
   environment variables in the task definition.
3. **Protected sections** (`configProtectionProvider`, DPAPI / RSA machine keys): they cannot be decrypted in a Linux
   container. Ask the owner for the plain values through a secure channel or decrypt on the old server
   (`aspnet_regiis -pdf`) into Secrets Manager. Never commit the decrypted values; never print them in logs or reports.
4. **Code**: `ConfigurationManager.AppSettings["X"]` → `IOptions<T>` bound to a section (preferred) or `IConfiguration`.
   For a large library still shared with .NET Framework callers, `System.Configuration.ConfigurationManager` (package)
   works on .NET 10 reading `app.config`; plan its removal, do not rely on it in the container.
5. **Custom sections** (`IConfigurationSectionHandler`, `ConfigurationSection`) → POCOs bound with `Bind` / `Configure<T>`.
6. **machineKey**: if forms-auth cookies, ViewState or encrypted values must stay readable across the move, keep the
   key material in Secrets Manager and use the ASP.NET Core data-protection compatibility (`Microsoft.AspNetCore.DataProtection.SystemWeb`
   / `AspNetTicketDataFormat`); otherwise users sign in again once (announce it).
7. **Localhost and client IP logic**: a call to `localhost` assumed a service on the same server — make it a configured
   URL. Client IP read from `REMOTE_ADDR` is the load balancer behind AWS: use `ForwardedHeaders` middleware with the
   known proxies set.
8. **Feature flags.** `web.config` booleans that switch features, and `Microsoft.FeatureManagement` settings, move to AWS AppConfig feature flags. AppConfig has a feature-flag profile type. A .NET configuration provider for it is not confirmed (verify). Until one is confirmed, read flags through a small `IFeatureFlags` interface, so the source can change in one place. `Microsoft.FeatureManagement` reads `IConfiguration`, so it works once its values come through a provider (verify).

## Done when

No CFG-PROTECTED residue; no secret in any appsettings file or image layer; the app starts with only environment
variables and Secrets Manager in a clean container.
