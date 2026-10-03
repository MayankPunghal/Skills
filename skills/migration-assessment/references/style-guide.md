# Report style guide

The tone and wording rules for every client-facing text (narratives, reviewer notes, overrides). Calibrate this file from your own sample reports: replace the defaults below with what the samples do, keep the rules that still apply. The report structure lives in [report-template.md](report-template.md).

## Audience and voice

- **Readers:** the client's CTO or IT head (sections 1, 7, 8), their architects and leads (sections 4–6, 9–10), and the delivery team (appendices).
- **Write as the consultancy** ("we found", "we recommend"). Address the client by name, not as "the customer".
- **Plain, specific, calm.** Say what we found, where, what it means and what to do. No marketing, no superlatives, no fear language. "Blocker" is a defined severity, not a mood.
- **Default spelling: US English.** Change this here if the samples use UK English.

## Evidence rules (non-negotiable)

1. **Every finding cites evidence.** That means `path/to/File.cs:123`, `Package 1.2.3`, or a config key name.
2. **If code cannot show it, it is an open question, not a finding.** Infrastructure, licences, data volumes and runtime behaviour fall here.
3. **Never copy a secret value.** Say "a database password is stored in `Web.config` (`connectionStrings/MainDb`)". Never print the value.
4. **Numbers are ranges with a stated basis.** Write "45–80 person-days (likely 59)", never "about 2 months".
5. **Name tools and versions exactly.** Write ".NET 10 (LTS, supported to 14 Nov 2028)" and "AWS Transform for .NET". Never say "the latest .NET".

## Section-by-section

| Section | Do | Avoid |
| --- | --- | --- |
| Executive summary | 5–8 short paragraphs or bullets: current state, recommended path, effort/timeline range, licensing effect, top 3 risks, next step | Detailed findings, jargon without explanation |
| Architecture | What the applications do (from code), how they connect, which systems sit outside AWS after migration | Repeating the inventory table |
| Database | Recommended target with the evidence that drives it; what blocks Babelfish/PostgreSQL | Recommending Babelfish without a Compass run as next step |
| Application plans | One rationale paragraph per application; options with trade-offs (cost, risk, licence, time) | "Rewrite" as a default; options without trade-offs |
| Risks and questions | Each risk has an owner-type and mitigation; questions are answerable by the client | Generic risks not tied to this estate |
| Testing and merge | QA approach per wave, test data, regression scope, branch strategy tied to repository activity | Promising coverage numbers |
| Cost | Which licences go away (Windows Server, SQL Server) and which stay, with the assumptions; numbers only from client data / AWS OLA | Prices invented from code |

## Terms

- **7Rs (AWS definitions):** Retire, Retain, Rehost, Relocate, Repurchase, Replatform, Refactor/Re-architect. See [seven-rs.md](seven-rs.md). Always state the target with the R ("Replatform to .NET 10 on ECS Fargate").
- **Hybrid:** an application kept on .NET Framework while others move to .NET 10, with shared libraries on .NET Standard 2.0. Always explain the trade-off: two runtimes, Windows licence retained for that app, and the shared code limited to .NET Standard 2.0 APIs.
- **Linux-ready:** builds and runs on Linux with no Windows-only dependency in its code or packages. A Linux-ready app can still have Medium findings.

## Formatting

- **Tables** for anything with more than three items of the same shape. **Bullets** for steps and short lists. **Prose** for reasoning.
- **Refs:** findings are referred to as `F-012`, applications by name, packages by `Id version`.
- **Headings** come from the template. Narratives start directly with content; don't repeat the heading.
