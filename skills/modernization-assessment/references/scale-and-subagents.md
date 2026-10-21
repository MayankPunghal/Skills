# Scale: hundreds of repositories, lakhs of lines

The deterministic steps are fast: eShop (16 KLOC) scans in about 2.5 s, and a 5,000-file MVC/SSDT solution in under a minute. The expensive part is judgment (review, decisions, narratives), so that is what gets parallelised.

## Lead agent

1. **Set up** with `setup_assessment.py --roots <all estate folders>`, then run `discover_estate.py` (all repositories, resumable).
2. **Run the mechanical steps over the whole estate.**
   - `scan_repo.py --all` and `map_graphs.py --all` (add `--merge` for cross-repo questions).
   - These are resumable through `assessment/state.json`, and finished repositories are skipped.
   - On very large estates, run them in batches (`--repo`) across sessions.
3. **Plan review batches.**
   - Group repositories by application family (shared libraries, same solution family) using `estate.json` and the hybrid table.
   - Aim for 1–5 repositories or about 150 queued findings per batch (`review_queue.py --repo X | head`).
4. **Spawn one subagent per batch** (only when the user allows subagents; otherwise do batches sequentially). Give it:
   - the workspace path;
   - its repository names;
   - the brief: "Follow references/review-findings.md. Write verdicts to `assessment/reviews/<repo>.json` and manual findings to `assessment/reviews/<repo>.manual.json`. For each application of these repositories, propose a decision in `assessment/decisions.<repo>.json` (same format as decisions.json) with rationale citing finding IDs. Return a 10-line summary: what you confirmed, dismissed, added, and open questions. Do not edit any other repository's files.";
   - read-only access to the client code (never edit client repositories).
5. **Merge and finish.**
   - Merge `decisions.<repo>.json` into `decisions.json`, resolving cross-repository conflicts (shared libraries, hybrid plans).
   - Run `classify_apps.py`, then `estimate_effort.py`.
   - Write the estate-level narratives (executive summary, architecture, application plans, database, cost).
   - Run `build_report.py` and `verify_report.py`.

## Why the outputs merge cleanly

- **One file per repository** for inventory, findings, scan facts, graphs, reviews and decisions. Subagents never write the same file.
- **Stable finding IDs** (`<repo>:<rule>:<project>`), so rescans keep reviews.
- **Aggregation is scripted**: classification, estimate and report read all repositories, and nothing is merged by hand.
- **`state.json`** is written atomically per step. A crashed session resumes with `context.py` and its `NEXT` line.

## Resuming across sessions

Run `context.py` first; it prints counts and the next command. Don't re-read code that already has a verdict.
