"""Create (or complete) a codebase-documenter documentation workspace. Safe to re-run: never overwrites written pages.

    python <skill>/scripts/setup_workspace.py --product "Acme Orders" --code-name AcmeOrders --slug acme-orders \
        --source-root "src" --stack "ASP.NET MVC 5, SQL Server" \
        --description "Order management platform for ..." [--adapters generic-graph,generic-sql,generic-areas] [--force-config]

Creates: codebase-docs.json, docs/_src/** page scaffold (from templates/pages.json), docs/_notes/PROGRESS.md,
docs/_tools/ (runtime scripts: build_docs.py, gen_agent_index.py, lookup.py), docs/assets/, mkdocs.yml, .gitignore lines.
"""
import argparse
import json
import os
import shutil

from _common import CONFIG_NAME, DEFAULTS, SKILL_DIR, TEMPLATES, render, save_config, utf8_stdout, write

RUNTIME = ("build_docs.py", "gen_agent_index.py", "lookup.py")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    for a in ("product", "code-name", "slug", "source-root", "stack", "description", "adapters", "docs-dir"):
        ap.add_argument("--" + a)
    ap.add_argument("--markers", help="comma list of folders/files that identify the source root")
    ap.add_argument("--force-config", action="store_true")
    a = ap.parse_args()
    root = os.getcwd()
    cfg_path = os.path.join(root, CONFIG_NAME)
    if os.path.exists(cfg_path) and not a.force_config:
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        print(f"kept existing {CONFIG_NAME}")
    else:
        cfg = json.loads(json.dumps(DEFAULTS))
    for key, attr in (("product", "product"), ("code_name", "code_name"), ("slug", "slug"), ("source_root", "source_root"),
                      ("stack", "stack"), ("description", "description"), ("docs_dir", "docs_dir")):
        v = getattr(a, attr)
        if v:
            cfg[key] = v
    if a.adapters:
        cfg["adapters"] = [x.strip() for x in a.adapters.split(",") if x.strip()]
    if a.markers:
        cfg["source_markers"] = [x.strip() for x in a.markers.split(",") if x.strip()]
    cfg.setdefault("site", {})["name"] = cfg.get("site", {}).get("name") or f"{cfg.get('product') or 'Product'} documentation"
    if not cfg.get("slug"):
        cfg["slug"] = (cfg.get("code_name") or cfg.get("product") or "project").lower().replace(" ", "-")
    save_config(root, cfg)

    docs = cfg.get("docs_dir", "docs")
    vals = {"product": cfg.get("product") or "the product", "code_name": cfg.get("code_name", ""), "slug": cfg["slug"],
            "site_name": cfg["site"]["name"], "accent_hex": cfg.get("site", {}).get("accent_hex", "#3f51b5"),
            "language": cfg.get("site", {}).get("language", "en"),
            "docs_dir": docs}
    created = 0
    pages = json.load(open(os.path.join(TEMPLATES, "pages.json"), encoding="utf-8"))
    for sec in pages["sections"]:
        for k, p in enumerate(sec["pages"]):
            body = [f"# {render_str(p['title'], vals)}", "", f"<!-- nav: {k} -->", "",
                    f"<!-- docs:todo {render_str(p['purpose'], vals)} -->", ""]
            for h in p["outline"]:
                body += [f"## {render_str(h, vals)}", "", "<!-- docs:todo -->", ""]
            created += write(os.path.join(docs, "_src", sec["dir"], p["file"]), "\n".join(body), overwrite=False)
    created += write(os.path.join(docs, "_notes", "PROGRESS.md"), render("PROGRESS.md.tmpl", vals), overwrite=False)
    os.makedirs(os.path.join(docs, "_tools"), exist_ok=True)
    for f in RUNTIME:  # runtime scripts travel with the docs (repo-kit), so they are copied, not referenced
        shutil.copy2(os.path.join(SKILL_DIR, "scripts", "runtime", f), os.path.join(docs, "_tools", f))
    os.makedirs(os.path.join(docs, "assets"), exist_ok=True)
    if not os.path.exists(os.path.join(docs, "assets", "logo.svg")):
        shutil.copy2(os.path.join(TEMPLATES, "assets", "logo.svg"), os.path.join(docs, "assets", "logo.svg"))
    created += write(os.path.join(docs, "assets", "extra.css"), render("extra.css.tmpl", vals), overwrite=False)
    created += write("mkdocs.yml", render("mkdocs.yml.tmpl", vals), overwrite=False)
    gi = ".gitignore"
    have = open(gi, encoding="utf-8").read() if os.path.exists(gi) else ""
    add = [x for x in ("site/", "publish/", "graphify-out/cache/") if x not in have]
    if add:
        with open(gi, "a", encoding="utf-8") as fh:
            fh.write(("\n" if have and not have.endswith("\n") else "") + "\n".join(add) + "\n")
    print(f"workspace ready: {CONFIG_NAME}, {created} new files, runtime tools in {docs}/_tools, mkdocs.yml")
    print(f"source root: {cfg['source_root']} ({'found' if os.path.isdir(cfg['source_root']) else 'NOT FOUND'})")


def render_str(s, vals):
    for k, v in vals.items():
        s = s.replace("{{" + k + "}}", str(v))
    return s


if __name__ == "__main__":
    main()
