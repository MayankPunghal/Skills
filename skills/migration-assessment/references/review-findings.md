# Reviewing findings (judgment, with evidence)

Scanners find patterns; the reviewer decides what they mean. Review is required for every Blocker/High finding that is not Confirmed, and recommended for Likely Highs. `verify_report.py` fails while uncertain Blocker/High findings have no verdict.

## Token-economical workflow

1. **List what needs review:**

   ```bash
   python <skill>/scripts/review_queue.py --repo <repo>
   ```

   It prints the finding ID, rule, evidence `file:line` and, for each evidence file, the graph blast radius (how many files depend on it).
2. **For each item, read only the evidence lines plus about 15 lines around them.** Use a targeted read with an offset, never whole files.
3. **Use graphify to decide reachability and impact** instead of browsing folders:
   - `graphify affected "<ClassName>" --graph assessment/graphs/<repo>/graphify-out/graph.json --depth 2` shows who depends on the code that uses the Windows-only API.
   - `graphify path "<Controller>" "<ClassUsingApi>" --graph …` tells you whether a user-facing entry point reaches it.
   - `graphify explain "<Class>" --graph …` gives a one-paragraph orientation.
   - `graphify query "where are files written to disk" --graph … --budget 600` finds the related code.
4. **Record verdicts** in `assessment/reviews/<repo>.json`:

   ```json
   {"eshop:WIN-REGISTRY:src-app-app-csproj": {"verdict": "confirmed", "note": "Reads licence key at startup (LicenseService.cs:41); move to Parameter Store.", "reviewer": "agent", "date": "2026-10-02"},
    "eshop:STATE-STATIC-MUTABLE:src-app-app-csproj": {"verdict": "dismissed", "note": "Read-only lookup cache rebuilt per instance; safe when scaled out."},
    "eshop:HV-MACHINE-NAME:src-web-web-csproj": {"verdict": "adjusted", "severity": "Low", "note": "Machine name only written to session for diagnostics."}}
   ```

   - **Verdicts:** `confirmed` (raises confidence to Confirmed), `dismissed` (removed from the report and the estimate), `adjusted` (severity, confidence, fix or alternative changed).
   - **Notes appear in the report.** Write them for the client: specific, with `file:line`.
5. **Add findings the scanner cannot see** (judgment from reading code) in `assessment/reviews/<repo>.manual.json`.
   - Each one must have evidence, or `verify_report.py` fails:

   ```json
   [{"rule": "MAN-INTEGRATION-DIRECTION", "category": "dependencies", "title": "Order status arrives from SAP via a polling job, not an inbound API",
     "severity": "Medium", "confidence": "Confirmed", "project": "src/Jobs/Jobs.csproj",
     "evidence": [{"file": "src/Jobs/SapPoller.cs", "line": 57, "text": "var rows = client.GetChangedOrders(since);"}],
     "why": "...", "fix": "...", "alt": "", "effort_key": "small-change"}]
   ```

6. **Rerun:** `classify_apps.py`, then `estimate_effort.py`, then `build_report.py`. Rescanning never loses reviews, because verdicts are keyed by finding ID.

## Judgment calls the scanner leaves to you

| Situation | Decide |
| --- | --- |
| Windows-only API in a desktop project | Irrelevant to Linux if the desktop app is retained. Confirm, but the estimate already excludes it for Retain apps |
| `using` of a Windows namespace only | Usually unused; the scanner already downgrades it. Confirm by searching for the namespace's types |
| Static collections | Read-only lookup tables are fine; mutable per-user state is not |
| `DateTime.Now` | Decide whether a business rule depends on local time (cut-offs, reports, schedules) |
| Internal host names | Identify the system (config key names, class names around the call); add it to the dependency narrative |
| Hard-coded secret literal | Confirm it is a real credential (not a test value) and recommend rotation. **Never copy the value** |
| WCF bindings | Read the binding configuration (security mode, transport). CoreWCF supports BasicHttp, NetTcp and WSHttp with limits |
| Integration direction | Who calls whom. Inbound endpoints vs outbound calls vs polling jobs. Record as a manual finding if it changes the plan |

## Confidence scale

| Level | Meaning |
| --- | --- |
| **Confirmed** | Seen in code and its effect is clear |
| **Likely** | The pattern is present, but its use was not fully traced |
| **Needs verification** | Depends on runtime, data or infrastructure we cannot see. Pair with an open question |
