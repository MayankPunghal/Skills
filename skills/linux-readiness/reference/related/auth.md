# Playbook: authentication and identity

> Copied from the dotnet-modernization skill (`reference/playbooks/auth.md`) as related reading for the fix guide in SKILL.md. Rule IDs other than `LNX-*` (residue, assessment) belong to the other skills; `verify.py` is the dotnet-modernization gate runner. Keep this copy in step with the original.

**Rules:** API-WINDOWS-IDENTITY (residue); LNX-AUTH-*, LNX-CRY-ASPNET-DATAPROTECTION-KEYS, LNX-AUTH-SQL-INTEGRATED (Linux readiness); AUTH-* (assessment).
**Engines:** DevTx KB 08 and AWS Transform move Forms authentication and `[Authorize]` to ASP.NET Core cookies. What depends on Windows (integrated auth, AD lookups, impersonation, machineKey) is a design decision Claude prepares and the user approves.

## Forms authentication and machineKey

- `FormsAuthentication` → `AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme).AddCookie(...)`; `FormsAuthentication.SetAuthCookie` → `HttpContext.SignInAsync` with a `ClaimsPrincipal`; `User.Identity.Name` still works.
- Cookies issued by the old app cannot be read by the new one unless both share keys: either one forced re-login at cut-over (simplest, tell the business) or shared data protection with the old app using the System.Web adapters' machineKey compatibility (incremental moves).
- **Data protection keys** must persist outside the container when there is more than one task or any restart: `PersistKeysToAWSSystemsManager` / S3 + `ProtectKeysWithAwsKms` (AWS packages), or a shared file system. Without it every deployment signs users out and antiforgery tokens fail across tasks.
- ASP.NET Membership / `SqlMembershipProvider` → ASP.NET Core Identity with a migration of the user table, or the client's identity provider; password hashes need a rehash-on-login plan.

## Windows authentication and AD

A Linux container has no domain membership. Options, in order of preference:
1. **An identity provider** (Entra ID, Okta, Cognito, ADFS) with OIDC or SAML; the app trusts tokens, groups come as claims.
2. **Kerberos (Negotiate) on Linux**: `AddAuthentication(NegotiateDefaults.AuthenticationScheme).AddNegotiate()` with a keytab and a service principal, `krb5.conf` in the image; works but needs AD admin work per environment.
3. Keep that one app on Windows (a recorded decision).

`WindowsIdentity.Impersonate`, `WindowsPrincipal.IsInRole` → claims-based checks; file or database access that relied on the app pool identity → IAM roles (task role), database logins, or IAM database auth.

LDAP lookups (`System.DirectoryServices`): `System.DirectoryServices.Protocols` (`LdapConnection`) works on Linux with `libldap` in the image; `DirectoryEntry`/`DirectorySearcher` do not.

## Integrated security to databases

`Integrated Security=SSPI` / `Trusted_Connection=True` → SQL authentication with the secret in Secrets Manager, or IAM authentication for RDS PostgreSQL; Kerberos to SQL Server from Linux only with a keytab. The connection string never carries the password in config.

## Done when

No Windows identity APIs in code that runs on Linux; the chosen sign-in works through the ALB in the test environment; keys persist across a redeploy (sign in, redeploy, still signed in); the cut-over note for users is written.
