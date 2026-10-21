> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Audit SQL Server to PostgreSQL coverage

agent ae4e44d9725e4ed0e

READ-ONLY AUDIT: DB porting coverage (SQL Server to PostgreSQL). No files were edited, created or deleted.

VERDICT: Partial. The public skills cover the dual-mode code seams, the contract, refcursors, OUTPUT/return values, TVPs, COPY, error-number mapping, the 97-item checklist shape and the main T-SQL-to-PG rewrites. They are missing the PostgreSQL-only mode, several value-changing conversions, and automated DB gates. Some statements are wrong or overclaimed.

WRONG OR OVERCLAIMED (fix first)
1. HIGH. raw-sql-and-data-access.md: "Integer AVG truncates in both". False. SQL Server AVG(int) returns int; PG avg(int) returns numeric. Fix: cast or trunc to match. Source: dual-db-port/execute/references/type-map.md (RPT-06) and checklist SX-07.
2. HIGH. verification.md and raw-sql "Done when": "verify.py target --db-target dual builds and tests both engines". verify.py passes --db-target only to residue_scan.py. It runs one build, one test run and no DB gate. The database gate is manual only. Say so, or add the gate.
3. MED. raw-sql playbook: "NpgsqlException.SqlState". Npgsql exposes SqlState on PostgresException (search result: Npgsql docs, Exceptions/notices). The repo's own windows-api-catalog.md and rules.json already use PostgresException correctly.
4. MED. raw-sql "TOP n -> LIMIT n". LIMIT is invalid on UPDATE/DELETE. Those need a PK subquery or ctid. Source: syntax-map.md A26 and checklist SX-22.
5. MED. raw-sql "MERGE -> INSERT ON CONFLICT; BY SOURCE has no equivalent". Misleading. PG 15+ has MERGE; WHEN NOT MATCHED BY SOURCE arrived in PG 17 (search result: PG 17 manual). Default pg_version is 16, so this is version-gated.
6. MED. engines.md: "the assessment adds [Claude-path hours] when db_tool is claude". Not implemented. estimate_effort.py never reads db_tool; plan_execution.py only names the tool.
7. MED. database-assessment.md step 4 and estimate notes name "AWS DMS Schema Conversion or AWS SCT" for code conversion. AWS docs (search snippet) describe SCT's C# application conversion as Oracle-only. DMS SC converts schema objects, not application code. Re-scope the tooling claim.
8. MED. Dapper `= ANY(@ids)` (raw-sql playbook). Conflicts with the internal dapper.md note that Dapper expands IN lists into one parameter per element. Unverified either way (search found no confirmation). Say how to pass an array without expansion, or verify.
9. Npgsql DateTime is incomplete, not wrong. Npgsql 6.0 notes (fetched): DateTime maps to timestamptz by default, UTC to a timestamp column is rejected, and DateTimeOffset with a non-zero offset is rejected. The playbook covers only Local/Unspecified to timestamptz.

GAPS (source -> requirement -> target file)
HIGH
- G1. PostgreSQL-only mode is absent from the public playbook. Source: pg-only-port/SKILL.md (R1 to R13, no provider switch, "data migration is in scope") and validate/references/checklist/cutover-completeness.md (4 items: no SqlClient package refs, no MSSQL connection strings, no dbo qualifiers, a data-migration artifact). The public playbook assumes dual mode throughout, and database-assessment.md puts data movement out of scope. Target: raw-sql playbook (PG-only section) and engines.md "Choosing".
- G2. Residue rules do not enforce the seam in dual mode. DB-SQLCLIENT is scoped to when:postgresql only, so nothing flags SqlConnection outside the factory, provider conditionals, or DbProviderFactories. Target: residue_rules.json.
- G3. Residue SQL-TSQL-IN-STRING misses the constructs the playbook tells the reader to find: TOP (@n), OUTPUT DELETED, MERGE, #temp, UPDLOCK/READPAST/HOLDLOCK, @@ROWCOUNT, sp_executesql. Target: residue_rules.json.
- G4. Value-changing conversions have no mapping in the playbook while the block-level rule fires on them: DATEADD, DATEDIFF (month/year boundaries), CONVERT style codes, FORMAT, ROUND on float, tinyint CHECK 0-255, CAST('' AS int). Source: syntax-map A13, A70 to A73; type-map "value, not type" table; checklist SX-30. Target: raw-sql playbook.
- G5. No automated lint for refcursor disposal, PL/pgSQL parameter prefixes, SQL resource parity or contract-call matching. The playbook's Done-when claims these are checked. Source: pg-only validate/scripts check-refcursor-disposal.mjs and check-plpgsql-param-prefix.mjs; checklist CW-18, CW-22, DB-15. Target: residue_rules.json and verification.md.
MED
- G6. Public has group counts only (97 items, 9 groups; the counts match the internal checklist.json exactly). The Claude path has no per-item list to decide against. Source: dual-db-port/validate/checklist.json. Target: raw-sql playbook (a summary reference file; mind the licence note).
- G7. Trailing-space equality and char(n) padding are not covered beyond LEN. Source: checklist SX-09, type-map char(n). Target: raw-sql playbook.
- G8. TransactionScope defaults to Serializable in .NET. Secondary sources only (search, older blogs); confirm on Learn. Source: isolation.md. Target: raw-sql playbook "Transactions".
- G9. Npgsql EnableLegacyTimestampBehavior (a temporary bridge, must be reported), DisableDateTimeInfinityConversions, and DateTime range/precision. Source: dotnet-breaks/datetime-npgsql.md; Npgsql 6.0 notes. Target: raw-sql playbook "Types, dates and names".
- G10. OUTPUT clause on INSERT/UPDATE/DELETE to RETURNING, including old-row values via a data-modifying CTE. Source: syntax-map A21; pg_conversion "OUTPUT clause". Target: raw-sql playbook "Statements".
- G11. SqlDependency has no PG equivalent (LISTEN/NOTIFY or polling). Source: rules.json DATA-SQLDEPENDENCY; raw_sql.py API_RX. No residue rule and no playbook text. Target: raw-sql playbook "Flag, do not convert" and residue_rules.json.
- G12. Babelfish is absent from every reference. Only an eval prompt mentions it. AWS docs (search): Aurora PostgreSQL only; SCRAM, IAM, RDS Proxy and Database Activity Streams unsupported; CHECKSUM hashes differ; OUTPUT restrictions; 100-parameter cap; identifiers over 63 bytes hashed; numeric identity precision 19 vs 38. Target: database-assessment.md and engines.md (a decision point, not a code path).
- G13. EF Core: HasColumnType and DefaultValueSql with SQL Server type names or functions (GETDATE()) break PG migrations. The internal checklist PT-04 covers EF6 only. Target: kb/16 and the raw-sql playbook.
- G14. IDENTITY_INSERT needs OVERRIDING SYSTEM VALUE plus sequence re-sync after explicit-id loads. Source: pg_conversion "IDENTITY_INSERT" (rewrite). Target: raw-sql playbook.
- G15. JSON functions: native operators below PG17, SQL/JSON functions only from 17. The playbook says "by version" without the rule. Source: syntax-map A61 to A63, checklist SX-16. Target: raw-sql playbook.
- G16. Partial: InList/Dapper arrays are covered only by the playbook's `= ANY(@ids)` line (see item 8).
LOW
- G17. Dual-mode SQL-Server error-number detection misses switch/case forms (residue DB-SQLERROR-NUMBER; raw_sql.py API_RX catches them).
- G18. Npgsql pool settings: No Reset On Close, max_prepared_statements, bootstrap through PgBouncer. Source: checklist DB-18, CF-05.
- G19. pg_conversion.json has no entries for sp_getapplock, SCHEMA_NAME, ROUND, SET NOCOUNT or ANSI options; they fall to the generic default (0.05-0.2 h). Target: codebase-documenter/scripts/data/pg_conversion.json.
- G20. The playbook says TVP becomes a composite array. The internal checklist (SX-11, TY-03) offers array+unnest, jsonb or temp table and flags TVP types as no-equivalent. Present the options.

PUBLIC TEXT RULE: the internal source paths above are for the auditor only. Any text lifted into the public skills must not name the internal tool. Summarise.

SOURCES: internal files under <db-agent-repo>\.db-agent\skills\{dual-db-port,pg-only-port}; public files under skills/{dotnet-modernization,modernization-assessment,codebase-documenter}; web: npgsql.org 6.0 release notes, Npgsql PostgresException docs, PostgreSQL 17 MERGE manual and Percona/depesz posts, AWS SCT C# application conversion page, AWS Babelfish limitations page.
