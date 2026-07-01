# Agent instructions

## What this is

A specification and reference implementation for **dynamic metadata plugins**
for Python build backends, initially supporting scikit-build-core (see issue
#230). It defines a plugin protocol that lets a build backend compute
`[project]` fields (version, readme, dependencies, etc.) at build time. Design
is still WiP and may change.

The library is split into three audiences (see README.md):

- **Users** configure plugins as an ordered array of tables,
  `[[tool.dynamic-metadata]]`, each with a `provider`: either a registered
  entry-point name (string) or an inline table `{path, module}` for a local
  plugin. Entries run in order.
- **Plugin authors** implement the hooks; they do _not_ need to depend on this
  package at runtime.
- **Backend authors** consume `loader.py` to drive plugins; they also do not
  need a runtime dependency.

## Commands

Uses [nox](https://nox.thea.codes) for everything; sessions create their own
venvs.

```bash
nox                          # lint + tests on all installed Pythons
nox -s tests                 # pytest
nox -s tests -- --cov        # with coverage
nox -s lint                  # pre-commit on all files
nox -s pylint                # pylint (installed into pkg env, slower than pre-commit)
nox -s docs -- --serve       # build + serve docs

uv run pytest                # run tests directly in the dev env
uv run pytest tests/test_package.py::test_regex   # single test
prek -a --quiet              # lint (preferred over `pre-commit run -a`)
```

`mypy` runs in `--strict` mode (config in `pyproject.toml`);
`src/dynamic_metadata.*` additionally requires fully typed defs. Pytest treats
warnings as errors and uses `--strict-markers --strict-config`.

## Architecture

### The plugin protocol

A `provider` entry is one of two shapes, parsed by `_provider_location` and
loaded by `load_provider(module, provider_path=None)`. A **string** is a name in
the `dynamic_metadata.provider` entry-point group (bundled plugins register
there — see `pyproject.toml`, names prefixed `dynamic_metadata.`; third-party
plugins should prefix with their own package). An **inline table**
`{path, module}` is a local import (loose in-project scripts) — there is no
bare-import fallback. A duplicate name across distributions is a hard error. The
loaded object is used per kind: module as-is, class instantiated with no args
(hooks are bound methods sharing state via `self`), instance used directly.
`list_providers()` enumerates names (also `dynamic-metadata providers`). The one
required hook is `dynamic_metadata(settings, project) -> dict[str, Any]`. It
returns a fragment of the `[project]` table (`{field: value, ...}`), so one
plugin may set several fields. Three optional hooks:
`build_state(build_state) -> None` (called once before `dynamic_metadata` with
the current build state — a provider that cares stashes it, typically on `self`;
the loader detects it via
`isinstance(provider, DynamicMetadataBuildStateProtocol)`),
`dynamic_wheel(settings) -> dict[str, bool]` (per-field METADATA 2.2 dynamic
status; version must be false) and
`get_requires_for_dynamic_metadata(settings) -> list[str]` (extra build
requirements). Protocols are defined in `loader.py` (`DynamicMetadataProtocol`
and subclasses). There is no `field` argument: generic plugins (`regex`,
`template`) read their target from a `field` setting; single-purpose plugins
hardcode it.

### Field taxonomy — `info.py`

`info.py` is the single source of truth for which `[project]` fields can be
dynamic and what _shape_ their value has: `STR_FIELDS`, `LIST_STR_FIELDS`,
`DICT_STR_FIELDS`, `LIST_DICT_FIELDS`, plus special-cased `readme`,
`entry-points`, `optional-dependencies`. `name` and `dynamic` are intentionally
excluded. `ALL_FIELDS` is the union and is what `loader.py` validates against.

### Ordered resolution — `loader.py`

`process_dynamic_metadata(project, entries, build_state)` is the entry point.
`entries` is the **ordered list** of `[[tool.dynamic-metadata]]` tables. It
builds a plain `dict` and applies entries in order: each provider gets a
read-only `MappingProxyType` snapshot of the project resolved so far, so a later
entry reads an earlier one's result with `project[...]` (a forward reference is
just a `KeyError`; cycles are structurally impossible). The returned fragment is
merged per field by `_merge_metadata` — lists append, tables add keys (PEP 808
add-only), and a single-value field is replaced if a later entry targets it (a
`produced` set distinguishes a prior entry's result from a static value, which
for a scalar is the rejected static+dynamic case). Each resolved field is
removed from `dynamic`.

### Shared value-shaping helper — `plugins/__init__.py`

`_process_dynamic_metadata(field, action, result)` applies a string-transform
`action` across whatever container shape `field` requires (string, list, dict,
dict-of-lists, etc.), validating the shape against `info.py`. Bundled plugins
(`regex`, `template`) call this so they only write the transform once and get
correct behavior for every field type. This is the helper plugin authors are
encouraged to reuse or vendor.

### Bundled plugins — `plugins/`

- `regex.py` — extract a value from a file via regex (default targets
  `__version__`/`VERSION`).
- `template.py` — `str.format` substitution using `{project[...]}`,
  demonstrating cross-field references (reading earlier entries' results).

### Schema — `schema.py` + `resources/toml_schema.json`

`get_schema()` is exposed as a `validate_pyproject.tool_schema` entry point so
`[tool.dynamic-metadata]` is validated against the bundled JSON schema.

### Compat

`_compat/tomllib.py` shims `tomllib`/`tomli` (<3.11). `requires-python >=3.8`;
keep code 3.8-compatible (note `from __future__ import annotations` is required
by ruff isort config in every module).
