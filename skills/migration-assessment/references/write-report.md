# Writing the report

The report is assembled by `build_report.py` from three things:
- the **template**, [report-template.md](report-template.md);
- **generated blocks**: tables, diagrams, findings, estimate, appendices;
- **narratives** you write in `assessment/narrative/*.md`. Each stub explains what belongs in it.

Write per [style-guide.md](style-guide.md).

## Order of work

1. **Gather facts first.** Make sure findings are reviewed, decisions confirmed (`decisions.json`), and `estimate_effort.py` has been rerun.
2. **Run `build_report.py` once** to see the generated sections. The narratives refer to them.
3. **Write the narratives** in this order: `architecture`, `dependencies`, `database`, `application-plans`, `testing-and-merge`, `risks-and-questions`, `cost`, and **`executive-summary` last**.
   - Delete each stub's `PENDING:` line.
   - Use `graphify explain "<entry class>" --graph …` and the dependency table to describe what each application does. Read entry points (controllers, pages, service contracts, `Main`), not whole folders.
   - Cite findings with the tag `{{f:RULE-ID}}` (or `{{f:RULE-ID@project}}`), never a raw `F-nnn`: F-numbers are positions in the sorted findings and move on every rescan. The build turns tags into the current numbers; `verify_report.py` fails on raw numbers and on tags that match nothing.
   - **Copy numbers from `estimate.json` / the report tables. Never compute or invent them in prose.**
   - **Every factual sentence must be checkable in the code or a generated table.** Before writing a count (pages, registrations, KLOC, calls), a technology label (EDMX, WCF, Hangfire) or "no X found", open the evidence. Say "the scanner found" rather than "there is no" when absence is only what the scan saw. If you cannot verify a claim, leave it out or turn it into an open question. A confident wrong sentence costs more trust than a missing one.
   - Rerun the narratives' facts after a rescan: new applications, renamed findings and changed counts make old prose wrong.
4. **Run `build_report.py` and `build_html_report.py` again, then `verify_report.py`.** The HTML report is what PMs, BAs and the client usually open. Its sections, intros, branding and glossary come from [html-layout.json](html-layout.json). Fix every failure at its source: evidence, review, decisions, narratives, or a secret leak.

## Decisions file

`review_queue.py --decisions` prints the draft decisions to start from. Confirm or change each application, and add a rationale that cites evidence:

```json
{"<app id>": {"r7": "Retain", "target": ".NET Framework 4.8.1 on EC2 Windows (IIS); shared libraries to netstandard2.0",
  "rationale": ["Web Forms UI (184 pages, {{f:WEB-WEBFORMS-UI}}) tightly coupled to System.Web.UI; rewrite deferred to phase 2.", "..."],
  "options": ["Refactor UI to Blazor with AWS Transform (+120-180 p-d)"], "by": "reviewer", "date": "2026-10-02"}}
```

## Deliverables

All in `assessment/report/`:
- `<Client>-AWS-Migration-Assessment.html`: interactive, single file, works offline (search, filters, charts, CSV downloads, print to PDF);
- `<Client>-AWS-Migration-Assessment.md` (convert with pandoc/Word/Docs if a document is needed);
- `findings.csv` / `findings.json` (spreadsheet or deck);
- `applications.csv`;
- `packages.csv`;
- `open-questions.csv`, with an empty answer column for the client;
- `endpoints.csv`;
- `network-allowlist.csv`: one row per outbound destination (host, port, protocol, internal / external, applications, the config key or literal that names it, what the AWS VPC needs) and per inbound listener. The network team can use it for security groups, NAT egress, VPN routes and partner allow-lists. The same table is in section 4.4 and on the HTML **Third-party & integrations** tab. Each destination has a role (SMTP, SFTP, SMB file share, LDAP, report server, session state server and others) with what that role needs on AWS; drive letters other than `C:` are listed under the table.
- `scheduled-jobs.csv`: every scheduled or background job found (scheduler, schedule in plain words, what it runs, the config keys or file that set it, the application, Windows-only or not, the AWS equivalent). The same table opens the HTML **Hosting** tab and follows the network allow-list in section 4. Jobs started from outside the repository (Task Scheduler on a server, a SQL Agent job created by hand) cannot be seen: keep the open question about scheduled tasks.
- Section 8.8 **How the estimate was calculated** is generated (`{{block:methodology}}`) from `estimate.json`; do not paraphrase it in a narrative.

The allow-list comes from the codebase-documenter's `network_endpoints.py`. It covers URL literals in code, config, scripts and front end; bare host settings (`Smtp:Host`, `Kafka:BootstrapServers`); connection-string servers and ports; WCF client endpoints; UNC shares (SMB 445); and listeners (launchSettings, Kestrel, `ASPNETCORE_URLS`, Dockerfile `EXPOSE`, docker-compose, WCF services). Destinations built at run time are invisible. The block counts the outbound call sites with no key or literal next to them: ask the client where those addresses come from.

The report contains security findings and architecture details. **Share it privately with the client**, never publicly.
