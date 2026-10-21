# Playbook: server-hosted services to AWS managed services

**Rules:** NET-SMTP, LS-SMTP-PORT25, INT-SMTP-PICKUP-IIS, NET-FTP, WIN-MSMQ, FILE-LOCAL-WRITE, NET-UNC-SHARE,
LS-NETWORK-MOUNT, IIS-SESSION-STATE, STATE-SESSION, STATE-APP-CACHE (assessment); SVC-* , API-MSMQ, FILE-UNC (residue);
the `AWS-*` rows of the assessment's aws-native.md (the modernization-assessment skill's `aws_native.py`).
**Engines:** neither engine covers these. Claude does them, one service per commit.

## Order per service

1. Read the aws-native row: the wrapper (in this repository, in a shared library, or not found), the call sites, the
   config entries and the chosen target. A wrapper in a shared library is changed once, with that library.
2. Change the wrapper, not the callers. Callers change only when the API shape must (synchronous → async).
3. Configuration: endpoint and credentials from configuration / Secrets Manager; IAM role of the task, never access keys.
4. Test against the AWS service in a test account (gate "aws-native").

## Per service

| From | To | Change | Notes |
|---|---|---|---|
| Redis (StackExchange.Redis) | ElastiCache (Valkey / Redis OSS) | config | TLS on (`ssl=true`), cluster mode changes key-slot rules for multi-key commands, AUTH token from Secrets Manager |
| Memcached (Enyim) | ElastiCache for Memcached, or fold into Valkey | client-swap | Enyim is .NET Framework-only: EnyimMemcachedCore, or move the keys to the Redis client if folded |
| Aerospike | ElastiCache Valkey or DynamoDB; or self-managed on EC2 | rewrite / keep | data model decides; the client works on .NET 10 if kept |
| Elasticsearch (NEST / Elasticsearch.Net) | Amazon OpenSearch Service | client-swap | OpenSearch.Client; mapping types and version differences; SigV4 or fine-grained access |
| SMTP server / IIS pickup folder | Amazon SES (SMTP interface or SES API) | config / client-swap | port 587 with STARTTLS, SES SMTP credentials; verified sender identities; pickup directory → real SMTP send |
| FTP / SFTP to a server | AWS Transfer Family or S3 | config / rewrite | FluentFTP / SSH.NET work on Linux; S3 when the "server" was only file exchange |
| UNC share / local folder written at run time | S3 (or EFS when a file system is required) | rewrite | `File.*` → `IAmazonS3` via an `IFileStore` abstraction; no writes under the app folder in a container |
| MongoDB | Amazon DocumentDB (or keep MongoDB Atlas / remove) | config | the legacy 1.x API (`MongoServer`, `MongoCollection<T>`, `SafeMode`) was carried by the `mongocsharpdriver` package in 2.x and **removed in driver 3.0**: move through 2.30 to `IMongoClient` / `IMongoCollection<T>` (`InsertOne`), checking the GUID representation (legacy-format GUIDs read back wrong) and write concern (legacy code often wrote unacknowledged). DocumentDB itself is mostly configuration: TLS with the global CA bundle as a file path, `retryWrites=false` below engine 8.0.2. A feature that is switched off is a removal |
| RabbitMQ / MSMQ / Kafka | Amazon MQ / SQS / MSK | client-swap / rewrite | MSMQ (System.Messaging) does not exist on .NET 10: SQS |
| Hosted log service (Loggly, Splunk, ...) | CloudWatch Logs | client-swap | log to stdout (JSON), the awslogs driver or FireLens ships it |
| Session state server / SQL session | ElastiCache (distributed cache) session | config | `AddStackExchangeRedisCache` + `AddSession`; session objects must serialise (no BinaryFormatter) |
| In-process cache shared across servers | ElastiCache, or keep in-process if per-task is acceptable | decision | with several tasks behind a load balancer, in-process caches diverge |

## Done when

Each swapped service answers from its AWS endpoint in the test environment; no SVC-* residue except kept services with
a waiver naming the decision.
