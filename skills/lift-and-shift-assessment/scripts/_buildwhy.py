"""Plain-language reason for a failed build: why it fails, what is needed, and who has to provide it.
Used by build_doc.py for Section 5.1 and for the workbook sheet Build. Reads only the static check and the real build result."""
import os
import re


def _name(path):
    return re.split(r"[\\/]", path.strip().strip("'\""))[-1]


def _short_path(path):
    parts = [p for p in re.split(r"[\\/]", path.strip().strip("'\"")) if p]
    return "\\".join(parts[-2:]) if len(parts) > 1 else path


def why(st, real):
    """(reason, needed, who) for a FAIL; None when the build did not fail."""
    if real.get("status") != "FAIL":
        return None
    issues = st.get("issues") or []
    errs = " ".join(real.get("errors") or [])
    reasons, needed, who = [], [], []
    dlls = sorted({m.group(1) for i in issues for m in [re.search(r"reference DLL not found \((.+?) expected", i)] if m})
    if dlls:
        reasons.append(f"{len(dlls)} referenced DLL(s) are not in the repositories ({', '.join(dlls[:4])}{', ...' if len(dlls) > 4 else ''})")
        needed.append("the missing DLLs (the shared Library folder or the DLL cache)")
        who.append("the client")
    for m in sorted({_short_path(x) for x in re.findall(r'The project file "(.+?)" was not found', errs)}):
        reasons.append(f"the solution lists a project that is not in the repository ({_name(m)})")
        needed.append(f"the project folder of {_name(m)}")
        who.append("the client")
    for m in sorted({_short_path(x) for x in re.findall(r"Source file '(.+?)' could not be found", errs)}):
        reasons.append(f"a source file the project lists is not in the repository ({m})")
        needed.append(f"the file {_name(m)} (it may be ignored by git)")
        who.append("the client")
    if "Microsoft.Office.Interop" in errs:
        reasons.append("the code uses Office (Outlook) interop, which is not on the build machine")
        needed.append("the Outlook interop assembly on the build agent (or its NuGet package)")
        who.append("us / DevOps build agent")
    m = re.search(r"Could not write to output file '([A-Za-z]:[^']*)'", errs)
    if m:
        reasons.append(f"the project writes its output to a fixed drive path ({m.group(1)[:3]}...)")
        needed.append("a build agent that has that drive and folder, or a one-line change of the project's output path")
        who.append("us / DevOps build agent")
    order = sorted({m.group(2) for i in (st.get("prerequisites") or []) for m in [re.match(r"build order: (.+?) reads (\S+) from another project's bin folder", i)] if m})
    ns = sorted({x for x in re.findall(r"namespace name '([\w.]+)' could not be found", errs)})
    if order and ns and not dlls:
        reasons.append(f"it needs {', '.join(order[:3])} built by another project first (it reads the file from that project's bin folder, and the other project is in another repository)")
        needed.append("the pipeline must build that other project first (build order across repositories)")
        who.append("us / DevOps pipeline")
    elif ns and not dlls:
        reasons.append(f"the code does not compile: referenced assemblies or namespaces are not found ({', '.join(ns[:4])})")
        needed.append("the assemblies behind those names (most likely Library DLLs)")
        who.append("the client")
    elif dlls and re.search(r"error CS0(234|246)", errs):
        reasons.append("the compile errors follow from the missing DLLs")
    if not reasons:
        first = re.sub(r"\s*\[[A-Za-z]:\\.*$", "", (real.get("errors") or ["no error text captured"])[0])[:140]
        reasons.append(f"build error: {first}")
        needed.append("to be analysed")
        who.append("to be analysed")
    uniq = lambda xs: list(dict.fromkeys(xs))
    return "; ".join(uniq(reasons)), "; ".join(uniq(needed)), ", ".join(uniq(who))


def note(real):
    """What the pipeline must do on top of a plain restore for this solution to build (packages installed into a local folder)."""
    pk = real.get("packages_installed") or []
    out = [("The pipeline must install into a local packages folder: " + ", ".join(pk[:6]) + (" and more" if len(pk) > 6 else "")) if pk else ""]
    if real.get("status") == "PASS" and real.get("workarounds"):
        out.append("Contingent pass: builds only with " + str(len(real["workarounds"])) + " workaround(s) in the build copy, listed in sheet Build")
    return "; ".join(x for x in out if x)


def result_label(real):
    """The build result as shown in the workbook: a pass that needed workarounds in the copy is a contingent pass."""
    st = real.get("status", "NOT RUN")
    return "PASS with workaround" if st == "PASS" and real.get("workarounds") else st
