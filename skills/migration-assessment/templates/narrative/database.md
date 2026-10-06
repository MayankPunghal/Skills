<!-- Database code recommendation in prose: dual SQL Server + PostgreSQL or PostgreSQL only, why (cite F-nnn database findings), what
must be rewritten (procedures, CLR, data access), tooling for the first pass (AWS DMS Schema Conversion), and the dual-database cost trade-off.
Use the generated database inventory (section 6): the conversion-levels table (auto / rewrite / redesign), the "Cannot be
converted as written" table (name each redesign item and where it lives: procedure or C# file), SQL embedded in code and
how much is built at run time, and parse errors (scripts the parser could not read are not costed). Name the shared tables
and multi-writer tables from 4.8 that force applications to cut over together.
If no database code was in the repositories, say so and list what the client must provide (schema export). Delete the PENDING line. -->
PENDING: write the database recommendation.
