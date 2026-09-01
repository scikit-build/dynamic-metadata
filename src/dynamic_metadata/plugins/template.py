from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

from . import _fields_fragment, _require_field

__all__ = ["dynamic_metadata"]


def __dir__() -> list[str]:
    return __all__


KEYS = {"field", "result"}


def dynamic_metadata(
    settings: Mapping[str, Any],
    project: Mapping[str, Any],
) -> dict[str, Any]:
    field = _require_field(settings, KEYS)

    if "result" not in settings:
        msg = "Must contain the 'result' setting with a template substitution"
        raise RuntimeError(msg)

    # One field is the only difference from the fields plugin.
    return _fields_fragment(
        {field: settings["result"]}, lambda r: r.format(project=project)
    )
