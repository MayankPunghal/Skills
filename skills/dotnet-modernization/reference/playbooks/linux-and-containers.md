# Playbook: Linux file system, processes and the container image

**Rules:** FILE-DRIVE, FILE-BACKSLASH-JOIN, HOST-MACHINE-NAME (residue); LNX-FS-*, LNX-PROC-*, LNX-ENV-*, LNX-CTR-*, LNX-CI-* (Linux readiness, [linux-readiness.md](../linux-readiness.md)).
**Engines:** DevTx KB 19 writes a Dockerfile (fix its samples, below); the AWS Transform .NET agent writes none and lists Linux items in `NextSteps.md` and its Linux readiness report. AWS Transform's separate containerization feature can generate images and ECS (Terraform) or EKS (Helm) deployment code ([engines.md](../engines.md#other-aws-transform-agents)); treat its Dockerfile like any other: run the Linux readiness scan and the container gate on it. Claude does the rest and owns the Dockerfile.

## File system

- **Letter case matters.** `~/Content/Site.css` and `site.css` are different files. Fix every reference `linux_readiness.py` reports against the files on disk (views, scripts, styles, images, embedded resources, `appsettings.{Environment}.json`). Rename files with `git mv` so the case change is recorded.
- **Separators:** `Path.Combine` / `Path.Join`, never `"\\"` concatenation; `/` works on both in literals.
- **No drive letters, UNC paths or Windows folders** (drive-letter paths, UNC shares, `%APPDATA%`): paths from configuration; temporary files under `Path.GetTempPath()`; shared files on EFS or S3 ([aws-managed-services.md](aws-managed-services.md)).
- **The app folder is read-only** in a hardened container: nothing writes next to the binaries (`AppDomain.CurrentDomain.BaseDirectory`, `~/App_Data`). Writable paths are mounted volumes, set by configuration.
- Executable bit and line endings on scripts: `.gitattributes` with `*.sh text eol=lf`; `chmod +x` in the Dockerfile or `git update-index --chmod=+x`.

## Processes and environment

- No `cmd.exe`, `powershell.exe` or `.exe` launches: a library call, or the Linux tool installed in the image; `UseShellExecute=false` with an argument list.
- `Environment.MachineName` is the container id: do not use it as a node identity or in keys; use the ECS task id from the metadata endpoint if one is needed.
- Configuration keys in environment variables use `__` (`ConnectionStrings__Main`), never `:`.
- Environment variable names are case-sensitive on Linux.

## The image

```dockerfile
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish src/App/App.csproj -c Release -o /app --no-self-contained

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /app .
USER $APP_UID
ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "App.dll"]
```

- **Non-root:** `USER $APP_UID` (UID 1654 in the .NET 8+ images).
- **Final stage is the runtime image**, never the SDK. A `.dockerignore` keeps `bin/`, `obj/`, `.git`, secrets and local settings out of the build context.
- **Port 8080** (the .NET 8+ default); the ALB target group and health check use it.
- **Exec-form `ENTRYPOINT`** so `dotnet` is PID 1 and receives SIGTERM.
- **Health check:** the ALB / ECS health check calls `/health`. The runtime images have no `curl`: do not copy a `HEALTHCHECK CMD curl` line (DevTx KB 19 has one); if a container-level check is needed, use a tiny `--health` mode in the app or add a tool on purpose.
- **Native dependencies:** ICU and tzdata (in the full image; not in Alpine/chiseled without `-extra`), fonts for PDF/image rendering (`fonts-dejavu` or licensed corporate fonts), `libgdiplus` only if legacy System.Drawing is kept on purpose, `libldap` for LDAP, Kerberos libraries for Negotiate.
- **No secrets in the image or its history:** no passwords in `ENV`, no PFX copied in (DevTx KB 19's HTTPS sample does both); TLS ends at the ALB; secrets come from Secrets Manager as ECS task secrets.
- **Architecture:** build for the platform ECS runs (`docker buildx build --platform linux/amd64` or `linux/arm64` for Graviton) and check native packages exist for it.
- **Registry:** ECR, not Docker Hub; scan on push.
- **Database migrations** do not run in the entrypoint (several tasks race): a one-off ECS task in the deployment.

## Networking and state

- **ALB affinity** (cookie-based stickiness on the target group) keeps one user on one task. Use it only as a stopgap for state still held in memory, such as Blazor circuits, SignalR connections or in-process session. Affinity hides restarts and uneven load, so move the state out ([startup-and-middleware.md](startup-and-middleware.md)).
- **Static egress IPs.** Tasks in private subnets reach the internet through a NAT gateway, which has Elastic IP addresses. A partner that allow-lists IPs needs those addresses. A new NAT gateway means a new address, so agree the change with the partner first.

## Done when

`linux_readiness.py --gate` passes (blocking hits fixed or waived); `verify.py target --dockerfile Dockerfile` builds the image, starts it as non-root on 8080 and gets 200 from `/health`; the image has no secrets (`docker history` clean).
