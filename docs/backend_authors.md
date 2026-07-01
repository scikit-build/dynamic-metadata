# For backend authors

A backend's job is small: collect the ordered `[[tool.dynamic-metadata]]`
entries, load each entry's `provider`, and call its hooks at the right point in
the [PEP 517][] build. Because the entries are an explicit ordered list, there
is no dependency graph to solve.

The easiest way to do this is to take a build-time dependency on this package
and call the reference loader in {mod}`dynamic_metadata.loader`, which is what
this page shows. **You do not have to depend on us**, though: you can vendor the
loader or reimplement it from a precise description of its behaviour — see
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
must be one of the five values above (`dynamic_metadata.loader.BUILD_STATES`).

Run all hooks from the same directory PEP 517 uses (the project root), since
plugins resolve relative paths like `input = "src/pkg/__init__.py"` against the
current directory.

## Reading the configuration

Parse `pyproject.toml` and take `tool.dynamic-metadata` as an **ordered list of
tables**. Each table has a required `provider`; every other key is
plugin-specific and passed through verbatim as that plugin's `settings`.

```python
import tomllib  # or tomli on <3.11

with open("pyproject.toml", "rb") as f:
    pyproject = tomllib.load(f)

project = pyproject.get("project", {})
entries = pyproject.get("tool", {}).get("dynamic-metadata", [])
```

A field is only eligible if it appears in `project["dynamic"]`; the loader
enforces this for you.

## Collecting build requirements

In your `get_requires_for_build_*` hooks, load each provider and union in
anything it asks for. This is how a provider that wraps an external tool gets
its dependency installed without the user listing it.

```python
from dynamic_metadata.loader import (
    DynamicMetadataRequirementsProtocol,
    load_dynamic_metadata,
)


def collect_requires(entries):
    requires = []
    for provider, settings in load_dynamic_metadata(entries):
        if isinstance(provider, DynamicMetadataRequirementsProtocol):
            requires += provider.get_requires_for_dynamic_metadata(settings)
    return requires
```

`load_dynamic_metadata` is a thin generator that loads each entry's provider and
hands back the leftover keys as `settings` (it consumes only `provider`).

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
to be filled. You still have access to the original dynamic list, of course, if
you need it. The exact ordering, validation, and merge rules the loader applies
are documented in
[Reimplementing the loader](backend_authors_reimplement.md#resolving-the-metadata);
you only need them if you are replacing this call.

## METADATA 2.2 dynamic status

After resolving metadata you write a `METADATA` file. METADATA 2.2 lets a field
be marked `Dynamic`, meaning its value may legitimately differ between the SDist
and the wheel built from it. Ask each provider which of its fields are dynamic
in that sense via the optional `dynamic_wheel` hook:

```python
from dynamic_metadata.loader import (
    DynamicMetadataWheelProtocol,
    load_dynamic_metadata,
)


def dynamic_wheel_fields(entries):
    fields = {}
    for provider, settings in load_dynamic_metadata(entries):
        if isinstance(provider, DynamicMetadataWheelProtocol):
            fields.update(provider.dynamic_wheel(settings))
    return {field for field, is_dynamic in fields.items() if is_dynamic}
```

A field a provider does not mention defaults to **not** dynamic, and `version`
must never be dynamic. Call this hook after `dynamic_metadata`, so a provider
can rely on its inputs already being validated.

## Telling a provider the build state

If a provider implements `build_state`, the loader calls it once with the
build-state string **before** `dynamic_metadata`. A provider uses it to adapt —
for example, reading a value back out of an SDist's `PKG-INFO` during a wheel
build instead of recomputing it. Providers that do not care omit the hook; you
just have to pass the right `build_state` value (from the table above) into
`process_dynamic_metadata`.

## See also

The [API reference](api/index.md) documents the protocols, the
`dynamic_metadata.info` field taxonomy the loader validates against, and the
plugin helpers. If you would rather not depend on this package, see
[Reimplementing the loader](backend_authors_reimplement.md).

[PEP 517]: https://peps.python.org/pep-0517/
