# Playbook: raw SQL and data access (SQL Server → PostgreSQL)

**Rules:** DB-SQLCLIENT, DB-SYSTEM-SQLCLIENT, DB-SQLERROR-NUMBER, DB-XMLREADER, SQL-TSQL-IN-STRING, SQL-CROSS-DB, SQL-CONCAT-VALUE (residue); DATA-* and DB-* (assessment).
**Engines:** neither DevTx nor AWS Transform converts SQL. The database tool does: the DB porting agent, or Claude with the DB porting skills ([engines.md](../engines.md#db-porting-agent)). DevTx KB 07, 16, 17, 18 cover ADO.NET, EF6 → EF Core, Dapper and NHibernate on SQL Server only.

## Contents

- [Ground rules](#ground-rules)
- [Steps](#steps)
- [Calls and results](#calls-and-results)
- [Statements inside the code](#statements-inside-the-code)
- [Transactions, errors and connections](#transactions-errors-and-connections)
- [Types, dates and names](#types-dates-and-names)
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
| OUTPUT / InputOutput parameters | `ParameterDirection.Output` / `InputOutput` | Become result columns; InputOutput is both an argument and a column. Re-check every caller that read `.Value` |
| Return value | `ParameterDirection.ReturnValue`, `RETURN n` | No equivalent: a `ReturnValue` result column per contract |
| Table-valued parameter | `SqlDbType.Structured`, `AsTableValuedParameter`, `.TypeName =` | One composite-array argument (`MapComposite`); the composite type is a DB-team prerequisite. Never a `DataTable` on the PostgreSQL path |
| `SqlBulkCopy` | `SqlBulkCopy`, its options | Bulk-insert seam over `COPY ... FROM STDIN (FORMAT BINARY)`; reproduce batch size, column mapping, identity, triggers and constraint options |
| `ExecuteXmlReader`, `FOR XML` | `ExecuteXmlReader`, `FOR XML PATH/RAW/AUTO` | No FOR XML. Either the function returns XML built with PostgreSQL's XML functions, or the code builds the XML from rows. A design decision with the DB team; replay the goldens byte for byte |
| `ExecuteScalar` | casts of its result | PostgreSQL returns `bigint`, `numeric`, `bool` where SQL Server returned `int`, `decimal`, `bit`: use `Convert.ToInt32` and friends, not direct casts |
| Reader column access | `reader["Name"]`, `DataRow["Name"]`, Dapper mapping | Column names come back as the contract says (case and underscores); access by the contract name |
| MARS | `MultipleActiveResultSets=True`, nested readers | No equivalent: buffer the first result, or a second connection |
| EF Core / EF6 / Dapper / NHibernate | provider-specific calls, `FromSqlRaw`, `HasDbFunction` | Per technology: Npgsql provider, provider-specific migrations, raw SQL through the query provider, `xmin` for row versions |

## Statements inside the code

Raw T-SQL in strings goes into the PostgreSQL resource rewritten:

- `TOP n` → `LIMIT n`; `ISNULL` → `COALESCE`; `CHARINDEX(a, b)` → `STRPOS(b, a)` (arguments flipped); `LEN` → `LENGTH` (trailing spaces differ); `IIF` → `CASE`; `GETDATE()` → `now()` / `LOCALTIMESTAMP` (match the column type); `NEWID()` → `gen_random_uuid()`; `+` on strings → `||` (and NULL propagates the same way only with `||`, not `CONCAT`).
- `SCOPE_IDENTITY()` / `@@IDENTITY` → `INSERT ... RETURNING id`. **Never `lastval()`** (wrong under triggers and concurrency). `NEXT VALUE FOR s` → `nextval('s')`.
- `MERGE` → `INSERT ... ON CONFLICT`; a `WHEN NOT MATCHED BY SOURCE` delete branch has no equivalent: flag it.
- `UPDATE ... FROM ... JOIN`, `DELETE ... JOIN` → PostgreSQL `UPDATE ... FROM` / `DELETE ... USING`. `CROSS/OUTER APPLY` → `LATERAL`.
- `#temp` → `CREATE TEMP TABLE` (check its lifetime across calls); `##global` → redesign (flag); table variables → temp table or CTE.
- `NOLOCK` → remove (or flag where dirty reads were relied on); `UPDLOCK` → `FOR UPDATE`; `READPAST` → `SKIP LOCKED`; `OPTION (RECOMPILE/MAXDOP)` → remove.
- `OFFSET/FETCH` needs `ORDER BY`; nullable `ORDER BY` needs `NULLS FIRST/LAST` to match SQL Server; text `ORDER BY` needs a pinned collation.
- Case-insensitive comparisons (default SQL Server collation) → `ILIKE`, `lower()` on both sides, or a `citext`/ICU nondeterministic collation chosen with the DB team; unique text indexes reviewed.
- `bit` compares (`= 1`) → `= true`, bind as `bool`. Integer `AVG` truncates in both, but implicit conversions differ: make every one an explicit `CAST`.
- `STRING_SPLIT` → `string_to_array` / `unnest WITH ORDINALITY`; `FOR XML PATH('')` concatenation → `string_agg(... ORDER BY ...)`; `FOR JSON` → `json_agg` / `row_to_json`; JSON functions by PostgreSQL version.
- `TRY_CONVERT`, `TRY_CAST`, `ISNUMERIC` → flag; validate in .NET. `CONTAINS`/`FREETEXT` → `tsvector` + GIN, or flag. `GO` → remove. `TRUNCATE` resetting identity → `RESTART IDENTITY`. `@@ROWCOUNT` → `GET DIAGNOSTICS` in PL/pgSQL or the affected-rows count from the command.
- IN lists built by string concatenation → one array parameter (`= ANY(@ids)`). SQL Server's 2,100-parameter limit no longer applies.
- Positional `?` (OLE DB, ODBC) and `$1` → named `@name`; no parameter name that is a prefix of another; no literal `@` or `:` left in SQL text.

## Transactions, errors and connections

- **An error aborts the whole PostgreSQL transaction.** Any `catch` that swallows an error inside a transaction and carries on now fails on the next statement: use a savepoint, or end the transaction.
- `RepeatableRead` / `Serializable` → a bounded retry on SQLSTATE `40001`. `TransactionScope` over two resources (two databases, a database and a queue) → restructure or flag: no distributed transactions on Linux.
- No transaction kept open across outbound HTTP or other slow I/O.
- **Error numbers** → SQLSTATE through one classifier: 2627/2601 (duplicate key) → `23505`; 547 (foreign key) → `23503`; 515 (NULL into NOT NULL) → `23502`; 8152 / 2628 (string truncated) → `22001`; 1205 (deadlock) → `40P01`; serialization → `40001`; 4060 (cannot open database) → `3D000`; `RAISERROR`/`THROW 5xxxx` from procedures → the SQLSTATE the DB team chose. `SqlException` → `DbException` (or `NpgsqlException.SqlState`) in shared code.
- Connection strings: one per engine, from configuration and Secrets Manager; `Search Path` explicit; startup asserts the connection string is present. Integrated security → database login or IAM auth (no Kerberos in a Linux container by default). With PgBouncer in transaction mode, prepared statements need its support.

## Types, dates and names

- `datetime` / `datetime2` → `timestamp`; `datetimeoffset` → `timestamptz`. `DateTime.Kind` must match the column (Npgsql rejects a `Local` or `Unspecified` value for `timestamptz`); no `ToUniversalTime` on `timestamp` columns. Precision drops from 100 ns to 1 µs: equality checks on round-tripped values break.
- `money` → `numeric(19,4)`; bare `DECIMAL` → flag (default precision differs); `uniqueidentifier` → `uuid` (never `varchar(36)`); GUID sort order differs; `rowversion` → `xmin` (EF concurrency token).
- No equivalent (flag, do not map silently): `hierarchyid`, `geography`/`geometry` (PostGIS is a decision), `sql_variant`, Always Encrypted columns.
- Identifiers: under `preserve`, every name is double-quoted exactly as the contract has it; names over 63 bytes and reserved words are renamed by the DB team and reported. `[brackets]` and `dbo.` go.

## Flag, do not convert

Cross-database three- and four-part names (`db.dbo.t`, `OPENQUERY`, `OPENROWSET`, linked servers): options are `postgres_fdw`, `dblink`, two connections, or a staging copy, decided with the DB team. Also: dynamic SQL (`sp_executesql`, `EXEC(@sql)`), CLR procedures, Service Broker, `xp_cmdshell`, `EXECUTE AS`, FILESTREAM, T-SQL cursors and `WHILE` loops in procedures, `CREATE SYNONYM`, temporal tables, partition switching, triggers (the DB team ports them; check bulk paths that disabled them), SQL Agent jobs, Database Mail. Each goes in the report with file, line and the decision needed.

## Checklist groups

The DB porting agent's validation checklist has 97 items in nine groups; Claude with the DB porting skills uses the same groups (summarised here):

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

No DB-* or SQL-* residue on the PostgreSQL path (or a waiver naming the DB-team decision); every contract call and refcursor read checked; the error classifier in place; `verify.py target --db-target dual` builds and tests both engines; parity replays pass against PostgreSQL in the test environment.
