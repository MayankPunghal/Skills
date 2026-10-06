# Page patterns

## Contents

- Module page (`modules/<module>.md`)
- Screens and actions
- <Engine / process name> (step by step)
- Statuses
- Data
- Integrations
- Permissions
- Integration page (`integrations/<system>.md`)
- Outbound: <operation>
- Inbound: <operation>
- Known issues
- State machine (`workflows/state-machines.md` section)
- <Object> status
- End-to-end journey (`workflows/end-to-end.md`)
- Security findings register (`security/findings.md`)
- SEC-01 · <title> — Critical
- Defects register (`appendices/defects.md`)
- Glossary (`appendices/glossary.md`)
- Codes & statuses (`data/codes-and-statuses.md`)
- Composition and run-time wiring (`architecture/dependency-injection.md`)
- Diagrams


Proven layouts. Replace `<…>`; delete rows that do not apply; keep the order.

## Module page (`modules/<module>.md`)

```markdown
# <Module name>

<One paragraph: what the module is for, who uses it, where it sits in the journey.>

## Screens and actions
| Screen / action | What it does | Rules / side effects | Code |
| --- | --- | --- | --- |
| <Create order> | <business behaviour> | <emails, statuses, documents> | [[act:Order.Create]] |

## <Engine / process name> (step by step)
1. <step, with exact condition> ([[proc:Order_Calculate]])
2. …

## Statuses
<table or link to [[page:workflows/state-machines.md#orders|state machine]]>

## Data
| Object | Table | Notes |
| --- | --- | --- |

## Integrations
<links to integration pages, with trigger>

## Permissions
<roles / claims; anonymous entry points>

!!! warning "Known issues"
    <DEF-nn / SEC-nn with links>
```

## Integration page (`integrations/<system>.md`)

```markdown
# <System> (<what it is, one phrase>)

| Item | Value |
| --- | --- |
| Direction | Outbound / inbound / both |
| Trigger | <user action, job, event> |
| Configuration | `<GROUP/KEY_NAME>` (names only) |
| Payload builder | [[proc:X]] / [[cls:X]] |
| Authentication | <OAuth client credentials, basic, token env name> |
| Response handling | <success / failure handlers> |
| Logging | [[table:Json_Log]] |

## Outbound: <operation>
## Inbound: <operation>
## Known issues
```

## State machine (`workflows/state-machines.md` section)

````markdown
## <Object> status
```mermaid
stateDiagram-v2
  [*] --> Requested
  Requested --> Submitted: submit (OrderController.Submit)
  Submitted --> Placed: billing system accepts order (BillingCallbackService)
```
| From | To | Trigger | Code | Who |
| --- | --- | --- | --- | --- |
````

## End-to-end journey (`workflows/end-to-end.md`)

Sequence diagram (actors + systems), a stage table (`# · Stage · Actors · Module page · Status after`) and a hand-off table (`From → to · What travels · Built by`).

## Security findings register (`security/findings.md`)

Summary table (`Id · Severity · Finding · Area`) with links to sections; each section:

```markdown
<a id="sec-01"></a>
## SEC-01 · <title> — Critical
- **Where**: `<file>`, `<method>`.
- **What**: <condition>.
- **Impact**: <who can do what>.
- **Recommendation**: <fix>.
```

## Defects register (`appendices/defects.md`)

`Id · Priority · Area · Defect · Effect · Where` for DEF-nn; `Id · Item · Recommendation` for TD-nn.

## Glossary (`appendices/glossary.md`)

`Term · Meaning` alphabetically; link to the page that explains it; mark unknown expansions.

## Codes & statuses (`data/codes-and-statuses.md`)

One table per code set from enums **and** seed data (`Id · Name · Active · Meaning`), with a link to the enum and seed entries (`[[enum:X]]`, `[[seed:X]]`).

## Composition and run-time wiring (`architecture/dependency-injection.md`)

The narrative over the generated `reference/dependency-injection.md` (C#, generic-di adapter): link, do not retype its tables. Tags: `[[di:<Service>]]` (a registered service), `[[di:msg-<Message>]]`, `[[di:host-<Project>]]`, `[[di:find-<n>]]`, plus `[[cls:…]]` / `[[mth:…]]` for the classes and methods.

- **Composition roots and hosts**: one paragraph per host (web app, API, worker): where the container is built (`Program.cs`, `Startup.ConfigureServices`, a module class, an extension method such as `AddInfrastructure`), which registration modules it pulls in, framework features it switches on (sessions, caching, health checks, auth).
- **Registrations and lifetimes**: a table of the services that matter to the business (`Service · Implementation · Lifetime · Host · Notes`), grouped by layer; say why a lifetime was chosen when the code shows it (singleton caches, scoped DbContext). Decorators as "A is wrapped by B (logging / caching / retry)". Keyed or named services with the key and who asks for it.
- **How interface and virtual calls are dispatched**: for every interface with several implementations, which one each host injects; for every abstract / virtual method on a business path, the overrides and when each runs; partial classes and where their parts live.
- **Messages and handlers**: `Message · Kind (command / query / event / notification) · Handler · Sent from` and the pipeline behaviours around them (validation, logging, transactions). Messages with no sender in the code are named.
- **Events, delegates and method groups**: `Event / delegate · Raised or invoked by · Handled by · Wired in`. Stored lambdas and dispatch tables in plain words ("the scenario list holds one lambda per scenario; the runner calls each in turn").
- **Pipeline**: middleware in order, MVC / endpoint filters (global, controller, action), hosted services, startup filters; a `flowchart LR` of one request through them. Minimal-API endpoints: handler lambda → the method it calls.
- **Background jobs and scheduled work**: `Job · Scheduled / enqueued by · Runs · Retries`; schedules kept outside the repository are named as such.
- **Configuration and options**: options classes, the section each binds to, who consumes them (key names only).
- **Wiring risks and findings**: each finding from `#di-findings`, checked in code: real → DEF-nn; false positive → say why in one line.
- **How to trace a call through the wiring**: `trace_flow.py <Class.Method>` (hops show `[di registration]`, `[override]`, `[message]` …), `lookup.py`, and what static analysis cannot see (reflection, configuration-driven types, other repositories).

## Diagrams

- Mermaid only (renders in MkDocs and GitHub); real names; ≤ ~15 nodes per diagram; split otherwise.
- Context: `flowchart LR` users / system / externals. Containers: `flowchart TB`. Sequences: `sequenceDiagram` with `autonumber`. Data: `erDiagram` with the 10–20 core entities.
- `graphify export callflow-html` output is a starting point; verify every arrow before reusing it.
- Syntax traps MkDocs never reports (the diagram only fails in the browser; `verify_docs.py` lints them): no `;` in a sequence message or an unquoted label (it ends the statement: write `,` or `#59;`); quote labels with spaces or symbols and write a `"` inside one as `#quot;`; never use `end` as a node id (`End`, `end_`); keep `[ ] ( ) { }` balanced on each flowchart line.
