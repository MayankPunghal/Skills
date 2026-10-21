# 22 – Cryptography Migration (.NET 8 / .NET 10)

## Overview
The `System.Security.Cryptography` surface in modern .NET is largely backward-compatible with .NET Framework. Two specific changes matter for upgrades: the legacy `Portable.BouncyCastle` package is renamed to `BouncyCastle.Cryptography`, and several cryptographic providers (`RNGCryptoServiceProvider`, `RijndaelManaged`, `MD5CryptoServiceProvider`, `SHA1CryptoServiceProvider`) are deprecated in favour of factory-method-based static APIs.

---

## Step 1: Rename `Portable.BouncyCastle` → `BouncyCastle.Cryptography`

The `Portable.BouncyCastle` package was a community port that has now been deprecated in favour of the official `BouncyCastle.Cryptography` package. The namespace is unchanged (`Org.BouncyCastle.*`), so the only diff is in the project file.

### Before
```xml
<PackageReference Include="Portable.BouncyCastle" Version="1.9.0" />
```

### After
```xml
<PackageReference Include="BouncyCastle.Cryptography" Version="2.5.0" />
```

Source code referencing `Org.BouncyCastle.Crypto.*` does not change.

---

## Step 2: Replace deprecated `*CryptoServiceProvider` and `*Managed` types with factory methods

The provider-suffixed and managed-suffixed types still compile but emit `SYSLIB0021` / `SYSLIB0023` warnings. Modern code uses the static `Create()` factory methods on the abstract algorithm classes.

### Before
```csharp
using System.Security.Cryptography;

byte[] Hash(byte[] input)
{
    using var sha = new SHA256Managed();
    return sha.ComputeHash(input);
}

byte[] Random(int length)
{
    using var rng = new RNGCryptoServiceProvider();
    var buf = new byte[length];
    rng.GetBytes(buf);
    return buf;
}

byte[] Encrypt(byte[] key, byte[] iv, byte[] data)
{
    using var aes = new RijndaelManaged
    {
        Key = key,
        IV = iv,
        Mode = CipherMode.CBC,
        Padding = PaddingMode.PKCS7
    };
    using var enc = aes.CreateEncryptor();
    return enc.TransformFinalBlock(data, 0, data.Length);
}
```

### After
```csharp
using System.Security.Cryptography;

byte[] Hash(byte[] input)
{
    return SHA256.HashData(input);          // .NET 5+ static helper
}

byte[] Random(int length)
{
    return RandomNumberGenerator.GetBytes(length);    // .NET 6+ static helper
}

byte[] Encrypt(byte[] key, byte[] iv, byte[] data)
{
    using var aes = Aes.Create();
    aes.Key = key;
    aes.IV = iv;
    aes.Mode = CipherMode.CBC;
    aes.Padding = PaddingMode.PKCS7;
    using var enc = aes.CreateEncryptor();
    return enc.TransformFinalBlock(data, 0, data.Length);
}
```

`Rijndael` is the algorithm; `Aes` is the standardized 128-bit-block subset. They are interchangeable when block size is 128 bits (the default), which is true for almost all real-world usage.

---

## Step 3: Replace MD5 / SHA-1 where they are used for security

The factory pattern works for `MD5` and `SHA-1` too, but those algorithms are cryptographically broken and should not be used for new password hashing, signature, or content-integrity work. The .NET 8+ analyser `CA5350` / `CA5351` flags them. If they are used purely for non-security purposes (e.g., a content-addressable cache key for a non-adversarial input), suppress the warning at the call site with a comment explaining why.

### Before
```csharp
using var md5 = new MD5CryptoServiceProvider();
var hash = md5.ComputeHash(Encoding.UTF8.GetBytes(password));
```

### After (security: use a real password hash)
```csharp
// password hashing — use ASP.NET Core Identity's PasswordHasher<T>, or BCrypt.Net.BCrypt, or Argon2
var hasher = new PasswordHasher<string>();
var hash = hasher.HashPassword(null, password);
```

### After (non-security: cache key)
```csharp
#pragma warning disable CA5350    // SHA1 used as a non-cryptographic content-addressable key for cache correlation only
var key = SHA1.HashData(Encoding.UTF8.GetBytes(input));
#pragma warning restore CA5350
```

---

## Step 4: Cross-platform certificate handling

`X509Certificate2.PrivateKey` returning an `RSACryptoServiceProvider` is .NET-Framework-specific. On modern .NET, use `cert.GetRSAPrivateKey()` / `cert.GetECDsaPrivateKey()` and dispose the returned key.

### Before
```csharp
var rsa = (RSACryptoServiceProvider)cert.PrivateKey;
var sig = rsa.SignData(data, CryptoConfig.MapNameToOID("SHA256"));
```

### After
```csharp
using var rsa = cert.GetRSAPrivateKey();
var sig = rsa!.SignData(data, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
```

---

## Step 5: Validation Checklist

✅ `Portable.BouncyCastle` is replaced with `BouncyCastle.Cryptography` 2.x where present  
✅ Build emits no `SYSLIB0021` / `SYSLIB0023` warnings (deprecated CryptoServiceProvider / Managed types)  
✅ Round-trip a representative encryption / signing workload through the rewritten code and confirm byte-for-byte equality with the legacy code path  
✅ MD5 / SHA-1 use sites are reviewed: security-critical sites are migrated to a modern algorithm; non-security sites carry an inline comment explaining the choice  
✅ X509 certificate code paths use `GetRSAPrivateKey()` / `GetECDsaPrivateKey()` and dispose the returned key

---

## See Also
- [00-prebuild-cleanup-and-bulk-fixes.md](./00-prebuild-cleanup-and-bulk-fixes.md) – Prebuild cleanup and bulk fixes
- [08-auth-security-migration.md](./08-auth-security-migration.md) – Authentication, Identity, and password hashing
