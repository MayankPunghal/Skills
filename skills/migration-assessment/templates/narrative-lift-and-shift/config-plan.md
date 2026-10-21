<!-- Judgement on the configuration work, above the generated tables of section 4. Cover: how settings reach the servers today (read the CFG-TRANSFORMS finding
and the configuration files: transforms, machine config, appsettings, includes via configSource / appSettings file=), whether the generated tokenised
templates fit that (for example settings that live in a file outside the repository, such as an appSettings file= include, are not in the templates and the
client must supply that file), the settings that need a decision before a value can be set (internal servers that may move, secrets that are rotated),
variables whose values differ between projects, the encrypted sections (CFG-PROTECTED-SECTION) and how their key is moved, and any value the tool could
not tokenise (see 4.5). Never print a secret or a connection string value; names, hosts, IPs and paths are fine. Delete the PENDING line. -->
PENDING: write the configuration plan.
