# Linux readiness

What works on Windows today but breaks, or behaves differently, in a Linux container on AWS. The check (337 checks in 19 areas) belongs to the **linux-readiness** skill, which owns the scanner and its catalogue; this skill runs it through `scripts/linux_readiness.py`, a thin entry point that loads that skill (installed with this one). Check types, area counts, what AWS Transform and DevTx cover, and the sources are in the linux-readiness skill's own reference/linux-readiness.md (run `linux_readiness.py --explain` for one check).

## In execution

| Situation | Run | Why |
|---|---|---|
| Application already on .NET 5+ | **Only this check** (no porting engine) | The port is done; Linux is the remaining risk |
| After the porting engine and the Claude clean-up | `verify.py` runs it as the `linux` gate | Catches what the engine left and what the port introduced |
| Before the first container build | With `--gate` | Exit 1 while a blocking hit is open |

```bash
python scripts/linux_readiness.py <repo-or-solution-folder> [--out <dir>] [--waivers waivers.json] [--gate]
python scripts/linux_readiness.py <folder-or-Dockerfile> --dockerfile-only [--gate]
python scripts/linux_readiness.py --explain [LNX-ID | id prefix | words]
```

- Each hit maps to a playbook: `linux-and-containers`, `windows-only-apis`, `config-and-secrets`, `startup-and-middleware`, `time-and-culture` (and `http-handlers-and-modules`, `wcf-services`, `reporting`, `auth`, `logging`, `background-work`, `build-and-packages` for their areas).
- Read-only; secret values are masked in every hit. Waivers: `[{"rule": "LNX-...", "path": "glob", "reason": "...", "by": "...", "expires": "YYYY-MM-DD"}]`.
