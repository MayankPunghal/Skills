# Playbook: project files, packages and build

**Rules:** BUILD-*, INV-*, PKG-*, TEST-* (assessment); PROJ-LEGACY, PROJ-NETFX-TFM, PROJ-PACKAGES-CONFIG,
PROJ-WEB-TARGETS, PROJ-HINTPATH-NETFX (residue).
**Engines:** both engines convert project files and packages (DevTx KB 01, 06, 24, 27; AWS Transform). Claude fixes
what blocks the build afterwards. BUILD-WINDOWS-CI is DevOps; BUILD-INSTALLER is a client decision.

## After the engine run

1. **SDK-style everywhere**, `<TargetFramework>net10.0</TargetFramework>` (or `netstandard2.0` / multi-target for a
   library shared with .NET Framework callers — see [../workflow.md](../workflow.md)).
2. **No packages.config**, no `<HintPath>` into `packages\`; `Directory.Packages.props` (central package management)
   when the solution has many projects.
3. **Binary references** (`<Reference Include=... HintPath=...>` to a DLL in the repo): find the package or the source;
   a .NET Framework-only DLL is a blocker until replaced (DevTx KB 27 lists the usual ones).
4. **Polyfills to drop**: Microsoft.Net.Http, System.ValueTuple, Microsoft.Bcl.*, System.Net.Http (the framework has them).
5. **Windows-only packages**: replace (assessment package map: `modernization-assessment/scripts/data/package_map.json`).
6. **Major upgrades** (AutoMapper, Newtonsoft → System.Text.Json only when asked, log4net/NLog): one package per commit,
   read its breaking changes, rebuild.
7. **Warnings**: do not raise `TreatWarningsAsErrors` during the port; record the count in verify.md and compare with
   the baseline. Nullable stays off unless the project already had it.
8. **Tests**: test projects move to the same TFM; MSTest v1 / NUnit 2 → current versions (DevTx KB 24).

## Done when

`dotnet build -c Release` passes on Linux (the container's SDK image) with no PROJ-* residue.
