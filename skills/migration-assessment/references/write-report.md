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
   - Cite findings as `F-nnn`. The references are stable until the next build, so rebuild before final proofreading.
   - **Copy numbers from `estimate.json` / the report tables. Never compute or invent them in prose.**
4. **Run `build_report.py` and `build_html_report.py` again, then `verify_report.py`.** The HTML report is what PMs, BAs and the client usually open. Its sections, intros, branding and glossary come from [html-layout.json](html-layout.json). Fix every failure at its source: evidence, review, decisions, narratives, or a secret leak.

## Decisions file

`review_queue.py --decisions` prints the draft decisions to start from. Confirm or change each application, and add a rationale that cites evidence:

```json
{"<app id>": {"r7": "Retain", "target": ".NET Framework 4.8.1 on EC2 Windows (IIS); shared libraries to netstandard2.0",
  "rationale": ["Web Forms UI (184 pages, F-004) tightly coupled to System.Web.UI; rewrite deferred to phase 2.", "..."],
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
- `endpoints.csv`.

The report contains security findings and architecture details. **Share it privately with the client**, never publicly.
