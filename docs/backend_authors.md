# For backend authors

**You do not need to depend on dynamic-metadata to support plugins.** This page
describes everything a build backend has to do to drive plugins. You can call
the reference loader in {mod}`dynamic_metadata.loader` directly (a build-time
dependency), vendor it, or reimplement it from the description below — the
behaviour is what matters, not the code.

A backend's job is small: collect the ordered `[[tool.dynamic-metadata]]`
entries, load each entry's `provider`, and call its hooks at the right point in
the [PEP 517][] build. Because the entries are an explicit ordered list, there
is no dependency graph to solve.

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
tables**. Each table has a required `provider` and an optional `provider-path`;
every other key is plugin-specific and passed through verbatim as that plugin's
`settings`.

```python
import tomllib  # or tomli on <3.11

with open("pyproject.toml", "rb") as f:
    pyproject = tomllib.load(f)

project = pyproject.get("project", {})
entries = pyproject.get("tool", {}).get("dynamic-metadata", [])
```

A field is only eligible if it appears in `project["dynamic"]`; the loader
enforces this for you.

## Loading a provider

A `provider` is either a module (`"pkg.mod"`) or a `module:Class`
(`"pkg.mod:Class"`). A bare module is used as-is, so its hooks are module-level
functions; a class is instantiated with no arguments, so its hooks are bound
methods and can share state through `self`.

```python
import importlib


def load_provider(provider, provider_path=None):
    module_name, _, class_name = provider.partition(":")
    # provider_path handling omitted; see below
    module = importlib.import_module(module_name)
    return getattr(module, class_name)() if class_name else module
```

`provider-path` lets a plugin live inside the project being built (a local
directory not installed as a package). The reference loader installs a
`sys.meta_path` finder scoped to that directory for the single import —
mirroring how `pyproject_hooks` handles PEP 517's `backend-path` — so the
in-tree provider wins over any same-named installed module and a missing
provider raises rather than silently importing the wrong one. See
`load_provider` and `_ProviderPathFinder` in {mod}`dynamic_metadata.loader` for
the full implementation; reuse it unless you have a reason not to.

## Detecting the optional hooks

Every provider implements `dynamic_metadata`. The three optional hooks are
detected by their presence; the reference loader exposes runtime-checkable
`Protocol`s so you can test with `isinstance`, but a `hasattr` check is
equivalent:

| Hook                                | Protocol                              | When the backend calls it         |
| ----------------------------------- | ------------------------------------- | --------------------------------- |
| `build_state(state)`                | `DynamicMetadataBuildStateProtocol`   | once, before `dynamic_metadata`   |
| `get_requires_for_dynamic_metadata` | `DynamicMetadataRequirementsProtocol` | during `get_requires_for_build_*` |
| `dynamic_wheel(settings)`           | `DynamicMetadataWheelProtocol`        | after metadata, for METADATA 2.2  |

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
hands back the leftover keys as `settings` (it strips `provider` /
`provider-path`).

## Resolving the metadata

This is the core loop. Apply entries in order; each provider sees a **read-only
snapshot of the project as resolved so far**, returns a `dict` fragment of
`[project]`, and the fragment is merged in. A later entry can read an earlier
one's output with `project[field]`; a forward reference is just a `KeyError`,
and cycles are impossible because nothing can read ahead.

Here is the loop with the validation and merge details inlined — a trimmed
version of `process_dynamic_metadata`:

```python
from types import MappingProxyType
from dynamic_metadata.info import ALL_FIELDS, SCALAR_FIELDS
from dynamic_metadata.loader import (
    DynamicMetadataBuildStateProtocol,
    load_dynamic_metadata,
)


def process_dynamic_metadata(project, entries, build_state):
    result = dict(project)
    result["dynamic"] = list(result.get("dynamic", []))
    declared = set(result["dynamic"])
    snapshot = MappingProxyType(result)  # read-only view, updated in place

    produced = set()  # fields a *previous entry* wrote (vs. a static value)

    for provider, settings in load_dynamic_metadata(entries):
        if isinstance(provider, DynamicMetadataBuildStateProtocol):
            provider.build_state(build_state)
        fragment = provider.dynamic_metadata(settings, snapshot)

        for field, value in fragment.items():
            if field not in ALL_FIELDS:
                raise KeyError(f"{field!r} is not a settable field")
            if field not in declared:
                raise KeyError(f"{field!r} must be listed in project.dynamic")

            if field in produced and field in SCALAR_FIELDS:
                result[field] = value  # transform: replace
            elif field in result:
                result[field] = merge(field, result[field], value)  # PEP 808 add
            else:
                result[field] = value

            produced.add(field)
            if field in result["dynamic"]:
                result["dynamic"].remove(field)

    return result
```

Key points a reimplementation must preserve:

- **`snapshot` is a live read-only view** of `result`. Because
  `MappingProxyType` wraps the same dict, every provider sees fields written by
  earlier entries without you rebuilding the snapshot. It is read-only so a
  provider cannot mutate the project out from under the loader.
- **Validate against the field taxonomy.** A returned field must be in
  `ALL_FIELDS` (`name` and `dynamic` are intentionally excluded) and must be
  listed in `project.dynamic`. `info.py` is the single source of truth for the
  settable fields and their shapes — use it rather than hardcoding a list.
- **A field is resolved once written:** remove it from `dynamic`. After the
  loop, anything left in `dynamic` was declared but never produced — surface
  that as an error if your backend requires every dynamic field to be filled.

## Merge semantics (PEP 808)

`merge(field, current, addition)` combines a field's current value with a
provider's fragment. The rule depends on the field's shape (from `info.py`) and
on whether `current` is a _static_ value or an _earlier entry's_ output:

- **List fields** (`dependencies`, `classifiers`, `authors`, …): concatenate,
  existing entries first. A provider returns only its additions.
- **Table fields** (`urls`, `scripts`, `entry-points`, `optional-dependencies`,
  …): add keys only ([PEP 808][] is add-only). A provider may **not** change the
  value of a key that already exists — raise if it tries.
- **Scalar fields** (`version`, `description`, `requires-python`, `license`,
  `readme`): cannot be extended.
  - Against a **static** value this is the illegal "static _and_ dynamic" case —
    raise.
  - Against an **earlier entry's** output (tracked by `produced`) a later entry
    **replaces** it, enabling a transform pipeline (one plugin extracts a
    version, another normalizes it). This is the
    `field in produced and field in SCALAR_FIELDS` branch above.

The `produced` set is what distinguishes "a user wrote this in `[project]`" from
"an earlier plugin computed this", which is the only thing the static-vs-replace
decision turns on. See `_merge_metadata` and `_merge_dict` in
{mod}`dynamic_metadata.loader` for the per-shape implementation.

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

If a provider implements `build_state`, call it once with the build-state string
**before** `dynamic_metadata` (as shown in the loop). A provider uses it to
adapt — for example, reading a value back out of an SDist's `PKG-INFO` during a
wheel build instead of recomputing it. Providers that do not care omit the hook.

## Using the reference loader directly

If you are fine taking a build-time dependency, you do not need any of the code
above — call the loader:

```python
from dynamic_metadata.loader import process_dynamic_metadata

project = process_dynamic_metadata(project, entries, build_state="wheel")
```

and use `load_dynamic_metadata` for the `get_requires` and `dynamic_wheel`
passes. The [API reference](api/index.md) documents the protocols, the
`dynamic_metadata.info` field taxonomy the loader validates against, and the
plugin helpers.

[PEP 517]: https://peps.python.org/pep-0517/
[PEP 808]: https://peps.python.org/pep-0808/
