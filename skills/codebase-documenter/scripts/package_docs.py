"""Build the shareable package: one folder (README.md, website/, repo-kit/) and its zip, from single sources.

    python <skill>/scripts/package_docs.py [--name MyProduct-Docs]

Requires a built site (build_site.py) and the agent layer (make_agent_skill.py). Asserts the root layout, that the
project skill copy is byte-identical, and scans the package for secrets. graphify-out/ is never packaged (large,
machine-specific paths); the README tells the receiver how to rebuild it.
"""
import argparse
import filecmp
import json
import os
import shutil
import sys

from _common import load_config, render, run, tick, utf8_stdout, write

SKILL_SELF = os.path.dirname(os.path.abspath(__file__))


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--name")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    docs, slug = cfg["docs_dir"], cfg["slug"]
    skill = f"{slug}-docs"
    name = a.name or f"{(cfg.get('code_name') or cfg.get('product') or slug).replace(' ', '')}-Docs"
    skill_src = os.path.join(".claude", "skills", skill, "SKILL.md")
    for need in ("site/index.html", skill_src, "AGENTS.md", os.path.join(docs, "agent", "entities.jsonl")):
        if not os.path.exists(need):
            sys.exit(f"missing {need}: run build_site.py and make_agent_skill.py first")
    # a representative entity for the README's verification step
    verify = ("index", "page")
    for kind in ("action", "controller", "class", "routine", "table", "page"):
        for line in open(os.path.join(docs, "agent", "entities.jsonl"), encoding="utf-8"):
            e = json.loads(line)
            if e["kind"] == kind and len(e["name"]) < 60:
                verify = (e["name"], kind)
                break
        else:
            continue
        break
    markers = cfg.get("source_markers") or []
    sens = [s for s in cfg.get("sensitive", []) if os.path.exists(os.path.join(docs, s))]
    vals = {"product": cfg.get("product") or slug, "code_name": cfg.get("code_name") or cfg.get("product") or slug,
            "skill_name": skill, "package_name": name, "docs_dir": docs,
            "markers_text": " and ".join(f"`{m}`" for m in markers) or "the application source code",
            "sensitive_note": (" and ".join(f"`repo-kit/{docs}/{s}`" for s in sens) + " describe(s) security weaknesses.") if sens else "none flagged.",
            "verify_name": verify[0], "verify_kind": verify[1],
            "example_question": "how does <a key business process> work?"}
    pub = os.path.join("publish", name)
    shutil.rmtree("publish", ignore_errors=True)
    kit = os.path.join(pub, "repo-kit")
    shutil.copytree("site", os.path.join(pub, "website"), ignore=shutil.ignore_patterns("agent"))
    shutil.copytree(docs, os.path.join(kit, docs), ignore=shutil.ignore_patterns("__pycache__"))
    for f in ("AGENTS.md", "mkdocs.yml"):
        shutil.copy2(f, kit)
    # repo-kit/ is meant to be unpacked at the repository root (docs next to the code), so the shipped source root is
    # "." instead of this machine's path; lookup.py still finds the code by source_markers, DOCS_SOURCE_ROOT or --src
    raw = json.load(open("codebase-docs.json", encoding="utf-8"))  # the file as written, not merged with the defaults
    write(os.path.join(kit, "codebase-docs.json"), json.dumps(dict(raw, source_root="."), indent=2, ensure_ascii=False) + "\n")
    write(os.path.join(kit, "CLAUDE.md"), render("CLAUDE.block.md.tmpl", vals))
    # docs-only workspace (README mode B): the same block with every path under repo-kit/, copied to the package root
    write(os.path.join(kit, "CLAUDE.docs-only.md"),
          render("CLAUDE.block.md.tmpl", dict(vals, docs_dir=f"repo-kit/{docs}")).replace("`AGENTS.md`", "`repo-kit/AGENTS.md`"))
    write(os.path.join(kit, "SETUP-GUIDE.md"), render("SETUP-GUIDE.md.tmpl", vals))
    write(os.path.join(pub, "README.md"), render("README.package.md.tmpl", vals))
    dst = os.path.join(kit, skill_src)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(skill_src, dst)
    assert filecmp.cmp(skill_src, dst, shallow=False), "skill copy differs"
    assert sorted(os.listdir(pub)) == ["README.md", "repo-kit", "website"], sorted(os.listdir(pub))
    # secret scan of the package (patterns + config values) reuses verify_docs logic
    sys.path.insert(0, SKILL_SELF)
    from verify_docs import SECRET_PATTERNS, config_secret_values
    import re
    values = config_secret_values(cfg["source_root"]) if os.path.isdir(cfg["source_root"]) else set()
    hits = []
    for d, _, fs in os.walk(pub):
        if f"{os.sep}assets{os.sep}" in d + os.sep or f"{os.sep}search" in d:  # theme bundles / search index: third-party code
            continue
        for f in fs:
            if f.endswith((".md", ".html", ".json", ".jsonl", ".txt", ".js", ".yml")):
                t = open(os.path.join(d, f), encoding="utf-8", errors="ignore").read()
                if any(re.search(p, t) for p, _ in SECRET_PATTERNS) or any(v in t for v in values):
                    hits.append(os.path.relpath(os.path.join(d, f), pub))
    zip_path = shutil.make_archive(pub, "zip", "publish", name)
    n = sum(len(fs) for _, _, fs in os.walk(pub))
    print(f"{n} files -> {zip_path} ({os.path.getsize(zip_path) / 1e6:.1f} MB); root: README.md, website/, repo-kit/")
    print(f"secret scan: {'clean' if not hits else 'CHECK ' + ', '.join(hits[:8])}")
    print("next: test with a fresh agent (README setup + one question), then tick the package item in PROGRESS.md")
    if sens:
        print("sensitive pages inside — share privately: " + ", ".join(sens))


if __name__ == "__main__":
    main()
