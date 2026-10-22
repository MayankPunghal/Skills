# 7R decision rules and modernization patterns

Definitions follow AWS Prescriptive Guidance (S10). `classify_apps.py` drafts a recommendation from evidence. **The reviewer must confirm or override every application** in `assessment/decisions.json`; the report labels drafts as "pending review".

## Contents
- Definitions, as used in these reports
- Draft rules (in order)
- Every project: class libraries, tests and difficulty
- Migration order and blast radius
- The hybrid pattern
- Incremental vs in-place (large web apps)
- Targets (text used in the report: `data/decision_rules.json`)
- Client scenarios (code side)
- Decision tree (AWS strategies applied to one .NET application)
- Justifying each R in the report

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
3. **Already modern** → **Replatform** to Linux containers. "Modern" means .NET 5+, not `-windows`, no Windows-bound rule, no High linux-readiness finding, and a target still in support on the report date. .NET 8 and .NET 9 both reach end of support on 10 Nov 2026 (S4), so an app on either is retargeted to .NET 10 in the port (finding `INV-TFM-SUPPORT`, which turns from "ending soon" to "out of support" on the end date; the 7R rationale names the date). Retarget to .NET 10 if out of support.
4. **Windows-bound blockers** → **Rehost** on Windows now; Refactor the blocking component later. This applies when 3 or more of these are present, or a blocker package plus another: COM, Win32 P/Invoke, Office interop, Crystal, fax, EnterpriseServices, WF, Remoting, MSMQ, unsupported WCF bindings, blocker packages.
5a. **Web Forms project with a token UI** (≤ 3 pages and markup under 5% of its hand-written lines: a gateway or service with a status page) → **Replatform**; the page or two are rewritten inside the port (`webforms_token_ui` in `data/decision_rules.json`).
5. **Web Forms UI** → **Refactor** when small; **Retain + hybrid** when the app has ≥ 25 KLOC or ≥ 60 pages (thresholds in `data/decision_rules.json`).
6. **WCF service** → **Replatform** with CoreWCF, which keeps the contract. Option: Refactor to REST/gRPC.
7. **Windows service** → **Replatform** to a Worker Service on Linux (ECS service or scheduled task).
8. **Console app** → **Replatform** to a scheduled ECS task (or Lambda if short).
9. **Web Site project (no csproj)** → **Rehost**; convert to a Web Application project before any port.
10. **Anything else on .NET Framework** → **Replatform** to .NET 10 on Linux.

Then the reviewer adjusts using what the rules cannot know: business criticality, release plans, budget, team skills, AWS funding conditions, and client appetite for UI change.

## Every project: class libraries, tests and difficulty

The rules above classify deployables. `_projects.py` (run by `build_report.py`; output `assessment/report/projects.json`) gives **every** project its own 7R, so shared and class libraries are planned too. In order:

1. A project that is an application's entry project takes that application's decision.
2. **Test project** → Replatform with the projects it tests.
3. **Database project** → Retain (the database assessment decides).
4. **Library nothing references** (no project, DLL or deployable uses it) → **Retire?**, for the reviewer to confirm.
5. **Already modern** (.NET 5+) → Retain if in support, else Replatform (retarget).
6. **Windows-bound code** (COM, P/Invoke, Office interop, Crystal, registry ...) → Refactor: isolate it behind an interface.
7. **System.Web in a library** → Refactor: move the HttpContext / session / cache use to the caller.
8. **Library shared with an app that stays on .NET Framework** (hybrid plan, or a desktop consumer) → Replatform to `netstandard2.0`.
9. Otherwise → Replatform to .NET 10.

A reviewer decision overrides any of these: key `project:<repo>:<path>` in `assessment/decisions.json`.

**Difficulty** (Easy / Medium / Hard) says how hard the port is, independent of the 7R:

| Base | Kinds |
| --- | --- |
| Easy | Web API, class / .NET libraries, console, worker, already-modern projects, tests, database projects |
| Medium | Service hosts (WCF, Windows service), MVC UIs |
| Hard | Web Forms and desktop UIs (rewritten, not ported) |

One level up for a Windows-bound Blocker / High finding (else for any other Blocker); one more for more than 50,000 lines. A Web Forms project with a token UI counts as an API.

## Migration order and blast radius

- **Dependencies** come from project references, DLL references matched to assemblies built elsewhere in the estate ("DLL from <repo>"), and project edges in the code graph.
- **Waves:** a project moves in the wave after everything it depends on. Projects in a dependency cycle share a wave and move together.
- **Order inside a wave:** libraries before deployables, the most-used first, then the easiest.
- **Blast radius:** the projects that depend on it, directly or through others, the deployables to retest, and the uses of its code from other files (`file_impact` in the code graph). High at 3 or more dependent projects or deployables; Medium with any dependent, or 20 or more uses.
- **Pilot:** the deployable that is easiest, needs the easiest projects first, has the smallest blast radius and is at least 1,000 lines. It proves the build, container, deploy and test pipeline.

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
| Desktop | .NET 10 Windows Desktop on user machines; Amazon WorkSpaces / Amazon WorkSpaces Applications (formerly AppStream 2.0) if centrally hosted |

## Client scenarios (code side)

| Scenario | What happens per application | When |
| --- | --- | --- |
| `modernize` (default) | The reviewed 7R decision per app: port to .NET 10 for Linux, replace Windows-bound parts | The client wants cost and agility gains |
| `lift-and-shift` | Every server app moves as it is to EC2 with the same OS (Windows to Windows, Linux to Linux); the draft sets Rehost and keeps the modernization path as a future option. Costs AWS-landing, connectivity, configuration, secrets, identity, integration, security and hypervisor findings | The client wants out of the current hosting first and will modernize later. Chosen in the intake questionnaire |
| `windows-rehost` | Every server app moves as-is from on-premises Windows to Windows EC2. Only connectivity, configuration, secrets, identity and integration findings are costed | Fastest exit from the data centre; no code port |

Hosting of the database and operations work are out of scope; the estimate counts coding hours only. The report's scenario table shows both, so the client sees the trade-off between code effort and modernization.

## Decision tree (AWS strategies applied to one .NET application)

```
Is the application still needed (usage, owners, consumers)?
  no  -> RETIRE: name the replacement, archive data, decommission, sign-off
  yes -> Commodity function with a SaaS fit (integrations and data export acceptable)?
    yes -> REPURCHASE
    no  -> Hard blocker to moving now (compliance, vendor, hardware, unfunded rewrite, dependency first)?
      yes -> RETAIN (review date + exit criteria; hybrid shared libraries)
      no  -> Must leave the data centre fast with no code change, or Windows-bound components?
        yes -> REHOST on EC2 Windows (whole VMware estate: RELOCATE); plan the follow-up
        no  -> Is the platform the only blocker (Windows, IIS, .NET Framework, SQL Server licence)?
          yes -> REPLATFORM: port to .NET 10, Linux containers, managed services
          no  -> REFACTOR / re-architect the slice that cannot move (incremental, strangler)

Overlay: a UI framework with no .NET 10 counterpart (Web Forms) makes that UI slice a Refactor,
whatever the application-level answer (a token UI is rewritten inside the port).
```

AWS advises rehost, relocate or replatform first in large migrations and refactoring after cutover
([migration strategies](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html));
its replatform examples include porting .NET Framework to .NET to run on Linux.

## Justifying each R in the report

Every application plan shows, besides **Why** and **Options considered**:

- **Why not the other Rs**: the default reasoning for the chosen R, which the reviewer edits per application;
- **Then**: what happens next for that R (for Retire: what replaces the capability, hidden-consumer check, data export,
  decommission steps; for Refactor: what is rewritten and how, incrementally);
- **Risks** and **Signs off**.

They come from `r7_guidance` in `data/decision_rules.json` (per R, with sources); a reviewer's decision in
`decisions.json` can override any of the four lists.

**Retire, then what?** Retire never means "delete and hope". Name what takes over each capability (another application,
which screens or calls move there and who builds them; a SaaS; a read-only archive; nothing), prove there are no
hidden consumers (IIS logs by path, service callers, scheduled jobs, reports on its database), export the data under
the retention rule, then decommission and keep a final backup. The work of moving screens into another application is
estimated with that application.

**Rewrite: why and how.** Rewrite only the slice that has no .NET 10 counterpart or cannot meet demand; keep porting
the rest. Rewrite when the UI framework is gone (Web Forms), when the code cannot be tested or understood well enough
to port safely, or when the business wants new behaviour anyway. Do it incrementally: YARP in front, one route or page
at a time, System.Web adapters for shared code and session, characterisation tests and parity before each move.
Conversion is not automatically cheaper than a rewrite (QSM data: conversions with under 5% new function show a worse
productivity index than new builds), so price both when the choice is close. Challenges and methods:
[modernisation-challenges.md](modernisation-challenges.md).
