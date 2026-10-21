# Playbook: authentication and identity

**Rules:** API-WINDOWS-IDENTITY (residue); LNX-AUTH-*, LNX-CRY-ASPNET-DATAPROTECTION-KEYS, LNX-AUTH-SQL-INTEGRATED (Linux readiness); AUTH-* (assessment).
**Engines:** DevTx KB 08 and AWS Transform move Forms authentication and `[Authorize]` to ASP.NET Core cookies. What depends on Windows (integrated auth, AD lookups, impersonation, machineKey) is a design decision Claude prepares and the user approves.

## Choose the target first

| Need | Target | Notes |
|---|---|---|
| Staff sign in with their company identity; groups come from the directory | IAM Identity Center or the client's identity provider (OIDC or SAML) | Groups arrive as claims |
| Windows users, Kerberos, or existing AD groups that the app must honour | AWS Managed Microsoft AD (with a trust if the directory stays on premises) | Keep the Negotiate path for the app; see below |
| Customers or external users in an app-owned user pool | Amazon Cognito user pools | Hosted sign-in pages or the API |
| Existing ASP.NET Identity 2 users | ASP.NET Core Identity on a backfilled schema, or the identity provider above | See the Identity 2 section |

Record the choice per application. A single application with two user populations may need two targets.

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

## Identity 2, OWIN and tokens

- **OWIN cookie middleware** (`UseCookieAuthentication`) maps to ASP.NET Core cookie authentication. Cookies do not carry over, so users sign in again at cut-over unless the keys are shared (see the forms section).
- **Identity 2 users.** The AspNetUsers, AspNetRoles and related tables can stay. ASP.NET Core Identity expects normalised user name and email columns and a concurrency stamp that Identity 2 does not have. Backfill them, then move the data context to ASP.NET Core Identity. Check the column list against the real schema.
- **Password hashes.** ASP.NET Core can verify Identity 2 hashes with its Identity V2 compatibility mode (verify the option name in your version). Rehash to the current format on each successful login, so no one has to reset a password.
- **Antiforgery.** Keep `ValidateAntiForgeryToken` on every state-changing action. The framework issues and checks the token pair. Do not build tokens by hand. The keys must persist, as above.
- **JWT for API clients.** `AddJwtBearer` with the issuer, audience and signing keys from the identity provider. Old tokens do not verify, so issue new ones at cut-over.
- **API endpoints.** On .NET 10, cookie authentication returns 401 or 403 for API endpoints instead of redirecting to a login page ([breaking-changes.md](../breaking-changes.md)).
- **Claims transformation.** A claims hook in the old pipeline maps to `IClaimsTransformation`. Keep role and group mapping there, not in controllers.

## Done when

No Windows identity APIs in code that runs on Linux; the chosen sign-in works through the ALB in the test environment; keys persist across a redeploy (sign in, redeploy, still signed in); the cut-over note for users is written.
