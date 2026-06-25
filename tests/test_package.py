from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import dynamic_metadata.loader
import dynamic_metadata.plugins


def test_load_provider_path_loads_local(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "local_prov_ok.py").write_text(
        "def dynamic_metadata(field, settings, project):\n    return '1.2.3'\n"
    )

    provider = dynamic_metadata.loader.load_provider("local_prov_ok", str(plugin_dir))
    assert provider.dynamic_metadata("version", {}, {}) == "1.2.3"


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
        {
            "requires-python": {
                "provider": "dynamic_metadata.plugins.template",
                "result": ">={project[version]}",
            },
        },
    )

    assert pyproject["requires-python"] == ">=0.1.0"


def test_template_needs() -> None:
    # These are intentionally out of order to test the order of processing
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {
            "name": "test",
            "version": "0.1.0",
            "dynamic": ["requires-python", "license", "readme"],
        },
        {
            "license": {
                "provider": "dynamic_metadata.plugins.template",
                "result": "{project[requires-python]}",
            },
            "readme": {
                "provider": "dynamic_metadata.plugins.template",
                "result": {"file": "{project[license]}"},
            },
            "requires-python": {
                "provider": "dynamic_metadata.plugins.template",
                "result": ">={project[version]}",
            },
        },
    )

    assert pyproject["requires-python"] == ">=0.1.0"


def test_template_entry_points() -> None:
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {
            "name": "test",
            "dynamic": ["version", "entry-points"],
        },
        {
            "version": {
                "provider": "dynamic_metadata.plugins.template",
                "result": "1.2.3",
            },
            "entry-points": {
                "provider": "dynamic_metadata.plugins.template",
                "result": {
                    "my_group": {"my_point": "my_app:script_{project[version]}"}
                },
            },
        },
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
        {
            "requires-python": {
                "provider": "dynamic_metadata.plugins.regex",
                "input": "pyproject.toml",
                "regex": r"name = \"(?P<name>.+)\"",
                "result": ">={name}",
            },
        },
    )

    assert pyproject["requires-python"] == ">=dynamic-metadata"


def test_regex_rejects_unknown_setting() -> None:
    with pytest.raises(RuntimeError, match="settings allowed"):
        dynamic_metadata.loader.process_dynamic_metadata(
            {"name": "test", "version": "0.1.0", "dynamic": ["requires-python"]},
            {
                "requires-python": {
                    "provider": "dynamic_metadata.plugins.regex",
                    "input": "pyproject.toml",
                    "typo": "oops",
                },
            },
        )


def test_pep808_extends_static_dependencies() -> None:
    # PEP 808: a field may be both static and dynamic; the provider only adds.
    pyproject = dynamic_metadata.loader.process_dynamic_metadata(
        {
            "name": "test",
            "version": "1.2.3",
            "dependencies": ["torch", "packaging"],
            "dynamic": ["dependencies"],
        },
        {
            "dependencies": {
                "provider": "dynamic_metadata.plugins.template",
                "result": ["numpy>={project[version]}"],
            },
        },
    )

    # Static entries are preserved and ordered first; the provider's additions
    # are appended verbatim.
    assert pyproject["dependencies"] == ["torch", "packaging", "numpy>=1.2.3"]
    assert pyproject["dynamic"] == []


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
