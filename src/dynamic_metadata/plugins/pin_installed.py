from __future__ import annotations

import importlib.metadata
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["dynamic_metadata", "dynamic_wheel", "get_requires_for_dynamic_metadata"]


def __dir__() -> list[str]:
    return __all__


KEYS = {"packages"}

# A PEP 508 name followed by a specifier-set template; the name's character
# class excludes the operator characters, so the split is unambiguous.
_PACKAGE_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(?P<specifiers>[<>=!~].*)?$"
)
_SPECIFIER_RE = re.compile(r"^\s*(?P<op>===|==|!=|<=|>=|<|>|~=)\s*(?P<version>\S+)\s*$")
_COMPONENT_RE = re.compile(r"^x(?:\+(?P<add>\d+))?$")
# The release portion of an installed (PEP 440) version; epoch and any
# pre/post/dev/local suffix are dropped for substitution.
_RELEASE_RE = re.compile(r"^v?(?:\d+!)?(?P<release>\d+(?:\.\d+)*)")


def _packages(settings: Mapping[str, Any]) -> list[str]:
    if settings.keys() - KEYS:
        msg = f"Only {KEYS} settings allowed by this plugin"
        raise RuntimeError(msg)
    if "packages" not in settings:
        msg = "Must contain the 'packages' setting listing requirement templates"
        raise RuntimeError(msg)
    packages = settings["packages"]
    if not isinstance(packages, list) or not all(isinstance(p, str) for p in packages):
        msg = "Setting 'packages' must be a list of strings"
        raise TypeError(msg)
    return packages


def _parse(package: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a template into the distribution name and (operator, version) pairs."""
    match = _PACKAGE_RE.match(package)
    if match is None:
        msg = f"Invalid package template {package!r}"
        raise RuntimeError(msg)
    if match["specifiers"] is None:
        msg = f"Package template {package!r} must include a specifier like '==x.x.*'"
        raise RuntimeError(msg)
    specifiers = []
    for part in match["specifiers"].split(","):
        specifier = _SPECIFIER_RE.match(part)
        if specifier is None:
            msg = f"Invalid specifier {part.strip()!r} in {package!r}"
            raise RuntimeError(msg)
        specifiers.append((specifier["op"], specifier["version"]))
    return match["name"], specifiers


def _fill(op: str, template: str, release: list[str], package: str) -> str:
    """Substitute the installed release into one version template.

    Each dot-separated component is ``x`` (that release component, 0 when the
    release is shorter), ``x+N`` (that component plus N, for a ``<x+1`` cap), a
    literal number, or a trailing ``*`` (PEP 440 wildcard, ``==``/``!=`` only).
    """
    parts = template.split(".")
    out = []
    for i, part in enumerate(parts):
        if part == "*":
            if i != len(parts) - 1:
                msg = f"'*' must be the last component in {package!r}"
                raise RuntimeError(msg)
            if op not in {"==", "!="}:
                msg = f"'*' requires the '==' or '!=' operator in {package!r}"
                raise RuntimeError(msg)
            out.append(part)
        elif part.isdigit():
            out.append(part)
        else:
            component = _COMPONENT_RE.match(part)
            if component is None:
                msg = (
                    f"Invalid version component {part!r} in {package!r}; "
                    "use 'x', 'x+N', '*', or a number"
                )
                raise RuntimeError(msg)
            value = int(release[i]) if i < len(release) else 0
            out.append(str(value + int(component["add"] or 0)))
    return ".".join(out)


def _resolve(package: str) -> str:
    name, specifiers = _parse(package)
    try:
        version = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        msg = (
            f"Package {name!r} is not installed; it must be present in the "
            "build environment to pin against"
        )
        raise RuntimeError(msg) from exc
    release_match = _RELEASE_RE.match(version)
    if release_match is None:
        msg = f"Installed version {version!r} of {name!r} is not PEP 440"
        raise RuntimeError(msg)
    release = release_match["release"].split(".")
    return name + ",".join(
        op + _fill(op, template, release, package) for op, template in specifiers
    )


def dynamic_metadata(
    settings: Mapping[str, Any],
    _project: Mapping[str, Any],
) -> dict[str, Any]:
    return {"dependencies": [_resolve(package) for package in _packages(settings)]}


def dynamic_wheel(settings: Mapping[str, Any]) -> dict[str, bool]:
    # The pins depend on what the build environment resolves, so a wheel's
    # dependencies legitimately differ from the SDist's PKG-INFO.
    return {"dependencies": bool(_packages(settings))}


def get_requires_for_dynamic_metadata(settings: Mapping[str, Any]) -> list[str]:
    # The bare names, so the packages are present when dynamic_metadata runs;
    # constrain the build version in [build-system].requires if needed.
    return [_parse(package)[0] for package in _packages(settings)]
