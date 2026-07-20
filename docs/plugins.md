# Bundled plugins

This package ships eight plugins. `ast`, `regex`, `template`, `from_file`, and
`substitute` are generic — they read their target from a `field` setting.
`static` writes values straight from its settings; `readme_fragment` and
`pin_installed` are single-purpose and always write `readme` and `dependencies`
respectively. Because they live inside `dynamic-metadata`, you must add
`dynamic-metadata` to your `[build-system].requires` to use them.

Each registers a provider name of `dynamic_metadata.` plus the heading below, so
the `regex` plugin is `provider = "dynamic_metadata.regex"`. The examples use
these names.

Entries run in order and each sees the project resolved so far, so several
entries can cooperate on one field: `readme_fragment` and `substitute` build a
readme the way [hatch-fancy-pypi-readme][] assembles one — one entry per
fragment or substitution rather than a nested list.

[hatch-fancy-pypi-readme]: https://github.com/hynek/hatch-fancy-pypi-readme

## `regex`

`dynamic_metadata.regex` extracts a value from a file with a regular expression.
By default it pulls a version out of a `__version__`/`VERSION` assignment.

```toml
[project]
dynamic = ["version"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.regex"
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

## `ast`

`dynamic_metadata.ast` reads the literal value assigned to a module-level global
in a Python file. The file is parsed with {mod}`ast`, never imported, so it
works without the package (or its dependencies) being importable in the build
environment.

```toml
[project]
dynamic = ["version"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.ast"
field = "version"
input = "src/my_package/__init__.py"
name = "__version__"
```

Settings (all values must be strings):

| Setting | Required | Description                |
| ------- | -------- | -------------------------- |
| `field` | yes      | The metadata field to set. |
| `input` | yes      | The Python file to parse.  |
| `name`  | yes      | The global to read.        |

Only assignments at module scope are considered (including annotated ones like
`__version__: str = "1.2.3"`); if the name is assigned more than once, the last
assignment wins, as it would when executing the file. The value must be a
literal accepted by {func}`ast.literal_eval` — a call like `get_version()` is an
error.

Unlike `regex`, which always extracts a string, the value keeps its Python
shape, so a list or table field can be filled directly — for example
`field = "keywords"` from `KEYWORDS = ["science", "build"]`. Tuples are
converted to lists. The shape must match what the field requires.

## `template`

`dynamic_metadata.template` fills a `str.format` template from fields resolved
by earlier entries, demonstrating cross-field references.

```toml
[[tool.dynamic-metadata]]
provider = "dynamic_metadata.template"
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

## `from_file`

`dynamic_metadata.from_file` fills a field with the contents of a file. The file
is interpreted by the shape of the target field:

- A **string field** gets the file's contents, stripped of surrounding
  whitespace — the classic `VERSION` file.
- A **list field** gets one item per line, requirements.txt-style —
  `dependencies` from a `requirements.txt`.
- A **table field** names the key to fill after a dot in `field`, one entry per
  key: `optional-dependencies.test` fills the `test` extra with one requirement
  per line, and a `urls`/`scripts`/`gui-scripts` key takes the stripped file
  contents like a string field.

```toml
[project]
dynamic = ["version", "dependencies", "optional-dependencies"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.from_file"
field = "version"
path = "VERSION"

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.from_file"
field = "dependencies"
path = "requirements.txt"

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.from_file"
field = "optional-dependencies.test"
path = "requirements-test.txt"
```

Settings (all values must be strings):

| Setting | Required | Description                                                                                        |
| ------- | -------- | -------------------------------------------------------------------------------------------------- |
| `field` | yes      | The metadata field to set; a table field takes the key after a dot (`optional-dependencies.test`). |
| `path`  | yes      | The file to read (UTF-8).                                                                          |

Line parsing follows the requirements.txt conventions: blank lines and `#`
comments (at line start or preceded by whitespace) are dropped, and a trailing
backslash joins a line with the next. pip _options_ (`-r other.txt`, `-e .`,
`--index-url`) are not requirements and raise an error — to combine several
files, use one entry per file: list fields append across entries, entries for
the same extra append, and each extra is its own entry.

Fields whose values aren't flat text — `readme` (use
[`readme_fragment`](#readme_fragment)), `entry-points`, `authors`, and
`maintainers` — are rejected.

## `static`

`dynamic_metadata.static` sets fields directly from its own settings — an
alternative to writing them in `[project]`. Each setting is a metadata field
mapped to its value, returned verbatim.

```toml
[project]
dynamic = ["version", "description"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.static"
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
provider = "dynamic_metadata.static"
version = "1.2.3-beta"

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.substitute"
field = "version"
pattern = "-beta$"
replacement = "b0"
```

It can also keep metadata out of `[project]`, hiding it from tools that read
`[project]` directly.

## `readme_fragment`

`dynamic_metadata.readme_fragment` builds a `readme` from an ordered series of
fragments, each its own entry. Every entry appends to the readme produced by the
entries before it, so a heading, a slice of a file, and a changelog excerpt can
be stitched together. An entry with `text` is a literal fragment; an entry with
`path` reads a file and may slice it.

```toml
[project]
dynamic = ["readme"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.readme_fragment"
content-type = "text/markdown"
text = "# My Project\n\n"

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.readme_fragment"
path = "README.md"
start-after = "<!-- start -->\n"
end-before = "\n<!-- end -->"

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.readme_fragment"
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

## `pin_installed`

`dynamic_metadata.pin_installed` pins runtime dependencies to the version of a
package installed in the build environment. This is the classic
compiled-extension workflow: a wheel built against the pytorch (or historically
numpy) ABI must require a matching version at runtime, and that version is only
known when the wheel is built.

```toml
[project]
dynamic = ["dependencies"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.pin_installed"
packages = ["torch==x.x.*"]
```

Settings:

| Setting    | Required | Description                                                              |
| ---------- | -------- | ------------------------------------------------------------------------ |
| `packages` | yes      | A list of requirement templates, resolved against the build environment. |

Each template is a distribution name followed by a specifier set whose version
components are, dot-separated:

- `x` — the corresponding release component of the installed version (`0` if the
  release is shorter). Epoch, pre/post/dev markers, and local version segments
  (`+cu126`) are ignored.
- `x+N` — that component plus `N`, for an upper bound like `<x+1`.
- `*` — a literal PEP 440 wildcard; only valid as the last component with `==`
  or `!=`.
- a literal number, passed through.

With torch 2.7.1 installed, `"torch==x.x.*"` resolves to `torch==2.7.*`, and
`"numpy>=x.x.x,<x+1"` with numpy 1.26.4 resolves to `numpy>=1.26.4,<2` (the
numpy ABI recommendation). The resolved requirements are appended to any static
`dependencies` (PEP 808).

The plugin implements both optional collection hooks:

- `get_requires_for_dynamic_metadata` requests the bare names, so the packages
  are present to be inspected. Constrain which version is used for the _build_
  in `[build-system].requires` (or by pre-installing with
  `--no-build-isolation`); the plugin pins the _runtime_ requirement to whatever
  was resolved.
- `dynamic_wheel` reports `dependencies` as dynamic, so an SDist's `PKG-INFO`
  marks `Requires-Dist` as `Dynamic` (METADATA 2.2) — the pins legitimately
  differ per build environment, so installers must not trust the SDist's value.

## `substitute`

`dynamic_metadata.substitute` applies a single regex substitution to a field
already produced by an earlier entry, the way fancy-pypi-readme touches up an
assembled readme (for example, turning `#123` into a link).

```toml
[[tool.dynamic-metadata]]
provider = "dynamic_metadata.substitute"
field = "readme"
pattern = "#(\\d+)"
replacement = "[#\\1](https://github.com/org/repo/issues/\\1)"
```

Settings:

| Setting       | Required     | Description                                                       |
| ------------- | ------------ | ----------------------------------------------------------------- |
| `field`       | yes          | The field to transform. Must be a scalar field (see below).       |
| `pattern`     | yes          | The regex to replace, applied with `re.sub` (every match).        |
| `replacement` | yes          | The replacement; backreferences such as `\1` are supported.       |
| `ignore-case` | no (`false`) | Match case-insensitively.                                         |
| `format`      | no (`false`) | Resolve `{project[...]}` references in `replacement` (see below). |

With `format = true`, `replacement` is run through `str.format(project=...)`
before substitution, so it can pull in fields produced by earlier entries — the
same `{project[...]}` syntax as [`template`](#template). Backreferences keep
working alongside it (braces and backslashes don't collide):

```toml
[[tool.dynamic-metadata]]
provider = "dynamic_metadata.substitute"
field = "readme"
pattern = "#(\\d+)"
replacement = "[#\\1](https://github.com/org/repo/v{project[version]}/issues/\\1)"
format = true
```

It is opt-in because formatting makes `{` and `}` special: with `format = true`
a literal brace in the replacement must be doubled (`{{` / `}}`), as with any
`str.format` string. Leave it off (the default) to use the replacement verbatim.

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
