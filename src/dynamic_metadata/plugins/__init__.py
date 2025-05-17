from __future__ import annotations

import typing
from collections.abc import Callable

from ..info import DICT_STR_FIELDS, LIST_DICT_FIELDS, LIST_STR_FIELDS, STR_FIELDS

T = typing.TypeVar(
    "T",
    bound="str | list[str] | list[dict[str, str]] | dict[str, str] | dict[str, list[str]] | dict[str, dict[str, str]]",
)


def _process_dynamic_metadata(field: str, action: Callable[[str], str], result: T) -> T:
    """
    Helper function for processing an action on the various possible metadata fields.
    """

    if field in STR_FIELDS:
        if not isinstance(result, str):
            msg = f"Field {field!r} must be a string"
            raise RuntimeError(msg)
        return action(result)  # type: ignore[return-value]
    if field in LIST_STR_FIELDS:
        if not (isinstance(result, list) and all(isinstance(r, str) for r in result)):
            msg = f"Field {field!r} must be a list of strings"
            raise RuntimeError(msg)
        return [action(r) for r in result]  # type: ignore[return-value]
    if field in DICT_STR_FIELDS | {"readme"}:
        if not isinstance(result, dict) or not all(
            isinstance(v, str) for v in result.values()
        ):
            msg = f"Field {field!r} must be a dictionary of strings"
            raise RuntimeError(msg)
        return {action(k): action(v) for k, v in result.items()}  # type: ignore[return-value]
    if field in LIST_DICT_FIELDS:
        if not isinstance(result, list) or not all(
            isinstance(k, str) and isinstance(v, str)
            for d in result
            for k, v in d.items()
        ):
            msg = f"Field {field!r} must be a dictionary of strings"
            raise RuntimeError(msg)
        return [{k: action(v) for k, v in d.items()} for d in result]  # type: ignore[return-value]
    if field == "entry-points":
        if not isinstance(result, dict) or not all(
            isinstance(d, dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in d.items())
            for d in result.values()
        ):
            msg = "Field 'entry-points' must be a dictionary of dictionary of strings"
            raise RuntimeError(msg)
        return {
            dk: {action(k): action(v) for k, v in dv.items()}
            for dk, dv in result.items()
        }  # type: ignore[return-value]
    if field == "optional-dependencies":
        if not isinstance(result, dict) or not all(
            isinstance(v, list) for v in result.values()
        ):
            msg = "Field 'optional-dependencies' must be a dictionary of lists"
            raise RuntimeError(msg)
        return {k: [action(r) for r in v] for k, v in result.items()}  # type: ignore[return-value]

    msg = f"Unsupported field {field!r} for action"
    raise RuntimeError(msg)
