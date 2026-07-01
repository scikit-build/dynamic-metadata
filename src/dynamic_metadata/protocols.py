from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Protocol,
    get_args,
    runtime_checkable,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "BUILD_STATES",
    "BuildState",
    "DynamicMetadataBuildStateProtocol",
    "DynamicMetadataProtocol",
    "DynamicMetadataRequirementsProtocol",
    "DynamicMetadataWheelProtocol",
]


def __dir__() -> list[str]:
    return __all__


BuildState = Literal[
    "sdist", "wheel", "editable", "metadata_wheel", "metadata_editable"
]
BUILD_STATES: frozenset[str] = frozenset(get_args(BuildState))


@runtime_checkable
class DynamicMetadataProtocol(Protocol):
    def dynamic_metadata(
        self,
        settings: Mapping[str, Any],
        project: Mapping[str, Any],
    ) -> dict[str, Any]: ...


@runtime_checkable
class DynamicMetadataBuildStateProtocol(DynamicMetadataProtocol, Protocol):
    def build_state(self, build_state: BuildState) -> None: ...


@runtime_checkable
class DynamicMetadataRequirementsProtocol(DynamicMetadataProtocol, Protocol):
    def get_requires_for_dynamic_metadata(
        self, settings: Mapping[str, Any]
    ) -> list[str]: ...


@runtime_checkable
class DynamicMetadataWheelProtocol(DynamicMetadataProtocol, Protocol):
    def dynamic_wheel(self, settings: Mapping[str, Any]) -> dict[str, bool]: ...
