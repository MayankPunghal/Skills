# Review lenses

What to look for on each axis. The **Quality** axis applies lenses A–F; the **Standards** axis applies the repository's documented rules plus the smell baseline; both use the false-positive filters before a finding is reported.

## Contents

- [Quality axis: lenses A–F](#quality-axis-lenses-af)
- [Standards axis: smell baseline](#standards-axis-smell-baseline)
- [False-positive filters](#false-positive-filters)
- [Severity decision guide](#severity-decision-guide)
- [Risk rating: impact × likelihood](#risk-rating-impact--likelihood)

## Quality axis: lenses A–F

You are reviewing for **correctness, security, design, performance, and maintainability**. Apply the following lenses systematically.

### A. Correctness & Bugs (Highest Priority)
| Pattern | What to Check |
|---------|---------------|
| **Null/undefined handling** | Guard clauses, optional chaining, defensive checks before dereference |
| **Boundary conditions** | Off-by-one, empty collections, zero/negative values, max int overflow |
| **Concurrency/race conditions** | Shared mutable state, non-atomic check-then-act, missing locks, async ordering bugs |
| **Resource leaks** | Unclosed connections/streams/files, missing `using`/`try-finally`/`defer`, event listener cleanup |
| **Exception handling** | Swallowed exceptions, overly broad `catch`, exception masking, stack trace loss |
| **Logic errors** | Inverted conditions, wrong operator (`=` vs `==`), incorrect loop bounds, wrong branch taken |
| **State machine violations** | Invalid transitions, missing states, orphaned states |
| **Idempotency** | Retry safety, duplicate request handling, exactly-once semantics |

### B. Security (Highest Priority)
| Category | Specific Checks |
|----------|-----------------|
| **Injection** | SQL/NoSQL/LDAP/OS command injection — parameterized queries, input validation, allowlists |
| **Path traversal** | `../` in file paths, `Path.Combine` misuse, user-controlled paths |
| **Secrets exposure** | API keys, passwords, tokens, connection strings in code/config committed |
| **Authentication/Authorization** | Missing authz checks, privilege escalation, broken object-level authz (BOLA), JWT validation flaws |
| **Deserialization** | Untrusted data deserialized (JSON.NET TypeNameHandling, Java serialization, pickle, YAML unsafe load) |
| **XSS/CSRF** | Unescaped output in HTML/JS contexts, missing CSRF tokens on state-changing ops |
| **Crypto** | Weak algorithms (MD5, SHA1, DES), hardcoded keys/IVs, ECB mode, custom crypto |
| **SSRF/RCE** | User-controlled URLs fetched, arbitrary code execution via templates/scripts |
| **Data exposure** | PII in logs, verbose error messages, excessive API response fields |
| **Supply chain** | Suspicious new dependencies, typosquatting, unpinned versions |

### C. Design & Architecture
| Principle | Violations to Flag |
|-----------|-------------------|
| **Single Responsibility** | Classes/functions doing too many things, god objects |
| **Open/Closed** | Modifying existing stable code instead of extending, switch on type instead of polymorphism |
| **Liskov Substitution** | Subtypes breaking base contracts, strengthened preconditions/weakened postconditions |
| **Interface Segregation** | Fat interfaces forcing unused implementations |
| **Dependency Inversion** | High-level modules depending on low-level concretions, missing abstractions |
| **Layer Boundaries** | UI calling DB directly, domain logic in controllers, cross-layer cycles |
| **Coupling** | Tight coupling via global state, singletons, static calls, circular deps |
| **Cohesion** | Scattered related logic, feature envy, data clumps |
| **Abstraction Leaks** | Implementation details in public APIs, leaky DTOs, ORM entities exposed |
| **Consistency** | Inconsistent patterns (naming, error handling, async style) across codebase |

### D. Performance
| Area | Red Flags |
|------|-----------|
| **Database** | N+1 queries, missing indexes, Cartesian products, unbounded result sets, eager loading everything |
| **Memory** | Large allocations in loops, unbounded collections, caching without eviction, string concatenation in hot paths |
| **Async/Concurrency** | Sync-over-async (`.Result`, `.Wait()`), thread pool starvation, missing cancellation tokens |
| **Algorithmic** | O(n²) where O(n log n) possible, repeated computation, missing memoization |
| **Network** | Chatty APIs, missing batching, no connection pooling, large payloads |
| **Serialization** | Heavy serializers in hot paths, excessive object graphs |

### E. Maintainability & Observability
| Concern | What to Flag |
|---------|--------------|
| **Testing** | No tests for new logic, flaky tests, testing implementation not behavior, missing edge cases |
| **Logging** | Missing correlation IDs, log levels wrong (debug in prod), sensitive data in logs, structured logging absent |
| **Metrics/Tracing** | No instrumentation on critical paths, missing spans, high-cardinality labels |
| **Documentation** | Public APIs undocumented, complex algorithms without comments, outdated docs |
| **Error Messages** | Generic "failed", no actionable info, missing context for debugging |
| **Configuration** | Hardcoded values that should be config, missing validation, secrets in config |

### F'. When the capped diff isn't enough

`gh-context.mjs` caps context to keep the default call cheap (see "Token minimization" in SKILL.md) — that's a default, not a ceiling. Two situations mean you're not seeing enough to judge a finding:
- A file's `patch` field is `null`/missing in the `files` array — GitHub itself omitted the diff (huge change).
- You're looking at a truncation marker (`... (truncated: ...)`) or the `-U3` context window cuts off right where you'd need to see more (e.g. to check whether a variable is null-checked a few lines outside the shown hunk).

In either case, pull that one file's full content instead of guessing:
```bash
node <skill-base-dir>/scripts/fetch-file.mjs --owner <owner> --repo <repo> --path <path> --ref <headSha>
```
Use this selectively, for the specific file(s) a finding's confidence depends on — not as a default for every file in the PR, or you lose the point of the cap.

The selective rule is about *extra context around a shown hunk*. Files in the context's `coverage` block are different: `patchMissing` and `notInDiff` files have no diff at all, and `truncated` files were cut off, so read every one of them (fetch-file, or the local file in a local review) before the review is complete. `excluded` files are generated or vendored and are skipped.

### F. Language/Platform Specific (apply as relevant)
- **C#/.NET**: `IDisposable` not implemented/disposed, `async void`, capture of loop variable, `ConfigureAwait(false)` missing, reflection in hot path, boxing in loops
- **JavaScript/TypeScript**: `any` type, missing `await`, event loop blocking, prototype pollution, prototype chain issues
- **Python**: Mutable default args, late binding closures, GIL-unaware CPU work, `eval`/`exec`
- **Go**: Error wrapping lost, goroutine leaks, `defer` in loops, interface nil checks
- **Database**: Missing migrations, destructive schema changes without backward compat, missing foreign keys

## Standards axis: smell baseline

On top of whatever the repository documents, the Standards axis always carries this baseline: a fixed set of Fowler code smells (*Refactoring*, ch. 3) that applies even when a repository documents nothing. Two rules bind it:

- **The repo overrides.** A documented repo standard always wins; where it endorses something the baseline would flag, suppress the smell.
- **Always a judgement call.** Each smell is a labelled heuristic ("possible Feature Envy", `kind: "judgement"`), never a hard violation. Like any standard here, skip anything tooling already enforces (`tooling` in the context: linters, formatters, analyzers).

Each smell reads *what it is* → *how to fix*; match it against the diff:

- **Mysterious Name**: a function, variable, or type whose name doesn't reveal what it does or holds. → rename it; if no honest name comes, the design's murky.
- **Duplicated Code**: the same logic shape appears in more than one hunk or file in the change. → extract the shared shape, call it from both.
- **Feature Envy**: a method that reaches into another object's data more than its own. → move the method onto the data it envies.
- **Data Clumps**: the same few fields or params keep travelling together (a type wanting to be born). → bundle them into one type, pass that.
- **Primitive Obsession**: a primitive or string standing in for a domain concept that deserves its own type. → give the concept its own small type.
- **Repeated Switches**: the same `switch`/`if`-cascade on the same type recurs across the change. → replace with polymorphism, or one map both sites share.
- **Shotgun Surgery**: one logical change forces scattered edits across many files in the diff. → gather what changes together into one module.
- **Divergent Change**: one file or module is edited for several unrelated reasons. → split so each module changes for one reason.
- **Speculative Generality**: abstraction, parameters, or hooks added for needs the spec doesn't have. → delete it; inline back until a real need shows.
- **Message Chains**: long `a.b().c().d()` navigation the caller shouldn't depend on. → hide the walk behind one method on the first object.
- **Middle Man**: a class or function that mostly just delegates onward. → cut it, call the real target direct.
- **Refused Bequest**: a subclass or implementer that ignores or overrides most of what it inherits. → drop the inheritance, use composition.

Documented-standard breaches can be hard (`kind: "hard"`): cite the file and the rule in `rule` (e.g. `CONTRIBUTING.md: "public methods need XML docs"`).

*The two-axis method (Standards and Spec as separate reports) and this smell baseline are adapted from Matt Pocock's `code-review` skill ([mattpocock/skills](https://github.com/mattpocock/skills/tree/main/skills/engineering/code-review), MIT License, © 2026 Matt Pocock).*

## False-positive filters

Before a finding goes in the report, it must survive all of these:

- **It is in the change.** The cited line is added or modified by this diff, or the diff makes existing code newly reachable, newly wrong, or worse. Untouched pre-existing problems are out of scope unless the change depends on them; mention one in the summary at most.
- **The line is right.** `line` is the new-file line at the head commit (right side of the diff). Re-read it before reporting.
- **It is not handled elsewhere.** Check the caller, guard clauses, middleware, validation layers and tests a few hops out (fetch the file) before calling something unhandled.
- **Tooling does not already catch it.** Skip what a configured linter, formatter, analyzer or a failing CI check already reports.
- **It is not already raised.** Skip what `existingComments` already says on that file and line; add to the thread only with new evidence.
- **It is concrete.** A finding names the input, state or sequence that goes wrong. "Could be a problem" without a trigger is a judgement call at most, or no finding.
- **It is not taste.** No style nits unless they cause real problems; no praise; no restating the diff.

## Severity decision guide

| If the issue... | Severity |
|-----------------|----------|
| Allows unauthorized access, data breach, RCE, injection | `security` |
| Causes wrong results, crashes, data corruption, deadlock | `bug` |
| Violates architecture, creates technical debt, hinders future changes | `design` |
| Causes measurable slowdown, resource waste, scalability limit | `performance` |
| Makes code harder to understand, test, debug, or operate | `maintainability` |

**Severity ordering** (within the Quality axis): `security` > `bug` > `design` > `performance` > `maintainability`. Severity is the *kind* of problem; the risk rating below is *how big* it is.

## Risk rating: impact × likelihood

Every finding gets `impact` and `likelihood` (each `high`, `medium` or `low`); the scripts derive `risk` from this matrix:

| Impact ↓ / Likelihood → | high | medium | low |
|---|---|---|---|
| **high** | critical | high | medium |
| **medium** | high | medium | low |
| **low** | medium | low | low |

- **Impact**: what breaks and for whom. High = security breach, data loss or corruption, outage, wrong money or legal output. Medium = a feature misbehaves for some users, a recoverable error, notable slowdown, a standard broken in a way that spreads. Low = local, cosmetic or maintainability cost only.
- **Likelihood**: how often the path runs and how easy the trigger is. High = every request / normal use / attacker-controlled input. Medium = specific but realistic inputs or timing. Low = rare edge case, misconfiguration, or needs another failure first.
- Set `risk` yourself only to override the matrix, and say why in `issue`; `findings-cache.mjs --save` warns on a mismatch.
