# 28 – .NET Remoting Migration (.NET 8 / .NET 10)

## Overview

.NET Remoting (`System.Runtime.Remoting.*`) is **not ported, not shimmed, and not stubbed** on modern .NET. Unlike WCF (which has CoreWCF, see [20](./20-wcf-to-corewcf-migration.md)), there is **no drop-in replacement and no bridging shim**. Almost the entire API surface is *absent from the reference assemblies*, so remoting code produces hard **compile errors** (`CS0234`, `CS0246`, `CS0103`, `CS0117`) rather than runtime failures.

Microsoft's position:

> ".NET Remoting isn't supported on .NET 6+. .NET remoting was identified as a problematic architecture. It's used for communicating across application domains, which are no longer supported. Also, remoting requires runtime support, which is expensive to maintain."
> — [.NET Framework technologies unavailable on .NET 6+](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable)

The reason it cannot be ported: remoting's transparent proxy is a **CLR-level dispatch hook**, not library code. No NuGet package can reintroduce it on CoreCLR.

> **🚨 Classify before you transform.** A large fraction of real-world `MarshalByRefObject` usage is *not distributed at all* — it is cross-AppDomain isolation or `RealProxy`-based AOP. Those have cheap local remedies (`AssemblyLoadContext`, `DispatchProxy`) and need **no network transport**. Defaulting every remoting site to gRPC creates enormous unnecessary work. **Step 1 below is mandatory.**

> **Package versions:** `Grpc.*`, `StreamJsonRpc`, `MessagePack`, and `protobuf-net.*` are versioned **independently of the .NET runtime major** — use the latest compatible release on .NET 8 or .NET 10. Only `Microsoft.AspNetCore.SignalR.*` and `Microsoft.Extensions.*` follow the `8.0.x` / `10.0.x` rule from the [README](./README.md).

---

## Step 1: Classify every remoting usage (MANDATORY FIRST STEP)

Do not touch code until each usage site has one of four verdicts. The classifier is *"is there a channel registration?"*

```
Is there a channel registration?
  (ChannelServices.RegisterChannel / RemotingConfiguration.Register* / config <channels>)
│
├── NO ──► RealProxy / ProxyAttribute present?        ──► (A) DispatchProxy — AOP, no transport   [cheap]
│          AppDomain.CreateDomain present?            ──► (B) AssemblyLoadContext or merge        [Step 6]
│          MarshalByRefObject only, no transport?     ──► (C) delete the base class               [Step 5]
│
└── YES ─► Same machine only (IpcChannel / ipc:// URI)?
           ├── YES ─► Same app boundary?  ──► (C) consolidate in-process       [best outcome]
           │          else                ──► (D) named pipes: gRPC-over-pipes or StreamJsonRpc
           └── NO (TcpChannel / HttpChannel — cross-machine)
                      ├── all methods [OneWay]        ──► (E) queue: SQS / SNS / MassTransit
                      ├── server→client callbacks     ──► (F) gRPC server streaming or SignalR
                      ├── browser / 3rd-party clients ──► (G) ASP.NET Core Web API (REST + JSON)
                      ├── SOAP / WSDL is contractual  ──► CoreWCF — see [20](./20-wcf-to-corewcf-migration.md)
                      └── otherwise                   ──► (H) gRPC   [default]
```

### (A) `RealProxy` without any channel → `DispatchProxy`

Microsoft: *"Despite being in the `System.Runtime.Remoting` namespace, in many cases users aren't actually doing any cross-process remoting with `RealProxy`. Instead, many developers use it as an easy way to implement an aspect-oriented programming (AOP) paradigm."* ([devblogs](https://devblogs.microsoft.com/dotnet/migrating-realproxy-usage-to-dispatchproxy))

`System.Reflection.DispatchProxy` is **in-box** on modern .NET. Two differences that matter:
- `DispatchProxy` proxies **interfaces only**, not classes.
- You call `DispatchProxy.Create<TInterface, TProxy>()`; you do not subclass and override `Invoke(IMessage)`.

Fall back to `Castle.DynamicProxy` when class proxying is genuinely required.

---

## Step 2: Detection signals

### Tier 1 — namespace imports (conclusive)

```
System.Runtime.Remoting
System.Runtime.Remoting.Channels        .Channels.Tcp   .Channels.Http   .Channels.Ipc
System.Runtime.Remoting.Activation      .Lifetime       .Messaging       .Proxies
System.Runtime.Remoting.Contexts        .Metadata       .Services        .Metadata.W3cXsd2001
System.Runtime.Serialization.Formatters.Soap
```

> ⚠️ **`using System.Runtime.Remoting;` alone does NOT produce an error** — `ObjectHandle` still lives in that namespace and keeps it alive. Keying detection on "root namespace fails to resolve" yields **false negatives**. Match the **sub-namespaces** and individual type names instead.

### Tier 2 — types and members (conclusive)

| Category | Symbols |
|---|---|
| Registration | `RemotingConfiguration.Configure`, `RegisterWellKnownServiceType`, `RegisterActivatedServiceType`, `RegisterWellKnownClientType`, `RegisterActivatedClientType`, `ApplicationName`, `CustomErrorsMode` |
| Channels | `ChannelServices.RegisterChannel` / `.UnregisterChannel`, `TcpChannel`, `TcpServerChannel`, `TcpClientChannel`, `HttpChannel`, `HttpServerChannel`, `HttpClientChannel`, `IpcChannel`, `IpcServerChannel`, `IpcClientChannel` |
| Sinks / formatters | `BinaryClientFormatterSink(Provider)`, `BinaryServerFormatterSink(Provider)`, `SoapClientFormatterSink`, `SoapServerFormatterSink`, `SoapFormatter`, `IClientChannelSink`, `IServerChannelSink`, `IChannelSinkBase` |
| Marshaling / identity | `RemotingServices.Marshal` / `.Unmarshal` / `.Connect` / `.GetObjectUri` / `.SetObjectUriForMarshal` / `.IsTransparentProxy` / `.GetRealProxy`, `ObjRef`, `IObjectHandle` |
| Activation | `Activator.GetObject`, `Activator.CreateInstance(..., activationAttributes)`, `UrlAttribute`, `IConstructionCallMessage` |
| Lifetime | `InitializeLifetimeService`, `GetLifetimeService`, `ILease`, `ISponsor`, `ClientSponsor`, `LifetimeServices.{LeaseTime,RenewOnCallTime,SponsorshipTimeout,LeaseManagerPollTime}`, `LeaseState` |
| Proxies / contexts | `RealProxy`, `ProxyAttribute`, `TransparentProxy`, `Context`, `ContextAttribute`, `IContributeObjectSink` |
| Modes | `WellKnownObjectMode.Singleton`, `WellKnownObjectMode.SingleCall`, `TypeFilterLevel.{Low,Full}` |
| Tracking | `TrackingServices.RegisterTrackingHandler`, `ITrackingHandler` |
| Attributes | `[OneWay]`, `[Synchronization]`, `[Context*]` |
| Base classes | `: MarshalByRefObject`, `: ContextBoundObject` |

### Tier 2b — the AppDomain co-signal (high value)

`AppDomain.CreateDomain`, `CreateInstanceAndUnwrap`, `CreateInstanceFromAndUnwrap`, `AppDomain.Unload`, `DoCallBack`, `SetData`/`GetData`.

When these co-occur with `MarshalByRefObject`, the workload is **in-process isolation, not distribution** → route to **Step 6**, not to a transport.

### Tier 3 — configuration (`app.config` / `web.config`)

```xml
<configuration>
  <system.runtime.remoting>
    <application name="OrderHost">
      <lifetime leaseTime="10M" sponsorshipTimeout="1M"
                renewOnCallTime="15M" leaseManagerPollTime="8s" />
      <channels>
        <channel ref="tcp|http|ipc" port="8000" secure="true">
          <serverProviders>
            <formatter ref="binary" typeFilterLevel="Full" />
          </serverProviders>
          <clientProviders><formatter ref="binary" /></clientProviders>
        </channel>
      </channels>
      <service>
        <wellknown mode="Singleton|SingleCall" type="NS.Type, Asm" objectUri="Svc.rem" />
        <activated type="NS.Type, Asm" />
      </service>
      <client url="tcp://host:8000">
        <wellknown type="NS.Type, Asm" url="tcp://host:8000/Svc.rem" />
        <activated type="NS.Type, Asm" />
      </client>
    </application>
    <channelSinkProviders>...</channelSinkProviders>
    <customErrors mode="On|Off|RemoteOnly" />
    <debug loadTypes="true" />
  </system.runtime.remoting>
</configuration>
```

Notes: `<lifetime>` applies **only** to `Singleton` and client-activated objects, never to `SingleCall`. The `microsoft:Remoting:LateHttpHeaderParsing` AppContext switch (a CVE-2024-29059 mitigation flag) is also a strong remoting indicator.

No Microsoft tool detects this config section — see Step 10.

### Tier 3b — endpoints and hosting

`.rem` / `.soap` URL suffixes; `tcp://` and `ipc://` URIs; IIS-hosted remoting (a `bin`-deployed assembly plus `<wellknown>` in `web.config`, with **no** `.asmx` or `.svc` file); `RemotingConfiguration.Configure` called from `Global.asax` `Application_Start` (see [10](./10-global-asax-migration.md)).

### Tier 3c — serialization coupling (weak alone, expensive to fix)

`[Serializable]`, `ISerializable` + `.ctor(SerializationInfo, StreamingContext)`, `[NonSerialized]`, `[OptionalField]`, `ISerializationSurrogate` / `SurrogateSelector`, `[OnSerializing]` / `[OnDeserialized]`.

These predate and outlive remoting, so on their own they are weak signals. Combined with Tier 1–2 they define the **DTO migration scope** — see Step 7.

---

## Step 3: What actually exists on modern .NET

Only **three** remoting-adjacent artifacts survive, all leaked into `System.Private.CoreLib`. There are **zero** `*Remoting*` assemblies in the .NET 10 reference pack.

| Type / namespace | Status on .NET 8 / 9 / 10 | Diagnostic if used |
|---|---|---|
| `System.MarshalByRefObject` | **EXISTS** — inert base class, no proxying, no marshaling | none for inheritance |
| `MarshalByRefObject.GetLifetimeService()` | EXISTS, obsolete, **throws `PlatformNotSupportedException`** | `SYSLIB0010` |
| `MarshalByRefObject.InitializeLifetimeService()` | EXISTS, obsolete, **throws `PlatformNotSupportedException`** | `SYSLIB0010`; overriding → `CS0672` |
| `System.Runtime.Remoting.ObjectHandle` | **EXISTS** (used by `Activator` unwrapping) | none |
| `System.ContextBoundObject` / `ContextStaticAttribute` | **EXISTS** (`ContextBoundObject` inert) | none |
| `RemotingException`, `RemotingConfiguration`, `RemotingServices`, `ObjRef`, `WellKnownObjectMode`, `ServerException`, `RemotingTimeoutException` | **REMOVED** (despite being in the root namespace) | `CS0234` / `CS0103` |
| `…Remoting.Channels[.Tcp/.Http/.Ipc]` — all channels, sinks, formatter sinks | **REMOVED** (whole namespaces) | `CS0234` |
| `…Remoting.Lifetime` — `ILease`, `ISponsor`, `ClientSponsor`, `LifetimeServices` | **REMOVED** | `CS0234` |
| `…Remoting.Messaging` — `IMessage`, `CallContext`, `OneWayAttribute` | **REMOVED** | `CS0234` |
| `…Remoting.Proxies` — `RealProxy`, `ProxyAttribute` | **REMOVED** | `CS0234` |
| `…Remoting.Activation` / `.Contexts` / `.Metadata` / `.Services` | **REMOVED** | `CS0234` |
| `Activator.GetObject` | **REMOVED** (the *method*; the type exists) | **`CS0117`** |
| `SoapFormatter` | **REMOVED** | `CS0234` |
| `TypeFilterLevel` | EXISTS, obsolete | `SYSLIB0050` |
| `BinaryFormatter` | EXISTS, **obsolete as ERROR**, always throws | **`SYSLIB0011` (error)** |
| `System.EnterpriseServices.*` (COM+) | **REMOVED** | `CS0234` |
| `System.Reflection.DispatchProxy` | **EXISTS** — the `RealProxy` replacement | none |
| `System.Runtime.Loader.AssemblyLoadContext` | EXISTS — the `AppDomain` replacement | none |

**Version note:** remoting types have been absent since .NET Core 1.0 — there is **no** difference between .NET 8, 9, and 10 here. The version axis that genuinely matters is `BinaryFormatter` (Step 7).

---

## Step 4: Concept mapping

| Remoting concept | Modern equivalent | Notes |
|---|---|---|
| **SAO `Singleton`** | DI singleton (`AddSingleton`) behind a gRPC/HTTP service | Same lifetime, but now **must be explicitly thread-safe** — remoting sometimes hid this behind `[Synchronization]` |
| **SAO `SingleCall`** | DI scoped/transient (`AddScoped`) | Cleanest mapping; already stateless — **migrate these first** |
| **CAO** (client-activated) | Explicit session: session id + server-side store (`IMemoryCache`, Redis/ElastiCache) with TTL | No transport gives per-client server objects for free — **migrate these last** |
| **`MarshalByRefObject` pass-by-reference** | **Nothing.** Redesign to pass-by-value DTOs | The most invasive change. Reference semantics across a process boundary are gone by design |
| **Pass-by-value `[Serializable]`** | Plain POCOs + `System.Text.Json`, or protobuf messages | Remoting serialization is **opt-out (fields)**; modern is **opt-in (public properties)** |
| **Lease lifetime** (`InitializeLifetimeService`, `ILease`) | Stateless service; or explicit TTL cache; or gRPC keepalive for *connection* liveness | Separate *object* lifetime (→ cache TTL) from *connection* liveness (→ keepalive). `return null` ("infinite lease") → plain DI singleton |
| **`ClientSponsor` / `ISponsor`** | Explicit heartbeat/renew RPC that extends the TTL | Becomes a visible, auditable protocol operation |
| **Remoting events / cross-domain delegates** | gRPC server streaming, or SignalR hub callbacks | `Delegate.BeginInvoke`/`EndInvoke` **throw `PlatformNotSupportedException`** — use `async`/`await` |
| **`RemotingConfiguration.Configure(file)`** | `appsettings.json` + DI registration in `Program.cs` | See [11](./11-configuration-migration.md) |
| **`Activator.GetObject(type, url)`** | Typed client from DI (`AddGrpcClient<T>` / `IHttpClientFactory`) | `CS0117` at compile time |
| **`RemotingServices.Marshal` / `.Connect`** | Server: `MapGrpcService<T>()`. Client: channel + typed client | URI identity → routing and addressing |
| **`[OneWay]`** | Queue publish (SQS/SNS, Service Bus, MassTransit) | `[OneWay]` silently discarded exceptions **and** return values; a queue gives durability the original lacked |
| **Remoting contexts / `ContextBoundObject`** | ASP.NET Core middleware, gRPC interceptors, DI decorators | `ContextBoundObject` compiles but does nothing |
| **Custom channel sinks** (`IClientChannelSink`) | gRPC `Interceptor`, `DelegatingHandler`, middleware ([14](./14-middleware-migration.md)) | Direct conceptual analogue |
| **`TrackingServices` / `ITrackingHandler`** | `ILogger` + OpenTelemetry ([12](./12-logging-migration.md)) | Modern observability is strictly richer |
| **`RemotingException`** | `RpcException` + `StatusCode`, or HTTP status + `ProblemDetails` | See the mapping table in Step 9 |
| **`CallContext.SetData`** (logical call context) | `AsyncLocal<T>`; propagate cross-process via gRPC metadata / HTTP headers | `CallContext` is removed |
| **`TypeFilterLevel`** | Contract-first schemas (protobuf) — type-carrying polymorphic payloads are simply not expressible | The vulnerability class is *designed out*, not configured away |
| **`AppDomain.CreateDomain`** | `AssemblyLoadContext`, or a separate process + IPC | See Step 6 |
| **`[Synchronization]`** | Explicit `lock` / `SemaphoreSlim` / `Channel<T>`, or a stateless service | **No equivalent** — silent thread-safety regression, see Step 9 |

---

## Step 5: Remove the `MarshalByRefObject` base class

`MarshalByRefObject` still compiles, which makes it tempting to leave in place. Don't — it is misleading and blocks reasoning about value semantics. Microsoft's own guidance is to *"discontinue use of `MarshalByRefObject`."*

```csharp
// Before
public class OrderService : MarshalByRefObject, IOrderService
{
    public Order GetOrder(int id) { /* ... */ }
    public override object InitializeLifetimeService() => null;   // infinite lease
}

// After — extract the interface (this is the strangler seam), drop the base class
public interface IOrderService
{
    Task<Order?> GetOrderAsync(int id, CancellationToken ct = default);
}

public sealed class OrderService : IOrderService { /* ... */ }
```

Hierarchy rules:

1. **Leaf service classes** — delete `: MarshalByRefObject`. Extract an interface first if none exists.
2. **`MarshalByRefObject` as a polymorphic parameter or return type** (e.g. `void Register(MarshalByRefObject o)`) — replace with a purpose-built interface. This is a design decision, not a mechanical edit → **flag for human review**.
3. **Overrides of `InitializeLifetimeService`** — delete them. `return null` ("infinite lease") is expressed as a DI singleton. Leaving the override yields `CS0672`.
4. **Classes deriving from an in-box type that itself derives from `MarshalByRefObject`** — `Stream`, `Component`, `TextWriter`, `WaitHandle`, `Timer`, `Uri`, `RegistryKey`, … → **no change needed, do not flag**. Dozens of in-box types descend from `MarshalByRefObject`, which makes bare inheritance the **least reliable** detection signal.
5. **`ContextBoundObject`** — also delete, but note that removing it silently drops any `[Synchronization]` protection (Step 9).

---

## Step 6: The AppDomain angle (often the real story)

`AppDomain.CreateDomain("x")` compiles with `SYSLIB0024` and throws at runtime:

```
System.PlatformNotSupportedException: Secondary AppDomains are not supported on this platform.
```

Some `AppDomain` members still work (`UnhandledException`), and some silently no-op (`SetCachePath`) — so the mere presence of `AppDomain` code is not an error signal; the **specific member** matters.

**Critical caveat:** `AssemblyLoadContext` provides *assembly* isolation, **not** *object* isolation, and gives you **no marshaling layer**. Microsoft: *"`AssemblyLoadContext` does not provide any security features. All code has full permissions of the process."* Cross-AppDomain remoting calls must therefore become **either direct in-process calls (usually correct) or real IPC** — `AssemblyLoadContext` alone never preserves the semantics.

| Original AppDomain purpose | Correct replacement |
|---|---|
| Load/unload plugins, version isolation | Collectible `AssemblyLoadContext` (`isCollectible: true`) + `AssemblyDependencyResolver`. Share **only an interface** loaded from the default ALC, or you hit the classic `Unable to cast object of type 'Plugin' to type 'Plugin'` error |
| Fault isolation (untrusted or crash-prone code) | **Separate process** + IPC. ALC does not contain crashes or `Environment.Exit` |
| Security sandboxing | **OS boundaries** — containers ([19](./19-linux-containerization.md)), separate user accounts, VMs. Neither ALC nor CAS provides this |
| Only existed so remoting could be used locally | **Delete the boundary** and call directly in-process |

---

## Step 7: BinaryFormatter is a hard blocker

`BinaryClientFormatterSink` / `BinaryServerFormatterSink` are `BinaryFormatter` wrappers — the dependency is structural, not incidental. This is the one place where the target runtime major genuinely matters:

| Runtime | `BinaryFormatter` status |
|---|---|
| .NET 5 | `Serialize`/`Deserialize` obsolete as **warning** (`SYSLIB0011`); prohibited by default in ASP.NET |
| .NET 7 | `SYSLIB0011` escalated to **error** for those methods |
| **.NET 8** | Methods **throw `NotSupportedException`** on most project types; the type itself obsolete as error. Opt-out flag still worked |
| **.NET 9 / .NET 10** | **Implementation removed from the runtime.** Always throws `PlatformNotSupportedException: BinaryFormatter serialization and deserialization have been removed.` The backwards-compatibility flag **no longer helps** |

There is an unsupported `System.Runtime.Serialization.Formatters` compatibility package plus `<EnableUnsafeBinaryFormatterSerialization>`. Microsoft: *"The compatibility package is not supported and unsafe. We strongly recommend against taking a dependency on this package."* **For a remoting migration it is always the wrong choice** — remoting is being removed anyway, so the DTOs must be reworked regardless.

### DTO rework rules

| Legacy pattern | Replacement | Diagnostic |
|---|---|---|
| `[Serializable]` | **Delete it** — `System.Text.Json` doesn't need it | — |
| `[NonSerialized]` | `[JsonIgnore]` | — |
| `ISerializable` + `.ctor(SerializationInfo, StreamingContext)` | `JsonConverter<T>` | `SYSLIB0051` |
| `ISerializationSurrogate` / `SurrogateSelector` | `JsonConverter<T>` (no surrogate concept exists) | `SYSLIB0050` |
| `[OnDeserialized]` / `[OnSerializing]` | `IJsonOnDeserialized` / `IJsonOnSerializing` (.NET 7+) | **none — silent break** |
| Custom exceptions with `[Serializable]` + `GetObjectData` | Remove all serialization scaffolding | `SYSLIB0051` |
| Private/readonly field state | `[JsonInclude]`, constructor binding, or a converter | **none — silent data loss** |
| Custom `SerializationBinder` | **Dead code — delete, do not port** | — |

> 🚨 **Two silent failures to treat as hard blockers, not warnings:**
> - `[OnDeserialized]` **compiles fine and never fires** under `System.Text.Json`.
> - Remoting serialized **fields (including private ones)**; `System.Text.Json` serializes **public properties**. DTOs carrying private state lose it silently.

Replacements: `System.Text.Json` (default, see [06](./06-package-migrations.md)); protobuf / `protobuf-net.Grpc` when going gRPC (lets you keep `[DataContract]`-style contracts with `Order =` field numbers); `MessagePack` for compact binary / StreamJsonRpc.

---

## Step 8: Transformation templates

### (H) `TcpChannel` + `WellKnownServiceType` Singleton → gRPC

**Before**
```csharp
public class OrderService : MarshalByRefObject
{
    public Order GetOrder(int id) { /* ... */ }
    public override object InitializeLifetimeService() => null;
}

// Host
var channel = new TcpChannel(8000);
ChannelServices.RegisterChannel(channel, ensureSecurity: true);
RemotingConfiguration.RegisterWellKnownServiceType(
    typeof(OrderService), "OrderService", WellKnownObjectMode.Singleton);
```

**After — contract**
```proto
syntax = "proto3";
option csharp_namespace = "Orders.Grpc";
package orders;

service OrderService {
  rpc GetOrder (GetOrderRequest) returns (OrderReply);
}
message GetOrderRequest { int32 id = 1; }
message OrderReply {
  int32 id = 1;
  string customer_name = 2;
  OrderStatus status = 3;
}
enum OrderStatus { ORDER_STATUS_UNSPECIFIED = 0; PENDING = 1; SHIPPED = 2; }
```

**After — server `.csproj`**
```xml
<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>   <!-- or net10.0 -->
    <Nullable>enable</Nullable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Grpc.AspNetCore" Version="2.80.0" />
  </ItemGroup>
  <ItemGroup>
    <Protobuf Include="Protos\order.proto" GrpcServices="Server" />
  </ItemGroup>
</Project>
```

**After — `Program.cs`** (see [05](./05-hosting-deployment-migration.md))
```csharp
var builder = WebApplication.CreateBuilder(args);

builder.Services.AddGrpc(o => o.EnableDetailedErrors = builder.Environment.IsDevelopment());
// WellKnownObjectMode.Singleton -> AddSingleton (MUST now be thread-safe)
builder.Services.AddSingleton<IOrderRepository, OrderRepository>();

var app = builder.Build();
app.MapGrpcService<OrderGrpcService>();
app.Run();
```

**After — service implementation**
```csharp
public sealed class OrderGrpcService : Orders.Grpc.OrderService.OrderServiceBase
{
    private readonly IOrderRepository _repo;
    public OrderGrpcService(IOrderRepository repo) => _repo = repo;

    public override async Task<OrderReply> GetOrder(
        GetOrderRequest request, ServerCallContext context)
    {
        var order = await _repo.FindAsync(request.Id, context.CancellationToken);
        if (order is null)
            throw new RpcException(new Status(StatusCode.NotFound, $"Order {request.Id} not found."));

        return new OrderReply
        {
            Id           = order.Id,
            CustomerName = order.CustomerName,
            Status       = (OrderStatus)order.Status
        };
    }
}
```

The class **no longer derives from `MarshalByRefObject`** and `InitializeLifetimeService` is gone — singleton lifetime is now DI's job.

### `Activator.GetObject` client → typed gRPC client with DI

**Before** — `Activator.GetObject` produces `CS0117` on modern .NET
```csharp
var channel = new TcpChannel();
ChannelServices.RegisterChannel(channel, ensureSecurity: true);
var svc = (OrderService)Activator.GetObject(
    typeof(OrderService), "tcp://server:8000/OrderService");
var order = svc.GetOrder(42);      // transparent proxy, synchronous
```

**After — client `.csproj`**
```xml
<ItemGroup>
  <PackageReference Include="Grpc.Net.ClientFactory" Version="2.80.0" />
  <PackageReference Include="Google.Protobuf"        Version="3.35.1" />
  <PackageReference Include="Grpc.Tools" Version="2.83.0" PrivateAssets="all" />
</ItemGroup>
<ItemGroup>
  <Protobuf Include="Protos\order.proto" GrpcServices="Client" />
</ItemGroup>
```
(`Grpc.Tools` legitimately versions ahead of the runtime packages — not an error.)

**After — config-driven registration becomes DI + `appsettings.json`**
```jsonc
// appsettings.json — replaces <client><wellknown url="tcp://..." /></client>
{ "Services": { "OrderService": { "Address": "https://orders.internal:8443" } } }
```
```csharp
builder.Services
    .AddGrpcClient<Orders.Grpc.OrderService.OrderServiceClient>((sp, o) =>
    {
        var cfg = sp.GetRequiredService<IConfiguration>();
        o.Address = new Uri(cfg["Services:OrderService:Address"]!);
    })
    .AddStandardResilienceHandler();   // Microsoft.Extensions.Http.Resilience

public sealed class OrderReader(Orders.Grpc.OrderService.OrderServiceClient client)
{
    public async Task<OrderReply?> ReadAsync(int id, CancellationToken ct)
    {
        try
        {
            return await client.GetOrderAsync(new GetOrderRequest { Id = id },
                                              cancellationToken: ct);
        }
        catch (RpcException ex) when (ex.StatusCode == StatusCode.NotFound)
        {
            return null;   // was: RemotingException / null-returning proxy
        }
    }
}
```

### (D) `IpcChannel` same-machine → named pipes

**Before**
```csharp
var channel = new IpcChannel("MyAppPipe");
ChannelServices.RegisterChannel(channel, ensureSecurity: true);
RemotingConfiguration.RegisterWellKnownServiceType(
    typeof(LocalService), "LocalService", WellKnownObjectMode.Singleton);
// client: Activator.GetObject(typeof(LocalService), "ipc://MyAppPipe/LocalService")
```

**After, option 1 — gRPC over named pipes (requires .NET 8+)**
```csharp
// Server
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddGrpc();
builder.WebHost.ConfigureKestrel(o =>
{
    if (OperatingSystem.IsWindows())
        o.ListenNamedPipe("MyAppPipe");
    else
        o.ListenUnixSocket(Path.Combine(Path.GetTempPath(), "myapp.sock"));

    o.ConfigureEndpointDefaults(l => l.Protocols = HttpProtocols.Http2);
});
var app = builder.Build();
app.MapGrpcService<LocalGrpcService>();
app.Run();
```
```csharp
// Client — custom ConnectCallback
var connectionFactory = new NamedPipesConnectionFactory("MyAppPipe");
var handler = new SocketsHttpHandler
{
    ConnectCallback = connectionFactory.ConnectAsync,
    EnableMultipleHttp2Connections = true
};
using var channel = GrpcChannel.ForAddress("http://localhost",
    new GrpcChannelOptions { HttpHandler = handler });
var client = new LocalService.LocalServiceClient(channel);
```
> **Caveat:** a channel using `ConnectCallback` **loses** client-side load balancing and `GrpcChannel.State` connectivity tracking — using them throws `InvalidOperationException`. Harmless for IPC.

**After, option 2 — StreamJsonRpc (lowest ceremony, closest to remoting's ergonomics)**
```csharp
// Shared contract — a plain C# interface, no attributes
public interface IOrderService
{
    Task<Order?> GetOrderAsync(int id, CancellationToken ct = default);
}

// Server
await using var pipeServer = new NamedPipeServerStream(
    "myapp", PipeDirection.InOut, NamedPipeServerStream.MaxAllowedServerInstances,
    PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
await pipeServer.WaitForConnectionAsync(ct);
using var rpc = JsonRpc.Attach(pipeServer, new OrderService());
await rpc.Completion;

// Client — proxy generated from the interface
await using var pipeClient = new NamedPipeClientStream(
    ".", "myapp", PipeDirection.InOut, PipeOptions.Asynchronous);
await pipeClient.ConnectAsync(ct);
using var proxy = JsonRpc.Attach<IOrderService>(pipeClient);
var order = await proxy.GetOrderAsync(42, ct);
```
**Prefer this when the legacy code already used a shared interface** — the interface survives verbatim and only the wiring changes.

Named-pipe security (remoting's `ensureSecurity: true` has no direct analogue): apply `PipeSecurity` on the server, validate the server's owner SID on the client, and pass `TokenImpersonationLevel.None`/`Anonymous` to guard against impersonation-based privilege escalation.

### (F) Remoting event / callback → gRPC server streaming or SignalR

**Before** — the client registers a delegate and the server invokes it across the boundary. This required the client object to be a `MarshalByRefObject`, and `BeginInvoke` for async. **Both are dead.**

**After — gRPC server streaming**
```proto
service OrderEvents {
  rpc Subscribe (SubscribeRequest) returns (stream OrderEvent);
}
```
```csharp
// Server
public override async Task Subscribe(SubscribeRequest request,
    IServerStreamWriter<OrderEvent> responseStream, ServerCallContext context)
{
    await foreach (var evt in _bus.ReadAllAsync(context.CancellationToken))
        await responseStream.WriteAsync(evt);
}

// Client
using var call = client.Subscribe(new SubscribeRequest());
await foreach (var evt in call.ResponseStream.ReadAllAsync(ct))
    Handle(evt);
```

**After — SignalR** (better for many clients, browsers, auto-reconnect)
```csharp
var conn = new HubConnectionBuilder()
    .WithUrl("https://orders.internal/hubs/orders")
    .WithAutomaticReconnect()
    .Build();
conn.On<OrderEvent>("OrderChanged", Handle);
await conn.StartAsync(ct);
```

### (E) `[OneWay]` → queue-based messaging

**Before**
```csharp
[OneWay]                                   // CS0246 on modern .NET
public void LogAudit(AuditRecord r) { }    // exceptions AND return value silently discarded
```

**After (AWS SQS)**
```csharp
public sealed class AuditPublisher(IAmazonSQS sqs, IOptions<AuditOptions> opt)
{
    public Task PublishAsync(AuditRecord r, CancellationToken ct) =>
        sqs.SendMessageAsync(new SendMessageRequest
        {
            QueueUrl    = opt.Value.QueueUrl,
            MessageBody = JsonSerializer.Serialize(r),
            // FIFO only: MessageGroupId / MessageDeduplicationId
        }, ct);
}
```
This **improves** on `[OneWay]` — durable, retryable, DLQ-capable — but delivery becomes at-least-once, so **handlers must be idempotent**.

### Lease / sponsorship → explicit session with TTL

```csharp
// Before: CAO + ClientSponsor kept a per-client server object alive
// After: explicit session, explicit expiry
public sealed class SessionService(IDistributedCache cache)      // Redis / ElastiCache
{
    private static readonly DistributedCacheEntryOptions Ttl = new()
        { SlidingExpiration = TimeSpan.FromMinutes(20) };        // ~ renewOnCallTime

    public async Task<string> CreateAsync(SessionState s, CancellationToken ct)
    {
        var id = Guid.NewGuid().ToString("N");
        await cache.SetStringAsync(id, JsonSerializer.Serialize(s), Ttl, ct);
        return id;
    }

    // Replaces ISponsor.Renewal — now an explicit, auditable operation
    public async Task<bool> RenewAsync(string id, CancellationToken ct)
        => await cache.GetStringAsync(id, ct) is not null;        // sliding TTL refreshes
}
```

For *connection* liveness (not object lifetime), use gRPC keepalive instead:
```csharp
var handler = new SocketsHttpHandler
{
    KeepAlivePingDelay             = TimeSpan.FromSeconds(60),
    KeepAlivePingTimeout           = TimeSpan.FromSeconds(30),
    EnableMultipleHttp2Connections = true
};
```

### AWS hosting notes

- **ALB + gRPC on ECS/EKS** is the documented path. Hard constraints for gRPC target groups: listener protocol **must be HTTPS**; only `forward` listener-rule actions; only `instance` / `ip` target types (**no Lambda**); health-check path must be `/package.service/method` (default `/AWS.ALB/healthcheck`); success `Matcher` codes range 0–99 with **default `12`** (`UNIMPLEMENTED`, a convenient liveness probe). ALB routes on package/service/method and supports unary plus all three streaming modes.
- **NLB** — when you need TCP passthrough or app-terminated mTLS.
- **API Gateway** — REST/HTTP APIs only; pick it only if the target is Web API, not gRPC.
- **SQS / SNS / EventBridge** — the `[OneWay]` replacement: SQS for work queues (FIFO if ordering matters), SNS for fan-out, EventBridge for routed/filtered domain events.

---

## Step 9: Gotchas

**Security — this is why remoting was killed.** `TypeFilterLevel` was never a real boundary: `Low` (the default) blocks deserializing `MarshalByRefObject`, `DelegateSerializationHolder`, `ObjRef`, `IEnvoyInfo`, `ISponsor` and still has documented RCE bypasses, plus `DataSet`-based DoS payloads; `Full` is trivially exploitable. Real CVE-class impact: **CVE-2024-29847** (Ivanti EPM, unauthenticated pre-auth RCE via `.NET Remoting TcpChannel` deserialization, public PoC) and **CVE-2024-29059** (.NET Framework HTTP remoting `ObjRef` leak → RCE; **on CISA's Known Exploited Vulnerabilities list**). Microsoft: *"you should never expose a .NET Remoting endpoint to the Internet or to untrusted clients."*

> **Any internet-reachable remoting endpoint found during assessment is an active security finding, not a migration backlog item.** Report it referencing these CVEs — see [08](./08-auth-security-migration.md).

**Chattiness.** Remoting made fine-grained property access look free — `customer.FirstName` was a network round trip. Ported naively, an N-property read becomes N round trips. **Batch and coarsen**: return whole DTOs, add bulk operations, eliminate chatty property walks. This is the single most common cause of "the migration made it slower." When a migrated interface exposes more than ~5 fine-grained members, redesign it before swapping the transport.

**Pass-by-reference is genuinely gone.** Any design where the server calls back into a client-supplied `MarshalByRefObject` (or vice versa) must be redesigned — usually inverted into streaming/events, or removed. No configuration restores it.

**`ObjRef` / URI identity vs stateless services.** Remoting identity was a URI plus process-local state. Modern services are stateless and load-balanced: consecutive calls may hit different instances. Anything relying on per-proxy server state needs an explicit session store, plus sticky routing or externalized state behind an ALB.

**Assembly-version binding over the wire.** Remoting payloads embedded assembly-qualified type names, so client and server had to agree on assembly versions and `Type.GetType` / `SerializationBinder` behaviour was load-bearing. Protobuf/JSON contracts are name-and-number based: versioning becomes a schema concern (**never renumber protobuf fields — add, don't repurpose**). Custom `SerializationBinder` logic is dead code; delete it rather than porting it.

**Exception fidelity.** Remoting serialized arbitrary exceptions and rethrew them client-side — convenient, and an information-disclosure vector. gRPC gives a status code plus a string; any non-`RpcException` becomes `StatusCode.Unknown` with the generic message `"Exception was thrown by handler"`. Keep `EnableDetailedErrors` **development-only**.

| Remoting / .NET exception | gRPC `StatusCode` | HTTP |
|---|---|---|
| `RemotingException` (generic failure) | `Unknown` / `Internal` | 500 |
| `RemotingTimeoutException` | `DeadlineExceeded` | 504 |
| Server unreachable / channel failure | `Unavailable` | 503 |
| `ArgumentException` / validation | `InvalidArgument` | 400 |
| Not found (bad URI / missing object) | `NotFound` | 404 |
| `UnauthorizedAccessException` | `PermissionDenied` / `Unauthenticated` | 403 / 401 |
| `NotSupportedException` (no such method) | `Unimplemented` | 501 |
| Cancellation | `Cancelled` | 499 |

For structured errors use the rich error model via `Grpc.StatusProto` (`Google.Rpc.Status` + `BadRequest`/`ErrorInfo`) — but note errors travel in **headers, typically capped at 8 KB**.

**Distributed transactions.** Remoting could flow `System.Transactions`/MSDTC ambient transactions (and `System.EnterpriseServices` COM+ is entirely absent). gRPC and REST have **no ambient distributed transaction support**, and `TransactionScope` will not propagate across the new boundary. Redesign with the Saga / compensating-transaction pattern, or collapse participants into one service with a single local transaction.

> 🚨 **Silent failure:** `TransactionScope` still compiles and *appears* to work while quietly no longer being distributed. **Flag any `TransactionScope` spanning a former remoting call as a correctness risk.**

**Threading and `[Synchronization]`.** `[Synchronization]` (a `ContextAttribute` providing automatic per-instance call serialization) has **no equivalent**, and `ContextBoundObject` compiles while doing nothing.

> 🚨 **Silent failure:** classes that relied on `[Synchronization]` become **non-thread-safe with no compile error** — a latent race. Replace with explicit `lock` / `SemaphoreSlim` / `Channel<T>` serialization, or make the service stateless. Related: `SingleCall` → scoped DI is safe, but `Singleton` → `AddSingleton` now demands genuine thread-safety.

**`CallContext`** (logical call context) → `AsyncLocal<T>` in-process; propagated across processes only via explicit gRPC metadata / HTTP headers.

**`Delegate.BeginInvoke` / `EndInvoke` throw `PlatformNotSupportedException`** — they were remoting-backed. Migrate to `Task.Run` / `async`-`await`.

**`ensureSecurity: true` is not preserved.** `TcpChannel`/`IpcChannel` security must be reconstructed explicitly: TLS for gRPC, `PipeSecurity` + owner validation for named pipes, mTLS or certificate auth where remoting relied on SSPI.

---

## Step 10: Compiler errors and analyzer IDs

| Diagnostic | Message | Trigger | Remedy |
|---|---|---|---|
| **CS0234** | `The type or namespace name 'Channels' does not exist in the namespace 'System.Runtime.Remoting'` | `using System.Runtime.Remoting.Channels;` and every other sub-namespace | Delete the `using`; re-architect per Step 1 |
| **CS0234** | `The type or namespace name 'RemotingException' does not exist in the namespace 'System.Runtime.Remoting'` | Fully-qualified `RemotingException`, `RemotingConfiguration`, `RemotingServices`, `ObjRef`, `WellKnownObjectMode` | `RpcException` / HTTP errors (Step 9) |
| **CS0246** | `The type or namespace name 'TcpChannel' could not be found` | Unqualified `TcpChannel`, `IpcChannel`, `HttpChannel`, `ILease`, `ClientSponsor`, `RealProxy`, `ObjRef` | Per-type replacement (Step 4) |
| **CS0246** | `… 'OneWay' could not be found` **and** `… 'OneWayAttribute' could not be found` | `[OneWay]` | Queue messaging (Step 8). Roslyn emits **two** errors per attribute (short + `Attribute` form) — dedupe when counting |
| **CS0246** | `… 'Synchronization' / 'SynchronizationAttribute' could not be found` | `[Synchronization]` | Explicit locking (Step 9) |
| **CS0103** | `The name 'ChannelServices' does not exist in the current context` | `ChannelServices.RegisterChannel`, `RemotingConfiguration.Configure`, `RemotingServices.Connect` after the `using` is removed | Endpoint mapping / DI registration |
| **CS0117** | `'Activator' does not contain a definition for 'GetObject'` | `Activator.GetObject(type, url)` | Typed client from DI (Step 8). **Distinctive** — the type exists, the member doesn't |
| **CS0672** | `Member 'MyService.InitializeLifetimeService()' overrides obsolete member 'MarshalByRefObject.InitializeLifetimeService()'` | Overriding `InitializeLifetimeService` | **Delete the override**; use DI lifetime (Step 5) |
| **SYSLIB0010** (warning) | Remoting APIs are obsolete; also throw at runtime | `GetLifetimeService()`, `InitializeLifetimeService()` | Remove the calls |
| **SYSLIB0011** (**error** on .NET 8+) | `'BinaryFormatter' is obsolete: 'BinaryFormatter serialization is obsolete and should not be used.'` | Any `BinaryFormatter` / `IFormatter` / `Formatter` reference | `System.Text.Json` / protobuf / MessagePack (Step 7) |
| **SYSLIB0024** (warning) | `'AppDomain.CreateDomain(string)' is obsolete: 'Creating and unloading AppDomains is not supported and throws an exception.'` | `AppDomain.CreateDomain` | `AssemblyLoadContext` / separate process (Step 6) |
| **SYSLIB0050** (warning) | `Formatter-based serialization is obsolete` | `IFormatterConverter`, `TypeFilterLevel`, `FormatterTypeStyle`, `ISerializationSurrogate`, `SurrogateSelector`, `IObjectReference` | Remove formatter scaffolding (Step 7) |
| **SYSLIB0051** (warning) | Legacy serialization support APIs are obsolete | `.ctor(SerializationInfo, StreamingContext)`, `ISerializable.GetObjectData`, `IObjectReference.GetRealObject` | Remove (Step 7) |
| **CA2300–CA2330** | Insecure deserializer analyzer rules | `BinaryFormatter` (CA2300/01/02), `NetDataContractSerializer` (CA2311/12), `ObjectStateFormatter` (CA2315), `JavaScriptSerializer` (CA2321/22), `Newtonsoft.Json` `TypeNameHandling` (CA2326–CA2330) | Remediate, **do not suppress** |
| **MSB3825** (build) | Binary-formatted resources may deserialize via `BinaryFormatter` | `.resx` with binary resources | Relevant mainly on ≤ .NET 8; suppress with `GenerateResourceWarnOnBinaryFormatterUse=false` when targeting .NET 9+ |
| **Runtime `TypeLoadException`** | `Could not load type 'System.Runtime.Remoting.Channels.IChannel' from assembly 'mscorlib, …'` | A **third-party / precompiled** assembly using remoting internally | Upgrade the dependency; the Windows Compatibility Pack does **not** help. See [27](./27-blocked-packages-and-build-integrity.md) |

**Runtime exception messages** (useful for triaging post-build failures):
```
System.PlatformNotSupportedException: Remoting is not supported on this platform.
System.PlatformNotSupportedException: Secondary AppDomains are not supported on this platform.
System.PlatformNotSupportedException: Operation is not supported on this platform.          // Delegate.BeginInvoke
System.PlatformNotSupportedException: BinaryFormatter serialization and deserialization have been removed.
```

> **Detector heuristic:** `CS0234` on a `System.Runtime.Remoting.*` **sub-namespace** is the most reliable, lowest-false-positive signal. Inheriting from `MarshalByRefObject` is the **least** reliable and must never alone trigger a migration finding.

**Tooling reality check.** No Microsoft tool helps here. .NET Upgrade Assistant is officially deprecated (superseded by the GitHub Copilot modernization agent) and never had remoting transforms — it retargets the TFM and leaves you facing the `CS0234` wall. .NET Portability Analyzer / API Port is deprecated with its backend shut down (offline mode retains some *inventory* value). `try-convert` only migrates project-file format. **Config-file detection (`<system.runtime.remoting>`) and Step-1 classification are entirely manual.**

---

## Step 11: Phasing (perform Phases 1–2 while still on .NET Framework)

| Phase | Action | Runs on |
|---|---|---|
| **0** | **Classify** every usage site per Step 1 | — |
| **1** | **Extract plain C# interfaces.** For each `MarshalByRefObject` service define `IFoo`, implement it, and change all callers to depend on `IFoo` | .NET Framework — ships independently, zero behaviour change. **Highest leverage, lowest risk** |
| **2** | **Make the interface async** — `Foo()` → `Task<T> FooAsync(…, CancellationToken)` | .NET Framework — remoting was sync-by-default; every modern transport is async-first |
| **3** | **Swap the transport behind the interface** (strangler fig): implement `IFoo` twice — legacy remoting adapter and new gRPC/pipe client — and select by config flag. Callers never change | Both |
| **4** | **Stand up the new service on modern .NET**, port DTOs off `BinaryFormatter` (Step 7), cut over per operation. `SingleCall` services first, CAO/sessionful last | Modern .NET |
| **5** | **Delete remoting**: base classes, config sections, `[Serializable]`/`ISerializable` scaffolding | Modern .NET |

### Can the .NET Framework side talk to the new .NET side during transition?

Yes — but **only over the new protocol**, never at the remoting boundary. A protocol-level remoting shim is **not feasible**: the wire format is `BinaryFormatter`-based and that implementation is gone from .NET 9+. An *interface*-level shim (Phases 1–3) is the supported mechanism.

- **HTTP/REST from .NET Framework** — works everywhere; **the most reliable bridge**. If transition interop is critical and the topology is uncertain, bridge over REST even when the end state is gRPC.
- **gRPC client on .NET Framework 4.6.1+ via `Grpc.Net.Client`** — "limited support", requiring **all** of: `System.Net.Http.WinHttpHandler` (≥ 6.0.1) wired via `GrpcChannelOptions.HttpHandler`; **Windows 11+ or Windows Server 2019+**; **TLS only** (no plaintext h2c). On **Windows Server 2019/2022 only unary and server-streaming work — client-streaming and bidirectional streaming do not**. It is also slower than on modern .NET.
  ```csharp
  var channel = GrpcChannel.ForAddress("https://localhost:5001",
      new GrpcChannelOptions { HttpHandler = new WinHttpHandler() });
  ```
- **gRPC *server* on .NET Framework** — **not possible** with `grpc-dotnet` (it requires ASP.NET Core). Direction matters: modern-.NET → legacy-Framework gRPC calls have no supported path.
- **`Grpc.Core` (C-core)** — could host a server on Framework, but is unsupported by Microsoft, in maintenance mode, and not recommended. Treat as unavailable.
- **gRPC-Web** — fallback where HTTP/2 is unavailable or for browsers, at the cost of client-streaming and bidirectional streaming.

Third-party shims (CoreRemoting, GoreRemoting) preserve remoting's API *shape* over gRPC/WebSockets but explicitly drop `MarshalByRef` semantics — GoreRemoting states *"No support for MarshalByRef behaviour. Everything is by value."* They can shorten a migration; they are not drop-in and not Microsoft-supported.

---

## Step 12: Validation Checklist

✅ Every remoting usage site has a Step-1 verdict recorded; **nothing was defaulted to gRPC without classification**
✅ No `System.Runtime.Remoting.*` sub-namespace `using` remains; no `TcpChannel` / `IpcChannel` / `HttpChannel` / `ChannelServices` / `RemotingConfiguration` / `RemotingServices` / `Activator.GetObject` references remain
✅ No `<system.runtime.remoting>` block remains in any `app.config` / `web.config`; endpoints and client addresses live in `appsettings.json` + DI
✅ `: MarshalByRefObject` is removed from all service classes; all `InitializeLifetimeService` overrides are deleted; in-box `MarshalByRefObject` descendants (`Stream`, `Component`, `Timer`, `Uri`, …) were **not** touched
✅ No `BinaryFormatter` / `SoapFormatter` reference remains, and the unsupported `System.Runtime.Serialization.Formatters` compatibility package was **not** added
✅ Every `[OnDeserialized]` / `[OnSerializing]` on a migrated DTO was converted to `IJsonOnDeserialized` / `IJsonOnSerializing`, and DTOs carrying private field state were audited for silent data loss
✅ Every class that relied on `[Synchronization]` has explicit synchronization, and every `AddSingleton` service formerly registered as `WellKnownObjectMode.Singleton` is verifiably thread-safe
✅ Every `TransactionScope` that used to span a remoting call has been reviewed and redesigned (Saga) or collapsed into one local transaction
✅ `RemotingException` handlers were rewritten to `RpcException` + `StatusCode` (or HTTP status), and `EnableDetailedErrors` is development-only
✅ Human review was requested for: `MarshalByRefObject` as a polymorphic parameter/return type; server→client callbacks on client-supplied MBR objects; CAO/sessionful lifetime; custom channel sinks
✅ Any internet-reachable legacy remoting endpoint was reported as a **security finding** (CVE-2024-29847 / CVE-2024-29059), not as tech debt
✅ Interfaces with more than ~5 fine-grained members were coarsened before the transport swap
✅ `dotnet build` produces no `CS0234` / `CS0246` / `CS0103` / `CS0117` / `CS0672` in the affected projects, and no `SYSLIB0010` / `SYSLIB0011` / `SYSLIB0024` / `SYSLIB0050` / `SYSLIB0051` diagnostics

---

## See Also

- [20-wcf-to-corewcf-migration.md](./20-wcf-to-corewcf-migration.md) – WCF → CoreWCF (the right target when SOAP/WSDL fidelity is contractual)
- [06-package-migrations.md](./06-package-migrations.md) – NuGet package replacements, `System.Text.Json`
- [11-configuration-migration.md](./11-configuration-migration.md) – `<system.runtime.remoting>` → `appsettings.json`
- [13-dependency-injection-migration.md](./13-dependency-injection-migration.md) – DI lifetimes replacing `WellKnownObjectMode`
- [05-hosting-deployment-migration.md](./05-hosting-deployment-migration.md) – Kestrel hosting, `Program.cs`
- [08-auth-security-migration.md](./08-auth-security-migration.md) – transport security replacing `ensureSecurity` / `TypeFilterLevel`
- [27-blocked-packages-and-build-integrity.md](./27-blocked-packages-and-build-integrity.md) – third-party assemblies with internal remoting dependencies
- [19-linux-containerization.md](./19-linux-containerization.md) – containers as the AppDomain isolation replacement
