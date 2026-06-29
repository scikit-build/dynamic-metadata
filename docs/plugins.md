# Bundled plugins

This package ships a handful of plugins. Two are generic (they read their target
from a `field` setting and can write any field), and two wrap external tools.
Because they live inside `dynamic-metadata`, you must add `dynamic-metadata` to
your `[build-system].requires` to use them.

## `regex`

`dynamic_metadata.plugins.regex` extracts a value from a file with a regular
expression. By default it pulls a version out of a `__version__`/`VERSION`
assignment.

```toml
[project]
dynamic = ["version"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.regex"
field = "version"
input = "src/my_package/__init__.py"
```

Settings (all values must be strings):

| Setting  | Required           | Description                                                                                                                                  |
| -------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `field`  | yes                | The metadata field to set.                                                                                                                   |
| `input`  | yes                | The file to read.                                                                                                                            |
| `regex`  | unless version     | The pattern to search for. Must capture a `value` named group (`?P<value>`). Defaults to matching `__version__`/`VERSION` (optionally `: str`-annotated). |
| `result` | no (`"{value}"`)   | A `str.format` template over the match, with access to every numbered and named group.                                                       |
| `remove` | no                 | A regex stripped from the result.                                                                                                            |

The search runs in `re.MULTILINE` mode. When the target `field` is not a string
field, `result` is applied across the container shape the field requires (each
string in a list, each value in a table, and so on).

## `template`

`dynamic_metadata.plugins.template` fills a `str.format` template from fields
resolved by earlier entries, demonstrating cross-field references.

```toml
[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.template"
field = "readme"
result = "{project[name]} {project[version]}"
```

Settings:

| Setting  | Required | Description                                                              |
| -------- | -------- | ------------------------------------------------------------------------ |
| `field`  | yes      | The metadata field to set.                                               |
| `result` | yes      | A `str.format` template; reference resolved fields with `{project[...]}`. |

Only fields produced by earlier entries (or static values already in
`[project]`) are available — a forward reference raises a `KeyError`.

## `setuptools_scm`

`dynamic_metadata.plugins.setuptools_scm` wraps [setuptools-scm][] to derive the
version from your version control system. It takes no inline settings; configure
it through setuptools-scm's own `[tool.setuptools_scm]` table. The dependency is
declared via `get_requires_for_dynamic_metadata`, so the backend installs it
automatically.

```toml
[project]
dynamic = ["version"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.setuptools_scm"

[tool.setuptools_scm]
```

## `fancy_pypi_readme`

`dynamic_metadata.plugins.fancy_pypi_readme` wraps [hatch-fancy-pypi-readme][] to
build a `readme`. It takes no inline settings; configure it through the
`[tool.hatch.metadata.hooks.fancy-pypi-readme]` table. The dependency
(`hatch-fancy-pypi-readme>=22.3`) is declared via
`get_requires_for_dynamic_metadata`. Substitutions can reference the resolved
`version`, so place this entry after the one that produces it.

```toml
[project]
dynamic = ["readme"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.fancy_pypi_readme"

[tool.hatch.metadata.hooks.fancy-pypi-readme]
content-type = "text/markdown"
# ... fragments and substitutions ...
```

[setuptools-scm]: https://setuptools-scm.readthedocs.io
[hatch-fancy-pypi-readme]: https://github.com/hynek/hatch-fancy-pypi-readme
</content>
