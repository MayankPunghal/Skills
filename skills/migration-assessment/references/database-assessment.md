# Database assessment (code side)

This skill costs and assesses the **code and SQL conversion** only. Where the database is hosted, how data moves and database testing are out of scope.

**Inputs:**
- Findings in category `database` (T-SQL in `.sql` files and SSDT projects; SSIS/SSRS/SSAS artefacts).
- Data-access findings (`DATA-*`).
- Connection strings (servers, databases, auth mode; never passwords).

## Contents

- [Scenarios](#scenarios)
- [Steps](#steps)
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
4. **Name the conversion tooling** in the narrative (AWS DMS Schema Conversion or AWS SCT for the first pass, then manual review of complex routines).
5. **Time zone and collation:** check `TZ-SQL-LOCAL-TIME` findings; PostgreSQL collation and case-sensitivity differ from SQL Server defaults.
6. **Authentication:** Windows-auth connection strings (`DATA-INTEGRATED-SECURITY`) become username/password or IAM authentication, with credentials in Secrets Manager.

## What the inventory counts

- Every CREATE TABLE / VIEW / PROCEDURE / FUNCTION / TRIGGER / TYPE, with its size (small, medium, large).
- T-SQL constructs that need rework: cursors, temp tables, table variables, dynamic SQL, TRY/CATCH, MERGE, OUTPUT, APPLY, PIVOT, XML, identity functions, hints.
- The data-access footprint: stored-procedure call sites, inline SQL, T-SQL in code strings, SqlClient usage, Dapper, EF contexts and EDMX function imports.

Hours come from `estimation.json` (`postgres`): objects by kind and size, plus constructs, plus code changes, multiplied by `ai_assistance.db_factor`. **Dual** adds provider abstraction per application.

## Writing the recommendation

- **Lead with the scenario and the evidence** ("F-031 CLR assembly in `Db/Assemblies/Crypto.sql:12` has no PostgreSQL equivalent and must be rewritten in application code").
- **State the trade-off.** Dual support doubles the long-term cost of every database change; recommend it only when a customer contract or a staged migration needs both engines. PostgreSQL-only is cheaper to maintain but is a larger one-time conversion.
- **If no database code was available,** say so and list what is needed.
