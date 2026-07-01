"""Provider discovery helpers.

Not part of the minimum a backend needs to resolve dynamic metadata (that is
``loader.py``); this is tooling for listing what is installed, used by the
``dynamic-metadata providers`` command.
"""

from __future__ import annotations

from ._compat import metadata
from .loader import PROVIDER_GROUP, _entry_point_dist

__all__ = ["list_providers"]


def __dir__() -> list[str]:
    return __all__


def list_providers() -> dict[str, str]:
    """Map each registered provider name to a human-readable descriptor.

    Discovers every entry point in ``PROVIDER_GROUP`` (the bundled plugins plus
    any installed third-party plugins). The descriptor is the entry-point value,
    annotated with the providing distribution when available.
    """
    providers: dict[str, str] = {}
    for ep in metadata.entry_points(PROVIDER_GROUP):
        dist = _entry_point_dist(ep)
        providers[ep.name] = f"{ep.value} ({dist})" if dist else ep.value
    return providers
