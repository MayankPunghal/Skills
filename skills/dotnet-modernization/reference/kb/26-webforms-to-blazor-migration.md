# 26 – Web Forms → Blazor Migration (.NET 8 / .NET 10)

## Overview
Blazor is often the **most natural** target for ASP.NET Web Forms apps: its component model with server-side event handlers (`@onclick`) mirrors the Web Forms control/event/postback model far more closely than stateless MVC does. Microsoft explicitly recommends Blazor as a Web Forms successor. This guide covers re-authoring `.aspx` pages as Blazor components. For the stateless Razor Pages/MVC alternative — and the **target-decision matrix** — see [25-webforms-to-razor-migration.md](./25-webforms-to-razor-migration.md).

Like Razor, this is a **per-page rewrite**, not a port; there is no automated `.aspx`→`.razor` converter.

---

## Step 1: Choose the Blazor hosting model

| Model | When it fits | Notes |
|---|---|---|
| **Blazor Server** | Internal / line-of-business apps, low-latency network to server | Closest to Web Forms: UI logic runs on the server over a SignalR circuit; smallest rewrite |
| **Blazor WebAssembly (WASM)** | Public apps needing offline / CDN-served client | Client-side execution; server data access moves behind an API |
| **Blazor Web App (unified, .NET 8+)** | New default | Single project with per-component render modes (Server / WASM / Auto); prefer this on `net8.0`/`net10.0` |

On .NET 8 and .NET 10 the **Blazor Web App** template (unified render modes) is the recommended starting point. For a Web Forms migration, **Interactive Server** render mode is usually the lowest-friction landing spot because it keeps UI logic on the server like Web Forms did.

---

## Step 2: Map the file types

| Web Forms | Blazor |
|---|---|
| `Default.aspx` + `Default.aspx.cs` | `Default.razor` (markup + `@code` block, or a `.razor.cs` code-behind) |
| `.ascx` user control | Child `.razor` component |
| `Site.master` | Layout component (`MainLayout.razor`) with `@Body` |
| `<asp:ContentPlaceHolder>` | `@Body` / `RenderFragment` parameters |
| `<%@ Page %>` directive | `@page "/route"` directive |

### Example component skeleton
```razor
@page "/orders"
@inject IOrderRepository Repo

<h1>Orders</h1>

<table class="table">
    @foreach (var o in _orders)
    {
        <tr><td>@o.Id</td><td>@o.Name</td></tr>
    }
</table>

<input @bind="_name" />
<button @onclick="Save">Save</button>

@code {
    private List<Order> _orders = new();
    private string? _name;

    protected override async Task OnInitializedAsync()   // was: Page_Load (!IsPostBack)
        => _orders = await Repo.GetOrdersAsync();

    private async Task Save()                             // was: SaveButton_Click
    {
        await Repo.SaveAsync(new Order { Name = _name });
        _orders = await Repo.GetOrdersAsync();
    }
}
```

---

## Step 3: Lifecycle and events

| Web Forms | Blazor |
|---|---|
| `Page_Load` (first load, `!IsPostBack`) | `OnInitialized` / `OnInitializedAsync` |
| `Page_Load` on every postback | `OnParametersSet` / `OnParametersSetAsync` |
| `Button_Click`, `LinkButton_Command` | `@onclick`, `@onclick:preventDefault` handlers |
| `TextBox.TextChanged` (AutoPostBack) | `@bind` / `@bind:event="oninput"` |
| `IsPostBack` branching | Not needed — lifecycle methods separate init from interaction |
| `Page.IsValid` / validators | `EditForm` + `DataAnnotationsValidator` |

There is **no postback**: interactivity flows through component events over the circuit (Server) or in the browser (WASM), and Blazor re-renders the affected component tree automatically. `StateHasChanged()` is only needed for updates triggered outside the normal event flow.

---

## Step 4: Server controls → components

| Web Forms control | Blazor replacement |
|---|---|
| `<asp:TextBox>` | `<input @bind="Model.X" />` or `<InputText @bind-Value="Model.X" />` inside `EditForm` |
| `<asp:Button OnClick=...>` | `<button @onclick="Handler">` |
| `<asp:Label>` | `<span>@value</span>` |
| `<asp:DropDownList>` | `<InputSelect @bind-Value="X">` / `<select @bind="X">` |
| `<asp:Repeater>` | `@foreach` in markup |
| `<asp:GridView>` (paging/sorting) | `QuickGrid` (`Microsoft.AspNetCore.Components.QuickGrid`) |
| `<asp:Validator>` controls | `DataAnnotationsValidator` + `<ValidationMessage For="...">` |
| `<asp:UpdatePanel>` (partial postback) | Native — component re-renders without a full page load |

### Forms with validation
```razor
<EditForm Model="_order" OnValidSubmit="Save">
    <DataAnnotationsValidator />
    <InputText @bind-Value="_order.Name" />
    <ValidationMessage For="() => _order.Name" />
    <button type="submit">Save</button>
</EditForm>
```

---

## Step 5: State — ViewState → component state

- **Control values / page state** → component fields bound with `@bind`; they live for the lifetime of the circuit/component, so most ViewState usage simply disappears.
- **Cross-component / cross-page state** → a scoped/singleton state service injected with `@inject` (see [13-dependency-injection-migration.md](./13-dependency-injection-migration.md)).
- **Per-user server state** → scoped services (Blazor Server) or browser storage / API-backed state (WASM).
- **Passing data into a child component** → `[Parameter]` properties (the component analogue of a user control's public properties).

---

## Step 6: Data access, DI, and auth

- Inject services with `@inject` (constructor injection in `.razor.cs` code-behind also works). Data access moves out of code-behind into injected repositories/services.
- For **Blazor WebAssembly**, the component runs in the browser — server data access must move behind a Web API (see [04-webapi-migration.md](./04-webapi-migration.md)); inject a typed `HttpClient` instead of a repository.
- Authentication/authorization integrates with the standard ASP.NET Core stack (`AuthorizeView`, `[Authorize]` on components) — see [08-auth-security-migration.md](./08-auth-security-migration.md).

---

## Step 7: Validation Checklist

✅ No `.aspx` / `.ascx` / `.master` files remain; no `System.Web.UI.*` types  
✅ Each page is a `.razor` component with an `@page` route; user controls are child components; master pages are layout components  
✅ Lifecycle logic uses `OnInitialized*` / `OnParametersSet*`; no `IsPostBack` branching remains  
✅ Control events are `@onclick` / `@bind` handlers; no server-control event handlers or ViewState assumptions remain  
✅ Forms use `EditForm` + `DataAnnotationsValidator`; grids use `QuickGrid` or `@foreach`  
✅ Data access is injected (Blazor Server) or behind an API (WASM); no data access in component markup  
✅ A chosen render/hosting model is recorded (Server / WASM / Blazor Web App) with rationale  
✅ The app builds and each migrated screen renders and handles its interactive events

---

## See Also
- [25-webforms-to-razor-migration.md](./25-webforms-to-razor-migration.md) – the stateless (Razor Pages / MVC) alternative + target-decision matrix
- [02-systemweb-migration.md](./02-systemweb-migration.md) – System.Web APIs
- [08-auth-security-migration.md](./08-auth-security-migration.md) – authentication / authorization
- [13-dependency-injection-migration.md](./13-dependency-injection-migration.md) – dependency injection and state services
