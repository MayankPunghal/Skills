"""grep for research that never prints a secret value: credentials in config, connection strings and commented-out code
are masked before the line reaches the transcript.

    python <skill>/scripts/safe_grep.py "<regex>" [--path SUB] [--glob "*.cs"] [--context N] [--max 200]
    python <skill>/scripts/safe_grep.py --secrets [--path SUB]     # locations of secret-looking values only (file:line kind)

Runs from the documentation workspace (source root from codebase-docs.json) or with --root. Masked: values after
password= / pwd= / uid= / user id= / key= / secret / token / apikey / accountkey / sharedaccesskey / credential, and
provider keys (pk_live_, sk_live_, rk_live_, whsec_, AKIA..., ghp_, xox.-, AIza...). Standard library only.
"""
import argparse
import fnmatch
import json
import os
import re
import sys

SKIP = {".git", "node_modules", "bin", "obj", "packages", ".vs", "dist", "build", "target", "__pycache__", ".venv", "venv",
        ".idea", "graphify-out", "site", "publish", "vendor", "coverage"}
TEXT_EXT = {".cs", ".vb", ".fs", ".cshtml", ".vbhtml", ".razor", ".aspx", ".ascx", ".master", ".asax", ".asmx", ".ashx", ".svc",
            ".config", ".json", ".xml", ".yml", ".yaml", ".js", ".ts", ".tsx", ".jsx", ".py", ".java", ".kt", ".go", ".rb", ".php",
            ".sql", ".ps1", ".psm1", ".bat", ".cmd", ".sh", ".env", ".ini", ".properties", ".toml", ".txt", ".md", ".pubxml",
            ".settings", ".resx", ".tf", ".bicep", ".dockerfile"}
# a quoted literal under a secret-named key: "ApiKey": "...", Password = "...", connectionString="..."
QUOTED = re.compile(r"(?i)(\b\w*(?:password|passwd|pwd|secret|token|api_?key|account_?key|access_?key|private_?key|signing_?key|"
                    r"credential|connection_?string)\w*[\"']?\s*(?:=|:|=>)\s*[@$]?[\"'])([^\"'\r\n]{2,})")
# connection-string style, no spaces around "=": Password=x; User Id=sa; uid=sa; AccountKey=...; key=...
CONN = re.compile(r"(?i)(\b(?:password|passwd|pwd|uid|user ?id|account ?key|shared ?access ?key|access ?key|key|secret|token)=)"
                  r"([^;\"'<>\s][^;\"'<>\r\n]*)")
PROVIDER = re.compile(r"\b(pk_live_|sk_live_|rk_live_|pk_test_|sk_test_|whsec_|ghp_|gho_|github_pat_|xox[abprs]-|AKIA|ASIA|AIza|"
                      r"SG\.|eyJ)[A-Za-z0-9_\-./+=]{6,}")
SAFE_VALUE = re.compile(r"(?i)^(true|false|null|none|\{\{.*\}\}|\$\{.*\}|%\w+%|\*+|<[^>]*>|x+|\.\.\.|string|int|bool|"
                        r"[A-Za-z_][\w.]*\(.*|[A-Za-z_]\w*\s*\+.*)$")


def mask(line):
    """The line with every secret-looking value replaced by ***; (masked line, kinds found)."""
    kinds = []

    def rep(m):
        val = m.group(2).strip()
        if not val or SAFE_VALUE.match(val):
            return m.group(0)
        kinds.append(re.sub(r"[^a-z]+", "", m.group(1).lower()) or "value")
        return m.group(1) + "***"
    out = CONN.sub(rep, QUOTED.sub(rep, line))

    def prov(m):
        kinds.append(m.group(1).rstrip("_-.").lower() + " key")
        return m.group(1) + "***"
    out = PROVIDER.sub(prov, out)
    return out, kinds


def walk(root, sub="", glob=None):
    base = os.path.join(root, sub) if sub else root
    for d, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if glob and not fnmatch.fnmatch(f, glob):
                continue
            if not glob and ext not in TEXT_EXT and f.lower() not in ("dockerfile", ".env"):
                continue
            if re.search(r"(?i)\.min\.(js|css)$", f):
                continue
            p = os.path.join(d, f)
            try:
                if os.path.getsize(p) > 2_000_000:
                    continue
            except OSError:
                continue
            yield os.path.relpath(p, root).replace("\\", "/"), p


def secret_locations(root, sub=""):
    """[(file, line, kinds)] of lines that hold a secret-looking value (values never returned)."""
    out = []
    for rel, p in walk(root, sub):
        try:
            for i, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
                _, kinds = mask(line)
                if kinds:
                    out.append((rel, i, sorted(set(kinds))))
        except OSError:
            continue
    return out


def source_root(arg):
    if arg:
        return arg
    try:
        cfg = json.load(open("codebase-docs.json", encoding="utf-8"))
        return os.environ.get("DOCS_SOURCE_ROOT") or cfg.get("source_root", ".")
    except (OSError, ValueError):
        return "."


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern", nargs="?")
    ap.add_argument("--root")
    ap.add_argument("--path", default="", help="sub-folder of the source root")
    ap.add_argument("--glob", help="file-name filter, e.g. *.config")
    ap.add_argument("--context", type=int, default=0)
    ap.add_argument("--max", type=int, default=200)
    ap.add_argument("-i", action="store_true", help="ignore case")
    ap.add_argument("--secrets", action="store_true", help="list secret-looking values by location only")
    a = ap.parse_args()
    root = source_root(a.root)
    if a.secrets:
        locs = secret_locations(root, a.path)
        for rel, ln, kinds in locs:
            print(f"{rel}:{ln}  {', '.join(kinds)}")
        print(f"{len(locs)} line(s) with secret-looking values (values not shown)", file=sys.stderr)
        return
    if not a.pattern:
        ap.error("a pattern, or --secrets")
    rx = re.compile(a.pattern, re.I if a.i else 0)
    shown = 0
    for rel, p in walk(root, a.path, a.glob):
        try:
            lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            if not rx.search(line):
                continue
            lo, hi = max(0, i - a.context), min(len(lines), i + a.context + 1)
            for k in range(lo, hi):
                print(f"{rel}:{k + 1}{':' if k == i else '-'} {mask(lines[k])[0][:400]}")
            if a.context:
                print("--")
            shown += 1
            if shown >= a.max:
                print(f"... stopped at {a.max} matches (--max)", file=sys.stderr)
                return
    print(f"{shown} match(es); secret-looking values are masked as ***", file=sys.stderr)


if __name__ == "__main__":
    main()
