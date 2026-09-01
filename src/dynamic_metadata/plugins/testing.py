"""A provider for backend integration tests: every hook, driven by settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import _fields_fragment

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..protocols import BuildState

__all__ = ["Provider"]


def __dir__() -> list[str]:
    return __all__


KEYS = {"fields", "requires", "dynamic-wheel"}


def _check(settings: Mapping[str, Any]) -> None:
    if settings.keys() - KEYS:
        msg = f"Only {KEYS} settings allowed by this plugin"
        raise RuntimeError(msg)
    if not isinstance(settings.get("fields", {}), dict):
        msg = "Setting 'fields' must be a table"
        raise RuntimeError(msg)
    for key in ("requires", "dynamic-wheel"):
        value = settings.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            msg = f"Setting {key!r} must be a list of strings"
            raise RuntimeError(msg)


class Provider:
    """Return ``fields`` verbatim, with ``{build_state}`` and ``{project[...]}`` formatted into strings.

    ``requires`` is returned from ``get_requires_for_dynamic_metadata`` and each
    field in ``dynamic-wheel`` is reported dynamic. The build state is stashed by
    the ``build_state`` hook, so a test can check it reached the provider.
    """

    def __init__(self) -> None:
        self.state: BuildState | None = None

    def build_state(self, build_state: BuildState) -> None:
        self.state = build_state

    def dynamic_metadata(
        self, settings: Mapping[str, Any], project: Mapping[str, Any]
    ) -> dict[str, Any]:
        _check(settings)
        return _fields_fragment(
            settings.get("fields", {}),
            lambda s: s.format(build_state=self.state, project=project),
        )

    def get_requires_for_dynamic_metadata(
        self, settings: Mapping[str, Any]
    ) -> list[str]:
        _check(settings)
        return list(settings.get("requires", []))

    def dynamic_wheel(self, settings: Mapping[str, Any]) -> dict[str, bool]:
        _check(settings)
        return dict.fromkeys(settings.get("dynamic-wheel", []), True)
