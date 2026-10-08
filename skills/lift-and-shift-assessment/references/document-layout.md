# Document layout

The document is a clone of the reference plan the manager supplied (reference migration plan). Headings, order and the plain look do not change; only the content does. `build_doc.py` writes it and `verify_doc.py` checks the headings.

## Contents

- [Sections](#sections)
- [Look](#look)
- [What is ours to propose](#what-is-ours-to-propose)

## Sections

1. Document control: Field/Value table (Engagement, Phase covered, Version, Date, Status, Created By, Evidence convention); 1.1 Scope box (IN SCOPE, environment table, Optional IN Scope, NOT in scope, Explicit carry-forward statement).
2. Executive summary: What Phase 1 achieves; What Phase 1 deliberately does not do.
3. 7R disposition: workloads (WL-nn = deployable x environment), Rs table, NOTE.
4. Current state: solutions, external integrations and licensed components, Windows-only dependencies carried forward unchanged.
5. Prerequisites: 5.1 Make the build reproducible; 5.2 Secrets into Secrets Manager; 5.3 Connection-string indirection; 5.4 Framework version. "HARD BLOCKER" is added only when the data shows a blocker.
6. Migration approach: Option A (MGN), Option B (rebuild on fresh AMI), selected mechanism per workload.
7. Target architecture on AWS Windows; 7.1 AWS Secrets Manager integration.
8. Migration execution per workload: 8.1 web deployables, 8.2 services and jobs, 8.3 sequencing dependency.
9. Wave plan and cutover: Wave / Content / Entry criteria / Exit criteria / Rollback.
10. Effort estimate and timeline: App-side work / Hours, contingency, total in hours and dev-days.
11. Validation and testing: executed by the party named in the intake.

## Look

Plain, like the reference: Arial, black headings (title regular weight), light-grey table header, thin grey borders, bullets, bold lead-ins. No colours, banners, footers or decoration.

## What is ours to propose

Waves, target architecture and execution steps are not left to DevOps. The skill proposes them (rehearsal wave on the smallest solution, then batches of at most 10 workloads; MGN unless the intake says otherwise; standard Windows EC2 architecture) and labels them INFERRED. DevOps answers in the intake replace the assumption.
