# DB porting checklist (summary)

The DB porting agent signs off a SQL Server → PostgreSQL code port against a 97-item checklist in 9 groups. This page summarises every item in this skill's own words, so that Claude with the DB porting skills, and anyone reviewing the agent's report, can decide each item the same way. The IDs match the agent's report. **Auto** means the agent has a script check for it; every other item is a judgement the reviewer records (done, not applicable, or flagged with options). The how-to for each item is in [playbooks/raw-sql-and-data-access.md](playbooks/raw-sql-and-data-access.md).

Items are written for the dual-database mode (both engines behind one provider switch).

## Contents
- [Core wiring and guardrails (23)](#core-wiring-and-guardrails-23)
- [.NET-layer breaks (18)](#net-layer-breaks-18)
- [Configuration (5)](#configuration-5)
- [Schema, migrations and DDL (7)](#schema-migrations-and-ddl-7)
- [Naming (4)](#naming-4)
- [SQL syntax and behaviour (30)](#sql-syntax-and-behaviour-30)
- [Types (3)](#types-3)
- [Per technology (5)](#per-technology-5)
- [Sign-off (2)](#sign-off-2)

## Core wiring and guardrails (23)

Always checked.

| ID | Check | Auto |
|---|---|---|
| CW-01 | The solution builds. | yes |
| CW-02 | The provider setting is read once at start-up into a typed value; a wrong value stops the app at once. | |
| CW-03 | Both connection strings exist as placeholders; no secret appears anywhere, including logs and the report. | |
| CW-04 | `new SqlConnection` appears only inside the connection factory. | yes |
| CW-05 | Concrete `Sql*` types appear only in the SQL Server dialect code. | |
| CW-06 | Repositories and services contain no provider checks (`if (isPg)`, connection-string sniffing, type tests). | yes |
| CW-07 | All raw SQL lives in the query provider and is parameterised; any SQL that was concatenated is now parameterised and reported as a security fix. | |
| CW-08 | SQL Server behaviour is unchanged on every path (results, order, precision, performance): the PostgreSQL path was added beside it. | |
| CW-09 | No logic changes slipped in as improvements (query rewrites, caching, paging changes). | |
| CW-10 | No logical schema change unless the run allows it; only per-engine type mapping. | |
| CW-11 | Every mapping that can lose data or precision is flagged in the report. | |
| CW-12 | One portable statement is preferred over two dialect versions; every fork made points to a known dialect difference. | |
| CW-13 | Every construct with no PostgreSQL equivalent is flagged with two or three options, never approximated quietly. | |
| CW-14 | The change set is repeatable and touches nothing outside scope (no drive-by reformatting). | |
| CW-15 | Both engines were exercised, or every unverified path is listed; no claim of testing against an engine nobody connected to. | yes |
| CW-16 | Nothing is renamed beyond the mandated identifier style and PL/pgSQL prefixes; all other names match the original exactly. | |
| CW-17 | The PostgreSQL version is taken from the repository or infrastructure (image tag, CI, IaC, runbook), not assumed; every version-dependent choice (MERGE, JSON functions, generated columns, INCLUDE indexes) matches it. | |
| CW-18 | Every named SQL resource the code loads exists for each provider path that reaches it. | yes |
| CW-19 | No database object was written unless its source is in the repository; objects the app calls with no source are listed as DB-team prerequisites. | yes |
| CW-20 | Every reference the plan required was actually used during the change. | yes |
| CW-21 | Every file the analysis flagged was changed, or skipped with a reason. | yes |
| CW-22 | Every PostgreSQL call matches the database contract: exact (quoted) name, `CALL` for procedures and `SELECT` for functions, arguments in contract order (a TVP as one composite array), `CommandType.Text`, no named-argument syntax; every contract object has a call path; EF `[DbFunction]` schemas remapped; `rowversion` mapped to `xmin`. | yes |
| CW-23 | The provider switch key and both connection-string names exist in `appsettings.json` exactly as the code reads them, so the app starts on either engine. | yes |

## .NET-layer breaks (18)

Checked when the matching code exists.

| ID | Check |
|---|---|
| DB-01 | Reader access by column name works under the chosen identifier style everywhere (readers, `DataTable`, `IDataRecord`, hand-written mappers); Dapper maps underscores when names are snake case. |
| DB-02 | Every `ExecuteScalar` result is converted, not cast to one engine's boxed type. |
| DB-03 | Parameters are checked for reuse in one statement, prefix collisions (`@id` / `@id2`), `@` or `:` inside literals, casts, JSON operators or comments, and name casing; no `SqlDbType` in shared code. |
| DB-04 | `IN` lists with a variable count use one array parameter (`= ANY(@ids)` on PostgreSQL), not expanded literals. |
| DB-05 | `SqlException` handling becomes `DbException` or goes through the dialect's error classifier; retry rules keyed on SQL Server error numbers also cover PostgreSQL `SqlState` codes. |
| DB-06 | Every catch-and-continue inside a transaction is reviewed: PostgreSQL aborts the whole transaction on an error. Use a savepoint or restructure. Procedures with `SET XACT_ABORT ON` already behave this way. |
| DB-07 | `REPEATABLE READ` and `SERIALIZABLE` paths retry on `40001`; code that relied on SQL Server's read blocking takes `FOR UPDATE` locks; `SNAPSHOT` use is mapped to a PostgreSQL level. |
| DB-08 | Every `NOLOCK` / `READ UNCOMMITTED` (in SQL and in C# `IsolationLevel`) is removed as unneeded under MVCC or flagged as a real dependency. |
| DB-09 | MARS dependencies are removed: buffer the first result or use a second connection; check nested readers and lazy loading. |
| DB-10 | One `DateTime.Kind` convention end to end (database reads, `Now` / `UtcNow`, JSON input, values from SQL Server); the Npgsql legacy timestamp and infinity switches are decided and reported; sub-microsecond assertions and `MinValue`-based validation are flagged. |
| DB-11 | Code or tests that depend on GUID order are reviewed; `NEWSEQUENTIALID()` gets a UUIDv7 or sequence alternative. |
| DB-12 | A concurrency-token strategy is chosen and written down (`xmin`, a version column, or a timestamp); SQL Server's `TIMESTAMP` is never mapped to PostgreSQL `timestamp`. |
| DB-13 | Transactions spanning several connections or resources are restructured to one resource, or flagged with `max_prepared_transactions` as an infrastructure prerequisite. |
| DB-14 | Three-part (cross-database) names are flagged with options: `postgres_fdw` / `dblink`, or two connections joined in the app. |
| DB-15 | Each multi-result procedure has as many refcursors as the original had result sets, and the calling code closes every one. |
| DB-16 | Every positional parameter binding becomes named; a driver with no named parameters is flagged as a standing order risk. |
| DB-17 | No connection or transaction stays open across outbound I/O or across calls on a class field, and every catch inside a transaction rolls back or disposes, so no session sits "idle in transaction". |
| DB-18 | With PgBouncer in front: `No Reset On Close=true` when Npgsql pooling is on, prepared statements handled, and the first migration run directly against PostgreSQL; all listed as infrastructure prerequisites. |

## Configuration (5)

| ID | Check |
|---|---|
| CF-01 | Every connection-string setting (host, port, database, user, authentication, TLS, pool size, timeouts, MARS, read routing, default schema) is set per engine, never translated at run time. |
| CF-02 | The PostgreSQL connection string sets `Search Path` explicitly. |
| CF-03 | Start-up checks that the chosen provider's connection string exists and is not empty. |
| CF-04 | Windows authentication (`Integrated Security`) is listed as an infrastructure prerequisite, not solved in code. |
| CF-05 | With a transaction-mode pooler, prepared statements are configured or turned off, and this is listed as an infrastructure prerequisite. |

## Schema, migrations and DDL (7)

| ID | Check |
|---|---|
| SD-01 | Each provider has its own migration set, and every model change has a migration in each set. |
| SD-02 | Generated index, key and constraint names fit PostgreSQL's 63-byte limit, shortened on purpose where truncation would collide. |
| SD-03 | Nothing relies on physical row order (PostgreSQL has no clustered index): every query whose order matters has `ORDER BY`. |
| SD-04 | Per-engine DDL differences are handled: identity and identity insert, existence guards, computed columns (PostgreSQL stored columns need immutable expressions), filtered and included indexes, catalog queries, procedural script blocks. |
| SD-05 | Sequences are reset to `max(id)` after data loads, as a runbook step. |
| SD-06 | Synonyms are flagged: a view for same-database targets, the cross-database options for others. |
| SD-07 | Partitioning is redone per engine; nothing relies on SQL Server partition switching, splitting or merging. |

## Naming (4)

| ID | Check | Auto |
|---|---|---|
| NM-01 | One identifier style (preserve or snake case) everywhere, never mixed; brackets removed through the dialect's quoting. | |
| NM-02 | PL/pgSQL parameters and locals get the configured prefixes in every ported routine, no column shadowing, columns qualified with the table alias; .NET call sites keep their `@name` style. | |
| NM-03 | Every table, column and alias is checked against PostgreSQL reserved words: quoted, or renamed only when schema changes are allowed; collisions reported. | |
| NM-04 | No PL/pgSQL parameter or local is missing its prefix. | yes |

## SQL syntax and behaviour (30)

| ID | Check | Auto |
|---|---|---|
| SX-01 | Every raw SQL statement found is in the report's inventory with a risk class and resolution. | |
| SX-02 | Case-insensitive compares and `LIKE` go through the dialect's case-insensitive helper; bracket character classes in `LIKE` become regex or `SIMILAR TO`. | |
| SX-03 | `ORDER BY` on nullable columns states `NULLS FIRST` or `NULLS LAST`. | |
| SX-04 | `bit` compares become boolean and bind as `bool`, not `= 1`. | |
| SX-05 | Unique indexes on text are reviewed for case: SQL Server treats `Widget` and `widget` as duplicates, PostgreSQL does not. | yes |
| SX-06 | Implicit conversions get an explicit cast where PostgreSQL's stricter typing would fail. | |
| SX-07 | `AVG` over integers is cast so the fractional result matches the intent (SQL Server truncates, PostgreSQL does not). | |
| SX-08 | Text sort order is pinned with a collation where the old order depended on SQL Server's collation (case, punctuation, accents). | yes |
| SX-09 | No string compare relies on SQL Server ignoring trailing spaces. | |
| SX-10 | `GROUP BY` lists every column explicitly: no PostgreSQL-only functional-dependency grouping, no SQL Server alias or ordinal grouping. | |
| SX-11 | Table-valued parameters become an array with `unnest`, JSONB, or a temp table. | |
| SX-12 | Migration retry and rollback plans account for PostgreSQL's fuller transactional DDL. | |
| SX-13 | Query and lock hints (`RECOMPILE`, `MAXDOP`, index hints, `sp_getapplock`, lock timeout, deadlock priority) are removed with the intent reported. | |
| SX-14 | Return codes and output parameters are re-checked against the call style actually used (`CALL` vs `SELECT`); `CommandType.StoredProcedure` behaviour is verified. | |
| SX-15 | String, date, JSON and XML functions are converted or flagged: `STUFF ... FOR XML PATH` → `string_agg`, `PIVOT` → `crosstab` or `CASE`, `FOR JSON` / `OPENJSON` → `json_agg` / `jsonb_to_recordset`, XML methods → `xpath` / `xmltable`. | |
| SX-16 | `JSON_VALUE` / `JSON_QUERY` / `JSON_EXISTS` only on PostgreSQL 17+; below that, the `->`, `->>` and `?` operators. | |
| SX-17 | Explicit sequences (`NEXT VALUE FOR`) become `nextval`, and each default clause is checked on its own. | |
| SX-18 | `CHECKSUM` / `BINARY_CHECKSUM` is flagged when the value is stored or compared across systems; `HASHBYTES` becomes `digest()` (pgcrypto). | |
| SX-19 | Temp tables and table variables are converted with their lifetime checked; global `##temp` tables are flagged for redesign. | |
| SX-20 | `TRY_CONVERT`, `TRY_CAST` and `ISNUMERIC` are flagged where PostgreSQL has no soft-fail form; validation moves to .NET. | |
| SX-21 | Bulk loads use `COPY` through the bulk-insert seam, not row-by-row inserts. | |
| SX-22 | `UPDATE ... FROM ... JOIN` and `DELETE ... FROM ... JOIN` use PostgreSQL's forms (`UPDATE ... FROM ... WHERE`, `DELETE ... USING`); `UPDATE` / `DELETE TOP (n)` uses a key subquery or `ctid`. | |
| SX-23 | `CROSS APPLY` / `OUTER APPLY` become `CROSS JOIN LATERAL` / `LEFT JOIN LATERAL`. | |
| SX-24 | Paging with `OFFSET ... FETCH` always has an explicit `ORDER BY`. | |
| SX-25 | String concatenation is checked for NULL handling: `CONCAT` skips NULLs, `+` and `||` propagate them. | |
| SX-26 | Full-text search becomes a `tsvector` column with a GIN index and `to_tsquery` / `ts_rank`, or is flagged when ranking and stemming parity can't be shown. | |
| SX-27 | System-versioned temporal tables are flagged: no core PostgreSQL equivalent, and the extension is not offered on managed cloud PostgreSQL. | |
| SX-28 | Each bulk path keeps its `SqlBulkCopy` options: triggers fire only where they did (per batch when auditing per statement), NULLs become defaults unless `KeepNulls`, sequences reset after `KeepIdentity`, and loads that skipped constraints are reported as a behaviour change. | |
| SX-29 | Inserted ids come from `RETURNING`, never `lastval()` (a trigger's insert changes it); app-side trigger disabling becomes a transaction-local setting the trigger reads; errors raised in triggers are classified by `SqlState`. | |
| SX-30 | Values convert, not just types: `CONVERT` styles become explicit `to_char` formats; `DATEDIFF` month and year counts boundaries; `ROUND` on float runs on `numeric`; `datetime2(7)` / `time(7)` values are truncated to microseconds before writing (no rounding up to year 10000 or `24:00:00`); `binary(n)` readers get padded bytes; reliance on `datetime`'s 1/300 s rounding is reported. | |

## Types (3)

| ID | Check |
|---|---|
| TY-01 | Every type keeps its precision and scale (`money` → `numeric(19,4)`, never float); every bare `DECIMAL` / `NUMERIC` is flagged (SQL Server means `(18,0)`, PostgreSQL means unconstrained). |
| TY-02 | `uniqueidentifier` becomes `uuid` / `Guid`, never `varchar(36)`. |
| TY-03 | Types with no PostgreSQL equivalent (`hierarchyid`, spatial types, `sql_variant`, TVP types, Always Encrypted columns) are flagged with real options, never swapped for a lookalike. |

## Per technology (5)

| ID | Check | Auto |
|---|---|---|
| PT-01 | The data-access technology in use (EF Core, EF6, Dapper, ADO.NET, NHibernate, stored procedures) has every provider difference handled: EF Core model forks, separate migrations assemblies and a PostgreSQL retry policy (`EnableRetryOnFailure` is SQL Server only); Dapper type handlers per provider; ADO.NET adapters and command builders; NHibernate dialect, driver, SQL types and id generators; procedure call style, outputs and result sets. | |
| PT-02 | EF6: every `DbContext` gets a factory connection or a `name=` connection-string name, never a raw connection string, so the provider resolves correctly. | |
| PT-03 | EF6 with config-based registration: both the `entityFramework` providers section and the `DbProviderFactories` entry exist for each provider (one alone fails at the first connection). | |
| PT-04 | EF6: no `HasColumnType` names a SQL Server-only type without a provider fork (the Npgsql EF6 provider throws when building the model). | |
| PT-05 | Every ported procedure body is checked for CLR, dynamic `sp_executesql`, linked servers, `FOR XML`, `MERGE ... OUTPUT`, cursor options, Service Broker and `SqlDependency`; each is ported, moved into the app, or flagged as blocking. | yes |

## Sign-off (2)

| ID | Check |
|---|---|
| SO-01 | The build succeeds, the provider switch resolves for both engines, and both connection strings are configured. The report says plainly that no live test ran against either database: that is QA's job. |
| SO-02 | The report has all its sections, and scratch files are removed. |
