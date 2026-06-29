# For users

Plugins are configured as an **ordered array of tables**,
`[[tool.dynamic-metadata]]`. Each entry must specify a `provider` exposing the
plugin API; everything else in the entry is passed to that plugin as settings. A
`provider` is either a module (`"<module>"`) or a class within a module
(`"<module>:<Class>"`); a class is instantiated and its hooks are called as
methods.

```toml
[[tool.dynamic-metadata]]
provider = "<module>"        # or "<module>:<Class>"
# ... plugin settings ...
```

Entries run **in order**, so a later entry sees every field an earlier entry
produced. This makes resolution order explicit (no dependency graph), lets you
modify one field with several plugins, and means a plugin can read another
field's value simply with `project[...]`.

There is an optional key, `provider-path`, which specifies a local directory to
load the plugin from, allowing plugins to live inside your own project. Plugins
can, if desired, use their own `tool.*` sections as well.

Your build backend _must support_ dynamic-metadata for this to work. Build
backends known to support this currently include:

- scikit-build-core (1.0+)

## Example: regex

An example regex plugin is provided in this package. It is used like this:

```toml
[build-system]
requires = ["...", "dynamic-metadata"]
build-backend = "..."

[project]
dynamic = ["version"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.regex"
field = "version"
input = "src/my_package/__init__.py"
```

Since this plugin lives inside `dynamic-metadata`, you have to include that in
your requirements. Make sure the field is marked dynamic in your project table.
The settings are defined by the plugin; see [Bundled plugins](plugins.md) for
the full list of settings each one accepts.

## Mixing static and dynamic values (PEP 808)

Following [PEP 808][], list and table fields can be given a static value in
`[project]` _and_ listed in `dynamic` at the same time. A provider may only
**add** to the static portion — it cannot remove, reorder, or change existing
entries.

```toml
[project]
dependencies = ["torch", "packaging"]
dynamic = ["dependencies"]

[[tool.dynamic-metadata]]
provider = "..."
field = "dependencies"
```

The provider returns only its additions; the loader merges them onto the current
value, with existing entries kept first and the provider's entries appended
verbatim. A provider may read the value of any field already resolved (the
static value of the field it is extending, or any field produced by an earlier
entry) via `project[...]` to decide what to add; reading a field that has not
been produced yet raises a `KeyError`. For tables (`urls`, `scripts`,
`entry-points`, `optional-dependencies`, …) the provider may add keys but not
change the value of an existing one.

This add-only merge applies to every list/table field. The single-value fields
(`version`, `description`, `requires-python`, `license`, and `readme`) cannot be
extended, so they may not be both static and dynamic; a later entry targeting
one of them instead **replaces** the value (a transform pipeline — for example,
one plugin extracts a version and a later one normalizes it).

[PEP 808]: https://peps.python.org/pep-0808/

</content>
</invoke>
