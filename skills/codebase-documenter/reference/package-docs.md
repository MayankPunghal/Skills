# package-docs — one zip for people and agents

`python <skill>/scripts/package_docs.py [--name <Product>-Docs]` builds `publish/<Name>/` and `publish/<Name>.zip`:

```
<Name>/
├── README.md     the only file at the root: for people (open website/index.html) and step-by-step setup
│                 instructions an AI agent follows ("Read README.md in this folder and set up the <product> docs skill")
├── website/      the built site (offline, searchable)
└── repo-kit/     installed next to the code: AGENTS.md, CLAUDE.md (CLAUDE.docs-only.md: paths under repo-kit/ for a
                  docs-only workspace), SETUP-GUIDE.md, codebase-docs.json, mkdocs.yml,
                  .claude/skills/<slug>-docs/SKILL.md, docs/ (pages, _src, _notes, _tools, agent/, llms.txt)
```

The script asserts the root layout and a byte-identical skill copy, scans the package for secrets, and lists sensitive pages. The README's setup instructions cover three install modes (A: into the code repository; B: docs-only workspace; C: personal / global install with a pinned docs root), a verification lookup with expected output, other agents (AGENTS.md; Copilot instructions), the optional graph rebuild, and the report back to the user.

**Never packaged**: `graphify-out/` (large; machine-specific paths; the reference already carries its relationship data — the README explains how to rebuild it on the real repository), `site/` outside `website/`, caches.

## Test before handing over

1. Unzip into a clean temporary folder.
2. Start a fresh agent there with only: *"Read README.md in this folder and set up the <product> docs skill."*
3. Start another fresh session and ask a question with `/<slug>-docs …`.
4. Both must succeed without help. Delete the test folder.

## Sharing

Private channels only when `sensitive` pages exist (security findings describe exploitable weaknesses of a real system). Do not publish to a public URL without the user's explicit go-ahead.
