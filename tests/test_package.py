from __future__ import annotations

import importlib.metadata
import json
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import dynamic_metadata.__main__
import dynamic_metadata.discovery
import dynamic_metadata.errors
import dynamic_metadata.loader
import dynamic_metadata.plugins
import dynamic_metadata.protocols
from dynamic_metadata._compat import metadata as compat_metadata

if TYPE_CHECKING:
    from collections.abc import Callable


def _fake_group(*eps: EntryPoint) -> Callable[[str], list[EntryPoint]]:
    """Stand in for the entry-point shim, serving ``eps`` for the provider group."""
    group = dynamic_metadata.loader.PROVIDER_GROUP
    return lambda name: list(eps) if name == group else []


def _write_provider(plugin_dir: Path, name: str, body: str) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / f"{name}.py").write_text(body)


def test_load_provider_path_loads_local(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "local_prov_ok.py").write_text(
        "def dynamic_metadata(settings, project):\n    return {'version': '1.2.3'}\n"
    )

    provider = dynamic_metadata.loader.load_provider(
        {"path": str(plugin_dir), "module": "local_prov_ok"}
    )
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
        dynamic_metadata.loader.load_provider(
            {"path": str(empty), "module": "shadow_prov"}
        )


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

    with pytest.raises(dynamic_metadata.errors.InvalidFieldError, match="settable"):
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

    with pytest.raises(
        dynamic_metadata.errors.InvalidFieldError, match=r"project\.dynamic"
    ):
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


def test_ast_version(tmp_path: Path) -> None:
    (tmp_path / "version.py").write_text('__version__ = "1.2.3"\n')

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["version"]},
        [
            {
                "provider": "dynamic_metadata.ast",
                "field": "version",
                "input": str(tmp_path / "version.py"),
                "name": "__version__",
            },
        ],
        "wheel",
    )

    assert pyproject["version"] == "1.2.3"


def test_ast_last_assignment_wins(tmp_path: Path) -> None:
    (tmp_path / "version.py").write_text(
        '__version__: str = "0.1"\n__version__ = "0.2"\n'
    )

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["version"]},
        [
            {
                "provider": "dynamic_metadata.ast",
                "field": "version",
                "input": str(tmp_path / "version.py"),
                "name": "__version__",
            },
        ],
        "wheel",
    )

    assert pyproject["version"] == "0.2"


def test_ast_list_field_from_tuple(tmp_path: Path) -> None:
    (tmp_path / "meta.py").write_text('KEYWORDS = ("science", "build")\n')

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "version": "0.1.0", "dynamic": ["keywords"]},
        [
            {
                "provider": "dynamic_metadata.ast",
                "field": "keywords",
                "input": str(tmp_path / "meta.py"),
                "name": "KEYWORDS",
            },
        ],
        "wheel",
    )

    assert pyproject["keywords"] == ["science", "build"]


def test_ast_missing_name_raises(tmp_path: Path) -> None:
    (tmp_path / "version.py").write_text('other = "1.0"\n')

    with pytest.raises(RuntimeError, match="Couldn't find a global assignment"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["version"]},
            [
                {
                    "provider": "dynamic_metadata.ast",
                    "field": "version",
                    "input": str(tmp_path / "version.py"),
                    "name": "__version__",
                },
            ],
            "wheel",
        )


def test_ast_non_literal_raises(tmp_path: Path) -> None:
    (tmp_path / "version.py").write_text("__version__ = get_version()\n")

    with pytest.raises(RuntimeError, match="not a literal constant"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["version"]},
            [
                {
                    "provider": "dynamic_metadata.ast",
                    "field": "version",
                    "input": str(tmp_path / "version.py"),
                    "name": "__version__",
                },
            ],
            "wheel",
        )


def test_ast_requires_name(tmp_path: Path) -> None:
    (tmp_path / "version.py").write_text('__version__ = "1.2.3"\n')

    with pytest.raises(RuntimeError, match="'name' setting"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["version"]},
            [
                {
                    "provider": "dynamic_metadata.ast",
                    "field": "version",
                    "input": str(tmp_path / "version.py"),
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

    def run(build_state: dynamic_metadata.protocols.BuildState) -> Any:
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


def test_get_requires_for_dynamic_metadata(tmp_path: Path) -> None:
    # Requirements are collected in entry order; a provider without the hook is
    # simply skipped.
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "req_prov.py").write_text(
        "class Provider:\n"
        "    def get_requires_for_dynamic_metadata(self, settings):\n"
        "        return ['some-dep>=1']\n"
        "    def dynamic_metadata(self, settings, project):\n"
        "        return {'version': '1.2.3'}\n"
    )
    (plugin_dir / "bare_prov.py").write_text(
        "def dynamic_metadata(settings, project):\n    return {'description': 'hi'}\n"
    )
    (plugin_dir / "req_prov2.py").write_text(
        "def get_requires_for_dynamic_metadata(settings):\n"
        "    return ['other-dep']\n"
        "def dynamic_metadata(settings, project):\n"
        "    return {'description': 'hi'}\n"
    )

    requires = dynamic_metadata.loader.get_requires_for_dynamic_metadata(
        [
            {"provider": {"path": str(plugin_dir), "module": "req_prov:Provider"}},
            {"provider": {"path": str(plugin_dir), "module": "bare_prov"}},
            {"provider": {"path": str(plugin_dir), "module": "req_prov2"}},
        ]
    )

    assert requires == ["some-dep>=1", "other-dep"]


def test_dynamic_wheel_fields(tmp_path: Path) -> None:
    # Only fields reported True are dynamic; unmentioned fields (and providers
    # without the hook) default to not dynamic.
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "wheel_prov.py").write_text(
        "class Provider:\n"
        "    def dynamic_wheel(self, settings):\n"
        "        return {'version': False, 'dependencies': True}\n"
        "    def dynamic_metadata(self, settings, project):\n"
        "        return {'version': '1.2.3', 'dependencies': ['numpy']}\n"
    )
    (plugin_dir / "bare_prov.py").write_text(
        "def dynamic_metadata(settings, project):\n    return {'description': 'hi'}\n"
    )

    fields = dynamic_metadata.loader.dynamic_wheel_fields(
        [
            {"provider": {"path": str(plugin_dir), "module": "wheel_prov:Provider"}},
            {"provider": {"path": str(plugin_dir), "module": "bare_prov"}},
        ]
    )

    assert fields == {"dependencies"}


def test_dynamic_wheel_fields_any_true_wins(tmp_path: Path) -> None:
    # Contributions to a field merge, so it is dynamic if *any* provider says
    # so; a later False does not retract an earlier True.
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "wheel_true.py").write_text(
        "def dynamic_wheel(settings):\n"
        "    return {'dependencies': True}\n"
        "def dynamic_metadata(settings, project):\n"
        "    return {'dependencies': ['a']}\n"
    )
    (plugin_dir / "wheel_false.py").write_text(
        "def dynamic_wheel(settings):\n"
        "    return {'dependencies': False}\n"
        "def dynamic_metadata(settings, project):\n"
        "    return {'dependencies': ['b']}\n"
    )

    fields = dynamic_metadata.loader.dynamic_wheel_fields(
        [
            {"provider": {"path": str(plugin_dir), "module": "wheel_true"}},
            {"provider": {"path": str(plugin_dir), "module": "wheel_false"}},
        ]
    )

    assert fields == {"dependencies"}


def test_dynamic_wheel_fields_rejects_unknown_field(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "wheel_bad.py").write_text(
        "def dynamic_wheel(settings):\n"
        "    return {'not-a-field': True}\n"
        "def dynamic_metadata(settings, project):\n"
        "    return {}\n"
    )

    with pytest.raises(dynamic_metadata.errors.InvalidFieldError, match="settable"):
        dynamic_metadata.loader.dynamic_wheel_fields(
            [{"provider": {"path": str(plugin_dir), "module": "wheel_bad"}}]
        )


def test_dynamic_wheel_fields_rejects_dynamic_version(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "wheel_ver.py").write_text(
        "def dynamic_wheel(settings):\n"
        "    return {'version': True}\n"
        "def dynamic_metadata(settings, project):\n"
        "    return {'version': '1.0'}\n"
    )

    with pytest.raises(ValueError, match="'version' may never"):
        dynamic_metadata.loader.dynamic_wheel_fields(
            [{"provider": {"path": str(plugin_dir), "module": "wheel_ver"}}]
        )


def test_load_dynamic_metadata_requires_provider_key() -> None:
    with pytest.raises(
        dynamic_metadata.errors.ConfigError, match="must set a 'provider'"
    ):
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
    with pytest.raises(
        dynamic_metadata.errors.InvalidFieldError, match="not a settable"
    ):
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
    with pytest.raises(
        dynamic_metadata.errors.InvalidFieldError, match=r"project\.dynamic"
    ):
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


def test_fields_sets_several_fields() -> None:
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["version", "description", "keywords"]},
        [
            {
                "provider": "dynamic_metadata.fields",
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


def test_fields_formats_project() -> None:
    # One entry sets several fields, each reading the project resolved so far.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "version": "1.2.3", "dynamic": ["description", "urls"]},
        [
            {
                "provider": "dynamic_metadata.fields",
                "description": "{project[name]} {project[version]}",
                "urls": {"Release": "https://x.invalid/v{project[version]}"},
            }
        ],
        "wheel",
    )

    assert pyproject["description"] == "test 1.2.3"
    assert pyproject["urls"] == {"Release": "https://x.invalid/v1.2.3"}


def test_fields_reads_earlier_entry() -> None:
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["version", "description"]},
        [
            {"provider": "dynamic_metadata.static", "version": "1.2.3"},
            {
                "provider": "dynamic_metadata.fields",
                "description": "Version {project[version]}",
            },
        ],
        "wheel",
    )

    assert pyproject["description"] == "Version 1.2.3"


def test_fields_forward_reference_is_an_error() -> None:
    with pytest.raises(KeyError):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["version", "description"]},
            [
                {
                    "provider": "dynamic_metadata.fields",
                    "description": "Version {project[version]}",
                },
                {"provider": "dynamic_metadata.static", "version": "1.2.3"},
            ],
            "wheel",
        )


def test_fields_rejects_unknown_field() -> None:
    with pytest.raises(
        dynamic_metadata.errors.InvalidFieldError, match="not a settable"
    ):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["version"]},
            [{"provider": "dynamic_metadata.fields", "descriptions": "typo"}],
            "wheel",
        )


def test_fields_rejects_wrong_shape() -> None:
    with pytest.raises(RuntimeError, match="must be a string"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["version"]},
            [{"provider": "dynamic_metadata.fields", "version": ["1.2.3"]}],
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
    # The inline table forces a local import; a registered entry point of the
    # same name is not consulted.
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

    provider = dynamic_metadata.loader.load_provider(
        {"path": str(tmp_path), "module": "local"}
    )
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


def _fake_versions(**versions: str) -> Callable[[str], str]:
    """Stand in for importlib.metadata.version with a fixed environment."""

    def version(name: str) -> str:
        try:
            return versions[name]
        except KeyError:
            raise importlib.metadata.PackageNotFoundError(name) from None

    return version


def test_pin_installed_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    # The classic torch pin: match the installed major.minor, any patch. The
    # local version segment (+cu126) is ignored for substitution.
    monkeypatch.setattr(
        importlib.metadata, "version", _fake_versions(torch="2.7.1+cu126")
    )

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["dependencies"]},
        [
            {
                "provider": "dynamic_metadata.pin_installed",
                "packages": ["torch==x.x.*"],
            }
        ],
        "wheel",
    )

    assert pyproject["dependencies"] == ["torch==2.7.*"]
    assert pyproject["dynamic"] == []


def test_pin_installed_range_with_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    # The numpy ABI recommendation: at least the build version, below the next
    # major. x+1 adds to the substituted component.
    monkeypatch.setattr(importlib.metadata, "version", _fake_versions(numpy="1.26.4"))

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["dependencies"]},
        [
            {
                "provider": "dynamic_metadata.pin_installed",
                "packages": ["numpy>=x.x.x,<x+1"],
            }
        ],
        "wheel",
    )

    assert pyproject["dependencies"] == ["numpy>=1.26.4,<2"]


def test_pin_installed_multiple_and_static_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pins keep the packages order and append to static dependencies (PEP 808).
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        _fake_versions(torch="2.7.1", numpy="1.26.4"),
    )

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {
            "name": "test",
            "dependencies": ["packaging"],
            "dynamic": ["dependencies"],
        },
        [
            {
                "provider": "dynamic_metadata.pin_installed",
                "packages": ["torch==x.x.*", "numpy~=x.x"],
            }
        ],
        "wheel",
    )

    assert pyproject["dependencies"] == ["packaging", "torch==2.7.*", "numpy~=1.26"]


def test_pin_installed_odd_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    # A short release pads missing components with 0; epoch and pre-release
    # suffixes are dropped; literal components pass through.
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        _fake_versions(short="2.0", fancy="1!3.4.0rc1"),
    )

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["dependencies"]},
        [
            {
                "provider": "dynamic_metadata.pin_installed",
                "packages": ["short==x.x.x", "fancy>=x.x.0,<x+1"],
            }
        ],
        "wheel",
    )

    assert pyproject["dependencies"] == ["short==2.0.0", "fancy>=3.4.0,<4"]


def test_pin_installed_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.metadata, "version", _fake_versions())

    with pytest.raises(RuntimeError, match="'torch' is not installed"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["dependencies"]},
            [
                {
                    "provider": "dynamic_metadata.pin_installed",
                    "packages": ["torch==x.x.*"],
                }
            ],
            "wheel",
        )


def test_pin_installed_real_package() -> None:
    # One un-mocked run against a distribution guaranteed to be installed.
    major = importlib.metadata.version("pytest").split(".")[0]

    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["dependencies"]},
        [
            {
                "provider": "dynamic_metadata.pin_installed",
                "packages": ["pytest==x.*"],
            }
        ],
        "wheel",
    )

    assert pyproject["dependencies"] == [f"pytest=={major}.*"]


@pytest.mark.parametrize(
    ("package", "match"),
    [
        pytest.param("torch", "must include a specifier", id="no-specifier"),
        pytest.param("==x.x", "Invalid package template", id="no-name"),
        pytest.param("torch=x.x", "Invalid specifier", id="single-equals"),
        pytest.param("torch==x.*.x", "must be the last component", id="wildcard-mid"),
        pytest.param("torch>=x.*", "requires the '==' or '!='", id="wildcard-range"),
        pytest.param("torch==x.y", "Invalid version component", id="bad-component"),
    ],
)
def test_pin_installed_rejects_bad_template(
    monkeypatch: pytest.MonkeyPatch, package: str, match: str
) -> None:
    monkeypatch.setattr(importlib.metadata, "version", _fake_versions(torch="2.7.1"))

    with pytest.raises(RuntimeError, match=match):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["dependencies"]},
            [
                {
                    "provider": "dynamic_metadata.pin_installed",
                    "packages": [package],
                }
            ],
            "wheel",
        )


@pytest.mark.parametrize(
    ("settings", "match"),
    [
        pytest.param({}, "Must contain the 'packages'", id="missing"),
        pytest.param(
            {"packages": "torch==x.x.*"}, "must be a list of strings", id="not-list"
        ),
        pytest.param({"packages": [42]}, "must be a list of strings", id="not-str"),
        pytest.param(
            {"packages": [], "typo": "oops"}, "settings allowed", id="unknown-setting"
        ),
    ],
)
def test_pin_installed_rejects_bad_settings(
    settings: dict[str, Any], match: str
) -> None:
    with pytest.raises(RuntimeError, match=match):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "dynamic": ["dependencies"]},
            [{"provider": "dynamic_metadata.pin_installed", **settings}],
            "wheel",
        )


def test_pin_installed_dynamic_wheel() -> None:
    # Pinned dependencies differ per build environment, so the SDist marks them
    # Dynamic (METADATA 2.2); with nothing to pin, nothing is dynamic.
    fields = dynamic_metadata.loader.dynamic_wheel_fields(
        [
            {
                "provider": "dynamic_metadata.pin_installed",
                "packages": ["torch==x.x.*"],
            }
        ]
    )
    assert fields == {"dependencies"}

    fields = dynamic_metadata.loader.dynamic_wheel_fields(
        [{"provider": "dynamic_metadata.pin_installed", "packages": []}]
    )
    assert fields == set()


def test_pin_installed_get_requires() -> None:
    # The bare names are requested so the packages exist to be inspected.
    requires = dynamic_metadata.loader.get_requires_for_dynamic_metadata(
        [
            {
                "provider": "dynamic_metadata.pin_installed",
                "packages": ["torch==x.x.*", "numpy>=x.x.x,<x+1"],
            }
        ]
    )
    assert requires == ["torch", "numpy"]


def test_from_file_dependencies(tmp_path: Path) -> None:
    # requirements.txt conventions: comments, blank lines, and backslash
    # continuations are handled; the result appends to static dependencies.
    reqs = tmp_path / "requirements.txt"
    reqs.write_text(
        "# a full-line comment\n"
        "numpy>=1.26  # a trailing comment\n"
        "rich\\\n"
        ">=13\n"
        "\n"
        'typing-extensions; python_version<"3.11"\n'
    )
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {
            "name": "test",
            "version": "0.1.0",
            "dependencies": ["packaging"],
            "dynamic": ["dependencies"],
        },
        [
            {
                "provider": "dynamic_metadata.from_file",
                "field": "dependencies",
                "path": str(reqs),
            },
        ],
        "wheel",
    )

    assert pyproject["dependencies"] == [
        "packaging",
        "numpy>=1.26",
        "rich>=13",
        'typing-extensions; python_version<"3.11"',
    ]
    assert "dependencies" not in pyproject["dynamic"]


def test_from_file_optional_dependencies(tmp_path: Path) -> None:
    # One entry per extra; entries for the same extra append.
    (tmp_path / "requirements-test.txt").write_text("pytest>=7\n")
    (tmp_path / "requirements-docs.txt").write_text("sphinx\nfuro\n")
    (tmp_path / "requirements-test-extra.txt").write_text("pytest-cov\n")
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "version": "0.1.0", "dynamic": ["optional-dependencies"]},
        [
            {
                "provider": "dynamic_metadata.from_file",
                "field": "optional-dependencies.test",
                "path": str(tmp_path / "requirements-test.txt"),
            },
            {
                "provider": "dynamic_metadata.from_file",
                "field": "optional-dependencies.docs",
                "path": str(tmp_path / "requirements-docs.txt"),
            },
            {
                "provider": "dynamic_metadata.from_file",
                "field": "optional-dependencies.test",
                "path": str(tmp_path / "requirements-test-extra.txt"),
            },
        ],
        "wheel",
    )

    assert pyproject["optional-dependencies"] == {
        "test": ["pytest>=7", "pytest-cov"],
        "docs": ["sphinx", "furo"],
    }


def test_from_file_string_field(tmp_path: Path) -> None:
    # A string field takes the whole file, stripped: the classic VERSION file.
    (tmp_path / "VERSION").write_text("1.2.3\n")
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["version"]},
        [
            {
                "provider": "dynamic_metadata.from_file",
                "field": "version",
                "path": str(tmp_path / "VERSION"),
            },
        ],
        "wheel",
    )

    assert pyproject["version"] == "1.2.3"


def test_from_file_url_key(tmp_path: Path) -> None:
    # A dict-of-strings field takes a dotted key with the stripped contents.
    (tmp_path / "homepage.txt").write_text("https://example.com\n")
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "version": "0.1.0", "dynamic": ["urls"]},
        [
            {
                "provider": "dynamic_metadata.from_file",
                "field": "urls.Homepage",
                "path": str(tmp_path / "homepage.txt"),
            },
        ],
        "wheel",
    )

    assert pyproject["urls"] == {"Homepage": "https://example.com"}


@pytest.mark.parametrize("line", ["-r base.txt", "--index-url https://x", "-e ."])
def test_from_file_rejects_option_lines(tmp_path: Path, line: str) -> None:
    reqs = tmp_path / "requirements.txt"
    reqs.write_text(f"{line}\npytest\n")
    with pytest.raises(RuntimeError, match="Option line"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "version": "0.1.0", "dynamic": ["dependencies"]},
            [
                {
                    "provider": "dynamic_metadata.from_file",
                    "field": "dependencies",
                    "path": str(reqs),
                },
            ],
            "wheel",
        )


@pytest.mark.parametrize(
    ("settings", "match"),
    [
        pytest.param(
            {"field": "readme", "path": "x.md"},
            "readme_fragment",
            id="readme",
        ),
        pytest.param(
            {"field": "optional-dependencies", "path": "x.txt"},
            "requires a key",
            id="table-without-key",
        ),
        pytest.param(
            {"field": "urls", "path": "x.txt"},
            "requires a key",
            id="urls-without-key",
        ),
        pytest.param(
            {"field": "dependencies.test", "path": "x.txt"},
            "does not take a dotted key",
            id="dotted-list-field",
        ),
        pytest.param(
            {"field": "authors", "path": "x.txt"},
            "cannot be read from a file",
            id="unsupported-field",
        ),
        pytest.param(
            {"field": "dependencies"},
            "'path' setting",
            id="missing-path",
        ),
        pytest.param(
            {"field": "dependencies", "path": 3},
            "must be a string",
            id="non-string-path",
        ),
        pytest.param(
            {"field": "dependencies", "path": "x.txt", "typo": "oops"},
            "settings allowed",
            id="unknown-setting",
        ),
    ],
)
def test_from_file_rejects_bad_settings(settings: dict[str, Any], match: str) -> None:
    # Settings and field shapes are validated before the file is read, so none
    # of these need the file to exist.
    with pytest.raises(RuntimeError, match=match):
        dynamic_metadata.loader.process_dynamic_metadata(
            {
                "name": "test",
                "version": "0.1.0",
                "dynamic": ["dependencies", "optional-dependencies", "urls"],
            },
            [{"provider": "dynamic_metadata.from_file", **settings}],
            "wheel",
        )


def test_list_providers_includes_bundled() -> None:
    providers = dynamic_metadata.discovery.list_providers()
    assert "dynamic_metadata.regex" in providers
    assert "dynamic_metadata.plugins.regex" in providers["dynamic_metadata.regex"]


def test_cli_providers(capsys: pytest.CaptureFixture[str]) -> None:
    dynamic_metadata.__main__.main(["providers"])
    out = capsys.readouterr().out
    assert "dynamic_metadata.regex" in out
    assert "dynamic_metadata.template" in out


def test_errors_share_base() -> None:
    # Every loader error derives from DynamicMetadataError (and keeps a
    # standard base), so a backend can translate them with one except clause.
    errors = dynamic_metadata.errors
    for cls, base in [
        (errors.ConfigError, ValueError),
        (errors.InvalidFieldError, ValueError),
        (errors.ProviderNotFoundError, ModuleNotFoundError),
        (errors.ProviderLoadError, ImportError),
    ]:
        assert issubclass(cls, errors.DynamicMetadataError)
        assert issubclass(cls, base)
        assert str(cls("msg")) == "msg"


def test_provider_not_found_error(tmp_path: Path) -> None:
    with pytest.raises(dynamic_metadata.errors.ProviderNotFoundError):
        dynamic_metadata.loader.load_provider(
            {"path": str(tmp_path), "module": "nope_prov"}
        )
    with pytest.raises(dynamic_metadata.errors.ProviderNotFoundError):
        dynamic_metadata.loader.load_provider("nope.provider")


def test_provider_load_error_local(tmp_path: Path) -> None:
    # A local provider whose own import fails is a load error, distinct from
    # the provider module itself being missing.
    _write_provider(tmp_path, "broken_import_prov", "import not_a_real_module_xyz\n")
    with pytest.raises(
        dynamic_metadata.errors.ProviderLoadError, match="Could not load provider"
    ):
        dynamic_metadata.loader.load_provider(
            {"path": str(tmp_path), "module": "broken_import_prov"}
        )


def test_config_error_bad_provider_shape() -> None:
    with pytest.raises(dynamic_metadata.errors.ConfigError):
        dynamic_metadata.loader.load_provider(3)
    with pytest.raises(dynamic_metadata.errors.ConfigError, match="build_state"):
        dynamic_metadata.loader.process_dynamic_metadata({}, [], "bad")  # type: ignore[arg-type]


def test_entries_from_pyproject() -> None:
    entries = dynamic_metadata.loader.entries_from_pyproject(
        {"tool": {"dynamic-metadata": [{"provider": "x", "a": 1}]}}
    )
    assert entries == [{"provider": "x", "a": 1}]
    assert dynamic_metadata.loader.entries_from_pyproject({}) == []
    assert dynamic_metadata.loader.entries_from_pyproject({"tool": {}}) == []


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ({"provider": "x"}, "array of tables"),
        ("x", "array of tables"),
        (["x"], "array of tables"),
        ([{"a": 1}], "must set a 'provider'"),
    ],
)
def test_entries_from_pyproject_rejects(value: Any, match: str) -> None:
    with pytest.raises(dynamic_metadata.errors.ConfigError, match=match):
        dynamic_metadata.loader.entries_from_pyproject(
            {"tool": {"dynamic-metadata": value}}
        )


def test_load_dynamic_metadata_rejects_non_table() -> None:
    with pytest.raises(dynamic_metadata.errors.ConfigError, match="array of tables"):
        list(dynamic_metadata.loader.load_dynamic_metadata(["x"]))  # type: ignore[list-item]


def test_get_requires_skips_unloadable(tmp_path: Path) -> None:
    # A provider importing (at module level) a package it would have declared
    # as a requirement is skipped; other providers still contribute. A missing
    # provider module is a config error and still raises.
    _write_provider(tmp_path, "unloadable_prov", "import not_a_real_module_xyz\n")
    _write_provider(
        tmp_path,
        "loadable_prov",
        "def get_requires_for_dynamic_metadata(settings):\n    return ['dep']\n"
        "def dynamic_metadata(settings, project):\n    return {}\n",
    )
    entries = [
        {"provider": {"path": str(tmp_path), "module": "unloadable_prov"}},
        {"provider": {"path": str(tmp_path), "module": "loadable_prov"}},
    ]
    requires = dynamic_metadata.loader.get_requires_for_dynamic_metadata(entries)
    assert requires == ["dep"]

    with pytest.raises(dynamic_metadata.errors.ProviderNotFoundError):
        dynamic_metadata.loader.get_requires_for_dynamic_metadata(
            [{"provider": {"path": str(tmp_path), "module": "missing_prov"}}]
        )


def test_metadata_headers_cover_all_fields() -> None:
    assert (
        set(dynamic_metadata.info.METADATA_HEADERS) == dynamic_metadata.info.ALL_FIELDS
    )


@pytest.mark.parametrize("field", ["import-names", "import-namespaces"])
def test_import_names(field: str) -> None:
    result = dynamic_metadata.loader.process_dynamic_metadata(
        {"dynamic": [field]},
        [{"provider": "dynamic_metadata.static", field: ["pkg"]}],
        "wheel",
    )

    assert result[field] == ["pkg"]
    assert not result["dynamic"]


def test_testing_provider_all_hooks() -> None:
    entries = [
        {
            "provider": "dynamic_metadata.testing",
            "fields": {
                "description": "{project[name]} built as {build_state}",
                "dependencies": ["dep-{build_state}"],
            },
            "requires": ["test-plugin-requirement"],
            "dynamic-wheel": ["dependencies"],
        }
    ]
    project = dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test", "dynamic": ["description", "dependencies"]},
        entries,
        "sdist",
    )
    assert project["description"] == "test built as sdist"
    assert project["dependencies"] == ["dep-sdist"]
    assert dynamic_metadata.loader.dynamic_wheel_fields(entries) == {"dependencies"}
    assert dynamic_metadata.loader.get_requires_for_dynamic_metadata(entries) == [
        "test-plugin-requirement"
    ]


def test_testing_provider_defaults() -> None:
    entries = [{"provider": "dynamic_metadata.testing"}]
    assert dynamic_metadata.loader.process_dynamic_metadata(
        {"name": "test"}, entries, "wheel"
    ) == {"name": "test", "dynamic": []}
    assert dynamic_metadata.loader.dynamic_wheel_fields(entries) == set()
    assert dynamic_metadata.loader.get_requires_for_dynamic_metadata(entries) == []


def test_testing_provider_rejects_bad_settings() -> None:
    with pytest.raises(RuntimeError, match="settings allowed"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test"},
            [{"provider": "dynamic_metadata.testing", "nope": 1}],
            "wheel",
        )
    with pytest.raises(RuntimeError, match="list of strings"):
        dynamic_metadata.loader.dynamic_wheel_fields(
            [{"provider": "dynamic_metadata.testing", "dynamic-wheel": "dependencies"}]
        )
