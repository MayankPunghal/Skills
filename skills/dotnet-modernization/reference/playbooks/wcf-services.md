# Playbook: WCF services and clients

**Rules:** WCF-SERVICE, WCF-CLIENT (assessment); `.svc` files and `System.ServiceModel` configuration (residue, Linux readiness).
**Engines:** DevTx KB 20 (WCF → CoreWCF) and AWS Transform (WCF is a supported project type; its UI porting does not handle `.svc`) do the bulk. Claude checks wire compatibility and finishes the clients. ASMX is a different playbook: [asmx-and-soap-clients.md](asmx-and-soap-clients.md).

## Services

1. **Callers first.** List who calls each service (logs, the assessment's endpoint map). Callers that cannot change set the bar: same path, SOAP version, WSDL, namespaces, action names, faults, message size and time-outs.
2. **Snapshot the contract** on the original: the WSDL (`?wsdl`, `?singleWsdl`) and golden request/response pairs for every operation in use (`parity.py record`).
3. **Choose:**
   - callers can change and the service is internal → a Web API or gRPC service, callers changed in the same wave;
   - callers cannot change → **CoreWCF** on ASP.NET Core: `builder.Services.AddServiceModelServices()`, `app.UseServiceModel(b => b.AddService<Svc>().AddServiceEndpoint<Svc, ISvc>(new BasicHttpBinding(), "/Service.svc"))`, metadata with `AddServiceModelMetadata()`.
4. **Bindings on Linux:** BasicHttp, WSHttp (without WS-* features that need Windows), NetTcp and WebHttp work; **NetNamedPipe is Windows-only**; MSMQ binding → SQS ([aws-managed-services.md](aws-managed-services.md)); WS-AtomicTransaction and WIF are not supported: redesign. Transport security terminates at the ALB, so the service often moves from HTTPS to HTTP behind it: keep the published WSDL addresses `https` (`UseRequestHeadersForMetadataAddress`).
5. **Configuration** moves from `<system.serviceModel>` in web.config to code (and `appsettings.json` for addresses); behaviours (throttling, `includeExceptionDetailInFaults`) are set explicitly.
6. **Diff the new WSDL against the snapshot** and replay the goldens. Element order, namespaces, `nil` elements and date formats are where differences show.

## Clients

- Regenerate with `dotnet-svcutil <wsdl> -n "*,<Namespace>"` (System.ServiceModel.Http / NetTcp packages). Methods become async (`FooAsync`): make the call chain async rather than blocking with `.Result`.
- Endpoint addresses, time-outs and credentials from configuration and Secrets Manager, not from the generated defaults.
- One `ChannelFactory` per endpoint, reused; close or abort channels on failure.
- A service that also has a REST path: call that with `HttpClient` and drop the proxy.

## Gotchas

- `XmlSerializer` and `DataContractSerializer` give different element order and null handling; keep the one the original used (`[XmlSerializerFormat]`).
- Large messages: set `MaxReceivedMessageSize` and reader quotas to the old values, or big responses fail only in production.
- Duplex contracts and callbacks: supported over NetTcp only; plan a test.

## Done when

Each service builds on `net10.0`, its WSDL diff is empty or signed off, every called operation replays, and every client has been regenerated or replaced.
