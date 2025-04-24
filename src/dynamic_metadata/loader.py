from __future__ import annotations

import dataclasses
import importlib
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, Union, runtime_checkable

from .info import ALL_FIELDS

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable

    StrMapping = Mapping[str, Any]
else:
    StrMapping = Mapping


__all__ = ["load_dynamic_metadata", "load_provider", "process_dynamic_metadata"]


def __dir__() -> list[str]:
    return __all__


@runtime_checkable
class DynamicMetadataProtocol(Protocol):
    def dynamic_metadata(
        self,
        fields: Iterable[str],
        settings: dict[str, Any],
        project: Mapping[str, Any],
    ) -> dict[str, Any]: ...


@runtime_checkable
class DynamicMetadataRequirementsProtocol(DynamicMetadataProtocol, Protocol):
    def get_requires_for_dynamic_metadata(
        self, settings: dict[str, Any]
    ) -> list[str]: ...


@runtime_checkable
class DynamicMetadataWheelProtocol(DynamicMetadataProtocol, Protocol):
    def dynamic_wheel(self, field: str, settings: Mapping[str, Any]) -> bool: ...


DMProtocols = Union[
    DynamicMetadataProtocol,
    DynamicMetadataRequirementsProtocol,
    DynamicMetadataWheelProtocol,
]


def load_provider(
    provider: str,
    provider_path: str | None = None,
) -> DMProtocols:
    if provider_path is None:
        return importlib.import_module(provider)

    if not Path(provider_path).is_dir():
        msg = "provider-path must be an existing directory"
        raise AssertionError(msg)

    try:
        sys.path.insert(0, provider_path)
        return importlib.import_module(provider)
    finally:
        sys.path.pop(0)


def load_dynamic_metadata(
    metadata: Mapping[str, Mapping[str, Any]],
) -> Generator[tuple[str, DMProtocols | None, dict[str, str]], None, None]:
    for field, orig_config in metadata.items():
        if "provider" in orig_config:
            if field not in ALL_FIELDS:
                msg = f"{field} is not a valid field"
                raise KeyError(msg)
            config = dict(orig_config)
            provider = config.pop("provider")
            provider_path = config.pop("provider-path", None)
            loaded_provider = load_provider(provider, provider_path)
            yield field, loaded_provider, config
        else:
            yield field, None, dict(orig_config)


@dataclasses.dataclass
class DynamicPyProject(StrMapping):
    settings: dict[str, dict[str, Any]]
    project: dict[str, Any]
    providers: dict[str, DMProtocols]

    def __getitem__(self, key: str) -> Any:
        # Try to get the settings from either the static file or dynamic metadata provider
        if key in self.project:
            return self.project[key]

        # Check if we are in a loop, i.e. something else is already requesting
        # this key while trying to get another key
        if key not in self.providers:
            dep_type = "missing" if key in self.settings else "circular"
            msg = f"Encountered a {dep_type} dependency at {key}"
            raise ValueError(msg)

        provider = self.providers.pop(key)
        self.project[key] = provider.dynamic_metadata(key, self.settings[key], self)
        self.project["dynamic"].remove(key)

        return self.project[key]

    def __iter__(self) -> Iterator[str]:
        # Iterate over the keys of the static settings
        yield from [*self.project.keys(), *self.providers.keys()]

    def __len__(self) -> int:
        return len(self.project) + len(self.providers)

    def __contains__(self, key: object) -> bool:
        return key in self.project or key in self.providers


def process_dynamic_metadata(
    project: Mapping[str, Any],
    metadata: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Process dynamic metadata.

    This function loads the dynamic metadata providers and calls them to
    generate the dynamic metadata. It takes the original project table and
    returns a new project table. Empty providers are not supported; you
    need to implement this yourself for now if you support that.
    """

    initial = {f: (p, s) for (f, p, s) in load_dynamic_metadata(metadata)}
    for f, (p, _) in initial.items():
        if p is None:
            msg = f"{f} does not have a provider"
            raise KeyError(msg)

    settings = DynamicPyProject(
        settings={f: s for f, (p, s) in initial.items() if p is not None},
        project=dict(project),
        providers={k: p for k, (p, _) in initial.items() if p is not None},
    )

    return dict(settings)
