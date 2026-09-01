"""Exceptions raised by :mod:`dynamic_metadata.loader`.

Every error the loader raises itself derives from :class:`DynamicMetadataError`,
so a backend can translate them all with one ``except`` clause. The subclasses
also keep a standard base (``ValueError``, ``ImportError``, ...) so existing
handlers keep working. An exception raised *inside* a provider's hook is not
wrapped and propagates unchanged.
"""

from __future__ import annotations

__all__ = [
    "ConfigError",
    "DynamicMetadataError",
    "InvalidFieldError",
    "ProviderLoadError",
    "ProviderNotFoundError",
]


def __dir__() -> list[str]:
    return __all__


class DynamicMetadataError(Exception):
    """Base class for every error the loader raises."""


class ConfigError(DynamicMetadataError, ValueError):
    """The ``[[tool.dynamic-metadata]]`` configuration (or a loader argument) is invalid."""


class InvalidFieldError(DynamicMetadataError, ValueError):
    """A provider returned a field that cannot be set, or set it in an invalid way."""


class ProviderNotFoundError(DynamicMetadataError, ModuleNotFoundError):
    """No provider is registered under the given name, or the local module is missing."""


class ProviderLoadError(DynamicMetadataError, ImportError):
    """The provider was found but importing it failed (for example a missing dependency)."""
