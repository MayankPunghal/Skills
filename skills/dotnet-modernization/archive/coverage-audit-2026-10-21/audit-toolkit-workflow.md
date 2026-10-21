> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Audit toolkit workflow vs skill non-KB docs

agent ae8d4d6732ea7420e

READ-ONLY audit complete. No files created, edited or deleted. No secret values were printed (nuget.config and Dockerfile credentials were placeholders and not reproduced).

Roots: TK = <toolkit> ; SK = skills/dotnet-modernization

A) GAPS (tag | topic | source | what it says | skill file to hold it)

[HIGH] | DevTx deployment prerequisites (Node 22, Yarn 4, CDK >=2.190, Docker, CDK bootstrap, 2 EIPs + 1 VPC, Cognito, Kiro Pro licence, Kiro-supported Region) | TK/docs/src/content/docs/en/deployment/prerequisites.mdx, deployment/setup.mdx, plan-deployment/quotas.mdx | absent from skill | SK/reference/engines.md (Prerequisites), SK/scripts/install_prerequisites.py
[HIGH] | Data egress and residency: Kiro may process data outside the Region; Bedrock summary runs Sonnet 4.5 in us-east-1 | TK/docs/.../plan-deployment/security.mdx; TK/transformer/common/upgrade-report-generator/report-generator.ts (Bedrock call ~L96-290) | skill only says "--trust-all-tools" | SK/reference/engines.md (Watch out), SK/SKILL.md principles
[HIGH] | Unsupported DevTx project types: WinForms, WPF, WF | TK/docs/.../introduction/supported-transformation-types.mdx | engine table defaults to DevTx with no exclusion | SK/reference/engines.md (Choosing)
[HIGH] | Module settings that steer DevTx: solution file (root-level only, validateSolutionFileName in TK/backend/src/security.ts ~L502 rejects paths), build configuration, module path, custom build script | TK/backend/src/module.ts, transform.ts ~L405-411 | engines.md step 1 lists only targetVersion, modulePath, custom script; custom script replaces the build and skips tests (dotnet-q/perform-upgrade.sh ~L466-476 vs ~L719-735) | SK/reference/engines.md
[MED] | Kiro credential handling and fail-fast (Secrets Manager, kiro-cli whoami, ENABLE_Q_CLI exits; .sqlite3 upload) | TK/transformer/common/run.sh; TK/docs/.../settings/manage-system-admin.mdx | absent | SK/reference/engines.md; install_prerequisites.py checks only the binary
[MED] | Iteration artifacts and how to fetch them: iteration-N/ (code-upgrade.log, kiro-output.log, summary.md, report.json, initial-build.log, post-upgrade-verification.log, original-projects/); GET /modules/:id/:iteration/code-upgrade-log | dotnet-q/perform-upgrade.sh ~L870-884; TK/backend/src/api.ts L81 | absent | SK/reference/engines.md; SK/scripts/report.py
[MED] | Confidence score: 40% verification, 30% code size, 20% files, 10% deps; a skipped initial build and a no-test run both score as success | TK/transformer/common/upgrade-report-generator/confidence-calculator.ts | absent | SK/reference/engines.md (say it is not evidence)
[MED] | Preparation phase: line-ending normalisation before the port; Code Analysis via NuGet and GitHub advisory APIs; C# analyzer parses only PackageReference Include+Version and reads only the first csproj | TK/transformer/preparer/src/code-analyzers/language_analyzers/csharp.ts; TK/docs/.../userguide/manage-modules.mdx (step 5) | absent | SK/reference/workflow.md steps 1-2; linux-readiness.md (CRLF)
[MED] | Private NuGet feeds: nuget.config is commented out of the DevTx image (placeholder only) | TK/transformer/dotnet-q/Dockerfile | skill mentions private packages for AWS Transform only | SK/reference/engines.md (DevTx run steps)
[MED] | Source control and main-branch auto-tracking (PAT scopes; re-runs when main changes, 10-900 s polling) | TK/docs/.../userguide/configure-source-control.mdx; manage-system-admin.mdx; TK/backend/src/gitwatcher.ts | absent | SK/reference/engines.md
[LOW] | Cost and throughput (Kiro ~$177/month medium vs AWS Transform ~$308; concurrent jobs by instance size) | TK/docs/.../plan-deployment/cost.mdx, quotas.mdx | absent | SK/reference/engines.md
[LOW] | Toolkit hygiene rules (no TODO/stubs, remove commented-out code and attempt leftovers) | TK/docs/.../userguide/transform-code.mdx (sample prompts) | residue rules do not check commented-out code | SK/reference/verification.md (reviewer list)
[LOW] | Comparator scope: dotnet-proj-comparer.ts diffs PackageReference only, first TFM only; no packages.config or ProjectReference | TK/transformer/common/upgrade-report-generator/dotnet-proj-comparer.ts | absent | SK/reference/verification.md
[LOW] | Pins: Kiro model claude-sonnet-4.6; upgrade-assistant 1.0.518 | dotnet-q/Dockerfile; dotnet-upgrade-assistant/Dockerfile | install_prerequisites installs an unpinned upgrade-assistant | SK/scripts/install_prerequisites.py

B) CONTRADICTIONS (toolkit side first)

1. [HIGH] Solution default. docs manage-modules.mdx (.NET tab): blank means the first .sln is used. Code (dotnet-q and dotnet-upgrade-assistant perform-upgrade.sh, detect_dotnet_projects): blank means scan the tree and upgrade every .csproj/.vbproj. Skill is silent; verify.py target_of errors when a folder has several .sln.
2. [HIGH] Initial build. SK engines.md step 3: initial build skipped for .NET Framework projects. True only for DOTNET_UPGRADE_ASSISTANT_WITH_Q (dotnet-q L459-461). dotnet-upgrade-assistant/perform-upgrade.sh L372-399 runs it unconditionally and returns before the upgrade on failure. The non-AI engine, which DISABLE_AI also selects (transform.ts L661-671), should therefore stop on a .NET Framework solution on Linux. This is from reading the code; I did not run it.
3. [HIGH] Remote writes. SK workflow.md ground rules: "Never push to a client remote". DevTx clones the client repo, pushes <branch>-itr-N and opens PRs (dotnet-q git checkout -B and commit; TK/backend/src/job_complete.ts L223-284). The skill should say the copy's remote must be a sandbox.
4. [MED] Modern .NET path. SK workflow.md: already-on-.NET-5+ apps get a manual TFM upgrade. docs supported-transformation-types.mdx: .NET Core 1.0-3.1 and .NET 5-7 are supported DevTx sources.
5. [MED] Library targets. SK workflow.md step 2: multi-target libraries (netstandard2.0 or net48;net10.0). DevTx forces every project to targetVersion. The netstandard2.0 helper (common.sh determine_target_framework, L23-131) has no callers. verify.py accepts netstandard2.x, which DevTx never produces.
6. [MED] No-test gate. SK verification.md: "not run", never passed. DevTx: no test project gives exit 0, which counts as a pass (engines.md step 7 states this correctly, but it conflicts with the verification rule). Skill should say DevTx "tests green" proves nothing.
7. [MED] Container. SK engines.md table: DevTx "Linux container and health check: yes (KB 19)". The toolkit prompt has no Dockerfile or health step; its gates are build and test only.
8. [MED] Parity and gate reporting. SK verification.md says parity catches XML declaration, encoding and dropped headers, and that parity without goldens is listed. parity.py compares status and parsed body only (replay ~L141-146). verify.py adds no parity row without --goldens and no container row without --dockerfile.
9. [MED] Build arguments and warnings. TK docs say build arguments are used; the scripts export CUSTOM_BUILD_ARGUMENTS and never pass it. DevTx builds use -p:WarningLevel=0 while its prompt asks Kiro to reduce warnings; verify.py counts them, so the numbers are not comparable.
10. [MED] Autonomy. TK q-system-prompt: never ask, pick the safest option, record in summary.md Next steps. SK principles: decisions stop for the user. Skill should say DevTx decisions surface only in summary.md and the diff.
11. [LOW] WCF. dotnet-q prompt: convert WCF to REST or gRPC. SK wcf-services playbook: CoreWCF or SoapCore.

C) About 25 toolkit items checked are covered by the skill (not listed).
