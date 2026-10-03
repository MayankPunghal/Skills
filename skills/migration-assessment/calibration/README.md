# Calibration: drop your sample reports here

Put sample assessment reports (PDF, DOCX, PPTX, XLSX, MD or HTML) in `calibration/samples/`, then ask Claude:

> "/migration-assessment calibrate-report"

or

> "Calibrate the report from the samples"

The procedure (`references/calibration.md`):
1. **Outline each sample.** Run `python scripts/extract_sample.py calibration/samples/<file>`. For PDFs, Claude reads them directly.
2. **Fill in [gap-analysis.md](gap-analysis.md).** For every sample section, table and rating scale, record whether we have it, where, and what to change. Also note what we have that the samples lack (keep it if the engagement brief requires it).
3. **Apply the changes** in the calibration points only:

   | What | Where |
   | --- | --- |
   | Markdown report sections, order, wording | `references/report-template.md` |
   | HTML report sections, order, intros, branding, glossary | `references/html-layout.json` |
   | Tone, spelling, terminology, example paragraphs | `references/style-guide.md` |
   | What each narrative must cover | `templates/narrative/*.md` (new narrative files are picked up automatically) |
   | New checks the samples cover | `scripts/data/rules.json`, `categories.json`, then run `render_references.py` |
   | Effort model, rating thresholds | `scripts/data/estimation.json`, `decision_rules.json` |
   | New table or chart that needs new data | a block function in `build_report.py` plus a component in `build_html_report.py` (rare) |

4. **Rebuild the eShop sample** (`samples/eshop`) or a past assessment and compare it with the sample. Log the change in `references/calibration.md`.

## Confidentiality

Client sample reports stay on this machine. `calibration/samples/` is **excluded from the packaged zip**; only this README and the gap-analysis template ship. Outlines (`*.outline.md`) keep table headers and the first rows only. Delete them if they contain client data you don't want to keep.
