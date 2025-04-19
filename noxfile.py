#!/usr/bin/env -S uv run -q

# /// script
# dependencies = ["nox>=2025.2.9"]
# ///

from __future__ import annotations

import argparse
from pathlib import Path

import nox

nox.needs_version = ">=2025.2.9"
nox.options.default_venv_backend = "uv|virtualenv"

DIR = Path(__file__).parent.resolve()
PYPROJECT = nox.project.load_toml("pyproject.toml")
TEST_DEPS = nox.project.dependency_groups(PYPROJECT, "test")
DOCS_DEPS = nox.project.dependency_groups(PYPROJECT, "docs")


@nox.session
def lint(session: nox.Session) -> None:
    """
    Run the linter.
    """
    session.install("pre-commit")
    session.run("pre-commit", "run", "--all-files", *session.posargs)


@nox.session
def pylint(session: nox.Session) -> None:
    """
    Run PyLint.
    """
    # This needs to be installed into the package environment, and is slower
    # than a pre-commit check
    session.install(".", "pylint", "setuptools_scm", "hatch-fancy-pypi-readme")
    session.run("pylint", "src", *session.posargs)


@nox.session
def tests(session: nox.Session) -> None:
    """
    Run the unit and regular tests. Use --cov to activate coverage.
    """
    session.install("-e.", *TEST_DEPS)
    session.run("pytest", *session.posargs)


@nox.session(default=False)
def docs(session: nox.Session) -> None:
    """
    Build the docs. Pass "--serve" to serve.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", help="Serve after building")
    parser.add_argument(
        "-b", dest="builder", default="html", help="Build target (default: html)"
    )
    args, posargs = parser.parse_known_args(session.posargs)

    if args.builder != "html" and args.serve:
        session.error("Must not specify non-HTML builder with --serve")

    session.install("-e.", *DOCS_DEPS)
    session.chdir("docs")

    if args.builder == "linkcheck":
        session.run(
            "sphinx-build", "-b", "linkcheck", ".", "_build/linkcheck", *posargs
        )
        return

    session.run(
        "sphinx-build",
        "-n",  # nitpicky mode
        "-T",  # full tracebacks
        "-W",  # Warnings as errors
        "--keep-going",  # See all errors
        "-b",
        args.builder,
        ".",
        f"_build/{args.builder}",
        *posargs,
    )

    if args.serve:
        session.log("Launching docs at http://localhost:8000/ - use Ctrl-C to quit")
        session.run("python", "-m", "http.server", "8000", "-d", "_build/html")


@nox.session(default=False)
def build_api_docs(session: nox.Session) -> None:
    """
    Build (regenerate) API docs.
    """

    session.install("sphinx")
    session.chdir("docs")
    session.run(
        "sphinx-apidoc",
        "-o",
        "api/",
        "--module-first",
        "--no-toc",
        "--force",
        "../src/dynamic_metadata",
    )


@nox.session(default=False)
def build(session: nox.Session) -> None:
    """
    Build an SDist and wheel.
    """

    session.install("build")
    session.run("python", "-m", "build")


if __name__ == "__main__":
    nox.main()
