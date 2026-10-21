**Sequencing.**
1. **Shared library first.** `eShopLegacy.Utilities` moves to `netstandard2.0` while .NET Framework consumers still exist (section 7.1). Its BinaryFormatter code is replaced by System.Text.Json in the same step (F-006).
2. **The go-forward web app next.** Retarget `eShopPorted` from net461 to .NET 10. Upgrade ASP.NET Core 2.2 and EF Core 2.2, which are deprecated on nuget.org, and replace System.Drawing with SkiaSharp or ImageSharp for picture handling.
3. **The WCF service.** Port it with CoreWCF (`basicHttpBinding` is supported) so the desktop clients keep the same contract.
4. **The Web Forms catalog.** Rebuild as Blazor, using AWS Transform for .NET's Web Forms-to-Blazor porting as the starting point and the EF6 data access ported alongside. **Hybrid fallback:** if the rewrite is not funded, retain this app on .NET Framework 4.8.1 on EC2 Windows. `eShopLegacy.Utilities` then stays on netstandard2.0 permanently. The trade-off is a retained Windows licence and two runtimes.

**Tooling.**
- **AWS Transform for .NET** for the mechanical port: SDK-style project conversion, package upgrades, EF and Web Forms UI porting.
- **Manual work** concentrates on the BinaryFormatter API contract, System.Drawing, the OWIN/Azure AD sign-in (only if the Modernized lineage is the live one) and container hosting: health checks, logging to CloudWatch, configuration from Parameter Store and Secrets Manager.

**Retired applications.** These are archived after the client confirms that the go-forward lineage covers all functions:
- `eShopLegacyMVC`;
- `eShopModernizedMVC`;
- `eShopModernizedWebForms`;
- the Modernized `eShopWCFService`;
- `eShopWinForms.fx`.
