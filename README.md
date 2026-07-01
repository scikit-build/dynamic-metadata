# dynamic-metadata

[![Actions Status][actions-badge]][actions-link]
[![Documentation Status][rtd-badge]][rtd-link]

[![PyPI version][pypi-version]][pypi-link]
[![PyPI platforms][pypi-platforms]][pypi-link]

[![GitHub Discussion][github-discussions-badge]][github-discussions-link]

<!-- SPHINX-START -->

> [!WARNING]
>
> This is still a WiP! The design may still change.

`dynamic-metadata` defines a plugin protocol that lets a Python build backend
compute `[project]` fields (version, readme, dependencies, …) at build time.
Plugins are configured as an **ordered array of tables**,
`[[tool.dynamic-metadata]]`, each naming a `provider`. Entries run **in order**,
so a later entry sees every field an earlier entry produced.

A minimal example reads the version out of a file with the bundled `regex`
plugin:

```toml
[build-system]
requires = ["...", "dynamic-metadata"]
build-backend = "..."

[project]
dynamic = ["description", "version"]

[[tool.dynamic-metadata]]
provider = "dynamic_metadata.regex"
field = "version"
input = "src/my_package/__init__.py"
```

Because entries run in order, a later one can reference an earlier result. Here
the `template` plugin builds a description from the name and the version
produced above:

```toml
[[tool.dynamic-metadata]]
provider = "dynamic_metadata.template"
field = "description"
result = "This is {project[name]}, version {project[version]}"
```

Your build backend _must support_ dynamic-metadata for this to work. Build
backends known to support this currently include:

- scikit-build-core (1.0+)

If you have a build backend, it's easy to add support, you don't even need to
depend on this project to do it.

The documentation is split by audience:

- **[For users](https://dynamic-metadata.readthedocs.io/en/latest/users.html)**
  — configure plugins in `pyproject.toml`.
- **[Bundled plugins](https://dynamic-metadata.readthedocs.io/en/latest/plugins.html)**
  — the plugins shipped with this package (`regex`, `template`, `static`,
  `fragment`, `substitute`).
- **[For plugin authors](https://dynamic-metadata.readthedocs.io/en/latest/plugin_authors.html)**
  — implement the hooks; no runtime dependency on this package required.
- **[For backend authors](https://dynamic-metadata.readthedocs.io/en/latest/backend_authors.html)**
  — drive plugins from a build backend by calling the reference loader.
- **[Reimplementing the loader](https://dynamic-metadata.readthedocs.io/en/latest/backend_authors_reimplement.html)**
  — drive plugins without a dependency on this package.

<!-- SPHINX-END -->

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
