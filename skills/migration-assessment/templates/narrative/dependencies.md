<!-- Judgment on top of the generated dependency tables (4.5 project interdependencies, 4.6 workflow dependencies,
4.7 database object dependencies). The tables are name-based leads: confirm them for the workflows that matter.
Cover: (1) the critical shared projects whose change touches the most applications and the order they must be ported in
(layer 0 first); (2) the business workflows (order-to-cash, nightly jobs, reporting, integrations) that cross several projects,
database objects or external systems, in business terms, and which of them are riskiest to migrate (cite F-nnn and file:line);
(3) dependencies the scanner cannot see (DI by convention, reflection, dynamic SQL, EF-generated SQL, scheduled tasks,
cross-repository calls) with the question for the client; (4) workflows that must be regression-tested together and the
database objects that make them move together (dual-database sync). Use graphify (`path`, `affected`, `explain`) to check
a trace. Delete the PENDING line. -->
PENDING: describe project and workflow dependencies.
