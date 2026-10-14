"""Lines of code the way the ATF Codebase Scanner counts them: executable lines only.

A line counts when it still holds something after comments are removed. Blank lines, comment-only lines and lines that are only a
single bracket ({ } ( ) [ ]) do not count. C# (and Razor views) use C-style comments, VB uses ' and REM, WebForms and XAML use
<!-- --> and <%-- --%>. Comment markers inside string literals are not comments.

    from _loc import count_loc
    n = count_loc(text, ".cs")
"""
import re

C_FAMILY = {".cs", ".csx", ".cshtml", ".razor", ".fs", ".fsx", ".fsi"}
VB_FAMILY = {".vb", ".vbhtml"}
XML_FAMILY = {".aspx", ".ascx", ".master", ".asax", ".ashx", ".asmx", ".svc", ".xaml"}
LONE = set("{}()[]")


def _strip_c(text):
    """Remove // and /* */ comments; keep strings (verbatim, raw, interpolated and char literals included)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            while i < n and text[i] != "\n":
                i += 1
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("\n" * text.count("\n", i, j))  # keep the line breaks so line structure stays
            i = j
        elif text.startswith('"""', i):
            j = text.find('"""', i + 3)
            j = n if j < 0 else j + 3
            out.append(text[i:j])
            i = j
        elif c == '"' or (c in "@$" and re.match(r'[@$]{1,2}"', text[i:i + 3])):
            m = re.match(r'[@$]{0,2}"', text[i:i + 3])
            verbatim = "@" in m.group(0)
            j = i + len(m.group(0))
            while j < n:
                if verbatim:
                    if text[j] == '"':
                        if text[j + 1:j + 2] == '"':
                            j += 2
                            continue
                        break
                else:
                    if text[j] == "\\":
                        j += 2
                        continue
                    if text[j] == '"' or text[j] == "\n":
                        break
                j += 1
            out.append(text[i:j + 1])
            i = j + 1
        elif c == "'" and re.match(r"'(\\.[^']{0,6}|[^'\\\n])'", text[i:i + 10]):  # a char literal; a lone apostrophe in markup text is not
            m = re.match(r"'(\\.[^']{0,6}|[^'\\\n])'", text[i:i + 10])
            out.append(m.group(0))
            i += len(m.group(0))
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _strip_vb(text):
    out = []
    for line in text.splitlines():
        s = line.lstrip()
        if s.upper().startswith("REM ") or s.upper() == "REM":
            out.append("")
            continue
        in_str, cut = False, len(line)
        for k, ch in enumerate(line):
            if ch == '"':
                in_str = not in_str
            elif ch == "'" and not in_str:
                cut = k
                break
        out.append(line[:cut])
    return "\n".join(out)


def _strip_xml(text):
    text = re.sub(r"<%--.*?--%>", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


def count_loc(text, ext):
    ext = ext.lower()
    if ext in C_FAMILY:
        text = _strip_c(text)
        if ext in (".cshtml", ".razor"):
            text = re.sub(r"@\*.*?\*@", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
            text = _strip_xml(text)
    elif ext in VB_FAMILY:
        text = _strip_vb(text)
        if ext == ".vbhtml":
            text = _strip_xml(text)
    elif ext in XML_FAMILY:
        text = _strip_xml(text)
    n = 0
    for line in text.splitlines():
        t = line.strip()
        if not t or (len(t) == 1 and t in LONE):
            continue
        n += 1
    return n
