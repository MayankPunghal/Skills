# 7R decision rules and modernization patterns

Definitions follow AWS Prescriptive Guidance (S10). `classify_apps.py` drafts a recommendation from evidence. **The reviewer must confirm or override every application** in `assessment/decisions.json`; the report labels drafts as "pending review".

## Definitions, as used in these reports

| R | AWS definition | In a .NET Framework estate this usually means |
| --- | --- | --- |
| **Retire** | Decommission or archive | Duplicate or dormant app (the skill flags candidates; the client decides) |
| **Retain** | Keep in the source environment or don't migrate yet | Keep on .NET Framework (on-prem, or on Windows in AWS as part of a hybrid); desktop clients that stay on user machines |
| **Rehost** | Lift and shift without change | Move the Windows VM / IIS site as-is to EC2 Windows (AWS Application Migration Service), or into Windows containers |
| **Relocate** | Hypervisor-level move (e.g. VMware Cloud on AWS) | Whole VMware estate moved unchanged; rare for code-led work |
| **Repurchase** | Replace with another product (SaaS) | Crystal → SaaS reporting, fax → cloud fax, a custom CMS → SaaS |
| **Replatform** | Lift, tinker and shift: some optimisation | Port to .NET 10 on Linux with the **same architecture**: SDK-style projects, ASP.NET Core, Linux containers on ECS Fargate. Most code-led work lands here |
| **Refactor / re-architect** | Modify architecture with cloud-native features | Rewrite the Web Forms UI, WCF → REST/gRPC, MSMQ → SQS, split a monolith, event-driven jobs |

## Draft rules (in order)

1. **Database project** → database assessment ([database-assessment.md](database-assessment.md)).
2. **Desktop (WinForms/WPF)** → **Retain** on Windows (upgrade to .NET 10 Windows Desktop when the back end moves). Option: Refactor to web.
3. **Already modern** → **Replatform** to Linux containers. "Modern" means .NET 5+, not `-windows`, no Windows-bound rule and no High linux-readiness finding. Retarget to .NET 10 if out of support.
4. **Windows-bound blockers** → **Rehost** on Windows now; Refactor the blocking component later. This applies when 3 or more of these are present, or a blocker package plus another: COM, Win32 P/Invoke, Office interop, Crystal, fax, EnterpriseServices, WF, Remoting, MSMQ, unsupported WCF bindings, blocker packages.
5. **Web Forms UI** → **Refactor** when small; **Retain + hybrid** when the app has ≥ 25 KLOC or ≥ 60 pages (thresholds in `data/decision_rules.json`).
6. **WCF service** → **Replatform** with CoreWCF, which keeps the contract. Option: Refactor to REST/gRPC.
7. **Windows service** → **Replatform** to a Worker Service on Linux (ECS service or scheduled task).
8. **Console app** → **Replatform** to a scheduled ECS task (or Lambda if short).
9. **Web Site project (no csproj)** → **Rehost**; convert to a Web Application project before any port.
10. **Anything else on .NET Framework** → **Replatform** to .NET 10 on Linux.

Then the reviewer adjusts using what the rules cannot know: business criticality, release plans, budget, team skills, AWS funding conditions, and client appetite for UI change.

## The hybrid pattern

**When:** one app cannot reasonably leave .NET Framework (Web Forms tightly coupled to `System.Web.UI`, a WF/COM dependency, or the rewrite isn't funded). Other apps that share libraries with it can move.

**How:**
1. **Retain** the blocked app on .NET Framework 4.8.1 on Windows: EC2 Windows with IIS, or ECS Windows containers.
2. **Move shared/common projects to `netstandard2.0`** so both the 4.8.1 app and the .NET 10 apps reference the same build. `classify_apps.py` lists each shared library, its consumers and the plan.
3. If a shared library touches `System.Web`, either move that code back into the web app, or use `Microsoft.AspNetCore.SystemWebAdapters`. It supports shared libraries targeting .NET Standard 2.0.
4. **Replatform** the other apps to .NET 10 on Linux.
5. **Optionally** strangle the retained app later. Put YARP in front of it, port routes one at a time to ASP.NET Core, and share auth/session through System.Web adapters (S9).

**Trade-offs to state in the report:**
- Two runtimes to patch and two deployment models.
- The Windows licence stays for the retained app.
- Shared code is limited to the .NET Standard 2.0 API surface: no `Span`-heavy APIs, no newer BCL features.
- Package versions are constrained to ones that still ship netstandard2.0.
- CI must build both targets.
- The payoff is that the other apps move now and the risky rewrite is deferred, not cancelled.

**Variant:** multi-target (`net48;net10.0`) instead of netstandard2.0. Use it when the library needs framework-specific code paths. It costs more build complexity.

## Incremental vs in-place (large web apps)

Microsoft recommends **incremental migration** (strangler fig with YARP and System.Web adapters) for large production apps, apps with heavy System.Web use, or apps with unknown dependencies. **In-place** suits small apps (S9). Pick incremental when the repository is "active" or "hot" (parallel-development risk) or the app exceeds about 20 KLOC.

## Targets (text used in the report: `data/decision_rules.json`)

| Situation | Target |
| --- | --- |
| Web/API on .NET 10 | Linux containers on Amazon ECS + AWS Fargate (or EKS), behind an ALB. Note: **App Runner is closed to new customers** (S19); consider ECS Express Mode for simplicity |
| Worker / Windows service | .NET Worker Service as an ECS service; timed work through EventBridge Scheduler → ECS task |
| Console / batch | Scheduled ECS task (EventBridge Scheduler) or Lambda when short-running |
| Retained .NET Framework | EC2 Windows (IIS) or ECS Windows containers; consider AWS Elastic Beanstalk Windows platform for simple sites |
| Desktop | .NET 10 Windows Desktop on user machines; Amazon WorkSpaces / AppStream 2.0 if centrally hosted |

## Client scenarios (code side)

| Scenario | What happens per application | When |
| --- | --- | --- |
| `modernize` (default) | The reviewed 7R decision per app: port to .NET 10 for Linux, replace Windows-bound parts | The client wants cost and agility gains |
| `lift-and-shift` | Every server app moves as it is to EC2 with the same OS (Windows to Windows, Linux to Linux); the draft sets Rehost and keeps the modernization path as a future option. Costs AWS-landing, connectivity, configuration, secrets, identity, integration, security and hypervisor findings | The client wants out of the current hosting first and will modernize later. Chosen in the intake questionnaire |
| `windows-rehost` | Every server app moves as-is from on-premises Windows to Windows EC2. Only connectivity, configuration, secrets, identity and integration findings are costed | Fastest exit from the data centre; no code port |

Hosting of the database and operations work are out of scope; the estimate counts coding hours only. The report's scenario table shows both, so the client sees the trade-off between code effort and modernization.
