# 19 – Linux Containerization and Hosting Migration

## Overview
Migrating from Windows/IIS-hosted .NET Framework MVC or Web API applications to modern .NET (**.NET 8 or .NET 10**) Linux containers enables modern deployment strategies and platform independence.  
This guide covers Dockerfile creation, environment configuration, networking, and deployment to AWS, Azure, or on-premise Linux servers.

---

## Step 1: Prerequisites

- Target .NET SDK installed (.NET 8 or .NET 10, matching the toolkit target)
- Docker installed and running (`docker info`)
- App refactored to use `Program.cs` (no `Global.asax`)
- Static files under `wwwroot/`
- Configuration in `appsettings.json`

---

## Step 2: Create Dockerfile

Example for an ASP.NET Core MVC or Web API app:

```dockerfile
# Use the image tag matching the target runtime: 8.0 for .NET 8, 10.0 for .NET 10
# Stage 1 - Build
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY . .
RUN dotnet restore
RUN dotnet publish -c Release -o /app/publish

# Stage 2 - Runtime
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app
COPY --from=build /app/publish .
ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "MyApp.dll"]
```

---

## Step 3: Build and Run Locally

```bash
docker build -t myapp:latest .
docker run -p 8080:8080 myapp:latest
```

Visit: [http://localhost:8080](http://localhost:8080)

---

## Step 4: Environment Configuration

Use environment variables to override app settings in containerized environments.

Example:
```bash
docker run -e "ConnectionStrings__DefaultConnection=Server=db;Database=App;User Id=sa;Password=<password>;" myapp:latest
```

In `Program.cs`, configuration automatically loads environment variables that use `__` as key separators.

---

## Step 5: Multi-Container Setup (Docker Compose)

`docker-compose.yml` example for app + SQL Server:

```yaml
version: '3.8'
services:
  app:
    build: .
    ports:
      - "8080:8080"
    environment:
      - ASPNETCORE_ENVIRONMENT=Development
      - ConnectionStrings__DefaultConnection=Server=db;Database=AppDb;User Id=sa;Password=<password>;
    depends_on:
      - db

  db:
    image: mcr.microsoft.com/mssql/server:2022-latest
    environment:
      SA_PASSWORD: "Pass123"
      ACCEPT_EULA: "Y"
    ports:
      - "1433:1433"
```

Run:
```bash
docker-compose up --build
```

---

## Step 6: Logging and Monitoring

Logs go to container stdout/stderr by default — capture them with Docker or Kubernetes log systems.

Example (view logs):
```bash
docker logs myapp
```

For structured logging:
- Use Serilog with `WriteTo.Console()`
- Integrate with ELK or CloudWatch

---

## Step 7: HTTPS Support

Generate or import a certificate and mount it in the container.

Example Dockerfile addition:
```dockerfile
COPY mycert.pfx /https/
ENV ASPNETCORE_Kestrel__Certificates__Default__Password="<password>"
ENV ASPNETCORE_Kestrel__Certificates__Default__Path=/https/mycert.pfx
```

---

## Step 8: Health Checks

Add a basic endpoint:
```csharp
app.MapGet("/health", () => Results.Ok("Healthy"));
```
Configure Docker health check:
```dockerfile
HEALTHCHECK CMD curl --fail http://localhost:8080/health || exit 1
```

---

## Step 9: Deployment Options

| Platform | Method | Notes |
|-----------|--------|-------|
| AWS ECS / Fargate | Push to ECR, deploy with task definitions | Works well with modern .NET (8/10) base images |
| Azure App Service for Containers | Push to ACR or Docker Hub | Supports Linux containers natively |
| Kubernetes | Use Helm chart or Deployment YAML | Great for scalable microservices |
| On-prem Linux | Use systemd + Docker | Simplest for bare-metal |

---

## Step 10: CI/CD Example (GitHub Actions)

`.github/workflows/docker-build.yml`:
```yaml
name: Build and Push Docker Image

on:
  push:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Login to Docker Hub
      run: echo "${{ secrets.DOCKER_PASSWORD }}" | docker login -u "${{ secrets.DOCKER_USERNAME }}" --password-stdin
    - name: Build and Push
      run: |
        docker build -t myapp:latest .
        docker tag myapp:latest mydockerhub/myapp:latest
        docker push mydockerhub/myapp:latest
```

---

## Step 11: Troubleshooting

| Issue | Cause | Fix |
|-------|--------|-----|
| App doesn’t start | Wrong entrypoint or port | Ensure `ENTRYPOINT ["dotnet", "MyApp.dll"]` |
| 404 errors | Missing static files | Verify `app.UseStaticFiles()` in pipeline |
| DB connection failure | Wrong container hostname | Use `Server=db` in connection string |
| Permission errors | Volume mount mismatch | Set `USER` correctly or adjust file permissions |

---

## Step 12: Best Practices

- Use multi-stage builds (as shown)
- Keep images small by excluding SDK in final image
- Use environment variables for secrets (never hardcode)
- Add health checks and readiness probes
- Configure `DOTNET_ENVIRONMENT` properly
- Leverage cloud-native monitoring (CloudWatch, Azure Monitor, Prometheus)

---

## Step 13: Validation Checklist

✅ App builds and runs in Linux container  
✅ Static files served from `wwwroot`  
✅ HTTPS and environment variables configured  
✅ Health check endpoint responds 200  
✅ Container logs integrated with platform  
✅ Connected to database successfully  

---

## See Also
- [18-nhibernate-migration.md](./18-nhibernate-migration.md)
- [05-hosting-deployment-migration.md](./05-hosting-deployment-migration.md)
- [README.md](./README.md) – Migration file index
---

## 14. SmartStore.NET container notes

SmartStore after migration will have:
- a web project (ASP.NET Core) – the one you publish
- library projects with legacy code (some of which may still be partially commented)

When you containerize:

1. **Publish only the web host**:
   ```bash
   dotnet publish src/Presentation/SmartStore.Web/SmartStore.Web.csproj -c Release -o /app/publish
   ```

2. **Make sure EF Core design-time packages are not resolved at runtime** – they bloat the image.

3. **Run database migrations** inside the container entrypoint:
   ```bash
   dotnet SmartStore.Web.dll migrate --apply
   ```

4. **If you keep optional/disabled code** (like the packaging utilities), exclude them from the published output using `<ExcludeFromSingleFile>true</ExcludeFromSingleFile>` or conditional compilation.
