# Verification gates

A package is done when `scripts/verify.py target` passes, not when the engine says so. Run `verify.py baseline` on the
original before any change, so "no worse than before" has a reference.

## Contents
- The gates
- Waivers
- Parity: recording and replaying
- Linux readiness gate
- Database gate
- What a reviewer checks that the gates cannot

## The gates

| Gate | Command (verify.py runs it) | Passes when | Fails because, usually |
|---|---|---|---|
| baseline | MSBuild (via vswhere) or `dotnet build`, then `dotnet test` | recorded, never fails | the original build needs Visual Studio Build Tools: record it from the original CI instead |
| build | `dotnet build -c Release` | exit 0 and every project targets net10.0 (or netstandard2.0 for a library still shared with .NET Framework callers) | a reference still built for .NET Framework, a package with no .NET 10 build |
| tests | `dotnet test -c Release --no-build` | exit 0; "not run" when there is no test project (never counted as passed) | behaviour changed; time zone or culture in assertions |
| residue | `residue_scan.py` | no blocking hit left unwaived | the engine left System.Web, CallContext, packages.config, `.aspx` files, Windows paths |
| container | `docker build`, `docker run`, GET the health path for 60 s | HTTP 200 | missing native library (libgdiplus, ICU), a path with a backslash, the app writing under its own folder, port not 8080 |
| parity | `parity.py replay` | every recorded request matches after masking | a changed default (JSON casing, date format, XML declaration, encoding), a dropped header |

Exit code 1 from `verify.py target` when any gate that ran failed. Tests "not run" and parity without goldens are listed,
so the report shows what was not proven.

## Waivers

A blocking residue hit that must stay (for example `.asmx` kept behind SoapCore on purpose) gets a waiver in a JSON
file passed with `--waivers`:

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
5. A difference is a bug until someone signs it off as intended.

## Linux readiness gate

`verify.py` runs `linux_readiness.py` (240 checks, [linux-readiness.md](linux-readiness.md)) as the `linux` gate: no
blocking hit may stay open unless it is waived. The residue scan's `linux` group is a smaller, older subset; the
Linux readiness check is the one that gates. For an application already on modern .NET, run only this check:

```bash
python scripts/verify.py target <folder> --linux-only
python scripts/linux_readiness.py <folder> --gate
```

The container gate is the real proof: build and run the Linux image, then replay parity against it.

## Database gate

When the database moves to PostgreSQL (dual database):

- every procedure in the DB contract exists on PostgreSQL non-prod with the agreed name, call form and argument order;
- procedures that return rows are functions (`RETURNS TABLE` / `SETOF`) or procedures with `INOUT refcursor`, and the
  code fetches the cursor inside the same transaction;
- the data-access parity run (read paths compared per procedure on both databases) passes;
- the SQL Server path still passes its own tests: dual database means both work.

## What a reviewer checks that the gates cannot

- business-time logic now that containers run UTC;
- anything waived;
- security changes: machine key / cookie compatibility, secrets moved out of config, TLS;
- the engine's diff for deleted behaviour (catch blocks emptied, features stubbed with `NotImplementedException`,
  `#if NETFRAMEWORK` branches that hide code from the new build).
