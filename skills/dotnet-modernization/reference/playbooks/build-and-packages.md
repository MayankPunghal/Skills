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

## NuGet warnings that block the port

| Code | Meaning | Fix |
|---|---|---|
| `NU1701` | The package has no build for the target and was restored from a .NET Framework fallback | Replace it with a modern package. If nothing uses it, remove the reference. If code uses it, migrate that code first |
| `NU1608` | Another package requires a version range that this package's version is outside | Remove the legacy package that sets the constraint. Most of these go away with the `NU1701` package |
| `NU1605` | A package was downgraded because another package needs a higher version | Add a direct reference at the version the target runtime needs. Do not pin framework packages below the target runtime major |
| `NU1902` | The package has a known vulnerability | Migrate off the package if you can. Otherwise move to a patched version and record the advisory |

Avoid `NoWarn` for these codes: each one hides a real conflict.

## Build errors after conversion

| Error | Cause | Fix |
|---|---|---|
| `NETSDK1022` (duplicate Content or Compile items) | The SDK's default globs already include files that the old project listed by hand | Delete the explicit `Include` items. Use `Update` to change metadata. Or set `EnableDefaultCompileItems` or `EnableDefaultContentItems` to `false` and list the items yourself |
| `CS0579` (duplicate assembly attributes) | The SDK generates assembly attributes that clash with `Properties/AssemblyInfo.cs` | Set `GenerateAssemblyInfo` to `false` and keep the file, or delete the file and let the SDK generate the attributes. Do one, not both |

## Test projects

- `[ExpectedException]` was removed in NUnit 3. Use `Assert.Throws<T>(() => ...)`.
- Classic asserts such as `Assert.AreEqual` still compile on NUnit 3. Write the constraint form instead: `Assert.That(actual, Is.EqualTo(expected))`. It compiles on every NUnit 3 and 4 release, while the classic asserts moved between NUnit 4 releases.
- RhinoMocks is unmaintained and has no one-to-one successor, so rewrite each test. `MockRepository.GenerateMock<T>()` becomes `Mock<T>` (Moq) or `Substitute.For<T>()` (NSubstitute). `AssertWasCalled` becomes `Verify` (Moq) or `Received()` (NSubstitute).

## Done when

`dotnet build -c Release` passes on Linux (the container's SDK image) with no PROJ-* residue.
