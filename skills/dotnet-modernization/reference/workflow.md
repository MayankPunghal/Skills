# Workflow: one work package from plan to sign-off

## Contents
- Ground rules
- Order of work across a solution or estate
- Steps for one package
- Path for an application already on modern .NET
- Run log and hand-over

## Ground rules

- **One porting engine per project**: the AWS DevTx Version Upgrade Toolkit *or* AWS Transform for .NET, as the
  execution plan says (`port_engine`). Never run both on one project: their outputs conflict and nobody can tell which
  change came from where. Claude is the engine only when neither is available (`port_engine: claude`).
- **Claude cleans up after the engine**, playbook by playbook, for what that engine does not cover. Claude does not
  redo what the engine did; it fixes what the residue scan and the build still report.
- **One database tool**: the DB porting agent, or Claude with the DB porting skills when the DB porting agent is not approved or the
  repository is too complex for it (`db_tool`). Database objects belong to the DB team; the code follows their contract.
- **Work on a branch of a copy the user gives you.** Never push to a client remote, never change the client's original
  checkout, never touch production. Commit per step so each engine's and each playbook's change is its own commit.
- **No hand-coding is planned**: engineers run the tools, approve plans, review and sign off. Claude's own edits are
  reviewed like any engine output.
- Every Markdown output gets an `.html` twin (the scripts do this).

## Order of work across a solution or estate

1. **Shared class libraries first, simplest first.** A library with no project references and few findings ports
   fastest and unblocks everything that references it. Use the assessment's dependency graph; port leaves before the
   projects that depend on them.
2. **Multi-target a shared library while its callers are still on .NET Framework**: `netstandard2.0` when its API
   allows it, else `<TargetFrameworks>net48;net10.0</TargetFrameworks>` with `#if NETFRAMEWORK` only at the seams.
   Remove the old target when the last caller has moved.
3. **`System.Web.HttpContext` inside shared libraries**: do not convert every use by hand across the dependent
   applications. Either take `Microsoft.AspNetCore.SystemWebAdapters` (one `System.Web.HttpContext` type that works
   on both runtimes, so library code compiles unchanged), or move the library to an abstraction (pass the values it
   needs, or `IHttpContextAccessor` in the ASP.NET Core host). Details: [playbooks/systemweb-residue.md](playbooks/systemweb-residue.md).
4. **Applications next**, in the plan's order; a large web application can move incrementally (YARP in front, routes
   moved page by page) instead of in one cut: [playbooks/webforms-ui.md](playbooks/webforms-ui.md).
5. Database work runs beside the port, gated on the DB team's contract.

## Steps for one package

Copy this checklist into the run and tick it off:

```
Package: <name>
- [ ] 1. Read the plan entry (execution-plan.json): engine, playbooks, findings, files
- [ ] 2. Branch + baseline: verify.py baseline; parity.py record (test environment)
- [ ] 3. Engine run (DevTx toolkit OR AWS Transform), until its own build loop stops
- [ ] 4. Residue scan: residue_scan.py; triage by playbook
- [ ] 5. Claude clean-up, one playbook per commit, rebuilding after each
- [ ] 6. Data access: DB porting agent OR Claude with the DB porting skills (dual database)
- [ ] 7. AWS managed-service swaps (playbooks/aws-managed-services.md)
- [ ] 8. Linux container: Dockerfile, health endpoint, stdout logging
- [ ] 9. verify.py target with every gate; fix and rerun until it passes
- [ ] 10. report.py build; reviewer sign-off
```

1. **Plan entry.** `assessment/execution-plan.json` from the modernization-assessment skill lists, per package, every
   finding with its stream (engine, claude, db, aws-native, outside), playbook and files. No plan? Run the residue
   scan on the original and use its playbook column instead.
   - `extra_items` ("Work found in review"): work a reviewer added by hand, each with its stream. Do it with the package.
   - A package in mode `static` has no compiled code: publish its files to S3 + CloudFront, port nothing.
   - The data-access note may name libraries outside the repository (`DEP-OUTSIDE-REPO`). The package cannot build
     on .NET 10 until those libraries are ported or replaced: get their source and port them first, or stop and ask.
2. **Branch and baseline.** `git switch -c modernize/<package>` in the copy. `python scripts/verify.py baseline <sln>`.
   Record goldens with `parity.py record` from a running original (test environment). Log it:
   `report.py log --step baseline --engine human --status done`.
3. **Engine run.** Follow [engines.md](engines.md) for the chosen engine. Commit its output as one commit
   ("port: <engine> run N"). Do not start Claude clean-up while the engine is still iterating.
4. **Residue scan.** `python scripts/residue_scan.py <folder> --db-target <sqlserver|postgresql|dual>`. The report
   groups what is left by playbook and names the DevTx knowledge-base file that covers each rule.
5. **Claude clean-up.** For each playbook with hits, read `playbooks/<id>.md` (and the KB files it names), apply it,
   rebuild, rerun the residue scan, commit ("cleanup: <playbook>"). Stop and ask when a playbook says the change needs
   a decision (keep or retire a feature, a contract change for external callers).
6. **Data access.** The DB porting agent: run its phases and approve its plan; it writes the seams, the Sql / PostgreSql resources and
   the DB contract. Claude with the DB porting skills: follow the same phases and the same checklist
   ([playbooks/raw-sql-and-data-access.md](playbooks/raw-sql-and-data-access.md)).
7. **AWS managed services** (when the plan has them): [playbooks/aws-managed-services.md](playbooks/aws-managed-services.md).
8. **Container.** [playbooks/linux-and-containers.md](playbooks/linux-and-containers.md); DevTx KB 19.
9. **Verify.** `python scripts/verify.py target <sln> --db-target ... --dockerfile Dockerfile --goldens <dir>`.
   Fix what fails (back to the playbook that owns the rule) and rerun until it passes or every remaining hit has a
   written waiver.
10. **Report.** `python scripts/report.py build --dir <folder>/.modernization --plan <execution-plan.json> --package <name>`.

## Path for an application already on modern .NET

An application already on net5.0 or later needs no engine run. Do the Linux readiness check only:

1. `linux_readiness.py <folder>` (337 checks: letter case against the files on disk, separators, Windows-only APIs and
   packages, time zones, culture, encodings, native libraries, file system and process assumptions, IIS hosting, the
   container image; [linux-readiness.md](linux-readiness.md));
2. fix each hit with [playbooks/linux-and-containers.md](playbooks/linux-and-containers.md) and
   [playbooks/time-and-culture.md](playbooks/time-and-culture.md);
3. upgrade the target framework to net10.0 if it is out of support or about to be: .NET 5, 6 and 7 are out of
   support, and .NET 8 and .NET 9 both end support on 10 November 2026, so an app on 8 or 9 is not "done"
   ([breaking-changes.md](breaking-changes.md)). An SDK-style project: change the TFM, update packages, read the
   breaking-change list for each major version crossed. This is usually done by hand; for a large jump an engine can
   do it (DevTx accepts .NET Core 1.0-3.1 and .NET 5-7 sources, AWS Transform .NET Core 3.1 and .NET 5-10);
4. container gate and parity, as above.

## Run log and hand-over

Log every step: `report.py log --dir <folder>/.modernization --step <step> --engine <devtx|aws-transform|claude|db-agent|human> --status done --note "..."`.
Steps: intake, baseline, port, db, cleanup:<playbook>, aws-native:<service>, verify, review, handover.
The execution report (`execution-report.md` + `.html`) is the hand-over: gates, residue left and waived, parity, the
planned items marked done or open, and the run log.
