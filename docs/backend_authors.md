# For backend authors

A backend's job is small: collect the ordered `[[tool.dynamic-metadata]]`
entries, load each entry's `provider`, and call its hooks at the right point in
the [PEP 517][] build. Because the entries are an explicit ordered list, there
is no dependency graph to solve.

The easiest way is a build-time dependency on this package, calling the
reference loader in {mod}`dynamic_metadata.loader` — what this page shows. **You
do not have to depend on us**, though: you can vendor the loader or reimplement
it from a precise description of its behaviour — see
[Reimplementing the loader](backend_authors_reimplement.md).

## Where plugins plug into a build

Plugins touch two PEP 517 responsibilities: declaring extra build requirements,
and producing the final `[project]` metadata. Wire them in like this:

| PEP 517 hook                          | What the backend does                                   | `build_state`         |
| ------------------------------------- | ------------------------------------------------------- | --------------------- |
| `get_requires_for_build_wheel`        | add each provider's `get_requires_for_dynamic_metadata` | —                     |
| `get_requires_for_build_sdist`        | same                                                    | —                     |
| `get_requires_for_build_editable`     | same                                                    | —                     |
| `prepare_metadata_for_build_wheel`    | run `process_dynamic_metadata`, write `METADATA`        | `"metadata_wheel"`    |
| `prepare_metadata_for_build_editable` | run `process_dynamic_metadata`, write `METADATA`        | `"metadata_editable"` |
| `build_wheel`                         | run `process_dynamic_metadata`, write `METADATA`        | `"wheel"`             |
| `build_editable`                      | run `process_dynamic_metadata`, write `METADATA`        | `"editable"`          |
| `build_sdist`                         | run `process_dynamic_metadata`, write `PKG-INFO`        | `"sdist"`             |

`build_state` is the string you pass into the loader so a provider can tell
which build it is taking part in (see
[Telling a provider the build state](#telling-a-provider-the-build-state)). It
must be one of the five values above
(`dynamic_metadata.protocols.BUILD_STATES`).

Run all hooks from the same directory PEP 517 uses (the project root), since
plugins resolve relative paths like `input = "src/pkg/__init__.py"` against the
current directory.

## Reading the configuration

Parse `pyproject.toml` and take `tool.dynamic-metadata` as an **ordered list of
tables**. Each table has a required `provider`; every other key is
plugin-specific and passed through verbatim as that plugin's `settings`.
{func}`~dynamic_metadata.loader.entries_from_pyproject` reads and validates it,
returning `[]` if absent:

```python
import tomllib  # or tomli on <3.11

from dynamic_metadata.loader import entries_from_pyproject

with open("pyproject.toml", "rb") as f:
    pyproject = tomllib.load(f)

project = pyproject.get("project", {})
entries = entries_from_pyproject(pyproject)
```

A field is only eligible if it appears in `project["dynamic"]`; the loader
enforces this for you.

## Collecting build requirements

In your `get_requires_for_build_*` hooks, add anything the providers ask for.
This is how a provider that wraps an external tool gets its dependency installed
without the user listing it.

```python
from dynamic_metadata.loader import get_requires_for_dynamic_metadata

requires += get_requires_for_dynamic_metadata(entries)
```

Requirements are collected in entry order; a provider without the optional hook
contributes nothing.

A provider that is found but fails to import — typically one that imports at
module level a package it would have declared as its own requirement — is
skipped rather than raising, because its hook cannot be asked; the import error
surfaces when the metadata is resolved. An unknown provider name or a missing
local module always raises. Note that this hook can only run when
`dynamic-metadata` is already in `[build-system].requires`, since your backend
cannot import the loader otherwise; a backend that supports dynamic-metadata
without depending on it should append its own `dynamic-metadata >= X`
requirement when entries are present but the import fails.

## Resolving the metadata

`process_dynamic_metadata` is the core call. It applies the entries in order,
giving each provider a read-only snapshot of the project as resolved so far,
merges each returned fragment into `[project]`, and removes each resolved field
from `dynamic`.

```python
from dynamic_metadata.loader import process_dynamic_metadata

project = process_dynamic_metadata(project, entries, build_state="wheel")
```

After it returns, anything left in `project["dynamic"]` was declared but never
produced — surface that as an error if your backend requires every dynamic field
to be filled. The exact ordering, validation, and merge rules are documented in
[Reimplementing the loader](backend_authors_reimplement.md#resolving-the-metadata);
you only need them if you are replacing this call.

## METADATA 2.2 dynamic status

When building an SDist you write a `PKG-INFO` file. METADATA 2.2 lets a field in
it be marked `Dynamic`, meaning its value may legitimately differ between the
SDist and a wheel built from it. `dynamic_wheel_fields` asks each provider via
the optional `dynamic_wheel` hook and returns the set of field names to mark:

```python
from dynamic_metadata.loader import dynamic_wheel_fields
from dynamic_metadata.info import METADATA_HEADERS

fields = dynamic_wheel_fields(entries)
headers = sorted({h for field in fields for h in METADATA_HEADERS[field]})
```

Only an SDist build needs this. Remove these fields from `project["dynamic"]`
before writing `PKG-INFO` (a field cannot be both given and listed in `dynamic`
there) and write each of their core-metadata headers as a `Dynamic:` line;
`METADATA_HEADERS` in {mod}`dynamic_metadata.info` maps a field to its headers
(`optional-dependencies` → `Provides-Extra`, `Requires-Dist`).

A field no provider mentions is **not** dynamic, and `version` may never be. A
field is dynamic if _any_ provider reports it so: contributions to a field
merge, so one dynamic part makes the merged value dynamic (PEP 643 permits
marking a field `Dynamic` even when a value is also given). Call it after
`process_dynamic_metadata`, so a provider may assume its settings were already
validated by the main hook — but note providers are loaded fresh, so
`dynamic_wheel` cannot rely on state stashed during `dynamic_metadata`.

## Telling a provider the build state

If a provider implements `build_state`, the loader calls it once with the
build-state string **before** `dynamic_metadata`. A provider uses it to adapt —
for example, reading a value back out of an SDist's `PKG-INFO` during a wheel
build instead of recomputing it. Providers that do not care omit the hook; you
just have to pass the right `build_state` value (from the table above) into
`process_dynamic_metadata`.

## Errors

Every error the loader raises derives from
{class}`~dynamic_metadata.errors.DynamicMetadataError` (see
{mod}`dynamic_metadata.errors`), so one `except` translates them all; `str(exc)`
is the message. An exception a provider raises from inside a hook is _not_
wrapped, and propagates as-is.

```python
from dynamic_metadata.errors import DynamicMetadataError

try:
    project = process_dynamic_metadata(project, entries, build_state="wheel")
except DynamicMetadataError as exc:
    raise MyBackendError(str(exc)) from exc
```

## See also

The [API reference](api/index.md) documents the protocols, the
`dynamic_metadata.info` field taxonomy the loader validates against, and the
plugin helpers. If you would rather not depend on this package, see
[Reimplementing the loader](backend_authors_reimplement.md).

[PEP 517]: https://peps.python.org/pep-0517/
