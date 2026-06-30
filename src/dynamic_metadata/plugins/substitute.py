from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..info import SCALAR_FIELDS
from . import _process_dynamic_metadata

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["dynamic_metadata"]


def __dir__() -> list[str]:
    return __all__


KEYS = {"field", "pattern", "replacement", "ignore-case"}


def dynamic_metadata(
    settings: Mapping[str, Any],
    project: Mapping[str, Any],
) -> dict[str, Any]:
    if settings.keys() - KEYS:
        msg = f"Only {KEYS} settings allowed by this plugin"
        raise RuntimeError(msg)
    field = settings.get("field", "readme")
    if not isinstance(field, str):
        msg = "The 'field' setting must be a string"
        raise RuntimeError(msg)
    # Only scalar fields can be transformed in place: the loader *appends* a
    # produced extendable field, so re-emitting a whole transformed list/table
    # would duplicate it. Scalars are replaced, so the substitution sticks.
    if field not in SCALAR_FIELDS:
        msg = (
            f"Field {field!r} cannot be substituted; only scalar fields "
            f"{sorted(SCALAR_FIELDS)} can be transformed in place"
        )
        raise RuntimeError(msg)

    for key in ("pattern", "replacement"):
        if key not in settings:
            msg = f"Must contain the {key!r} setting"
            raise RuntimeError(msg)
        if not isinstance(settings[key], str):
            msg = f"Setting {key!r} must be a string"
            raise RuntimeError(msg)

    ignore_case = settings.get("ignore-case", False)
    if not isinstance(ignore_case, bool):
        msg = "Setting 'ignore-case' must be a boolean"
        raise RuntimeError(msg)

    if field not in project:
        msg = f"Field {field!r} must be produced by an earlier entry to substitute"
        raise RuntimeError(msg)

    pattern = settings["pattern"]
    replacement = settings["replacement"]
    flags = re.IGNORECASE if ignore_case else 0

    return {
        field: _process_dynamic_metadata(
            field,
            lambda s: re.sub(pattern, replacement, s, flags=flags),
            project[field],
        )
    }
