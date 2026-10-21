The estate is a single repository (`eShopModernizing`, 7 solutions, 11 projects, about 16,000 lines of C# and markup) that contains a product-catalog system in several variants. There are three lineages:
- a catalog web application, as ASP.NET MVC 5 and as ASP.NET Web Forms;
- a WCF catalog service with a Windows desktop client (WinForms/WPF);
- "Modernized" copies of the same applications, adapted to Windows containers and Azure services.

Everything server-side runs on .NET Framework 4.6.1–4.7.2 on Windows/IIS with SQL Server. Two of those target frameworks are already out of support (F-016 to F-019). One earlier port attempt (`eShopPorted`, ASP.NET Core 2.2) still targets .NET Framework 4.6.1.

**Recommended path.** Move the catalog to **.NET 10 (LTS, supported to November 2028) on Linux containers on Amazon ECS with AWS Fargate**, backed by **Amazon RDS for SQL Server**:
- **Replatform** `eShopPorted` (finish the existing port) and the WCF service (CoreWCF keeps the SOAP contract for the desktop clients).
- **Refactor** the small Web Forms catalog to Blazor (F-004).
- **Retain** the desktop clients on user machines, with a repointed service endpoint.
- **Retire** five duplicate or superseded applications, after the client confirms which lineage is in production.

**Effort and duration.** 118–432 hours (15–54 person-days), likely **244 hours (about 30 person-days)**, roughly 7 weeks with a team of three. This assumes AI-assisted delivery: AWS Transform for .NET or coding agents do the mechanical port, with generated tests and infrastructure templates. The manual equivalent is about 434 hours likely, so AI assistance saves about 44%. The figure includes QA, the AWS foundation, cut-over, project management and contingency (Effort & timeline). The largest single item is the Web Forms rewrite (about 62 hours likely). Alternatives are compared side by side in the scenario table:
- rehost as-is on EC2 Windows: about 186 hours;
- lift-and-shift to EC2 Linux: about 203 hours;
- full PostgreSQL port: about 327 hours.

**Licensing.** All server workloads leave Windows Server; only the desktop clients stay on Windows (user machines, no server licence). The database moves to RDS for SQL Server (licence included). No code-level blocker to Babelfish was found in the repository, but there is no production schema in it, so a Babelfish Compass run on a schema export decides whether the SQL Server licence can go too (section 6).

**Top risks.**
1. A brands download API returns **BinaryFormatter** output, which always throws on .NET 9 and later (F-006). The endpoint and its consumers must switch to JSON.
2. There are **no automated tests** (F-034). Regression relies on client QA, so we start with characterisation tests for the catalog flows.
3. **Production configuration is not in the repository.** Connection strings point at LocalDB, so server, authentication and identity-provider details are open questions (section 9.2).

**Next steps.**
- The client confirms the production lineage (Retire list) and answers the open questions.
- We run Babelfish Compass on a schema export and spike the BinaryFormatter replacement.
- The AWS account team can check funding eligibility (for example MAP) for the wave plan.
