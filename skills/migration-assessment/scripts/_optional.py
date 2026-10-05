"""Optional modernization opportunities (deterministic): where the code could use a managed AWS service instead of what it runs today.

Catalog and hours: scripts/data/optional_modernizations.json. None of these is required to run on Linux or AWS, so the result is
shown beside the estimate and is never part of its total.
"""
import os
import re

from _common import SOURCE_DIR_SKIP, data, read_text, rel

SOURCE_EXT = (".cs", ".vb", ".config", ".cshtml", ".aspx")
MAX_FILE_BYTES = 1_500_000  # larger files are generated or data, not code worth reading for these patterns


def scan_repo(root, inv):
    """Items found in one repository: [{id, title, aws, why, files: [{file, line, text}], count}]."""
    items = data("optional_modernizations.json")["items"]
    rx = {it["id"]: [re.compile(p) for p in it["detect"]] for it in items}
    hits = {it["id"]: {} for it in items}
    skip = SOURCE_DIR_SKIP | {"bin", "obj"}
    for p in inv["projects"]:
        pdir = os.path.join(root, os.path.dirname(p["path"]))
        for d, dirs, files in os.walk(pdir):
            dirs[:] = [x for x in dirs if x.lower() not in skip and not x.startswith(".")]
            for fn in files:
                if not fn.lower().endswith(SOURCE_EXT):
                    continue
                full = os.path.join(d, fn)
                if os.path.getsize(full) > MAX_FILE_BYTES or fn.lower().endswith((".designer.cs", ".g.cs")):
                    continue
                for n, line in enumerate(read_text(full).splitlines(), 1):
                    code = line.split("//")[0]
                    for it in items:
                        if any(r.search(code) for r in rx[it["id"]]):
                            hits[it["id"]].setdefault(rel(full, root), (n, line.strip()[:140]))
    out = []
    for it in items:
        files = hits[it["id"]]
        if files:
            out.append({"id": it["id"], "title": it["title"], "aws": it["aws"], "why": it["why"], "hours": it["hours"], "per_file": it["per_file"],
                        "count": len(files), "files": [{"file": f, "line": v[0], "text": v[1]} for f, v in sorted(files.items())][:5]})
    return out


def hours(item, code_factor):
    """Manual-equivalent and AI-assisted [low, high] hours for one found item: fixed + per additional file."""
    extra = max(item["count"] - 1, 0)
    manual = [item["hours"][i] + item["per_file"][i] * extra for i in (0, 1)]
    return manual, [manual[i] * code_factor[i] for i in (0, 1)]
