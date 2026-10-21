# Server-hosted services to AWS managed services

## Contents
- [What it answers](#what-it-answers)
- [What is found](#what-is-found)
- [Where the wrapper lives](#where-the-wrapper-lives)
- [Target options and hours](#target-options-and-hours)
- [How it reaches the estimate and the report](#how-it-reaches-the-estimate-and-the-report)
- [Running it on its own](#running-it-on-its-own)
- [Limits](#limits)

## What it answers
When the client wants servers they run today replaced by AWS managed services (intake `aws_native`), the question is how much **code** changes per service: Redis, Memcached and Aerospike caches, Elasticsearch, SMTP mail, SFTP / FTP, SMB file shares, MongoDB, RabbitMQ, Kafka, MSMQ, hosted log services (Loggly, Splunk, Sumo Logic, Papertrail) and out-of-process session state. Creating the AWS resources, networking, DNS, verified mail domains and data migration are DevOps work and are not in these hours.

Script: `scripts/aws_native.py`. Catalogue: `scripts/data/aws_native.json` (detection patterns, AWS target options, rates). Add a service or an option there, not in code.

## What is found
Per service and repository:
- **Packages**: NuGet ids and binary references that are its client (`packages.config`, `PackageReference`, `<Reference>`).
- **Wrapper (provider) files**: code that calls the client library directly. A file that only imports the client namespace (for a result type) is a caller, not the wrapper.
- **Call sites**: code lines outside the wrapper that use it: the wrapper's service-named types, the methods that hold the client calls (generic names such as `GetInstance` are ignored), and identifiers that name the service (`useAerospikeCache`, `LogErrorToLoggly`). Strings and comments are blanked first.
- **Configuration entries**: matched on key, element and attribute **names** (assembly binding lines skipped); every line of an external config file named after the service (`memcached.config`, `aerospike.config`). Values are never kept.
- **Legacy API**: patterns that need a rewrite whatever the target (MongoDB driver 1.x: `MongoServer`, `MongoCollection<T>.Insert`).
- **Hosts** (optional, `--facts`): network entries whose role is the service.

## Where the wrapper lives
- **In this repository**: the wrapper's work (fixed + per wrapper file) is counted here.
- **In a shared library** whose source is passed with `--library-source` (another repository of the estate): counted once with that library, reported beside the repository's own figure. In an estate run every repository is scanned, so the library's own repository carries its wrapper work and callers carry only their call sites.
- **Not found** (binary-only library or a configured appender): only call sites and settings are counted, plus a small fixed check against the new endpoint (`consumer_repo_fixed`).

## Target options and hours
Each service lists AWS target options; the first is the default. `change` says what kind of work it is: `config` (endpoint, TLS, credentials), `client-swap` (another client library behind the same wrapper), `rewrite` (wrapper rewritten for another service model), `remove` (the dependency goes). Examples: Redis to ElastiCache (config); Memcached to ElastiCache for Memcached (client swap: EnyimMemcached 2.x is .NET Framework only) or folded into Valkey (rewrite); Aerospike to ElastiCache Valkey or DynamoDB (rewrite; AWS has no managed Aerospike) or kept self-managed; SMTP to SES SMTP interface (config) or SES API (rewrite); SFTP to AWS Transfer Family (config) or S3 (rewrite); MongoDB to DocumentDB (client swap; legacy driver costs more) or removed.

Hours per option, manual-equivalent: `fixed` (wrapper here) or `consumer_repo_fixed` (callers only) + wrapper files x `per_provider_file` (or `legacy_per_provider_file`) + call sites x `per_consumer_site` + config entries x `per_config_key`. The option's `factor` (`code` or `redesign`) picks the AI factor from `estimation.json`, as for every other coding item. Choose a non-default option per service with `aws_native_choices` in `assessment.json` (for example `{"aerospike": "dynamodb"}`).

## How it reaches the estimate and the report
`estimate_effort.py` runs the scan for every repository and adds one optional-modernization row per service found (`AWS-<SERVICE>`). A row replaces the generic flat item for the same service (`supersedes_optional`: SMTP replaces `OPT-EMAIL-SES`, Kafka `OPT-KAFKA-SQS`, RabbitMQ / MSMQ `OPT-MQ-SQS`, Elasticsearch `OPT-SEARCH-OPENSEARCH`). With intake `aws_native = now` the rows are added to the estimate total; with `later` they are listed in report section 7.3 only.

## Running it on its own
```bash
python scripts/aws_native.py --root <repo> [--library-source <shared library source> ...] [--facts <facts.json>] \
       [--choices '{"aerospike": "dynamodb"}'] [--factors '{"code": [0.3, 0.5], "redesign": [0.7, 1.0]}'] --out <dir>
```
Writes `aws-native.json` (every option with its hours) and `aws-native.md` (a table per service and the options compared). Read-only: nothing under `--root` or `--library-source` changes.

## Limits
- Detection is pattern-based. A wrapper that talks to a service over plain HTTP (a hosted log API, for example) shows up through its call sites and settings, not as a wrapper file.
- Identifiers that merely name a service (an enum member `Redis`) count as call sites; the review queue is the place to dismiss them.
- Services configured only outside git (IIS settings, environment variables) are not seen.
