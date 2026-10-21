# 08 – Authentication and Security Migration (.NET 8 / .NET 10)

## Overview
The OWIN/Katana hosting model (`Microsoft.Owin.*`, `Owin.IAppBuilder`, `Startup.Auth.cs`) and ASP.NET Identity 2.x (`Microsoft.AspNet.Identity.*`) are replaced on modern .NET by ASP.NET Core authentication middleware (`Microsoft.AspNetCore.Authentication.*`) and ASP.NET Core Identity (`Microsoft.AspNetCore.Identity.*`). The data model maps closely — the same `AspNet*` tables — but an existing Identity 2.x database needs a schema migration (see Step 3), not a drop-in swap; the wiring code is a full rewrite.

---

## Step 1: Replace OWIN packages with ASP.NET Core authentication packages

### Before
```xml
<PackageReference Include="Microsoft.Owin" Version="4.2.2" />
<PackageReference Include="Microsoft.Owin.Host.SystemWeb" Version="4.2.2" />
<PackageReference Include="Microsoft.Owin.Security" Version="4.2.2" />
<PackageReference Include="Microsoft.Owin.Security.Cookies" Version="4.2.2" />
<PackageReference Include="Microsoft.Owin.Security.OAuth" Version="4.2.2" />
<PackageReference Include="Microsoft.AspNet.Identity.EntityFramework" Version="2.2.4" />
<PackageReference Include="Microsoft.AspNet.Identity.Owin" Version="2.2.4" />
```

### After
```xml
<PackageReference Include="Microsoft.AspNetCore.Authentication.Cookies" Version="8.0.10" />
<PackageReference Include="Microsoft.AspNetCore.Authentication.JwtBearer" Version="8.0.10" />
<PackageReference Include="Microsoft.AspNetCore.Identity.EntityFrameworkCore" Version="8.0.10" />
```

> **Version note:** the `8.0.10` pins above are illustrative (`net8.0`). Use the package major
> version that matches the configured target framework — e.g. `10.0.x` for `net10.0`. These
> `Microsoft.AspNetCore.*` packages version in lockstep with the SDK, so mixing an `8.0.x` pin
> into a `net10.0` project causes downgrade/restore (NU1605) errors. Third-party packages (e.g.
> `Sustainsys.Saml2.AspNetCore2` in Step 8) must be pinned to a version that supports the target
> TFM; if none exists, treat it as a blocked/incompatible package (see
> [06-package-migrations.md](./06-package-migrations.md)) and confirm before cutover.

---

## Step 2: Replace `Startup.Auth.cs` with `Program.cs` registrations

OWIN registered authentication via `app.UseCookieAuthentication(...)` in a partial `Startup` class. ASP.NET Core registers it via `builder.Services.AddAuthentication(...)` in `Program.cs`, then activates it via `app.UseAuthentication()`.

### Before
```csharp
// Startup.Auth.cs
public partial class Startup
{
    public void ConfigureAuth(IAppBuilder app)
    {
        app.UseCookieAuthentication(new CookieAuthenticationOptions
        {
            AuthenticationType = DefaultAuthenticationTypes.ApplicationCookie,
            LoginPath = new PathString("/Account/Login"),
            Provider = new CookieAuthenticationProvider
            {
                OnValidateIdentity = SecurityStampValidator.OnValidateIdentity<UserManager<ApplicationUser>, ApplicationUser>(
                    validateInterval: TimeSpan.FromMinutes(30),
                    regenerateIdentity: (manager, user) => user.GenerateUserIdentityAsync(manager))
            }
        });
    }
}
```

### After
```csharp
// Program.cs
builder.Services
    .AddDbContext<ApplicationDbContext>(opts => opts.UseSqlServer(connStr))
    .AddIdentity<ApplicationUser, IdentityRole>(opts =>
    {
        opts.SignIn.RequireConfirmedEmail = true;
        opts.Password.RequireDigit = true;
    })
    .AddEntityFrameworkStores<ApplicationDbContext>()
    .AddDefaultTokenProviders();

builder.Services.ConfigureApplicationCookie(opts =>
{
    opts.LoginPath = "/Account/Login";
    opts.ExpireTimeSpan = TimeSpan.FromHours(8);
    opts.SlidingExpiration = true;
});

var app = builder.Build();
app.UseAuthentication();
app.UseAuthorization();
```

---

## Step 3: Migrate `IdentityUser` and `IdentityDbContext`

The `ApplicationUser : IdentityUser` and `ApplicationDbContext : IdentityDbContext<ApplicationUser>` classes survive almost unchanged; they just inherit from the ASP.NET Core Identity types instead of the legacy ones.

### Before
```csharp
using Microsoft.AspNet.Identity.EntityFramework;

public class ApplicationUser : IdentityUser
{
    public string DisplayName { get; set; }
}

public class ApplicationDbContext : IdentityDbContext<ApplicationUser>
{
    public ApplicationDbContext() : base("ContosoConnection") { }
}
```

### After
```csharp
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Identity.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore;

public class ApplicationUser : IdentityUser
{
    public string? DisplayName { get; set; }
}

public class ApplicationDbContext : IdentityDbContext<ApplicationUser>
{
    public ApplicationDbContext(DbContextOptions<ApplicationDbContext> options)
        : base(options) { }
}
```

The `ApplicationUser` / `ApplicationDbContext` **code** ports almost unchanged, but the EF Core Identity **schema is not identical** to the ASP.NET Identity 2.x schema — an existing database **requires a schema migration**, it is not a drop-in swap. Password hashes remain verifiable (the ASP.NET Core `PasswordHasher` recognizes the legacy format marker and rehashes on next sign-in, so users are not forced to reset passwords), and existing rows in `AspNetUsers` / `AspNetRoles` / `AspNetUserClaims` carry over. What differs:

- **New normalized lookup columns** — `AspNetUsers.NormalizedUserName`, `AspNetUsers.NormalizedEmail`, and `AspNetRoles.NormalizedName`. These must be **backfilled** on the existing data (e.g. `UPDATE AspNetUsers SET NormalizedUserName = UPPER(UserName), NormalizedEmail = UPPER(Email);`), otherwise `FindByNameAsync` / `FindByEmailAsync` return nothing.
- **New `ConcurrencyStamp` columns** on `AspNetUsers` and `AspNetRoles` (populate with a fresh GUID or allow null).
- **Lockout column change** — 2.x `LockoutEndDateUtc` (`datetime`) becomes `LockoutEnd` (`datetimeoffset`): a column rename plus a type change.

Generate an EF Core migration against the modern Identity model, reconcile it with the current table shape (add the new columns, rename/convert `LockoutEnd`), and run the one-time normalized-column backfill before cutover.

---

## Step 4: Replace the `UserManager` / `SignInManager` access pattern

OWIN-era code resolved `UserManager<ApplicationUser>` from `HttpContext.GetOwinContext().GetUserManager<...>()`. ASP.NET Core uses standard constructor injection.

### Before
```csharp
public class AccountController : Controller
{
    private ApplicationUserManager UserManager =>
        HttpContext.GetOwinContext().GetUserManager<ApplicationUserManager>();

    [HttpPost]
    public async Task<ActionResult> Login(LoginViewModel model)
    {
        var user = await UserManager.FindAsync(model.Email, model.Password);
        // ...
    }
}
```

### After
```csharp
public class AccountController : Controller
{
    private readonly UserManager<ApplicationUser> _userManager;
    private readonly SignInManager<ApplicationUser> _signInManager;

    public AccountController(
        UserManager<ApplicationUser> userManager,
        SignInManager<ApplicationUser> signInManager)
    {
        _userManager = userManager;
        _signInManager = signInManager;
    }

    [HttpPost]
    public async Task<IActionResult> Login(LoginViewModel model)
    {
        var result = await _signInManager.PasswordSignInAsync(
            model.Email, model.Password, model.RememberMe, lockoutOnFailure: true);
        // ...
    }
}
```

---

## Step 5: Migrate JWT bearer auth (Web API scenarios)

Web API 2 projects often used `Microsoft.Owin.Security.OAuth` for token issuance. ASP.NET Core uses `Microsoft.AspNetCore.Authentication.JwtBearer` for validation, and either an external identity provider (Azure AD, Auth0, Cognito) or a hand-rolled `IdentityServer` / `OpenIddict` setup for issuance.

### Before
```csharp
app.UseOAuthBearerAuthentication(new OAuthBearerAuthenticationOptions { /* ... */ });
```

### After
```csharp
builder.Services
    .AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(opts =>
    {
        opts.Authority = builder.Configuration["Auth:Authority"];
        opts.Audience = builder.Configuration["Auth:Audience"];
        opts.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidateAudience = true,
            ValidateLifetime = true,
            ValidateIssuerSigningKey = true
        };
    });
```

---

## Step 6: Migrate antiforgery / CSRF protection

MVC 5 emitted tokens with `@Html.AntiForgeryToken()`, validated them with the `[ValidateAntiForgeryToken]` filter, and configured them through `AntiForgeryConfig`. ASP.NET Core has antiforgery built in and validates automatically for `[ValidateAntiForgeryToken]` (and for all unsafe verbs when you opt in with `AutoValidateAntiforgeryToken`).

### Before
```csharp
// Global.asax / AppStart
AntiForgeryConfig.UniqueClaimTypeIdentifier = ClaimTypes.NameIdentifier;

[HttpPost]
[ValidateAntiForgeryToken]
public ActionResult Update(Model m) { /* ... */ }
```
```html
@using (Html.BeginForm()) {
    @Html.AntiForgeryToken()
}
```

### After
```csharp
// Program.cs
builder.Services.AddControllersWithViews(o =>
    o.Filters.Add(new AutoValidateAntiforgeryTokenAttribute())); // validate on all unsafe verbs

// Optional: configure the header name for SPA / AJAX callers
builder.Services.AddAntiforgery(o => o.HeaderName = "X-CSRF-TOKEN");
```
```html
@* The form tag helper injects the hidden antiforgery field automatically *@
<form asp-controller="Account" asp-action="Update" method="post">
    <!-- fields -->
</form>
```

Notes:
- Razor form tag helpers emit the antiforgery field automatically; an explicit `@Html.AntiForgeryToken()` is only needed for hand-written `<form>` elements.
- `AntiForgeryConfig.UniqueClaimTypeIdentifier` has no ASP.NET Core equivalent — remove it; the token is bound to the authenticated user via the auth cookie.
- For AJAX/SPA callers, read the token from the antiforgery cookie and send it back in the configured header (`X-CSRF-TOKEN`).

---

## Step 7: Migrate the claims pipeline

Legacy apps customized claims through `ClaimsAuthenticationManager.Authenticate`, `UserManager.CreateIdentityAsync`, or an OWIN `OnValidateIdentity` hook. In ASP.NET Core the equivalents are `IClaimsTransformation` (per-request enrichment for any principal) and `IUserClaimsPrincipalFactory<TUser>` (claims baked in at sign-in for Identity users).

### Before
```csharp
public class AppClaimsAuthenticationManager : ClaimsAuthenticationManager
{
    public override ClaimsPrincipal Authenticate(string resourceName, ClaimsPrincipal incoming)
    {
        if (incoming.Identity.IsAuthenticated)
            ((ClaimsIdentity)incoming.Identity).AddClaim(new Claim("tenant", LookupTenant(incoming)));
        return incoming;
    }
}
```

### After
```csharp
// Per-request enrichment for any authenticated principal
public class TenantClaimsTransformation : IClaimsTransformation
{
    private readonly ITenantLookup _tenants;
    public TenantClaimsTransformation(ITenantLookup tenants) => _tenants = tenants;

    public async Task<ClaimsPrincipal> TransformAsync(ClaimsPrincipal principal)
    {
        if (principal.Identity?.IsAuthenticated == true &&
            !principal.HasClaim(c => c.Type == "tenant"))
        {
            var id = (ClaimsIdentity)principal.Identity;
            id.AddClaim(new Claim("tenant", await _tenants.ResolveAsync(principal)));
        }
        return principal;
    }
}

// Program.cs
builder.Services.AddScoped<IClaimsTransformation, TenantClaimsTransformation>();
```

Notes:
- `TransformAsync` can run more than once per request — make it idempotent (the `HasClaim` guard above).
- For claims that should persist with the Identity user, prefer a custom `IUserClaimsPrincipalFactory<ApplicationUser>` so they are added once at sign-in.
- Read claims via `User.FindFirstValue("tenant")`; `ClaimsPrincipal.Current` does not exist in ASP.NET Core.

---

## Step 8: Migrate SAML2 (Sustainsys.Saml2) to ASP.NET Core

Legacy apps wired SAML2 single sign-on through `Sustainsys.Saml2.HttpModule` (an `IHttpModule` registered in `web.config`) or the OWIN middleware (`Sustainsys.Saml2.Owin`). Neither runs on ASP.NET Core. Sustainsys ships a first-party ASP.NET Core package, `Sustainsys.Saml2.AspNetCore2`, that plugs into the standard authentication middleware as an external challenge scheme behind the application cookie.

### Before (System.Web HttpModule, web.config)
```xml
<system.webServer>
  <modules>
    <add name="Saml2" type="Sustainsys.Saml2.HttpModule.Saml2AuthenticationModule, Sustainsys.Saml2.HttpModule" />
  </modules>
</system.webServer>
<sustainsys.saml2 entityId="https://app.contoso.com/Saml2" returnUrl="https://app.contoso.com/">
  <identityProviders>
    <add entityId="https://idp.example.com/metadata"
         signOnUrl="https://idp.example.com/sso"
         allowUnsolicitedAuthnResponse="true">
      <signingCertificate fileName="~/AppData/idp.cer" />
    </add>
  </identityProviders>
</sustainsys.saml2>
```

### After (Program.cs)
```xml
<!-- Replace the HttpModule / OWIN packages with the ASP.NET Core package -->
<PackageReference Include="Sustainsys.Saml2.AspNetCore2" Version="2.10.0" />
```
```csharp
// Program.cs
builder.Services
    .AddAuthentication(o =>
    {
        // The app cookie is the primary scheme; SAML2 is the challenge scheme.
        o.DefaultScheme = CookieAuthenticationDefaults.AuthenticationScheme;
        o.DefaultChallengeScheme = Saml2Defaults.Scheme;
    })
    .AddCookie()
    .AddSaml2(opts =>
    {
        opts.SPOptions.EntityId = new EntityId("https://app.contoso.com/Saml2");
        opts.IdentityProviders.Add(
            new IdentityProvider(
                new EntityId("https://idp.example.com/metadata"),
                opts.SPOptions)
            {
                MetadataLocation = "https://idp.example.com/metadata",
                LoadMetadata = true,
                AllowUnsolicitedAuthnResponse = true
            });
        // Signing/decryption certs move from web.config to configuration / a secret store.
        opts.SPOptions.ServiceCertificates.Add(new ServiceCertificate
        {
            // X509CertificateLoader is .NET 9+; on net8.0 use: new X509Certificate2(path, password)
            Certificate = X509CertificateLoader.LoadPkcs12FromFile(
                builder.Configuration["Saml2:SpCertPath"]!,
                builder.Configuration["Saml2:SpCertPassword"])
        });
    });

var app = builder.Build();
app.UseAuthentication();
app.UseAuthorization();
```

Sign-in / sign-out are triggered with a standard challenge instead of the module's implicit interception:
```csharp
// SAML2 login
public IActionResult Login(string returnUrl = "/") =>
    Challenge(new AuthenticationProperties { RedirectUri = returnUrl }, Saml2Defaults.Scheme);

// SAML2 single logout
[Authorize]
public IActionResult Logout() =>
    SignOut(new AuthenticationProperties { RedirectUri = "/" },
        CookieAuthenticationDefaults.AuthenticationScheme, Saml2Defaults.Scheme);
```

Notes:
- The ACS and metadata endpoints (`/Saml2/Acs`, `/Saml2/`) are provided by the middleware — remove the old module routes and re-register the SP entityId and ACS URL at the IdP.
- SAML assertions arrive on the SAML2 scheme, then are persisted into the application cookie; map/rename claims with the Step 7 claims transformation if the app expects specific claim types (e.g. `ClaimTypes.NameIdentifier` → an app "userId").
- Certificates and IdP URLs move out of `web.config` into `appsettings.json` / a secret store; never commit private keys.
- This is a "no direct successor" migration — confirm the IdP relationship (metadata URL, SP entityId, certificate rotation) with the customer before cutover.

---

## Step 9: Validation Checklist

✅ No project references `Microsoft.Owin.*`, `Owin`, or `Microsoft.AspNet.Identity.*`  
✅ `Startup.Auth.cs`, `IdentityConfig.cs`, and any `App_Start/` partial-Startup files are deleted  
✅ Authentication is registered in `Program.cs` via `AddAuthentication` and activated via `UseAuthentication`  
✅ Existing user records still authenticate (password-hash compatibility test against a known user)  
✅ An EF Core schema migration reconciles the existing Identity 2.x database — normalized columns (`NormalizedUserName` / `NormalizedEmail` / `NormalizedName`) backfilled, `ConcurrencyStamp` added, `LockoutEndDateUtc` → `LockoutEnd` converted — and `FindByNameAsync` / `FindByEmailAsync` resolve a pre-existing user  
✅ `[Authorize]` attributes resolve correctly; an integration test posting to a protected route returns 401 without a token and 200 with a valid token  
✅ Antiforgery is enforced on unsafe verbs (`AutoValidateAntiforgeryToken` or `[ValidateAntiForgeryToken]`) and forms emit the token via tag helpers  
✅ Custom claims are added via `IClaimsTransformation` (idempotent) or `IUserClaimsPrincipalFactory`, not `ClaimsAuthenticationManager`; no `ClaimsPrincipal.Current` usage remains  
✅ SAML2 uses `Sustainsys.Saml2.AspNetCore2` behind the auth middleware; no `Sustainsys.Saml2.HttpModule` / OWIN or `<sustainsys.saml2>` web.config section remains; certs come from configuration / a secret store

---

## See Also
- [02-systemweb-migration.md](./02-systemweb-migration.md) – System.Web → ASP.NET Core
- [04-webapi-migration.md](./04-webapi-migration.md) – Web API (JWT bearer scenarios)
- [13-dependency-injection-migration.md](./13-dependency-injection-migration.md) – Constructor injection of UserManager / SignInManager
- [22-crypto-migration.md](./22-crypto-migration.md) – Password hashing and certificate handling
