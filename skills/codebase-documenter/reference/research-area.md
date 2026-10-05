# research-area — read one area in depth, write a verified note

The research note is the source of truth for the pages. Pages are written from notes; notes are written from code. Never write a page from memory.

## Protocol (per area)

1. **Scope** — open the note (`docs/_notes/<id>.md`); confirm paths and communities.
2. **Orient with the graph (cheap)** — `code_graph.py ask "<area topic>" --budget 800`; `graphify explain "<main class>"`; `graphify god-nodes` hubs that sit in this area; read the community's wiki page.
3. **Read fully** — controllers / endpoints, services, view models, validators, key views, stored procedures, triggers, jobs. Large engines (pricing, validation, payload builders) are read top to bottom, not skimmed. `--find`-style greps are for locating, not for understanding.
4. **Record facts in business terms**, each verified, into the template sections:
   - Screens / endpoints: what each action does, inputs, rules, side effects (emails, documents, statuses), who may call it.
   - Rules & calculations: numbered steps for engines; exact conditions and thresholds; ids and flags **checked against enums and seed data**.
   - Data: tables / collections read and written; procedures called.
   - Integrations: trigger, config key names (never values), payload builder, authentication, response handling, logging, retries.
   - Permissions: claims / roles / attributes; anonymous or unauthenticated entry points (check what a custom "AllowAnonymous" really skips).
   - Defects / risks: file + concrete failure scenario (DEF / SEC candidates). Dead code, TODOs, fake / test endpoints left in production.
   - Open questions: what the repository cannot answer (schedules, servers, external system behaviour).
5. **Cross-check** — direction of integrations (who calls whom), status transitions (which code sets which status), default values, "unused" claims (grep callers before saying something is unused).
6. **Save** after the area: `research_notes.py done <id>`. If a later area contradicts an earlier note, fix the earlier note at once and log it: `research_notes.py correct "<what was wrong → what is right (evidence: file)>"`; fix any page already written.
7. **Feed the graph memory** (optional, helps later questions): `graphify save-result --question "<q>" --answer "<a>" --nodes <labels> --outcome useful|dead_end|corrected`; run `graphify reflect` occasionally.

## Fact quality checklist

- [ ] Every number, id, status name and flag matches the enum / seed / schema.
- [ ] Every "only", "always", "never" was checked against all callers.
- [ ] Every integration has direction, trigger, config key names, payload source, auth, error handling.
- [ ] Every security observation names the file and the condition that makes it exploitable.
- [ ] Nothing copied from config values; no secrets in the note.
- [ ] External behaviour is marked "outside the repository".

If any box is unchecked, go back to the research for that area, fix the note, and re-check the whole list before moving on.

## Working efficiently

- Use `lookup.py` once the reference exists (`--find TEXT` lists matching lines of a declaring file).
- Read in large slices; avoid many tiny reads of the same file.
- Prefer graph queries to wide greps; prefer one grep with a good regex to many narrow ones.
- No subagents unless the user allowed them; if allowed, give each a self-contained brief and verify their claims before they enter a note.
