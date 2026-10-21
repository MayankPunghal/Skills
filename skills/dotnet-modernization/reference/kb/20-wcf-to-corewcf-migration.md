# 20 – WCF to CoreWCF Migration (.NET 8 / .NET 10)

## Overview
WCF server-side (`System.ServiceModel.*`) does not run on modern .NET. The migration target is **CoreWCF** — a community-driven port now officially supported by Microsoft. Most service contracts port without code changes; the breakage is all in hosting and configuration. WCF client-side has limited modern .NET support via the `System.ServiceModel` client packages on NuGet.

> **Package versions:** CoreWCF (`1.x`) and the `System.ServiceModel.*` WCF **client** packages (`8.x`) are versioned independently of the .NET runtime — they are **not** tied to the `net8.0`/`net10.0` major like the `Microsoft.AspNetCore.*` / `Microsoft.EntityFrameworkCore.*` packages are. Use the latest compatible release on either .NET 8 or .NET 10.

---

## Classify each project first: client vs server

WCF projects fall into two very different migration paths — decide which one applies **before** touching packages or `using` statements:

| Role | Identified by | Packages | Contract namespace |
|---|---|---|---|
| **Server** (hosts the service) | `.svc` files, `[ServiceContract]` implementations, `<system.serviceModel><services>` in config | `CoreWCF.*` | `CoreWCF` |
| **Client** (consumes a service) | generated `Reference.cs`, `ClientBase<T>`, `ChannelFactory<T>`, `<client><endpoint>` in config | `System.ServiceModel.*` (NuGet) | `System.ServiceModel` |

Key rules:
- **Never add `CoreWCF.*` to a client-only project**, and never add the `System.ServiceModel.*` client packages to a server project.
- **Microsoft Upgrade Assistant over-maps `System.ServiceModel` → `CoreWCF` for *every* project, including clients.** After UA runs, remove the `CoreWCF.*` packages it added to any client project and replace them with the `System.ServiceModel.*` packages from Step 5.
- A single project that is both host and client is rare; treat its contract/host code as server and its proxy code as client.

---

## Step 1: Replace `System.ServiceModel` server packages with CoreWCF

Server projects move off the framework-shipped `System.ServiceModel.*` assemblies and onto NuGet packages from the `CoreWCF.*` family.

### Before
```xml
<!-- packages.config or PackageReference on net48 -->
<Reference Include="System.ServiceModel" />
<Reference Include="System.ServiceModel.Web" />
```

### After
```xml
<ItemGroup>
  <PackageReference Include="CoreWCF.Primitives" Version="1.6.0" />
  <PackageReference Include="CoreWCF.Http" Version="1.6.0" />
  <PackageReference Include="CoreWCF.NetTcp" Version="1.6.0" />        <!-- only if NetTcp is used -->
  <PackageReference Include="CoreWCF.ConfigurationManager" Version="1.6.0" />  <!-- if config-driven -->
</ItemGroup>
```

---

## Step 2: `[ServiceContract]` / `[OperationContract]` — server contracts move to the `CoreWCF` namespace

On the **server**, once the project references `CoreWCF.Primitives` (Step 1) the service/operation contract attributes resolve from the `CoreWCF` namespace, not `System.ServiceModel`. Change the `using` on server contract and service files:

- `[ServiceContract]`, `[OperationContract]`, `[ServiceBehavior]`, `[FaultContract]` → `using CoreWCF;` (was `using System.ServiceModel;`)
- `[DataContract]`, `[DataMember]`, `[EnumMember]` → **unchanged**, they stay in `System.Runtime.Serialization`

Leaving `using System.ServiceModel;` on a server contract that references `CoreWCF.Primitives` produces `CS0246: 'ServiceContract' could not be found`. (On the **client** side these attributes *do* stay under `System.ServiceModel` — see the client-vs-server table above and Step 5.)

### Before
```csharp
using System.ServiceModel;

[ServiceContract]
public interface IOrderService
{
    [OperationContract]
    Order GetOrder(int id);
}
```

### After (server side)
```csharp
// server contracts compiled against CoreWCF.Primitives use the CoreWCF namespace
using CoreWCF;                       // was: using System.ServiceModel;

[ServiceContract]
public interface IOrderService
{
    [OperationContract]
    Order GetOrder(int id);
}
```

---

## Step 3: Replace `<system.serviceModel>` config with `IServiceCollection` wiring

The `<system.serviceModel>` element in `web.config` / `app.config` has no equivalent in modern .NET. Bindings, behaviours, and service endpoints move into `Program.cs` via `builder.Services.AddServiceModelServices()`.

### Before
```xml
<!-- web.config -->
<system.serviceModel>
  <services>
    <service name="Contoso.Orders.OrderService">
      <endpoint address="" binding="basicHttpBinding" contract="Contoso.Orders.IOrderService" />
    </service>
  </services>
  <bindings>
    <basicHttpBinding>
      <binding maxReceivedMessageSize="2147483647" />
    </basicHttpBinding>
  </bindings>
</system.serviceModel>
```

### After
```csharp
// Program.cs
using CoreWCF;
using CoreWCF.Configuration;
using CoreWCF.Description;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddServiceModelServices()
                .AddServiceModelMetadata();

var app = builder.Build();
app.UseServiceModel(serviceBuilder =>
{
    serviceBuilder.AddService<OrderService>(o =>
    {
        o.DebugBehavior.IncludeExceptionDetailInFaults = false;
    });

    serviceBuilder.AddServiceEndpoint<OrderService, IOrderService>(
        new BasicHttpBinding(),
        "/OrderService.svc");

    serviceBuilder.ConfigureServiceHostBase<OrderService>(host =>
    {
        host.Description.Behaviors.Find<ServiceMetadataBehavior>()!
            .HttpGetEnabled = true;
    });
});

app.Run();
```

---

## Step 4: Remove `.svc` files and replace `WebServiceHostFactory` references

The classic `.svc` endpoint file is replaced by an explicit route registration in `Program.cs`. Delete the `.svc` files and any `Service.svc.cs` code-behind (the service implementation class survives unchanged).

### Before
```
src/Contoso.Orders/OrderService.svc          (declares <%@ ServiceHost ... %>)
src/Contoso.Orders/OrderService.svc.cs       (empty code-behind)
```

### After
```
src/Contoso.Orders/OrderService.cs           (the implementation, unchanged)
src/Contoso.Orders/Program.cs                (declares the endpoint via AddServiceEndpoint)
```

---

## Step 5: WCF clients — use `System.ServiceModel.*` NuGet packages

Client-side code referencing `ChannelFactory<T>` or generated `ClientBase<T>` proxies works on modern .NET via the `System.ServiceModel.*` family on NuGet (separate from the framework-shipped assemblies of the same name). The source code does not change; only the package references do.

### Before
```xml
<Reference Include="System.ServiceModel" />
```

### After
```xml
<ItemGroup>
  <PackageReference Include="System.ServiceModel.Primitives" Version="8.1.0" />
  <PackageReference Include="System.ServiceModel.Http" Version="8.1.0" />
  <PackageReference Include="System.ServiceModel.NetTcp" Version="8.1.0" />     <!-- if NetTcp is used -->
  <PackageReference Include="System.ServiceModel.Security" Version="8.1.0" />   <!-- if WS-Security is used -->
</ItemGroup>
```

On the client, keep `using System.ServiceModel;` (and `System.ServiceModel.Channels` / `System.ServiceModel.Description` as used) — the contract and proxy types stay in that namespace. Do **not** add `CoreWCF.*` to a client project; if Upgrade Assistant added CoreWCF packages here, remove them and add the `System.ServiceModel.*` packages above.

Gotchas seen in real migrations:
- **`ClientBase<T>` config-name constructors don't exist** on `System.ServiceModel.Primitives`. Generated `Reference.cs` proxies that call `base(endpointConfigurationName)` (a `string`) fail with `CS1503`. Config-file endpoints (`<client><endpoint>`) are not supported — construct the client with an explicit `Binding` + `EndpointAddress` instead (e.g. `new BasicHttpBinding(), new EndpointAddress(url)`), sourcing the URL from `appsettings.json`.
- Regenerate proxies with `dotnet-svcutil` where possible; hand-editing the old `Reference.cs` is fine for small contracts.

Note: client-side has known limitations — federation bindings, MSMQ, and some WS-* features are not fully supported. Validate each client binding against the WCF on .NET Standard documentation.

---

## Step 6: Validation Checklist

✅ No server-side project references `System.ServiceModel.*` framework assemblies; all server traffic goes through `CoreWCF.*`  
✅ No `<system.serviceModel>` block remains in any `web.config` / `app.config`; service hosting is configured in `Program.cs`  
✅ All `.svc` files are deleted; routing is registered via `serviceBuilder.AddServiceEndpoint`  
✅ Server contract files use `using CoreWCF;` and compile against `CoreWCF.Primitives`; client projects keep `using System.ServiceModel;`, reference the `System.ServiceModel.*` NuGet packages, and contain **no** `CoreWCF.*` package references  
✅ A WCF client can call each ported service with no SOAP envelope changes (verify with a recorded request from the legacy service)

---

## See Also
- [06-package-migrations.md](./06-package-migrations.md) – NuGet package replacements
- [11-configuration-migration.md](./11-configuration-migration.md) – web.config → appsettings.json / code configuration
- [05-hosting-deployment-migration.md](./05-hosting-deployment-migration.md) – hosting model and `Program.cs`
