# Playbook: logging, tracing and metrics

**Rules:** API-EVENTLOG, SVC-HOSTED-LOG (residue); LNX-CFG-LOG-PATH, LNX-LOG-* (Linux readiness).
**Engines:** DevTx KB 12 moves logging to `ILogger`; AWS Transform keeps the existing library. Claude makes the output container-friendly and wires AWS.

## The target

- **Logs to stdout as structured JSON**, one event per line. ECS ships stdout to CloudWatch Logs (`awslogs` driver or FireLens); nothing writes log files inside the container.
- **`ILogger<T>`** in application code. log4net, NLog and Serilog can stay as the provider behind it (each has a console/JSON target); remove file appenders and rolling-file paths on a drive letter or under `~/App_Data/logs`.
- **Correlation:** a request id (or the `traceparent` trace id) on every log line; pass it to downstream calls.
- **Metrics and traces:** OpenTelemetry (`AddOpenTelemetry().WithMetrics(...).WithTracing(...)`) exported to CloudWatch / X-Ray through the ADOT collector sidecar; replaces `PerformanceCounter` and custom timing logs.

## Replacements

| Today | Becomes |
|---|---|
| `EventLog.WriteEntry` | `ILogger` at the right level |
| File appenders, trace listeners writing to disk (`TracePath` settings) | Console/JSON target; any file a person downloads today → S3 |
| `System.Diagnostics.Trace` / `Debug` | `ILogger` (Trace listeners are off by default) |
| Hosted log service (Loggly, Splunk HTTP) called from code | CloudWatch Logs, or a FireLens route to the same service; API keys from Secrets Manager ([aws-managed-services.md](aws-managed-services.md)) |
| Exceptions logged with `ex.Message` only | `logger.LogError(ex, "...")` (stack trace kept) |
| Request/response bodies written for debugging | Off by default, masked when on; never log secrets, tokens, card or personal data |

## Gotchas

- Log levels from `appsettings.json` (`Logging:LogLevel`), overridable by environment variable (`Logging__LogLevel__Default`).
- Multi-line stack traces break line-based shipping: the JSON formatter keeps them in one event.
- Sampling and retention cost money: set CloudWatch retention per log group with DevOps.

## Done when

No log file paths or EventLog in the ported code; the container's stdout shows structured events with a request id; errors carry stack traces; secrets do not appear (`linux_readiness.py` and `residue_scan.py` mask, but check a real log too).
