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
