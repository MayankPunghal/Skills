<!-- Judgment on top of the generated dependency tables (4.5 project interdependencies, 4.6 workflow dependencies,
4.7 database object dependencies, 4.8 database objects shared between applications). The tables are name-based leads: confirm them for the workflows that matter.
Cover: (1) the critical shared projects whose change touches the most applications and the order they must be ported in
(layer 0 first); (2) the business workflows (order-to-cash, nightly jobs, reporting, integrations) that cross several projects,
database objects or external systems, in business terms, and which of them are riskiest to migrate (cite F-nnn and file:line);
(3) dependencies the scanner cannot see (DI by unreadable convention, reflection, dynamic SQL, EF-generated SQL, scheduled
tasks, cross-repository calls) with the question for the client; for C#, the run-time-bound calls the resolver did find
(report 4.2 "Run-time wiring": DI dispatch, decorators, messages, events, delegates, jobs) are part of the traces, so name
the workflows that hinge on them; (4) workflows that must be regression-tested together and the
database objects that make them move together (dual-database sync); from 4.8, which applications share tables or
procedures (one cut-over group) and which tables more than one application writes (data ownership question for the client). Use graphify (`path`, `affected`, `explain`) to check
a trace. Delete the PENDING line. -->
PENDING: describe project and workflow dependencies.
