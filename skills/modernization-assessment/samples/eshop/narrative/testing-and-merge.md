**QA.** There are no automated tests in the repository (section 10.1), so:
1. Before any porting, add API-level characterisation tests for the catalog CRUD operations, the brands download, picture upload and `GetDiscount` (date boundaries).
2. Add Playwright smoke tests for the Blazor and MVC pages.
3. Each wave is tested on AWS (ECS on Fargate with RDS) by client QA with domain knowledge, using production-like catalog data.
4. Before cut-over, run a short load test against the ALB.

**Merge strategy.** The repository has no commits in the last 180 days (shallow clone, last commit 2023-10-25), so parallel-development risk is low. Port on short-lived branches per wave and merge to `main` after each wave's QA sign-off. If the client restarts feature work, rebase weekly and freeze the files being ported during each wave.
