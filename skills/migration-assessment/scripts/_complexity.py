"""Code-complexity metrics per source file and per project (deterministic, regex based, no compiler needed).

The effort engine (estimate_effort.py) multiplies a project's conversion hours by a complexity factor, so two projects with
the same line count but different logic density are not costed the same.

Metrics (hand-written C# / VB.NET only; generated code is excluded):
  decisions      decision points: if / else if / for / foreach / while / case / catch / when / && / || / ??  (a McCabe proxy)
  methods        method and constructor signatures
  cc_per_method  (decisions + methods) / methods: average cyclomatic complexity
  decisions_per_kloc  decision density, comparable across projects of different size
  big_files      files over BIG_FILE_LINES lines (hard to port and review in one piece)
"""
import re

BIG_FILE_LINES = 800  # past this a single file takes more than a day to read and port carefully

_STRING = re.compile(r'@"(?:[^"]|"")*"|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)\'')
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_DECISION_CS = re.compile(r"\b(?:if|else\s+if|for|foreach|while|case|catch|when)\b|&&|\|\||\?\?")
# VB.NET keywords are case-insensitive and spelled differently (ElseIf, For Each, AndAlso, OrElse); comments start with '
_DECISION_VB = re.compile(r"(?<!end\s)(?<!select\s)\b(?:if|elseif|for|while|case|catch|when|andalso|orelse)\b", re.I)
_VB_STRING = re.compile(r'"(?:[^"\n]|"")*"')
_VB_COMMENT = re.compile(r"'[^\n]*|\bRem\b[^\n]*", re.I)
_METHOD = re.compile(
    r"(?m)^\s*(?:\[[^\]\n]*\]\s*)*(?:public|private|protected|internal|static|override|virtual|async|Public|Private|Protected|Friend|Shared|Overrides)"
    r"[\w\s<>\[\],.?*]*\([^;{}]*\)\s*(?:where\s+[^{;]+)?\s*(?:\{|=>|$)")


def file_metrics(text, vb=False):
    """Decision points and method count of one source file (vb=True for VB.NET: case-insensitive keywords)."""
    if vb:
        clean = _VB_COMMENT.sub(" ", _VB_STRING.sub('""', text))
    else:
        clean = _COMMENT.sub(" ", _STRING.sub('""', text))
    return {"decisions": len((_DECISION_VB if vb else _DECISION_CS).findall(clean)), "methods": len(_METHOD.findall(clean)), "lines": text.count("\n") + 1}


def project_metrics(files):
    """Aggregate file_metrics dicts for one project into the numbers stored in the inventory."""
    dec = sum(f["decisions"] for f in files)
    met = sum(f["methods"] for f in files)
    lines = sum(f["lines"] for f in files)
    return {"decisions": dec, "methods": met, "files": len(files), "lines": lines,
            "cc_per_method": round((dec + met) / met, 2) if met else 0.0,
            "decisions_per_kloc": round(dec / (lines / 1000.0), 1) if lines else 0.0,
            "big_files": sum(1 for f in files if f["lines"] > BIG_FILE_LINES)}
