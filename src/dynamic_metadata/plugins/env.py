from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from ..info import STR_FIELDS
from . import _require_field, _require_str_settings

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["dynamic_metadata", "dynamic_wheel"]


def __dir__() -> list[str]:
    return __all__


KEYS = {"field", "variable", "default"}


def _field(settings: Mapping[str, Any]) -> str:
    """Validate the settings and return the target field name.

    The value read from the environment is a single string, so only scalar
    string fields (see :data:`STR_FIELDS`) can be filled.
    """
    field = _require_field(settings, KEYS)
    if "variable" not in settings:
        msg = "Must contain the 'variable' setting naming the environment variable"
        raise RuntimeError(msg)
    _require_str_settings(settings, KEYS)
    if field not in STR_FIELDS:
        msg = (
            f"Field {field!r} cannot be filled from an environment variable; "
            "only string fields are supported"
        )
        raise RuntimeError(msg)
    return field


def dynamic_metadata(
    settings: Mapping[str, Any],
    _project: Mapping[str, Any],
) -> dict[str, Any]:
    field = _field(settings)
    variable = settings["variable"]
    value = os.environ.get(variable)
    if value is None:
        if "default" not in settings:
            msg = (
                f"Environment variable {variable!r} is not set and no 'default' "
                "was given"
            )
            raise RuntimeError(msg)
        value = settings["default"]
        assert isinstance(value, str)
    return {field: value}


def dynamic_wheel(settings: Mapping[str, Any]) -> dict[str, bool]:
    # An environment variable may hold different values when the SDist and the
    # wheel are built, so the field is marked Dynamic (METADATA 2.2). 'version'
    # may never differ between the two, so it is never dynamic.
    field = _field(settings)
    return {field: field != "version"}
