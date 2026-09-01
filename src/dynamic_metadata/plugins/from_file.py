from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..info import DICT_STR_FIELDS, LIST_STR_FIELDS, STR_FIELDS
from . import _require_field

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["dynamic_metadata"]


def __dir__() -> list[str]:
    return __all__


KEYS = {"field", "path"}

# pip's comment rule: '#' at line start or preceded by whitespace.
_COMMENT_RE = re.compile(r"(^|\s+)#.*$")
_CONTINUATION_RE = re.compile(r"\\\r?\n")


def _lines(text: str, path: str) -> list[str]:
    """Parse requirements.txt-style lines from ``text``.

    Backslash continuations are joined, comments and blank lines dropped. pip
    option lines (``-r``, ``--index-url``, ...) are not requirements and raise;
    several files are combined with one entry per file instead.
    """
    result = []
    for raw in _CONTINUATION_RE.sub("", text).splitlines():
        line = _COMMENT_RE.sub("", raw).strip()
        if not line:
            continue
        if line.startswith("-"):
            msg = (
                f"Option line {line!r} in {path} is not supported; use one "
                "entry per file instead of '-r'"
            )
            raise RuntimeError(msg)
        result.append(line)
    return result


def dynamic_metadata(
    settings: Mapping[str, Any],
    _project: Mapping[str, Any],
) -> dict[str, Any]:
    field = _require_field(settings, KEYS)
    if "path" not in settings:
        msg = "Must contain the 'path' setting naming the file to read"
        raise RuntimeError(msg)
    path = settings["path"]
    if not isinstance(path, str):
        msg = "Setting 'path' must be a string"
        raise TypeError(msg)

    # A table field names the key to fill after a dot, one entry per key
    # (a further dot is part of the key, e.g. a 'urls' name).
    base, _, key = field.partition(".")
    if key:
        if base not in DICT_STR_FIELDS and base != "optional-dependencies":
            msg = f"Field {base!r} does not take a dotted key"
            raise RuntimeError(msg)
    elif field in DICT_STR_FIELDS or field == "optional-dependencies":
        example = "extra" if field == "optional-dependencies" else "name"
        msg = f"Field {field!r} requires a key: use '{field}.<{example}>'"
        raise RuntimeError(msg)
    elif field == "readme":
        msg = "Use the readme_fragment plugin to build a readme from a file"
        raise RuntimeError(msg)
    elif field not in STR_FIELDS and field not in LIST_STR_FIELDS:
        msg = f"Field {field!r} cannot be read from a file"
        raise RuntimeError(msg)

    with Path(path).open(encoding="utf-8") as f:
        text = f.read()

    if key:
        return {
            base: {key: _lines(text, path)}
            if base == "optional-dependencies"
            else {key: text.strip()}
        }
    if field in LIST_STR_FIELDS:
        return {field: _lines(text, path)}
    return {field: text.strip()}
