"""Quality gates for the documentation (deterministic). Exit code 1 if any gate fails.

    python <skill>/scripts/verify_docs.py [--no-site] [--coverage 100]

Gates:
  1 unresolved link tags = 0           (build_docs.py)
  2 unfinished scaffold sections = 0   (docs:todo markers)
  3 coverage >= threshold per kind     (appendices/coverage.md)
  4 MkDocs warnings = 0                (mkdocs build)
  5 no secrets in docs                 (pattern scan + every secret-like VALUE from the source config files)
  6 research areas all ticked          (PROGRESS.md)
  7 page hygiene                       (one H1 per page, no empty sections, no TBD/lorem, no raw Community N labels)
"""
import argparse
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

from _common import load_config, run, tick, utf8_stdout

SECRET_PATTERNS = [
    (r"(?i)\b(password|pwd|passwd)\s*[=:]\s*['\"]?[^\s'\";<>]{4,}", "password assignment"),
    (r"\bsk-[A-Za-z0-9_-]{20,}", "API key (sk-...)"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{24,}", "bearer token"),
    (r"(?i)\b(api[_-]?key|secret|token)\s*[=:]\s*['\"][A-Za-z0-9_\-./+=]{12,}['\"]", "key/secret literal"),
    (r"\bghp_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"\bxox[abp]-[A-Za-z0-9-]{10,}", "Slack token"),
]
SECRET_KEY = re.compile(r"(?i)pass|pwd|secret|token|apikey|api_key|credential|private|connectionstring|key$")


def config_secret_values(src):
    vals = set()
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in {"bin", "obj", "node_modules", ".git", "packages"}]
        for f in files:
            p = os.path.join(d, f)
            low = f.lower()
            try:
                if low in ("web.config", "app.config"):
                    r = ET.parse(p).getroot()
                    for a in r.findall("./appSettings/add"):
                        if SECRET_KEY.search(a.get("key", "")):
                            vals.add(a.get("value", ""))
                    for a in r.findall("./connectionStrings/add"):
                        for m in re.findall(r"(?i)(?:password|pwd)\s*=\s*([^;]+)", a.get("connectionString", "")):
                            vals.add(m)
                elif low.startswith(".env") or low.endswith(".properties"):
                    for k, v in re.findall(r"^\s*([\w.\-]+)\s*[=:]\s*(.+)$", open(p, encoding="utf-8", errors="ignore").read(), re.M):
                        if SECRET_KEY.search(k):
                            vals.add(v.strip().strip("'\""))
                elif re.search(r"(?i)^(?!launchsettings)[\w.-]*(settings|secrets)[\w.-]*\.json$", low):
                    def walk(o):
                        if isinstance(o, dict):
                            for k, v in o.items():
                                if isinstance(v, str) and SECRET_KEY.search(k):
                                    vals.add(v)
                                walk(v)
                    walk(json.load(open(p, encoding="utf-8-sig")))
            except Exception:
                continue
    return {v for v in vals if len(v) >= 6 and not re.fullmatch(r"(?i)true|false|\d+|none|null|\$\{.*\}|%.*%|<.*>", v)}


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-site", action="store_true")
    ap.add_argument("--coverage", type=float, default=100.0)
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    docs = cfg["docs_dir"]
    results = []

    code, out = run([sys.executable, os.path.join(docs, "_tools", "build_docs.py")])
    unres = sum(int(n) for _, n in re.findall(r"UNRESOLVED (\w+): (\d+)", out))
    results.append(("unresolved link tags", unres == 0, f"{unres}" + ("" if not unres else " → " + "; ".join(l.strip() for l in out.splitlines() if l.startswith("    "))[:400])))
    todo = re.search(r"TODO markers: (\d+) in (\d+) pages \(first: ([^)]*)\)", out)
    results.append(("unfinished scaffold sections", not todo, f"{todo.group(1)} in {todo.group(2)} pages ({todo.group(3)})" if todo else "0"))

    cov = os.path.join(docs, "appendices", "coverage.md")
    low = []
    if os.path.exists(cov):
        text = open(cov, encoding="utf-8").read()
        for title, done, total in re.findall(r"## (.+)\n\n(\d+) of (\d+) are discussed", text):
            pct = 100.0 * int(done) / max(int(total), 1)
            if pct < a.coverage:
                low.append(f"{title} {done}/{total}")
        summary = "; ".join(f"{t} {d}/{n}" for t, d, n in re.findall(r"## (.+)\n\n(\d+) of (\d+) are discussed", text))
    else:
        summary = "no coverage.md"
    results.append((f"coverage ≥ {a.coverage:g}%", not low and os.path.exists(cov), ", ".join(low) or summary))

    if not a.no_site:
        code, out = run([sys.executable, "-m", "mkdocs", "build"])
        warns = [l for l in out.splitlines() if "WARNING" in l and "MkDocs 2.0" not in l]
        results.append(("MkDocs build, 0 warnings", code == 0 and not warns, f"{len(warns)} warnings" + (": " + warns[0].split('WARNING -')[-1].strip()[:200] if warns else "")))

    hits = []
    pages = [p for p in glob.glob(os.path.join(docs, "**", "*.md"), recursive=True) if f"{os.sep}_tools{os.sep}" not in p]
    pages += glob.glob(os.path.join(docs, "**", "*.jsonl"), recursive=True) + glob.glob(os.path.join(docs, "llms.txt"))
    values = config_secret_values(cfg["source_root"]) if os.path.isdir(cfg["source_root"]) else set()
    for p in pages:
        t = open(p, encoding="utf-8", errors="ignore").read()
        for pat, label in SECRET_PATTERNS:
            for m in re.finditer(pat, t):
                hits.append(f"{os.path.relpath(p)}: {label}")
        for v in values:
            if v in t:
                hits.append(f"{os.path.relpath(p)}: a secret VALUE from the source config files")
    results.append(("no secrets in docs", not hits, f"{len(hits)} hits" + (": " + "; ".join(sorted(set(hits))[:6]) if hits else f" (checked {len(values)} config secret values + {len(SECRET_PATTERNS)} patterns)")))

    prog = os.path.join(docs, "_notes", "PROGRESS.md")
    if os.path.exists(prog):
        t = open(prog, encoding="utf-8").read()
        open_areas = re.findall(r"- \[ \] research ([\w-]+)", t)
        results.append(("research areas complete", not open_areas, ", ".join(open_areas[:10]) or "all ticked"))

    issues = []
    for p in glob.glob(os.path.join(docs, "_src", "**", "*.md"), recursive=True):
        t = open(p, encoding="utf-8").read()
        r = os.path.relpath(p, os.path.join(docs, "_src")).replace("\\", "/")
        body = re.sub(r"```.*?```", "(code block)", t, flags=re.S)  # a diagram or code block is section content
        if len(re.findall(r"^# ", body, re.M)) != 1:
            issues.append(f"{r}: H1 count")
        heads = [(i, len(m.group(1))) for i, l in enumerate(body.splitlines()) for m in [re.match(r"^(#{2,6}) ", l)] if m]
        lines = body.splitlines()
        for (i, lvl), (j, nxt) in zip(heads, heads[1:]):
            if nxt <= lvl and not "".join(lines[i + 1:j]).strip():
                issues.append(f"{r}: empty section '{lines[i].strip('# ')[:40]}'")
                break
        if re.search(r"(?i)\b(TBD|lorem ipsum|FIXME)\b", body):
            issues.append(f"{r}: TBD/lorem/FIXME")
        if re.search(r"(?i)\bCommunity \d+\b", body):
            issues.append(f"{r}: raw 'Community N' label")
    results.append(("page hygiene", not issues, "; ".join(issues[:8]) + (f" (+{len(issues) - 8})" if len(issues) > 8 else "") or "ok"))

    # typed counts that equal a generated headline number go stale on the next build: suggest the [[n:...]] tag
    sp = os.path.join(docs, "agent", "stats.json")
    stats = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    flat = [(f"{a}.{k}", v) for a, ks in stats.items() for k, v in ks.items() if isinstance(v, int) and v >= 5]
    typed = []
    for p in glob.glob(os.path.join(docs, "_src", "**", "*.md"), recursive=True):
        body = re.sub(r"```.*?```", "", open(p, encoding="utf-8").read(), flags=re.S)
        r = os.path.relpath(p, os.path.join(docs, "_src")).replace("\\", "/")
        for m in re.finditer(r"(?<![\w.:\[-])(\d[\d,]*)\s+([a-z][a-z-]+)", body):
            n, noun = int(m.group(1).replace(",", "")), m.group(2).rstrip("s")[:5]
            cands = [k for k, v in flat if v == n and noun in k.replace("-", "").replace("_", "")]
            if cands:
                typed.append(f"{r}: '{m.group(0)}' -> [[n:{cands[0]}]]")
    if typed:
        print(f"NOTE  typed counts that match a generated number ({len(typed)}; use the tag so they stay current): " + "; ".join(typed[:8]))

    w = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{w}}  {detail}")
    sens = [s for s in cfg.get("sensitive", []) if os.path.exists(os.path.join(docs, s))]
    if sens:
        print("NOTE  sensitive pages (share privately): " + ", ".join(sens))
    if all(ok for _, ok, _ in results):
        tick(cfg, "every scaffold page written")
        tick(cfg, "verify passes")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)


if __name__ == "__main__":
    main()
