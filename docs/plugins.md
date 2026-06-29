# Bundled plugins

This package ships two generic plugins. They read their target from a `field`
setting and can write any field. Because they live inside `dynamic-metadata`,
you must add `dynamic-metadata` to your `[build-system].requires` to use them.

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

| Setting  | Required         | Description                                                                                                                                               |
| -------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `field`  | yes              | The metadata field to set.                                                                                                                                |
| `input`  | yes              | The file to read.                                                                                                                                         |
| `regex`  | unless version   | The pattern to search for. Must capture a `value` named group (`?P<value>`). Defaults to matching `__version__`/`VERSION` (optionally `: str`-annotated). |
| `result` | no (`"{value}"`) | A `str.format` template over the match, with access to every numbered and named group.                                                                    |
| `remove` | no               | A regex stripped from the result.                                                                                                                         |

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

| Setting  | Required | Description                                                               |
| -------- | -------- | ------------------------------------------------------------------------- |
| `field`  | yes      | The metadata field to set.                                                |
| `result` | yes      | A `str.format` template; reference resolved fields with `{project[...]}`. |

Only fields produced by earlier entries (or static values already in
`[project]`) are available — a forward reference raises a `KeyError`.

</content>
