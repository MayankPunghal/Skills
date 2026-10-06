"""String-literal awareness for line rules over C# / VB: a rule that names an API should not fire on text inside a string
(log messages, test titles, help text). Standard library only; shared by migration-assessment's scan_repo.py and the
codebase-documenter's generic-portability adapter, so both outputs agree.

    from code_text import code_match
    code_match(rule_regex, line, vb=False)   # True when a match starts outside every string literal
"""


def string_spans(line, vb=False):
    """(start, end) of the contents of each string literal on one C# / VB line ("..", @"..", $"..", raw \"\"\"..\"\"\", '.' chars)."""
    spans, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c == '"':
            if not vb and line.startswith('"""', i):
                j = line.find('"""', i + 3)
                j = n if j < 0 else j
                spans.append((i + 3, j))
                i = j + 3
                continue
            verbatim = vb or (i > 0 and line[i - 1] == "@") or (i > 1 and line[i - 2:i] in ("@$", "$@"))
            interp = not vb and ((i > 0 and line[i - 1] == "$") or (i > 1 and line[i - 2:i] in ("@$", "$@")))
            j, start, depth = i + 1, i + 1, 0
            while j < n:
                ch = line[j]
                if interp and ch == "{":
                    if depth == 0 and j + 1 < n and line[j + 1] == "{":
                        j += 2  # {{ is a literal brace
                        continue
                    if depth == 0:
                        spans.append((start, j))  # text before the hole; the hole itself is code
                    depth += 1
                    j += 1
                    continue
                if interp and ch == "}" and depth:
                    depth -= 1
                    if depth == 0:
                        start = j + 1
                    j += 1
                    continue
                if depth:
                    j += 1
                    continue
                if ch == "\\" and not verbatim:
                    j += 2
                    continue
                if ch == '"':
                    if verbatim and j + 1 < n and line[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            spans.append((start, j))
            i = j + 1
            continue
        if c == "'" and not vb:
            j = line.find("'", i + 2 if i + 1 < n and line[i + 1] == "\\" else i + 1)
            if 0 < j - i <= 8:
                i = j + 1
                continue
        i += 1
    return spans


def code_match(rx, line, vb=False):
    """True when at least one match of rx starts outside a string literal (a pattern that includes the quote starts at it)."""
    spans = None
    for m in rx.finditer(line):
        spans = string_spans(line, vb) if spans is None else spans
        if not any(a <= m.start() < b for a, b in spans):
            return True
    return False
