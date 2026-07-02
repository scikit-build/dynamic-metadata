# Reimplementing the loader

**You do not need to depend on dynamic-metadata to support plugins.** You can
vendor {mod}`dynamic_metadata.loader` or reimplement it from the description
below — the behaviour is what matters. Every example here is self-contained:
nothing imports from `dynamic_metadata`.

This page assumes you have read [For backend authors](backend_authors.md) for
how the hooks plug into a PEP 517 build, how to read the configuration, and what
`build_state` is. Reimplementing replaces four things that page gets from the
package: loading a provider, detecting its optional hooks, the field taxonomy,
and the resolution loop with its merge rules.

## Loading a provider

A `provider` takes one of two shapes. A **string** is a name registered in the
`dynamic_metadata.provider` entry-point group. An **inline table**
`{ path, module }` names a local plugin: `module` (`"pkg.mod"` or
`"pkg.mod:Class"`) is imported from the `path` directory. The module-path form
is _only_ available via the table — an installed plugin is reachable through its
entry point, not a bare import string.

The loaded object is used according to its kind: a module is used as-is (hooks
are module-level functions); a class is instantiated with no arguments (hooks
are bound methods and can share state through `self`); an already-instantiated
object (a `module:instance` entry point) is used directly.

```python
from importlib.metadata import entry_points


def load_provider(spec):
    if not isinstance(spec, str):  # inline table {path, module}
        return import_from_path(spec["module"], spec["path"])  # see below
    matches = [
        ep for ep in entry_points(group="dynamic_metadata.provider") if ep.name == spec
    ]
    match matches:
        case []:
            raise ModuleNotFoundError(f"Unknown provider {spec!r}")
        case [ep]:
            obj = ep.load()
            return obj() if isinstance(obj, type) else obj
        case _:  # two distributions registered the same name
            raise RuntimeError(f"Provider {spec!r} is ambiguous: {matches}")
```

Names are conventionally prefixed with the providing package (the bundled
plugins are `dynamic_metadata.regex`, …); a name registered by more than one
distribution is a hard error, not a non-deterministic pick.

The inline-table `path` lets a plugin live inside the project being built. To
import it, install a `sys.meta_path` finder scoped to that directory for the
single import, mirroring how `pyproject_hooks` handles PEP 517's `backend-path`.
Scoping matters: the in-tree provider must win over any same-named installed
module, and a missing provider must raise rather than import the wrong one.
`load_provider` and `_ProviderPathFinder` in {mod}`dynamic_metadata.loader` are
a worked implementation you can copy.

You load each entry's provider several times (for requirements, metadata, and
the METADATA 2.2 pass), so a small generator that loads the provider and splits
off the plugin-specific keys as `settings` is handy:

```python
def load_dynamic_metadata(entries):
    for entry in entries:
        entry = dict(entry)
        provider = entry.pop("provider")
        yield load_provider(provider), entry  # entry is now `settings`
```

## Detecting the optional hooks

Every provider implements `dynamic_metadata`. The three optional hooks are
detected by their presence — a plain `hasattr` check:

| Hook                                | `hasattr` name                      | When the backend calls it         |
| ----------------------------------- | ----------------------------------- | --------------------------------- |
| `build_state(state)`                | `build_state`                       | once, before `dynamic_metadata`   |
| `get_requires_for_dynamic_metadata` | `get_requires_for_dynamic_metadata` | during `get_requires_for_build_*` |
| `dynamic_wheel(settings)`           | `dynamic_wheel`                     | after metadata, for METADATA 2.2  |

The requirements and METADATA 2.2 passes are simple collection loops
(`get_requires_for_dynamic_metadata` and `dynamic_wheel_fields` in
{mod}`dynamic_metadata.loader`, with each `isinstance(provider, SomeProtocol)`
replaced by `hasattr(provider, ...)`):

```python
def get_requires_for_dynamic_metadata(entries):
    requires = []
    for provider, settings in load_dynamic_metadata(entries):
        if hasattr(provider, "get_requires_for_dynamic_metadata"):
            requires += provider.get_requires_for_dynamic_metadata(settings)
    return requires


def dynamic_wheel_fields(entries):
    fields = set()
    for provider, settings in load_dynamic_metadata(entries):
        if not hasattr(provider, "dynamic_wheel"):
            continue
        for field, is_dynamic in provider.dynamic_wheel(settings).items():
            if field not in ALL_FIELDS:
                raise KeyError(f"{field!r} is not a settable field")
            if field == "version" and is_dynamic:
                raise ValueError("'version' may never be dynamic")
            if is_dynamic:
                fields.add(field)
    return fields
```

`dynamic_wheel_fields` must validate reported names against the field taxonomy,
reject a dynamic `version`, and treat a field as dynamic if _any_ provider says
so — contributions to a field merge, so one dynamic part makes the merged value
dynamic.

## The field taxonomy

You need to know which `[project]` fields a provider may set and what _shape_
each value has, because the shape decides how a fragment merges. `name` and
`dynamic` are intentionally excluded. This mirrors `dynamic_metadata.info`; copy
it if you would rather not maintain your own:

```python
STR_FIELDS = {"version", "description", "requires-python", "license"}
LIST_STR_FIELDS = {"classifiers", "keywords", "dependencies", "license-files"}
DICT_STR_FIELDS = {"urls", "scripts", "gui-scripts"}
LIST_DICT_FIELDS = {"authors", "maintainers"}

# Single-value fields: a later entry replaces the value rather than extending it.
SCALAR_FIELDS = STR_FIELDS | {"readme"}

ALL_FIELDS = (
    STR_FIELDS
    | LIST_STR_FIELDS
    | DICT_STR_FIELDS
    | LIST_DICT_FIELDS
    | {"optional-dependencies", "readme", "entry-points"}
)
```

`readme`, `entry-points`, and `optional-dependencies` are the special-cased
shapes; the merge rules below spell out how each combines.

## Resolving the metadata

This is the core loop. Apply entries in order; each provider sees a **read-only
snapshot of the project as resolved so far**, returns a `dict` fragment of
`[project]`, and the fragment is merged in. A later entry can read an earlier
one's output with `project[field]`; a forward reference is just a `KeyError`,
and cycles are impossible because nothing can read ahead.

```python
from types import MappingProxyType


def process_dynamic_metadata(project, entries, build_state):
    result = dict(project)
    result["dynamic"] = list(result.get("dynamic", []))
    declared = set(result["dynamic"])
    snapshot = MappingProxyType(result)  # read-only view, updated in place

    produced = set()  # fields a *previous entry* wrote (vs. a static value)

    for provider, settings in load_dynamic_metadata(entries):
        if hasattr(provider, "build_state"):
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

- **`snapshot` is a live read-only view** of `result`. `MappingProxyType` wraps
  the same dict, so every provider sees fields written by earlier entries with
  no rebuild; being read-only stops a provider mutating the project under the
  loader.
- **Validate against the field taxonomy.** A returned field must be in
  `ALL_FIELDS` and listed in `project.dynamic`.
- **A field is resolved once written:** remove it from `dynamic`. Anything left
  after the loop was declared but never produced — surface that as an error if
  your backend requires every dynamic field to be filled.

## Merge semantics (PEP 808)

`merge(field, current, addition)` combines a field's current value with a
provider's fragment, dispatching on the field's shape:

```python
def merge(field, current, addition):
    match field:
        case _ if field in LIST_STR_FIELDS | LIST_DICT_FIELDS:
            return current + addition  # concatenate, existing entries first
        case "entry-points" | "optional-dependencies":
            return merge_table(current, addition, nested=True)  # table of tables/lists
        case _ if field in DICT_STR_FIELDS:
            return merge_table(current, addition, nested=False)
        case _:  # scalar — cannot be extended
            raise ValueError(f"{field!r} is static and cannot also be dynamic")
```

- **List fields** concatenate, existing entries first; a provider returns only
  its additions.
- **Table fields** are add-only ([PEP 808][]): a provider adds keys but may
  **not** change an existing key's value — `merge_table` raises if it tries.
  `entry-points` and `optional-dependencies` nest one level (a table of
  groups/extras), so merge recursively with the same rule.
- **Scalar fields** cannot be extended. Reaching this branch means merging
  against a **static** value — the illegal "static _and_ dynamic" case. Merging
  against an **earlier entry's** output never gets here: the loop's
  `field in produced and field in SCALAR_FIELDS` branch **replaces** instead,
  enabling a transform pipeline (one plugin extracts a version, another
  normalizes it).

The `produced` set is the only thing the static-vs-replace decision turns on: it
distinguishes "a user wrote this in `[project]`" from "an earlier plugin
computed this". `_merge_metadata` and `_merge_dict` in
{mod}`dynamic_metadata.loader` are a per-shape implementation you can copy.

[PEP 808]: https://peps.python.org/pep-0808/
