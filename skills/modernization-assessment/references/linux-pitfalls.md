# Linux pitfalls in real .NET migrations

What breaks after the code compiles, and the rule that catches each one.

| Pitfall | Why | Rule / check | What to do |
| --- | --- | --- | --- |
| **Case-sensitive file names** | `~/Content/site.css` vs `Site.css` works on Windows (NTFS is case-insensitive) and 404s on Linux | `FILE-CASE-MISMATCH` (literals checked against the files on disk) | Fix the literal or the file; add a CI check on Linux |
| **Path separators** | `\` is a valid filename character on Linux | `FILE-BACKSLASH` | `Path.Combine`, `/` |
| **Drive letters, UNC, %VARS%, special folders** | Do not exist on Linux or containers | `FILE-DRIVE-LETTER`, `NET-UNC-SHARE`, `FILE-WIN-FOLDERS` | Configured paths on mounted storage / S3 |
| **Time zones** | Hosts and containers run UTC; Windows TZ IDs resolve only through ICU; invariant mode breaks conversions | `TZ-WINDOWS-ID`, `TZ-LOCAL-TIME`, `TZ-SQL-LOCAL-TIME` | Explicit business time zone; IANA IDs or conversion; `tzdata` + ICU in the image |
| **Culture / string comparison** | ICU (Linux) vs NLS (Windows on older .NET Framework) differ in sorting, ligatures, `IndexOf` with zero-weight characters, day-name abbreviations | `CULT-HARDCODED` | `StringComparison.Ordinal` for identifiers (CA1307/CA1309); request localization; test formatting |
| **Globalization invariant mode** | Small images (Alpine, chiseled) may default to invariant mode: cultures and time-zone conversion lose data | image review | Install `icu-libs`/`tzdata` or use full images |
| **Fonts / GDI** | System.Drawing throws; SkiaSharp/ImageSharp need fonts installed in the image | `WIN-DRAWING` | Add fonts (`fonts-dejavu`, licensed corporate fonts) to the image |
| **Line endings** | `Environment.NewLine` is `\n`; parsers splitting on `\r\n` or byte-compared files differ | `FILE-CRLF` | Accept both on input; set `.gitattributes` |
| **Encodings** | `Encoding.Default` is UTF-8 on .NET; code pages need a provider | `FILE-ENCODING` | `CodePagesEncodingProvider`; explicit encodings |
| **Max path / long paths** | Rarely an issue on Linux; Windows-side tools may still hit 260 chars | — | — |
| **TLS** | OpenSSL negotiates; pinned old protocols fail | `SEC-OLD-TLS` | Remove pinning |
| **Kerberos/NTLM** | No machine identity on Linux | `AUTH-*`, `DATA-INTEGRATED-SECURITY` | Keytab or move to SQL auth / OIDC |
| **Distributed transactions** | Not supported on Linux | `DATA-DISTRIBUTED-TX` | One connection per transaction |
| **Process/permissions** | No `cmd.exe`, no registry, different file permissions | `WIN-SHELL-EXEC`, `WIN-REGISTRY`, `WIN-ACL` | Library calls, configuration, IAM |
| **Memory/GC in containers** | Container limits; server GC defaults | — | Set `DOTNET_GCHeapHardLimit` / container limits during performance testing |
