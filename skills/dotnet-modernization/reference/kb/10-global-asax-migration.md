# 10 – Global.asax and Application Lifecycle Migration

## Overview

Covers the migration of global application startup logic from Global.asax to Program.cs.

## Replacing GlobalFilterCollection

- Comment out all usages of `GlobalFilterCollection`.
- Replace global filters with attribute-based filters or `IStartupFilter` registration in `Program.cs`.

## Additional Guidance

- Centralize middleware and request pipeline configuration in `Program.cs`.
- Move `Application_Start` logic into `builder.Services` or `app.Use*` calls.
