# Agent instructions

## What this is

A specification and reference implementation for **dynamic metadata plugins**
for Python build backends, initially supporting scikit-build-core (see issue
#230). It defines a plugin protocol that lets a build backend compute
`[project]` fields (version, readme, dependencies, etc.) at build time. Design
is still WiP and may change.

The library is split into three audiences (see README.md):

- **Users** configure plugins under `[tool.dynamic-metadata.<field-name>]` with
  a `provider` (module path) and optional `provider-path` (local dir).
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

A plugin is any module exposing
`dynamic_metadata(field, settings, project) -> value`. Two optional hooks:
`dynamic_wheel(field, settings) -> bool` (METADATA 2.2 dynamic status; version
must be false) and `get_requires_for_dynamic_metadata(settings) -> list[str]`
(extra build requirements). Protocols are defined in `loader.py`
(`DynamicMetadataProtocol` and subclasses).

### Field taxonomy — `info.py`

`info.py` is the single source of truth for which `[project]` fields can be
dynamic and what _shape_ their value has: `STR_FIELDS`, `LIST_STR_FIELDS`,
`DICT_STR_FIELDS`, `LIST_DICT_FIELDS`, plus special-cased `readme`,
`entry-points`, `optional-dependencies`. `name` and `dynamic` are intentionally
excluded. `ALL_FIELDS` is the union and is what `loader.py` validates against.

### Lazy, ordered resolution — `loader.py`

`process_dynamic_metadata(project, metadata)` is the entry point. The key design
is `DynamicPyProject`, a `Mapping` that resolves providers **lazily on
`__getitem__`**. This lets one plugin request another field via
`project["other-field"]`; the dependency is computed on demand and removed from
`dynamic`. Resolution order is therefore data-driven, not declaration order (see
`test_template_needs`). Circular/missing dependencies are detected because a
provider is `pop`-ed from `self.providers` before it runs — a re-entrant request
for a not-yet-resolved, no-longer-pending key raises.

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
  demonstrating cross-field references.
- `setuptools_scm.py` / `fancy_pypi_readme.py` — wrap external tools; both
  lazy-import their dependency inside the hook and declare it via
  `get_requires_for_dynamic_metadata`.

### Schema — `schema.py` + `resources/toml_schema.json`

`get_schema()` is exposed as a `validate_pyproject.tool_schema` entry point so
`[tool.dynamic-metadata]` is validated against the bundled JSON schema.

### Compat

`_compat/tomllib.py` shims `tomllib`/`tomli` (<3.11). `requires-python >=3.8`;
keep code 3.8-compatible (note `from __future__ import annotations` is required
by ruff isort config in every module).
