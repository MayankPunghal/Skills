# Evaluations for codebase-documenter

Run each prompt in a fresh session without the skill (baseline), then with it, and note the difference.

## Contents

- [Prompts](#prompts)

## Prompts

### Bare invocation
Prompt: `/codebase-documenter`
Should trigger: yes
Done looks like: workspace state and the command menu are shown; no step starts.

### Plain-language trigger
Prompt: "Document this whole repo for a new team: architecture, workflows, data model, and a searchable site."
Should trigger: yes
First file Claude should open: `reference/routing.md` or `reference/full-run.md`
Done looks like: workspace is set up outside the repo; the graph is built before any page is written.

### Should not trigger
Prompt: "Add a docstring to this function."
Should trigger: no
Done looks like: skill is not loaded.

### Verification gate
Prompt: "Verify the docs."
Should trigger: yes
Done looks like: `verify_docs.py` runs and reports unresolved links, coverage, secrets and stub markers; failures are fixed at the adapter or template, not by hand-editing generated files.

### Business flow
Prompt: "Show me how an order gets shipped, step by step, as a flow chart our BAs can click through."
Should trigger: yes
First file Claude should open: `reference/flows.md`
Done looks like: `trace_flow.py` used on the entry point instead of reading every file; a `.flow.json` in business language with decisions and data steps; `build_site.py` passes with every step ref resolved; the flow page embeds the interactive chart.

### Method and dependency map
Prompt: "Which projects depend on the data layer, and what are the parameters and callers of the order repository methods?"
Should trigger: yes
Done looks like: answers come from `dependencies.md` (layers, used by) and `lookup.py <name> --kind method` / `methods.md`, with file:line; INFERRED calls are flagged as needing verification.

### Runbook and error catalogue
Prompt: "A new engineer joins Monday: how do they run this locally, and what does the error 'Only Paid orders ship' mean?"
Should trigger: yes
Done looks like: the runbook is written from `build-and-run.md` (commands, launch profiles, compose services, env var names, never values); the error is found in `errors.md` with the method that raises it and the condition, linked to the flow if one exists.

### Debugging from the UI
Prompt: "Clicking Refund on the order page fails. What runs when I click it, which tables does it change, and which error messages can the user see?"
Should trigger: yes
Done looks like: answered from `ui-map.md` (button → endpoint → handler), `entry-points.md` (database objects with operation and technology, errors reachable) and `trace_flow.py <handler> --depth 3`, without reading the whole controller; dynamic or unresolved links are named as such, not guessed.

### What starts this method
Prompt: "Who or what ends up calling OrderWorkflow.LockStatusAsync? I want to know which screens can reach it."
Should trigger: yes
Done looks like: `trace_flow.py OrderWorkflow.LockStatusAsync --entry` lists each entry point with one call path and the UI triggers of each endpoint; the answer says that reflection and run-time dispatch paths are not covered (DI, overrides, messages and events are, through generic-di).
