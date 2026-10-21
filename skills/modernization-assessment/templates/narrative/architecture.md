<!-- What the applications do and how they connect, from the code (graphify query/explain + reading entry points).
One short paragraph per application: purpose, main modules, data stores, integrations, who calls it. Then which systems
remain outside AWS after migration (on-prem endpoints from the dependency table) and the network path they need.
Use `graphify query "<question>" --graph assessment/graphs/<repo>/graphify-out/graph.json --budget 800` to orient.
For C#, also say how each application is composed (report 4.2 "Run-time wiring", from analysis.json "wiring"): which DI
container and where its composition root is, the lifetimes that matter, messaging (MediatR / bus), background jobs,
middleware / filter pipeline, and what moving the composition root to Program.cs involves (cite the di-wiring findings).
Community names and one-line summaries in analysis.json "communities" help describe the modules.
Delete the PENDING line. -->
PENDING: describe the architecture.
