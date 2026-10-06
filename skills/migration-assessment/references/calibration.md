# Calibrating to your sample reports and actuals

The skill is built so that your consultancy's own report style and effort history can be applied without restructuring anything.

| What to calibrate | Where | How |
| --- | --- | --- |
| Section order, headings, fixed wording, which tables appear | `references/report-template.md` (Markdown) and `references/html-layout.json` (HTML: order, titles, intros, components, branding, glossary) | Reorder, rename or drop `{{block:…}}` / `{{narrative:…}}` placeholders; add fixed text (company boilerplate, disclaimers, document control) |
| Tone, spelling, terminology, executive-summary shape | `references/style-guide.md` | Replace the defaults with patterns from the samples (paste 2–3 exemplary paragraphs as models) |
| Narrative prompts | `templates/narrative/*.md` | Adjust the guidance comment in each stub to match the samples' content per section |
| Branding / company name | `assessment.json` → `prepared_by`, `engagement` | Per engagement |
| Severity / confidence definitions | `report-template.md` (2.2) and `review-findings.md` | Keep both identical |
| Effort numbers | `scripts/data/estimation.json` | Adjust from actuals; bump `version` |
| 7R thresholds and target wording | `scripts/data/decision_rules.json` | E.g. Web Forms retain threshold, target platform sentences |
| New checks seen in samples | `scripts/data/rules.json` (+ `categories.json` if a new category) | Add a rule with evidence patterns, then run `render_references.py` |
| New package knowledge | `scripts/data/package_map.json` | Add matches with status, replacement, licence notes |

## Where samples go

Put sample reports in `calibration/samples/` (excluded from packaging), then:
1. `python scripts/extract_sample.py calibration/samples/*` (DOCX/PPTX/XLSX/MD/HTML; PDFs are read with the Read tool) to get compact outlines (headings, word counts, every table's columns, vocabulary).
2. Fill `calibration/gap-analysis.md`: every sample section, table and rating scale → adopt / map / add / skip.
3. Apply changes at the calibration points in the table above (including `references/html-layout.json` for the HTML report). New narrative files in `assessment/narrative/` appear in the HTML report automatically and can be placed in the layout.

## Procedure when the samples arrive

1. Read the samples. List their sections, tables, tone, and how effort and 7R are presented.
2. Map each sample section to a template section (or add one). Keep every section the engagement brief requires; samples may add sections, not drop evidence rules.
3. Edit the template, style guide and narrative stubs.
4. Rebuild a previous assessment (`build_report.py`) and compare it side by side with a sample.
5. If the samples carry effort figures with actuals, calibrate `estimation.json` and record the change below.

## Calibration log

| Date | Change | Evidence |
| --- | --- | --- |
| 2026-10-02 | Initial research baseline (no house samples yet) | references/sources.md |
| 2026-10-06 | Estimation v5: size factor max(1, (repo KLOC / 10)^0.10); redesign work at AI factor 0.70–1.0 instead of 0.30–0.50; "likely" at 50 % for repositories of 100+ KLOC; 8-hour day kept. SmartStore manual likely (code only) 2,583 h to 3,635 h | references/estimation-validation.md (Smartstore port ≈ 3,200–6,600 code hours; COCOMO II; METR; AWS / Google AI studies) |
| 2026-10-05 | Estimation v4: coding hours only, complexity factor, dual / PostgreSQL scenarios, optional modernizations kept outside the total. Testbed FulfillmentHub: 849 h to 203 h likely | AWS Transform for .NET case study (143 KLOC, about 270 h saved); FulfillmentHub testbed |
