# Bundled plugins

This package ships five plugins. `regex`, `template`, and `substitute` are
generic — they read their target from a `field` setting. `static` writes values
straight from its settings, and `readme_fragment` is single-purpose and always
writes `readme`. Because they live inside `dynamic-metadata`, you must add
`dynamic-metadata` to your `[build-system].requires` to use them.

Entries run in order and each sees the project resolved so far, so several
entries can cooperate on one field: `readme_fragment` and `substitute` build a
readme the way [hatch-fancy-pypi-readme][] assembles one — one entry per
fragment or substitution rather than a nested list.

[hatch-fancy-pypi-readme]: https://github.com/hynek/hatch-fancy-pypi-readme

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

## `static`

`dynamic_metadata.plugins.static` sets fields directly from its own settings —
an alternative to writing them in `[project]`. Each setting is a metadata field
mapped to its value, returned verbatim.

```toml
[project]
dynamic = ["version", "description"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.static"
version = "1.2.3"
description = "My package"
```

Settings: any settable metadata field maps to the value to give it. The fields
must be listed in `project.dynamic` like every dynamic field, and values use the
same shape they would in `[project]` — a string for `version`, a list for
`keywords`, a table for `readme`, and so on.

This is mainly useful as the first half of a pipeline: it gives a later entry
like `substitute` a _dynamic_ value to transform, which a field set in
`[project]` cannot be (a scalar field may not be both static and dynamic).

```toml
[project]
dynamic = ["version"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.static"
version = "1.2.3-beta"

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.substitute"
field = "version"
pattern = "-beta$"
replacement = "b0"
```

It can also keep metadata out of `[project]`, hiding it from tools that read
`[project]` directly.

## `readme_fragment`

`dynamic_metadata.plugins.readme_fragment` builds a `readme` from an ordered
series of fragments, each its own entry. Every entry appends to the readme
produced by the entries before it, so a heading, a slice of a file, and a
changelog excerpt can be stitched together. An entry with `text` is a literal
fragment; an entry with `path` reads a file and may slice it.

```toml
[project]
dynamic = ["readme"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.readme_fragment"
content-type = "text/markdown"
text = "# My Project\n\n"

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.readme_fragment"
path = "README.md"
start-after = "<!-- start -->\n"
end-before = "\n<!-- end -->"

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.readme_fragment"
path = "CHANGELOG.md"
pattern = "(## .*?)(?=\n## )"
```

Settings (all values are strings):

| Setting        | Required             | Description                                                                                       |
| -------------- | -------------------- | ------------------------------------------------------------------------------------------------- |
| `text`         | one of text/path     | A literal fragment, used verbatim.                                                                |
| `path`         | one of text/path     | A file to read (UTF-8) as the fragment, optionally sliced by the keys below.                      |
| `content-type` | no (`text/markdown`) | The readme content type. Consulted when the first fragment creates the readme.                    |
| `start-after`  | no                   | Drop everything up to and including this marker (file fragments). Excludes `start-at`.            |
| `start-at`     | no                   | Drop everything before this marker, keeping it (file fragments). Excludes `start-after`.          |
| `end-before`   | no                   | Keep everything before this marker (file fragments). Excludes `end-at`.                           |
| `end-at`       | no                   | Keep everything through this marker (file fragments). Excludes `end-before`.                      |
| `pattern`      | no                   | A regex searched with `re.DOTALL`; the fragment becomes its first capture group (file fragments). |

Slicing is applied in order: start, then end, then `pattern`. A missing marker
or a non-matching `pattern` raises a `RuntimeError`.

## `substitute`

`dynamic_metadata.plugins.substitute` applies a single regex substitution to a
field already produced by an earlier entry, the way fancy-pypi-readme touches up
an assembled readme (for example, turning `#123` into a link).

```toml
[[tool.dynamic-metadata]]
provider = "dynamic_metadata.plugins.substitute"
field = "readme"
pattern = "#(\\d+)"
replacement = "[#\\1](https://github.com/org/repo/issues/\\1)"
```

Settings:

| Setting       | Required     | Description                                                 |
| ------------- | ------------ | ----------------------------------------------------------- |
| `field`       | yes          | The field to transform. Must be a scalar field (see below). |
| `pattern`     | yes          | The regex to replace, applied with `re.sub` (every match).  |
| `replacement` | yes          | The replacement; backreferences such as `\1` are supported. |
| `ignore-case` | no (`false`) | Match case-insensitively.                                   |

`field` must be a single-value field — a string field (`version`, `description`,
`requires-python`, `license`) or `readme` — and must already hold a value from
an earlier entry. List and table fields are rejected: the backend _appends_ a
provider's contribution to those, so re-emitting a whole transformed value would
duplicate it. For `readme` the substitution is applied across the table, so
anchor patterns to the body text rather than the content type.

:::{warning}

`substitute` only works on a **dynamic** field produced by an earlier entry. A
field set statically in `[project]` cannot be modified — a scalar field may not
be both static and dynamic (PEP 808), so substituting one is an error.

:::
