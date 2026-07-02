from __future__ import annotations

import difflib
import importlib
import importlib.abc
import importlib.machinery
import inspect
import sys
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)

from ._compat import metadata
from .info import (
    ALL_FIELDS,
    DICT_STR_FIELDS,
    EXTENDABLE_FIELDS,
    LIST_DICT_FIELDS,
    LIST_STR_FIELDS,
    SCALAR_FIELDS,
)
from .protocols import (
    BUILD_STATES,
    BuildState,
    DynamicMetadataBuildStateProtocol,
    DynamicMetadataProtocol,
    DynamicMetadataRequirementsProtocol,
    DynamicMetadataWheelProtocol,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence
    from importlib.machinery import ModuleSpec
    from importlib.metadata import EntryPoint
    from types import ModuleType


__all__ = [
    "dynamic_wheel_fields",
    "get_requires_for_dynamic_metadata",
    "load_dynamic_metadata",
    "load_provider",
    "process_dynamic_metadata",
]


def __dir__() -> list[str]:
    return __all__


# Entry-point group a plugin distribution registers a named provider under. The
# bundled plugins register here too (see pyproject.toml).
PROVIDER_GROUP = "dynamic_metadata.provider"


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


def _import_provider(module: str, path: str) -> Any:
    """Import ``module`` (``"pkg.mod"`` or ``"pkg.mod:Class"``) from the ``path`` directory.

    Returns the module, or the named attribute within it, without instantiating.
    """
    if not Path(path).is_dir():
        msg = f"provider 'path' {path!r} must be an existing directory"
        raise ValueError(msg)

    module_name, _, class_name = module.partition(":")
    finder = _ProviderPathFinder([path], module_name)
    sys.meta_path.insert(0, finder)
    try:
        imported = importlib.import_module(module_name)
    finally:
        sys.meta_path.remove(finder)

    return getattr(imported, class_name) if class_name else imported


def _entry_point_dist(ep: EntryPoint) -> str | None:
    """Best-effort distribution name for an entry point (for messages)."""
    dist = getattr(ep, "dist", None)
    return getattr(dist, "name", None) if dist is not None else None


def _load_entry_point(name: str) -> Any:
    """Load the provider registered under ``name`` in ``PROVIDER_GROUP``.

    Raises if ``name`` is unknown (with a spelling hint), is registered by more
    than one distribution (a non-deterministic collision), or fails to import.
    """
    all_eps = list(metadata.entry_points(PROVIDER_GROUP))
    eps = [ep for ep in all_eps if ep.name == name]
    if not eps:
        known = sorted({ep.name for ep in all_eps})
        matches = difflib.get_close_matches(name, known)
        hint = f"; did you mean {matches[0]!r}?" if matches else ""
        available = ", ".join(known) or "none"
        msg = f"Unknown provider {name!r}{hint} (available: {available})"
        raise ModuleNotFoundError(msg)
    if len(eps) > 1:
        dists = ", ".join(sorted(_entry_point_dist(ep) or ep.value for ep in eps))
        msg = (
            f"Provider name {name!r} is registered by multiple distributions "
            f"({dists}); use an explicit 'module' or 'module:Class' provider"
        )
        raise ValueError(msg)
    ep = eps[0]
    try:
        return ep.load()
    except (ImportError, AttributeError) as exc:
        msg = f"Could not load provider {name!r} ({ep.value!r}): {exc}"
        raise ImportError(msg) from exc


def load_provider(provider: object) -> DynamicMetadataProtocol:
    """Load a provider from its config value, returning the object whose hooks are called.

    ``provider`` is the value of the ``provider`` key in a
    ``[[tool.dynamic-metadata]]`` entry, in one of two forms:

    * a **string** — a name registered in the ``PROVIDER_GROUP`` entry-point
      group. Installed plugins are only reachable this way; a raw import path is
      not accepted.
    * an **inline table** ``{path, module}`` — a local plugin imported from the
      ``path`` directory as a module path (``"pkg.mod"`` or ``"pkg.mod:Class"``),
      for a plugin living inside the project being built. Entry points are not
      consulted.

    A bare module is returned as-is (hooks are module-level functions); a class
    is instantiated with no arguments so its hooks are bound methods sharing
    state through ``self``; an already-instantiated object is used directly.
    """
    if isinstance(provider, str):
        obj = _load_entry_point(provider)
    elif isinstance(provider, Mapping) and set(provider) == {"path", "module"}:
        obj = _import_provider(provider["module"], provider["path"])
    else:
        msg = (
            "'provider' must be a registered name (string) or an inline table "
            "with exactly 'path' and 'module' keys"
        )
        raise ValueError(msg)
    return cast("DynamicMetadataProtocol", obj() if inspect.isclass(obj) else obj)


def load_dynamic_metadata(
    entries: Sequence[Mapping[str, Any]],
) -> Generator[tuple[DynamicMetadataProtocol, dict[str, Any]], None, None]:
    """Load each entry's provider, yielding it with its plugin settings.

    Entries are processed in order; ``provider`` is consumed here and the
    remaining keys are returned as plugin settings.
    """
    for entry in entries:
        if "provider" not in entry:
            msg = "Each [[tool.dynamic-metadata]] entry must set a 'provider'"
            raise KeyError(msg)
        # 'provider' is the only key the loader consumes; the rest are plugin
        # settings, passed through verbatim to the provider.
        settings = {k: v for k, v in entry.items() if k != "provider"}
        yield load_provider(entry["provider"]), settings


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


def get_requires_for_dynamic_metadata(
    entries: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Collect every provider's extra build requirements, in entry order.

    Call this from each PEP 517 ``get_requires_for_build_*`` hook. A provider
    without the optional ``get_requires_for_dynamic_metadata`` hook contributes
    nothing.
    """
    requires = []
    for provider, settings in load_dynamic_metadata(entries):
        if isinstance(provider, DynamicMetadataRequirementsProtocol):
            requires += provider.get_requires_for_dynamic_metadata(settings)
    return requires


def dynamic_wheel_fields(entries: Sequence[Mapping[str, Any]]) -> set[str]:
    """Collect the fields to mark ``Dynamic`` in SDist metadata (METADATA 2.2).

    Asks each provider's optional ``dynamic_wheel`` hook which fields may
    legitimately differ between the SDist and a wheel built from it. A field is
    dynamic if *any* provider reports it ``True``: contributions to a field
    merge, so one dynamic part makes the merged value dynamic (PEP 643 permits
    marking a field ``Dynamic`` even when its value is also given). A field no
    provider mentions is not dynamic, and ``version`` may never be.

    Providers are loaded fresh here, so ``dynamic_wheel`` cannot rely on state
    from a ``dynamic_metadata`` call.
    """
    fields: set[str] = set()
    for provider, settings in load_dynamic_metadata(entries):
        if not isinstance(provider, DynamicMetadataWheelProtocol):
            continue
        for field, is_dynamic in provider.dynamic_wheel(settings).items():
            if field not in ALL_FIELDS:
                msg = f"{field!r} is not a settable dynamic-metadata field"
                raise KeyError(msg)
            if field == "version" and is_dynamic:
                msg = "'version' may never differ between the SDist and a wheel"
                raise ValueError(msg)
            if is_dynamic:
                fields.add(field)
    return fields
