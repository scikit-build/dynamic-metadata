from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["dynamic_metadata"]


def __dir__() -> list[str]:
    return __all__


# Settings consumed by a single fragment entry. A fragment is a text fragment
# ("text") or a file fragment ("path"); the slicing keys only apply to a file.
KEYS = {
    "text",
    "path",
    "content-type",
    "start-after",
    "start-at",
    "end-before",
    "end-at",
    "pattern",
}

FILE_ONLY_KEYS = {"start-after", "start-at", "end-before", "end-at", "pattern"}


def _find(text: str, marker: str, key: str, path: str) -> int:
    index = text.find(marker)
    if index < 0:
        msg = f"Could not find {key!r} marker {marker!r} in {path}"
        raise RuntimeError(msg)
    return index


def _slice(text: str, settings: Mapping[str, Any], path: str) -> str:
    """Cut a file fragment down with the start/end markers, then a pattern."""
    if "start-after" in settings and "start-at" in settings:
        msg = "Cannot set both 'start-after' and 'start-at'"
        raise RuntimeError(msg)
    if "end-before" in settings and "end-at" in settings:
        msg = "Cannot set both 'end-before' and 'end-at'"
        raise RuntimeError(msg)

    if "start-after" in settings:
        marker = settings["start-after"]
        text = text[_find(text, marker, "start-after", path) + len(marker) :]
    elif "start-at" in settings:
        marker = settings["start-at"]
        text = text[_find(text, marker, "start-at", path) :]

    if "end-before" in settings:
        marker = settings["end-before"]
        text = text[: _find(text, marker, "end-before", path)]
    elif "end-at" in settings:
        marker = settings["end-at"]
        text = text[: _find(text, marker, "end-at", path) + len(marker)]

    if "pattern" in settings:
        pattern = settings["pattern"]
        match = re.search(pattern, text, re.DOTALL)
        if match is None or not match.groups():
            msg = f"Pattern {pattern!r} with a capture group did not match {path}"
            raise RuntimeError(msg)
        text = match.group(1)

    return text


def _fragment_text(settings: Mapping[str, Any]) -> str:
    has_text = "text" in settings
    has_path = "path" in settings
    if has_text and has_path:
        msg = "A fragment must set exactly one of 'text' or 'path', not both"
        raise RuntimeError(msg)
    if not has_text and not has_path:
        msg = "A fragment must set 'text' or 'path'"
        raise RuntimeError(msg)

    if has_text:
        if settings.keys() & FILE_ONLY_KEYS:
            msg = "Slicing settings require 'path', not 'text'"
            raise RuntimeError(msg)
        return settings["text"]  # type: ignore[no-any-return]

    path = settings["path"]
    with Path(path).open(encoding="utf-8") as f:
        text = f.read()
    return _slice(text, settings, path)


def dynamic_metadata(
    settings: Mapping[str, Any],
    project: Mapping[str, Any],
) -> dict[str, Any]:
    if settings.keys() - KEYS:
        msg = f"Only {KEYS} settings allowed by this plugin"
        raise RuntimeError(msg)
    for key in settings:
        if not isinstance(settings[key], str):
            msg = f"Setting {key!r} must be a string"
            raise RuntimeError(msg)

    fragment = _fragment_text(settings)

    # Each entry appends to the readme produced by earlier entries (a scalar, so
    # the loader replaces the prior result with this extended one).
    existing = project.get("readme")
    content_type = settings.get("content-type")
    if existing is None:
        existing_text = ""
    elif isinstance(existing, dict) and "text" in existing:
        existing_text = existing["text"]
        content_type = content_type or existing.get("content-type")
    else:
        msg = (
            "fragment can only extend a text-based readme produced by an earlier entry"
        )
        raise RuntimeError(msg)

    return {
        "readme": {
            "content-type": content_type or "text/markdown",
            "text": existing_text + fragment,
        }
    }
