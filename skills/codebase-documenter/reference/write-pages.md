# write-pages — narrative documentation from verified notes

Load [quality-standards.md](quality-standards.md) and [page-patterns.md](page-patterns.md) first.

## Steps per section

1. Open the scaffold pages of the section (`docs/_src/<section>/`); each has an H1, `<!-- nav: N -->`, purpose and outline headings marked `<!-- docs:todo -->`.
2. Write from the research notes. Replace every `docs:todo` marker; keep, rename, add or remove headings as the content needs.
3. Link every named item with a tag: `[[table:Order]]`, `[[proc:Order_Calculate_Totals]]`, `[[cls:OrderService]]`, `[[mth:OrderService.Submit]]`, `[[fn:calculate_tax]]`, `[[prj:Orders.Api]]`, `[[pkg:Newtonsoft.Json]]`, `[[ep:GET /api/orders/{id}]]`, `[[err:OrderWorkflow-57]]`, `[[ctl:Order]]`, `[[act:Order.Approve]]`, `[[enum:LineType]]`, `[[seed:Order_Status]]`, `[[role:Administrator]]`, `[[js:app.js]]`, `[[rpt:Sales_Summary]]`, `[[mod:src/app.py]]`, `[[cfg:Billing-Url]]`, `[[page:security/findings.md#sec-02|SEC-02]]`. `Name|label` shows a different label.
   Counts taken from the generated reference are tags too: `[[n:db-access.sites]]`, `[[n:configuration.keys]]`, `[[n:views.screens]]`, `[[n:sql-<database>.procedure]]` (every key is in `docs/agent/stats.json`). A typed "455 call sites" is wrong the next time the code or a scanner fix changes the count; the tag is resolved on every build, and an unknown key fails as `UNRESOLVED n`. `verify_docs.py` prints a NOTE for typed counts that equal a generated number.
4. New module pages: add `docs/_src/modules/<module>.md` (or a folder with `index.md` for big modules) — the nav is regenerated automatically; order with `<!-- nav: N -->`.
5. After each section: `python <skill>/scripts/build_site.py --skip-adapters --no-site`. Fix every `UNRESOLVED` (wrong name, wrong kind, or the item is not in the reference → check the code, then the adapter).
6. Record any fact corrected while writing (`research_notes.py correct "…"`) and fix the note too.

## Section order that works

1. Getting started (overview, users & roles, navigation) — sets vocabulary.
2. Architecture (C4 context → containers → components; request lifecycle; composition and run-time wiring; data access; configuration; jobs). Projects, layers and packages come from the generated `dependencies.md`: summarise and link, don't retype. Write `architecture/dependency-injection.md` from the generated `dependency-injection.md` and the notes (pattern in [page-patterns.md](page-patterns.md#composition-and-run-time-wiring-architecturedependency-injectionmd)); every module page then says, for its own services, what runs behind each interface, message and event.
3. Business modules (one page per module; sub-pages for engines, approvals, imports, outputs).
4. Workflows (end-to-end sequence diagram, state machines for every status set, approval flow, fulfilment) and one business-flow spec per important journey ([flows.md](flows.md)).
5. Integrations (one page per external system; inbound API from `endpoints.md`; machine endpoints + complete anonymous list).
6. Data (data model with ER diagram, polymorphic / inheritance patterns, databases, codes & statuses).
7. Shared libraries (base classes & helpers, services map, front-end scripts).
8. Operations (build, environments, deployment, monitoring, constraints, other projects, testing). Write the **runbook** from `build-and-run.md` (commands in the order a new engineer runs them) plus the error catalogue for troubleshooting; write **testing** from `test-map.md` (what is reached, the biggest untested areas), checking each gap in code before calling it one.
9. Security (authentication, authorisation, findings register SEC-nn).
10. Appendices (glossary, defects DEF-nn / TD-nn, document control incl. agent access; coverage and code map are generated).

Write the security findings and defects registers **from the defect lists in the notes**, each verified once more in code before it gets an id. High-severity wiring findings (captive dependency, missing registration) from `dependency-injection.md#di-findings` are checked in code and, when real, become DEF-nn entries linked with `[[di:find-N]]`. The same goes for `endpoints.md#security-review` and `views-and-pages.md#ui-anonymous`: they are candidates, not findings. Read each group in code (does the action really change data, does a helper return sensitive data, does the anonymous page check the user itself) and turn the real ones into SEC-nn entries; group repeated cases (for example "521 helpers exposed as actions") into one entry with the count and examples instead of one entry each.
