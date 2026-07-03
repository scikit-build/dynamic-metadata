"""Fill a field from a structured data file (TOML or JSON).

The value at a dotted ``key`` path is read from a ``.toml`` or ``.json`` file and,
like the :mod:`ast <dynamic_metadata.plugins.ast>` plugin, keeps its shape — so a
list or table field can be filled directly. A table field may instead name a
single key after a dot in ``field`` (``optional-dependencies.test``), matching
the :mod:`from_file <dynamic_metadata.plugins.from_file>` convention.

This is the reference example of the optional ``build_state`` hook. An opt-in
``states`` setting gates the entry to a set of build states: when the current
build state is not listed, ``dynamic_metadata`` contributes nothing and the field
is left in ``project.dynamic`` for another entry (or the backend) to resolve.
Without ``states`` the plugin is unconditional, so nothing changes for anyone not
using the feature.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .._compat import tomllib
from ..info import DICT_STR_FIELDS
from ..protocols import BUILD_STATES
from . import _process_dynamic_metadata, _require_field, _require_str_settings

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..protocols import BuildState

__all__ = ["Provider"]


def __dir__() -> list[str]:
    return __all__


KEYS = {"field", "path", "key", "states"}


def _settings(settings: Mapping[str, Any]) -> tuple[str, str, str, list[str] | None]:
    """Validate the settings and return ``(field, path, key, states)``.

    ``states`` is ``None`` when the setting is absent (unconditional behavior).
    Runs identically from ``dynamic_metadata`` and the stateless ``dynamic_wheel``.
    """
    field = _require_field(settings, KEYS)
    for required in ("path", "key"):
        if required not in settings:
            msg = f"Must contain the {required!r} setting"
            raise RuntimeError(msg)
    _require_str_settings(settings, {"path", "key"})

    base = field.partition(".")[0]
    if (
        base != field
        and base not in DICT_STR_FIELDS
        and base != "optional-dependencies"
    ):
        msg = f"Field {base!r} does not take a dotted key"
        raise RuntimeError(msg)

    states = settings.get("states")
    if states is not None:
        if not isinstance(states, list) or not all(isinstance(s, str) for s in states):
            msg = "Setting 'states' must be a list of strings"
            raise RuntimeError(msg)
        unknown = sorted(set(states) - BUILD_STATES)
        if unknown:
            msg = f"Unknown build state(s) {unknown}; valid states are {sorted(BUILD_STATES)}"
            raise RuntimeError(msg)
        if base == "version":
            msg = (
                "'version' cannot be gated by 'states': a version must resolve "
                "identically in every build state"
            )
            raise RuntimeError(msg)

    return field, settings["path"], settings["key"], states


def _extract(path: str, key: str) -> Any:
    """Read ``path`` (format from its extension) and follow the dotted ``key``.

    Key segments that themselves contain a dot are not supported. A missing
    segment raises, naming the segment that failed.
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".toml":
        with Path(path).open("rb") as f:
            data: Any = tomllib.load(f)
    elif suffix == ".json":
        with Path(path).open(encoding="utf-8") as f:
            data = json.load(f)
    else:
        msg = f"Unsupported data file extension {suffix!r} for {path!r}; use '.toml' or '.json'"
        raise RuntimeError(msg)

    current = data
    seen: list[str] = []
    for segment in key.split("."):
        if not isinstance(current, dict):
            location = ".".join(seen) or "the document root"
            msg = f"Cannot read key segment {segment!r}: {location} is not a table in {path}"
            raise RuntimeError(msg)
        if segment not in current:
            location = ".".join(seen) or "the document root"
            msg = f"Key segment {segment!r} not found in {location} of {path}"
            raise RuntimeError(msg)
        current = current[segment]
        seen.append(segment)
    return current


class Provider:
    """Class provider: the ``build_state`` hook stashes the state on ``self``."""

    def __init__(self) -> None:
        self._build_state: BuildState | None = None

    def build_state(self, build_state: BuildState) -> None:
        self._build_state = build_state

    def dynamic_metadata(
        self,
        settings: Mapping[str, Any],
        _project: Mapping[str, Any],
    ) -> dict[str, Any]:
        field, path, key, states = _settings(settings)
        # Gated out for this build state: contribute nothing (the field stays in
        # project.dynamic unless another entry provides it).
        if states is not None and self._build_state not in states:
            return {}

        value = _extract(path, key)

        base, _, subkey = field.partition(".")
        if subkey:
            # A table field naming one key: validate the value's shape by pushing
            # {key: value} through the field's shape check.
            return {base: _process_dynamic_metadata(base, lambda s: s, {subkey: value})}
        return {field: _process_dynamic_metadata(field, lambda s: s, value)}

    def dynamic_wheel(self, settings: Mapping[str, Any]) -> dict[str, bool]:
        # A states-gated field can differ between the SDist build and the wheel
        # build, so it is Dynamic (METADATA 2.2); without states the file content
        # is identical at both times, so nothing is dynamic. Stateless by design.
        field, _, _, states = _settings(settings)
        return {field.partition(".")[0]: True} if states is not None else {}
