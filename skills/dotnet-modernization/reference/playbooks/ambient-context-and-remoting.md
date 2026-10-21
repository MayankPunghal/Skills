# Playbook: ambient context, .NET Remoting, BinaryFormatter

**Rules:** API-REMOTING, API-BINARYFORMATTER (assessment); API-CALLCONTEXT, API-BINARYFORMATTER (residue).
**Engines:** DevTx KB 28 covers CallContext → AsyncLocal and BinaryFormatter replacement (the DevTx run does it);
AWS Transform flags but does not redesign it. With Transform as the engine, Claude does it from this playbook and KB 28.

## Contents

- [CallContext / ambient request context](#callcontext--ambient-request-context)
- [Remoting](#remoting)
  - [Classify each use first](#classify-each-use-first)
  - [Concept map](#concept-map)
  - [AppDomains and Code Access Security](#appdomains-and-code-access-security)
  - [Exceptions across the boundary](#exceptions-across-the-boundary)
- [BinaryFormatter](#binaryformatter-and-soapformatter-netdatacontractserializer-losformatter-objectstateformatter)
- [Transactions across resources (MSDTC)](#transactions-across-resources-msdtc)
- [Done when](#done-when)

## CallContext / ambient request context

1. Find the context class (`CallContext.HostContext`, `CallContext.LogicalGetData/SetData`, `HttpContext.Current.Items`
   used as a per-request bag) and count its uses (`Context.Current.` style accessors).
2. Keep the accessor's shape so the hundreds of call sites do not change:
   ```csharp
   public sealed class Context {
       static readonly AsyncLocal<Context?> _current = new();
       public static Context? Current { get => _current.Value; set => _current.Value = value; }
   }
   ```
3. Set it once per request in middleware (`Context.Current = new Context(...)` before `await next()`, cleared after).
   For background work, set it explicitly at the start of the job.
4. Check every place that read the context on another thread: `AsyncLocal` flows into `Task.Run` and `await`
   continuations, but not into threads created before the value was set (timers, `ThreadPool.QueueUserWorkItem` with
   `UnsafeQueue`), and changes made inside a child task do not flow back to the caller.
5. Better, when the uses are few: inject a scoped service instead of the static accessor.

## Remoting

`System.Runtime.Remoting` does not exist on .NET 10. Cross-process calls → HTTP API or gRPC; same-process uses
(`RealProxy` for interception) → `DispatchProxy` or a decorator.

### Classify each use first

Do not change code until every use has one verdict. Check in this order:

1. **No channel registered** (`ChannelServices.RegisterChannel`, `RemotingConfiguration`, `<channels>` in config). Not distributed at all:
   - `RealProxy` or `ProxyAttribute` used for interception → `DispatchProxy` (interfaces only) or a decorator.
   - `AppDomain.CreateDomain` for plugins or version isolation → a collectible `AssemblyLoadContext`, or a separate process when the plugin can crash.
   - `MarshalByRefObject` with no transport → delete the base class and pass values.
2. **Same machine only** (`IpcChannel`, `ipc://`): call it in-process when both ends can live in one application. Otherwise use gRPC over a Unix domain socket, or StreamJsonRpc. Windows named pipe security does not carry over ([windows-only-apis.md](windows-only-apis.md)).
3. **Across machines** (`TcpChannel`, `HttpChannel`):
   - every method is `[OneWay]` → a queue: SQS, SNS or MassTransit ([aws-managed-services.md](aws-managed-services.md));
   - the server calls back into the client → gRPC server streaming or SignalR ([signalr.md](signalr.md));
   - browsers or outside parties call it → an ASP.NET Core Web API ([web-api.md](web-api.md));
   - a SOAP contract is relied on → CoreWCF ([wcf-services.md](wcf-services.md));
   - anything else → gRPC.

### Concept map

| Remoting | Target | Notes |
|---|---|---|
| Singleton server object (SAO) | A DI singleton behind a service | It must be thread-safe now. Remoting sometimes hid that behind `[Synchronization]` |
| SingleCall server object (SAO) | DI scoped or transient | The cleanest mapping. Migrate these first |
| Client-activated object (CAO) | A session id plus a server-side store with a TTL (`IMemoryCache`, ElastiCache) | No transport keeps per-client objects for free |
| `MarshalByRefObject` by reference | Nothing: pass DTOs by value | The most invasive change. Reference identity does not cross a process boundary |
| `[Serializable]` values | Plain classes with public properties and `System.Text.Json` | Opt in per property |
| `[OneWay]` | A queue message | `[OneWay]` silently drops exceptions and return values. A queue keeps the message |
| `[Synchronization]` | `lock`, `SemaphoreSlim` or `Channel<T>` | No equivalent. Missing it is a silent thread-safety regression |
| Lease and sponsor (`ILease`, `ISponsor`) | A stateless service, or a cache entry with a TTL and an explicit renew call | Object lifetime moves to the cache. Connection liveness moves to gRPC keepalive |
| Remoting events and delegate callbacks | gRPC server streaming, SignalR, or `async` calls | `Delegate.BeginInvoke` and `EndInvoke` throw `PlatformNotSupportedException` on modern .NET |
| `RemotingConfiguration.Configure(file)` | `appsettings.json` and DI registration in `Program.cs` | [config-and-secrets.md](config-and-secrets.md) |
| `Activator.GetObject` client | A typed client from DI (`AddGrpcClient<T>` or `IHttpClientFactory`) | Compile errors once the namespace is gone |
| Custom channel sinks | gRPC interceptors, `DelegatingHandler`, or middleware ([http-handlers-and-modules.md](http-handlers-and-modules.md)) | Direct conceptual match |

### AppDomains and Code Access Security

`AppDomain.CreateDomain` throws `PlatformNotSupportedException` on .NET 10, because secondary AppDomains are not supported. Some AppDomain members still work and some do nothing, so check the member, not the type. Pick the target by purpose:

| Original purpose | Target |
|---|---|
| Load and unload plugins, or run two versions of a library | A collectible `AssemblyLoadContext`. Share only an interface from the default context, or casts fail with "Unable to cast object" errors |
| Contain a crash or a runaway plugin | A separate process, with IPC |
| Sandbox untrusted code | OS boundaries: a container, a separate account, a VM. An `AssemblyLoadContext` is not a sandbox |
| Existed only so remoting worked locally | Delete the boundary and call in-process |

Code Access Security is not enforced on .NET 10. Remove the demands and attributes that depended on it, and move the trust boundary to the OS: container, IAM role, network.

### Exceptions across the boundary

Remoting passed server exceptions back to the caller. Over HTTP or gRPC, map each one on purpose, and log the full exception once on the server:

| Server exception | HTTP | gRPC |
|---|---|---|
| Invalid input (`ArgumentException`, validation errors) | 400 | `InvalidArgument` |
| Not authenticated | 401 | `Unauthenticated` |
| Not allowed | 403 | `PermissionDenied` |
| Item not found | 404 | `NotFound` |
| Conflicting change (concurrency, duplicate key) | 409 | `Aborted` or `AlreadyExists` |
| Remote end unreachable or timed out (`RemotingException`, `SocketException`) | 503 | `Unavailable` |
| Anything else | 500, with `ProblemDetails` and no stack trace | `Internal` |

Retry only the 503 and `Unavailable` cases, and only for idempotent calls.

## BinaryFormatter (and SoapFormatter, NetDataContractSerializer, LosFormatter, ObjectStateFormatter)

Removed in .NET 9. Per use:
- **serializing exceptions or objects for logging** → `System.Text.Json` or `ToString()`;
- **deep clone** → a copy constructor or JSON round trip;
- **data persisted or sent elsewhere in this format** → stop and decide with the owner: a one-off conversion of stored
  data, or a reader kept in a tool outside the app. Never re-enable it with the unsupported compatibility package in
  production code.

## Transactions across resources (MSDTC)

A `TransactionScope` that enlists two resources (two databases, a database and a message queue, or two connections that promote) needs a distributed coordinator. On .NET 7 and later, MSDTC is Windows-only: the `TransactionManager.ImplicitDistributedTransactions` setter is Windows-only, so Linux has no distributed transaction coordinator. Treat distributed transactions as unsupported until a test proves otherwise. A local transaction on one resource still works.

Find them by searching for `TransactionScope`, `System.Transactions` and `EnlistTransaction`. Redesign each one, in this order of preference:

1. **Outbox.** Write the business change and an outbox row in one local transaction. A worker sends the message and marks the row sent. Retries happen, so consumers must be idempotent.
2. **Saga.** For a long process whose steps can be undone, record each step and its compensation, and let a coordinator move the process forward or back.
3. **Two-phase commit** only with a coordinator that has been tested on Linux. Record the test result before the plan relies on it.

## Done when

No API-CALLCONTEXT / API-BINARYFORMATTER residue; a load test with concurrent requests shows no context bleed
(each response carries its own request id), and no `TransactionScope` spans resources without an outbox, a saga or a tested coordinator.
