| Risk | Likelihood / impact | Mitigation |
| --- | --- | --- |
| The wrong lineage is retired (a "Modernized" variant is the live system) | Medium / High | Confirm against the production hosting inventory before wave 1; the plan works with either lineage, but the ported code base changes |
| Consumers of the binary brands download break (F-006) | High / Medium | Identify callers from web-server logs; ship a JSON endpoint alongside, then remove the binary one |
| Desktop clients cannot be updated quickly | Medium / Medium | Keep a stable DNS name for the service so clients need no reconfiguration |
| No automated regression suite (F-034) | High / Medium | Characterisation tests for catalog CRUD and discounts before porting; client QA per wave |
