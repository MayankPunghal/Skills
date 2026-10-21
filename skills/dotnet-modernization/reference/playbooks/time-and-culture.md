# Playbook: time zones, dates and culture

**Rules:** TZ-WINDOWS-ID, TZ-LOCAL (residue); LNX-TZ-*, LNX-CUL-*, LNX-ENC-* (Linux readiness).
**Engines:** neither engine changes time or culture behaviour. Claude does, because the container runs in UTC and uses ICU, so code that compiled fine gives different answers.

## Time zones

- **The container's clock is UTC.** `DateTime.Now`, `DateTime.Today` and `ToLocalTime()` returned the server's zone on Windows (often US Eastern); now they return UTC. Decide per use: business time → convert explicitly from UTC to the business zone; timestamps → `DateTime.UtcNow` / `DateTimeOffset.UtcNow`. Do not set `TZ` in the image to hide it unless the client accepts that as the decision.
- **Zone IDs:** .NET 6+ on Linux accepts both Windows IDs ("Eastern Standard Time") and IANA IDs ("America/New_York") through ICU, so `FindSystemTimeZoneById("Eastern Standard Time")` works **if** ICU and tzdata are in the image. Prefer IANA IDs in new code and configuration; `TimeZoneInfo.TryConvertWindowsIdToIanaId` for stored Windows IDs.
- `TimeZoneInfo.DisplayName`, `StandardName` differ between Windows and Linux: never compare or persist them.
- Images: Alpine and chiseled images lack tzdata (and chiseled lacks ICU) by default: use the full `aspnet` image, `-extra` chiseled variants, or install `tzdata` + `icu-libs`.
- Dates in SQL: `GETDATE()` in procedures returns the database server's zone; on RDS it is UTC unless the parameter group sets one. Match the code ([raw-sql-and-data-access.md](raw-sql-and-data-access.md#types-dates-and-names)).
- Tests: run them with the business zone and with UTC (`TZ=` in the test container) to catch hidden local-time assumptions.

## Culture

- .NET on Linux uses ICU; .NET Framework on Windows used NLS. String comparison, sorting, `IndexOf` with special characters and some formatting differ.
- Identifiers, keys, file names, protocol values → `StringComparison.Ordinal` / `OrdinalIgnoreCase`, `ToUpperInvariant`, `CultureInfo.InvariantCulture` for parsing and formatting (CA1305, CA1307, CA1309, CA1310 on).
- User-facing text → the request culture (`UseRequestLocalization`), explicit, not the thread default.
- The container's default culture is invariant-like (`LANG` unset): number and date formatting that relied on the server's en-US culture changes. Set the culture explicitly where output format matters (CSV, XML feeds, emails).
- `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=true` breaks culture data and time-zone conversion: only for apps proven not to need either.

## Encodings and line endings

- `Encoding.GetEncoding(1252)` and other code pages need `Encoding.RegisterProvider(CodePagesEncodingProvider.Instance)` at startup.
- `Encoding.Default` is UTF-8 on .NET (it was the ANSI code page on Windows): read and write with explicit encodings.
- `Environment.NewLine` is `\n`: parsers that split on `\r\n` and byte-compared files break; accept both on input.

## Done when

No TZ-* residue; every `Now`/`Today` has a recorded decision; tests pass in UTC and in the business zone; file and feed outputs replay byte for byte.
