from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import _process_dynamic_metadata, _require_field

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["dynamic_metadata"]


def __dir__() -> list[str]:
    return __all__


KEYS = {"field", "input", "regex", "result", "remove"}


def _process(match: re.Match[str], remove: str, result: str) -> str:
    retval = result.format(*match.groups(), **match.groupdict())
    if remove:
        retval = re.sub(remove, "", retval)
    return retval


def dynamic_metadata(
    settings: Mapping[str, Any],
    _project: Mapping[str, Any],
) -> dict[str, Any]:
    # Input validation
    field = _require_field(settings, KEYS)
    if "input" not in settings:
        msg = "Must contain the 'input' setting to perform a regex on"
        raise RuntimeError(msg)
    if field != "version" and "regex" not in settings:
        msg = "Must contain the 'regex' setting if not getting version"
        raise RuntimeError(msg)
    for key in KEYS:
        if key in settings and not isinstance(settings[key], str):
            msg = f"Setting {key!r} must be a string"
            raise RuntimeError(msg)

    input_filename = settings["input"]
    regex = settings.get(
        "regex",
        r'(?i)^(__version__|VERSION)(?: ?\: ?str)? *= *([\'"])v?(?P<value>.+?)\2',
    )
    result = settings.get("result", "{value}")
    assert isinstance(result, str)
    remove = settings.get("remove", "")

    with Path(input_filename).open(encoding="utf-8") as f:
        match = re.search(regex, f.read(), re.MULTILINE)

    if not match:
        msg = f"Couldn't find {regex!r} in {input_filename}"
        raise RuntimeError(msg)

    return {
        field: _process_dynamic_metadata(
            field, functools.partial(_process, match, remove), result
        )
    }
