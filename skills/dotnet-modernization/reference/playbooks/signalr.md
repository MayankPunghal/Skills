# Playbook: ASP.NET SignalR to ASP.NET Core SignalR

**Rules:** WEB-SIGNALR-LEGACY (assessment); `Microsoft.AspNet.SignalR` packages and `jquery.signalR` scripts.
**Engines:** Neither the DevTx KB nor the AWS Transform docs cover SignalR, so plan this as Claude's work. The server and every client change in the same release, because ASP.NET Core SignalR is not compatible with ASP.NET SignalR clients or servers.

## Contents
- Steps
- Scale-out on AWS
- Gotchas
- Done when

## Steps

1. **Inventory.** List the hubs and their methods, the client methods the server calls, and the groups. List every client: browser pages, .NET clients, other servers. Note any scale-out (SQL Server or Redis backplane) and any `PersistentConnection`. Send any client you can't change to the user as a decision.
2. **Server.**
   - The `Microsoft.AspNet.SignalR` packages go. ASP.NET Core SignalR is part of the shared framework: `builder.Services.AddSignalR()` and `app.MapHub<ChatHub>("/chathub")`.
   - A hub class keeps its shape, but dynamic client calls change. `Clients.All.addMessage(...)` becomes `Clients.All.SendAsync("addMessage", ...)`, or a strongly typed `Hub<IChatClient>`.
   - `GlobalHost` does not exist. `GlobalHost.ConnectionManager.GetHubContext<T>()` becomes an injected `IHubContext<T>`.
   - A connection uses one hub.
   - `PersistentConnection` is removed: use a hub or raw WebSockets.
   - `HubPipeline` modules become hub filters (`IHubFilter`).
   - HubState and progress messages are removed. Server-to-client streaming (`IAsyncEnumerable<T>` or `ChannelReader<T>`) replaces progress reporting.
3. **JavaScript clients.**
   - jQuery, `jquery.signalR`, the generated `/signalr/hubs` proxies and `$.connection` go.
   - The new client is the npm package `@microsoft/signalr`: `new signalR.HubConnectionBuilder().withUrl("/chathub").withAutomaticReconnect().build()`. Client methods are registered with `connection.on("addMessage", ...)`. The server is called with `connection.invoke("Send", ...)`, the method name passed as a string.
   - Internet Explorer is not supported.
4. **.NET clients.** `Microsoft.AspNet.SignalR.Client` becomes `Microsoft.AspNetCore.SignalR.Client`, with the same builder pattern.
5. **Reconnect and groups.**
   - ASP.NET SignalR reconnected by default. In ASP.NET Core it is opt-in, with `withAutomaticReconnect()` (JS) or `WithAutomaticReconnect()` (.NET).
   - A reconnected client gets a new connection ID, so re-add it to its groups in the `onreconnected` handler or on the server.
6. **Authentication.** Cookie authentication flows with the connection. For bearer tokens, use the client's `accessTokenFactory`. Browsers send the token in the query string for WebSockets and Server-Sent Events, so read `access_token` in the JWT `OnMessageReceived` event, and keep it out of the access logs.
7. **Transports and protocol.**
   - The transports are WebSockets, Server-Sent Events and Long Polling. Forever Frame is gone.
   - Messages are JSON (System.Text.Json, camelCase) or MessagePack. To keep the old property-name casing, either update the client code or use `AddNewtonsoftJsonProtocol()`.

## Scale-out on AWS

- Running more than one ECS task needs a backplane. Use the Redis backplane (`AddStackExchangeRedis(...)`) on ElastiCache (Valkey or Redis OSS) ([aws-managed-services.md](aws-managed-services.md)). Azure SignalR Service is not an AWS option.
- The Redis backplane needs sticky sessions, so turn on stickiness on the ALB target group.
- The ALB supports WebSockets. Keep its idle timeout (60 seconds by default) above the SignalR keep-alive interval, and keep the server and client timeouts consistent.

## Gotchas

- The default maximum incoming message size is 32 KB (`MaximumReceiveMessageSize`). Large messages that worked before fail, so set it from the measured size.
- A hub method name that differs only by case from a client method causes confusion, because the client matches names case-insensitively. Keep one spelling.
- Clients pinned to a cached copy of the old script break on deploy. Version the script URL.

## Done when

- No `Microsoft.AspNet.SignalR` or `jquery.signalR` reference is left.
- Every client is moved in the same release.
- A test with two tasks behind the ALB shows a message sent on one task reaching a client on the other.
- Reconnect and group re-join are tested.

Sources: [Differences between ASP.NET SignalR and ASP.NET Core SignalR](https://learn.microsoft.com/en-us/aspnet/core/signalr/version-differences), [SignalR scale-out](https://learn.microsoft.com/en-us/aspnet/core/signalr/scale).
