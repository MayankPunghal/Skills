# Playbook: ambient context, .NET Remoting, BinaryFormatter

**Rules:** API-REMOTING, API-BINARYFORMATTER (assessment); API-CALLCONTEXT, API-BINARYFORMATTER (residue).
**Engines:** DevTx KB 28 covers CallContext → AsyncLocal and BinaryFormatter replacement (the DevTx run does it);
AWS Transform flags but does not redesign it. With Transform as the engine, Claude does it from this playbook and KB 28.

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

## BinaryFormatter (and SoapFormatter, NetDataContractSerializer, LosFormatter, ObjectStateFormatter)

Removed in .NET 9. Per use:
- **serializing exceptions or objects for logging** → `System.Text.Json` or `ToString()`;
- **deep clone** → a copy constructor or JSON round trip;
- **data persisted or sent elsewhere in this format** → stop and decide with the owner: a one-off conversion of stored
  data, or a reader kept in a tool outside the app. Never re-enable it with the unsupported compatibility package in
  production code.

## Done when

No API-CALLCONTEXT / API-BINARYFORMATTER residue; a load test with concurrent requests shows no context bleed
(each response carries its own request id).
