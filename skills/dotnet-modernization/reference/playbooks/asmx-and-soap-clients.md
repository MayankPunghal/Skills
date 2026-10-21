# Playbook: ASMX services and SOAP clients

**Rules:** WEB-ASMX, WCF-CLIENT (assessment); WEB-SOAP-PROXY, WEB-FORMS-FILE for `.asmx` (residue).
**Engines:** DevTx KB 20 covers WCF services (CoreWCF), not ASMX "Web References". AWS Transform regenerates some
clients. Claude does the rest.

## SOAP clients ("Web References", `SoapHttpClientProtocol`)

1. Find each `Web References/<Name>/Reference.cs` (or `.map` / `.wsdl`) and the `App_WebReferences` folder; list the
   operations actually called (grep the proxy class name) — often a fraction of the WSDL.
2. Choose per reference:
   - **the service already has a REST / Web API path** → call that with `HttpClient` and drop the proxy (fewest moving parts);
   - **SOAP must stay** → regenerate with `dotnet-svcutil <wsdl> -n "*,<Namespace>"` (System.ServiceModel.Http package),
     which produces async `Task` methods (`FooAsync`); adapt the callers (there is no synchronous method);
   - **only a few operations, simple payloads** → a typed `HttpClient` posting the SOAP envelope is acceptable when
     svcutil output is heavy; record the decision.
3. URLs and timeouts come from configuration (`IOptions`), not from the proxy's `Url` default; credentials from
   Secrets Manager.
4. A client-side load balancer or failover list around the proxy: replace with the AWS load balancer in front of the
   service, or keep it as a small `DelegatingHandler`; decide with DevOps.

## ASMX services (`.asmx`, `[WebMethod]`)

- **External callers that cannot change** → SoapCore (`app.UseSoapEndpoint<T>("/Service.asmx", new SoapEncoderOptions())`)
  keeps the WSDL and the path; check the WSDL diff and replay the goldens: namespaces, `xsi:type`, nullable elements
  and date formats are where SoapCore differs.
- **Internal callers only** → move to a Web API controller or minimal API and change the callers in the same wave.
- CoreWCF is for WCF services (`.svc`), not ASMX (see [wcf-services.md](wcf-services.md)).

## Gotchas

- Old proxies set `Expect: 100-continue`, `KeepAlive` and SOAP 1.1 headers; some servers depend on them.
- `XmlSerializer` output differs when a property type changes (`DateTime` kind, `decimal` precision). Parity catches it.

## Done when

No WEB-SOAP-PROXY or `.asmx` residue (or a waiver for SoapCore-kept files); each called operation replays.
