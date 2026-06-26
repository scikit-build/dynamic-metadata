from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

from . import _process_dynamic_metadata, _require_field

__all__ = ["dynamic_metadata"]


def __dir__() -> list[str]:
    return __all__


KEYS = {"field", "result"}


def dynamic_metadata(
    settings: Mapping[str, Any],
    project: Mapping[str, Any],
    _build_state: str,
) -> dict[str, Any]:
    field = _require_field(settings, KEYS)

    if "result" not in settings:
        msg = "Must contain the 'result' setting with a template substitution"
        raise RuntimeError(msg)

    result = settings["result"]

    return {
        field: _process_dynamic_metadata(
            field,
            lambda r: r.format(project=project),
            result,
        )
    }
