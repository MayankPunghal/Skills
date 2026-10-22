# Linux readiness

What works on Windows today but breaks, or behaves differently, in a Linux container on AWS. The check (337 checks in 19 areas) belongs to the **linux-readiness** skill, which owns the scanner and its catalogue; this skill runs it through `scripts/linux_readiness.py`, a thin entry point that loads that skill (installed with this one). Check types, area counts, what AWS Transform and DevTx cover, and the sources are in the linux-readiness skill's own reference/linux-readiness.md (run `linux_readiness.py --explain` for one check).

## In an assessment (step 3.2)

```bash
py -X utf8 scripts/linux_readiness.py --all                                   # every inventoried repository
py -X utf8 scripts/linux_readiness.py <repo-root> --out assessment/linux/<repo>  # one repository
py -X utf8 scripts/linux_readiness.py --explain LNX-HOST                        # what a check looks for and the fix
```

- Output per repository: `assessment/linux/<repo>/linux-readiness.json`, `.md` and `.html`. Read-only; secret values are masked in every hit.
- An application already on .NET 5+ gets only this check and no porting engine.

## How the hits are used

- **Findings.** `_findings.load` turns each blocking or warn hit into a finding (one per check and project, rule = the `LNX-` id, source `linux-readiness`): blocking = High, warn = Medium; File system and Encodings go to the `file-handling` category, Time zones and Globalization to `time-culture`, the rest to `linux-readiness`. They are reviewed, costed (`small-change` for blocking, `trivial` for warn in `data/estimation.json`) and planned like any other finding.
- **No double count.** A check whose catalogue `already_in` names a rule of this skill is skipped in a repository where that rule already has a finding; a check marked `COVERED` with no rule named is never a finding. Info hits and waived hits are not costed.
- **Report.** Section 3.3 lists every check that hit (level, what breaks, fix, repositories, applications, hits, examples, and how the estimate counts it: its own finding, within a named rule, waived, or verify); appendix A6 lists the checks a person confirms; appendix A1 links the per-repository reports. The HTML report shows the same table on the Linux tab.
- **Execution.** `data/tool_coverage.json` routes each `LNX-` area to a dotnet-modernization playbook.
