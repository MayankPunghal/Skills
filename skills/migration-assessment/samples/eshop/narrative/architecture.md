The repository holds one business capability, a **product catalog** (items, brands, types, pictures, discounts), implemented several times:
- **Catalog web app.** ASP.NET MVC 5 `eShopLegacyMVC`, its ASP.NET Core 2.2 port `eShopPorted`, and the Web Forms version `eShopLegacyWebForms` (Create, Edit, Delete and Details pages under `Catalog/`). All use Entity Framework (EF6 in the .NET Framework apps, EF Core 2.2 in `eShopPorted`) against one SQL Server database, `Microsoft.eShopOnContainers.Services.CatalogDb`. Both MVC apps expose small Web API controllers, including a brands download that uses the shared `eShopLegacy.Utilities` library (BinaryFormatter, F-006). Picture upload uses System.Drawing (F-020 to F-023).
- **N-tier catalog.** `eShopWCFService` exposes `ICatalogService` over `basicHttpBinding` (`Web.config:39`). The desktop client `eShopWinForms` calls it through a generated proxy (`App.config:26`); the integration direction is desktop to service. Discounts are evaluated by date on the service, using the user's local date sent by the client.
- **Modernized variants.** `eShopModernizedMVC`, `eShopModernizedWebForms` and `eShopModernizedNTier` repeat the same code adapted for Windows containers and Azure: Key Vault, Application Insights, Azure AD sign-in through OWIN OpenID Connect (F-049), and Azure SQL token authentication.

The code graph (section 4.2) confirms the shape: the most connected classes are the `CatalogItem` models of each variant, and the only cross-project code dependency is on `eShopLegacy.Utilities`.

**Systems outside the code after migration:**
- the SQL Server database (RDS);
- the identity provider, if the Azure AD variant is the live one (redirect URIs to register);
- the desktop clients on user machines, which need the new HTTPS service endpoint.

No on-premises host names or private IPs were found in code or configuration. Production connection details are configured outside the repository.
