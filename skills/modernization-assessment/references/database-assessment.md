# Database assessment (code side)

This skill costs and assesses the **code and SQL conversion** only. Where the database is hosted, how data moves and database testing are out of scope.

**Inputs:**
- Findings in category `database` (T-SQL in `.sql` files and SSDT projects; SSIS/SSRS/SSAS artefacts).
- Data-access findings (`DATA-*`).
- Connection strings (servers, databases, auth mode; never passwords).

## Contents

- [Scenarios](#scenarios)
- [Steps](#steps)
- [Other routes AWS offers](#other-routes-aws-offers)
- [What the inventory counts](#what-the-inventory-counts)
- [Writing the recommendation](#writing-the-recommendation)

## Scenarios

| Scenario | Meaning | Code work |
| --- | --- | --- |
| `dual` | The application runs on SQL Server **and** PostgreSQL | Provider-neutral data access, every procedure kept for both engines (or moved into the application), plus abstraction work per application |
| `postgresql` | PostgreSQL only; SQL Server is removed | Every table, view, procedure, function and trigger converted, plus the data-access code |
| `none` | SQL Server stays | No database code change |

`estimate_effort.py` costs the chosen scenario and shows the others beside it.

## Steps

1. **Inventory the databases.**
   - Collect SSDT projects (`.sqlproj`), `.sql` files and connection strings, and note cross-database references.
   - Ask for schema scripts if the repositories hold none.
2. **Read the feature matrix** (report section 6) and open the evidence for every `redesign` and `rework` finding.
3. **Check data access per application:** EF6/EDMX, ADO.NET, Dapper, stored-procedure calls, T-SQL in code strings. This decides how much application code changes.
4. **Name the conversion tooling** in the narrative (AWS DMS Schema Conversion or AWS SCT for the first pass, then manual review of complex routines; for apps already on .NET 6+, the AWS Transform SQL Server agent, see below). Neither AWS SCT nor DMS Schema Conversion converts the .NET code that calls SQL Server: AWS SCT's application code (C#) conversion covers Oracle sources only, and DMS Schema Conversion converts database objects, not application code. The data-access code is a separate effort, counted in this assessment.
5. **Time zone and collation:** check `TZ-SQL-LOCAL-TIME` findings; PostgreSQL collation and case-sensitivity differ from SQL Server defaults.
6. **Authentication:** Windows-auth connection strings (`DATA-INTEGRATED-SECURITY`) become username/password or IAM authentication, with credentials in Secrets Manager.

## Other routes AWS offers

Name them when they fit, as options for the client and its DB team; the skill still costs `dual`, `postgresql` or `none`.
- **AWS Transform SQL Server modernization:** SQL Server 2008 R2-2022 to Aurora PostgreSQL 15+ only (not RDS for PostgreSQL). It converts schema, T-SQL procedures to PL/pgSQL, triggers and identity, and the .NET data-access code (EF 6.3-6.5, EF Core 1.0-10.0, ADO.NET), with synthetic data, equivalence checks and a report of the share of schema converted. It needs apps on .NET 6, 7, 8 or 10 (port .NET Framework first), C# only, one account and Region per job; cross-database dependencies stay human work. It is PostgreSQL only: it does not fit the `dual` scenario.
- **Babelfish for Aurora PostgreSQL:** the app keeps T-SQL and the SQL Server driver and connects over TDS, with few code changes. Run **Babelfish Compass** (AWS's recommended check; AWS SCT also assesses it) to see which T-SQL is supported. AWS DMS does a full load only, no ongoing replication, into a Babelfish target. AWS's SCT example: Aurora PostgreSQL 98% of storage objects and 52% of code objects converted automatically or with minimal change, Babelfish 97% and 45%. Babelfish lowers the code change but keeps T-SQL as a long-term dependency. Limits: Aurora PostgreSQL only, not RDS for PostgreSQL; no RDS Proxy and no IAM database authentication (verify); SCRAM authentication and Database Activity Streams are not supported (verify); CHECKSUM values differ from SQL Server (verify); identifiers longer than 63 bytes are hashed (verify); numeric identity precision differs (19 against 38) (verify); OUTPUT clause restrictions and a 100-parameter cap apply (verify). Check each against the current Babelfish compatibility page before quoting it.
- **Cost context** (hosting is outside this assessment; quote only with the source): AWS's example, us-east-1, on-demand, r6i/r6g.2xlarge: SQL Server Enterprise on EC2 about $2,835 a month, RDS for SQL Server Enterprise about $3,750, Aurora PostgreSQL about $1,032. AWS claims savings of up to 80% (EC2 SQL Server Enterprise to RDS for PostgreSQL), up to 70% (to Aurora PostgreSQL) and up to 90% for variable loads on Aurora Serverless v2: these are vendor claims with no baseline ([sources.md](sources.md), S31).

## What the inventory counts

SQL is **parsed** with Microsoft's T-SQL parser (codebase-documenter `sql_parse.py`, ScriptDom; sqlglot when no .NET SDK is installed), never matched with regular expressions. `scan_repo.py` stores it in `assessment/scan/<repo>.json` → `db_inventory`.

- **Objects:** every TABLE, VIEW, PROCEDURE, FUNCTION, TRIGGER, TYPE, SEQUENCE, SYNONYM, INDEX, SECURITY POLICY and AGGREGATE, with its size (small, medium, large). Each object also carries its parameters, the tables it reads and writes (with the operation), the routines it calls, temp tables and dynamic SQL. `ALTER TABLE … ADD` is folded into its table.
- **Construct census:** about 150 constructs (cursors, TRY/CATCH, MERGE, OUTPUT, APPLY, PIVOT, FOR XML/JSON, temporal tables, CLR, Service Broker, linked servers, cross-database names, `@@` variables, T-SQL built-in functions, SQL Server data types …). Each is classified by `codebase-documenter/scripts/data/pg_conversion.json`:
  - **auto**: handled by conversion tooling or a rename.
  - **rewrite**: a PostgreSQL equivalent exists.
  - **redesign**: no equivalent. Each redesign construct becomes a `DB-PG-<construct>` finding unless a `DB-*` rule already covers it.
- **SQL embedded in C#:** string literals that parse as complete statements, with concatenations joined and run-time holes marked dynamic. They get the same reads, writes, calls and construct classification. Procedure and type names passed as literals (`CommandType.StoredProcedure`) are recorded as name sites.
- **Data-access APIs:** SqlClient, Dapper, EF6 contexts, EDMX function imports, stored-procedure call styles.
- **Syntax errors:** recorded as `DB-SQL-SYNTAX`. The rest of the file is still inventoried, batch by batch.

**Coupling.** `map_graphs.py` adds the database layer to the code graph (`sql_graph.py`) and writes `analysis.json` → `database`. It records:
- which projects read, write and execute each object;
- objects shared by several projects (report 4.8);
- tables written by more than one project (finding `DB-MULTI-WRITER`);
- objects with no caller.

Shared objects tie those applications' cut-over together.

**Hours.** They come from `estimation.json` (`postgres`), multiplied by `ai_assistance.db_factor`:
- objects by kind and size;
- plus every construct priced by its conversion level (`pg_conversion.json` hours);
- plus the data-access code (parsed embedded statements, those needing a rewrite, those built at run time, API usage).

Findings raised from the inventory are flagged `db.priced_by_inventory`, so they are not charged a second time. Findings flagged `db_only` are priced in the database estimate only, never in application packages. **Dual** adds provider abstraction per application.

## Writing the recommendation

- **Lead with the scenario and the evidence** ("{{f:DB-CLR}} CLR assembly in `Db/Assemblies/Crypto.sql:12` has no PostgreSQL equivalent and must be rewritten in application code").
- **State the trade-off.** Dual support doubles the long-term cost of every database change; recommend it only when a customer contract or a staged migration needs both engines. PostgreSQL-only is cheaper to maintain but is a larger one-time conversion.
- **If no database code was available,** say so and list what is needed.
