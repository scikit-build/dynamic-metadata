# For plugin authors

**You do not need to depend on dynamic-metadata to write a plugin.** This
library provides testing and static typing helpers that are not needed at
runtime, along with a reference implementation that you can either use as an
example, or use directly if you are fine to require the dependency.

Like PEP 517's hooks, `dynamic-metadata` defines a set of hooks that you can
implement; one required hook and three optional hooks. A provider is either a
module exposing these hooks as functions, or a class (`"<module>:<Class>"`)
exposing them as methods — a class is instantiated with no arguments, so its
hooks share state through `self`.

## Registering a name

An installed plugin is referenced by a name it registers in the
`dynamic_metadata.provider` entry-point group — the module-path form is only for
a loose script inside the project being built, given as an
[inline table](users.md#providing-a-custom-plugin). So a distributed plugin
registers:

```toml
[project.entry-points."dynamic_metadata.provider"]
"my_package.my_plugin" = "my_package.plugin"   # or "my_package.plugin:MyClass"
```

The value points at the module or class exposing the hooks. **Prefix the name
with your package name** (here `my_package.`) — the group is shared across every
installed plugin, and a name registered by two distributions is a hard error.
The bundled plugins follow this convention (`dynamic_metadata.regex`, …). This
is the only reason to touch your `pyproject.toml`; the hooks are unchanged, and
you still do not depend on `dynamic-metadata` at runtime.

## The required hook

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

The hook does not receive a `field` argument: a single-purpose plugin hardcodes
which field it produces, while a generic plugin (`regex`, `template`) reads the
target field from a `field` setting. `project` is a read-only mapping of the
project as resolved so far; read another field's value with
`project["version"]`. The backend calls this hook in the same directory as PEP
517's hooks.

## Optional hooks

### Receiving the build state

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

### METADATA 2.2 dynamic status

```python
def dynamic_wheel(
    settings: Mapping[str, Any],
) -> dict[str, bool]: ...  # map each field set -> may it change from SDist to wheel?
```

It returns a map from each field this plugin sets to whether that field's value
can change between the SDist and the wheel (the METADATA 2.2 feature). A field
not present defaults to "false", and `"version"` must always be "false". This
hook runs after the main hook in the build, so you do not need to validate the
input here — but it may be called on a fresh instance, so do not rely on state
stashed by `dynamic_metadata` or `build_state`.

### Extra build requirements

```python
def get_requires_for_dynamic_metadata(
    settings: Mapping[str, Any],
) -> list[str]: ...  # return list of packages to require
```

This is mostly used to provide wrappers for existing non-compatible plugins and
for plugins that require a CLI tool that has an optional compiled component.

## Example: regex

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

## Reusing the value-shaping helper

A generic plugin should work for every field type, not just strings. The
`dynamic_metadata.plugins._process_dynamic_metadata(field, action, result)`
helper applies a string-transform `action` across whatever container shape the
target `field` requires (a string, a list of strings, a table, a table of lists,
…), validating the shape along the way. The bundled `regex` and `template`
plugins call it so they only write the transform once. You are encouraged to do
something similar.
