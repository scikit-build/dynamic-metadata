# For users

Plugins are configured as an **ordered array of tables**,
`[[tool.dynamic-metadata]]`. Each entry must specify a `provider` exposing the
plugin API; everything else in the entry is passed to that plugin as settings.

An installed plugin is referenced by the **name** it registers in the
`dynamic_metadata.provider` entry-point group. Names are conventionally prefixed
with the providing package, so the bundled plugins are `dynamic_metadata.regex`,
`dynamic_metadata.template`, and so on:

```toml
[[tool.dynamic-metadata]]
provider = "dynamic_metadata.regex"
# ... plugin settings ...
```

Run `dynamic-metadata providers` to see the names available in your environment.
A plugin that lives inside your own project rather than an installed
distribution is instead given as an [inline table](#providing-a-custom-plugin)
with `path` and `module` keys.

Entries run **in order**, so a later entry sees every field an earlier entry
produced. This makes resolution order explicit (no dependency graph), lets you
modify one field with several plugins, and means a plugin can read another
field's value simply with `project[...]`. Plugins can, if desired, use their own
`tool.*` sections as well.

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
provider = "dynamic_metadata.regex"
field = "version"
input = "src/my_package/__init__.py"
```

`dynamic_metadata.regex` is the registered name of the bundled plugin. Since it
lives inside `dynamic-metadata`, you have to include that in your requirements.
Make sure the field is marked dynamic in your project table. The settings are
defined by the plugin; see [Bundled plugins](plugins.md) for the full list of
settings each one accepts.

## Providing a custom plugin

You don't have to publish a plugin, or even put it in an installed package, to
use one. Give `provider` as an **inline table** with a `path` (a local
directory) and a `module` (imported from it), so a plugin can live right inside
your project alongside `pyproject.toml`. A provider loaded this way needs no
runtime dependency on `dynamic-metadata` — it just has to expose the
[hooks](plugin_authors.md).

Drop a module in your project — say `scripts/my_plugin.py`:

```python
def dynamic_metadata(settings, project):
    return {"version": "1.2.3"}
```

and point an entry at it:

```toml
[project]
dynamic = ["version"]

[[tool.dynamic-metadata]]
provider = { path = "scripts", module = "my_plugin" }
```

`module` is the module name (`my_plugin`, the file without its `.py`), and
`path` is the directory to find it in (relative to `pyproject.toml`). It must be
an existing directory, and it is searched in isolation: a module of the same
name reachable elsewhere on `sys.path` will not shadow or substitute for one
missing from `path`. Use `module = "my_plugin:MyClass"` to load a class — it is
imported and instantiated the same way.

Because the module is imported, make sure any third-party packages it needs are
available at build time. If they aren't already pulled in by your build backend,
list them in `[build-system].requires`, or have the plugin declare them from its
`get_requires_for_dynamic_metadata` hook (see
[plugin authors](plugin_authors.md)).

## Inspecting the result

Installing `dynamic-metadata` provides a `dynamic-metadata` command (also
runnable as `python -m dynamic_metadata`) for previewing what your plugins
produce, without invoking the build backend:

```console
$ dynamic-metadata show
```

`show` reads `pyproject.toml` from the current directory, runs the configured
`[[tool.dynamic-metadata]]` entries in order, and prints the resolved
`[project]` table as JSON. Use `--pyproject-toml PATH` to point at another file
and `--state` to choose the build state passed to plugins (default
`metadata_wheel`).

`dynamic-metadata providers` lists the provider names registered in your
environment (the bundled plugins plus any installed third-party plugins) and the
module each resolves to.

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
