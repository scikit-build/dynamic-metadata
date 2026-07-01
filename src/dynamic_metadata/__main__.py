from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ._compat import tomllib
from .loader import BUILD_STATES, list_providers, process_dynamic_metadata

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .loader import BuildState

__all__ = ["main"]


def __dir__() -> list[str]:
    return __all__


def main_show(args: argparse.Namespace, /) -> None:
    """Print the project table with dynamic metadata resolved, as JSON."""
    with Path(args.pyproject_toml).open("rb") as f:
        pyproject = tomllib.load(f)

    project = pyproject.get("project", {})
    entries = pyproject.get("tool", {}).get("dynamic-metadata", [])
    if entries:
        project = process_dynamic_metadata(
            project, entries, cast("BuildState", args.state)
        )
    print(json.dumps(project, indent=2))


def main_providers(_args: argparse.Namespace, /) -> None:
    """Print the registered provider names and where each resolves to."""
    providers = list_providers()
    if not providers:
        print("No providers registered.")
        return
    width = max(len(name) for name in providers)
    for name in sorted(providers):
        print(f"{name:<{width}}  {providers[name]}")


def populate_parser(parser: argparse.ArgumentParser, /) -> None:
    """Add the ``dynamic-metadata`` subcommands to an existing parser."""
    subparsers = parser.add_subparsers(required=True, help="Commands")
    providers = subparsers.add_parser(
        "providers",
        help="List the registered dynamic-metadata providers",
        description="Lists every provider registered in the "
        "'dynamic_metadata.provider' entry-point group (the bundled plugins "
        "plus any installed third-party plugins) and where each resolves to.",
    )
    providers.set_defaults(func=main_providers)
    show = subparsers.add_parser(
        "show",
        help="Show the project table with dynamic metadata resolved",
        description="Reads pyproject.toml, runs the configured "
        "[[tool.dynamic-metadata]] plugins in order, and prints the resulting "
        "[project] table as JSON.",
    )
    show.set_defaults(func=main_show)
    show.add_argument(
        "--pyproject-toml",
        default="pyproject.toml",
        help="Path to the pyproject.toml to read (default: ./pyproject.toml)",
    )
    show.add_argument(
        "--state",
        choices=sorted(BUILD_STATES),
        default="metadata_wheel",
        help="The build state to resolve metadata for (default: metadata_wheel)",
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="dynamic-metadata",
        allow_abbrev=False,
        description="dynamic-metadata command line interface.",
    )
    populate_parser(parser)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
