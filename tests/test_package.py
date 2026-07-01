from __future__ import annotations

import json
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import dynamic_metadata.__main__
import dynamic_metadata.loader
import dynamic_metadata.plugins
from dynamic_metadata._compat import metadata as compat_metadata

if TYPE_CHECKING:
    from collections.abc import Callable


def _fake_group(*eps: EntryPoint) -> Callable[[str], list[EntryPoint]]:
    """Stand in for the entry-point shim, serving ``eps`` for the provider group."""
    group = dynamic_metadata.loader.PROVIDER_GROUP
    return lambda name: list(eps) if name == group else []


def _write_provider(plugin_dir: Path, name: str, body: str) -> None:
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / f"{name}.py").write_text(body)


def test_load_provider_path_loads_local(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "local_prov_ok.py").write_text(
        "def dynamic_metadata(settings, project):\n    return {'version': '1.2.3'}\n"
    )

    provider = dynamic_metadata.loader.load_provider("local_prov_ok", str(plugin_dir))
    assert provider.dynamic_metadata({}, {}) == {"version": "1.2.3"}


def test_load_provider_class_is_instantiated(tmp_path: Path) -> None:
    # A "module:Class" provider is imported and instantiated; its hooks are
    # bound methods that may share state through ``self``.
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "class_prov.py").write_text(
        "class Provider:\n"
        "    def dynamic_metadata(self, settings, project):\n"
        "        return {'version': '1.2.3'}\n"
    )

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["version"]},
        [{"provider": {"path": str(plugin_dir), "module": "class_prov:Provider"}}],
        "wheel",
    )

    assert pyproject["version"] == "1.2.3"


def test_load_provider_path_not_shadowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A same-named module reachable via the normal sys.path ...
    other = tmp_path / "other"
    other.mkdir()
    (other / "shadow_prov.py").write_text("WRONG = True\n")
    monkeypatch.syspath_prepend(str(other))

    # ... must not satisfy a provider-path request that does not contain it.
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ModuleNotFoundError):
        dynamic_metadata.loader.load_provider("shadow_prov", str(empty))


def test_template_basic() -> None:
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {
            "name": "test",
            "version": "0.1.0",
            "dynamic": ["requires-python"],
        },
        [
            {
                "provider": "dynamic_metadata.template",
                "field": "requires-python",
                "result": ">={project[version]}",
            },
        ],
        "wheel",
    )

    assert pyproject["requires-python"] == ">=0.1.0"
    assert pyproject["dynamic"] == []


def test_template_order_reads_earlier_result() -> None:
    # Entries run in list order; each later one reads what the earlier produced.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {
            "name": "test",
            "version": "0.1.0",
            "dynamic": ["requires-python", "license", "readme"],
        },
        [
            {
                "provider": "dynamic_metadata.template",
                "field": "requires-python",
                "result": ">={project[version]}",
            },
            {
                "provider": "dynamic_metadata.template",
                "field": "license",
                "result": "{project[requires-python]}",
            },
            {
                "provider": "dynamic_metadata.template",
                "field": "readme",
                "result": {"file": "{project[license]}"},
            },
        ],
        "wheel",
    )

    assert pyproject["requires-python"] == ">=0.1.0"
    assert pyproject["license"] == ">=0.1.0"
    assert pyproject["readme"] == {"file": ">=0.1.0"}
    assert pyproject["dynamic"] == []


def test_forward_reference_raises() -> None:
    # Reading a field that a *later* entry produces is a forward reference: the
    # value is simply not in the project snapshot yet.
    with pytest.raises(KeyError):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["requires-python", "version"]},
            [
                {
                    "provider": "dynamic_metadata.template",
                    "field": "requires-python",
                    "result": ">={project[version]}",
                },
                {
                    "provider": "dynamic_metadata.template",
                    "field": "version",
                    "result": "1.0",
                },
            ],
            "wheel",
        )


def test_multiple_entries_same_field_merge_in_order() -> None:
    # Two entries may target one field; their contributions merge in order.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["dependencies"]},
        [
            {
                "provider": "dynamic_metadata.template",
                "field": "dependencies",
                "result": ["a"],
            },
            {
                "provider": "dynamic_metadata.template",
                "field": "dependencies",
                "result": ["b"],
            },
        ],
        "wheel",
    )

    assert pyproject["dependencies"] == ["a", "b"]
    assert pyproject["dynamic"] == []


def test_scalar_field_second_entry_replaces() -> None:
    # A single-value field can be transformed by a later entry that reads it.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["version"]},
        [
            {
                "provider": "dynamic_metadata.template",
                "field": "version",
                "result": "1.0",
            },
            {
                "provider": "dynamic_metadata.template",
                "field": "version",
                "result": "{project[version]}.post1",
            },
        ],
        "wheel",
    )

    assert pyproject["version"] == "1.0.post1"


def test_provider_sets_multiple_fields(tmp_path: Path) -> None:
    # One entry's fragment may set several fields at once.
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "multi_prov.py").write_text(
        "def dynamic_metadata(settings, project):\n"
        "    return {'version': '1.2.3', 'requires-python': '>=3.8'}\n"
    )

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["version", "requires-python"]},
        [{"provider": {"path": str(plugin_dir), "module": "multi_prov"}}],
        "wheel",
    )

    assert pyproject["version"] == "1.2.3"
    assert pyproject["requires-python"] == ">=3.8"
    assert pyproject["dynamic"] == []


def test_unknown_field_rejected(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "bad_field_prov.py").write_text(
        "def dynamic_metadata(settings, project):\n    return {'not-a-field': 'x'}\n"
    )

    with pytest.raises(KeyError, match="settable"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["version"]},
            [{"provider": {"path": str(plugin_dir), "module": "bad_field_prov"}}],
            "wheel",
        )


def test_field_not_declared_dynamic_rejected(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "undeclared_prov.py").write_text(
        "def dynamic_metadata(settings, project):\n    return {'version': '1.0'}\n"
    )

    with pytest.raises(KeyError, match=r"project\.dynamic"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": []},
            [{"provider": {"path": str(plugin_dir), "module": "undeclared_prov"}}],
            "wheel",
        )


def test_template_entry_points() -> None:
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {
            "name": "test",
            "dynamic": ["version", "entry-points"],
        },
        [
            {
                "provider": "dynamic_metadata.template",
                "field": "version",
                "result": "1.2.3",
            },
            {
                "provider": "dynamic_metadata.template",
                "field": "entry-points",
                "result": {
                    "my_group": {"my_point": "my_app:script_{project[version]}"}
                },
            },
        ],
        "wheel",
    )

    assert pyproject["entry-points"] == {
        "my_group": {"my_point": "my_app:script_1.2.3"}
    }


def test_regex() -> None:
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {
            "name": "test",
            "version": "0.1.0",
            "dynamic": ["requires-python"],
        },
        [
            {
                "provider": "dynamic_metadata.regex",
                "field": "requires-python",
                "input": "pyproject.toml",
                "regex": r"name = \"(?P<name>.+)\"",
                "result": ">={name}",
            },
        ],
        "wheel",
    )

    assert pyproject["requires-python"] == ">=dynamic-metadata"


def test_regex_rejects_unknown_setting() -> None:
    with pytest.raises(RuntimeError, match="settings allowed"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "version": "0.1.0", "dynamic": ["requires-python"]},
            [
                {
                    "provider": "dynamic_metadata.regex",
                    "field": "requires-python",
                    "input": "pyproject.toml",
                    "typo": "oops",
                },
            ],
            "wheel",
        )


def test_build_state_hook_drives_result(tmp_path: Path) -> None:
    # A provider with the optional build_state hook is told the build state
    # before dynamic_metadata, and can drive its result from it: recompute for
    # sdist/wheel, reuse a precomputed value otherwise. A class provider stashes
    # the state on ``self`` for dynamic_metadata to read.
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "build_state_prov.py").write_text(
        "class Provider:\n"
        "    def build_state(self, build_state):\n"
        "        self.build_state = build_state\n"
        "    def dynamic_metadata(self, settings, project):\n"
        "        if self.build_state in {'sdist', 'wheel'}:\n"
        "            return {'version': 'computed'}\n"
        "        return {'version': 'reused'}\n"
    )

    def run(build_state: dynamic_metadata.loader.BuildState) -> Any:
        return dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["version"]},
            [
                {
                    "provider": {
                        "path": str(plugin_dir),
                        "module": "build_state_prov:Provider",
                    },
                },
            ],
            build_state,
        )["version"]

    assert run("sdist") == "computed"
    assert run("wheel") == "computed"
    assert run("metadata_wheel") == "reused"


def test_build_state_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="build_state must be one of"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "version": "0.1.0"},
            [],
            "bdist",  # type: ignore[arg-type]
        )


def test_load_dynamic_metadata_aggregates_requires_and_wheel(
    tmp_path: Path,
) -> None:
    # The backend-author pattern (see docs/backend_authors.md): iterate
    # load_dynamic_metadata and use the runtime-checkable protocols to collect
    # each provider's extra build requirements and METADATA 2.2 dynamic status.
    # A provider implementing neither hook is simply skipped.
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "full_prov.py").write_text(
        "class Provider:\n"
        "    def get_requires_for_dynamic_metadata(self, settings):\n"
        "        return ['some-dep>=1']\n"
        "    def dynamic_wheel(self, settings):\n"
        "        return {'version': False, 'dependencies': True}\n"
        "    def dynamic_metadata(self, settings, project):\n"
        "        return {'version': '1.2.3'}\n"
    )
    (plugin_dir / "bare_prov.py").write_text(
        "def dynamic_metadata(settings, project):\n    return {'description': 'hi'}\n"
    )

    entries = [
        {"provider": {"path": str(plugin_dir), "module": "full_prov:Provider"}},
        {"provider": {"path": str(plugin_dir), "module": "bare_prov"}},
    ]

    requires = []
    dynamic_wheel = {}
    for provider, settings in dynamic_metadata.loader.load_dynamic_metadata(entries):
        if isinstance(
            provider,
            dynamic_metadata.loader.DynamicMetadataRequirementsProtocol,
        ):
            requires += provider.get_requires_for_dynamic_metadata(settings)
        if isinstance(provider, dynamic_metadata.loader.DynamicMetadataWheelProtocol):
            dynamic_wheel.update(provider.dynamic_wheel(settings))

    assert requires == ["some-dep>=1"]
    assert dynamic_wheel == {"version": False, "dependencies": True}


def test_load_dynamic_metadata_requires_provider_key() -> None:
    with pytest.raises(KeyError, match="must set a 'provider'"):
        list(dynamic_metadata.loader.load_dynamic_metadata([{"field": "version"}]))


def test_pep808_extends_static_dependencies() -> None:
    # PEP 808: a field may be both static and dynamic; the provider only adds.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {
            "name": "test",
            "version": "1.2.3",
            "dependencies": ["torch", "packaging"],
            "dynamic": ["dependencies"],
        },
        [
            {
                "provider": "dynamic_metadata.template",
                "field": "dependencies",
                "result": ["numpy>={project[version]}"],
            },
        ],
        "wheel",
    )

    # Static entries are preserved and ordered first; the provider's additions
    # are appended verbatim.
    assert pyproject["dependencies"] == ["torch", "packaging", "numpy>=1.2.3"]
    assert pyproject["dynamic"] == []


def test_pep808_provider_reads_own_static() -> None:
    # A provider may read the static value of the field it is extending.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {
            "name": "test",
            "dependencies": ["a", "b"],
            "dynamic": ["dependencies"],
        },
        [
            {
                "provider": "dynamic_metadata.template",
                "field": "dependencies",
                "result": ["saw:{project[dependencies]}"],
            },
        ],
        "wheel",
    )

    assert pyproject["dependencies"] == ["a", "b", "saw:['a', 'b']"]


@pytest.mark.parametrize(
    ("field", "static", "dynamic", "output"),
    [
        pytest.param(
            "classifiers",
            ["A", "A"],
            ["A", "B"],
            ["A", "A", "A", "B"],
            id="list-str",
        ),
        pytest.param(
            "urls",
            {"Home": "h"},
            {"Docs": "d"},
            {"Home": "h", "Docs": "d"},
            id="dict-str",
        ),
        pytest.param(
            "authors",
            [{"name": "a"}],
            [{"name": "b"}],
            [{"name": "a"}, {"name": "b"}],
            id="list-dict",
        ),
        pytest.param(
            "optional-dependencies",
            {"dev": ["pytest"]},
            {"dev": ["mypy"], "docs": ["sphinx"]},
            {"dev": ["pytest", "mypy"], "docs": ["sphinx"]},
            id="optional-dependencies",
        ),
        pytest.param(
            "entry-points",
            {"grp": {"a": "x"}},
            {"grp": {"b": "y"}, "other": {"c": "z"}},
            {"grp": {"a": "x", "b": "y"}, "other": {"c": "z"}},
            id="entry-points",
        ),
    ],
)
def test_merge_metadata(field: str, static: Any, dynamic: Any, output: Any) -> None:
    assert dynamic_metadata.loader._merge_metadata(field, static, dynamic) == output


def test_merge_metadata_rejects_string_field() -> None:
    with pytest.raises(ValueError, match="both statically and dynamically"):
        dynamic_metadata.loader._merge_metadata("version", "1.0", "2.0")


def test_merge_metadata_rejects_modifying_existing_key() -> None:
    with pytest.raises(ValueError, match="may not modify existing key"):
        dynamic_metadata.loader._merge_metadata(
            "scripts", {"cli": "pkg:main"}, {"cli": "pkg:other"}
        )


@pytest.mark.parametrize(
    ("field", "input", "output"),
    [
        pytest.param("version", "{sub}", "42", id="str"),
        pytest.param("classifiers", ["a", "{sub}"], ["a", "42"], id="list-str"),
        pytest.param(
            "scripts",
            {"a": "{sub}", "{sub}": "b"},
            {"a": "42", "42": "b"},
            id="dict-str",
        ),
        pytest.param(
            "authors", [{"name": "{sub}"}], [{"name": "42"}], id="list-dict-str"
        ),
        pytest.param(
            "optional-dependencies",
            {"dev": ["{sub}"]},
            {"dev": ["42"]},
            id="dict-list-str",
        ),
        pytest.param("readme", {"text": "{sub}"}, {"text": "42"}, id="readme"),
        pytest.param(
            "entry-points",
            {"ep": {"{sub}": "{sub}"}},
            {"ep": {"42": "42"}},
            id="dict-dict-str",
        ),
    ],
)
def test_actions(field: str, input: Any, output: Any) -> None:
    result = dynamic_metadata.plugins._process_dynamic_metadata(
        field, lambda x: x.format(sub=42), input
    )
    assert output == result


def test_cli_show(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "test"\n'
        'version = "0.1.0"\n'
        'dynamic = ["requires-python"]\n'
        "\n"
        "[[tool.dynamic-metadata]]\n"
        'provider = "dynamic_metadata.template"\n'
        'field = "requires-python"\n'
        'result = ">={project[version]}"\n'
    )

    dynamic_metadata.__main__.main(["show", "--pyproject-toml", str(pyproject)])

    project = json.loads(capsys.readouterr().out)
    assert project == {
        "name": "test",
        "version": "0.1.0",
        "requires-python": ">=0.1.0",
        "dynamic": [],
    }


def test_cli_show_no_entries(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # With no [[tool.dynamic-metadata]] entries the static project table is
    # printed verbatim.
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "0.1.0"\n')

    dynamic_metadata.__main__.main(["show", "--pyproject-toml", str(pyproject)])

    project = json.loads(capsys.readouterr().out)
    assert project == {"name": "test", "version": "0.1.0"}


def test_cli_show_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # --state is forwarded to the build_state hook.
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "state_prov.py").write_text(
        "class Provider:\n"
        "    def build_state(self, build_state):\n"
        "        self.build_state = build_state\n"
        "    def dynamic_metadata(self, settings, project):\n"
        "        return {'version': self.build_state}\n"
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "test"\n'
        'dynamic = ["version"]\n'
        "\n"
        "[[tool.dynamic-metadata]]\n"
        f"provider = {{ path = {json.dumps(str(plugin_dir))}, "
        'module = "state_prov:Provider" }\n'
    )

    dynamic_metadata.__main__.main(
        ["show", "--pyproject-toml", str(pyproject), "--state", "sdist"]
    )

    project = json.loads(capsys.readouterr().out)
    assert project["version"] == "sdist"


def test_readme_fragment_text_creates_readme() -> None:
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["readme"]},
        [{"provider": "dynamic_metadata.readme_fragment", "text": "# Hello\n"}],
        "wheel",
    )

    assert pyproject["readme"] == {"content-type": "text/markdown", "text": "# Hello\n"}
    assert pyproject["dynamic"] == []


def test_readme_fragment_appends_in_order() -> None:
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["readme"]},
        [
            {
                "provider": "dynamic_metadata.readme_fragment",
                "text": "# Title\n\n",
            },
            {"provider": "dynamic_metadata.readme_fragment", "text": "Body.\n"},
        ],
        "wheel",
    )

    assert pyproject["readme"] == {
        "content-type": "text/markdown",
        "text": "# Title\n\nBody.\n",
    }


def test_readme_fragment_content_type_carried() -> None:
    # The creating fragment sets content-type; later fragments keep it.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["readme"]},
        [
            {
                "provider": "dynamic_metadata.readme_fragment",
                "content-type": "text/x-rst",
                "text": "Title\n",
            },
            {"provider": "dynamic_metadata.readme_fragment", "text": "more\n"},
        ],
        "wheel",
    )

    assert pyproject["readme"] == {
        "content-type": "text/x-rst",
        "text": "Title\nmore\n",
    }


def test_readme_fragment_file_start_after_end_before(tmp_path: Path) -> None:
    src = tmp_path / "README.md"
    src.write_text("intro\n<!-- start -->\nkeep me\n<!-- end -->\noutro\n")

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["readme"]},
        [
            {
                "provider": "dynamic_metadata.readme_fragment",
                "path": str(src),
                "start-after": "<!-- start -->\n",
                "end-before": "<!-- end -->",
            }
        ],
        "wheel",
    )

    assert pyproject["readme"]["text"] == "keep me\n"


def test_readme_fragment_file_start_at_end_at(tmp_path: Path) -> None:
    src = tmp_path / "f.md"
    src.write_text("AAA## Heading\nbody\nEND tail")

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["readme"]},
        [
            {
                "provider": "dynamic_metadata.readme_fragment",
                "path": str(src),
                "start-at": "## Heading",
                "end-at": "END",
            }
        ],
        "wheel",
    )

    assert pyproject["readme"]["text"] == "## Heading\nbody\nEND"


def test_readme_fragment_file_pattern(tmp_path: Path) -> None:
    src = tmp_path / "CHANGELOG.md"
    src.write_text("## 1.0\nlatest\n## 0.9\nold\n")

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["readme"]},
        [
            {
                "provider": "dynamic_metadata.readme_fragment",
                "path": str(src),
                "pattern": r"(## 1\.0.*?)(?=\n## )",
            }
        ],
        "wheel",
    )

    assert pyproject["readme"]["text"] == "## 1.0\nlatest"


def test_readme_fragment_rejects_text_and_path() -> None:
    with pytest.raises(RuntimeError, match="exactly one of 'text' or 'path'"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["readme"]},
            [
                {
                    "provider": "dynamic_metadata.readme_fragment",
                    "text": "x",
                    "path": "y",
                }
            ],
            "wheel",
        )


def test_readme_fragment_rejects_neither() -> None:
    with pytest.raises(RuntimeError, match="must set 'text' or 'path'"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["readme"]},
            [{"provider": "dynamic_metadata.readme_fragment"}],
            "wheel",
        )


def test_readme_fragment_rejects_slicing_without_path() -> None:
    with pytest.raises(RuntimeError, match="Slicing settings require 'path'"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["readme"]},
            [
                {
                    "provider": "dynamic_metadata.readme_fragment",
                    "text": "x",
                    "start-after": "y",
                }
            ],
            "wheel",
        )


def test_readme_fragment_rejects_both_starts(tmp_path: Path) -> None:
    src = tmp_path / "f.md"
    src.write_text("abc")
    with pytest.raises(RuntimeError, match="both 'start-after' and 'start-at'"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["readme"]},
            [
                {
                    "provider": "dynamic_metadata.readme_fragment",
                    "path": str(src),
                    "start-after": "a",
                    "start-at": "b",
                }
            ],
            "wheel",
        )


def test_readme_fragment_missing_marker(tmp_path: Path) -> None:
    src = tmp_path / "f.md"
    src.write_text("nothing to see")
    with pytest.raises(RuntimeError, match="Could not find 'start-after'"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["readme"]},
            [
                {
                    "provider": "dynamic_metadata.readme_fragment",
                    "path": str(src),
                    "start-after": "absent",
                }
            ],
            "wheel",
        )


def test_readme_fragment_rejects_unknown_setting() -> None:
    with pytest.raises(RuntimeError, match="settings allowed"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["readme"]},
            [
                {
                    "provider": "dynamic_metadata.readme_fragment",
                    "text": "x",
                    "typo": "oops",
                }
            ],
            "wheel",
        )


def test_substitute_readme() -> None:
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["readme"]},
        [
            {
                "provider": "dynamic_metadata.readme_fragment",
                "text": "see #42 now\n",
            },
            {
                "provider": "dynamic_metadata.substitute",
                "field": "readme",
                "pattern": r"#(\d+)",
                "replacement": r"[#\1](https://x/\1)",
            },
        ],
        "wheel",
    )

    assert pyproject["readme"]["text"] == "see [#42](https://x/42) now\n"


def test_substitute_str_field() -> None:
    # substitute transforms a string field produced by an earlier entry.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "version": "0.1.0", "dynamic": ["description"]},
        [
            {
                "provider": "dynamic_metadata.template",
                "field": "description",
                "result": "Version {project[version]}",
            },
            {
                "provider": "dynamic_metadata.substitute",
                "field": "description",
                "pattern": "Version",
                "replacement": "v",
            },
        ],
        "wheel",
    )

    assert pyproject["description"] == "v 0.1.0"


def test_substitute_format_references_field() -> None:
    # With format=true, the replacement pulls in another field via {project[...]}.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "version": "1.2.3", "dynamic": ["description"]},
        [
            {
                "provider": "dynamic_metadata.template",
                "field": "description",
                "result": "placeholder",
            },
            {
                "provider": "dynamic_metadata.substitute",
                "field": "description",
                "pattern": "placeholder",
                "replacement": "v{project[version]}",
                "format": True,
            },
        ],
        "wheel",
    )

    assert pyproject["description"] == "v1.2.3"


def test_substitute_format_with_backreference() -> None:
    # A regex backreference and a {project[...]} reference coexist in one
    # replacement: braces and backslashes use disjoint syntax.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "version": "1.2.3", "dynamic": ["description"]},
        [
            {
                "provider": "dynamic_metadata.template",
                "field": "description",
                "result": "#42",
            },
            {
                "provider": "dynamic_metadata.substitute",
                "field": "description",
                "pattern": r"#(\d+)",
                "replacement": r"{project[version]}-\1",
                "format": True,
            },
        ],
        "wheel",
    )

    assert pyproject["description"] == "1.2.3-42"


def test_substitute_no_format_keeps_braces_literal() -> None:
    # Default (format off): literal braces in the replacement pass through and
    # are not treated as a format string. This is why format is opt-in.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["description"]},
        [
            {
                "provider": "dynamic_metadata.template",
                "field": "description",
                "result": "placeholder",
            },
            {
                "provider": "dynamic_metadata.substitute",
                "field": "description",
                "pattern": "placeholder",
                "replacement": "x{y}z",
            },
        ],
        "wheel",
    )

    assert pyproject["description"] == "x{y}z"


def test_substitute_format_rejects_non_bool() -> None:
    with pytest.raises(RuntimeError, match="'format' must be a boolean"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["description"]},
            [
                {
                    "provider": "dynamic_metadata.template",
                    "field": "description",
                    "result": "placeholder",
                },
                {
                    "provider": "dynamic_metadata.substitute",
                    "field": "description",
                    "pattern": "placeholder",
                    "replacement": "x",
                    "format": "yes",
                },
            ],
            "wheel",
        )


def test_substitute_ignore_case() -> None:
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["readme"]},
        [
            {
                "provider": "dynamic_metadata.readme_fragment",
                "text": "Hello HELLO\n",
            },
            {
                "provider": "dynamic_metadata.substitute",
                "field": "readme",
                "pattern": "hello",
                "replacement": "hi",
                "ignore-case": True,
            },
        ],
        "wheel",
    )

    assert pyproject["readme"]["text"] == "hi hi\n"


def test_substitute_rejects_non_scalar() -> None:
    with pytest.raises(RuntimeError, match="cannot be substituted"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["keywords"]},
            [
                {
                    "provider": "dynamic_metadata.substitute",
                    "field": "keywords",
                    "pattern": "a",
                    "replacement": "b",
                }
            ],
            "wheel",
        )


def test_substitute_requires_existing_value() -> None:
    with pytest.raises(RuntimeError, match="must be produced by an earlier entry"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["readme"]},
            [
                {
                    "provider": "dynamic_metadata.substitute",
                    "field": "readme",
                    "pattern": "a",
                    "replacement": "b",
                }
            ],
            "wheel",
        )


def test_substitute_rejects_unknown_setting() -> None:
    with pytest.raises(RuntimeError, match="settings allowed"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["readme"]},
            [
                {
                    "provider": "dynamic_metadata.readme_fragment",
                    "text": "hi\n",
                },
                {
                    "provider": "dynamic_metadata.substitute",
                    "field": "readme",
                    "pattern": "a",
                    "replacement": "b",
                    "typo": "oops",
                },
            ],
            "wheel",
        )


def test_static_sets_fields() -> None:
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["version", "description", "keywords"]},
        [
            {
                "provider": "dynamic_metadata.static",
                "version": "1.2.3",
                "description": "My package",
                "keywords": ["a", "b"],
            }
        ],
        "wheel",
    )

    assert pyproject["version"] == "1.2.3"
    assert pyproject["description"] == "My package"
    assert pyproject["keywords"] == ["a", "b"]
    assert pyproject["dynamic"] == []


def test_static_then_substitute() -> None:
    # The main use: static gives substitute a dynamic value to transform.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["version"]},
        [
            {
                "provider": "dynamic_metadata.static",
                "version": "1.2.3-beta",
            },
            {
                "provider": "dynamic_metadata.substitute",
                "field": "version",
                "pattern": "-beta$",
                "replacement": "b0",
            },
        ],
        "wheel",
    )

    assert pyproject["version"] == "1.2.3b0"


def test_static_rejects_unknown_field() -> None:
    with pytest.raises(KeyError, match="not a settable dynamic-metadata field"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["version"]},
            [
                {
                    "provider": "dynamic_metadata.static",
                    "descriptions": "typo",
                }
            ],
            "wheel",
        )


def test_static_field_must_be_dynamic() -> None:
    with pytest.raises(KeyError, match=r"must be listed in project\.dynamic"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": []},
            [
                {
                    "provider": "dynamic_metadata.static",
                    "version": "1.2.3",
                }
            ],
            "wheel",
        )


def test_regex_short_name() -> None:
    # The bundled plugins are registered under dynamic_metadata-prefixed names,
    # so the registered name resolves via the entry-point group to the module.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "version": "0.1.0", "dynamic": ["requires-python"]},
        [
            {
                "provider": "dynamic_metadata.regex",
                "field": "requires-python",
                "input": "pyproject.toml",
                "regex": r"name = \"(?P<name>.+)\"",
                "result": ">={name}",
            },
        ],
        "wheel",
    )

    assert pyproject["requires-python"] == ">=dynamic-metadata"


def test_entry_point_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_provider(
        tmp_path,
        "ep_mod",
        "def dynamic_metadata(settings, project):\n    return {'version': '1.0'}\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(
        compat_metadata,
        "entry_points",
        _fake_group(
            EntryPoint("mymod", "ep_mod", dynamic_metadata.loader.PROVIDER_GROUP)
        ),
    )

    provider = dynamic_metadata.loader.load_provider("mymod")
    assert provider.dynamic_metadata({}, {}) == {"version": "1.0"}


def test_entry_point_class_is_instantiated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_provider(
        tmp_path,
        "ep_cls",
        "class Provider:\n"
        "    def dynamic_metadata(self, settings, project):\n"
        "        return {'version': '2.0'}\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(
        compat_metadata,
        "entry_points",
        _fake_group(
            EntryPoint("cls", "ep_cls:Provider", dynamic_metadata.loader.PROVIDER_GROUP)
        ),
    )

    import ep_cls  # type: ignore[import-not-found]  # noqa: PLC0415

    provider = dynamic_metadata.loader.load_provider("cls")
    assert isinstance(provider, ep_cls.Provider)


def test_entry_point_instance_not_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An entry point may point at an already-instantiated object; it is used as
    # is rather than called (a class would be instantiated).
    _write_provider(
        tmp_path,
        "ep_inst",
        "class Provider:\n"
        "    def dynamic_metadata(self, settings, project):\n"
        "        return {'version': '3.0'}\n"
        "INSTANCE = Provider()\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(
        compat_metadata,
        "entry_points",
        _fake_group(
            EntryPoint(
                "inst", "ep_inst:INSTANCE", dynamic_metadata.loader.PROVIDER_GROUP
            )
        ),
    )

    import ep_inst  # type: ignore[import-not-found]  # noqa: PLC0415

    provider = dynamic_metadata.loader.load_provider("inst")
    assert provider is ep_inst.INSTANCE


def test_entry_point_used_not_raw_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without provider-path, a name is resolved through the entry-point group
    # only; a same-named importable module is never imported directly.
    _write_provider(
        tmp_path,
        "winning",
        "def dynamic_metadata(settings, project):\n    return {'version': 'ep'}\n",
    )
    _write_provider(
        tmp_path,
        "collide",
        "def dynamic_metadata(settings, project):\n    return {'version': 'module'}\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(
        compat_metadata,
        "entry_points",
        _fake_group(
            EntryPoint("collide", "winning", dynamic_metadata.loader.PROVIDER_GROUP)
        ),
    )

    provider = dynamic_metadata.loader.load_provider("collide")
    assert provider.dynamic_metadata({}, {}) == {"version": "ep"}


def test_raw_import_rejected_without_provider_path() -> None:
    # The module-path form requires the inline table: an importable module that
    # is not a registered entry point is not accepted as a bare string.
    with pytest.raises(ModuleNotFoundError, match="Unknown provider"):
        dynamic_metadata.loader.load_provider("dynamic_metadata.plugins.regex")


def test_provider_inline_table_local(tmp_path: Path) -> None:
    # The inline table {path, module} imports a local plugin from a directory.
    _write_provider(
        tmp_path,
        "inline_prov",
        "def dynamic_metadata(settings, project):\n    return {'version': '9.9'}\n",
    )

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["version"]},
        [{"provider": {"path": str(tmp_path), "module": "inline_prov"}}],
        "wheel",
    )

    assert pyproject["version"] == "9.9"


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param({"module": "x"}, id="missing-path"),
        pytest.param({"path": "x"}, id="missing-module"),
        pytest.param({"path": "x", "module": "y", "extra": "z"}, id="extra-key"),
        pytest.param(42, id="wrong-type"),
    ],
)
def test_provider_inline_table_rejects_bad_shape(spec: Any) -> None:
    with pytest.raises(ValueError, match="inline table with exactly"):
        list(dynamic_metadata.loader.load_dynamic_metadata([{"provider": spec}]))


def test_entry_point_duplicate_name_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = dynamic_metadata.loader.PROVIDER_GROUP
    monkeypatch.setattr(
        compat_metadata,
        "entry_points",
        _fake_group(
            EntryPoint("dup", "a.mod", group),
            EntryPoint("dup", "b.mod", group),
        ),
    )

    with pytest.raises(ValueError, match="multiple distributions"):
        dynamic_metadata.loader.load_provider("dup")


def test_entry_point_load_failure_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = dynamic_metadata.loader.PROVIDER_GROUP
    monkeypatch.setattr(
        compat_metadata,
        "entry_points",
        _fake_group(EntryPoint("broken", "no_such_module_xyz", group)),
    )

    with pytest.raises(ImportError, match="Could not load provider 'broken'"):
        dynamic_metadata.loader.load_provider("broken")


def test_provider_path_ignores_entry_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # provider-path forces a raw import; a registered entry point of the same
    # name is not consulted.
    _write_provider(
        tmp_path,
        "local",
        "def dynamic_metadata(settings, project):\n    return {'version': 'local'}\n",
    )
    monkeypatch.setattr(
        compat_metadata,
        "entry_points",
        _fake_group(
            EntryPoint(
                "local",
                "dynamic_metadata.plugins.static",
                dynamic_metadata.loader.PROVIDER_GROUP,
            )
        ),
    )

    provider = dynamic_metadata.loader.load_provider("local", str(tmp_path))
    assert provider.dynamic_metadata({}, {}) == {"version": "local"}


def test_unknown_provider_suggests(monkeypatch: pytest.MonkeyPatch) -> None:
    group = dynamic_metadata.loader.PROVIDER_GROUP
    monkeypatch.setattr(
        compat_metadata,
        "entry_points",
        _fake_group(EntryPoint("regex", "dynamic_metadata.plugins.regex", group)),
    )

    with pytest.raises(ModuleNotFoundError, match="did you mean 'regex'"):
        dynamic_metadata.loader.load_provider("regx")


def test_list_providers_includes_bundled() -> None:
    providers = dynamic_metadata.loader.list_providers()
    assert "dynamic_metadata.regex" in providers
    assert "dynamic_metadata.plugins.regex" in providers["dynamic_metadata.regex"]


def test_cli_providers(capsys: pytest.CaptureFixture[str]) -> None:
    dynamic_metadata.__main__.main(["providers"])
    out = capsys.readouterr().out
    assert "dynamic_metadata.regex" in out
    assert "dynamic_metadata.template" in out
