# Migrating from scikit-build-core

If you've used scikit-build-core before the 1.0 release, it shipped an earlier,
provisional dynamic-metadata system under `[tool.scikit-build.metadata]`. This
page maps that system onto the one described here: the first section is for
**users** rewriting their configuration, the second is for **plugin authors**
updating a provider so it works under both loaders during the transition.

The two systems differ in three structural ways:

- **Configuration is an ordered array, not a field-keyed table.** The old
  `[tool.scikit-build.metadata.<field>]` becomes a `[[tool.dynamic-metadata]]`
  entry with the target given as a `field` setting. Entries run top to bottom
  instead of being resolved on demand, so ordering is explicit (see
  [For users](users.md)). This has much less magic and is easier for backends to
  adopt.
- **`provider` is a registered name, not an import path.** The old value was a
  bare importable module; now a string is a name in the
  `dynamic_metadata.provider` entry-point group. Because of this, a plugin can
  support both systems from a single release. A local plugin is an inline
  `{path, module}` table instead of `provider` + `provider-path`.
- **The hook returns a fragment, not a single value.** `dynamic_metadata` no
  longer takes a `field` argument and returns one value, instead it returns
  `{field: value, ...}`.

## Updating `tool.scikit-build.metadata`

Each `[tool.scikit-build.metadata.<field>]` table becomes one
`[[tool.dynamic-metadata]]` array entry:

| Old (`tool.scikit-build.metadata`)     | New (`tool.dynamic-metadata`)                     |
| -------------------------------------- | ------------------------------------------------- |
| `[tool.scikit-build.metadata.version]` | `[[tool.dynamic-metadata]]` + `field = "version"` |
| `provider = "<import.path>"`           | `provider = "<registered-name>"`                  |
| `provider-path = "dir"`                | `provider = { path = "dir", module = "<mod>" }`   |
| any other keys                         | unchanged (still passed as settings)              |

A couple of the bundled providers are in this package as well:
`scikit_build_core.metadata.regex` is `dynamic_metadata.regex`, and
`scikit_build_core.metadata.template` is `dynamic_metadata.template`. Run
`dynamic-metadata providers` to list the non-local providers installed in your
environment.

### A local provider

`provider-path` becomes the `path` of an inline-table `provider`, and the
importable module name becomes `module`:

```toml
# Before
[tool.scikit-build.metadata.version]
provider = "my_plugin"
provider-path = "scripts"
```

```toml
# After
[[tool.dynamic-metadata]]
provider = { path = "scripts", module = "my_plugin" }
field = "version"
```

See [Providing a custom plugin](users.md#providing-a-custom-plugin) for the
details of the inline form (including `module = "my_plugin:MyClass"`).

### Ordering and cross-references

The old system resolved fields lazily and detected cycles at runtime. Entries
now run in the order you list them, and a plugin reads an earlier entry's output
with `project[...]`. If one field is computed from another, make sure the entry
that produces it comes **first** — a forward reference is just a `KeyError`. See
[For users](users.md) for the full ordering and merge rules.

## Updating a plugin

A provider needs two changes to work with the new loader. Both can be made
without breaking the old scikit-build-core system, so a single release can
support both while consumers migrate.

### 1. Register an entry point

The old loader imported the provider module directly from its config string. The
new loader resolves a string `provider` through the `dynamic_metadata.provider`
entry-point group, so add a registration to your `pyproject.toml`:

```toml
[project.entry-points."dynamic_metadata.provider"]
"my_package.my_plugin" = "my_package.plugin"
```

**Prefix the name with your package** — the group is shared, and a name claimed
by two distributions is a hard error. Registering an entry point does not
require a runtime dependency on `dynamic-metadata`. See
[Registering a name](plugin_authors.md#registering-a-name).

### 2. Wrap the hook for both signatures

The two loaders call `dynamic_metadata` differently:

| Loader            | Call                                                                  | Returns           |
| ----------------- | --------------------------------------------------------------------- | ----------------- |
| scikit-build-core | `dynamic_metadata(field, settings)` (or `(field, settings, project)`) | the field's value |
| dynamic-metadata  | `dynamic_metadata(settings, project)`                                 | `{field: value}`  |

`get_requires_for_dynamic_metadata(settings) -> list[str]` has the same
signature in both systems; leave it as is.

`dynamic_wheel` changed shape — the old `dynamic_wheel(field, settings) -> bool`
became `dynamic_wheel(settings) -> dict[str, bool]`. Wrap it the same way if you
implement it.

The new `build_state` hook has no old-system equivalent; add it only if you need
it (see [Optional hooks](plugin_authors.md#optional-hooks)). It is detected by
presence, so an old loader that does not know about it simply never calls it.

### A wrapper class

The new system supports classes, so instead of branching on the argument types
you can keep the existing module-level hooks untouched (scikit-build-core still
imports the module and calls them directly) and add a small class that exposes
the modern signatures, delegating to the old ones. Point the new entry point at
the class:

```toml
[project.entry-points."dynamic_metadata.provider"]
"my_package.my_plugin" = "my_package.plugin:Provider"
```

```python
# ... classic hooks here


class Provider:
    """Adapt the old module-level hooks to the dynamic-metadata protocol."""

    def dynamic_metadata(self, settings, project):
        field = settings["field"]  # or hardcode it for a single-purpose plugin
        # the bare name calls the module-level hook above, not this method
        return {field: dynamic_metadata(field, settings)}

    def dynamic_wheel(self, settings):
        field = settings["field"]
        return {field: dynamic_wheel(field, settings)}

    def get_requires_for_dynamic_metadata(self, settings):
        # unchanged signature — forward as-is
        return get_requires_for_dynamic_metadata(settings)
```

Only add methods for the hooks your plugin actually implements; the loader
detects each by its presence. Because the new loader instantiates the class with
no arguments, `Provider` can also stash state on `self` across hooks (for
example from a `build_state` method) — something the old module-level functions
could not do.

(You do not need to use a class for the new system, but it's available for
things like this).
