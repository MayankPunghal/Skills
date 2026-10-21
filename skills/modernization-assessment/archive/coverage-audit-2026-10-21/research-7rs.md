> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Modernisation approaches and 7 Rs research

agent a734180e0cc63468e

Research written to: <scratchpad>\research\modernisation-approaches.md

10-line summary:
1. Sections 1-8 cover the 7 Rs (definitions, criteria, evidence, next steps, risks, decision tree), Web Forms to Blazor/Razor, System.Web adapters and shared libraries, WCF/CoreWCF/ASMX, WPF/WinForms, MongoDB and DocumentDB, a challenges table, and AWS Transform for .NET.
2. Every claim is tagged [V] (primary page opened), [S] (search snippet only) or [K] (my knowledge, unsourced). Verify [K] items before relying on them.
3. Upgrade Assistant is deprecated; Microsoft points to the GitHub Copilot app modernization agent [V].
4. AWS Transform for .NET covers Web Forms, WCF, ASMX, WinForms/WPF, MVC, Web API, class libs for .NET 8/10. Since Dec 2025 it ports Web Forms UI to Blazor Server, with an unsupported list (.svc, .ashx, .asmx, service/web references, third-party controls, Web Site projects, mixed aspx/cshtml) [V].
5. Web Forms has no ASP.NET Core counterpart. Remote-app session, wrapped session and machineKey data protection are the incremental tools [V].
6. Shared libraries: adapters let one library serve net48 and ASP.NET Core callers; netstandard2.0 is possible if HttpContext is the only System.Web dependency [V].
7. WCF server means CoreWCF (ASP.NET Core hosted); WCF clients use dotnet-svcutil. ASMX has no Microsoft replacement page in my research (gap).
8. WPF and WinForms are Windows-only on .NET. Options: keep on Windows, WorkSpaces applications (formerly AppStream 2.0), or rewrite [V].
9. MongoDB: the 1.x to 3.x upgrade is multi-hop (via 2.30); the GUID representation change is the main data risk. DocumentDB is mostly config (TLS CA, retryWrites=false below engine 8.0.2), but $where, getLastError, capped collections, reverse $natural and natural-order reliance break [V].
10. Not archived and no HTML version written: you asked for one output file, which overrides the memory rule and CLAUDE.md archive step. Both can be run on request. Several items are gaps or snippet-only (listed in section 10).
