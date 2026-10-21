# Playbook: HTTP handlers and modules

**Rules:** WEB-MODULE-HANDLER, IIS-MODULES-HANDLERS (assessment); WEB-HANDLER-IFACE, WEB-FORMS-FILE for `.ashx` (residue).
**Engines:** DevTx KB 14 covers modules → middleware; neither engine reliably ports `IHttpAsyncHandler` plumbing
(Begin/End pairs, custom `IAsyncResult`). Claude does it.

## Steps

1. **Inventory**: every `.ashx`, every class implementing `IHttpHandler` / `IHttpAsyncHandler` / `IHttpModule`, every
   `<handlers>` / `<modules>` / `<httpHandlers>` / `<httpModules>` entry in web.config (path, verb, type, preCondition).
2. **Handlers → endpoints.** One endpoint per handler, same path and verbs:
   ```csharp
   app.MapMethods("/gateway.ashx", new[] { "GET", "POST" }, async (HttpContext ctx, GatewayService svc) =>
       await svc.HandleAsync(ctx));
   ```
   Keep the old path (callers have it configured); add a new path only beside it.
3. **Async handlers**: replace `BeginProcessRequest` / `EndProcessRequest` and the custom `IAsyncResult` with one
   `async Task`. Keep any queueing or throttling the old code did with a `SemaphoreSlim` or a rate limiter.
4. **Modules → middleware**: one middleware per module, registered in the order the modules ran
   (`BeginRequest` → before `next`, `EndRequest` → after `next`). `PreSendRequestHeaders` → `ctx.Response.OnStarting`.
5. **Request/response API differences**: `Request.InputStream` → `Request.Body` (enable buffering if read twice:
   `ctx.Request.EnableBuffering()`); synchronous reads are off by default in Kestrel: make them async, do not turn
   `AllowSynchronousIO` on except as a waived, temporary step. `Response.ContentType`, `Response.StatusCode` stay;
   `Response.End()` → `return` (the pipeline ends when the delegate returns); `Response.Flush()` → `await Response.Body.FlushAsync()`.
6. **Encoding**: Web Forms defaulted the response to UTF-8 with the `<globalization>` settings; set the charset
   explicitly when the old output relied on `responseEncoding`.
7. Delete the `.ashx` file and its web.config registration once the endpoint replays the goldens.

## Done when

No WEB-HANDLER-IFACE or `.ashx` residue; parity replay of every request type passes on the old path.
