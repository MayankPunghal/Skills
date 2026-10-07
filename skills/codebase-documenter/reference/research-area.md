# research-area — read one area in depth, write a verified note

The research note is the source of truth for the pages. Pages are written from notes; notes are written from code. Never write a page from memory.

## Protocol (per area)

1. **Scope** — open the note (`docs/_notes/<id>.md`); confirm paths and communities.
2. **Orient with the graph (cheap)** — `code_graph.py ask "<area topic>" --budget 800`; `graphify explain "<main class>"`; `graphify god-nodes` hubs that sit in this area; read the community's wiki page. Once the reference is built, `trace_flow.py <entry point>` shows each journey's call tree with parameters ([flows.md](flows.md)); note the journeys worth a flow.
3. **Read fully** — controllers / endpoints, services, view models, validators, key views, stored procedures, triggers, jobs. Large engines (pricing, validation, payload builders) are read top to bottom, not skimmed. `--find`-style greps are for locating, not for understanding.
4. **Record facts in business terms**, each verified, into the template sections:
   - Screens / endpoints: what each action does, inputs, rules, side effects (emails, documents, statuses), who may call it.
   - Rules & calculations: numbered steps for engines; exact conditions and thresholds; ids and flags **checked against enums and seed data**.
   - Data: tables / collections read and written; procedures called.
   - Integrations: trigger, config key names (never values), payload builder, authentication, response handling, logging, retries.
   - Permissions: claims / roles / attributes; anonymous or unauthenticated entry points (check what a custom "AllowAnonymous" really skips).
   - Defects / risks: file + concrete failure scenario (DEF / SEC candidates). Dead code, TODOs, fake / test endpoints left in production.
   - Open questions: what the repository cannot answer (schedules, servers, external system behaviour).
   - Run-time wiring (C#, from `docs/reference/dependency-injection.md` / `docs/agent/di.json`, then confirmed in code): for every service the area uses, which class the container injects in which host and with which lifetime; decorators wrapped around it; keyed / named variants and who picks which key; abstract or virtual methods and the overrides that run; messages sent and the handler that receives each; events raised and their subscribers; delegates, method groups and lambdas stored and called later; background jobs enqueued; filters / middleware that run around the area's endpoints; partial classes split across files (read every part); minimal-API handlers (lambdas in Program.cs). Write each as "A calls B through <mechanism>", because a reader cannot see it in the code.
5. **Cross-check** — direction of integrations (who calls whom), status transitions (which code sets which status), default values, "unused" claims (grep callers before saying something is unused).
   - **What really runs when the user acts.** Before writing "the Approve button runs X", find the caller: `trace_flow.py X --entry`, the endpoint's note in `endpoints.md` (*no script, view or form in the repository names this URL* means no screen calls it), and a search of the scripts for the URL. A script function can keep an old name and post to a newer action (`FinalizeTrade()` calling `/Orders/FinalizeTradeWithoutPdf`); steps commented out in the script change the journey too. Describe the path that is live today and name the dead one as dead.
   - **Absences need evidence.** "No migrations", "no tests", "no jobs", "not used" come from a script result or a search, cited in the note (the database reference lists migration classes; `test-map.md` the tests; the trace the callers).
   - **Counts say what they cover.** A count of procedures, call sites or features that includes code copied from another application (a batch job's sources kept in the tree) or code no entry point reaches is labelled so: use the *Reached from an entry point* column and the *Where* folders of the database reference.
6. **Save** after the area: `research_notes.py done <id>`. If a later area contradicts an earlier note, fix the earlier note at once and log it: `research_notes.py correct "<what was wrong → what is right (evidence: file)>"`; fix any page already written.
7. **Feed the graph memory** (optional, helps later questions): `graphify save-result --question "<q>" --answer "<a>" --nodes <labels> --outcome useful|dead_end|corrected`; run `graphify reflect` occasionally.

## Fact quality checklist

- [ ] Every number, id, status name and flag matches the enum / seed / schema.
- [ ] Every "only", "always", "never" was checked against all callers.
- [ ] Every integration has direction, trigger, config key names, payload source, auth, error handling.
- [ ] Every security observation names the file and the condition that makes it exploitable.
- [ ] Nothing copied from config values; no secrets in the note. Servers named in commented-out connection strings or comments are described ("a production server named in a comment"), with no part of the address, not even its last digits.
- [ ] Every "the user / button / screen does X" names the script, view or job that calls X today.
- [ ] Every "there is no …" cites the script result or search behind it.
- [ ] External behaviour is marked "outside the repository".
- [ ] Every call through an interface, base class, message, event or delegate names what actually runs (and where it is registered or subscribed), or says that it is decided outside the code (configuration, reflection, another repository).

If any box is unchecked, go back to the research for that area, fix the note, and re-check the whole list before moving on.

## Working efficiently

- Use `lookup.py` once the reference exists (`--find TEXT` lists matching lines of a declaring file).
- Read in large slices; avoid many tiny reads of the same file.
- Prefer graph queries to wide greps; prefer one grep with a good regex to many narrow ones.
- **Search with `safe_grep.py`, not plain grep**, whenever the search can touch configuration, connection strings, credentials or commented-out code: `python <skill>/scripts/safe_grep.py "<regex>" [--path SUB] [--glob "*.config"] [--context 2]`. It masks values after `password=`, `pwd=`, `uid=`, `key=`, secret / token / API-key names and provider keys (`pk_live_`, `sk_live_`, `whsec_` …), so a value never reaches the transcript. `safe_grep.py --secrets` lists where such values sit (locations only); the survey already lists them for SEC findings.
- No subagents unless the user allowed them; if allowed, give each a self-contained brief and verify their claims before they enter a note.
