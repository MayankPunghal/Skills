# Reference adapters and the anchor contract

An adapter is a Python script that reads the source (or the graph) and writes Markdown pages into `docs/reference/`. `build_site.py` runs adapters with the current directory = workspace root, `DOCS_SOURCE_ROOT` = the source root, and `PYTHONPATH` = the adapter's folder. Read settings from `codebase-docs.json` (`adapter_options.<name>`).

## Anchor contract (what makes everything clickable)

1. Every entry starts with an explicit anchor: `<a id="<prefix>-<slug>"></a>` where `slug` = lower-case, non-alphanumerics → `-`, joined parts (`slug("tbl", "Order_Line")` → `tbl-order-line`). Explicit anchors work in GitHub, VS Code previews and MkDocs alike.
2. Prefixes in use: `tbl` table · `sp` routine · `ctl` controller · `act` action · `cls` class · `fn` function · `mod` source file · `com` community · `view` / `views` Razor view / folder · `enum` · `seed` · `claim` · `role` · `js` script · `rpt` report · `cfg` / `cfgfile` config · `ep` endpoint · `area` group · `mth` method · `prj` project · `pkg` package · `prjm` method-map project section · `err` error message · `run` build-and-run item · `dba` database call sites of one object · `ui` UI trigger · `uif` UI file section · `ent` entry point · `entm` method row in the entry-point index. New prefixes work automatically with the generic tag resolver (`[[<prefix>:Name]]`).
3. Each page opens with `<a id="index"></a>` and an index table linking to the entries; each section has `[↑ Back to index](#index)`.
4. Each entry states its **source file** in backticks, relative to the source root (`` `src/orders/service.py` `` or `File: \`…\``), so `lookup.py` can print `src: path:line`.
5. Cross-links between pages use the target page's anchor (`db-tables.md#tbl-order`). Don't worry about dead targets: `build_docs.py` de-duplicates repeated anchors (`-2`, `-3`) and turns links to missing anchors into plain text.
6. Table rows may carry the anchor in the first cell: `| <a id="sp-x"></a>**X** | … |`; headings may follow a standalone anchor line.

## Skeleton

```python
import json, os, re
CFG = json.load(open("codebase-docs.json", encoding="utf-8"))
ROOT = os.environ.get("DOCS_SOURCE_ROOT") or CFG["source_root"]
OUT = os.path.join(CFG.get("docs_dir", "docs"), "reference")

def slug(*p): return re.sub(r"[^a-z0-9]+", "-", "-".join(p).lower()).strip("-")

items = []  # (name, file_rel, line, details...) extracted deterministically from ROOT
out = ["# Endpoints", "", '<a id="index"></a>', "", "| Endpoint | File |", "| --- | --- |"]
out += [f"| [{n}](#{slug('ep', n)}) | `{f}` |" for n, f, *_ in items]
for n, f, line, *rest in items:
    out += ["", f'<a id="{slug("ep", n)}"></a>', "", f"## {n}", "", f"File: `{f}` · [↑ Back to index](#index)", ""]
os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, "endpoints.md"), "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
print("endpoints", len(items))
```

Register it: `"adapters": [..., "custom:tools/adapters/endpoints.py"]`, add `{"title": "Endpoints", "prefix": "ep-", "page": "endpoints.md"}` to `coverage` if every endpoint must be discussed, and use `[[ep:GET /orders]]` in pages.

## Pitfalls already handled in the shipped adapters

- Overloads and partial classes produce duplicate anchors → resolved by `build_docs.py`.
- Class names with suffixes (`Order_CCWRController1`) → regex `\w+Controller\w*`.
- Actions returning `void` / primitives are actions too; exclude only `[NonAction]` and `Dispose`.
- API controllers outside `Controllers/` (e.g. `Api/V1/`).
- ORM aliases (EF function import ≠ procedure name) → alias map from the model file.
- Pseudo-tables in seed scripts (`@Validation_Message`) and views linked as tables → become plain text.
- Same name in several projects → resolver prefers exact class names; authors can qualify tags (`[[ctl:Api-OrderController|OrderController]]`).
- A nested class inside a controller (an exception or DTO type in the middle of the file) → class bodies are brace-matched on comment- and string-free text (`code_text.code_only` / `block_close`); nested types are blanked so their methods are not actions, and the controller's later actions are kept.
- The skill's own output under the source root (the `.codebase-docs` workspace, an installed docs kit) → `_scan.walk`, `vendored()` and the graph excludes skip `vendor_files.docs_kit_dirs()`; a custom adapter that walks the tree itself should skip them too.

## Facts the shipped adapters add for other steps

| File | Added by | What |
| --- | --- | --- |
| `docs/agent/endpoints.json` `callers`, `caller` | generic-api | how many script / view / form references name the endpoint's URL (`Url.Action`, `asp-action`, `'/Ctl/Action'`, same-controller helpers in `Views/<Ctl>/`), comments blanked; `0` adds *no script, view or form in the repository names this URL* to the endpoint's note; templated routes are not checked |
| `docs/agent/db.json` `migrations`, `sql_server_features` | generic-sql | EF6 / EF Core / FluentMigrator migration classes; SQL Server-only features used from code with sites, folders and (for `db.dbo.x`) database names |
| `docs/agent/db.json` routine `reachable`, call site `reachable` | generic-trace | whether a method that an entry point reaches calls the procedure; `db-code-routines.md` gets the column and a summary by folder |
| `docs/_notes/graph-communities.json` `files` | code_graph.py summary | the ten busiest source files of each community, so the survey can attach communities to feature areas |
