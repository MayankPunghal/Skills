"""Error catalogue: every error message the code raises or shows, where, and in which method.

Writes docs/reference/errors.md (anchors err-<file>-<line>; tag [[err:OrderWorkflow-57]] matches by suffix).
Finds, with the literal message text:
  exceptions      throw new X("…") (C#, Java, JS/TS), raise X("…") (Python), errors.New / fmt.Errorf (Go), panic("…")
  validation      [Required(ErrorMessage = "…")] and other ErrorMessage attributes, ModelState.AddModelError(…, "…")
  http            BadRequest("…") / NotFound("…") / Conflict / Unauthorized / Problem(detail: "…") / StatusCode(4xx, "…"),
                  res.status(4xx).json/send("…" or {message|error: "…"}), HTTPException(detail="…"), abort(4xx, "…")
  user message    TempData / ViewBag / ViewData keys named error / bad / fail / warning, Flask flash(…, "error")
  database        RAISERROR('…'), THROW 5xxxx, '…' (T-SQL), RAISE EXCEPTION '…' (PL/pgSQL)
Interpolated parts are kept as written ({amount:N2}, ${id}, %s). Options (adapter_options.generic-errors): skip_regex,
include_tests (default false), max_message (default 180).
"""
import json
import os
import re
from collections import Counter, defaultdict

from _scan import BACK, DOCS, Methods, esc, esc_text, line_at, options, project_of, read, slug, walk, write_page
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

OPT = options("generic-errors")
MAXLEN = OPT.get("max_message", 180)
TESTS = re.compile(r"(^|/)(tests?|specs?|__tests__)(/|$)|[._-](tests?|spec)\.\w+$|Tests?\.\w+$|(^|/)test_\w+\.py$", re.I)
STR = r"\$?@?(?:\"((?:[^\"\\\n]|\\.)*)\"|'((?:[^'\\\n]|\\.)*)'|`([^`]*)`)"  # C# $"…" / @"…", JS '…' / `…`, Python
PY_STR = r"[frbu]{0,2}(?:\"((?:[^\"\\\n]|\\.)*)\"|'((?:[^'\\\n]|\\.)*)')"
PATTERNS = [
    ("exception", {".cs", ".vb", ".java", ".kt", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".php"},
     re.compile(r"\bthrow\s+(?:new\s+)?([\w.]*(?:Exception|Error|Fault)\w*)\s*\(\s*(?:\w+\s*:\s*)?(?:nameof\([^)]*\)\s*,\s*)?" + STR)),
    ("exception", {".vb"}, re.compile(r"\bThrow\s+New\s+([\w.]*Exception)\s*\(\s*" + STR)),
    ("exception", {".py"}, re.compile(r"\braise\s+([\w.]+)\s*\(\s*" + PY_STR)),
    ("exception", {".go"}, re.compile(r"\b(errors\.New|fmt\.Errorf|panic)\s*\(\s*" + STR)),
    ("validation", None, re.compile(r"\b(ErrorMessage)\s*=\s*" + STR)),
    ("validation", None, re.compile(r"\b(AddModelError)\s*\(\s*[^,()]*(?:\([^()]*\))?[^,()]*,\s*" + STR)),
    ("http", {".cs", ".vb"}, re.compile(r"\b(BadRequest|NotFound|Conflict|Unauthorized|UnprocessableEntity|Forbid|ValidationProblem)\s*\(\s*" + STR)),
    ("http", {".cs", ".vb"}, re.compile(r"\b(Problem)\s*\([^)]*?detail\s*:\s*" + STR)),
    ("http", {".cs", ".vb"}, re.compile(r"\b(StatusCode)\s*\(\s*([45]\d\d)\s*,\s*" + STR)),
    ("http", {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"},
     re.compile(r"\.status\(\s*([45]\d\d)\s*\)\s*\.\s*(?:json|send)\(\s*(?:\{\s*(?:message|error|detail)\s*:\s*)?" + STR)),
    ("http", {".py"}, re.compile(r"\b(HTTPException)\s*\([^)]*?detail\s*=\s*" + PY_STR)),
    ("http", {".py"}, re.compile(r"\b(abort)\s*\(\s*([45]\d\d)\s*,\s*(?:description\s*=\s*)?" + PY_STR)),
    ("user message", {".cs", ".vb"}, re.compile(r"\b(?:TempData|ViewData|ViewBag)\s*(?:\[\s*\"(\w*(?:error|bad|fail|warn)\w*)\"\s*\]|\.(\w*(?:Error|Fail|Warn)\w*))\s*=\s*" + STR, re.I)),
    ("user message", {".py"}, re.compile(r"\b(flash)\s*\(\s*" + PY_STR + r"\s*,\s*['\"](?:error|danger|warning)['\"]")),
    ("database", {".sql"}, re.compile(r"\b(RAISERROR)\s*\(\s*N?'((?:[^']|'')*)'", re.I)),
    ("database", {".sql"}, re.compile(r"\b(THROW)\s+(\d+)\s*,\s*N?'((?:[^']|'')*)'", re.I)),
    ("database", {".sql"}, re.compile(r"\b(RAISE\s+EXCEPTION)\s+'((?:[^']|'')*)'", re.I)),
]


def message_of(groups):
    """The last non-empty captured string is the message; earlier groups are the type / code."""
    vals = [g for g in groups if g]
    return vals[-1] if vals else ""


def literal_at(text, q):
    """(contents, end) of the double-quoted literal whose opening quote is at q; an interpolated $"..." keeps its {holes}
    whole, including strings nested inside them ($"expected [{string.Join(", ", e)}]")."""
    interp = text[max(0, q - 2):q].replace("@", "").endswith("$")
    verbatim = "@" in text[max(0, q - 2):q]
    i, depth, out = q + 1, 0, []
    while i < len(text) and text[i] != "\n" or (verbatim and i < len(text)):
        ch = text[i]
        if depth:
            if ch == '"':  # a string inside the hole
                j = i + 1
                while j < len(text) and text[j] not in '"\n':
                    j += 2 if text[j] == "\\" else 1
                out.append(text[i:j + 1])
                i = j + 1
                continue
            depth += (ch == "{") - (ch == "}")
        elif interp and ch == "{":
            if text.startswith("{{", i):
                out.append("{")
                i += 2
                continue
            depth = 1
        elif ch == "\\" and not verbatim:
            out.append(text[i:i + 2])
            i += 2
            continue
        elif ch == '"':
            if verbatim and text.startswith('""', i):
                out.append('"')
                i += 2
                continue
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    return "".join(out), i


def with_concat(text, end, msg):
    """Follow "a" + name + "b" (VB &) on to the closing ")" so the message reads 'a{name}b' instead of stopping at the first piece."""
    for _ in range(8):
        m = re.match(r"\s*[+&]\s*", text[end:end + 20])
        if not m:
            return msg
        k = end + m.end()
        if text[k:k + 1] == '"' or text[k:k + 2] in ('$"', '@"'):
            q = text.index('"', k)
            part, end = literal_at(text, q)
            msg += part
            continue
        ident = re.match(r"[\w.]+(?:\(\))?", text[k:])
        if not ident:
            return msg + " …"
        msg += "{" + ident.group(0) + "}"
        end = k + ident.end()
    return msg


def kind_label(kind, groups, msg):
    first = next((g for g in groups if g and g != msg), "")
    if kind == "http" and re.fullmatch(r"[45]\d\d", first or ""):
        return f"HTTP {first}"
    return first


def main():
    skip = re.compile(OPT["skip_regex"]) if OPT.get("skip_regex") else None
    m = Methods()
    rows = []
    exts = set().union(*(e for _, e, _ in PATTERNS if e)) | {".cs", ".vb", ".java", ".kt", ".js", ".ts", ".py", ".go", ".php"}
    for path, full in walk(exts=exts):
        if (skip and skip.search(path)) or (not OPT.get("include_tests") and TESTS.search(path)):
            continue
        ext = os.path.splitext(path)[1].lower()
        text = None
        seen = set()
        for kind, only, rx in PATTERNS:
            if only and ext not in only:
                continue
            if ext == ".sql" and kind != "database":
                continue
            text = text if text is not None else read(full)
            for hit in rx.finditer(text):
                msg = message_of(hit.groups()).replace("''", "'").strip()
                gi = max((k for k, g in enumerate(hit.groups(), 1) if g), default=0)
                end = hit.end()
                if gi and ext != ".sql" and text[hit.start(gi) - 1:hit.start(gi)] == '"':  # read the whole literal, then any concatenation
                    msg, end = literal_at(text, hit.start(gi) - 1)
                    msg = with_concat(text, end, msg).strip()
                if len(msg) < 3 or not re.search(r"[A-Za-z]{2}", msg):
                    continue
                if kind == "exception" and re.fullmatch(r"[A-Za-z_]\w*", msg) and re.search(r"Argument(Null|OutOfRange)?Exception|Null", hit.group(0)):
                    continue  # ArgumentNullException("blogPost"): a parameter name, not a message anyone reads
                line = line_at(text, hit.start())
                if (line, msg) in seen:
                    continue
                seen.add((line, msg))
                rows.append({"kind": kind, "type": kind_label(kind, hit.groups(), msg), "message": msg[:MAXLEN] + ("…" if len(msg) > MAXLEN else ""),
                             "file": path, "line": line, "method": m.enclosing(path, line) if ext != ".sql" else None})
    if not rows:
        print("errors: none found")
        return
    by_proj = defaultdict(list)
    for r in rows:
        by_proj[project_of(r["file"])].append(r)
    kinds = Counter(r["kind"] for r in rows)
    dup = Counter(r["message"] for r in rows)
    out = ["# Error catalogue", "",
           f"Every error message found in the code ({len(rows)}: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()) + "), "
           "with the method that raises it. Use it to explain what a user or caller sees, to find where an error in a log "
           "comes from, and to spot inconsistent wording. Messages built entirely at run time or loaded from resources "
           "are not listed. Messages used in more than one place are marked ×N.", "", '<a id="index"></a>', "",
           "| Project | Errors |", "| --- | ---: |"]
    out += [f"| [{esc_text(p)}](#{slug('area', p)}) | {len(v)} |" for p, v in sorted(by_proj.items())]
    for p, rs in sorted(by_proj.items()):
        out += ["", f'<a id="{slug("area", p)}"></a>', "", f"## {p}", "", BACK, "",
                "| Message | Kind | Raised in | Source |", "| --- | --- | --- | --- |"]
        for r in sorted(rs, key=lambda r: (r["file"], r["line"])):
            a = slug("err", os.path.splitext(os.path.basename(r["file"]))[0], r["line"])
            where = m.link(r["method"]) or "—"
            kind = r["kind"] + (f" · `{esc(r['type'])}`" if r["type"] else "")
            times = f" ×{dup[r['message']]}" if dup[r["message"]] > 1 else ""
            out.append(f'| <a id="{a}"></a>"{esc_text(r["message"])}"{times} | {kind} | {where} | `{esc(r["file"])}:{r["line"]}` |')
    write_page("errors.md", out)
    for r in rows:
        r["anchor"] = slug("err", os.path.splitext(os.path.basename(r["file"]))[0], r["line"])
    os.makedirs(os.path.join(DOCS, "agent"), exist_ok=True)
    open(os.path.join(DOCS, "agent", "errors.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(rows, ensure_ascii=False, indent=1))
    stat("errors", errors=len(rows), projects=len(by_proj))
    print(f"errors: {len(rows)} in {len(by_proj)} projects (" + ", ".join(f"{k} {v}" for k, v in kinds.most_common()) + ")")


if __name__ == "__main__":
    main()
