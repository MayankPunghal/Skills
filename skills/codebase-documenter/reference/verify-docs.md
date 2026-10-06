# verify-docs — quality gates

`python <skill>/scripts/verify_docs.py [--no-site] [--coverage 100]` prints one `PASS` / `FAIL` line per gate and exits non-zero on failure.

| Gate | Passes when | Typical fix |
| --- | --- | --- |
| Unresolved link tags | 0 | See build-site fixes |
| Unfinished scaffold sections | 0 `docs:todo` markers | Write the section or delete the heading if truly not applicable (say why in a sentence if the reader would expect it) |
| Coverage | each configured kind ≥ threshold | Discuss the item in a module page; for trivial items the code & data map is enough |
| MkDocs | build ok, 0 warnings | Fix at source (adapter, tag, page) |
| No secrets | no secret patterns and **no secret value from the source config files** found in docs / index / llms.txt. A password pattern needs a literal-looking value (`password=x`, a quoted value, or one with a digit / symbol / inner capital), so prose such as "has no password: users …" passes | Remove the value, name the key instead; re-check notes |
| Research complete | every area ticked in PROGRESS | Finish or consciously drop (with a note) |
| Page hygiene | one H1, no empty sections, no TBD/lorem/FIXME, no raw `Community N` labels | Edit the page |
| Mermaid diagrams lint | no `;` in a sequence message or unquoted label, balanced `"`, no `end` node id, balanced brackets on flowchart lines (written pages and reference pages) | Fix the diagram (rules in page-patterns.md "Diagrams") |
| Site loads no remote scripts | no `<script src="https://…">` in the built site (the offline plugin's iframe-worker search shim is reported, not failed) | Remove the remote script or serve it from `docs/assets/` |
| (NOTE) diagrams need internet | pages have diagrams and `mkdocs.yml` lists no local `mermaid.min.js` | `offline_mermaid.py` (see build-site.md) |
| (NOTE) typed counts | a number in a hand-written page equals a generated headline number (`docs/agent/stats.json`); a version after a product name ("Entity Framework 6", ".NET 4.8") is ignored | Replace it with the suggested `[[n:area.key]]` tag |

Then, by reading (the scripts cannot judge these):

1. **Fact spot-check**: pick 10 claims across pages (ids, statuses, rules, integration directions, "only/never" statements) and re-verify in code. Fix and log corrections.
2. **Consistency pass**: glossary terms, capitalisation, units, spelling standard.
3. **Navigation pass**: open the built site; click index → entry → back; follow 10 cross-links; check diagrams render.
4. **Sensitive content**: confirm the `sensitive` pages list is right; the package README will warn about them.
