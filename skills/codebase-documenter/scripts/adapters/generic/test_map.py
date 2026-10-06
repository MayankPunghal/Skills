"""Test map: which production methods the tests reach through the call graph, and which nothing tests.

Writes docs/reference/test-map.md from docs/agent/methods.json (the method map; run after generic-graph / generic-methods).
A test method is any method in a .NET test project (one that references a test framework or the test SDK) or in a file
named / placed like a test (adapter_options.generic-tests.test_regex) that holds at least one test case. From every test the
call graph is followed (up to max_depth calls, default 8, INFERRED edges included); every production method on the way
is "reached". This is static reachability, not run-time coverage. For C# with generic-di, calls through DI registrations,
interfaces, overrides, messages, events and stored delegates are followed; reflection, HTTP and SQL are not, so
"not reached" means "no test calls it in a way the graph can see".
"""
import os
import re
from collections import defaultdict, deque

from _scan import BACK, OUT, ROOT, Methods, esc, options, project_of, read, slug, write_page
from _stats import stat  # noqa: E402  (headline numbers for [[n:...]] tags)

OPT = options("generic-tests")
TEST_RX = re.compile(OPT.get("test_regex", r"(^|/)(tests?|specs?|__tests__|testing)(/|$)|[._-](tests?|spec)\.\w+$|Tests?\.\w+$|"
                                          r"(^|/)test_\w+\.py$|_test\.(go|py)$|IntegrationTests?|UnitTests?"), re.I)
DEPTH = OPT.get("max_depth", 8)
MAX_TESTS_SHOWN = 4
# a test case, not a helper in a test file: xUnit / NUnit / MSTest attributes, JUnit @Test, test_* / Test* functions, it( / test(
CASE = re.compile(r"\[\s*(?:\w+\.)*(Fact|Theory|Test|TestMethod|DataTestMethod|TestCase\w*|TestCaseSource|Property)\b|@(Test|ParameterizedTest)\b|"
                  r"^\s*(?:async\s+)?def\s+test_|^\s*func\s+Test\w*\(|\b(?:it|test)\s*\(\s*['\"`]", re.M)
# a .NET project that references a test framework or the test SDK is a test project, whatever its files are called
TEST_PKG = re.compile(r"(?i)Microsoft\.NET\.Test\.Sdk|\b(?:xunit|nunit|MSTest\.TestFramework|MSTest\.Sdk)\b|"
                      r"Microsoft\.VisualStudio\.(?:QualityTools\.)?UnitTest")
_lines = {}
_test_proj = {}


def test_project(f):
    p = project_of(f)
    if p not in _test_proj:
        d = os.path.join(ROOT, p) if p != "." else ROOT
        try:
            manifests = [x for x in os.listdir(d) if re.search(r"(?i)\.(cs|vb|fs)proj$|^packages\.config$", x)]
        except OSError:
            manifests = []
        _test_proj[p] = any(TEST_PKG.search(read(os.path.join(d, x))) for x in manifests)
    return _test_proj[p]


def test_file(f, _cache={}):
    """A file of tests: in a .NET test project, or named / placed like a test AND holding a test case. A business feature
    called "Backtest" (Models/Backtest.cs, Scripts/BackTesting/BackTest.js) matches the name pattern but has no test case."""
    if f not in _cache:
        _cache[f] = test_project(f) or bool(TEST_RX.search(f) and CASE.search(read(os.path.join(ROOT, f))))
    return _cache[f]


def is_case(x):
    """Is the method at x['file']:x['line'] a test case? Reads the declaration and the attribute lines above it."""
    f = x["file"]
    if f not in _lines:
        _lines[f] = read(os.path.join(ROOT, f)).splitlines()
    ln = x.get("line") or 0
    return bool(ln) and any(CASE.search(t) for t in _lines[f][max(0, ln - 4):ln])


def main():
    m = Methods()
    if not m.data:
        print("test-map: docs/agent/methods.json not found (needs generic-graph or generic-methods earlier in the adapters)")
        return
    tests = [a for a, x in m.data.items() if test_file(x["file"])]
    tset = set(tests)
    prod = {a for a in m.data if a not in tset}
    reached = defaultdict(set)  # production method -> tests that reach it
    direct = defaultdict(set)   # production method -> tests that call it directly
    for t in tests:
        seen, q = {t}, deque([(t, 0)])
        while q:
            a, d = q.popleft()
            if d >= DEPTH:
                continue
            for b in m.data[a].get("calls", []):
                if b in seen or b not in m.data:
                    continue
                seen.add(b)
                if b in prod:
                    reached[b].add(t)
                    if d == 0:
                        direct[b].add(t)
                q.append((b, d + 1))
    by_proj = defaultdict(list)
    for a in prod:
        by_proj[project_of(m.data[a]["file"])].append(a)
    total = len(prod)
    hit = len(reached)
    cases = sum(1 for t in tests if is_case(m.data[t]))
    helpers = len(tests) - cases
    out = ["# Test map", "",
           f"{cases} test cases" + (f" (and {helpers} helper method{'s' if helpers != 1 else ''} in test files)" if helpers else "") + f" reach {hit} of {total} production methods ({(100 * hit // total) if total else 0}%) through the "
           "call graph. This is static reachability, not run-time coverage: calls resolved from the code (including, for C#, "
           "dependency injection, interfaces, overrides, messages and events) are followed; reflection, HTTP calls to the "
           "application and SQL are not. Treat \"not reached\" as \"no test calls it in a way the code shows\" and "
           "check before reporting a gap. **Bold** tests call the method directly.", "", '<a id="index"></a>', "",
           "| Project | Methods | Reached by tests | Share |", "| --- | ---: | ---: | ---: |"]
    for p in sorted(by_proj):
        ids = by_proj[p]
        r = sum(1 for a in ids if a in reached)
        out.append(f"| [{esc(p)}](#{slug('area', p)}) | {len(ids)} | {r} | {100 * r // len(ids)}% |")
    test_files = sorted({m.data[t]["file"] for t in tests})
    # database routines tests exercise directly through SQL text (common in integration tests)
    routines = {}
    for page in (os.listdir(OUT) if os.path.isdir(OUT) else []):
        if page.endswith("routines.md"):
            for a in re.findall(r'<a id="(sp-[^"]+)"', read(os.path.join(OUT, page))):
                routines.setdefault(a, page)
    sql_hits, shown_as = defaultdict(set), {}
    for f in test_files:
        for tok in set(re.findall(r"[A-Za-z_][\w.]*", read(os.path.join(ROOT, f)))):
            for cand in (tok, tok.split(".")[-1]):
                a = slug("sp", cand)
                if a in routines:
                    sql_hits[a].add(f)
                    shown_as.setdefault(a, cand)
    out += ["", f"Test files ({len(test_files)}): " + (", ".join(f"`{esc(f)}`" for f in test_files[:40]) or "none found") +
            (f" +{len(test_files) - 40} more" if len(test_files) > 40 else "")]
    if sql_hits:
        out += ["", f"Database routines named in test code ({len(sql_hits)} of {len(routines)}): " + ", ".join(
            f"[{shown_as[a]}]({routines[a]}#{a})" for a in sorted(sql_hits))]
    for p in sorted(by_proj):
        ids = sorted(by_proj[p], key=lambda a: m.data[a]["name"].lower())
        got = [a for a in ids if a in reached]
        miss = [a for a in ids if a not in reached]
        out += ["", f'<a id="{slug("area", p)}"></a>', "", f"## {p}", "", BACK, ""]
        if got:
            out += ["| Method | Reached by |", "| --- | --- |"]
            for a in got:
                ts = sorted(reached[a], key=lambda t: (t not in direct[a], m.data[t]["name"]))
                shown = ", ".join(("**" + m.link(t) + "**") if t in direct[a] else m.link(t) for t in ts[:MAX_TESTS_SHOWN])
                out.append(f"| {m.link(a)} | {shown}{f' +{len(ts) - MAX_TESTS_SHOWN} more' if len(ts) > MAX_TESTS_SHOWN else ''} |")
            out.append("")
        out.append(f"**Not reached by any test ({len(miss)}):** " + (", ".join(m.link(a) for a in miss) or "none"))
    write_page("test-map.md", out)
    stat("tests", tests=cases, test_file_methods=len(tests), methods_reached=hit, methods=total)
    print(f"test-map: {cases} test cases ({len(tests)} methods in test files) reach {hit}/{total} production methods")


if __name__ == "__main__":
    main()
