# Playbook: background work, Windows services and scheduled jobs

**Rules:** WIN-SERVICE, Topshelf, `QueueBackgroundWorkItem`, timers in web apps (assessment); LNX-PROC-NO-HOST-LIFETIME, LNX-HOST-USEWINDOWSSERVICE-ONLY, LNX-SCH-* (Linux readiness).
**Engines:** neither engine changes the hosting model of background work. Claude does, with the user deciding where each job runs.

## Inventory

For every piece of background work: what starts it (Windows service, Task Scheduler entry, timer in the web app, `QueueBackgroundWorkItem`, SQL Agent job), how often, how long it runs, whether two copies may run at once, what it touches. Task Scheduler and SQL Agent entries are not in the code: ask the client (the assessment lists them as open questions).

## Where it goes

| Today | On AWS |
|---|---|
| Windows service (`ServiceBase`, Topshelf) running continuously | A worker: `Host.CreateApplicationBuilder` + `BackgroundService`, its own ECS service, `UseSystemd()` only if it ever runs on a VM |
| Task Scheduler / cron-like job | EventBridge Scheduler → ECS `RunTask` of a console app that does one run and exits |
| Timer inside the web app | Out of the web app when it must run once across tasks (scheduled task above); a `BackgroundService` in the web app only for per-instance work |
| `HostingEnvironment.QueueBackgroundWorkItem`, fire-and-forget `Task.Run` | `BackgroundService` reading a `Channel<T>`; durable work → SQS + a worker |
| `IRegisteredObject` registered with `HostingEnvironment.RegisterObject` | `IHostedService` or `BackgroundService`. Do the shutdown work in `StopAsync`. The other System.Web hosting types are in [systemweb-residue.md](systemweb-residue.md) |
| MSMQ consumer | SQS consumer worker ([aws-managed-services.md](aws-managed-services.md)) |
| Quartz.NET / Hangfire | Keep, with a shared job store (database) and clustering on, or move simple schedules to EventBridge |
| SQL Agent job calling procedures | The DB team's choice: `pg_cron`, or EventBridge + a small task |

## Run correctly in a container

- **Stop on SIGTERM.** ECS sends SIGTERM, then SIGKILL after the stop timeout (30 s default). Use the generic host and honour the `CancellationToken` in `ExecuteAsync`; finish or checkpoint the current item. A `Main` that loops forever or waits on `Console.ReadLine()` never stops cleanly.
- **One run at a time** where the job is not idempotent: a distributed lock (DynamoDB conditional write, Redis `SET NX` with expiry) or a single-task service.
- **No local state between runs**: files to S3, progress to the database.
- Exceptions in `ExecuteAsync` stop the host on .NET 8+ (`BackgroundServiceExceptionBehavior.StopHost`): catch per item, log, carry on; let ECS restart on a real crash.

## Stopping work

`Thread.Abort` throws `PlatformNotSupportedException` on .NET 5 and later, and the compiler reports it as obsolete (SYSLIB0006). Remove every call and stop work with a `CancellationToken` instead:

- Pass the token into the loop and check it between items (`ThrowIfCancellationRequested()`).
- Pass the token into awaited calls. Most I/O overloads take one. For a call that does not, wrap it with `Task.WaitAsync(token)` and accept that the inner work keeps running.
- Blocking code with no way to cancel: run it in a child process and stop that process. This is the last resort.

AppDomains and Code Access Security have their own section in [ambient-context-and-remoting.md](ambient-context-and-remoting.md).

## Done when

Every job has a recorded home and schedule; each worker stops within the stop timeout when sent SIGTERM; a forced double start does not run a non-idempotent job twice.
