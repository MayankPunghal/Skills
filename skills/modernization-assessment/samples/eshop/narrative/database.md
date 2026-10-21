**Recommendation: Amazon RDS for SQL Server** for `CatalogDb`, migrated with native backup and restore through Amazon S3; AWS DMS only if the downtime window is short. RDS keeps T-SQL and EF6/EF Core behaviour unchanged and needs no change in the data layer.

**Evidence:**
- The repository contains EF models, migrations and seed scripts, but no stored procedures, CLR, linked servers, Agent jobs or other RDS-limited features. The scan of all `.sql` files found none (section 5.8).
- All connection strings in the repository point at LocalDB or a local container (the CFG-DEV-DATABASE findings), so production server, edition, size and authentication mode are open questions.

**Babelfish (removes the SQL Server licence).** Nothing in the code blocks it. Because the production schema is not in the repository, the next step is a **Babelfish Compass** run on a schema export from production. If Compass reports no blockers, Aurora PostgreSQL with Babelfish is the lower-cost target: about 24–60 hours (3–7.5 person-days) versus 8–24 hours (1–3 person-days) for RDS.

**Authentication:** use SQL authentication with credentials in AWS Secrets Manager (with rotation). The Azure SQL access-token code in the Modernized variants is not needed on AWS.
