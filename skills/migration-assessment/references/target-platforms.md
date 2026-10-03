# AWS target mapping

Use this page when writing fixes, alternatives and application targets. Service availability changes: check [sources.md](sources.md).

| On-prem / Windows concern | AWS / .NET 10 target | Notes |
| --- | --- | --- |
| IIS web app / API | ASP.NET Core on Kestrel in Linux containers: **ECS on Fargate** behind an **ALB**; EKS for Kubernetes shops; **ECS Express Mode** for simple services | App Runner is closed to new customers (30 Apr 2026). Elastic Beanstalk (.NET on Linux platform) for simple single apps |
| Windows-retained app | **EC2 Windows** (IIS) via AWS Application Migration Service, or **ECS Windows containers** | Windows licence-included on EC2; consider Dedicated Hosts only for BYOL |
| Windows service / timers | .NET Worker Service: ECS service; **EventBridge Scheduler** → ECS task / Lambda for timed jobs | Use a distributed lock if several instances run |
| Task Scheduler / SQL Agent jobs | EventBridge Scheduler; RDS keeps SQL Agent; Babelfish/PostgreSQL need external scheduling | |
| MSMQ / Service Broker | **Amazon SQS** (+ SNS fan-out), Amazon MQ for broker semantics | MassTransit / NServiceBus have SQS transports |
| Session state, Application cache | **Amazon ElastiCache** (Valkey/Redis) via IDistributedCache / distributed session; DynamoDB for session alternative | Removes sticky sessions |
| File shares (UNC), local writes | **Amazon S3** (objects), **Amazon EFS** (POSIX shared FS for Linux), **FSx for Windows File Server** / **FSx for NetApp ONTAP** (SMB) | Choose by access pattern |
| web.config appSettings | appsettings.json + environment; **Systems Manager Parameter Store** | Amazon.Extensions.Configuration.SystemsManager |
| Secrets, connection-string passwords, machineKey | **AWS Secrets Manager** (rotation for RDS), **KMS** | Data Protection key ring in S3 + KMS |
| Certificates | **ACM** at the ALB / CloudFront; private keys in Secrets Manager when the app needs them | |
| Windows auth / AD | **AWS Managed Microsoft AD** (Kerberos, RDS Windows auth) or AD over VPN; better: OIDC (IAM Identity Center, Cognito, Entra ID federation) | Negotiate on Linux needs keytab + LDAP |
| Event Log, log files | stdout JSON → **CloudWatch Logs** (awslogs / FireLens); AWS.Logger providers | |
| Perf counters, health | **CloudWatch** metrics, **X-Ray** / ADOT (OpenTelemetry); ASP.NET Core health checks for ALB/ECS | |
| SMTP relay | **Amazon SES** (SMTP or API) | Verify domains; port 25 throttled on EC2 |
| FTP/SFTP partners | **AWS Transfer Family**; fixed egress IPs via NAT gateway EIPs | Partners must update allow-lists |
| On-prem systems that stay | **Site-to-Site VPN** / **Direct Connect**; **Route 53 Resolver** endpoints for on-prem DNS names | Internal host names in code depend on this |
| SQL Server | **RDS for SQL Server** / **Aurora PostgreSQL + Babelfish** / **SQL Server on EC2** | See [database-assessment.md](database-assessment.md) |
| SSRS / SSIS / SSAS | RDS SSRS option (2016-2022), PBIRS (2025); SSIS on RDS 2016-2022 or AWS Glue / Step Functions; SSAS on EC2 | |
| Crystal / Office / fax / printing | Reporting library or SSRS/PBIRS; Open XML libraries; cloud fax API; PDF + on-prem print agent | Repurchase may fit |
| CI/CD | **CodePipeline / CodeBuild** (Linux images), **GitHub Actions** Linux runners; **CodeArtifact** for private NuGet | |
| Container images | `mcr.microsoft.com/dotnet/aspnet:10.0` (Ubuntu/Debian/Alpine/Chiseled) → **ECR** | Include ICU + tzdata unless invariant mode is safe |
