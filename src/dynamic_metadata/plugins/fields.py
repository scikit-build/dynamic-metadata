from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

from ..info import ALL_FIELDS
from . import _process_dynamic_metadata

__all__ = ["dynamic_metadata"]


def __dir__() -> list[str]:
    return __all__


def dynamic_metadata(
    settings: Mapping[str, Any],
    project: Mapping[str, Any],
) -> dict[str, Any]:
    # Like `static`, but every string is a `str.format` template, so one entry
    # can set several fields and reference the project resolved so far. A
    # literal brace must be doubled; use `static` for values that are verbatim.
    # An unknown field is passed through untouched so the loader reports it.
    return {
        field: _process_dynamic_metadata(
            field,
            lambda s: s.format(project=project),
            value,
        )
        if field in ALL_FIELDS
        else value
        for field, value in settings.items()
    }
