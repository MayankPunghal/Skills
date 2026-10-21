> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Linux readiness catalogue for .NET apps (Windows to Linux containers on AWS ECS/EKS)

Generated 2026-10-21. Read-only research. Covers .NET Framework 4.x apps being ported to .NET 8/10 and .NET 5+ apps that run on Windows today.

## How to read this

- **ID**: proposed `LNX-<AREA>-<NAME>`. Areas: BLD, FS, TZ, CUL, ENC, PROC, CON, ENV, CRY, AUTH, DATA, NET, IPC, API, WEB, HOST, CTR, CFG, PERF, LOG, SCH, MSG, SER, CI.
- **Sev**: `block` = fails build, startup, or a common path on Linux. `warn` = behaves differently or fails on some paths. `info` = context, verify.
- **Detect**: .NET-flavoured regex (escaped `\|` for table cells) and the file types to search: `cs`, `vb`, `proj` (.csproj/.vbproj/.props/.targets), `cfg` (web/app.config, appsettings*.json, runtimeconfig), `markup` (cshtml/aspx/ascx/master), `sql`, `yml` (CI), `df` (Dockerfile), `pubxml`, `ps1/sh/bat`.
- **Already in**: `COVERED: <rule id>` = an existing rule already flags it. `PARTIAL: <id>` = related rule exists but misses part of the check. `GAP` = no rule. Rule ids come from `migration-assessment/scripts/data/rules.json` (186 rules) and `dotnet-modernization/scripts/data/residue_rules.json` (44 rules).
- **Src**: short codes, listed in section 23. `[K]` = from engineering knowledge, not fetched; verify before relying on it.

Totals and top gaps are in section 20.

## 1. Build, project and packaging

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-BLD-CA1416 | Windows-only API called from cross-platform code: CA1416 warns at build, call throws PlatformNotSupportedException at runtime | build log on Linux: `warning CA1416`; cs | block | Replace, remove, or guard with `OperatingSystem.IsWindows()` | S1, S2 | PARTIAL: validate_linux_build.py builds on Linux; no rule parses CA1416 output |
| LNX-BLD-TFM-WINDOWS | `-windows` TFM makes the whole assembly Windows-only | proj: `<TargetFrameworks?>[^<]*-windows` | block | Multi-target `net10.0` for shared code; keep `-windows` only on Windows-only projects | S1 | GAP (PROJ-NETFX-TFM covers net4x only) |
| LNX-BLD-WINFORMS-WPF | WinForms/WPF SDK flags pull in Windows desktop targets | proj: `<UseWindowsForms>true\|<UseWPF>true\|Microsoft\.NET\.Sdk\.WindowsDesktop` | block | Move logic to a class library; UI stays on Windows | S5 | PARTIAL: DESK-WINFORMS (cs/vb), DESK-WPF (proj) |
| LNX-BLD-RID-WINDOWS | Publish pinned to a Windows RID; artifact is not a Linux binary | proj/pubxml: `<RuntimeIdentifier>win[-\w]*<`; `win-x64\|win-x86` | block | Publish `linux-x64` (or `linux-arm64` for Graviton/Fargate ARM) | S3 | GAP |
| LNX-BLD-MSDEPLOY-PUBLISH | IIS/MSDeploy publish profile has no container equivalent | pubxml: `WebDeploy\|MSDeploy` | warn | `dotnet publish` plus Dockerfile | S3 | COVERED: IIS-PUBLISH (info) |
| LNX-BLD-WINDOWS-PACKAGES | Packages that are Windows-only (their APIs throw or are absent on Linux) | proj: `Include="(System\.Drawing\.Common\|System\.DirectoryServices[\w.]*\|System\.Management\|System\.ServiceProcess\.ServiceController\|System\.Diagnostics\.PerformanceCounter\|System\.Diagnostics\.EventLog\|System\.Messaging\|System\.Security\.Cryptography\.ProtectedData\|System\.Speech\|System\.Windows\.Extensions\|Microsoft\.Win32\.Registry)"` | block if server code uses them | Replace per API row below; add a post-build package check | S5, S7, S12 | PARTIAL: WIN-* rules match code, not package references |
| LNX-BLD-WINCOMPAT-PACK | Windows Compatibility Pack (~20k APIs) compiles, but its Windows parts still fail on Linux | proj: `Include="Microsoft\.Windows\.Compatibility"` | warn | Keep only for Windows-only projects; otherwise remove and fix call sites | S5 | GAP |
| LNX-BLD-MODULE-OUTPUT | Multi-module assemblies (`OutputType=Module`) unsupported in .NET 6+ | proj: `<OutputType>Module<` | block | Merge modules into one assembly | S4 | GAP |
| LNX-BLD-REFLECTION-EMIT-SAVE | AssemblyBuilder.Save / RunAndSave / ReflectionOnly unavailable through .NET 8 (PersistedAssemblyBuilder added in .NET 9) | cs: `AssemblyBuilderAccess\.(RunAndSave\|Save\|ReflectionOnly)`; `\.Save\(` near `DefineDynamicAssembly` | block (on .NET 8) | Use PersistedAssemblyBuilder on .NET 9+, or do not persist | S4 | GAP |
| LNX-BLD-APPDOMAIN | Creating app domains is not supported; CreateDomain throws | cs/vb: `AppDomain\.CreateDomain\(\|AppDomainSetup\|AppDomain\.CurrentDomain\.SetData` | block | Separate process or container; AssemblyLoadContext for plugins | S4 | GAP |
| LNX-BLD-CAS-ATTRIBUTES | Code Access Security / security transparency is not a boundary; attributes are no-ops | cs/vb: `SecurityPermission\|PermissionSet\|CodeAccessPermission\|SecurityTransparent\|AllowPartiallyTrustedCallers` | warn | Remove; rely on OS/container isolation | S4 | COVERED: API-CAS (low) |
| LNX-BLD-DELEGATE-BEGININVOKE | Delegate BeginInvoke/EndInvoke throw PlatformNotSupportedException | cs/vb: `\.BeginInvoke\(\|\.EndInvoke\(` (review each hit; delegates only) | warn | Task.Run / async-await | S4 | GAP |
| LNX-BLD-PREBUILD-WINDOWS-CMD | Pre/post-build events call Windows commands; build fails on Linux | proj: `<(Pre\|Post)BuildEvent>[^<]*(copy \|xcopy\|del \|cmd\|powershell\|\\\\\|%[A-Za-z]+%)` | block | Replace with MSBuild Copy/Exec using `$(MSBuildProjectDirectory)` | S3 | COVERED: BUILD-EVENTS |
| LNX-BLD-NUGET-WINDOWS-SOURCE | NuGet source is a UNC or drive-letter path | NuGet.Config: `value="(\\\\\|[A-Za-z]:\\)` | block | Use a URL feed (CodeArtifact / Azure Artifacts) | S3 | PARTIAL: BUILD-PRIVATE-FEED |
| LNX-BLD-USINGTASK-WINDOWS | Custom MSBuild task loaded from a Windows path or Program Files | proj/targets: `<UsingTask[^>]*AssemblyFile="[^"]*(Program Files\|\\\\\|[A-Za-z]:)`; `\$\(ProgramFiles\|MSBuildExtensionsPath32` | block | Ship the task as a cross-platform NuGet package | K | GAP |
| LNX-BLD-NATIVE-DLL-COPY | Windows native DLLs copied into output; not loadable on Linux | proj: `<(Content\|None\|Reference)[^>]*Include="[^"]*\.dll"`; `HintPath>[^<]*\\(x64\|x86)\\` | block (if loaded) | Use Linux `.so` builds per RID | S3 | PARTIAL: WIN-PINVOKE-NATIVE (cs only) |
| LNX-BLD-GAC-REFERENCE | Strong-named assembly resolved from GAC (no HintPath) | proj: `<Reference Include=` without `<HintPath>` | warn | Replace with NuGet package | S3 | COVERED: BUILD-GAC-REFERENCE |
| LNX-BLD-WEB-TARGETS | VS web application targets are Windows build tooling | proj: `Microsoft\.WebApplication\.targets\|WebApplicationProjectGuid` | block | SDK-style web project | S3 | COVERED: PROJ-WEB-TARGETS, BUILD-WEB-TARGETS |
| LNX-BLD-INSTALLER | InstallUtil, WiX and setup projects are Windows-only | proj/cs: `\.wixproj\|System\.Configuration\.Install\|RunInstallerAttribute` | warn | Container image replaces the installer | S3 | COVERED: BUILD-INSTALLER |
| LNX-BLD-LEGACY-CSPROJ | Non SDK-style project does not build with `dotnet` on Linux | proj: `<Project\s+ToolsVersion=` | block | Convert to SDK-style | S3 | COVERED: PROJ-LEGACY |

## 2. File system and paths

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-FS-CASE-LITERAL | Path literal differs in case from the file on disk: works on NTFS, not found on ext4/overlayfs | cs/vb/markup/cfg: `"~?/?[^"]+\.(cshtml\|css\|js\|json\|png\|jpg\|gif\|svg\|xml\|config\|resx\|txt\|html)"`, then compare with `git ls-files` (case-sensitive) | block | Rename file or literal (`git mv` for case-only renames); add a Linux CI check | S30, S32 | GAP: FILE-CASE-MISMATCH is documented in migration-assessment/references/linux-pitfalls.md but is not in rules.json or any script |
| LNX-FS-CASE-VIEW-NAME | Razor view or partial named with different case than the .cshtml file | cs/markup: `\b(View\|PartialView\|RenderPartial\|Partial\|RenderAction)\(\s*"([^"]+)"` checked against Views/ file list | block | Match casing exactly | S30 | GAP |
| LNX-FS-CASE-STATIC-URL | Script, style or image reference differs in case from wwwroot file | markup: `(src\|href)="(/?[^"#?]+\.(js\|css\|png\|jpg\|gif\|svg\|woff2?))"` checked against wwwroot | block | Fix casing; add lowercase file-name convention | S30 | GAP (FILE-CASE-MISMATCH not implemented) |
| LNX-FS-CASE-EMBEDDED-RESOURCE | GetManifestResourceStream name must match exactly; default names come from folder/namespace casing | cs: `GetManifestResourceStream\("([^"]+)"`; proj: `<EmbeddedResource Include=` without `LogicalName` | block | Set explicit `LogicalName`; compare names in a test | K | GAP |
| LNX-FS-CASE-ASSEMBLY-NAME | Assembly and type loads by name differ in case from the DLL file | cs: `Assembly\.Load(From)?\(\s*"[^"]+"\)`; `Type\.GetType\("[^"]+,\s*[^"]+"\)` | block | Exact assembly names; prefer typed references | S31 | GAP |
| LNX-FS-CASE-APPSETTINGS | Host loads `appsettings.{Environment}.json` by exact name; `appsettings.production.json` vs `Production` fails | file list: `appsettings\.[A-Za-z]+\.json`, compare with ASPNETCORE_ENVIRONMENT value | block | Single agreed casing; CI check | S30 | GAP |
| LNX-FS-BACKSLASH-LITERAL | `\` is a valid name character on Linux; paths built with it are wrong | cs/vb: `(Path\.Combine\|File\.\|Directory\.\|new FileInfo\|new DirectoryInfo)\([^)]*"[^"]*\\\\[^"]*"` | warn | `Path.Combine` and `/` | S14 | COVERED: FILE-BACKSLASH; FILE-BACKSLASH-JOIN (residue) |
| LNX-FS-SPLIT-BACKSLASH | Parsing paths by splitting on `\` | cs/vb: `\.Split\(\s*(@?"\\\\?"\|'\\\\')` | warn | `Path.DirectorySeparatorChar` / Path APIs | S14 | PARTIAL: FILE-BACKSLASH |
| LNX-FS-DRIVE-LETTER | Drive letter paths do not exist in containers | cs/cfg/sql/proj: `@?"[A-Za-z]:\\` | block | Configured path on mounted storage (EFS) or S3 | S3 | COVERED: FILE-DRIVE (residue); FILE-DRIVE-LETTER (rules) |
| LNX-FS-UNC-PATH | UNC share paths do not resolve on Linux | cs/cfg: `@?"\\\\[A-Za-z0-9._-]+\\` | block | EFS / S3 / SDK | S3 | COVERED: FILE-UNC (residue); NET-UNC-SHARE (rules) |
| LNX-FS-SPECIAL-FOLDER | GetFolderPath returns "" when the folder does not physically exist; several Windows SpecialFolder values have no Linux equivalent | cs/vb: `GetFolderPath\(\s*Environment\.SpecialFolder\.(ProgramFiles\|ProgramFilesX86\|Windows\|System\|SystemX86\|CommonProgramFiles\|Programs\|Startup\|StartMenu\|Favorites\|Cookies\|Recent\|SendTo\|Templates\|CommonApplicationData)` | block if result used as a path | Configuration or IConfiguration path; test with empty value | S15 | PARTIAL: FILE-WIN-FOLDERS |
| LNX-FS-WIN-ENV-VAR-PATH | `%windir%`, `%ProgramData%`, `%APPDATA%` etc. are not defined on Linux | cfg/proj/cs: `%(SystemRoot\|windir\|ProgramData\|ProgramFiles\|APPDATA\|LOCALAPPDATA\|TEMP\|TMP\|SystemDrive)%`; `ExpandEnvironmentVariables\(` | block | Config keys, not env expansion | S3 | COVERED: FILE-WIN-FOLDERS |
| LNX-FS-TEMP-PATH | Path.GetTempPath() is /tmp, which is ephemeral per ECS task; code assumes a Windows temp folder or persistence | cs/vb: `GetTempPath\(\)`; `"C:\\\\Temp` | info | Explicit temp dir on a mounted volume; cleanup on startup | K | GAP |
| LNX-FS-INVALID-NAME-CHECK | Validation via GetInvalidFileNameChars assumes Windows set; on Linux only `/` and NUL are invalid, so `:*?"<>\|` pass and break on Windows or S3 | cs/vb: `GetInvalidFileNameChars\|GetInvalidPathChars` | warn | Explicit allow-list for uploaded/derived file names | S14 | GAP |
| LNX-FS-LOCAL-WRITE-APPDIR | Writes into app folder (AppContext.BaseDirectory, CurrentDirectory) fail when the root filesystem is read-only or owned by root | cs: `(AppContext\.BaseDirectory\|Directory\.GetCurrentDirectory\(\)\|Assembly\.GetExecutingAssembly\(\)\.Location\|AppDomain\.CurrentDomain\.BaseDirectory)` near `File\.(Create\|Write\|Append\|Open)\|StreamWriter\|CreateDirectory` (heuristic) | block | Write to a mounted volume (EFS) or S3; app dir read-only | K | PARTIAL: FILE-LOCAL-WRITE (state-scale) |
| LNX-FS-LONG-PATH-PREFIX | `\\?\` long-path prefix is a literal file name on Linux | cs/vb: `"\\\\\?\\` | block | Remove prefix; keep paths short | S14 | GAP |
| LNX-FS-FILE-LOCKING | Locks are advisory on Linux (no mandatory share modes); cross-process FileShare.None assumptions break | cs/vb: `FileShare\.(None\|Read)` with file-based coordination | warn | Use a DB or lock service for coordination | K | COVERED: FILE-LOCKING (low) |
| LNX-FS-CASE-INSENSITIVE-COMPARE | Path equality done case-insensitively: wrong on Linux | cs/vb: `(path\|file\|dir)[\w.]*\s*(==\|\.Equals\()[^;]*(OrdinalIgnoreCase\|ToLower\(\|ToUpper\()` (heuristic) | warn | Compare normalized full paths with Path.GetFullPath, ordinal | K | GAP |
| LNX-FS-WATCHER-SEMANTICS | FileSystemWatcher on Linux uses inotify; buffer overflow drops events; rename/move events and network mounts behave differently | cs/vb: `new FileSystemWatcher\|FileSystemWatcher\(` | warn | Polling fallback, idempotent processing, reconcile on startup | S17 | GAP |
| LNX-FS-SYMLINK-JUNCTION | Junctions do not exist on Linux; symlinks are used instead | cs/vb/ps1/sh/bat: `mklink\|CreateSymbolicLink\|\.Junction\|mklink /J` | info | Use symlinks or path config | K | GAP |
| LNX-FS-ATTRIBUTE-FLAGS | ReadOnly / Hidden attributes are not Linux permissions; hidden means leading dot | cs/vb: `FileAttributes\.(ReadOnly\|Hidden\|System)`; `File\.SetAttributes\(` | warn | Use file mode / explicit checks | K | GAP |
| LNX-FS-SCRIPT-EXEC-BIT | Shell scripts committed without executable bit: `Permission denied` at container start | git: `git ls-files -s '*.sh'` mode not `100755`; df `ENTRYPOINT ["./` | block | `git update-index --chmod=+x` or `chmod +x` in Dockerfile | K | GAP |
| LNX-FS-CRLF-SCRIPTS | CRLF line endings in shell scripts or Dockerfile: `/usr/bin/env: 'bash\r'` | `\r$` in `*.sh`, `Dockerfile`, `*.yml`, `entrypoint*` (grep) | block | `.gitattributes`: `*.sh text eol=lf`; convert files | K | PARTIAL: FILE-CRLF (cs/vb only, low) |
| LNX-FS-DELETE-OPEN-FILE | Deleting or renaming a file that another handle has open succeeds on Linux but fails on Windows; code written on Linux can break on Windows | cs/vb: `File\.(Delete\|Move)` near open streams (review) | info | Explicit close before delete; test on both | K | GAP |

## 3. Time zones

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-TZ-WINDOWS-ID | Windows IDs resolve on Linux only through ICU; fail without ICU, in invariant mode, or on tzdata-less images | cs/vb/cfg/sql: `"(Eastern\|Central\|Mountain\|Pacific\|GMT\|W\. Europe\|India\|China\|AUS Eastern\|Tokyo\|Romance\|Romance) Standard Time"\|"[A-Za-z .]+ Standard Time"` | block | Store IANA IDs; convert with TimeZoneInfo.TryConvertWindowsIdToIanaId or TimeZoneConverter | S9, S29 | COVERED: TZ-WINDOWS-ID (residue); TZ-WINDOWS-ID (rules) |
| LNX-TZ-IANA-ID-IN-CODE | IANA IDs (`America/New_York`) work on Windows only on .NET 6+ with ICU; old Windows or NLS mode fail | cs/vb/cfg: `"(America\|Europe\|Asia\|Australia\|Africa\|Pacific)/[A-Za-z_]+"` | warn | Keep one canonical id per deployment; test on Windows and Linux | S9 | GAP |
| LNX-TZ-LOCAL-NOW | Containers run UTC; DateTime.Now / Today and TimeZoneInfo.Local silently change behaviour | cs/vb: `DateTime\.(Now\|Today)\b\|DateTimeOffset\.Now\|TimeZoneInfo\.Local\b` | warn | Explicit business zone or UTC | S29 | COVERED: TZ-LOCAL-TIME (rules); TZ-LOCAL (residue) |
| LNX-TZ-SQL-LOCAL-TIME | SQL Server GETDATE/SYSDATETIME use DB-server local time, not app time | sql/cs: `\b(GETDATE\|SYSDATETIME\|SYSDATETIMEOFFSET)\s*\(` | warn | GETUTCDATE / app-supplied UTC | S29 | COVERED: TZ-SQL-LOCAL-TIME (rules) |
| LNX-TZ-TZDATA-MISSING | Image without tzdata (alpine, chiseled): TimeZoneInfo throws TimeZoneNotFoundException for IANA ids | df: `FROM .*(alpine\|chiseled\|distroless)` and no `tzdata` line | block (if zones used) | Install tzdata or use full Debian/Ubuntu image | S28 | GAP |
| LNX-TZ-DISPLAY-NAME | StandardName / DisplayName text differs on Linux (ICU display names) | cs/cshtml: `\.(StandardName\|DaylightName\|DisplayName)\b` | info | Do not show zone names from the OS; use a fixed label table | S9 | GAP |
| LNX-TZ-CONVERT-DST | Ambiguous/invalid local times around DST resolved per tzdata version; differs across images | cs/vb: `TimeZoneInfo\.ConvertTime(ToUtc)?\(` | info | Store UTC; convert at the edge; test DST boundaries | K | GAP |

## 4. Globalization and culture (ICU vs NLS)

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-CUL-HARDCODED-CULTURE | Culture name hardcoded; culture data comes from ICU/CLDR and differs | cs/vb/cfg: `new CultureInfo\("[a-z]{2}-[A-Z]{2}"\)\|GetCultureInfo\("[a-z]{2}-[A-Z]{2}"\)` | info | Explicit invariant or request culture | S9 | COVERED: CULT-HARDCODED (rules) |
| LNX-CUL-IMPLICIT-STRING-COMPARE | Culture-sensitive default comparisons: ICU and NLS order and match differently (zero-weight `\0`, ligatures, apostrophes) | cs/vb: `\.(StartsWith\|EndsWith\|IndexOf\|LastIndexOf)\("[^"]*"\)` (no comparison arg); `string\.Compare\(` without StringComparison | warn (block for identifiers) | `StringComparison.Ordinal` for identifiers; run CA1307/CA1309 | S9 | PARTIAL: CULT-HARDCODED |
| LNX-CUL-SORT-DEFAULT | List/Order sorting of strings uses culture rules: order changes (`bill's` vs `bills`) | cs/vb: `OrderBy\(\|\.Sort\(\)\|Array\.Sort\(` on strings with no comparer | warn | Explicit comparer | S9 | GAP |
| LNX-CUL-CASE-CONVERSION | ToUpper/ToLower use current culture (Turkish I) and ICU casing | cs/vb: `\.(ToUpper\|ToLower)\(\)` on keys, codes, identifiers | warn | `ToUpperInvariant()` / Ordinal | S9 | GAP |
| LNX-CUL-SHORTEST-DAY-NAME | Day abbreviations changed: GetShortestDayName gives one character on .NET 5+ | cs/vb: `GetShortestDayName\|GetAbbreviatedDayName` | info | Explicit format strings | S9 | GAP |
| LNX-CUL-DEFAULT-NUMBER-FORMAT | ToString("C"/"N"/"D"/"F") uses current culture; containers default to invariant (no LANG) | cs/vb: `\.ToString\(\s*"[CNDFP]"\s*\)` | warn | Explicit culture for user-facing output | S10 | GAP |
| LNX-CUL-INVARIANT-MODE | InvariantGlobalization removes culture data: CultureInfo("de-DE") behaves as invariant | proj: `<InvariantGlobalization>true`; df/yml: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`; cfg: `System.Globalization.Invariant": true` | warn (block if culture-sensitive app) | Enable only when culture-free; verify formatting | S10 | GAP |
| LNX-CUL-ICU-MISSING-IMAGE | Non-invariant app on an image without libicu: process fails at startup ("Failed to load system ICU") | df: `FROM .*(alpine\|chiseled\|distroless)` without invariant flag or ICU install | block | Use Debian/Ubuntu base or `icu-libs` / invariant mode | S9, S28 | GAP |
| LNX-CUL-NLS-SWITCH | UseNls is Windows-only; Linux ignores it, so Windows-like behaviour is not reproduced | cfg/proj/env: `System\.Globalization\.UseNls\|DOTNET_SYSTEM_GLOBALIZATION_USENLS` | info | Remove; test under ICU | S10 | GAP |
| LNX-CUL-LCID-CULTURE | Numeric LCID (Windows) used to create CultureInfo; invalid or different on Linux | cs/vb: `new CultureInfo\(\s*0x?[0-9A-Fa-f]{3,4}\s*\)` | warn | Named cultures | K | GAP |
| LNX-CUL-LIST-SEPARATOR | Parsing input or CSV with the current culture list separator or decimal separator | cs/vb: `ListSeparator\|NumberDecimalSeparator` used in parsers | warn | Explicit separators for file formats | K | GAP |

## 5. Encodings, line endings and text

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-ENC-CODEPAGE-LITERAL | Code pages other than UTF and ASCII/Latin-1 are not built in (.NET 5+); GetEncoding throws | cs/vb: `Encoding\.GetEncoding\(\s*(?!65001\|1200\|1201\|12000\|12001\|20127\|28591\|65000)\d+\s*\)`; `GetEncoding\("(windows-125\d\|iso-8859-(?!1\b)\d+\|shift_jis\|gb2312\|big5\|euc-kr)"` | block | Register CodePagesEncodingProvider; or move to UTF-8 | S16 | PARTIAL: FILE-ENCODING |
| LNX-ENC-CODEPAGE-PROVIDER-MISSING | Code pages used but System.Text.Encoding.CodePages not referenced or not registered | proj: absent `System.Text.Encoding.CodePages`; cs: `Encoding.RegisterProvider` absent | block | Add package and `Encoding.RegisterProvider(CodePagesEncodingProvider.Instance)` | S16 | GAP |
| LNX-ENC-DEFAULT-ENCODING | Encoding.Default is UTF-8 on .NET 5+ (ANSI on .NET Framework): legacy files read as mojibake | cs/vb: `Encoding\.Default\b` | warn | Explicit encoding everywhere | S16 | COVERED: FILE-ENCODING |
| LNX-ENC-NO-ENCODING-ARG | StreamReader / File.ReadAll* without encoding: legacy 1252/BOM files misread | cs/vb: `new StreamReader\((?![^)]*Encoding)`; `File\.ReadAll(Text\|Lines)\((?![^)]*Encoding)` | warn | Explicit encoding | S16 | GAP |
| LNX-ENC-BOM-SENSITIVE | Byte-level signatures, hashes and XML change with BOM presence | cs/vb: `UTF8Encoding\(true\)\|GetPreamble\(\)\|\\uFEFF` | warn | Consistent BOM policy, documented | K | GAP |
| LNX-ENC-CRLF-PROTOCOL | Protocol or format built with `\r\n` literal; partners or parsers differ | cs/vb: `"\\r\\n"` in Write/Send/Format calls | warn | Use explicit CRLF constant where the protocol requires it | K | PARTIAL: FILE-CRLF (cs/vb, low) |
| LNX-ENC-NEWLINE-SPLIT | Splitting text on `\r\n` only; LF-only files from Linux tooling are not split | cs/vb: `\.Split\(\s*(new\s*string\[\]\s*\{\s*)?"\\r\\n"` | warn | Split on `\r?\n` or Environment.NewLine plus tolerant parsing | K | PARTIAL: FILE-CRLF |
| LNX-ENC-HASH-TEXT-FILE | Hash or signature over file bytes; CRLF on Windows checkout and LF on Linux give different hashes | cs/vb: `ComputeHash\(File\.ReadAllBytes`; `SHA256\.HashData\(File\.`; repo: no `.gitattributes` with `text=auto` | block | Normalize line endings before hashing; `.gitattributes` | K | GAP |
| LNX-ENC-XML-DECLARATION | XML declares a Windows code page (windows-1252) the parser cannot read without the provider | cfg/cs: `encoding="(windows-125\d\|iso-8859-\d\|shift_jis)"` in XML or XmlWriterSettings | block | Register provider or re-encode to UTF-8 | S16 | GAP |

## 6. Processes, shell, console and signals

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-PROC-EXE-SUFFIX | Process started with a `.exe` name; Linux binaries have no suffix | cs/vb: `FileName\s*=\s*"[^"]*\.exe"\|Process\.Start\(\s*"[^"]*\.exe"` | block | Use executable names per platform or library calls | S13 | COVERED: WIN-SHELL-EXEC |
| LNX-PROC-WINDOWS-TOOLS | cmd, powershell, cscript, regsvr32, icacls, xcopy, sc, reg, netsh etc. do not exist in Linux images | cs/vb/cfg/ps1/yml: `"(cmd(\.exe)?\|powershell(\.exe)?\|cscript\|wscript\|regsvr32\|msiexec\|sc\.exe\|icacls\|xcopy\|robocopy\|reg\.exe\|netsh\|tasklist\|taskkill)"` | block | Library calls or pwsh / sh equivalents | S13 | PARTIAL: WIN-SHELL-EXEC |
| LNX-PROC-SHELL-SCRIPTS-BAT | App or pipeline runs .bat/.cmd/.ps1/.vbs | cs/vb/yml/proj: `"[^"]*\.(bat\|cmd\|ps1\|vbs)"` | block | Port to sh or pwsh | S13 | GAP |
| LNX-PROC-SHELLEXECUTE-DOCS | UseShellExecute opens files through the desktop shell; not present in containers | cs/vb: `UseShellExecute\s*=\s*true`; `Process\.Start\(\s*"[^"]*\.(pdf\|docx\|xlsx\|html?\|txt)"` | block | Library rendering (no shell) | S13 | COVERED: WIN-SHELL-ASSOC |
| LNX-PROC-USER-LOGON | ProcessStartInfo UserName / LoadUserProfile needs Windows logon | cs/vb: `\.(UserName\|LoadUserProfile)\s*=\|\.Domain\s*=` | block | Run as container user; no impersonation | S13 | COVERED: WIN-PROCESS-USER |
| LNX-PROC-PROCESS-NAME-MATCH | Process names on Linux have no `.exe` and are truncated; name matching fails | cs/vb: `GetProcessesByName\(\s*"[^"]*\.exe"\|ProcessName\s*==\s*"[^"]*"` | warn | Match on executable path or id | K | GAP |
| LNX-PROC-PATH-SEMICOLON | PATH split on `;` (Windows) instead of `:` | cs/vb: `Split\(\s*';'\s*\)` near `PATH` | warn | `Path.PathSeparator` | K | GAP |
| LNX-PROC-CTRLC-HANDLER | SetConsoleCtrlHandler (Windows API) and console key handling differ; SIGTERM is the Linux stop signal | cs/vb: `SetConsoleCtrlHandler\|CancelKeyPress\|TreatControlCAsInput` | warn | Host lifetime (IHostApplicationLifetime) | K | PARTIAL: WIN-CONSOLE-WINDOW (low) |
| LNX-PROC-NO-HOST-LIFETIME | App ignores SIGTERM: ECS sends SIGTERM then SIGKILL after stopTimeout (30 s default); loops without cancellation keep running | cs: `static .* Main\(` in Program.cs with `while\s*\(\s*true\s*\)` or `Thread\.Sleep\(Timeout\.Infinite\)` and no `IHost`/`BackgroundService`/`WebApplication` | warn | Generic host / BackgroundService with cancellation tokens | S18 | PARTIAL: HOST-WINDOWS-SERVICE-LIFETIME |
| LNX-PROC-SHELL-FORM-ENTRYPOINT | Dockerfile shell form: shell is PID 1 and does not forward SIGTERM to dotnet | df: `^(CMD\|ENTRYPOINT)\s+[^\[]` | warn | Exec form `ENTRYPOINT ["dotnet", "App.dll"]` | K | GAP |
| LNX-CON-READKEY-NO-TTY | Console.ReadKey / WindowWidth / SetCursorPosition fail without a TTY (container) | cs/vb: `Console\.(ReadKey\|WindowWidth\|WindowHeight\|SetCursorPosition\|Beep\|ReadLine)` in non-console apps | warn | Guard with `Console.IsInputRedirected` or remove | K | PARTIAL: WIN-CONSOLE-WINDOW |

## 7. Environment, identity and user

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-ENV-VAR-CASE | Environment variable names are case-sensitive on Linux; ECS task definition name differs from code | cs/vb: `GetEnvironmentVariable\("([^"]+)"`; compare with task definition names | block | One casing; test in container | K | GAP |
| LNX-ENV-DOUBLE-UNDERSCORE | Hierarchical config via env needs `__`; `:` in env names is not portable through shells and ECS | yml/df/task json: env names containing `:` | warn | Use `__` (DevTx 19 documents this) | S33 | GAP |
| LNX-ENV-WINDOWS-VARS | Reads of Windows-only variables return null on Linux | cs/vb: `GetEnvironmentVariable\("(USERPROFILE\|HOMEDRIVE\|HOMEPATH\|COMPUTERNAME\|USERDOMAIN\|LOGONSERVER\|APPDATA\|LOCALAPPDATA\|TEMP\|TMP\|OS\|PROCESSOR_ARCHITECTURE\|NUMBER_OF_PROCESSORS\|SystemRoot\|windir)"` | block | Use .NET APIs (AppContext, Path) or config | S15 | COVERED: FILE-WIN-FOLDERS (partial) |
| LNX-ENV-HOME-ASSUMPTION | Code writes to /root or assumes ~ for the non-root app user (UID 1654 in .NET 8+ images) | cs/vb/cfg/df: `"/root/\|~/\|/home/` | warn | Config path; test with non-root user | S27 | GAP |
| LNX-ENV-DOTNET-VS-ASPNETCORE | Both DOTNET_ENVIRONMENT and ASPNETCORE_ENVIRONMENT set with different values; config loaded from the wrong file | df/yml/task json: both keys present | warn | One variable | S33 | GAP |
| LNX-ENV-MACHINE-NAME | Container host name changes per task; logic keyed on machine name | cs/vb: `Environment\.MachineName` | warn | Explicit instance id config | K | COVERED: HOST-MACHINE-NAME, HV-MACHINE-NAME |
| LNX-ENV-PROCESSOR-ARCH | PROCESSOR_ARCHITECTURE / Is64BitOperatingSystem reflect the container arch; Graviton is arm64 | cs/vb: `PROCESSOR_ARCHITECTURE\|Is64BitOperatingSystem` | info | Avoid arch assumptions | K | GAP |

## 8. Cryptography and certificates

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-CRY-DPAPI | ProtectedData (DPAPI) is Windows-only; PlatformNotSupportedException on .NET Core non-Windows | cs/vb: `ProtectedData\.(Protect\|Unprotect)\|DataProtectionScope` | block | Data Protection API with KMS/Secrets Manager key store | S12 | COVERED: WIN-PROTECTEDDATA |
| LNX-CRY-ASPNET-DATAPROTECTION-KEYS | ASP.NET Core Data Protection keys default to a per-container folder; cookies/antiforgery break across tasks | cs: `AddDataProtection\(\)` without `PersistKeysTo\|ProtectKeysWith` | block (multi-task) | Persist keys to shared store (S3/SSM/Secrets Manager) | K | GAP |
| LNX-CRY-CNG-CSP | CNG and CSP key containers are Windows-only: RSACng, ECDsaCng, CngKey.Open, CspParameters throw on Linux | cs/vb: `CspParameters\|RSACryptoServiceProvider\|DSACryptoServiceProvider\|CngKey\.Open\|RSACng\|ECDsaCng\|ECDiffieHellmanCng` | block | Load keys from PEM/PFX via X509 APIs; use RSA.Create | S11 | COVERED: WIN-CNG-CSP (rated medium; should be high) |
| LNX-CRY-LOCALMACHINE-STORE | LocalMachine\My, Root (write), Disallowed not supported on Linux | cs/vb: `StoreLocation\.LocalMachine\|X509Store\(` with LocalMachine | block | Mount PEM/PFX; load from file | S11 | COVERED: WIN-CERTSTORE |
| LNX-CRY-THUMBPRINT-LOOKUP | Certificate chosen by thumbprint from a Windows store | cs/vb/cfg: `FindByThumbprint\|X509FindType\.FindByThumbprint\|thumbprint` | warn | Name or file reference | S11 | COVERED: LS-CERT-THUMBPRINT |
| LNX-CRY-PFX-KEYSET-FLAGS | MachineKeySet / UserKeySet meaningless on Linux; EphemeralKeySet is the portable choice | cs/vb: `X509KeyStorageFlags\.(MachineKeySet\|UserKeySet\|PersistKeySet)` | warn | Flags: EphemeralKeySet or explicit file | S11 | PARTIAL: WIN-CERTSTORE |
| LNX-CRY-KEY-FILE-PERMS | Private key or PFX mounted unreadable by UID 1654 (non-root): CryptographicException at startup | df/task json: `COPY .*\.(pfx\|p12\|key\|pem)`; mounted secrets file mode; manual check | block | Make readable to app user; use secret mount with correct owner | S11 | GAP |
| LNX-CRY-PRIVATE-CA-TRUST | Corporate/private CA trusted via Windows store is missing in the Linux image; TLS to internal services fails | cs/vb/cfg: `ServerCertificateCustomValidationCallback` absent but internal https endpoints; df: no `ca-certificates` / `SSL_CERT_FILE` | block | Add CA to image bundle or SSL_CERT_FILE; OpenSSL trust paths | S11 | GAP |
| LNX-CRY-DES-RC2-CFB | DES/3DES/RC2 CBC/ECB work; RC2-CFB is unsupported on all platforms | cs/vb: `RC2.*CFB\|RC2CryptoServiceProvider\|DESCryptoServiceProvider\|TripleDESCryptoServiceProvider` | warn | Move to AES-GCM / AES-CBC with HMAC | S11 | PARTIAL: API-WEAK-CRYPTO (residue), SEC-WEAK-CRYPTO |
| LNX-CRY-ECC-NAMED-CURVES | Brainpool and other named curves depend on distro OpenSSL | cs/vb: `brainpool\|ECCurve\.NamedCurves\.` | warn | Use NIST P-256/384/521 or explicit curves | S11 | GAP |
| LNX-CRY-OPENSSL-ALGORITHMS | SHA-3, SHAKE, KMAC, ML-KEM/ML-DSA/SLH-DSA need OpenSSL 1.1.1+ / 3.x / 3.5+ in the image | cs/vb: `SHA3_\|SHAKE\|KMAC\|MLKem\|MLDsa\|SlhDsa`; df: OpenSSL version | warn | Check `IsSupported`; pin image | S11 | GAP |
| LNX-CRY-ALGORITHM-FACTORY | HashAlgorithm.Create / SymmetricAlgorithm.Create by name map differently across providers | cs/vb: `(Hash\|Symmetric\|RSA\|DSA)Algorithm\.Create\(\s*"` | warn | Concrete types | S11 | COVERED: API-CRYPTO-FACTORY |

## 9. Authentication and identity

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-AUTH-WINDOWS-AUTH-IIS | `windowsAuthentication enabled=true` / `<authentication mode="Windows">` is IIS-only | cfg: `windowsAuthentication\s+enabled="true"\|<authentication\s+mode="Windows"` | block | OIDC / JWT; or Negotiate with Kerberos | S21 | COVERED: AUTH-WINDOWS |
| LNX-AUTH-NEGOTIATE-KERBEROS | Negotiate on Kestrel works on Linux only with Kerberos (keytab, realm, SPN) and 1:1 proxy affinity | cs: `AddNegotiate\(\|NegotiateDefaults\|Microsoft\.AspNetCore\.Authentication\.Negotiate` | block | Kerberos on image (krb5.conf, keytab) or move to OIDC | S21 | PARTIAL: AUTH-WINDOWS |
| LNX-AUTH-HTTPSYS | HTTP.sys (UseHttpSys) is Windows-only; Windows auth delegated to it | cs: `UseHttpSys\|HttpSysOptions\|HttpSysDefaults` | block | Kestrel + Negotiate | S21 | COVERED: HOST-HTTPSYS-IIS-INPROC |
| LNX-AUTH-WINDOWSIDENTITY | WindowsIdentity.Impersonate / GetCurrent for user context: Windows-only | cs/vb: `WindowsIdentity\.(Impersonate\|GetCurrent)\|WindowsImpersonationContext` | block | Delegate auth to token or DB | S21 | COVERED: API-WINDOWS-IDENTITY; AUTH-IMPERSONATION |
| LNX-AUTH-WINDOWS-PRINCIPAL | WindowsPrincipal / WindowsBuiltInRole role checks rely on Windows identity | cs/vb: `WindowsPrincipal\|WindowsBuiltInRole\|IsInRole\(WindowsBuiltInRole` | block | Claims from token or DB | K | GAP |
| LNX-AUTH-DIRECTORYSERVICES | System.DirectoryServices (ADSI) is Windows-only; LDAP via DirectoryServices.Protocols works on Linux | cs/vb: `System\.DirectoryServices\b\|DirectoryEntry\(\|DirectorySearcher` | block | System.DirectoryServices.Protocols (LDAP) | S5 | COVERED: WIN-DIRSERVICES |
| LNX-AUTH-ACCOUNTMANAGEMENT | PrincipalContext / UserPrincipal (AccountManagement) are Windows-only | cs/vb: `PrincipalContext\|UserPrincipal\|GroupPrincipal\|System\.DirectoryServices\.AccountManagement` | block | Protocols + LDAP queries | S5 | PARTIAL: WIN-DIRSERVICES |
| LNX-AUTH-SQL-INTEGRATED | Integrated Security / Trusted_Connection needs Kerberos or AD-joined host on Linux | cfg/cs/vb: `Integrated Security\s*=\s*(true\|SSPI\|yes)\|Trusted_Connection\s*=\s*(true\|yes)` | block | SQL auth via Secrets Manager, or Kerberos keytab (community guides; verify with driver docs) | K | COVERED: DATA-INTEGRATED-SECURITY |
| LNX-AUTH-MACHINEKEY | machineKey (ViewState, forms ticket keys) not used by Core; keys must be shared across tasks | cfg: `<machineKey` | block | Data Protection with shared keys | S21 | COVERED: AUTH-MACHINEKEY |
| LNX-AUTH-DEFAULT-CREDENTIALS | Outbound UseDefaultCredentials / DefaultCredentials need Kerberos/NTLM on Linux | cs/vb/cfg: `UseDefaultCredentials\s*=\s*true\|CredentialCache\.DefaultCredentials` | warn | Service credentials from Secrets Manager | S21 | COVERED: AUTH-DEFAULT-CREDENTIALS |
| LNX-AUTH-NEGOTIATESTREAM-NTLM | NegotiateStream / NTLM client flows need GSSAPI or Kerberos; NTLM is not available on Linux GSSAPI | cs/vb: `NegotiateStream\|NtlmClient` | block | Kerberos or token-based auth | K | GAP |
| LNX-AUTH-WSFED-ADFS | WS-Federation / WIF is Windows-centric | cfg/cs/vb: `microsoft\.identityServices\|WSFederationAuthenticationModule\|System\.IdentityModel\.Services` | block | OIDC / SAML library | S21 | COVERED: AUTH-WSFED |

## 10. Databases (SQL Server, ODBC, OLE DB, Oracle)

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-DATA-LOCALDB | LocalDB and (localdb) instances do not exist on Linux | cfg/cs/vb/test: `\(localdb\)\|LocalDB\|MSSQLLocalDB` | block | Test SQL container; dev DB | K | GAP |
| LNX-DATA-NAMED-INSTANCE | Named instances (`host\INSTANCE`, SQLEXPRESS) do not exist on Linux SQL Server | cfg/cs/vb: `Server\s*=\s*[^;"]*\\\\[A-Za-z0-9_]+` (e.g. `\\SQLEXPRESS`) | block | Host/port, or `host,port` | K | GAP |
| LNX-DATA-LOCAL-SERVER-ALIAS | `.`, `(local)` and `localhost\INSTANCE` names resolve to the container, not a DB host | cfg/cs/vb: `Server\s*=\s*(\.\|\(local\)\|localhost\\\\)` | block | Explicit DB host | K | GAP |
| LNX-DATA-ATTACH-DBFILENAME | AttachDbFilename (.mdf) with Windows paths | cfg/cs/vb: `AttachDbFilename\s*=` | block | Restore DB into server; no attach | K | GAP |
| LNX-DATA-ODBC-DRIVER-NAME | ODBC driver names like `{SQL Server}` or `{SQL Native Client}` are not installed in images | cfg/cs/vb: `Driver\s*=\s*\{(SQL Server\|SQL Native Client[^}]*)\}` | block | Install msodbcsql18 and use its name | K | PARTIAL: DATA-ODBC (generic), LS-ODBC-DSN |
| LNX-DATA-SQLCE | SQL Server Compact is Windows-only | cs/vb/cfg: `SqlServerCe\|System\.Data\.SqlServerCe` | block | Migrate to SQL Server or PostgreSQL | K | GAP |
| LNX-DATA-COLLATION | DDL or queries depend on Windows collation names; string ordering differs from app code | sql/cs: `COLLATE\s+[A-Za-z_]+` | warn | Explicit collation in queries; test | K | GAP |
| LNX-DATA-DB-MAIL | sp_send_dbmail depends on server mail profile; verify availability on Linux SQL Server | sql: `sp_send_dbmail` | info (verify) | Send mail from app (SES) | K | GAP |
| LNX-DATA-MSDTC | TransactionScope across connections needs MSDTC; distributed transactions not on Linux | cs/vb: `TransactionScope\(\|System\.Transactions` with >1 connection | block | One connection per transaction; outbox pattern | S3 | COVERED: DATA-DISTRIBUTED-TX; DB-MSDTC (sql) |
| LNX-DATA-FILESTREAM | FILESTREAM / FileTable use Windows file handles | sql/cs: `FILESTREAM\|FILETABLE\|GET_FILESTREAM_TRANSACTION_CONTEXT` | block | Store blobs in S3 | K | COVERED: DB-FILESTREAM |
| LNX-DATA-SQLDEPENDENCY | SqlDependency / SqlCacheDependency rely on Service Broker and notifications | cs/vb/cfg: `SqlDependency\|SqlCacheDependency` | warn | Polling or messaging | K | COVERED: DATA-SQLDEPENDENCY |
| LNX-DATA-CLR | SQL CLR assemblies do not run on Linux SQL Server | sql: `CREATE ASSEMBLY\|EXTERNAL NAME` | block | Move logic to app | K | COVERED: DB-CLR |
| LNX-DATA-XP-CMDSHELL | xp_cmdshell and OLE automation procedures | sql: `xp_cmdshell\|sp_OACreate` | block | Move to app / job | K | COVERED: DB-XP-CMDSHELL |
| LNX-DATA-LINKED-SERVER | Linked servers and OPENQUERY depend on OLE DB providers | sql: `OPENQUERY\|OPENROWSET\|sp_addlinkedserver` | warn | Explicit ETL | K | COVERED: DB-LINKED-SERVER |
| LNX-DATA-BULK-FILE | BULK INSERT / OPENROWSET(BULK) read server-side Windows paths | sql: `BULK INSERT\|OPENROWSET\(BULK` | block | App-side bulk copy | K | COVERED: DB-BULK-FILE |
| LNX-DATA-SQLBULKCOPY | SqlBulkCopy is supported; file paths inside it are not | cs/vb: `SqlBulkCopy` with local file paths | warn | Stream from S3 | K | COVERED: DATA-BULKCOPY |
| LNX-DATA-CROSS-DATABASE | Three-part names across databases (may be fine on same server) | cs/vb/sql: `\[?\w+\]?\.\[?\w+\]?\.\[?dbo\]?\.` | warn | Single DB or explicit config | S33 | COVERED: DB-CROSS-DATABASE, SQL-CROSS-DB |
| LNX-DATA-ERROR-NUMBER | Error-number logic is SQL Server-only; PostgreSQL SQLSTATE differs | cs/vb: `SqlException.*\.Number\|\.Number\s*==\s*\d{3,5}` | warn | Map by SQLSTATE per target | S33 | COVERED: DATA-SQL-ERROR-NUMBERS, DB-SQLERROR-NUMBER |
| LNX-DATA-OLEDB-JET | OLE DB / Jet / ACE providers are Windows-only | cs/vb/cfg: `Microsoft\.(Jet\|ACE)\.OLEDB\|Provider\s*=\s*Microsoft\.(Jet\|ACE)` | block | Replace with supported provider | S3 | COVERED: DATA-OLEDB |
| LNX-DATA-ORACLE-UNMANAGED | Unmanaged ODP.NET is Windows-only; managed driver works | cs/vb/proj: `Oracle\.DataAccess\|Oracle\.ManagedDataAccess` (verify) | block | Managed driver | S3 | COVERED: DATA-ORACLE-UNMANAGED |

## 11. Networking

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-NET-UDP-BROADCAST | UDP broadcast/multicast discovery does not cross VPC/ECS networking | cs/vb/cfg: `IPAddress\.Broadcast\|EnableBroadcast\s*=\s*true\|JoinMulticastGroup` | block | Service discovery (Cloud Map) | K | COVERED: LS-BROADCAST-MULTICAST |
| LNX-NET-HOSTS-FILE | Code or config relies on the server hosts file | cs/vb/cfg/ps1/sh: `(drivers\\\\etc\\\\hosts\|/etc/hosts)` | warn | Route 53 private zones | K | COVERED: LS-HOSTS-FILE |
| LNX-NET-DNS-MACHINENAME | Dns.GetHostEntry(Environment.MachineName) and NetBIOS names differ in containers | cs/vb: `Dns\.GetHostEntry\(\s*Environment\.MachineName` | warn | Explicit hostnames | K | GAP |
| LNX-NET-SOCKET-WINDOWS-OPTIONS | Windows-only socket options (ExclusiveAddressUse, SIO_* IOControl) throw or are ignored | cs/vb: `SocketOptionName\.ExclusiveAddressUse\|SIO_[A-Z_]+\|\.IOControl\(` | warn | Remove or guard with OperatingSystem checks | K | GAP |
| LNX-NET-WINHTTP-HANDLER | WinHttpHandler and WebRequestHandler are Windows / .NET Framework only | cs/vb/proj: `WinHttpHandler\|WebRequestHandler` | block | SocketsHttpHandler (default on .NET 5+) | K | GAP |
| LNX-NET-SERVICEPOINT-MANAGER | ServicePointManager settings (SecurityProtocol, connection limits) do not apply to HttpClient the same way | cs/vb: `ServicePointManager\.(SecurityProtocol\|ServerCertificateValidationCallback\|DefaultConnectionLimit\|Expect100Continue)` | warn | HttpClient / SocketsHttpHandler config | K | PARTIAL: SEC-OLD-TLS |
| LNX-NET-TLS-OLD-PROTOCOLS | SSL3/TLS1.0/1.1 disabled by OpenSSL or distro policy; pinned old protocols fail | cs/vb/cfg: `SecurityProtocolType\.(Ssl3\|Tls)\b\|SslProtocols\.(Ssl2\|Ssl3\|Tls\|Tls11)\b` | block | Remove pinning; TLS 1.2+ | S3 | COVERED: SEC-OLD-TLS |
| LNX-NET-CERT-VALIDATION-OFF | Certificate validation disabled in code | cs/vb: `ServerCertificateCustomValidationCallback\s*=\s*.*true\|RemoteCertificateValidationCallback.*true` | block | Fix trust (see LNX-CRY-PRIVATE-CA-TRUST) | K | COVERED: SEC-CERT-VALIDATION-OFF |
| LNX-NET-SYSTEM-PROXY | DefaultWebProxy / system proxy from Windows settings; Linux uses HTTP_PROXY/HTTPS_PROXY/NO_PROXY | cs/vb/cfg: `DefaultWebProxy\|GetSystemWebProxy\|UseProxy\s*=\s*true\|<defaultProxy` | warn | Environment variables; explicit proxy config | K | PARTIAL: NET-PROXY |
| LNX-NET-SMTP-PICKUP | SMTP pickup directory (IIS) is a local folder on Windows | cfg/cs/vb: `deliveryMethod="SpecifiedPickupDirectory"\|SmtpDeliveryMethod\.SpecifiedPickupDirectory` | warn | SES SMTP / API | S3 | COVERED: INT-SMTP-PICKUP-IIS; NET-SMTP (partial) |
| LNX-NET-SMTP-PORT25 | Port 25 blocked from ECS/VPC by default | cfg/cs/vb: `port\s*=\s*"?25"?` | warn | Port 587 with SES | K | COVERED: LS-SMTP-PORT25 |
| LNX-NET-NETSH-URLACL | netsh http urlacl / advfirewall are Windows commands used in setup scripts | ps1/sh/bat/yml/cs: `netsh\s+(http\|advfirewall)\|urlacl` | block | Container port config | K | GAP |
| LNX-NET-WCF-NETTCP | NetTcpBinding / netTcp, NetNamedPipeBinding and port sharing are not in CoreWCF | cfg/cs/vb: `netTcpBinding\|NetTcpBinding\|netNamedPipeBinding\|NetNamedPipeBinding\|net\.tcp\|net\.pipe` | block | HTTP/JSON or gRPC | S3 | COVERED: WCF-BINDING |
| LNX-NET-WCF-CLIENT | Generated WCF proxies reference GAC/System.ServiceModel classic | cs/vb/cfg: `System\.ServiceModel\.ClientBase\|svcutil\|<client>` | warn | Regenerate with dotnet-svcutil | S3 | COVERED: WCF-CLIENT |
| LNX-NET-LOCALHOST-DEP | Config expects service on localhost (sidecar assumption) | cfg/cs: `(localhost\|127\.0\.0\.1)[:/]` for downstream services | info | Service endpoints by config | K | COVERED: LS-LOCALHOST-SERVICE |

## 12. Interprocess communication and named kernel objects

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-IPC-NAMED-PIPE-ACL | Named pipe security (PipeSecurity, PipeAccessRule, pipe GetAccessControl) is Windows-only | cs/vb: `PipeSecurity\|PipeAccessRule\|PipeAccessControl\|GetAccessControl\(\)\|SetAccessControl\(` near Named pipe classes | block | Anonymous pipe / Unix socket / gRPC over TCP with auth | K | GAP |
| LNX-IPC-PIPE-PATH | Named pipe names of the form `\\.\pipe\name` are Windows paths | cs/vb/cfg: `\\\\\.\\pipe\\` and `\\\\\.\\pipe` | block | Logical pipe name (not path) | K | GAP |
| LNX-IPC-NAMED-MUTEX | Named Mutex, Semaphore, EventWaitHandle for cross-process use: behaviour and naming differ on Linux | cs/vb: `new (Mutex\|Semaphore\|EventWaitHandle)\([^)]*"` with Global\\ prefix | warn | Distributed lock (DynamoDB / Redis) | S33 | COVERED: API-NAMED-SYNC |
| LNX-IPC-NAMED-MMF | Named memory-mapped files for cross-process sharing are not portable | cs/vb: `MemoryMappedFile\.(CreateOrOpen\|CreateNew)\([^)]*"` | warn | Shared store / socket | K | COVERED: WIN-NAMED-MMF |
| LNX-IPC-WINDOW-MESSAGES | SendMessage / PostMessage / window messages are Windows-only | cs/vb: `SendMessage\|PostMessage\|user32\.dll` | block | Remove | K | PARTIAL: WIN-PINVOKE-WIN32 |

## 13. Windows-only APIs (inventory)

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-API-REGISTRY | Microsoft.Win32.Registry throws PlatformNotSupportedException | cs/vb: `Microsoft\.Win32\.Registry\|Registry\.(LocalMachine\|CurrentUser\|ClassesRoot\|Users)\|RegistryKey` | block | Configuration + SSM Parameter Store | S5 | COVERED: API-REGISTRY; WIN-REGISTRY |
| LNX-API-EVENTLOG | System.Diagnostics.EventLog is Windows-only | cs/vb/cfg: `EventLog\b\|System\.Diagnostics\.EventLog\|EventLogLoggerProvider` | block | ILogger to stdout (CloudWatch) | S5 | COVERED: API-EVENTLOG; WIN-EVENTLOG |
| LNX-API-WMI | System.Management / WMI is Windows-only | cs/vb: `System\.Management\|ManagementObjectSearcher\|ManagementClass\|ManagementScope` | block | Read metrics via SDK or OS files | S5 | COVERED: WIN-WMI |
| LNX-API-PERFCOUNTER | Windows performance counters (not on Linux) | cs/vb: `PerformanceCounter\|System\.Diagnostics\.PerformanceCounter` | warn | EventCounters / OpenTelemetry metrics | S5 | COVERED: API-PERFCOUNTER; WIN-PERFCOUNTER |
| LNX-API-SERVICECONTROLLER | ServiceController (controls Windows services) | cs/vb: `ServiceController\|System\.ServiceProcess` | warn | Remove or ECS-level control | S5 | COVERED: WIN-SERVICECONTROLLER |
| LNX-API-DRAWING | System.Drawing.Common is Windows-only from .NET 6 (GDI+) on server | cs/vb/proj: `System\.Drawing\.(Bitmap\|Graphics\|Image\|Font\|Imaging)\|System\.Drawing\.Common` | block (server) | SkiaSharp or ImageSharp | S7 | COVERED: API-DRAWING; WIN-DRAWING |
| LNX-API-PRINTING | PrintDocument / PrinterSettings / PageSettings and printer spooler are Windows-only | cs/vb: `PrintDocument\|PrinterSettings\|PageSettings\|System\.Drawing\.Printing` | block | PDF generation library (headless) | S7 | COVERED: INT-PRINTING |
| LNX-API-COM-INTEROP | COM interop and ComImport need Windows COM | cs/vb/proj: `\[ComImport\]\|\[ComVisible\|CoCreateInstance\|Interop\.(?!Npgsql)` | block | Replace COM component | S4 | COVERED: API-COM; WIN-COM-INTEROP |
| LNX-API-COMPLUS | System.EnterpriseServices (COM+) not supported | cs/vb/cfg: `System\.EnterpriseServices\|ServicedComponent\|ContextUtil` | block | Transactions via library | S4 | COVERED: API-ENTERPRISESERVICES |
| LNX-API-MSMQ | System.Messaging / MSMQ not available | cs/vb/cfg: `System\.Messaging\|MessageQueue\|MSMQ` | block | Amazon SQS | S5 | COVERED: API-MSMQ; WIN-MSMQ |
| LNX-API-SPEECH-UI | Speech, sound and desktop-only UI libraries | cs/vb/proj: `System\.Speech\|SoundPlayer\|SystemSounds\|System\.Windows\.Forms` in server code | block | Remove from server | S5 | COVERED: WIN-SPEECH-UI; WIN-SOUND |
| LNX-API-SYSTEM-EVENTS | Microsoft.Win32.SystemEvents (session, power, display events) | cs/vb: `SystemEvents\.` | warn | Remove or host-specific | K | COVERED: WIN-SYSTEMEVENTS |
| LNX-API-SERIAL-COM-PORT | COM1..COMn port names: Linux uses /dev/ttyS*, /dev/ttyUSB* | cs/vb/cfg: `"COM\d+"` | block | Port name in config; device mapping | K | COVERED: HV-LOCAL-DEVICE |
| LNX-API-DLLIMPORT-WIN32 | P/Invoke into kernel32, user32, advapi32, ole32, oleaut32, shell32, gdi32, netapi32, ws2_32, crypt32, wininet, winspool | cs/vb: `DllImport\("(kernel32\|user32\|advapi32\|ole32\|oleaut32\|shell32\|gdi32\|netapi32\|ws2_32\|crypt32\|wininet\|winspool\|msvcrt)\.dll"` | block | Replace with managed API or Linux native lib | S5 | COVERED: WIN-PINVOKE-WIN32; API-PINVOKE |
| LNX-API-DLLIMPORT-DLL-SUFFIX | Native library named with `.dll` suffix: Linux probes `name.so`, not `name.dll` | cs/vb: `DllImport\("[^"]+\.dll"\)` | block | Name without suffix; per-RID `.so` files | K | PARTIAL: WIN-PINVOKE-NATIVE |
| LNX-API-UNMANAGED-WCHAR-LONG | wchar_t is 4 bytes on Linux (2 on Windows); C `long` is 8 bytes on Linux x64 (4 on Windows): marshalling breaks | cs/vb: `UnmanagedType\.(LPWStr\|BStr)\|CharSet\.Unicode`; `\blong\b` in DllImport signatures | block | Explicit sized types; test on Linux | K | GAP |
| LNX-API-CALLING-CONVENTION | StdCall / ThisCall ignored on x64 Linux; Winapi maps to platform default | cs/vb: `CallingConvention\.(StdCall\|ThisCall\|Winapi)` | info | Use Cdecl for Linux libs | K | GAP |
| LNX-API-STA-THREADS | COM STA apartment threads: Windows-only | cs/vb: `\[STAThread\]\|ApartmentState\.STA\|SetApartmentState` | warn | Remove; MTA | K | COVERED: WIN-STA |
| LNX-API-REMOTING | .NET Remoting unsupported in .NET 6+ | cs/vb/cfg: `System\.Runtime\.Remoting\|MarshalByRefObject\|RemotingConfiguration` | block | gRPC / HTTP JSON | S4 | COVERED: API-REMOTING; API-CALLCONTEXT |
| LNX-API-CALLCONTEXT | CallContext.LogicalSetData / Remoting-era state (use AsyncLocal) | cs/vb: `CallContext\.` | block | AsyncLocal<T> | S4 | COVERED: API-CALLCONTEXT |
| LNX-API-XSLT-SCRIPT | XSLT script blocks (msxsl:script) unsupported | any: `msxsl:script\|<msxsl:script` | block | Rewrite transform | S4 | COVERED: API-XSLT-SCRIPT |
| LNX-API-WORKFLOW | Windows Workflow Foundation not in .NET 6+ | cs/vb/proj/cfg: `System\.Workflow\|WorkflowRuntime` | block | CoreWF or code | S4 | COVERED: API-WORKFLOW |
| LNX-API-SECURITY-IDENTIFIER | SecurityIdentifier / WellKnownSidType are Windows-only | cs/vb: `SecurityIdentifier\|WellKnownSidType` | block | Remove | K | GAP |
| LNX-API-DESKTOP-UI | Windows Forms / WPF / UI in server code | cs/vb/proj: `System\.Windows\.Forms\|System\.Windows\.(Controls\|Media)` | block | Split UI from server | S5 | COVERED: DESK-WINFORMS; DESK-WPF |
| LNX-API-FILE-ACL | FileSystemAclExtensions / FileSecurity / DirectorySecurity / FileSystemAccessRule are Windows-only | cs/vb: `FileSystemAclExtensions\|FileSecurity\|DirectorySecurity\|FileSystemAccessRule\|GetAccessControl\(\)` | block | Unix permissions in image | S5 | COVERED: WIN-ACL |

## 14. Web platform and IIS hosting

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-WEB-SYSTEMWEB | System.Web namespaces (not on .NET 8+) | cs/vb: `\bSystem\.Web\.(UI\|Mvc\|Http(?!Utility)\|Security\|SessionState\|Hosting\|Caching\|Routing)\b` | block | ASP.NET Core | S3 | COVERED: WEB-SYSTEMWEB-NS; WEB-SYSTEMWEB |
| LNX-WEB-HTTPCONTEXT-CURRENT | HttpContext.Current / HttpRuntime | cs/vb: `HttpContext\.Current\|HttpRuntime\.` | block | IHttpContextAccessor | S3 | COVERED: WEB-HTTPCONTEXT-CURRENT |
| LNX-WEB-MAPPATH | Server.MapPath / HostingEnvironment.MapPath | cs/vb/markup: `Server\.MapPath\|HostingEnvironment\.MapPath` | block | IWebHostEnvironment | S3 | COVERED: FILE-MAPPATH |
| LNX-WEB-GLOBAL-ASAX | Global.asax application events | file: `global\.asax$` | block | Program.cs / middleware | S3 | COVERED: WEB-GLOBAL-ASAX |
| LNX-WEB-VIEWSTATE | ViewState / postbacks | markup/cs: `__VIEWSTATE\|EnableViewState` | block | Not portable; redesign | S3 | COVERED: FE-VIEWSTATE |
| LNX-WEB-BUNDLING | System.Web.Optimization bundling | cs/vb/markup: `BundleConfig\|System\.Web\.Optimization\|@Scripts\.Render` | warn | Static asset pipeline | S3 | COVERED: FE-BUNDLING |
| LNX-WEB-CONTENT-REMOVE | Content Remove/Update drops wwwroot or views from publish output | proj: `<Content (Remove\|Update)="[^"]*(wwwroot\|Views)` | block | Remove the exclusion | K | GAP |
| LNX-WEB-RAZOR-COMPILE | Razor views compiled at build vs runtime; missing views (case) appear only at runtime | proj: `<RazorCompileOnBuild>false\|<RazorCompileOnBuild>true` changes; markup hits in test | warn | Compile on build; test all views on Linux | K | GAP |
| LNX-WEB-SESSION-INPROC | InProc session state: lost per task; sticky sessions needed | cfg: `<sessionState\s+mode="InProc"`; cs: `Session\[` | warn | Distributed cache or DB session | S33 | COVERED: IIS-SESSION-STATE; STATE-SESSION |
| LNX-WEB-SIGNALR-LEGACY | ASP.NET SignalR legacy (Owin) | cs/vb/js: `Microsoft\.AspNet\.SignalR` | warn | ASP.NET Core SignalR | S3 | COVERED: WEB-SIGNALR-LEGACY |
| LNX-HOST-INPROC-IIS | aspNetCore module with inprocess hosting; AspNetCoreModuleV2 | cfg: `AspNetCoreModuleV2\|hostingModel="inprocess"` | block | Kestrel in container | S3 | COVERED: HOST-HTTPSYS-IIS-INPROC; IIS-MODULES-HANDLERS |
| LNX-HOST-WEBCONFIG-PRESENT | web.config present in publish; ignored by Kestrel except ASP.NET Core module section | file: `(^\|/)web\.config$` | warn | Move settings to appsettings / env | S33 | COVERED: CFG-WEBCONFIG-APP |
| LNX-HOST-URL-REWRITE | IIS URL Rewrite rules in web.config are not applied by Kestrel | cfg: `<rewrite>\|<rule name=` | warn | UseRewriter middleware | S3 | COVERED: IIS-REWRITE |
| LNX-HOST-APPPOOL-IDENTITY | IIS application pool identities and IIS APPPOOL accounts | cfg/ps1/yml: `IIS APPPOOL\\\|ApplicationPoolIdentity\|applicationPools` | block | Container user; IAM task role | K | GAP |
| LNX-HOST-TOPSHELF | Topshelf (HostFactory) runs as Windows service: no Linux equivalent in code | cs/vb/proj: `Topshelf\|HostFactory\.(Run\|New)` | block | Generic host / BackgroundService in container | K | GAP |
| LNX-HOST-SERVICEBASE | ServiceBase / ServiceInstaller | cs/vb: `ServiceBase\|ServiceInstaller\|ServiceProcess` | block | Worker service (+systemd or ECS) | S18 | COVERED: WIN-SERVICE |
| LNX-HOST-USEWINDOWSSERVICE-ONLY | UseWindowsService without a Linux host path: no-op on Linux, service does not start under systemd | cs: `UseWindowsService\(` without `UseSystemd` | warn | Add Microsoft.Extensions.Hosting.Systemd for systemd hosts (ECS does not need it) | S18 | GAP |
| LNX-HOST-FORWARDED-HEADERS | Behind ALB: scheme/host/client IP lost; http redirects, cookie Secure flag and links wrong | cs: absence of `UseForwardedHeaders\|ForwardedHeadersOptions` | warn | UseForwardedHeaders with trusted proxies | K | GAP |
| LNX-HOST-PORT-80 | .NET 8+ container default port is 8080; port 80 mapping fails unless ASPNETCORE_HTTP_PORTS=80 | df/yml/task json: `EXPOSE\s+80\b`; `ASPNETCORE_URLS=http://\+?\*?:80\b`; `-p\s+\d+:80\b`; ALB target port 80 with app on 8080 | block | Set ASPNETCORE_HTTP_PORTS=8080 and matching target group port | S8 | GAP |
| LNX-HOST-HEALTHCHECK-CURL | Dockerfile HEALTHCHECK calls curl; .NET images do not ship curl by default [K: verify on image] | df: `HEALTHCHECK\s+CMD\s+curl` | warn | Use ECS health check on /health with a tool present, or built-in probe | S33 | GAP (DevTx KB uses it) |
| LNX-HOST-HTTPS-CERT-IN-IMAGE | PFX certificate copied into image and password in ENV (secret in image and history) | df: `COPY .*\.pfx\|Kestrel__Certificates__Default__Password=` | block | TLS at ALB; secret from Secrets Manager | S33 | COVERED: CFG-HARDCODED-SECRET (cfg only); GAP for df |
| LNX-HOST-DOTNET-BUILD-ON-HOST | Windows-only install tasks (IIS features) in provisioning scripts | ps1/yml: `Install-WindowsFeature\|Enable-WindowsOptionalFeature` | info | Remove for containers | K | GAP |

## 15. Containers and images

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-CTR-WINDOWS-BASE | Windows base image (servercore/nanoserver) cannot run on Linux ECS/EKS nodes | df: `FROM .*(windowsservercore\|nanoserver)` | block | Linux base | S3 | COVERED: HOST-WINDOWS-CONTAINER |
| LNX-CTR-LIBGDIPLUS | System.Drawing on Linux needs libgdiplus; EnableUnixSupport switch existed only in .NET 6 | df: `libgdiplus`; proj/cfg: `System\.Drawing\.EnableUnixSupport`; df: missing libgdiplus with System.Drawing | block | Replace library (SkiaSharp/ImageSharp) | S7 | GAP |
| LNX-CTR-FONTS | Server-side rendering (PDF, images, charts) needs fonts; no fonts = boxes or missing glyphs | proj: `SkiaSharp\|ImageSharp\|QuestPDF\|iText\|PdfSharp\|wkhtmltopdf\|Rotativa\|PuppeteerSharp\|DinkToPdf`; df: no `fonts-` package | warn | Install fonts in image (licensed corporate fonts) | S7 | PARTIAL: LIN-FONTS (cs/vb, low) |
| LNX-CTR-NATIVE-ARCH | Native .so/.dll built for x64 breaks on arm64 Graviton/Fargate ARM | proj/df/yml: `linux-arm64\|linux-x64` absent or mixed; native files | block | Multi-arch build or pick one arch | K | GAP |
| LNX-CTR-BUILD-ARCH | Image built on arm64 laptop runs on x86 ECS: `exec format error` | yml/sh: `docker build` without `--platform` | block | `--platform linux/amd64` (or arm64) explicit | K | GAP |
| LNX-CTR-NONROOT-NUMERIC | Non-root user set by name: Kubernetes runAsNonRoot cannot verify names | df: `^USER\s+(?!\d\|\$APP_UID)` | warn | `USER $APP_UID` (1654 in .NET 8+) | S27 | GAP |
| LNX-CTR-USER-MISSING | No USER directive: process runs as root | df: no `^USER\s` line | warn | Non-root user | S27 | GAP |
| LNX-CTR-TAG-MISMATCH | Build and runtime image tags differ or are unpinned (latest / no tag) | df: `FROM .*dotnet/(aspnet\|runtime\|sdk):(?!\d)`; sdk and aspnet major mismatch | warn | Pin tags by digest or major version | S33 | GAP |
| LNX-CTR-SDK-IN-FINAL-STAGE | Final stage uses sdk image: large attack surface and size | df: last `FROM` contains `/sdk:` | info | Use aspnet/runtime in final stage | S33 | GAP |
| LNX-CTR-DOCKERIGNORE | No .dockerignore: bin/obj, .vs, *.user and appsettings with secrets are copied | file: `.dockerignore` absent | warn | Add .dockerignore | K | GAP |
| LNX-CTR-SECRETS-COPIED | Secret or environment files copied into image | df: `COPY .*\.(env\|pfx\|p12\|key\|pem)\b\|COPY .*appsettings\.(Production\|Development)?\.json` | block | Inject at runtime (Secrets Manager / SSM) | S33 | COVERED: CFG-HARDCODED-SECRET (partial) |
| LNX-CTR-ASPNET-DEVELOPMENT | ASPNETCORE_ENVIRONMENT=Development in image: developer exception pages and dev settings | df/yml: `ASPNETCORE_ENVIRONMENT=Development` | warn | Set per environment at runtime | S33 | GAP |

## 16. Configuration and secrets

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-CFG-HARDCODED-SECRET | Passwords, keys, tokens in config or code (also a container image risk) | cfg/cs/vb: `(Password\|pwd\|secret\|apikey\|token)\s*[=:]\s*"?[^";\s]{6,}` (review hits) | block | Secrets Manager / SSM | S33 | COVERED: CFG-HARDCODED-SECRET |
| LNX-CFG-PROTECTED-SECTION | Protected configuration (DPAPI / RSA key container) cannot be decrypted in containers | cfg: `configProtectionProvider\|aspnet_regiis\|<configProtectedData` | block | Secrets Manager + config provider | S33 | COVERED: CFG-PROTECTED; CFG-PROTECTED-SECTION |
| LNX-CFG-CONFIGMANAGER | System.Configuration.ConfigurationManager for app settings; works but not IConfiguration | cs/vb: `ConfigurationManager\.(AppSettings\|ConnectionStrings)` | warn | IConfiguration | S5 | COVERED: CFG-CONFIGMANAGER; API-CONFIGMANAGER |
| LNX-CFG-TRANSFORMS | web.config / app.config transforms not applied in container builds | proj/file: `*.Release.config\|*.Production.config\|SlowCheetah` | info | Environment variables / appsettings | K | COVERED: CFG-TRANSFORMS |
| LNX-CFG-LOG-PATH | File logging to Windows path (log4net, NLog file targets) | cfg: `file(Name)?\s*=\s*"[A-Za-z]:\\\|value="[A-Za-z]:\\` in log4net/NLog | block | stdout logging | S33 | COVERED: LOG-FILE-TARGETS |

## 17. Logging, performance, GC and runtime

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-LOG-EVENTLOG | Event Log sink (Windows) | cfg/cs: `EventLogTraceListener\|EventLogLoggerProvider` | block | Console (stdout) | S18 | COVERED: API-EVENTLOG |
| LNX-LOG-ELMAH | ELMAH error log (System.Web) | cfg/cs: `elmah` | warn | Serilog / ILogger | K | COVERED: LOG-ELMAH |
| LNX-LOG-TRACE-LISTENER | System.Diagnostics trace listeners (file or Windows) | cfg: `<add type="System\.Diagnostics\.` | warn | ILogger | K | COVERED: LOG-TRACE |
| LNX-PERF-WORKING-SET | Process working set / private memory differ in meaning (RSS on Linux) | cs/vb: `\.(WorkingSet64\|PrivateMemorySize64\|VirtualMemorySize64)` | warn | Use GC.GetGCMemoryInfo / cgroup numbers | K | GAP |
| LNX-PERF-GC-CONTAINER-LIMIT | Container memory limit drives GC heap (75% default in containers); no limit set means unbounded | cfg/proj/df/task json: `GCHeapHardLimit\|ServerGarbageCollection\|ConcurrentGarbageCollection`; task def: no `memory` | info | Set task memory and GC heap limit; load test | S19 | GAP |
| LNX-PERF-PROCESSOR-COUNT | Environment.ProcessorCount reflects cgroup CPU limit; thread-pool sizing changes with Fargate task size | cs/vb: `Environment\.ProcessorCount` | info | Load test; explicit thread settings if needed | S19 | GAP |
| LNX-PERF-CPU-GROUPS | GC CpuGroup / Thread_UseAllCpuGroups are Windows-only settings | cfg/proj: `System\.GC\.CpuGroup\|Thread_UseAllCpuGroups\|DOTNET_GCCpuGroup` | info | Remove on Linux | S19 | GAP |
| LNX-PERF-THREAD-ABORT | Thread.Abort / Suspend / Resume unsupported in .NET 5+ | cs/vb: `Thread\.(Abort\|Suspend\|Resume)\(` | warn | Cooperative cancellation | K | COVERED: API-THREAD-ABORT |

## 18. Scheduling, messaging, serialization

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-SCH-TASK-SCHEDULER | Windows Task Scheduler jobs (schtasks, TaskService) | cs/vb/ps1/yml: `Microsoft\.Win32\.TaskScheduler\|schtasks\|TaskService` | block | EventBridge Scheduler + ECS task | S33 | COVERED: BG-TASK-SCHEDULER |
| LNX-SCH-HANGFIRE-QUARTZ | Hangfire / Quartz server config with Windows paths or SQL Server locks | cfg/cs: `Hangfire\|Quartz` with SQL Server connection | info | Test on Linux DB | K | COVERED: BG-HANGFIRE-QUARTZ |
| LNX-SCH-WEB-TIMER | Timers / background work inside web processes run per task (duplicate jobs) | cs/vb: `System\.Timers\.Timer\|new Timer\(` in Controllers/Global | warn | Worker service | K | COVERED: STATE-WEB-BACKGROUND |
| LNX-MSG-MSMQ | MSMQ transports (NServiceBus MSMQ, System.Messaging) | cs/vb/cfg: `MsmqTransport\|System\.Messaging\|msmq` | block | SQS transport | S5 | COVERED: WIN-MSMQ; API-MSMQ |
| LNX-SER-BINARYFORMATTER | BinaryFormatter throws on .NET 9+ (even with old settings) | cs/vb: `BinaryFormatter` | block | System.Text.Json / protobuf | S20 | COVERED: API-BINARYFORMATTER |
| LNX-SER-OTHER-FORMATTERS | SoapFormatter, NetDataContractSerializer, LosFormatter, ObjectStateFormatter: removed or unsupported on .NET 5+ [K: verify version] | cs/vb: `SoapFormatter\|NetDataContractSerializer\|LosFormatter\|ObjectStateFormatter` | block | Json/XML/contract serializers | K | GAP |
| LNX-SER-TYPENAMEHANDLING | Json.NET TypeNameHandling (unsafe deserialisation) | cs/vb/cfg: `TypeNameHandling\.(All\|Auto\|Objects\|Arrays)` | block | None; explicit types | K | COVERED: SEC-TYPENAMEHANDLING |

## 19. CI/CD and tests

| ID | What breaks on Linux | Detect (regex / file types) | Sev | Fix | Src | Already in |
|---|---|---|---|---|---|---|
| LNX-CI-WINDOWS-RUNNER | Pipeline runs on Windows agent; Linux image build not exercised | yml: `runs-on:\s*windows\|vmImage:\s*['"]?windows-` | warn | Add Linux build job | S33 | COVERED: BUILD-WINDOWS-CI |
| LNX-CI-MSBUILD-EXE | msbuild.exe / nuget.exe / vstest.console.exe in pipeline | yml/ps1/sh: `msbuild\.exe\|nuget\.exe\|vstest\.console\.exe` | block | `dotnet build`, `dotnet test`, `dotnet restore` | K | GAP |
| LNX-CI-POWERSHELL-EXE | `powershell.exe` step (Windows PowerShell) instead of pwsh | yml: `\bpowershell(\.exe)?\s` | block | `pwsh` | K | PARTIAL: BUILD-WINDOWS-CI |
| LNX-CI-VSTEST | MSTest v1 / Coded UI test runner | proj/cs: `Microsoft\.VisualStudio\.TestTools\.UITest\|CodedUITest` | warn | Migrate to MSTest/xUnit on dotnet test | S33 | COVERED: TEST-CODED-UI |
| LNX-CI-DOCKER-PLATFORM | docker build without target platform on Apple silicon runners | yml/sh: `docker build(?!.*--platform)` | block | Explicit `--platform` | K | GAP |
| LNX-CI-GITATTRIBUTES | No .gitattributes: CRLF and exec bit drift between Windows and Linux checkouts | file: `.gitattributes` absent or without `text=auto`/`eol=lf` | warn | Add .gitattributes | K | GAP |
| LNX-CI-SIGNTOOL | signtool / sn.exe in pipeline (Windows-only signing) | yml/ps1: `signtool\|sn\.exe` | warn | Remove for containers; sign image if needed | K | GAP |
| LNX-CI-TEST-ASSUMPTIONS | Tests assume Windows paths, case-insensitive file or URL matching, or LocalDB | test cs/vb: `"[A-Za-z]:\\\\\|StringComparison\.OrdinalIgnoreCase` in asserts | warn | Platform-neutral test fixtures | K | PARTIAL: FILE-DRIVE-LETTER |

## 20. Summary of gaps (for the rules team)

Totals: 240 checks. Status: 111 COVERED by an existing rule, 29 PARTIAL, 100 GAP. Severity: 130 block, 91 warn, 19 info. Three rows originally marked `high` were mapped to block or warn to fit the legend.

Top gaps versus existing rules:

1. **Case sensitivity has no working rule.** `FILE-CASE-MISMATCH` is named in `migration-assessment/references/linux-pitfalls.md` but is not in `rules.json` or any script. Add literal-to-disk comparison for `.cshtml`, `~/...` links, `GetManifestResourceStream`, `appsettings.{env}.json`, assembly/type names.
2. **Container runtime gaps.** No rules for: port 80 vs 8080 (`ASPNETCORE_HTTP_PORTS`), non-root (`USER $APP_UID`), read-only root FS (only a state-scale rule), ICU/tzdata/invariant in base image, libgdiplus, fonts, arm64 vs amd64, `.dockerignore`, secrets copied into image.
3. **Time zone and culture rules are narrow.** Only Windows IDs and hardcoded culture are flagged. Missing: IANA IDs on Windows, tzdata-less images, implicit culture comparisons, sorting, ICU missing, invariant mode switch.
4. **Named pipes, sockets, DNS, LocalDB, CE, collation, named instances, `.dll` probing.** No rules.
5. **Crypto is under-rated.** `WIN-CNG-CSP` is medium; RSACng/CngKey use on Linux should be high. ASP.NET Data Protection key persistence and private-CA trust are absent.
6. **Process/CI.** No rules for msbuild.exe / vstest / powershell.exe steps, docker `--platform`, `.gitattributes`, exec bit on scripts, `Process.ProcessName` matching, PID 1 shell-form ENTRYPOINT.
7. **Host.** Topshelf not covered (WIN-SERVICE is ServiceBase only). Missing ForwardedHeaders for ALB, AppPool identity, `UseWindowsService` without systemd.

## 21. AWS Transform for .NET: what it checks, transforms and leaves

Sources: [S22] Visual Studio guide, [S23] how it works, [S24] capabilities, [S25] prescriptive guidance, [S26] Porting Assistant status.

**Checks (what it flags)**
- Linux readiness report: a downloadable report of Windows-specific items the tool could not fix at build time. In Visual Studio it exports as CSV with project, file, description, issue and recommendation columns [S22].
- Linux porting status column in the code groups table: items that need manual file updates before the app runs on Linux [S22].
- Build verification locally and in its remote build environment, and unit test execution [S23, S24].

**Transforms (what it changes automatically)**
- Replaces outdated C# with Linux-compatible C# versions; upgrades .NET Framework to cross-platform .NET; replaces packages, libraries and APIs; sets up middleware and runtime configuration; handles IIS and WCF components; rewrites deprecated or inefficient code for Linux compatibility [S23].

**Leaves (what it does not do or hands back)**
- NextSteps.md: remaining porting work, with prompts for an AI code companion or a new run [S22, S23].
- Not transformed: Win32 DLLs without core-compatible libraries; repositories without .NET solutions; web site projects without a project file [S24].
- No container-specific readiness checks, Dockerfile generation or image build steps are described in the AWS docs found. The only container material is marketplace listings [search only].

**Supported scope [S24]**
- From: .NET Framework 3.5, .NET Core 3.1, .NET 5 through 10. To: .NET 8, .NET 10, .NET Standard (class libraries).
- Languages: C#, VB.NET. Project types listed: class libraries, console apps, ASP.NET (MVC, Web API, Web Forms), test projects (NUnit, xUnit, MSTest), WCF services, desktop (WinForms, WPF), Xamarin, ASMX.

**Porting Assistant for .NET [S26]**
- AWS states it is no longer open to new customers from 7 Nov 2025 and points to AWS Transform. Its rule catalogue was not retrieved (the datastore repo is the likely location; not confirmed).

**AWS prescriptive guidance (Linux containers) [S25]**
- Option for porting to Linux containers on ECS/EKS, with Fargate or EC2; tools named: Porting Assistant and App2Container (A2C). States that manual code changes are needed for the port to compile with dependencies.

**Not covered in this run:** AWS Microservice Extractor for .NET (not researched).

## 22. DevTx: Linux content

Source: `<toolkit>\transformer\common\migration-knowledge\dotnet\19-linux-containerization.md` [S33]. Other hits in the repo (Java 17-containerization.md, dotnet 05-hosting, 21-system-drawing-migration.md, 28-dotnet-remoting-migration.md, prompts/dotnet-upgrade-prompt.txt, README) were listed but not read in full for this catalogue. `21-system-drawing-migration.md` and `28-dotnet-remoting-migration.md` are the most likely to overlap with section 4 and section 13 and should be read next.

**What the KB covers**
- Prerequisites (Program.cs, wwwroot, appsettings), a multi-stage Dockerfile on `dotnet/sdk:8.0` and `dotnet/aspnet:8.0` with `ASPNETCORE_URLS=http://+:8080` and `EXPOSE 8080`.
- Build and run commands; environment overrides with `__` separators; docker-compose with a SQL Server service.
- Logs to stdout (Serilog console, CloudWatch or ELK suggestions).
- HTTPS via a mounted PFX with Kestrel certificate env vars.
- Health endpoint and a `HEALTHCHECK` line.
- Deployment table: ECS/Fargate, App Service for containers, Kubernetes, on-prem with systemd.
- GitHub Actions example pushing to Docker Hub.
- Troubleshooting table, best practices, validation checklist.
- Section 14: SmartStore.NET container notes (publish the web host only, run migrations in the entrypoint, exclude optional code).

**Gaps and defects in the KB (for the DevTx team)**
- No Linux readiness content: no case sensitivity, path separators, ICU/invariant mode, tzdata, fonts or libgdiplus, time zones, culture, encodings, CRLF, exec bit, ProcessName or shell calls, Windows-only APIs, DPAPI, Data Protection key persistence, Windows auth/Kerberos, SQL integrated security, certificate store, named pipes, Topshelf, or IIS-to-Kestrel mapping.
- `HEALTHCHECK CMD curl` assumes curl is in the image; verify and prefer a tool that is present.
- The Dockerfile sets no `USER`, yet the troubleshooting table says to set it. Non-root is not shown (use `USER $APP_UID`).
- Secrets: the sample connection string contains a hard-coded password, and the HTTPS example sets the PFX password in an ENV line. Both put secrets in the image or history. Do not copy these samples as-is.
- Inconsistent environment variables: `DOTNET_ENVIRONMENT` is mentioned in text while compose sets `ASPNETCORE_ENVIRONMENT`.
- Image target uses Docker Hub, not ECR, and has no ECS task definition, port mapping for ALB, read-only FS or health check wiring.
- `version: '3.8'` in compose is obsolete (cosmetic).
- Section 14 runs database migrations in the entrypoint; with several ECS tasks this races. Use a one-off task instead.

## 23. Sources

Microsoft Learn (fetched unless noted):
- [S1] Platform compatibility analyzer: https://learn.microsoft.com/en-us/dotnet/standard/analyzers/platform-compat-analyzer
- [S2] CA1416 rule: https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/quality-rules/ca1416 (linked from S1; not fetched)
- [S3] Upgrade .NET apps overview (porting): https://learn.microsoft.com/en-us/dotnet/core/porting/
- [S4] .NET Framework technologies unavailable on .NET 6+: https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable
- [S5] Windows Compatibility Pack: https://learn.microsoft.com/en-us/dotnet/core/porting/windows-compat-pack
- Portability analyzer (deprecated, read): https://learn.microsoft.com/en-us/dotnet/standard/analyzers/portability-analyzer
- [S7] System.Drawing.Common Windows-only: https://learn.microsoft.com/en-us/dotnet/core/compatibility/core-libraries/6.0/system-drawing-common-windows-only
- [S8] ASP.NET Core default port 8080: https://learn.microsoft.com/en-us/dotnet/core/compatibility/containers/8.0/aspnet-port
- [S9] Globalization and ICU: https://learn.microsoft.com/en-us/dotnet/core/extensions/globalization-icu
- [S10] Globalization config (invariant, NLS): https://learn.microsoft.com/en-us/dotnet/core/runtime-config/globalization
- [S11] Cross-platform cryptography: https://learn.microsoft.com/en-us/dotnet/standard/security/cross-platform-cryptography
- [S12] ProtectedData: https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.protecteddata
- [S13] ProcessStartInfo.UseShellExecute: https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo.useshellexecute
- [S14] Path.GetInvalidFileNameChars: https://learn.microsoft.com/en-us/dotnet/api/system.io.path.getinvalidfilenamechars
- [S15] Environment.GetFolderPath: https://learn.microsoft.com/en-us/dotnet/api/system.environment.getfolderpath (Unix note linked: https://learn.microsoft.com/en-us/dotnet/core/compatibility/core-libraries/8.0/getfolderpath-unix, not fetched)
- [S16] CodePagesEncodingProvider: https://learn.microsoft.com/en-us/dotnet/api/system.text.codepagesencodingprovider
- [S17] FileSystemWatcher: https://learn.microsoft.com/en-us/dotnet/api/system.io.filesystemwatcher
- [S18] Windows service worker (BackgroundService): https://learn.microsoft.com/en-us/dotnet/core/extensions/windows-service
- [S19] Garbage collector config: https://learn.microsoft.com/en-us/dotnet/core/runtime-config/garbage-collector
- [S20] BinaryFormatter removal (.NET 9): https://learn.microsoft.com/en-us/dotnet/core/compatibility/serialization/9.0/binaryformatter-removal
- [S21] ASP.NET Core Windows authentication: https://learn.microsoft.com/en-us/aspnet/core/security/authentication/windowsauth
- Time zone names page returned 404 when fetched; not used.

AWS:
- [S22] AWS Transform, Visual Studio: https://docs.aws.amazon.com/transform/latest/userguide/dotnet-ide-vs.html
- [S23] AWS Transform, how it works: https://docs.aws.amazon.com/transform/latest/userguide/dotnet-ide-how.html
- [S24] AWS Transform, .NET capabilities and limitations: https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html
- [S25] Re-architecting as a Linux container: https://docs.aws.amazon.com/prescriptive-guidance/latest/modernization-net-applications/refactor-linux.html
- [S26] Porting Assistant for .NET: https://aws.amazon.com/porting-assistant-dotnet/

Community (search results, not official):
- [S27] Rootless containers, UID 1654 and USER $APP_UID: https://devblogs.microsoft.com/dotnet/securing-containers-with-rootless
- [S28] .NET container images, ICU and tzdata in Alpine/chiseled: https://github.com/dotnet/dotnet-docker/discussions/4995
- [S29] Cross-platform time zones with .NET Core: https://devblogs.microsoft.com/dotnet/cross-platform-time-zones-with-net-core/
- [S30] Case sensitivity write-up: https://www.benlocke.co.uk/case-sensitivity/
- [S31] URL case sensitivity and assembly loading: https://blogs.msdn.microsoft.com/junfeng/2005/03/20/url-case-sensitivity-and-assembly-loading/
- [S32] Umbraco thread on case-sensitive file names: https://discord-chats.umbraco.com/t/22323315/handling-case-sensitivity-of-filenames-when-transferring-to-?t=v2

Local:
- [S33] DevTx KB 19 and migration-assessment rules (see section 22 and the rule catalogues named in section 23).
- Migration-assessment linux-pitfalls.md: `<skills-source>\skills\migration-assessment\references\linux-pitfalls.md`
- Rule catalogue: `<skills-source>\skills\migration-assessment\scripts\data\rules.json`
- Residue catalogue: `<skills-source>\skills\dotnet-modernization\scripts\data\residue_rules.json`
- lift-and-shift-assessment and nonnet-dependency-scan: searched for Linux content; none found.

Not fetched, knowledge only (marked [K]): case-sensitive env var names, named pipe ACLs, wchar_t and long sizes, DllImport `.dll` probing, Socket.ExclusiveAddressUse, WinHttpHandler, Process.ProcessName truncation, Data Protection key persistence defaults, curl presence in .NET images, shell-form ENTRYPOINT signal handling, arm64 vs amd64 image mismatch. Verify these before shipping rules.
