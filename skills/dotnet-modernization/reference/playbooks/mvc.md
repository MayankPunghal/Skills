# Playbook: ASP.NET MVC 5 to ASP.NET Core MVC

**Rules:** WEB-CHILD-ACTION, WEB-DI-RESOLVER (assessment); `System.Web.Mvc` usings (residue, the System.Web family).
**Engines:**
- DevTx KB 03 (MVC), 05, 10 and 13 (start-up, filters, DI) and 15 (views) guide the model. KB 03 says areas are discovered by convention, which is wrong; this playbook corrects it.
- AWS Transform: MVC is a supported project type.

Claude checks routes, areas, child actions, helpers and views. API controllers without views are [web-api.md](web-api.md). Start-up and middleware order are [startup-and-middleware.md](startup-and-middleware.md).

## Contents
- Steps
- Gotchas
- Done when

## Steps

1. **Snapshot first.** Record the pages users reach (`parity.py record`, with volatile parts such as antiforgery tokens and dates masked).
2. **Routes.**
   - `RouteConfig.RegisterRoutes` becomes `app.MapControllerRoute(...)`, keeping the same templates and defaults.
   - Attribute routes (`routes.MapMvcAttributeRoutes()`) are mapped with `app.MapControllers()` next to the conventional routes.
   - Conventional routes are matched in order, so keep the original order.
3. **Areas.**
   - `AreaRegistration` classes do not exist, and nothing is registered by convention.
   - Mark each area controller `[Area("Name")]`. Then add either one route `{area:exists}/{controller=Home}/{action=Index}/{id?}` or one `app.MapAreaControllerRoute(name, areaName, pattern)` per area. Area routes go before the default route because they are more specific.
   - Views stay where they were: the engine searches `/Areas/<Area>/Views/<Controller>/` first, then `/Areas/<Area>/Views/Shared/`, then `/Views/Shared/`.
4. **Filters.**
   - Global filters (`GlobalFilters.Filters.Add` in FilterConfig) move to `AddControllersWithViews(o => o.Filters.Add<T>())`.
   - `HandleErrorAttribute` becomes `app.UseExceptionHandler("/Home/Error")`.
   - `[ValidateAntiForgeryToken]` keeps its name in the Core namespace. `AutoValidateAntiforgeryTokenAttribute` can enforce it everywhere.
   - `[OutputCache]` becomes the output caching middleware: `AddOutputCache()`, `app.UseOutputCache()` and `[OutputCache]` on .NET 7 and later.
5. **Child actions.**
   - `@Html.Action`, `@Html.RenderAction` and `[ChildActionOnly]` do not exist.
   - A child action with logic becomes a view component. Its class derives from `ViewComponent` with `InvokeAsync(...)`, and its view sits at `Views/Shared/Components/<Name>/Default.cshtml`. Call it with `@await Component.InvokeAsync("Name", new { ... })` or the `<vc:name>` tag helper.
   - A child action with no logic becomes a partial view (`<partial name="..." />`).
   - Any AJAX endpoint the child action also served stays a normal action.
6. **Views and helpers.**
   - `Views/web.config` namespaces move to `_ViewImports.cshtml` (`@using ...` and `@addTagHelper *, Microsoft.AspNetCore.Mvc.TagHelpers`). `_ViewStart.cshtml` stays.
   - `@Html.Partial` and `Html.RenderPartial` become `<partial>` or `await Html.PartialAsync(...)`.
   - Custom helpers change types: `HtmlHelper` extensions become `IHtmlHelper` extensions, and `MvcHtmlString` becomes `IHtmlContent` or `HtmlString`.
   - The Razor `@helper` syntax is gone. Use a partial view, a tag helper, or a local function in `@functions`.
   - `@Styles.Render` and `@Scripts.Render` (System.Web.Optimization) become static `<link>` and `<script>` tags with `asp-append-version="true"`, after a build-time bundling step.
   - `Ajax.BeginForm` and `Ajax.ActionLink` (Microsoft.jQuery.Unobtrusive.Ajax) have no built-in equivalent. Use the jquery-ajax-unobtrusive script with `data-ajax-*` attributes, or `fetch`.
7. **Model binding.**
   - `[Bind(Include = "a,b")]` becomes `[Bind("a,b")]`.
   - `FormCollection` becomes `IFormCollection`, and `HttpPostedFileBase` becomes `IFormFile`.
   - `JsonRequestBehavior.AllowGet` is gone, because GET is allowed.
   - `Json(...)` now serializes with System.Text.Json in camelCase, so check the page scripts that read the result.
8. **State.** Session must be added and ordered in the pipeline ([startup-and-middleware.md](startup-and-middleware.md)). TempData uses a cookie by default, so large TempData values need the session provider.
9. **Dependency injection.**
   - `DependencyResolver.SetResolver(...)` with the Autofac, Unity or Ninject MVC integration becomes the built-in container, or the container's ASP.NET Core integration (`UseServiceProviderFactory`).
   - `DependencyResolver.Current.GetService<T>()` becomes constructor injection.
10. **Razor runtime compilation** is obsolete on .NET 10. Use Hot Reload in development, and precompiled views in the image ([breaking-changes.md](../breaking-changes.md)).

## Gotchas

- `Url.Action` and `Html.ActionLink` inside an area keep the current area. Pass `new { area = "" }` to link out of it.
- Razor in ASP.NET Core is stricter about unclosed tags and code blocks, so compile every view (the build does this by default).
- `RouteData.Values["area"]` and `ViewContext.RouteData` give the area in code, where MVC 5 used `DataTokens["area"]`.
- Bundles referenced from `_Layout` break silently when the bundle names change. Load every layout once in the replay.

## Done when

- No `System.Web.Mvc` reference is left, and no `Html.Action` or `RenderAction` is left.
- Every area has an explicit route.
- Every recorded page renders, with any diffs signed off.
- Forms post, with antiforgery and validation messages tested.

Sources: [Areas in ASP.NET Core](https://learn.microsoft.com/en-us/aspnet/core/mvc/controllers/areas), [View components](https://learn.microsoft.com/en-us/aspnet/core/mvc/views/view-components), [ASP.NET Core 10 breaking changes](https://learn.microsoft.com/en-us/aspnet/core/breaking-changes/10/overview).
