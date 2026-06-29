# dynamic-metadata

[![Actions Status][actions-badge]][actions-link]
[![Documentation Status][rtd-badge]][rtd-link]

[![PyPI version][pypi-version]][pypi-link]
[![PyPI platforms][pypi-platforms]][pypi-link]

[![GitHub Discussion][github-discussions-badge]][github-discussions-link]

<!-- SPHINX-START -->

This repo is to support
https://github.com/scikit-build/scikit-build-core/issues/230.

> [!WARNING]
>
> This is still a WiP! The design may still change.

## For users

Plugins are configured as an **ordered array of tables**,
`[[tool.dynamic-metadata]]`. Each entry must specify a `provider` exposing the
API in the next section; everything else in the entry is passed to that plugin
as settings. A `provider` is either a module (`"<module>"`) or a class within a
module (`"<module>:<Class>"`); a class is instantiated and its hooks are called
as methods.

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

### Example: regex

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
regex = '(?i)^(__version__|VERSION) *= *([\'"])v?(?P<value>.+?)\2'
```

Since this plugin lives inside `dynamic-metadata`, you have to include that in
your requirements. Make sure the field is marked dynamic in your project table.
The settings are defined by the plugin; this one takes the target `field`, a
required `input` file, and an optional `regex` (which defaults to the expression
above). The regex needs a `"value"` named group (`?P<value>`), which it will
set.

### Mixing static and dynamic values (PEP 808)

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

## For plugin authors

**You do not need to depend on dynamic-metadata to write a plugin.** This
library provides testing and static typing helpers that are not needed at
runtime, along with a reference implementation that you can either use as an
example, or use directly if you are fine to require the dependency.

Like PEP 517's hooks, `dynamic-metadata` defines a set of hooks that you can
implement; one required hook and three optional hooks. A provider is either a
module exposing these hooks as functions, or a class (`"<module>:<Class>"`)
exposing them as methods — a class is instantiated with no arguments, so its
hooks share state through `self`. The required hook is:

```python
def dynamic_metadata(
    settings: Mapping[str, Any],
    project: Mapping[str, Any],
) -> dict[str, Any]: ...  # return a fragment of [project], e.g. {"version": ...}
```

The hook returns a **dict** that is a fragment of the `[project]` table — a
mapping of field name to value, such as `{"version": "1.2.3"}` or
`{"dependencies": ["numpy"]}`. The framework merges it into the project. One
plugin may set several fields at once, and every returned field must be listed
in `[project].dynamic`.

The hook no longer receives a `field` argument: a single-purpose plugin
(`setuptools_scm`, `fancy_pypi_readme`) hardcodes which field it produces, while
a generic plugin (`regex`, `template`) reads the target field from a `field`
setting. `project` is a read-only mapping of the project as resolved so far;
read another field's value with `project["version"]`. The backend calls this
hook in the same directory as PEP 517's hooks.

There are three optional hooks.

A plugin can receive the current build state:

```python
def build_state(
    build_state: str,
) -> None: ...  # called before dynamic_metadata with the current build state
```

`build_state` is a string the backend supplies describing the current build. It
must be one of scikit-build-core's five build states: `"sdist"`, `"wheel"`,
`"editable"`, `"metadata_wheel"`, or `"metadata_editable"` (the latter two are
the `prepare_metadata_for_build_*` phases). This hook is called once, before
`dynamic_metadata`. A plugin may use it — for example to reuse a value already
computed in an SDist's `PKG-INFO` instead of recomputing it for the wheel — by
stashing it (typically on `self` in a class provider) for `dynamic_metadata` to
read; a plugin that does not care simply omits this hook.

A plugin can return METADATA 2.2 dynamic status:

```python
def dynamic_wheel(
    settings: Mapping[str, Any],
) -> dict[str, bool]: ...  # map each field set -> may it change from SDist to wheel?
```

It returns a map from each field this plugin sets to whether that field's value
can change between the SDist and the wheel (the METADATA 2.2 feature). A field
not present defaults to "false", and `"version"` must always be "false". This
hook is called after the main hook, so you do not need to validate the input
here.

A plugin can also decide at runtime if it needs extra dependencies:

```python
def get_requires_for_dynamic_metadata(
    settings: Mapping[str, Any],
) -> list[str]: ...  # return list of packages to require
```

This is mostly used to provide wrappers for existing non-compatible plugins and
for plugins that require a CLI tool that has an optional compiled component.

### Example: regex

Here is a simplified version of the regex plugin:

```python
def dynamic_metadata(
    settings: Mapping[str, Any],
    _project: Mapping[str, Any],
) -> dict[str, Any]:
    # Input validation
    if settings.keys() - {"field", "input", "regex"}:
        raise RuntimeError("Only 'field', 'input', and 'regex' settings allowed")
    if "field" not in settings:
        raise RuntimeError("Must contain the 'field' setting naming the target")
    if "input" not in settings:
        raise RuntimeError("Must contain the 'input' setting to perform a regex on")
    if not all(isinstance(x, str) for x in settings.values()):
        raise RuntimeError("All settings must be strings")

    field = settings["field"]
    # If not explicitly specified in the entry, the default regex below is used.
    regex = settings.get(
        "regex", r'(?i)^(__version__|VERSION) *= *([\'"])v?(?P<value>.+?)\2'
    )

    with Path(settings["input"]).open(encoding="utf-8") as f:
        match = re.search(regex, f.read())

    if not match:
        raise RuntimeError(f"Couldn't find {regex!r} in {settings['input']}")

    return {field: match.group("value")}
```

## For backend authors

**You do not need to depend on dynamic-metadata to support plugins.** This
library provides some helper functions you can use if you want, but you can
implement them yourself following the standard provided or vendor the helper
file (which will be tested and supported).

Collect the array of `[[tool.dynamic-metadata]]` entries and process them in
order: load each entry's `provider`, call its `dynamic_metadata` hook with a
snapshot of the project resolved so far, and merge the returned fragment in.
Because the order is explicit, there is no dependency graph to compute — see
`src/dynamic_metadata/loader.py` for the reference loop.

<!-- prettier-ignore-start -->
[actions-badge]:            https://github.com/scikit-build/dynamic-metadata/workflows/CI/badge.svg
[actions-link]:             https://github.com/scikit-build/dynamic-metadata/actions
[github-discussions-badge]: https://img.shields.io/static/v1?label=Discussions&message=Ask&color=blue&logo=github
[github-discussions-link]:  https://github.com/scikit-build/scikit-build/discussions
[pypi-link]:                https://pypi.org/project/dynamic-metadata/
[pypi-platforms]:           https://img.shields.io/pypi/pyversions/dynamic-metadata
[pypi-version]:             https://img.shields.io/pypi/v/dynamic-metadata
[rtd-badge]:                https://readthedocs.org/projects/dynamic-metadata/badge/?version=latest
[rtd-link]:                 https://dynamic-metadata.readthedocs.io/en/latest/?badge=latest

<!-- prettier-ignore-end -->
