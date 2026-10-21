# Verification gates

A package is done when `scripts/verify.py target` passes, not when the engine says so. Run `verify.py baseline` on the
original before any change, so "no worse than before" has a reference. A gate that did not run stays in the report as
"not run" with its reason, so the report never hides what was not proven.

## Contents
- The gates
- Waivers
- Parity: recording and replaying
- Output-diff gate: console apps, services, workers, batch jobs
- Linux readiness gate
- Database gate (manual)
- Optional gates
- What a reviewer checks that the gates cannot

## The gates

| Gate | Command (verify.py runs it) | Passes when | Fails because, usually |
|---|---|---|---|
| baseline | MSBuild (via vswhere) or `dotnet build`, then `dotnet test` | recorded, never fails | the original build needs Visual Studio Build Tools: record it from the original CI instead |
| build | `dotnet build -c Release` | exit 0; every project targets the plan's framework (`--tfm net8.0`, `net10.0` or `both`, the default), or netstandard2.0 for a library still shared with .NET Framework callers; no NU1701, NU1605 or NU1608 in the build log | a reference still built for .NET Framework, a package with no build for the target, a package downgrade (NU1605), a package restored from .NET Framework (NU1701) |
| tests | `dotnet test -c Release --no-build` | exit 0; "not run" when there is no test project (never counted as passed). Tests an engine generated (AWS Transform in Visual Studio does not validate them) count only after a person has reviewed them | behaviour changed; time zone or culture in assertions; a generated test that asserts the new behaviour instead of the old |
| residue | `residue_scan.py` | no blocking hit left unwaived. Scans C# and VB, markup (`.cshtml`, `.razor`, `.aspx`, `.ascx`, `.master`, `.asmx`, `.svc`, `.ashx`, `.asax`), `wwwroot` (`.html`, `.htm`, `.js`), project and config files, and `.sql` files | the engine left System.Web, CallContext, packages.config, `.aspx` files, Windows paths, T-SQL in a SQL file |
| linux readiness | `linux_readiness.py` (run by verify.py) | no blocking hit unwaived | see [linux-readiness.md](linux-readiness.md) |
| container | `docker build`, `docker run`, GET the health path for 60 s | HTTP 200 | missing native library (libgdiplus, ICU), a path with a backslash, the app writing under its own folder, port not 8080 |
| parity | `parity.py replay` | every recorded request matches after masking, and the raw response matches (charset in Content-Type, XML declaration, byte order mark) | a changed default (JSON casing, date format, XML declaration or encoding, charset), a dropped header |
| outputs | compares the files each case writes with the goldens | every case exits with the golden's code, and every output matches the golden (exact bytes, then after the masks) | a changed number format or culture, line endings, a file name, a log line that moved |
| database | manual, not run by the script | see the Database gate section | not applicable to a SQL Server target |
| security | optional: `dotnet list package --vulnerable --include-transitive` (`--security`) | no project lists a vulnerable package | a package with a published advisory; an old version kept by the port |
| performance | optional, manual, not run by the script | see Optional gates | not run |

`verify.py target` exits 1 when any gate that ran failed, and also when no gate ran at all. The report lists every gate,
including the ones "not run", with the reason. `--skip` names gates to leave out; a skipped gate still appears as "not run".

## Waivers

A blocking residue or Linux readiness hit that must stay (for example `.asmx` kept behind SoapCore on purpose) gets a
waiver in a JSON file passed with `--waivers`:

```json
[{"rule": "WEB-FORMS-FILE", "path": "legacy/**", "reason": "kept for one release, removed in wave 3", "by": "tech lead"}]
```

Waived hits stay in the report, marked waived. No waiver without a reason and a name.

## Parity: recording and replaying

1. Pick one request per request type (and per page for UI smoke tests): the assessment's contract list
   (`contracts.request_types`, controllers, handlers) is the checklist.
2. `parity.py record` against the original in a test environment, never production. Store the goldens with the branch.
3. Masks: GUIDs, timestamps and session-like tokens are masked by default. Add `masks.json` entries for anything else
   that changes per call (`{"regex": "...", "why": "..."}`, or `{"xml_path": "ElementName"}` / `{"json_key": "name"}`
   to ignore a value by name).
4. `path_new` in a request entry when the port moved the route (an `.ashx` handler became an endpoint): the same body
   goes to the new path, which keeps the comparison honest.
5. The raw response is compared as well: the charset in `Content-Type`, the XML declaration (version and encoding) and a
   leading byte order mark. A change there is a difference even when the parsed body matches. Sign it off or fix it.
6. A difference is a bug until someone signs it off as intended.

## Output-diff gate: console apps, services, workers, batch jobs

These have no HTTP endpoint to replay. Their check is: fixed inputs go in, and the files or records they write are compared
before and after the port.

1. Write `cases.json`: a list of cases. Each case has a `name`, a `cmd` (an argument list; its first element may be a
   program inside the solution folder), optionally `cwd` and `stdin_file` (both relative to the solution folder),
   `timeout` in seconds, and `outputs` (the files the case writes, relative to `cwd`).

```json
[{"name": "nightly-import", "cmd": ["dotnet", "bin/Release/net10.0/Importer.dll", "inputs/orders.csv"],
  "outputs": ["out/orders.csv", "out/import.log"]}]
```

2. Record once, against the original build (its cases must run the original program):
   `python scripts/verify.py record-outputs <original-folder> --outputs cases.json --output-goldens goldens/outputs`.
   Store the goldens with the branch, as for parity.
3. Compare on the port: `python scripts/verify.py target <solution> --outputs cases.json --output-goldens goldens/outputs`.

The comparison checks the exit code first, then each output: identical bytes pass; otherwise the output passes when it is
equal after the parity masks (add `--masks` for more); otherwise the first differing line is reported. A log line with a
time in it needs a mask in `masks.json`, not an edited golden.

## Linux readiness gate

`verify.py` runs `linux_readiness.py` (337 checks, [linux-readiness.md](linux-readiness.md)) as the `linux readiness` gate:
no blocking hit may stay open unless it is waived. The residue scan's `linux` group is a smaller, older subset; the
Linux readiness check is the one that gates. For an application already on modern .NET, run only this check:

```bash
python scripts/verify.py target <folder> --linux-only
python scripts/linux_readiness.py <folder> --gate
```

The container gate is the real proof: build and run the Linux image, then replay parity against it.

## Database gate (manual)

`verify.py` does not run a database gate. `--db-target dual` selects the residue rules for both database paths; it does
not build or test twice. The report lists the database gate as "not run" with the reason. When the database moves to
PostgreSQL (dual database), run these checks by hand in the test environment and keep the results with the branch:

1. Tests on each engine: run `dotnet test --no-build` once with the SQL Server setting and once with the PostgreSQL
   setting (the provider or connection setting the port reads, for example `Data:Provider`), and record both results.
2. Every procedure in the DB contract exists on PostgreSQL non-prod with the agreed name, call form and argument order.
3. Procedures that return rows are functions (`RETURNS TABLE` / `SETOF`) or procedures with `INOUT refcursor`, and the
   code fetches the cursor inside the same transaction.
4. The data-access parity run (read paths compared per procedure on both databases) passes.
5. The SQL Server path still passes its own tests: dual database means both work.

## Optional gates

- **Performance (manual, not run by verify.py).** Run a load test with k6 or JMeter against the container: the health
  path and the busiest parity requests, with the same request mix as the original. Record p95 latency and error rate next
  to the baseline. The acceptable margin is the team's decision.
- **Security.** `verify.py target --security` runs `dotnet list package --vulnerable --include-transitive` and fails when
  any project lists a vulnerable package. It needs NuGet access. Static analysis (SAST) is not run here; record its result
  in the report by hand.

## What a reviewer checks that the gates cannot

- business-time logic now that containers run UTC;
- anything waived;
- security changes: machine key / cookie compatibility, secrets moved out of config, TLS;
- the engine's diff for deleted behaviour (catch blocks emptied, features stubbed with `NotImplementedException`,
  `#if NETFRAMEWORK` branches that hide code from the new build);
- leftovers from the engine or the clean-up: commented-out code, and `TODO`, `FIXME` or `HACK` comments that the port added.
