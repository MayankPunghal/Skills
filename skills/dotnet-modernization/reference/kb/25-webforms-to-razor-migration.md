# 25 – Web Forms → ASP.NET Core (Razor Pages / MVC) Migration (.NET 8 / .NET 10)

## Overview
ASP.NET Web Forms (`.aspx` / `.ascx` / `.master`, the code-behind event model, server controls, and ViewState) has **no equivalent on modern .NET** — `Microsoft.AspNet.WebForms` was never ported. Each page is **re-authored**, not ported. This guide covers the migration to **ASP.NET Core Razor Pages or MVC** (server-rendered). For the component-based alternative, see [26-webforms-to-blazor-migration.md](./26-webforms-to-blazor-migration.md).

There is no automated `.aspx`→`.cshtml` converter; this is per-page work. Kiro performs the rewrite page by page using the mappings below.

---

## Choosing your target: Razor Pages / MVC vs Blazor

| Concern | → Razor Pages / MVC (this file) | → Blazor ([26](./26-webforms-to-blazor-migration.md)) |
|---|---|---|
| Model | Stateless request/response | Stateful component model |
| `.aspx` / `.ascx` | → `.cshtml` page/view + partials | → `.razor` components |
| Code-behind events (`Button_Click`) | → form posts + handler methods / controller actions | → `@onclick` handlers (closest to the WF event model) |
| Server controls (`<asp:GridView>`) | → tag helpers / HTML + model binding | → Blazor components / `QuickGrid` |
| ViewState / postback | Removed — re-model as explicit state | Component state / bound fields |
| Best fit | SEO-first, server-rendered, or app already partly MVC | Rich interactivity, SPA-like UX, teams that liked the WF event model |

**Rule of thumb:** choose Razor Pages/MVC for content/CRUD apps where a stateless request model is fine; choose Blazor when the app leaned heavily on the interactive control/postback model. A large app may migrate most pages to Razor Pages and a few highly-interactive screens to Blazor.

---

## Step 1: Inventory and prerequisites

Before rewriting any page:
- Enumerate all `.aspx` (pages), `.ascx` (user controls), and `.master` (master pages) files and their code-behind (`.aspx.cs` / `.ascx.cs`).
- Identify ViewState reliance (server controls that round-trip state across postbacks) — these need explicit re-modeling.
- Confirm the project is SDK-style and targets the toolkit's framework (`net8.0` or `net10.0`) with SDK `Microsoft.NET.Sdk.Web` (see [01-project-file-migration.md](./01-project-file-migration.md)).

Prefer **Razor Pages** over MVC for a Web Forms migration: its page-centric model (a `.cshtml` + a `PageModel` code-behind) maps more naturally onto the one-page-one-code-behind Web Forms structure than MVC's controller/action split.

---

## Step 2: Map the file types

| Web Forms | Razor Pages | MVC |
|---|---|---|
| `Default.aspx` + `Default.aspx.cs` | `Pages/Index.cshtml` + `Index.cshtml.cs` (`PageModel`) | View + controller action |
| `.ascx` user control | Partial view (`_Widget.cshtml`) or View Component | Partial / View Component |
| `Site.master` | `Pages/Shared/_Layout.cshtml` | `Views/Shared/_Layout.cshtml` |
| `<asp:ContentPlaceHolder>` | `@RenderBody()` / `@RenderSection(...)` | `@RenderBody()` |
| `MasterPageFile="~/Site.master"` | `@{ Layout = "_Layout"; }` (or `_ViewStart.cshtml`) | `Layout` in `_ViewStart.cshtml` |

---

## Step 3: Code-behind → PageModel handler (or controller action)

The Web Forms lifecycle event model (`Page_Load`, `IsPostBack`, control event handlers) becomes explicit HTTP handlers.

### Before (Web Forms)
```csharp
// Orders.aspx.cs
public partial class Orders : System.Web.UI.Page
{
    protected void Page_Load(object sender, EventArgs e)
    {
        if (!IsPostBack)
            GridView1.DataSource = _repo.GetOrders();
    }

    protected void SaveButton_Click(object sender, EventArgs e)
    {
        _repo.Save(new Order { Name = NameTextBox.Text });
    }
}
```

### After (Razor Pages)
```csharp
// Pages/Orders.cshtml.cs
public class OrdersModel : PageModel
{
    private readonly IOrderRepository _repo;
    public OrdersModel(IOrderRepository repo) => _repo = repo;

    public IReadOnlyList<Order> Orders { get; private set; } = [];

    [BindProperty]
    public string? Name { get; set; }

    public void OnGet()                       // was: Page_Load when !IsPostBack
    {
        Orders = _repo.GetOrders();
    }

    public IActionResult OnPostSave()         // was: SaveButton_Click
    {
        _repo.Save(new Order { Name = Name });
        return RedirectToPage();
    }
}
```

- `Page_Load` under `if (!IsPostBack)` → `OnGet`.
- Each control's `_Click` / `_Command` handler → a named `OnPost<Handler>` method, targeted from the form with `asp-page-handler="Save"`.
- Data access moves to injected services (no more `new Repository()` in code-behind) — see [13-dependency-injection-migration.md](./13-dependency-injection-migration.md).

---

## Step 4: Server controls → Razor markup / tag helpers

| Web Forms control | Razor replacement |
|---|---|
| `<asp:TextBox ID="NameTextBox" runat="server" />` | `<input asp-for="Name" class="form-control" />` |
| `<asp:Label runat="server" Text='<%# ... %>' />` | `@Model.SomeValue` / `<span>@Model.SomeValue</span>` |
| `<asp:Button Text="Save" OnClick="SaveButton_Click" />` | `<button type="submit" asp-page-handler="Save">Save</button>` |
| `<asp:DropDownList>` | `<select asp-for="X" asp-items="Model.Options"></select>` |
| `<asp:Repeater>` / `<asp:GridView>` | `@foreach` over the model rendering a `<table>` / list |
| `<asp:GridView>` (rich: paging/sorting) | HTML table + query-string paging, or migrate that screen to Blazor `QuickGrid` ([26](./26-webforms-to-blazor-migration.md)) |
| `<asp:Validator>` controls | DataAnnotations on the model + `<span asp-validation-for="X">` |

### Example: `<asp:Repeater>` → `@foreach`
```html
@* Orders.cshtml *@
<table class="table">
    <thead><tr><th>Id</th><th>Name</th></tr></thead>
    <tbody>
    @foreach (var o in Model.Orders)
    {
        <tr><td>@o.Id</td><td>@o.Name</td></tr>
    }
    </tbody>
</table>

<form method="post">
    <input asp-for="Name" class="form-control" />
    <button type="submit" asp-page-handler="Save">Save</button>
</form>
```

---

## Step 5: ViewState and the postback model → explicit state

ViewState does not exist. Re-model the state that Web Forms used to round-trip:
- **Form field values** → model binding (`[BindProperty]` / action parameters); the browser re-posts them.
- **Transient cross-request messages** (e.g. "Saved successfully") → `TempData`.
- **Per-user server state** → session (`ISession`) or a distributed cache (see [02-systemweb-migration.md](./02-systemweb-migration.md) Step 9).
- **Control state that was purely UI** → hidden inputs or client-side JS.

Antiforgery is enforced automatically by the form tag helper (see [08-auth-security-migration.md](./08-auth-security-migration.md) Step 6); a hand-written `<form>` needs `@Html.AntiForgeryToken()`.

---

## Step 6: Validation Checklist

✅ No `.aspx` / `.ascx` / `.master` files remain; no code inherits `System.Web.UI.Page` / `UserControl` / `MasterPage`  
✅ No `Microsoft.AspNet.WebForms`, `System.Web.UI.*`, or `<%@ Page %>` / `<%# %>` / `<%= %>` markup remains  
✅ Every page is a Razor Page (`.cshtml` + `PageModel`) or MVC view+action; server controls are replaced by tag helpers / `@foreach` markup  
✅ No ViewState assumptions — state is re-modeled via model binding, `TempData`, or session  
✅ Control event handlers are `OnPost<Handler>` methods (or controller actions), invoked via `asp-page-handler` / form posts  
✅ Data access is injected, not instantiated in code-behind  
✅ The app builds and each migrated screen renders and round-trips a form post successfully

---

## See Also
- [02-systemweb-migration.md](./02-systemweb-migration.md) – System.Web APIs (HttpContext, session, caching)
- [03-mvc-migration.md](./03-mvc-migration.md) – MVC controllers, routing, Razor
- [15-views-static-files-migration.md](./15-views-static-files-migration.md) – Razor views and static files
- [26-webforms-to-blazor-migration.md](./26-webforms-to-blazor-migration.md) – the component-based (Blazor) alternative
