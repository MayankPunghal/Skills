# Playbook: ASP.NET Web API 2 to ASP.NET Core

**Rules:** WEB-WEBAPI2, WEB-OWIN (assessment); `System.Web.Http` usings (residue, the System.Web family).
**Engines:** DevTx KB 04 (Web API 2) and 23 (Swagger), and AWS Transform (Web API is a supported project type), convert most controllers. Claude checks what they leave behind: return types, message handlers, formatters, the error shape and the wire contract. MVC controllers with views are [mvc.md](mvc.md).

## Contents
- Steps
- Swagger and OpenAPI
- Gotchas
- Done when

## Steps

1. **Snapshot the contract on the original.** Record every route, verb, status code and body in use (`parity.py record`). Save the Swagger document too if there is one. Callers that cannot change set the bar.
2. **Controllers.**
   - Change the base class from `ApiController` to `ControllerBase`, add `[ApiController]`, and change the namespace from `System.Web.Http` to `Microsoft.AspNetCore.Mvc`.
   - `[ApiController]` makes attribute routing required. Convention routes from `config.Routes.MapHttpRoute("api/{controller}/{id}")` become `[Route("api/[controller]")]` on the class plus `[HttpGet("{id}")]` on the action.
   - `[RoutePrefix("x")]` becomes `[Route("x")]` on the class.
   - Register the controllers with `app.MapControllers()`.
3. **Verb selection.** Web API 2 picked the verb from the method-name prefix (`GetProducts`, `PostOrder`). ASP.NET Core does not, so every action gets an explicit `[HttpGet]`, `[HttpPost]` or other verb attribute.
4. **Return types.**
   - `IHttpActionResult` becomes `IActionResult` or `ActionResult<T>`. `Ok(x)`, `NotFound()` and `BadRequest()` keep their names.
   - `HttpResponseMessage` and `Request.CreateResponse(...)` are rewritten to `ObjectResult`, `StatusCode(...)`, `File(...)` or `Content(...)`, with headers set on `Response.Headers`.
   - The compatibility shim (`Microsoft.AspNetCore.Mvc.WebApiCompatShim`) is deprecated and was dropped in ASP.NET Core 3.0, so it is not an option.
5. **Binding and validation.**
   - `[ApiController]` infers `[FromBody]` for complex parameters.
   - It answers an invalid model with an automatic 400 and a ProblemDetails body. Web API 2 ran the action and returned whatever it built. If callers parse the old error body, either shape a matching response or turn the automatic response off with `ConfigureApiBehaviorOptions(o => o.SuppressModelStateInvalidFilter = true)`.
   - `[FromUri]` becomes `[FromQuery]` or `[FromRoute]`.
6. **Message handlers.**
   - A server-side `DelegatingHandler` in `config.MessageHandlers` becomes middleware if it runs on every request, or an action or endpoint filter if it covers some controllers.
   - A `DelegatingHandler` on an outgoing `HttpClient` stays. Register it through `IHttpClientFactory` with `AddHttpMessageHandler<T>()`.
7. **Filters and errors.**
   - Web API exception handling moves to ASP.NET Core: `IExceptionHandler`, `IExceptionLogger` and `ExceptionFilterAttribute` become an `IExceptionHandler` (.NET 8+) with `app.UseExceptionHandler()`, or an `IExceptionFilter`.
   - `ActionFilterAttribute` moves to `Microsoft.AspNetCore.Mvc.Filters`, and async filters implement `IAsyncActionFilter`.
   - Global filters registered with `config.Filters.Add(...)` move to `AddControllers(o => o.Filters.Add<T>())`.
8. **Formatters.**
   - Web API 2 serialized with Newtonsoft.Json and kept property names as declared. ASP.NET Core uses System.Text.Json with camelCase names.
   - To keep the wire output, either call `AddNewtonsoftJson()` with the settings copied from `config.Formatters.JsonFormatter.SerializerSettings` (including ReferenceLoopHandling), or configure System.Text.Json to match and replay the goldens.
   - XML: Web API 2's default XML formatter used `DataContractSerializer`. Use `AddXmlDataContractSerializerFormatters()` to keep it, or `AddXmlSerializerFormatters()` where the original used `XmlSerializer`.
   - A custom `MediaTypeFormatter` becomes an `InputFormatter` or `OutputFormatter`.
9. **CORS.** `EnableCors()` and `[EnableCors]` (Microsoft.AspNet.WebApi.Cors) become named policies with `AddCors(...)` and `app.UseCors()`, called after routing and before authentication. Controllers use `[EnableCors("policy")]`.
10. **OData.** `Microsoft.AspNet.OData` becomes `Microsoft.AspNetCore.OData` (8 or later). Its routing and query-option set-up changed, so replay every query the callers send.
11. **OWIN self-host.** `WebApp.Start` and `IAppBuilder.UseWebApi` become a `WebApplication`. OWIN middleware becomes ASP.NET Core middleware ([http-handlers-and-modules.md](http-handlers-and-modules.md)).
12. **Replay the goldens.** Diff status codes, headers and bodies.

## Swagger and OpenAPI

- **Swashbuckle for Web API 2** (Swashbuckle.Core with `SwaggerConfig`, `EnableSwagger` and `EnableSwaggerUi`) has two replacements:
  - Swashbuckle.AspNetCore (`AddSwaggerGen`, `UseSwagger`, `UseSwaggerUI`);
  - the built-in `Microsoft.AspNetCore.OpenApi` (`AddOpenApi`, `MapOpenApi`).

  The .NET 9 and later templates use the built-in package and ship no UI. Add Swagger UI or Scalar if people use the UI.
- **Swashbuckle.Examples** (`IExamplesProvider`) becomes Swashbuckle.AspNetCore.Filters (`IExamplesProvider<T>`).
- **Document version.** Web API 2 produced a Swagger 2.0 document. The .NET 10 generator writes OpenAPI 3.1 by default, and `WithOpenApi` is deprecated ([breaking-changes.md](../breaking-changes.md)). Generated clients (NSwag, AutoRest, openapi-generator) and API gateways that import the document may need regenerating. If an importer accepts only an older version, set the document version in the OpenAPI options.
- **Diff the documents.** Compare the old and new documents (paths, operation IDs, schemas, required fields) and get the differences signed off.

## Gotchas

- **Content negotiation.** ASP.NET Core ignores a browser's Accept header by default (`RespectBrowserAcceptHeader = false`). When no formatter matches, it falls back to JSON unless `ReturnHttpNotAcceptable = true`.
- **Dates.** Newtonsoft and System.Text.Json write `DateTime` kinds and offsets differently, so compare date fields in the goldens.
- **Cookie auth on API endpoints.** On .NET 10, cookie authentication answers 401 or 403 on known API endpoints instead of redirecting to the login page. A client that followed the redirect changes ([breaking-changes.md](../breaking-changes.md), [auth.md](auth.md)).
- **Routing.** Route templates are matched without regard to case or a trailing slash, but token replacement (`[controller]`) uses the class name without the `Controller` suffix. Check every path a caller uses.

## Done when

- No `System.Web.Http` reference is left.
- Every action has an explicit verb.
- The goldens replay with the same status codes and bodies, or each difference is signed off.
- The OpenAPI document diff is signed off.
- No server-side `DelegatingHandler` remains.

Sources: [Web API to ASP.NET Core](https://learn.microsoft.com/en-us/aspnet/core/migration/fx-to-core/areas/webapi), [WebApiCompatShim removal](https://github.com/dotnet/docs/issues/14963), [ASP.NET Core 10 breaking changes](https://learn.microsoft.com/en-us/aspnet/core/breaking-changes/10/overview).
