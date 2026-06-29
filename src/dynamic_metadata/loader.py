from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
from pathlib import Path
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Protocol,
    Union,
    get_args,
    runtime_checkable,
)

from .info import (
    ALL_FIELDS,
    DICT_STR_FIELDS,
    EXTENDABLE_FIELDS,
    LIST_DICT_FIELDS,
    LIST_STR_FIELDS,
    SCALAR_FIELDS,
)

BuildState = Literal[
    "sdist", "wheel", "editable", "metadata_wheel", "metadata_editable"
]
BUILD_STATES: frozenset[str] = frozenset(get_args(BuildState))

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence
    from importlib.machinery import ModuleSpec
    from types import ModuleType


__all__ = [
    "BuildState",
    "load_dynamic_metadata",
    "load_provider",
    "process_dynamic_metadata",
]


def __dir__() -> list[str]:
    return __all__


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


DMProtocols = Union[
    DynamicMetadataProtocol,
    DynamicMetadataBuildStateProtocol,
    DynamicMetadataRequirementsProtocol,
    DynamicMetadataWheelProtocol,
]

# Per-entry keys consumed by the loader itself; everything else is plugin
# settings, passed through verbatim to the provider.
RESERVED_KEYS = frozenset(["provider", "provider-path"])


class _ProviderPathFinder(importlib.abc.MetaPathFinder):
    """Load the top-level provider module from ``provider-path``.

    Mirrors how pyproject_hooks handles PEP 517 ``backend-path``: a finder at
    the front of ``sys.meta_path`` guarantees the in-tree provider wins over a
    same-named module elsewhere on ``sys.path`` (or behind another finder), and
    a provider absent from ``provider-path`` raises instead of silently
    importing the wrong module. Only the top-level name is intercepted; nested
    modules resolve through the parent package's path. A provider already cached
    in ``sys.modules`` short-circuits import and bypasses this finder.
    """

    def __init__(self, provider_path: list[str], provider: str) -> None:
        self.provider_path = provider_path
        self.provider = provider
        self.provider_parent = provider.partition(".")[0]

    def find_spec(
        self,
        fullname: str,
        _path: Sequence[str] | None,
        _target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if "." in fullname:
            return None

        spec = importlib.machinery.PathFinder.find_spec(
            fullname, path=self.provider_path
        )
        if spec is None and fullname == self.provider_parent:
            msg = f"Cannot find module {self.provider!r} in {self.provider_path!r}"
            raise ModuleNotFoundError(msg)
        return spec


def _merge_dict(
    field: str, base: Mapping[str, Any], additions: Mapping[str, Any]
) -> dict[str, Any]:
    """Add new keys to a table; a provider may not change existing values."""
    merged = dict(base)
    for key, value in additions.items():
        if key in merged and merged[key] != value:
            msg = f"Provider for {field!r} may not modify existing key {key!r}"
            raise ValueError(msg)
        merged[key] = value
    return merged


def _merge_metadata(field: str, static: Any, dynamic: Any) -> Any:
    """Merge a current value with a provider's additions (PEP 808).

    Existing entries are preserved as-is and kept first; the provider's value is
    appended after them. Lists are concatenated verbatim, so a provider should
    return only its additions and may add a value already present. Single-value
    fields (string fields, readme) cannot be extended; merging onto a static
    value of one is the invalid "static *and* dynamic" case and raises.
    """
    if field not in EXTENDABLE_FIELDS:
        msg = f"Field {field!r} cannot be given both statically and dynamically"
        raise ValueError(msg)

    if field in LIST_STR_FIELDS or field in LIST_DICT_FIELDS:
        return [*static, *dynamic]

    if field in DICT_STR_FIELDS:
        return _merge_dict(field, static, dynamic)

    if field == "optional-dependencies":
        merged_extras = {extra: list(deps) for extra, deps in static.items()}
        for extra, deps in dynamic.items():
            merged_extras.setdefault(extra, []).extend(deps)
        return merged_extras

    # entry-points: a table of groups, each a table of name -> object reference
    merged_groups = {group: dict(eps) for group, eps in static.items()}
    for group, eps in dynamic.items():
        merged_groups[group] = _merge_dict(
            f"entry-points group {group!r}", merged_groups.get(group, {}), eps
        )
    return merged_groups


def load_provider(
    provider: str,
    provider_path: str | None = None,
) -> DMProtocols:
    """Load a provider, returning the object whose hooks are called.

    ``provider`` is either a module path (``"pkg.mod"``) or a module path and a
    class within it (``"pkg.mod:Class"``). A bare module is returned as-is, so
    its hooks are plain module-level functions; a class is instantiated with no
    arguments and the instance is returned, so its hooks are bound methods and
    may share state through ``self`` (e.g. the optional ``build_state`` hook
    stashing the build state for ``dynamic_metadata`` to read).
    """
    module_name, _, class_name = provider.partition(":")

    if provider_path is None:
        module = importlib.import_module(module_name)
    else:
        if not Path(provider_path).is_dir():
            msg = "provider-path must be an existing directory"
            raise AssertionError(msg)
        finder = _ProviderPathFinder([provider_path], module_name)
        sys.meta_path.insert(0, finder)
        try:
            module = importlib.import_module(module_name)
        finally:
            sys.meta_path.remove(finder)

    return getattr(module, class_name)() if class_name else module


def load_dynamic_metadata(
    entries: Sequence[Mapping[str, Any]],
) -> Generator[tuple[DMProtocols, dict[str, Any]], None, None]:
    """Load each entry's provider, yielding it with its plugin settings.

    Entries are processed in order; ``provider`` and ``provider-path`` are
    consumed here and the remaining keys are returned as plugin settings.
    """
    for entry in entries:
        if "provider" not in entry:
            msg = "Each [[tool.dynamic-metadata]] entry must set a 'provider'"
            raise KeyError(msg)
        settings = {k: v for k, v in entry.items() if k not in RESERVED_KEYS}
        provider = load_provider(entry["provider"], entry.get("provider-path"))
        yield provider, settings


def process_dynamic_metadata(
    project: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    build_state: BuildState,
) -> dict[str, Any]:
    """Process dynamic metadata.

    Takes the original ``[project]`` table and an ordered list of
    ``[[tool.dynamic-metadata]]`` entries, and returns a new project table.
    Entries run in list order: each provider is called with a read-only snapshot
    of the project as resolved so far, so a later entry can read a field an
    earlier one produced via ``project[...]``. A provider returns a ``dict``
    fragment of the project table (``{field: value, ...}``) which is merged in.

    ``build_state`` is the backend's description of the current build. It must
    be one of these build states (``BUILD_STATES``): ``"sdist"``, ``"wheel"``,
    ``"editable"``, ``"metadata_wheel"``, or ``"metadata_editable"``. A provider
    that cares about it implements an optional ``build_state`` hook, called with
    this value before ``dynamic_metadata``; providers that ignore it simply omit
    the hook.
    """

    if build_state not in BUILD_STATES:
        msg = f"build_state must be one of {sorted(BUILD_STATES)}, got {build_state!r}"
        raise ValueError(msg)

    result = dict(project)
    result["dynamic"] = list(result.get("dynamic", []))
    declared_dynamic = set(result["dynamic"])
    snapshot = MappingProxyType(result)

    # Fields already written by an earlier entry: a further entry merges onto
    # that result (and may *replace* a scalar), as opposed to a static value
    # still sitting in [project], which is the PEP 808 add-only case.
    produced: set[str] = set()

    for provider, settings in load_dynamic_metadata(entries):
        if isinstance(provider, DynamicMetadataBuildStateProtocol):
            provider.build_state(build_state)
        fragment = provider.dynamic_metadata(settings, snapshot)

        for field in fragment:
            if field not in ALL_FIELDS:
                msg = f"{field!r} is not a settable dynamic-metadata field"
                raise KeyError(msg)
            if field not in declared_dynamic:
                msg = f"{field!r} must be listed in project.dynamic to be set"
                raise KeyError(msg)

        for field, value in fragment.items():
            if field in produced:
                # A second entry for this field: extend its prior result, or for
                # a single-value field replace it (a transform pipeline).
                result[field] = (
                    value
                    if field in SCALAR_FIELDS
                    else _merge_metadata(field, result[field], value)
                )
            elif field in result:
                # PEP 808: a static value is present; the provider only adds.
                result[field] = _merge_metadata(field, result[field], value)
            else:
                result[field] = value
            produced.add(field)
            if field in result["dynamic"]:
                result["dynamic"].remove(field)

    return result
