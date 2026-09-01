from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

from . import _fields_fragment

__all__ = ["dynamic_metadata"]


def __dir__() -> list[str]:
    return __all__


def dynamic_metadata(
    settings: Mapping[str, Any],
    _project: Mapping[str, Any],
) -> dict[str, Any]:
    # An alternative to writing the values in [project]: each setting is a
    # metadata field returned verbatim. This gives a later entry (e.g.
    # substitute) a *dynamic* value to transform, and keeps the values out of
    # [project]. `fields` is the same with `{project[...]}` templating.
    return _fields_fragment(settings, lambda s: s)
