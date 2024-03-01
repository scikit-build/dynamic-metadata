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
> This plugin is still a WiP!

## For users

Every external plugin must specify a "provider", which is a module that provides
the API listed in the next section.

```toml
[tool.dynamic-metadata]
<field-name>.provider = "<module>"
```

There is an optional field: "provider-path", which specifies a local path to
load a plugin from, allowing plugins to reside inside your own project.

All other fields are passed on to the plugin, allowing plugins to specify custom
configuration per field. Plugins can, if desired, use their own `tool.*`
sections as well; plugins only supporting one metadata field are more likely to
do this.

### Example: regex

An example regex plugin is provided in this package. It is used like this:

```toml
[build-system]
requires = ["...", "dynamic-metadata"]
build-backend = "..."

[project]
dynamic = ["version"]

[tool.dynamic-metadata.version]
provider = "dynamic_metadata.plugins.regex"
input = "src/my_package/__init__.py"
regex = '(?i)^(__version__|VERSION) *= *([\'"])v?(?P<value>.+?)\2'
```

In this case, since the plugin lives inside `dynamic-metadata`, you have to
include that in your requirements. Make sure the version is marked dynamic in
your project table. And then you specify `version.provider`. The other options
are defined by the plugin; this one takes a required `input` file and an
optional `regex` (which defaults to the expression you see above). The regex
optional `regex` (which defaults to the expression you see above). The regex
needs to have a `"value"` named group (`?P<value>`), which it will set.

## For plugin authors

**You do not need to depend on dynamic-metadata to write a plugin.** This
library provides testing and static typing helpers that are not needed at
runtime.

Like PEP 517's hooks, `dynamic-metadata` defines a set of hooks that you can
implement; one required hook and two optional hooks. The required hook is:

```python
def dynamic_metadata(
    field: str,
    settings: dict[str, object] | None = None,
) -> str | dict[str, str | None]:
    ...  # return the value of the metadata
```

The backend will call this hook in the same directory as PEP 517's hooks.

There are two optional hooks.

A plugin can return METADATA 2.2 dynamic status:

```python
def dynamic_wheel(field: str, settings: Mapping[str, Any] | None = None) -> bool:
    ...  # Return true if metadata can change from SDist to wheel (METADATA 2.2 feature)
```

If this hook is not implemented, it will default to "false". Note that "version"
must always return "false". This hook is called after the main hook, so you do
not need to validate the input here.

A plugin can also decide at runtime if it needs extra dependencies:

```python
def get_requires_for_dynamic_metadata(
    settings: Mapping[str, Any] | None = None,
) -> list[str]:
    ...  # return list of packages to require
```

This is mostly used to provide wrappers for existing non-compatible plugins and
for plugins that require a CLI tool that has an optional compiled component.

### Example: regex

Here is the regex plugin example implementation:

```python
def dynamic_metadata(
    field: str,
    settings: Mapping[str, Any],
) -> str:
    # Input validation
    if field not in {"version", "description", "requires-python"}:
        raise RuntimeError("Only string feilds supported by this plugin")
    if settings > {"input", "regex"}:
        raise RuntimeError("Only 'input' and 'regex' settings allowed by this plugin")
    if "input" not in settings:
        raise RuntimeError("Must contain the 'input' setting to perform a regex on")
    if not all(isinstance(x, str) for x in settings.values()):
        raise RuntimeError("Must set 'input' and/or 'regex' to strings")

    input = settings["input"]
    # If not explicitly specified in the `tool.dynamic-metadata.<field-name>` table,
    # the default regex provided below is used.
    regex = settings.get(
        "regex", r'(?i)^(__version__|VERSION) *= *([\'"])v?(?P<value>.+?)\2'
    )

    with Path(input).open(encoding="utf-8") as f:
        match = re.search(regex, f.read())

    if not match:
        raise RuntimeError(f"Couldn't find {regex!r} in {file}")

    return match.groups("value")
```

## For backend authors

**You do not need to depend on dynamic-metadata to support plugins.** This
library provides some helper functions you can use if you want, but you can
implement them yourself following the standard provided or vendor the helper
file (which will be tested and supported).

You should collect the contents of `tool.dynamic-metadata` and load each,
something like this:

```python
def load_provider(
    provider: str,
    provider_path: str | None = None,
) -> DynamicMetadataProtocol:
    if provider_path is None:
        return importlib.import_module(provider)

    if not Path(provider_path).is_dir():
        msg = "provider-path must be an existing directory"
        raise AssertionError(msg)

    try:
        sys.path.insert(0, provider_path)
        return importlib.import_module(provider)
    finally:
        sys.path.pop(0)


for dynamic_metadata in settings.metadata.values():
    if "provider" in dynamic_metadata:
        config = dynamic_metadata.copy()
        provider = config.pop("provider")
        provider_path = config.pop("provider-path", None)
        module = load_provider(provider, provider_path)
        # Run hooks from module
```

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
