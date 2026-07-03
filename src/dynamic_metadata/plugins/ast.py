from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import _process_dynamic_metadata, _require_field, _require_str_settings

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["dynamic_metadata"]


def __dir__() -> list[str]:
    return __all__


KEYS = {"field", "input", "name"}


def _tuples_to_lists(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_tuples_to_lists(v) for v in value]
    if isinstance(value, dict):
        return {k: _tuples_to_lists(v) for k, v in value.items()}
    return value


def dynamic_metadata(
    settings: Mapping[str, Any],
    _project: Mapping[str, Any],
) -> dict[str, Any]:
    # Input validation
    field = _require_field(settings, KEYS)
    if "input" not in settings:
        msg = "Must contain the 'input' setting naming a Python file to parse"
        raise RuntimeError(msg)
    if "name" not in settings:
        msg = "Must contain the 'name' setting naming the global to read"
        raise RuntimeError(msg)
    _require_str_settings(settings, KEYS)

    input_filename = settings["input"]
    name = settings["name"]

    tree = ast.parse(
        Path(input_filename).read_text(encoding="utf-8"), filename=input_filename
    )

    # Last matching module-level assignment wins, like execution would give
    value_node = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            value_node = value

    if value_node is None:
        msg = f"Couldn't find a global assignment to {name} in {input_filename}"
        raise RuntimeError(msg)

    try:
        result = _tuples_to_lists(ast.literal_eval(value_node))
    except ValueError as err:
        msg = f"Assignment at {input_filename}:{value_node.lineno} is not a literal constant"
        raise RuntimeError(msg) from err

    return {field: _process_dynamic_metadata(field, lambda s: s, result)}
