from __future__ import annotations

import dataclasses
import difflib
import importlib
import importlib.abc
import importlib.machinery
import inspect
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)

from ._compat import metadata
from .errors import (
    ConfigError,
    InvalidFieldError,
    ProviderLoadError,
    ProviderNotFoundError,
)
from .info import (
    ALL_FIELDS,
    DICT_STR_FIELDS,
    EXTENDABLE_FIELDS,
    LIST_DICT_FIELDS,
    LIST_STR_FIELDS,
    METADATA_HEADERS,
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
    from collections.abc import Generator, Iterable
    from importlib.machinery import ModuleSpec
    from importlib.metadata import EntryPoint
    from types import ModuleType


__all__ = [
    "Resolved",
    "dynamic_wheel_fields",
    "entries_from_pyproject",
    "get_requires_for_dynamic_metadata",
    "load_dynamic_metadata",
    "load_provider",
    "process_dynamic_metadata",
    "resolve",
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
            raise ProviderNotFoundError(msg)
        return spec


def _merge_dict(
    field: str, base: Mapping[str, Any], additions: Mapping[str, Any]
) -> dict[str, Any]:
    """Add new keys to a table; a provider may not change existing values."""
    merged = dict(base)
    for key, value in additions.items():
        if key in merged and merged[key] != value:
            msg = f"Provider for {field!r} may not modify existing key {key!r}"
            raise InvalidFieldError(msg)
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
        raise InvalidFieldError(msg)

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
        raise ConfigError(msg)

    module_name, _, class_name = module.partition(":")
    finder = _ProviderPathFinder([path], module_name)
    sys.meta_path.insert(0, finder)
    try:
        imported = importlib.import_module(module_name)
    except ProviderNotFoundError:
        raise
    except ImportError as exc:
        msg = f"Could not load provider {module!r} from {path!r}: {exc}"
        raise ProviderLoadError(msg) from exc
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
        raise ProviderNotFoundError(msg)
    if len(eps) > 1:
        dists = ", ".join(sorted(_entry_point_dist(ep) or ep.value for ep in eps))
        msg = (
            f"Provider name {name!r} is registered by multiple distributions "
            f"({dists}); use an explicit 'module' or 'module:Class' provider"
        )
        raise ConfigError(msg)
    ep = eps[0]
    try:
        return ep.load()
    except (ImportError, AttributeError) as exc:
        msg = f"Could not load provider {name!r} ({ep.value!r}): {exc}"
        raise ProviderLoadError(msg) from exc


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
        raise ConfigError(msg)
    return cast("DynamicMetadataProtocol", obj() if inspect.isclass(obj) else obj)


def _validate_entries(entries: object) -> list[Mapping[str, Any]]:
    if not isinstance(entries, Sequence) or isinstance(entries, str):
        msg = "tool.dynamic-metadata must be an array of tables"
        raise ConfigError(msg)
    for entry in entries:
        if not isinstance(entry, Mapping):
            msg = "tool.dynamic-metadata must be an array of tables"
            raise ConfigError(msg)
        if "provider" not in entry:
            msg = "Each [[tool.dynamic-metadata]] entry must set a 'provider'"
            raise ConfigError(msg)
    return list(entries)


def entries_from_pyproject(pyproject: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the validated ``[[tool.dynamic-metadata]]`` entries of a parsed ``pyproject.toml``.

    Returns ``[]`` if the table is absent. Raises
    :class:`~dynamic_metadata.errors.ConfigError` if it is not an array of
    tables or an entry lacks ``provider``.
    """
    tool = pyproject.get("tool", {})
    if not isinstance(tool, Mapping):
        msg = "tool must be a table"
        raise ConfigError(msg)
    return [
        dict(entry) for entry in _validate_entries(tool.get("dynamic-metadata", []))
    ]


def load_dynamic_metadata(
    entries: Sequence[Mapping[str, Any]],
) -> Generator[tuple[DynamicMetadataProtocol, dict[str, Any]], None, None]:
    """Load each entry's provider, yielding it with its plugin settings.

    Entries are processed in order; ``provider`` is consumed here and the
    remaining keys are returned as plugin settings.
    """
    for entry in _validate_entries(entries):
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
        raise ConfigError(msg)

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
                raise InvalidFieldError(msg)
            if field not in declared_dynamic:
                msg = f"{field!r} must be listed in project.dynamic to be set"
                raise InvalidFieldError(msg)

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

    A provider that is found but fails to import — typically because it imports
    at module level a package it would have declared as its own requirement —
    is skipped, since its hook cannot be asked; the import error surfaces
    later, when the metadata is resolved. An unknown provider name or a missing
    local module still raises.
    """
    requires: list[str] = []
    for entry in _validate_entries(entries):
        settings = {k: v for k, v in entry.items() if k != "provider"}
        try:
            provider = load_provider(entry["provider"])
        except ProviderLoadError:
            continue
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
                raise InvalidFieldError(msg)
            if field == "version" and is_dynamic:
                msg = "'version' may never differ between the SDist and a wheel"
                raise InvalidFieldError(msg)
            if is_dynamic:
                fields.add(field)
    return fields


@dataclasses.dataclass(frozen=True)
class Resolved:
    """The result of :func:`resolve`."""

    #: The new ``[project]`` table. Fields a provider produced are removed from
    #: ``dynamic``, as are the SDist-dynamic fields below.
    project: dict[str, Any]
    #: For an SDist build, the fields whose value may differ in a wheel built
    #: from it (METADATA 2.2 ``Dynamic``); empty for every other build state.
    dynamic_fields: frozenset[str] = frozenset()

    @property
    def dynamic_headers(self) -> tuple[str, ...]:
        """``dynamic_fields`` as sorted core-metadata header names (``Dynamic:`` values)."""
        return tuple(
            sorted(
                {h for field in self.dynamic_fields for h in METADATA_HEADERS[field]}
            )
        )


def resolve(
    pyproject: Mapping[str, Any],
    build_state: BuildState,
    *,
    backend_fields: Iterable[str] = (),
    strict: bool = True,
) -> Resolved:
    """Resolve a whole parsed ``pyproject.toml``, handling the ``dynamic`` bookkeeping.

    This is :func:`entries_from_pyproject`, :func:`process_dynamic_metadata`,
    and (for ``"sdist"``) :func:`dynamic_wheel_fields` in one call. If there are
    no entries the ``[project]`` table is returned unchanged (``{}`` if absent);
    if there are entries but no ``[project]`` table, :class:`~dynamic_metadata.errors.ConfigError` is
    raised.

    For an SDist build, the fields the providers report as wheel-dynamic are
    removed from ``dynamic`` (so the ``PKG-INFO`` is valid) and returned as
    ``dynamic_fields`` for the backend to write as ``Dynamic:`` headers.

    With ``strict`` (the default), a field still listed in ``dynamic`` after
    that — declared dynamic but produced by no provider — raises
    :class:`~dynamic_metadata.errors.ConfigError`, unless it is in ``backend_fields``, the fields the
    backend fills in itself (for example ``version`` read from a build file).
    """
    entries = entries_from_pyproject(pyproject)
    if not entries:
        return Resolved(dict(pyproject.get("project", {})))
    if "project" not in pyproject:
        msg = "[[tool.dynamic-metadata]] entries require a [project] table"
        raise ConfigError(msg)

    project = process_dynamic_metadata(pyproject["project"], entries, build_state)
    wheel_fields = (
        frozenset(dynamic_wheel_fields(entries))
        if build_state == "sdist"
        else frozenset()
    )
    unset = set(project["dynamic"]) - wheel_fields - set(backend_fields)
    if strict and unset:
        msg = (
            "Fields declared in project.dynamic but not set by any "
            f"dynamic-metadata provider: {', '.join(sorted(unset))}"
        )
        raise ConfigError(msg)
    project["dynamic"] = [f for f in project["dynamic"] if f not in wheel_fields]
    return Resolved(project, wheel_fields)
