# 24 – Test Stack Migration (.NET 8 / .NET 10)

## Overview
The .NET test stack moves to async-friendly, source-generator-aware versions on modern .NET. MSTest v1 → MSTest v3 is mechanical. NUnit 2 → 3 has API breakage that needs review. xUnit and Moq mostly bump cleanly. `RhinoMocks` is abandoned and has no successor — every `RhinoMocks` site is rewritten as `Moq` or `NSubstitute`.

---

## Step 1: Replace test runner packages

Modern .NET test runners are `Microsoft.NET.Test.Sdk` plus a per-framework adapter. Legacy `MSTest.TestFramework` v1 and `NUnit2TestAdapter` are out.

### Before
```xml
<PackageReference Include="Microsoft.VisualStudio.QualityTools.UnitTestFramework" Version="10.0.0" />
<PackageReference Include="MSTest.TestAdapter" Version="1.4.0" />
<PackageReference Include="NUnit" Version="2.6.4" />
<PackageReference Include="NUnit.Runners" Version="2.6.4" />
```

### After (MSTest v3)
```xml
<ItemGroup>
  <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
  <PackageReference Include="MSTest.TestAdapter" Version="3.6.0" />
  <PackageReference Include="MSTest.TestFramework" Version="3.6.0" />
</ItemGroup>
```

### After (NUnit 3+)
```xml
<ItemGroup>
  <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
  <PackageReference Include="NUnit" Version="4.5.0" />
  <PackageReference Include="NUnit3TestAdapter" Version="4.6.0" />
</ItemGroup>
```

> **Do not pin NUnit 4.0–4.4.** On those versions the classic asserts (`Assert.AreEqual`, `Assert.IsTrue`, …) were moved out of the `Assert` class into `ClassicAssert` in the `NUnit.Framework.Legacy` namespace, so any code still calling `Assert.AreEqual` fails to compile with **CS0117** (`'Assert' does not contain a definition for 'AreEqual'`). They were restored to `Assert` in **4.5**, which is why this guide pins 4.5. If you must stay on the NUnit 3 line instead, pin `NUnit` `3.14.0` (classic asserts are on `Assert` throughout 3.x) with `NUnit3TestAdapter` `4.6.0`.

### After (xUnit)
```xml
<ItemGroup>
  <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
  <PackageReference Include="xunit" Version="2.9.2" />
  <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2" />
</ItemGroup>
```

---

## Step 2: NUnit 2 → 3 attribute changes

NUnit 3 dropped the assertion classes' shorthand API and renamed several attributes. The most common breakage is `[TestCase]` parameter ordering and `Assert.That` syntax.

### Before
```csharp
using NUnit.Framework;

[TestFixture]
public class OrderTests
{
    [Test]
    [ExpectedException(typeof(ArgumentException))]
    public void Constructor_RejectsNegativeAmount()
    {
        new Order(-1);
    }

    [Test]
    public void Total_IsSumOfLines()
    {
        var o = new Order(1);
        Assert.AreEqual(100, o.Total);
    }
}
```

### After
```csharp
using NUnit.Framework;

[TestFixture]
public class OrderTests
{
    [Test]
    public void Constructor_RejectsNegativeAmount()
    {
        Assert.Throws<ArgumentException>(() => new Order(-1));
    }

    [Test]
    public void Total_IsSumOfLines()
    {
        var o = new Order(1);
        Assert.That(o.Total, Is.EqualTo(100));
    }
}
```

`[ExpectedException]` is removed; use `Assert.Throws<T>` instead. Rewrite classic asserts like `Assert.AreEqual(expected, actual)` to the constraint model `Assert.That(actual, Is.EqualTo(expected))` — this is the idiomatic form and, because it never depends on the classic asserts being present on `Assert`, it compiles across NUnit 3.x and every 4.x release regardless of the CS0117 namespace churn described above.

---

## Step 3: Bump `Moq` and review constructor-mock patterns

`Moq` 4.x works on .NET 10. The 4.20.x line briefly shipped a controversial telemetry feature (SponsorLink) that was reverted in 4.20.70+; pin to 4.20.70 or higher.

### Before
```xml
<PackageReference Include="Moq" Version="4.18.4" />
```

### After
```xml
<PackageReference Include="Moq" Version="4.20.72" />
```

If telemetry concerns are an issue, switch to `NSubstitute` 5.x or `FakeItEasy` 8.x. Both have active maintenance and similar mocking APIs.

---

## Step 4: RhinoMocks → Moq or NSubstitute

`RhinoMocks` has been unmaintained since 2010 and does not have a 1:1 successor. Each test using `MockRepository.GenerateMock<T>()` or `MockRepository.GenerateStub<T>()` is rewritten.

### Before (RhinoMocks)
```csharp
using Rhino.Mocks;

[Test]
public void GetOrder_CallsRepository()
{
    var repo = MockRepository.GenerateMock<IOrderRepository>();
    repo.Stub(r => r.FindById(42)).Return(new Order { Id = 42 });

    var svc = new OrderService(repo);
    var result = svc.GetOrder(42);

    Assert.That(result.Id, Is.EqualTo(42));
    repo.AssertWasCalled(r => r.FindById(42));
}
```

### After (Moq)
```csharp
using Moq;

[Test]
public void GetOrder_CallsRepository()
{
    var repo = new Mock<IOrderRepository>();
    repo.Setup(r => r.FindById(42)).Returns(new Order { Id = 42 });

    var svc = new OrderService(repo.Object);
    var result = svc.GetOrder(42);

    Assert.That(result.Id, Is.EqualTo(42));
    repo.Verify(r => r.FindById(42), Times.Once);
}
```

---

## Step 5: Validation Checklist

✅ Every test project's `Microsoft.NET.Test.Sdk` is at 17.10 or higher  
✅ No project references the legacy `Microsoft.VisualStudio.QualityTools.UnitTestFramework` assembly  
✅ `RhinoMocks` is removed; every former call site is rewritten on `Moq`, `NSubstitute`, or `FakeItEasy`  
✅ All tests run via `dotnet test` and produce the same pass/fail counts as before the migration  
✅ NUnit assertion changes (`Assert.That(...)`, `Assert.Throws<T>`) compile and produce equivalent failure messages

---

## See Also
- [00-prebuild-cleanup-and-bulk-fixes.md](./00-prebuild-cleanup-and-bulk-fixes.md) – Prebuild cleanup and bulk fixes
- [06-package-migrations.md](./06-package-migrations.md) – NuGet package replacements
