# Intake questionnaire

The questions live in `scripts/data/intake.json`: each has an id, plain wording, options, a `stage`, an optional `when` / `when_found` condition and an `affects` line naming the document section it feeds. Ask them with the multiple-choice tool, then `intake.py --answers '<json>'` (JSON keyed by question id). `intake.py` lists what is pending; the tools named in SKILL.md refuse to run while a gating question is open.

Rules: all pending questions are asked (100% coverage, no assumptions); "unknown" is recorded only when the user says it and prints as UNKNOWN; `when_found` questions are asked only when the scan or build found the matching rule ids or signal (build-blocked, inbound-public, licensed-components, rekey-integrations, scheduled-jobs).

| Stage | Questions (ids) | Feed |
|---|---|---|
| before_scan: document | engagement_title, phase_covered, prepared_by | document control |
| before_scan: scope and work | scope_confirm, scope_exclusions, work_items, retarget_to, regression_tests, estimate_basis | which solutions and lines are priced; section 5.4 |
| before_scan: environments | environments, environments_differ, server_list (+detail), current_hosting, windows_versions | workloads, 1.1 table, 3, 6 |
| before_scan: AWS and waves | aws_landing_zone, aws_connectivity, aws_region, database_location, devops_mechanism, wave_strategy, wave_detail, maintenance_windows, hypercare_days, parallel_run_days, devops_notes | 6, 7, 9 |
| before_scan: CI/CD and secrets | ci_platform_today, build_agent, artifact_format, ci_platform_target, pipeline_scope (+solutions), secrets_injection, secrets_rotation, secrets_owner, existing_vault | 5.1, 5.2, 7.1, pipeline lines |
| before_scan: testing | test_environment, smoke_tests, testing_by, cutover_support_hours | 8, 11 |
| after_scan (when found) | ad_domain, mail_relay, file_shares, public_endpoints, ip_allowlists, licence_terms, machine_bound, job_schedules, credential_rotation_owner, private_feeds | 4, 5.1 to 5.3, 7, 8.2 |
| after_build (when blocked) | missing_references | 5.1 |

Per solution settings, when a solution has its own environments: `intake.py --solution <repo>/<solution> --environments "dev, prod" [--ci yes|no|unknown] [--note TEXT]`. Changing an environment list clears the confirmation.

Status commands: `intake.py` (show and pending), `--confirm-environments`, `--finalize "<who>"` (refused with pending questions or unconfirmed environments), `--reopen` (back to DRAFT).

Do not ask the questions that belong to other teams (database engine, VPC design, DNS cutover mechanics). The waves, architecture and execution steps are our proposal, and the answers above only steer them.
