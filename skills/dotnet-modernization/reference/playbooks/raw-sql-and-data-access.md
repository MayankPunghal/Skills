# Playbook: raw SQL and data access (SQL Server → PostgreSQL)

**Rules:** DB-SQLCLIENT, DB-SYSTEM-SQLCLIENT, DB-SQLERROR-NUMBER, DB-XMLREADER, SQL-TSQL-IN-STRING, SQL-CROSS-DB, SQL-CONCAT-VALUE (residue); DATA-* and DB-* (assessment).
**Engines:** DevTx and the AWS Transform .NET agent do not convert SQL. The database tool does: the DB porting agent, or Claude with the DB porting skills ([engines.md](../engines.md#db-porting-agent)). AWS Transform also has a separate SQL Server modernization agent (SQL Server 2008 R2-2022 to Aurora PostgreSQL 15+ only; .NET 6, 7, 8 or 10 applications, not .NET Framework, so port first; EF 6.3-6.5, EF Core and ADO.NET; no VB.NET; one account and Region per job; cross-database dependencies left to people). It replaces the database instead of adding a PostgreSQL path beside SQL Server, so it is a PostgreSQL-only route, and it counts as the one database tool for that repository. DevTx KB 07, 16, 17, 18 cover ADO.NET, EF6 → EF Core, Dapper and NHibernate on SQL Server only.

## Contents

- [Ground rules](#ground-rules)
- [Steps](#steps)
- [Calls and results](#calls-and-results)
- [Statements inside the code](#statements-inside-the-code)
- [Transactions, errors and connections](#transactions-errors-and-connections)
- [Types, dates and names](#types-dates-and-names)
- [Conversions that change values](#conversions-that-change-values)
- [Per technology: EF6, EF Core, Dapper, NHibernate](#per-technology-ef6-ef-core-dapper-nhibernate)
- [Flag, do not convert](#flag-do-not-convert)
- [Checklist groups](#checklist-groups)
- [Done when](#done-when)

## Ground rules

- **SQL Server behaviour stays the same.** In dual mode the SQL Server path is untouched; the PostgreSQL path sits beside it behind one provider switch (`Data:Provider`) read once at startup.
- **Seams only.** Engine-specific code lives in the seams: a connection factory, a dialect (`ISqlDialect`), a query provider (`ISqlQueryProvider`, one embedded `.sql` resource per engine per statement), a bulk-insert seam, an error classifier. No `if (provider == ...)` in repositories or services, no `new SqlConnection` outside the factory.
- **The DB team owns database objects.** The code never authors procedures, functions or tables; it follows the **database contract**: for every object its PostgreSQL name, kind (procedure, table function, scalar function, refcursor function), call form and argument order. A call that is not in the contract is a question for the DB team, not a guess.
- **No logic changes, no renames** beyond what the contract mandates. Every lossy change (a type, an ordering, a precision) is flagged in the report.
- Parameterised SQL only; `SQL-CONCAT-VALUE` (values concatenated into SQL) is fixed on both paths.

## Steps

1. **Inventory.** From the assessment: `sql-inventory.json` (`raw_sql.py`) lists every raw statement, procedure call, result-set procedure, multi-result read, OUTPUT parameter, TVP, FOR XML, cross-database name and error-number check, with file and line. No assessment? `residue_scan.py --db-target dual` and grep the patterns below.
2. **Contract.** Agree `db-contract.json` with the DB team (the DB porting agent's Plan phase builds it from the call sites: a call read with `ExecuteReader` and one result set → table function; several → refcursor function; `ExecuteNonQuery` → procedure; `ExecuteScalar` → scalar function).
3. **Approval.** Show the plan and the contract; wait for a yes.
4. **Seams.** Add the factory, dialect, query provider and switch; move each raw statement into its pair of `.sql` resources.
5. **Convert call sites** in dependency order, rebuilding every few files.
6. **Validate**: build, the checks under each section below, the checklist; then QA runs both engines.

## Calls and results

| Construct | What to find | PostgreSQL path |
|---|---|---|
| Procedure call | `CommandType.StoredProcedure`; `EXEC proc @p = ...` in strings; `SqlDataSource SelectCommandType="StoredProcedure"` in markup | Per contract: `CALL proc(...)` for a procedure; `SELECT * FROM fn(...)` for a table function; `SELECT fn(...)` for a scalar. `CommandType.Text` with the exact schema-qualified, quoted name |
| **Procedure returning one result set** | `ExecuteReader`, `Fill(DataTable)`, Dapper `Query` on a procedure | Function `RETURNS TABLE` / `SETOF`, read with `SELECT * FROM fn(...)`. Column names and order as in the contract |
| **Several result sets** | `NextResult()`, `Fill(DataSet)` with several tables, Dapper `QueryMultiple` | Function with one **refcursor** OUT per result set (same count as today). In one transaction: call, read the cursor names, `FETCH ALL FROM "<name>"` per cursor in order, then close; dispose every reader. A `DataSet` gets one table per cursor |
| `OUTPUT` clause on INSERT/UPDATE/DELETE | `OUTPUT INSERTED.*`, `OUTPUT DELETED.*`, `OUTPUT ... INTO @t` | `RETURNING`. Old values of an UPDATE: `RETURNING OLD.*` needs PostgreSQL 18; before that, a data-modifying CTE that selects the rows `FOR UPDATE` first. `OUTPUT ... INTO` a table variable → `WITH x AS (... RETURNING ...) INSERT INTO ... SELECT ... FROM x` |
| OUTPUT / InputOutput parameters | `ParameterDirection.Output` / `InputOutput` | Become result columns; InputOutput is both an argument and a column. Re-check every caller that read `.Value` |
| Return value | `ParameterDirection.ReturnValue`, `RETURN n` | No equivalent: a `ReturnValue` result column per contract |
| Table-valued parameter | `SqlDbType.Structured`, `AsTableValuedParameter`, `.TypeName =` | PostgreSQL has no table type. Options, chosen with the DB team: an array of a composite type (`MapComposite`; the type is a DB-team prerequisite), parallel arrays read with `unnest(@a, @b)`, one `jsonb` argument read with `jsonb_to_recordset`, or a temp table filled with `COPY`. Never a `DataTable` on the PostgreSQL path |
| `SqlBulkCopy` | `SqlBulkCopy`, its options | Bulk-insert seam over `COPY ... FROM STDIN (FORMAT BINARY)`; reproduce batch size, column mapping, identity, triggers and constraint options |
| `ExecuteXmlReader`, `FOR XML` | `ExecuteXmlReader`, `FOR XML PATH/RAW/AUTO` | No FOR XML. Either the function returns XML built with PostgreSQL's XML functions, or the code builds the XML from rows. A design decision with the DB team; replay the goldens byte for byte |
| `ExecuteScalar` | casts of its result | PostgreSQL returns `bigint`, `numeric`, `bool` where SQL Server returned `int`, `decimal`, `bit`: use `Convert.ToInt32` and friends, not direct casts |
| Reader column access | `reader["Name"]`, `DataRow["Name"]`, Dapper mapping | Column names come back as the contract says (case and underscores); access by the contract name |
| MARS | `MultipleActiveResultSets=True`, nested readers | No equivalent: buffer the first result, or a second connection |
| EF Core / EF6 / Dapper / NHibernate | provider-specific calls, `FromSqlRaw`, `HasDbFunction` | Per technology: Npgsql provider, provider-specific migrations, raw SQL through the query provider, `xmin` for row versions |

## Statements inside the code

Raw T-SQL in strings goes into the PostgreSQL resource rewritten:

- `TOP n` in a `SELECT` → `LIMIT n` (`TOP (@n)` → `LIMIT @n`). `LIMIT` is not valid on `UPDATE` or `DELETE`: use `WHERE id IN (SELECT id ... ORDER BY ... LIMIT n FOR UPDATE)`, or `ctid` for a table without a key; `ISNULL` → `COALESCE`; `CHARINDEX(a, b)` → `STRPOS(b, a)` (arguments flipped); `LEN` → `LENGTH` (trailing spaces differ); `IIF` → `CASE`; `GETDATE()` → `now()` / `LOCALTIMESTAMP` (match the column type); `NEWID()` → `gen_random_uuid()`; `+` on strings → `||` (and NULL propagates the same way only with `||`, not `CONCAT`).
- `SCOPE_IDENTITY()` / `@@IDENTITY` → `INSERT ... RETURNING id`. **Never `lastval()`** (wrong under triggers and concurrency). `NEXT VALUE FOR s` → `nextval('s')`.
- `MERGE` is version-gated: PostgreSQL 15+ has `MERGE`; `WHEN NOT MATCHED BY SOURCE` and `RETURNING` on `MERGE` need PostgreSQL 17. On an older target, or for a plain upsert, use `INSERT ... ON CONFLICT`. Read the target version from the plan (the default is 16) before choosing.
- `UPDATE ... FROM ... JOIN`, `DELETE ... JOIN` → PostgreSQL `UPDATE ... FROM` / `DELETE ... USING`. `CROSS/OUTER APPLY` → `LATERAL`.
- `#temp` → `CREATE TEMP TABLE` (check its lifetime across calls); `##global` → redesign (flag); table variables → temp table or CTE.
- `NOLOCK` → remove (or flag where dirty reads were relied on); `UPDLOCK` → `FOR UPDATE`; `READPAST` → `SKIP LOCKED`; `OPTION (RECOMPILE/MAXDOP)` → remove.
- `OFFSET/FETCH` needs `ORDER BY`; nullable `ORDER BY` needs `NULLS FIRST/LAST` to match SQL Server; text `ORDER BY` needs a pinned collation.
- Case-insensitive comparisons (default SQL Server collation) → `ILIKE`, `lower()` on both sides, or a `citext`/ICU nondeterministic collation chosen with the DB team; unique text indexes reviewed.
- `bit` compares (`= 1`) → `= true`, bind as `bool`.
- `AVG` over an integer column: SQL Server returns an integer (truncated), PostgreSQL returns `numeric`. Use `trunc(avg(x))::int` to keep the old result, or change the reading code on purpose and report it. Implicit conversions differ in general: make every one an explicit `CAST`.
- Trailing spaces: SQL Server ignores them in `=` comparisons for `varchar` and `char`; PostgreSQL ignores them only for `char(n)`, not for `varchar` or `text`. Keys and lookups that relied on it need `rtrim` on both sides or a data clean-up (DB team).
- `SET IDENTITY_INSERT t ON` with explicit ids → `INSERT ... OVERRIDING SYSTEM VALUE` (for `GENERATED ALWAYS`), then re-sync the sequence: `SELECT setval(pg_get_serial_sequence('t', 'id'), (SELECT max(id) FROM t))`.
- `SET NOCOUNT ON`, `SET ANSI_NULLS`, `SET QUOTED_IDENTIFIER` → remove.
- `STRING_SPLIT` → `string_to_array` / `unnest WITH ORDINALITY`; `FOR XML PATH('')` concatenation → `string_agg(... ORDER BY ...)`; `FOR JSON` → `json_agg` / `row_to_json`. JSON by version: `JSON_VALUE`, `JSON_QUERY`, `JSON_EXISTS` and `JSON_TABLE` exist only from PostgreSQL 17; below 17 use the operators (`->`, `->>`, `#>>`), `jsonb_path_query`, and `jsonb_to_recordset` for `OPENJSON`.
- `TRY_CONVERT`, `TRY_CAST`, `ISNUMERIC` → flag; validate in .NET. `CONTAINS`/`FREETEXT` → `tsvector` + GIN, or flag. `GO` → remove. `TRUNCATE` resetting identity → `RESTART IDENTITY`. `@@ROWCOUNT` → `GET DIAGNOSTICS` in PL/pgSQL or the affected-rows count from the command.
- IN lists built by string concatenation → one array parameter (`= ANY(@ids)`). SQL Server's 2,100-parameter limit no longer applies. With Dapper on an `NpgsqlConnection` a list parameter is sent as one array, so `= ANY(@ids)` is right, and Dapper's SQL Server form `IN @ids` is not expanded and fails. A wrapped connection (a profiler) has another type name and makes Dapper expand the list again: test through the real connection type.
- Positional `?` (OLE DB, ODBC) and `$1` → named `@name`; no parameter name that is a prefix of another; no literal `@` or `:` left in SQL text.

## Transactions, errors and connections

- **An error aborts the whole PostgreSQL transaction.** Any `catch` that swallows an error inside a transaction and carries on now fails on the next statement: use a savepoint, or end the transaction.
- `RepeatableRead` / `Serializable` → a bounded retry on SQLSTATE `40001`.
- `new TransactionScope()` defaults to **Serializable** (and a one-minute timeout). On PostgreSQL that brings serialization failures. Pass `TransactionOptions { IsolationLevel = IsolationLevel.ReadCommitted }` unless Serializable was meant, and report the change.
- `TransactionScope` over two resources (two databases, a database and a queue) → restructure (outbox, saga) or flag. Distributed transactions need MSDTC: on .NET 7+ `TransactionManager.ImplicitDistributedTransactions` can be set only on Windows, so Linux has none.
- No transaction kept open across outbound HTTP or other slow I/O.
- **Error numbers** → SQLSTATE through one classifier: 2627/2601 (duplicate key) → `23505`; 547 (foreign key) → `23503`; 515 (NULL into NOT NULL) → `23502`; 8152 / 2628 (string truncated) → `22001`; 1205 (deadlock) → `40P01`; serialization → `40001`; 4060 (cannot open database) → `3D000`; `RAISERROR`/`THROW 5xxxx` from procedures → the SQLSTATE the DB team chose. `SqlException` → `DbException` in shared code; the SQLSTATE is `PostgresException.SqlState` (Npgsql). Checks written as `switch (ex.Number)` / `case 2627:` count too.
- Connection strings: one per engine, from configuration and Secrets Manager; `Search Path` explicit; startup asserts the connection string is present. Integrated security → database login or IAM auth (no Kerberos in a Linux container by default). With PgBouncer in transaction mode, prepared statements need PgBouncer's `max_prepared_statements` (1.21+), and the Npgsql connection string sets `No Reset On Close=true`. Set `Maximum Pool Size` from the task count so the total stays under the database's connection limit.
- Microsoft.Data.SqlClient 4.0+ defaults to `Encrypt=true`. On the SQL Server path in a Linux container the connection fails unless the server certificate is trusted: add the CA to the image, or use `TrustServerCertificate=true` in test environments only.

## Types, dates and names

- `datetime` / `datetime2` → `timestamp`; `datetimeoffset` → `timestamptz`. `DateTime.Kind` must match the column (Npgsql rejects a `Local` or `Unspecified` value for `timestamptz`); no `ToUniversalTime` on `timestamp` columns. Precision drops from 100 ns to 1 µs: equality checks on round-tripped values break.
- Npgsql 6+ maps a UTC `DateTime` to `timestamptz`, rejects a UTC `DateTime` for a `timestamp` column, and rejects a `DateTimeOffset` with a non-zero offset for `timestamptz`. The `Npgsql.EnableLegacyTimestampBehavior` switch brings back the old mapping as a temporary bridge only: if used, it goes in the report with a removal date.
- `DateTime.MinValue` and `MaxValue` become `-infinity` and `infinity` unless `Npgsql.DisableDateTimeInfinityConversions` is set. Code that stores them as sentinels picks one behaviour and tests it.
- `money` → `numeric(19,4)`; bare `DECIMAL` → flag (default precision differs); `uniqueidentifier` → `uuid` (never `varchar(36)`); GUID sort order differs; `rowversion` → `xmin` (EF concurrency token).
- No equivalent (flag, do not map silently): `hierarchyid`, `geography`/`geometry` (PostGIS is a decision), `sql_variant`, Always Encrypted columns.
- Identifiers: under `preserve`, every name is double-quoted exactly as the contract has it; names over 63 bytes and reserved words are renamed by the DB team and reported. `[brackets]` and `dbo.` go.

## Conversions that change values

These compile on both engines but give different results. Each one is rewritten on purpose and listed in the report.

| SQL Server | What differs | PostgreSQL rewrite |
|---|---|---|
| `DATEDIFF(month, a, b)`, `DATEDIFF(year, a, b)` | Counts boundaries crossed (31 Jan to 1 Feb is 1 month) | `(extract(year from b) - extract(year from a)) * 12 + extract(month from b) - extract(month from a)`; days: `b::date - a::date`. Not `age()`, which counts whole periods |
| `DATEADD(unit, n, d)` | `n` must be a whole number | `d + make_interval(months => n)` and so on; the result keeps the column type |
| `CONVERT(varchar, d, style)` | Style codes (101, 103, 112, 120 ...) | `to_char(d, '<pattern>')` per style; list the styles used |
| `FORMAT(x, '...', culture)` | .NET culture formatting | `to_char` for fixed patterns; culture-dependent formatting moves to .NET |
| `ROUND(float, n)` | `double precision` may round ties to even | `round(x::numeric, n)` (numeric rounds ties away from zero) |
| `tinyint` | 0-255; PostgreSQL has none | `smallint` with `CHECK (x BETWEEN 0 AND 255)` (DB team) |
| `CAST('' AS int)`, `CAST('' AS datetime)` | SQL Server returns 0 and 1900-01-01 | PostgreSQL raises an error: `NULLIF(x, '')` before the cast, or handle it in .NET |
| `AVG(int_column)`, trailing-space comparisons | See "Statements inside the code" | As above |

## Per technology: EF6, EF Core, Dapper, NHibernate

**EF6 → EF Core** (DevTx KB 07 and 16, with their errors corrected):
- Staying is possible: EF 6.5 runs on .NET 10. For a PostgreSQL target, move to EF Core with the Npgsql provider.
- Context: `DbContext(string nameOrConnectionString)` → a constructor taking `DbContextOptions<T>`, configured in `Program.cs` (`UseSqlServer` / `UseNpgsql` from the provider switch). `Database.SetInitializer` goes; migrations replace it.
- API: `DbEntityEntry` → `EntityEntry`; `ObjectContext` and Entity SQL have no equivalent. `Database.SqlQuery<T>` for non-entity results → `Database.SqlQueryRaw<T>` or `SqlQuery<T>(FormattableString)` (unmapped types from EF Core 8); entity results → `FromSqlRaw` / `FromSql`. `[Index]` is supported (`Microsoft.EntityFrameworkCore.IndexAttribute`, or `HasIndex(...)`): KB 00, 07 and 16 say otherwise, which is wrong.
- Keep index and key names (`HasDatabaseName`, `HasConstraintName`) where scripts or hints use them.
- Lazy loading is off by default: `Microsoft.EntityFrameworkCore.Proxies` with `UseLazyLoadingProxies()`, or explicit `Include`. Watch for N+1 queries.
- Cascade-delete and many-to-many defaults differ: compare the generated script (`dotnet ef migrations script`) with the old schema.
- EDMX has no designer: scaffold from the database (`dotnet ef dbcontext scaffold`) or convert to code-first.
- Migrations: the existing SQL Server schema is the baseline. Create an initial migration, mark it applied (its row in `__EFMigrationsHistory`, or an empty `Up`), and never run it against the existing database. One migrations assembly per provider. `HasColumnType("datetime")`, `nvarchar(max)` and `HasDefaultValueSql("getdate()")` are SQL Server text that breaks Npgsql migrations: move them behind the provider.
- Concurrency: `[Timestamp]` / `rowversion` → `xmin` on PostgreSQL (a `uint` property marked `IsRowVersion()`).

**Dapper:** a connection factory in DI (from the provider switch) instead of `new SqlConnection` in repositories; `SqlMapper.AddTypeHandler` where Npgsql maps a type differently (`DateOnly`, enums, JSON); async calls end to end; transactions passed explicitly; `QueryMultiple` becomes refcursor reads (above); lists as arrays (above).

**NHibernate** (verify class names against the version in use): dialect and driver change per engine (Npgsql driver and a PostgreSQL dialect; NHibernate.Extensions.Npgsql 8.x targets .NET 8+ with NHibernate 5.5.2 or later); one `ISessionFactory` (singleton) and one `ISession` per request (scoped); HQL is portable, native SQL (`CreateSQLQuery`) goes through the query provider; schema changes through the DB team's scripts or FluentMigrator, not `SchemaExport`.

## Flag, do not convert

Cross-database three- and four-part names (`db.dbo.t`, `OPENQUERY`, `OPENROWSET`, linked servers): options are `postgres_fdw`, `dblink`, two connections, or a staging copy, decided with the DB team. Also: dynamic SQL (`sp_executesql`, `EXEC(@sql)`), `SqlDependency` (query notifications: PostgreSQL has `LISTEN`/`NOTIFY` with triggers the DB team writes, or polling), CLR procedures, Service Broker, `xp_cmdshell`, `EXECUTE AS`, FILESTREAM, T-SQL cursors and `WHILE` loops in procedures, `CREATE SYNONYM`, temporal tables, partition switching, triggers (the DB team ports them; check bulk paths that disabled them), SQL Agent jobs, Database Mail. Each goes in the report with file, line and the decision needed.

## Checklist groups

The DB porting agent's validation checklist has 97 items in nine groups; Claude with the DB porting skills uses the same groups (summarised here; every item is in [db-porting-checklist.md](../db-porting-checklist.md)):

| Group | Items | What it asks |
|---|---|---|
| Core wiring | 23 | Builds; provider resolved once; connection strings are placeholders; no `new SqlConnection` or engine `if` outside the seams; raw SQL in the query provider and parameterised; SQL Server path unchanged; every resource and contract call resolves |
| .NET breaks | 18 | Reader column names; `ExecuteScalar` casts; parameters; IN lists; exceptions; abort-on-error; retry on `40001`; NOLOCK; MARS; `DateTime.Kind`; GUID ordering; row versions; multi-resource transactions; cross-database names; refcursor count and disposal; named bindings; no transaction across I/O; PgBouncer |
| Configuration | 5 | Connection fields per engine; search path; startup assert; Windows auth as an infrastructure item; prepared statements with PgBouncer |
| Schema and DDL | 7 | Migrations per provider; 63-byte names; no reliance on row order; identity and computed columns; sequences re-synced; synonyms; partitioning |
| Naming | 4 | Identifier style applied uniformly; `par_`/`var_` prefixes in PL/pgSQL; reserved words; prefix check clean |
| Syntax and behaviour | 30 | Every raw statement classified, and each construct above handled |
| Types | 3 | Mappings keep precision; bare DECIMAL flagged; no-equivalent types flagged |
| Per technology | 5 | ADO.NET, Dapper, EF6, EF Core, NHibernate rules followed; procedure bodies reviewed for CLR, dynamic SQL, linked servers, FOR XML, MERGE OUTPUT, Service Broker |
| Sign-off | 2 | Build and provider switch for both engines; report complete |

Scoring (DB porting agent): pass + half credit for a documented divergence, minus 10 per construct with no equivalent and 5 per warning; capped at 69 while any item fails and 40 while the build fails. Filing a code gap as "DB team" or "out of scope" to raise the score is not allowed.

## Done when

No DB-* or SQL-* residue on the PostgreSQL path (or a waiver naming the DB-team decision); every contract call and refcursor read checked; the error classifier in place; every value-changing conversion listed in the report; `verify.py target --db-target dual` runs the residue scan for both paths, but builds and tests once and has no database gate, so run the tests against each engine (switch `Data:Provider`) and record both results; parity replays pass against PostgreSQL in the test environment.
