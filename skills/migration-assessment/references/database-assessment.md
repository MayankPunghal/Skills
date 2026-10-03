# Database assessment

**Inputs:**
- Findings in category `database` (T-SQL in `.sql` files and SSDT projects; SSIS/SSRS/SSAS artefacts).
- Data-access findings (`DATA-*`).
- Connection strings (servers, databases, auth mode; never passwords).

`estimate_effort.py` computes an option matrix per repository: RDS for SQL Server / Babelfish / SQL Server on EC2, with blocking and limited features and effort. You write the recommendation in `assessment/narrative/database.md`.

## Options

| Target | Licensing | Fits when | Blocked / limited by (code evidence) |
| --- | --- | --- | --- |
| **Amazon RDS for SQL Server** | License-included (or BYOL-free only on EC2) | T-SQL heavy apps; least change | CLR on 2017+ (`DB-CLR`); FILESTREAM/FileTable; xp_cmdshell/OLE automation; replication; server triggers/endpoints/TRUSTWORTHY/sp_configure (`DB-SERVER-CONFIG`); SSIS on SQL 2025; SSAS on 2022+; linked servers limited; msdb import; max 30–100 databases per instance (S11, S12) |
| **Aurora PostgreSQL + Babelfish** | Removes the SQL Server licence | Moderate T-SQL; apps using the TDS protocol unchanged | CLR, Service Broker, full-text, MERGE, hierarchyid, temporal tables, BULK INSERT, global temp tables, EXECUTE AS, cross-db DDL, SQL Agent, Database Mail, XML methods … (`DB-BABELFISH-SYNTAX` and the `db.babelfish` column) (S13, S14) |
| **PostgreSQL (native, re-written data layer)** | Removes the SQL Server licence | Apps already on EF Core; low stored-procedure count; long-term cost focus | All T-SQL must be converted (AWS SCT / DMS Schema Conversion); stored procedures re-written; EF provider change |
| **SQL Server on EC2** | License-included or BYOL (licence mobility) | Features unsupported on RDS; need sysadmin/OS access | None technically; you keep operating the server |

## Steps

1. **Inventory the databases.**
   - Collect SSDT projects (`.sqlproj`), `.sql` files and connection strings, and note cross-database references (they decide co-location).
   - Ask for schema scripts if the repositories hold none.
2. **Read the feature matrix** (report section 6) and open the evidence for every blocker.
3. **Babelfish:** never recommend it without **Babelfish Compass**.
   - Run Compass on a full schema export (DDL from SSMS "Generate Scripts", or SSDT build output).
   - Compass needs Java 8+. Put its report path in the narrative.
4. **Migration method** (stated in the narrative):
   - **RDS:** native backup/restore via S3 for one-time moves, AWS DMS for minimal downtime.
   - **Babelfish:** Compass, then schema via `babelfishpg` scripts, then data via DMS.
   - **PostgreSQL:** DMS Schema Conversion / SCT, then DMS.
5. **Time zone:** RDS sets the instance time zone only at creation. Check `TZ-SQL-LOCAL-TIME` findings.
6. **Authentication:** Windows-auth logins need AWS Managed Microsoft AD (`DATA-INTEGRATED-SECURITY`). Otherwise use SQL logins with credentials in Secrets Manager and rotation.
7. **HA and sizing:** Multi-AZ (Always On AGs), instance class versus edition core limits, and storage (16 TiB gp, 64 TiB io). Volumes and growth are client questions.

## Writing the recommendation

- **Lead with the target per database and the evidence** ("F-031 CLR assemblies in `Db/Assemblies/Crypto.sql:12` rule out RDS 2017+ …").
- **State the licensing effect and the next validation step** (Compass run, DMS proof of concept).
- **If no database code was available,** say so and list what is needed.

## Full PostgreSQL port and dual-database support

Use these when the client wants to drop SQL Server entirely, or to run on both engines.

- **Inventory** (`scan_repo.py`, `db_inventory`):
  - every CREATE TABLE / VIEW / PROCEDURE / FUNCTION / TRIGGER / TYPE, with its size;
  - T-SQL constructs that need rework: cursors, temp tables, table variables, dynamic SQL, TRY/CATCH, MERGE, OUTPUT, APPLY, PIVOT, XML, identity functions, hints;
  - the data-access footprint: stored-procedure call sites, inline SQL, T-SQL in code strings, SqlClient usage, Dapper, EF contexts and EDMX function imports.
- **Estimate** (`estimation.json`, `postgres`):
  - objects by kind and size, plus constructs, plus code changes, multiplied by `ai_assistance.db_factor` (AWS DMS Schema Conversion with generative AI / SCT plus agents);
  - plus tooling and data migration per database;
  - plus testing (30-45 % of conversion; dual 50-80 %).
  - **Dual** adds provider abstraction per application and a CI matrix that tests every build on both engines.
- **Report:** section 6.1 and the Data tab, with the PostgreSQL and dual options in the scenario comparison.
- **Advice to state:**
  - Dual support doubles the long-term cost of every database change. Recommend it only when a customer contract demands both engines.
  - For a large T-SQL estate, move to AWS on RDS for SQL Server first, then port to PostgreSQL as a separate phase.
