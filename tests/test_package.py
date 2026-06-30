from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import dynamic_metadata.__main__
import dynamic_metadata.loader
import dynamic_metadata.plugins


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
        [{"provider": "class_prov:Provider", "provider-path": str(plugin_dir)}],
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
                "provider": "dynamic_metadata.plugins.template",
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
                "provider": "dynamic_metadata.plugins.template",
                "field": "requires-python",
                "result": ">={project[version]}",
            },
            {
                "provider": "dynamic_metadata.plugins.template",
                "field": "license",
                "result": "{project[requires-python]}",
            },
            {
                "provider": "dynamic_metadata.plugins.template",
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
                    "provider": "dynamic_metadata.plugins.template",
                    "field": "requires-python",
                    "result": ">={project[version]}",
                },
                {
                    "provider": "dynamic_metadata.plugins.template",
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
                "provider": "dynamic_metadata.plugins.template",
                "field": "dependencies",
                "result": ["a"],
            },
            {
                "provider": "dynamic_metadata.plugins.template",
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
                "provider": "dynamic_metadata.plugins.template",
                "field": "version",
                "result": "1.0",
            },
            {
                "provider": "dynamic_metadata.plugins.template",
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
        [{"provider": "multi_prov", "provider-path": str(plugin_dir)}],
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
            [{"provider": "bad_field_prov", "provider-path": str(plugin_dir)}],
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
            [{"provider": "undeclared_prov", "provider-path": str(plugin_dir)}],
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
                "provider": "dynamic_metadata.plugins.template",
                "field": "version",
                "result": "1.2.3",
            },
            {
                "provider": "dynamic_metadata.plugins.template",
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
                "provider": "dynamic_metadata.plugins.regex",
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
                    "provider": "dynamic_metadata.plugins.regex",
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
                    "provider": "build_state_prov:Provider",
                    "provider-path": str(plugin_dir),
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
        {"provider": "full_prov:Provider", "provider-path": str(plugin_dir)},
        {"provider": "bare_prov", "provider-path": str(plugin_dir)},
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
                "provider": "dynamic_metadata.plugins.template",
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
                "provider": "dynamic_metadata.plugins.template",
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
        'provider = "dynamic_metadata.plugins.template"\n'
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
        'provider = "state_prov:Provider"\n'
        f"provider-path = {json.dumps(str(plugin_dir))}\n"
    )

    dynamic_metadata.__main__.main(
        ["show", "--pyproject-toml", str(pyproject), "--state", "sdist"]
    )

    project = json.loads(capsys.readouterr().out)
    assert project["version"] == "sdist"
