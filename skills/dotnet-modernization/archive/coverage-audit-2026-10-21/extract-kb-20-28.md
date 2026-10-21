> Archived raw report from the coverage audit of 2026-10-21. It is not loaded at run time and may be out of date.
> Local paths, client names and internal tool names were replaced with placeholders; nothing else was changed.

# Extract KB detectable items 20-28

agent a8a28cbbc63c64e78

KB detectable-items extraction (read-only; all 9 files read in full; no credentials present in these files)

20-wcf-to-corewcf-migration.md
- [ns] System.ServiceModel | server contracts move to CoreWCF; client keeps it | blocks-linux-or-build: Y
- [proj-marker] Reference Include="System.ServiceModel" | framework ref on server; replace with CoreWCF.Primitives | blocks-linux-or-build: Y
- [proj-marker] Reference Include="System.ServiceModel.Web" | framework ref on server; replace with CoreWCF | blocks-linux-or-build: Y
- [pkg] CoreWCF.Primitives | server contract package, 1.x | blocks-linux-or-build: N
- [pkg] CoreWCF.Http | server HTTP transport package | blocks-linux-or-build: N
- [pkg] CoreWCF.NetTcp | server NetTcp package, only if used | blocks-linux-or-build: N
- [attr] [ServiceContract] | server: use CoreWCF namespace, else CS0246 | blocks-linux-or-build: Y
- [attr] [OperationContract] | server: use CoreWCF namespace | blocks-linux-or-build: Y
- [attr] [ServiceBehavior] | server: use CoreWCF namespace | blocks-linux-or-build: Y
- [attr] [DataContract] | stays in System.Runtime.Serialization; no change | blocks-linux-or-build: N
- [config-key] system.serviceModel | config block has no equivalent; move to Program.cs | blocks-linux-or-build: Y
- [config-key] service / endpoint (binding, contract) | replace with serviceBuilder.AddServiceEndpoint | blocks-linux-or-build: Y
- [config-key] basicHttpBinding | replace with new BasicHttpBinding() in code | blocks-linux-or-build: Y
- [config-key] client endpoint | unsupported; use explicit Binding plus EndpointAddress | blocks-linux-or-build: Y
- [wcf-asmx-remoting] .svc | delete; register endpoint in Program.cs | blocks-linux-or-build: Y
- [wcf-asmx-remoting] ServiceHost directive | .svc directive; delete with the file | blocks-linux-or-build: Y
- [wcf-asmx-remoting] WebServiceHostFactory | .svc host factory reference; remove | blocks-linux-or-build: Y
- [api] ClientBase<T> | string-name ctor missing on Primitives; CS1503 | blocks-linux-or-build: Y
- [pkg] CoreWCF.* on client project | remove; clients use System.ServiceModel.* | blocks-linux-or-build: Y
- [pkg] System.ServiceModel.Primitives | client-side NuGet package, 8.x | blocks-linux-or-build: N
- [pkg] System.ServiceModel.Http | client-side NuGet package, 8.x | blocks-linux-or-build: N

21-system-drawing-migration.md
- [ns] System.Drawing | Windows-only; PlatformNotSupportedException on Linux/macOS | blocks-linux-or-build: Y
- [ns] System.Drawing.Imaging | Windows-only; move to SkiaSharp or ImageSharp | blocks-linux-or-build: Y
- [pkg] System.Drawing.Common | Windows-only on Linux; keep only for Windows-only apps | blocks-linux-or-build: Y
- [api] Image.FromFile | replace with SKBitmap.Decode or ImageSharp load | blocks-linux-or-build: Y
- [api] Bitmap | replace with SKBitmap or ImageSharp image | blocks-linux-or-build: Y
- [api] ImageFormat.Jpeg | replace with SKEncodedImageFormat.Jpeg | blocks-linux-or-build: Y
- [api] Size | System.Drawing type; use SKImageInfo dimensions | blocks-linux-or-build: Y
- [api] SKFilterQuality | removed in SkiaSharp v4; use SKSamplingOptions | blocks-linux-or-build: Y
- [api] SKCubicResampler.Mitchell | high-quality resampler; SKFilterQuality.High equivalent | blocks-linux-or-build: N
- [api] SKSamplingOptions | SkiaSharp resize options replacement | blocks-linux-or-build: N
- [pkg] SkiaSharp | default replacement, MIT, no build-time gating | blocks-linux-or-build: N
- [pkg] SkiaSharp.NativeAssets.Linux | native assets needed when Linux is target | blocks-linux-or-build: N
- [pkg] SixLabors.ImageSharp 3.1.x | pinned line with no build-time key | blocks-linux-or-build: N
- [blocked-pkg] SixLabors.ImageSharp 4.x | build-time license key; build fails without key | blocks-linux-or-build: Y
- [api] Image.Mutate / Resize | ImageSharp processing target API | blocks-linux-or-build: N
- [api] Image.LoadAsync / SaveAsJpegAsync | ImageSharp load/save target API | blocks-linux-or-build: N
- [other] Windows-only deployment (WinForms, WPF, IIS, service) | keep System.Drawing.Common; no change | blocks-linux-or-build: N

22-crypto-migration.md
- [pkg] Portable.BouncyCastle | deprecated; rename to BouncyCastle.Cryptography 2.x | blocks-linux-or-build: N
- [pkg] BouncyCastle.Cryptography | official replacement package, 2.5.0 | blocks-linux-or-build: N
- [ns] Org.BouncyCastle | namespace unchanged on package rename | blocks-linux-or-build: N
- [api] SHA256Managed | use SHA256.HashData; SYSLIB0021/0023 warnings | blocks-linux-or-build: N
- [api] RNGCryptoServiceProvider | use RandomNumberGenerator.GetBytes | blocks-linux-or-build: N
- [api] RijndaelManaged | use Aes.Create(); deprecated | blocks-linux-or-build: N
- [api] MD5CryptoServiceProvider | deprecated; security use needs password hasher | blocks-linux-or-build: N
- [api] SHA1CryptoServiceProvider | deprecated; flagged by CA5351 | blocks-linux-or-build: N
- [api] MD5 | CA5350 flagged; not for security use | blocks-linux-or-build: N
- [api] SHA1 | CA5350/CA5351 flagged; suppress only with comment | blocks-linux-or-build: N
- [api] RSACryptoServiceProvider | cast of cert.PrivateKey; use GetRSAPrivateKey | blocks-linux-or-build: Y
- [api] X509Certificate2.PrivateKey | use GetRSAPrivateKey / GetECDsaPrivateKey | blocks-linux-or-build: Y
- [build] SYSLIB0021 | deprecated CryptoServiceProvider warning | blocks-linux-or-build: N
- [build] SYSLIB0023 | deprecated Managed type warning | blocks-linux-or-build: N
- [build] CA5350 | analyzer: weak MD5/SHA-1 use | blocks-linux-or-build: N
- [build] CA5351 | analyzer: broken hash algorithm use | blocks-linux-or-build: N

23-swagger-swashbuckle-migration.md
- [pkg] Swashbuckle.Core 5.6.0 | Web API 2 generator; remove | blocks-linux-or-build: Y
- [pkg] Swashbuckle.Examples 4.1.0 | old examples package; remove | blocks-linux-or-build: Y
- [pkg] Swashbuckle.AspNetCore | ASP.NET Core generator; use TFM-compatible version | blocks-linux-or-build: N
- [pkg] Swashbuckle.AspNetCore.Annotations | annotations replacement package | blocks-linux-or-build: N
- [blocked-pkg] Swashbuckle.AspNetCore.Filters | third-party; blocked if no net10.0 release | blocks-linux-or-build: Y
- [ns] System.Web.Http | Web API 2 namespace used by SwaggerConfig | blocks-linux-or-build: Y
- [other] App_Start/SwaggerConfig.cs | delete; configure AddSwaggerGen in Program.cs | blocks-linux-or-build: Y
- [api] GlobalConfiguration.Configuration | Web API 2 config; absent in ASP.NET Core | blocks-linux-or-build: Y
- [api] EnableSwagger | replace with AddSwaggerGen | blocks-linux-or-build: Y
- [api] EnableSwaggerUi | replace with UseSwaggerUI | blocks-linux-or-build: Y
- [api] SingleApiVersion | replace with c.SwaggerDoc("v1", ...) | blocks-linux-or-build: Y
- [attr] [SwaggerResponse] (HttpStatusCode arg) | status must be int or use ProducesResponseType | blocks-linux-or-build: Y
- [attr] [SwaggerResponseExample] | int status; jsonConverter argument removed | blocks-linux-or-build: Y
- [attr] [SwaggerRequestExample] | Filters attribute; provider is IExamplesProvider<T> | blocks-linux-or-build: N
- [api] IExamplesProvider | non-generic; change to IExamplesProvider<T>; CS0305 | blocks-linux-or-build: Y
- [api] jsonConverter: | CS1739 if kept; set enum-as-string globally | blocks-linux-or-build: Y
- [attr] [SwaggerOperation] (positional id) | positional id renamed to OperationId | blocks-linux-or-build: Y
- [attr] [ResponseType] | Web API 2 attribute; use ProducesResponseType | blocks-linux-or-build: Y
- [attr] [SwaggerResponseRemoveDefaults] | no equivalent; remove | blocks-linux-or-build: Y
- [api] AddSwaggerGen | Program.cs target configuration (EnableAnnotations, ExampleFilters) | blocks-linux-or-build: N

24-test-stack-migration.md
- [pkg] Microsoft.VisualStudio.QualityTools.UnitTestFramework | legacy MSTest assembly; remove | blocks-linux-or-build: Y
- [pkg] MSTest.TestAdapter 1.4.0 | MSTest v1 adapter; move to 3.x | blocks-linux-or-build: Y
- [pkg] MSTest.TestFramework 3.6.0 | MSTest v3 target package | blocks-linux-or-build: N
- [pkg] NUnit 2.6.4 | NUnit 2 framework; move to 3.x or 4.5 | blocks-linux-or-build: Y
- [pkg] NUnit.Runners | NUnit 2 runner; remove | blocks-linux-or-build: Y
- [pkg] NUnit2TestAdapter | out of support; use NUnit3TestAdapter | blocks-linux-or-build: Y
- [pkg] NUnit 4.0-4.4 | classic asserts moved; do not pin | blocks-linux-or-build: Y
- [pkg] NUnit 4.5.0 | target version restoring classic asserts | blocks-linux-or-build: N
- [api] Assert.AreEqual | CS0117 on NUnit 4.0-4.4; rewrite to Assert.That | blocks-linux-or-build: Y
- [api] Assert.IsTrue | classic assert; CS0117 on NUnit 4.0-4.4 | blocks-linux-or-build: Y
- [attr] [ExpectedException] | removed in NUnit 3; use Assert.Throws<T> | blocks-linux-or-build: Y
- [pkg] Microsoft.NET.Test.Sdk 17.10+ | required test SDK version | blocks-linux-or-build: N
- [pkg] xunit 2.9.2 | xUnit target version | blocks-linux-or-build: N
- [pkg] Moq 4.18.4 | old; bump to 4.20.70+ (SponsorLink reverted) | blocks-linux-or-build: N
- [pkg] Moq 4.20.72 | target Moq version | blocks-linux-or-build: N
- [api] MockRepository.GenerateMock<T> | RhinoMocks API; rewrite to Mock<T> | blocks-linux-or-build: Y
- [api] MockRepository.GenerateStub<T> | RhinoMocks API; rewrite to Mock<T> | blocks-linux-or-build: Y
- [api] .Stub(...).Return(...) | RhinoMocks stub; rewrite to Setup/Returns | blocks-linux-or-build: Y
- [api] AssertWasCalled | RhinoMocks verify; rewrite to Verify | blocks-linux-or-build: Y
- [ns] Rhino.Mocks | RhinoMocks namespace; remove all uses | blocks-linux-or-build: Y
- [pkg] RhinoMocks | unmaintained; replace with Moq, NSubstitute or FakeItEasy | blocks-linux-or-build: Y

25-webforms-to-razor-migration.md
- [ns] System.Web.UI | Web Forms namespace; no code may inherit from it | blocks-linux-or-build: Y
- [api] System.Web.UI.Page | page base class; re-author as PageModel | blocks-linux-or-build: Y
- [api] UserControl | .ascx base class; replace with partial or view component | blocks-linux-or-build: Y
- [api] MasterPage | .master base class; replace with _Layout.cshtml | blocks-linux-or-build: Y
- [pkg] Microsoft.AspNet.WebForms | never ported; remove | blocks-linux-or-build: Y
- [webforms] .aspx | page file; re-author as Razor Page | blocks-linux-or-build: Y
- [webforms] .ascx | user control file; re-author as partial | blocks-linux-or-build: Y
- [webforms] .master | master page file; replace with _Layout.cshtml | blocks-linux-or-build: Y
- [webforms] .aspx.cs | code-behind; move handlers to PageModel | blocks-linux-or-build: Y
- [webforms] <%@ Page %> | directive; remove | blocks-linux-or-build: Y
- [webforms] <%# %> | data-binding syntax; replace with Razor | blocks-linux-or-build: Y
- [webforms] <%= %> | inline expression; replace with Razor @ syntax | blocks-linux-or-build: Y
- [webforms] <asp:GridView> | replace with table markup or QuickGrid | blocks-linux-or-build: Y
- [webforms] <asp:Button OnClick> | replace with asp-page-handler form posts | blocks-linux-or-build: Y
- [webforms] <asp:DropDownList> | replace with select asp-items | blocks-linux-or-build: Y
- [webforms] <asp:TextBox> | replace with input asp-for | blocks-linux-or-build: Y
- [webforms] <asp:Validator> | replace with DataAnnotations and asp-validation-for | blocks-linux-or-build: Y
- [webforms] <asp:ContentPlaceHolder> | replace with RenderBody / RenderSection | blocks-linux-or-build: Y
- [webforms] ViewState | removed; re-model via binding, TempData or session | blocks-linux-or-build: Y
- [api] IsPostBack | removed; split into OnGet and OnPost handlers | blocks-linux-or-build: Y
- [api] Page_Load | lifecycle handler; becomes OnGet | blocks-linux-or-build: Y
- [api] _Click handler (e.g. SaveButton_Click) | becomes OnPost<Handler> method | blocks-linux-or-build: Y
- [webforms] runat="server" | server-control marker; replace with tag helpers | blocks-linux-or-build: Y

26-webforms-to-blazor-migration.md
- [ns] System.Web.UI.* | no System.Web.UI types may remain | blocks-linux-or-build: Y
- [webforms] .aspx / .ascx / .master | re-author as .razor components and layout | blocks-linux-or-build: Y
- [webforms] <%@ Page %> | replace with @page route directive | blocks-linux-or-build: Y
- [webforms] <asp:UpdatePanel> | replaced by native component re-render | blocks-linux-or-build: Y
- [webforms] ViewState | replaced by component fields and state services | blocks-linux-or-build: Y
- [api] IsPostBack | removed; use OnInitialized and OnParametersSet | blocks-linux-or-build: Y
- [api] Page.IsValid | replace with EditForm validation | blocks-linux-or-build: Y
- [api] Page_Load | becomes OnInitializedAsync | blocks-linux-or-build: Y
- [api] Button_Click | becomes @onclick handler | blocks-linux-or-build: Y
- [razor-blazor] @page | Blazor route directive target | blocks-linux-or-build: N
- [razor-blazor] @inject | DI into components; target | blocks-linux-or-build: N
- [razor-blazor] @onclick | component click handler target | blocks-linux-or-build: N
- [razor-blazor] @bind / @bind:event | two-way binding; replaces AutoPostBack | blocks-linux-or-build: N
- [razor-blazor] EditForm | form with validation target | blocks-linux-or-build: N
- [razor-blazor] DataAnnotationsValidator | validation component target | blocks-linux-or-build: N
- [razor-blazor] ValidationMessage | field validation message target | blocks-linux-or-build: N
- [razor-blazor] InputText / InputSelect | Blazor form input components | blocks-linux-or-build: N
- [razor-blazor] @Body / RenderFragment | layout body; replaces ContentPlaceHolder | blocks-linux-or-build: N
- [razor-blazor] QuickGrid | Microsoft.AspNetCore.Components.QuickGrid; replaces GridView | blocks-linux-or-build: N
- [razor-blazor] OnParametersSetAsync | runs on each parameter change | blocks-linux-or-build: N
- [razor-blazor] StateHasChanged | manual re-render outside event flow | blocks-linux-or-build: N

27-blocked-packages-and-build-integrity.md
- [build] NU1701 | package restored via .NET Framework fallback; remove or replace | blocks-linux-or-build: Y
- [build] NU1608 | version outside dependency constraint; remove legacy package | blocks-linux-or-build: Y
- [build] NU1605 | package downgrade; pin direct ref at 8.0.x/10.0.x | blocks-linux-or-build: Y
- [build] NU1902 | known vulnerability advisory (moderate); migrate or bump | blocks-linux-or-build: N
- [build] NU1903 | known vulnerability advisory (high); migrate or bump | blocks-linux-or-build: N
- [blocked-pkg] Microsoft.AspNet.Mvc | MVC5; remove, use Microsoft.AspNetCore.Mvc | blocks-linux-or-build: Y
- [blocked-pkg] Microsoft.AspNet.WebApi | Web API 2 packages; remove, unified into MVC | blocks-linux-or-build: Y
- [blocked-pkg] Microsoft.AspNet.Razor | remove; Razor built into Web SDK | blocks-linux-or-build: Y
- [blocked-pkg] Microsoft.AspNet.WebPages | remove; Razor built into Web SDK | blocks-linux-or-build: Y
- [blocked-pkg] Microsoft.Web.Infrastructure | remove; no longer needed | blocks-linux-or-build: Y
- [blocked-pkg] System.Web.Optimization | remove; use build-time bundler | blocks-linux-or-build: Y
- [blocked-pkg] WebGrease | remove with bundling stack | blocks-linux-or-build: Y
- [blocked-pkg] Autofac.Mvc5 | NU1701 offender; remove or use Autofac.Extensions.DI | blocks-linux-or-build: Y
- [blocked-pkg] Autofac.WebApi2 | remove; use built-in DI | blocks-linux-or-build: Y
- [blocked-pkg] Antlr | MVC5 bundling dependency; use Antlr4 if needed | blocks-linux-or-build: Y
- [blocked-pkg] NuGet.Core | no modern equivalent; remove dependent code | blocks-linux-or-build: Y
- [blocked-pkg] System.Diagnostics.DiagnosticSource | NU1605 downgrade; add direct ref at target major | blocks-linux-or-build: Y
- [blocked-pkg] Autofac | NU1608 conflict with Autofac.Mvc5; resolved by its removal | blocks-linux-or-build: Y
- [blocked-pkg] log4net | vulnerable; migrate to Microsoft.Extensions.Logging | blocks-linux-or-build: N
- [blocked-pkg] NLog | advisories; migrate to Microsoft.Extensions.Logging | blocks-linux-or-build: N
- [blocked-pkg] Newtonsoft.Json | advisory; prefer System.Text.Json, else >= 13.0.1 | blocks-linux-or-build: N

28-dotnet-remoting-migration.md
- [ns] System.Runtime.Remoting | root alone does not error; match sub-namespaces | blocks-linux-or-build: Y
- [ns] System.Runtime.Remoting.Channels.* | Tcp/Http/Ipc channels removed; CS0234 | blocks-linux-or-build: Y
- [ns] System.Runtime.Remoting.Lifetime | removed; ILease, ISponsor gone | blocks-linux-or-build: Y
- [ns] System.Runtime.Remoting.Messaging | removed; IMessage, CallContext, OneWay gone | blocks-linux-or-build: Y
- [ns] System.Runtime.Remoting.Proxies | removed; RealProxy, ProxyAttribute gone | blocks-linux-or-build: Y
- [ns] System.Runtime.Remoting.{Activation,Contexts,Metadata,Services} | removed; CS0234 | blocks-linux-or-build: Y
- [ns] System.Runtime.Serialization.Formatters.Soap | SoapFormatter removed | blocks-linux-or-build: Y
- [api] RemotingConfiguration | removed; configure via DI and appsettings | blocks-linux-or-build: Y
- [api] ChannelServices.RegisterChannel | removed; CS0103; use gRPC or pipes | blocks-linux-or-build: Y
- [api] TcpChannel | removed; CS0246; use gRPC over HTTP/2 | blocks-linux-or-build: Y
- [api] RemotingServices | removed; use typed gRPC or HTTP clients | blocks-linux-or-build: Y
- [api] Activator.GetObject | method removed; CS0117; use typed client | blocks-linux-or-build: Y
- [api] RealProxy | removed; use DispatchProxy for AOP | blocks-linux-or-build: Y
- [api] AppDomain.CreateDomain | throws PlatformNotSupportedException; use AssemblyLoadContext | blocks-linux-or-build: Y
- [api] BinaryFormatter | always throws on .NET 9+; SYSLIB0011 error | blocks-linux-or-build: Y
- [api] SoapFormatter | removed; use JSON or protobuf | blocks-linux-or-build: Y
- [api] Delegate.BeginInvoke | throws PlatformNotSupportedException; use async/await | blocks-linux-or-build: Y
- [api] InitializeLifetimeService | obsolete and throws; delete override (CS0672) | blocks-linux-or-build: Y
- [api] MarshalByRefObject | inert base; remove from service classes only | blocks-linux-or-build: N
- [api] ContextBoundObject | inert; remove, drops [Synchronization] protection | blocks-linux-or-build: N
- [attr] [OneWay] | removed; CS0246; replace with queue publish | blocks-linux-or-build: Y
- [attr] [Synchronization] | removed; CS0246; replace with explicit locking | blocks-linux-or-build: Y
- [api] CallContext | removed; use AsyncLocal or gRPC metadata | blocks-linux-or-build: Y
- [api] ObjRef | removed; CS0234; use DTO or URI-free design | blocks-linux-or-build: Y
- [attr] [OnDeserialized] / [OnSerializing] | compile but never fire under System.Text.Json | blocks-linux-or-build: N
- [api] TransactionScope | compiles but no longer distributed across remoting calls | blocks-linux-or-build: N
- [config-key] system.runtime.remoting | config section; no tool detects it; manual | blocks-linux-or-build: N
- [wcf-asmx-remoting] tcp:// URI | remoting endpoint; internet exposure is a security finding | blocks-linux-or-build: N
- [build] CS0234 | remoting sub-namespace unresolved; most reliable signal | blocks-linux-or-build: Y
- [build] CS0246 | remoting type not found; dedupe OneWay errors | blocks-linux-or-build: Y
- [build] CS0117 | Activator.GetObject member missing | blocks-linux-or-build: Y
- [build] CS0672 | overriding obsolete InitializeLifetimeService | blocks-linux-or-build: Y
- [build] SYSLIB0011 | BinaryFormatter obsolete as error | blocks-linux-or-build: Y
- [build] SYSLIB0010 | obsolete lease APIs; throw at runtime | blocks-linux-or-build: N
- [build] SYSLIB0050 | formatter serialization obsolete warning | blocks-linux-or-build: N
- [build] SYSLIB0051 | legacy serialization APIs obsolete warning | blocks-linux-or-build: N
- [other] TypeLoadException System.Runtime.Remoting.Channels.IChannel | third-party assembly still uses remoting | blocks-linux-or-build: Y
- [other] PlatformNotSupportedException "Remoting is not supported" | runtime failure from remoting code | blocks-linux-or-build: Y
- [blocked-pkg] Grpc.Core | unsupported C-core; treat as unavailable | blocks-linux-or-build: Y
- [pkg] CoreRemoting / GoreRemoting | third-party shims; not drop-in, not Microsoft-supported | blocks-linux-or-build: N
- [pkg] System.Runtime.Serialization.Formatters | unsupported compatibility package; must not be added | blocks-linux-or-build: N

TOTAL ITEMS: 199
