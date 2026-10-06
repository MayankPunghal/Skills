# setup-workspace — create the documentation workspace

The workspace is a folder that holds the documentation project; it can be the repository itself or a separate analysis folder next to an unzipped copy of the code.

## Steps

0. **Pick the workspace location** and say which one and why (ask when the user has not said):

   | Option | Use when | Trade-off |
   | --- | --- | --- |
   | Sibling folder `<repo>-docs/` next to the code (recommended) | The code is a client checkout, read-only, or shared | Nothing is written into the repository; the docs are shared as a zip or their own repository |
   | `<repo>/.codebase-docs/` inside the repository | The team wants the docs versioned with the code | Every graph and site rebuild shows up in the repository's status unless the folder is git-ignored; vendor and survey scans must skip it (they do: it starts with a dot) |

1. Decide the **source root** (the folder with the code) and 1–3 **source markers**: sub-folders or files that only exist at that root (e.g. `src`, `MyApp.sln`, `MyApp.Database`). `lookup.py` uses them to find the code later, wherever the docs travel.
2. Run, from the workspace folder:

   ```
   python <skill-base-dir>/scripts/setup_workspace.py --product "<Product name>" --code-name "<CodeName>" --slug <short-id> \
       --source-root "<path to code>" --markers "<marker1>,<marker2>" --stack "<main technologies>" \
       --description "<one sentence: what the system is for>"
   ```

   - `--slug` names the project skill later (`<slug>-docs`) — short, lower-case, meaningful (e.g. `acme-orders`).
   - Adapters default to `generic-graph,generic-sql,generic-config,generic-areas`; set them after the survey (`generate-reference`).
3. Check the printout: `source root: … (found)`.
4. Install MkDocs once if missing: `pip install mkdocs-material`.

## What it creates (never overwrites written pages)

| Path | Purpose |
| --- | --- |
| `codebase-docs.json` | Project settings: product, slug, source root & markers, adapters, coverage kinds, seed tables, sensitive pages, graph options |
| `docs/_src/**` | Page scaffold (Diátaxis-shaped sections: getting-started, architecture, modules, workflows, integrations, data, shared, operations, security, appendices) with outline headings and `<!-- docs:todo -->` markers |
| `docs/_notes/PROGRESS.md` | Phase checklist, research-area lines, corrections log |
| `docs/_tools/` | Runtime tools that travel with the docs: `build_docs.py`, `gen_agent_index.py`, `lookup.py` |
| `docs/assets/` | Logo and theme CSS (accent colour from `site.accent_hex`) |
| `mkdocs.yml` | Material theme, search + offline plugins, Mermaid, strict link validation, generated nav block |

## Settings worth editing now (`codebase-docs.json`)

- `sensitive`: pages that must be shared privately (default `security/findings.md`).
- `site.accent_hex`, `site.language`.
- `graph.model` / `graph.api_key_env` / `graph.base_url` if a specific LLM should name communities.
- `graph.vendor_dirs`: folders (or files) of copied third-party code to leave out of the graph, the survey and the endpoint scan, relative to the source root. Run `python <skill>/scripts/survey_codebase.py --pre` first on a large repository: it lists the vendored folders it detects and the largest folders, before the slow graph build.
