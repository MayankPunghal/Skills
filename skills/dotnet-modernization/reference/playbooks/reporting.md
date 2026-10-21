# Playbook: Reports (ReportViewer/RDLC, SSRS, Crystal Reports)

**Rules:** WEB-REPORTVIEWER, INT-CRYSTAL, INT-SSRS-CLIENT (assessment). Reporting needs a decision: this playbook stops for the user before any change.
**Engines:** Neither engine converts reports. The DevTx KB has no reporting file, and AWS Transform lists third-party UI controls as unsupported.

## Contents
- What runs where
- Options
- Steps
- Gotchas
- Done when

## What runs where

| Technology | On .NET 8/10 and Linux |
|---|---|
| Microsoft ReportViewer controls (Web Forms and WinForms), RDLC files | **.NET Framework only.** Microsoft has not ported them. |
| ReportViewerCore.NETCore / ReportViewerCore.WinForms (community) | A recompiled ReportViewer for .NET 8+. Its NuGet page says it is **not supported or developed by Microsoft**. It renders and exports RDLC (PDF, Excel, Word), but the web build has no interactive viewer. Test fonts and images on the Linux image. |
| SSRS server reports (`.rdl` on a report server) | The app calls the report server through URL access or the REST API, which works from Linux. The report server itself needs Windows and SQL Server. |
| SAP Crystal Reports for Visual Studio | **Verify.** No SAP statement of support for .NET Core, .NET 5+ or Linux was found. Treat it as .NET Framework on Windows until SAP confirms. |

## Options

Present these to the user, per report family, with the volume (number of reports, how often they run, who uses them).

| Option | 7 R | When |
|---|---|---|
| Keep the reporting part on Windows: a small .NET Framework service on EC2 Windows, called by the ported app | Retain / Rehost (that part) | Many complex reports, little change expected, or a Crystal estate |
| Host the reports on SSRS (EC2 Windows, or the SSRS option of RDS for SQL Server) and render them through URL or REST from the ported app | Rehost | Reports already on a report server; the data stays on SQL Server |
| Render RDLC with ReportViewerCore in the Linux container | Replatform | Export-only use (PDF or Excel), and the client accepts a community dependency |
| Rebuild with a commercial reporting tool (Telerik Reporting, DevExpress Reports, Stimulsoft, Bold Reports and others; check each vendor's .NET 10 and Linux support) or as HTML/PDF generation | Refactor | Few reports, or a UI redesign anyway |
| Move to a BI service (Amazon QuickSight dashboards and paginated reports) or a SaaS reporting product | Repurchase | Reports are mostly analytics or exports for business users |

If the database moves to PostgreSQL, every report's data source and its queries move too. Count them in the DB porting work ([raw-sql-and-data-access.md](raw-sql-and-data-access.md)).

## Steps

1. **Inventory.**
   - Every `.rdlc` and `.rdl` file, every Crystal `.rpt` file, and every page or form that hosts a viewer.
   - Each report's data source (dataset class, stored procedure, SQL) and its parameters.
   - Each report's outputs: on-screen, PDF, Excel, email or print.
2. **Record goldens.** Export each report in its formats with fixed parameters on the original. These outputs are the parity reference.
3. **Ask the user to choose** an option per report family, and record the choice as a decision in the execution report.
4. **Apply the choice.**
   - Retain: put an HTTP API in front of the Windows service and call it from the ported app.
   - SSRS: call `/ReportServer?/<path>&rs:Format=PDF` or the REST API with a service account. Keep the credentials in Secrets Manager ([config-and-secrets.md](config-and-secrets.md)).
   - ReportViewerCore: load the `.rdlc` as an embedded resource, bind the data sources by name, and render to a byte array.
   - Rebuild: one report at a time, compared against the goldens.
5. **Compare** each new output with its golden: page count, totals, and text with dates masked.

## Gotchas

- RDLC expressions that call custom code or .NET Framework assemblies (`Code.` blocks, referenced assemblies) may not run under ReportViewerCore. Test those reports first.
- Fonts: a Linux image has few fonts, so PDF layout shifts. Install the fonts the reports use (check their licences) and compare page counts.
- Printing straight from the server (`PrintDocument`, a local printer queue) has no Linux path. Return a PDF instead ([windows-only-apis.md](windows-only-apis.md)).
- Crystal runtime licensing and deployment differ by version. Check the client's licence before choosing to keep it.

## Done when

- Every report family has a recorded decision.
- Each kept or rebuilt report matches its golden output, or the differences are signed off.
- No ReportViewer or Crystal reference is left in the Linux image, unless the decision says so.

Sources: [ReportViewerCore.NETCore](https://www.nuget.org/packages/ReportViewerCore.NETCore/), [Microsoft Q&A on RDLC in .NET 8 WinForms](https://learn.microsoft.com/en-us/answers/questions/2283533/how-can-i-display-rdlc-reports-in-a-net-8-winforms), [SAP Crystal Reports for Visual Studio](https://pages.community.sap.com/topics/crystal-reports/visual-studio).
