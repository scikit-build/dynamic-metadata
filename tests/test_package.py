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
