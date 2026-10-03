# write-pages — narrative documentation from verified notes

Load [quality-standards.md](quality-standards.md) and [page-patterns.md](page-patterns.md) first.

## Steps per section

1. Open the scaffold pages of the section (`docs/_src/<section>/`); each has an H1, `<!-- nav: N -->`, purpose and outline headings marked `<!-- docs:todo -->`.
2. Write from the research notes. Replace every `docs:todo` marker; keep, rename, add or remove headings as the content needs.
3. Link every named item with a tag: `[[table:Order]]`, `[[proc:Order_Calculate_Totals]]`, `[[cls:OrderService]]`, `[[fn:calculate_tax]]`, `[[ctl:Order]]`, `[[act:Order.Approve]]`, `[[enum:LineType]]`, `[[seed:Order_Status]]`, `[[role:Administrator]]`, `[[js:app.js]]`, `[[rpt:Sales_Summary]]`, `[[mod:src/app.py]]`, `[[cfg:Billing-Url]]`, `[[page:security/findings.md#sec-02|SEC-02]]`. `Name|label` shows a different label.
4. New module pages: add `docs/_src/modules/<module>.md` (or a folder with `index.md` for big modules) — the nav is regenerated automatically; order with `<!-- nav: N -->`.
5. After each section: `python <skill>/scripts/build_site.py --skip-adapters --no-site`. Fix every `UNRESOLVED` (wrong name, wrong kind, or the item is not in the reference → check the code, then the adapter).
6. Record any fact corrected while writing (`research_notes.py correct "…"`) and fix the note too.

## Section order that works

1. Getting started (overview, users & roles, navigation) — sets vocabulary.
2. Architecture (C4 context → containers → components; request lifecycle; data access; configuration; jobs).
3. Business modules (one page per module; sub-pages for engines, approvals, imports, outputs).
4. Workflows (end-to-end sequence diagram, state machines for every status set, approval flow, fulfilment).
5. Integrations (one page per external system; inbound API; machine endpoints + complete anonymous list).
6. Data (data model with ER diagram, polymorphic / inheritance patterns, databases, codes & statuses).
7. Shared libraries (base classes & helpers, services map, front-end scripts).
8. Operations (build, environments, deployment, monitoring, constraints, other projects, testing).
9. Security (authentication, authorisation, findings register SEC-nn).
10. Appendices (glossary, defects DEF-nn / TD-nn, document control incl. agent access; coverage and code map are generated).

Write the security findings and defects registers **from the defect lists in the notes**, each verified once more in code before it gets an id.
