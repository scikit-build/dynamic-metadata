from __future__ import annotations

__all__ = [
    "ALL_FIELDS",
    "DICT_STR_FIELDS",
    "DUAL_FIELDS",
    "EXTENDABLE_FIELDS",
    "LIST_DICT_FIELDS",
    "LIST_STR_FIELDS",
    "METADATA_HEADERS",
    "SCALAR_FIELDS",
    "STR_FIELDS",
]

# Name is not dynamically settable, so not in this list
STR_FIELDS = frozenset(
    [
        "version",
        "description",
        "requires-python",
        "license",
    ]
)

# Dynamic is not dynamically settable, so not in this list. The import-* fields
# come from PEP 794 (core metadata 2.5).
LIST_STR_FIELDS = frozenset(
    [
        "classifiers",
        "keywords",
        "dependencies",
        "license-files",
        "import-names",
        "import-namespaces",
    ]
)

DICT_STR_FIELDS = frozenset(
    [
        "urls",
        "scripts",
        "gui-scripts",
    ]
)

LIST_DICT_FIELDS = frozenset(
    [
        "authors",
        "maintainers",
    ]
)

# Fields that accept either a string or a table of strings. "readme" takes a
# path shorthand or a {file|text, content-type} table; "license" takes an SPDX
# expression (PEP 639) or the classic {file} / {text} table.
DUAL_FIELDS = frozenset(
    [
        "readme",
        "license",
    ]
)

# Single-value fields: a later entry replaces the value rather than extending it,
# and PEP 808 forbids giving them both statically and dynamically.
SCALAR_FIELDS = STR_FIELDS | frozenset(["readme"])

# "dynamic" and "name" can't be set or requested
ALL_FIELDS = (
    STR_FIELDS
    | LIST_STR_FIELDS
    | DICT_STR_FIELDS
    | LIST_DICT_FIELDS
    | frozenset(
        [
            "optional-dependencies",
            "readme",
            "entry-points",
        ]
    )
)

# Fields that PEP 808 allows to be given statically in [project] *and* listed in
# dynamic, letting a provider only add to the static portion: everything except
# the scalar fields (string fields and readme), which hold a single value and so
# cannot be extended.
EXTENDABLE_FIELDS = ALL_FIELDS - SCALAR_FIELDS

# Core-metadata header(s) each field maps to, for the METADATA 2.2 ``Dynamic``
# header (mirrors pyproject-metadata's ``field_to_metadata``). Entry-point
# fields have no header, since they live in ``entry_points.txt``.
METADATA_HEADERS: dict[str, frozenset[str]] = {
    "authors": frozenset(["Author", "Author-Email"]),
    "classifiers": frozenset(["Classifier"]),
    "dependencies": frozenset(["Requires-Dist"]),
    "description": frozenset(["Summary"]),
    "entry-points": frozenset(),
    "gui-scripts": frozenset(),
    "import-names": frozenset(["Import-Name"]),
    "import-namespaces": frozenset(["Import-Namespace"]),
    "keywords": frozenset(["Keywords"]),
    "license": frozenset(["License", "License-Expression"]),
    "license-files": frozenset(["License-File"]),
    "maintainers": frozenset(["Maintainer", "Maintainer-Email"]),
    "optional-dependencies": frozenset(["Provides-Extra", "Requires-Dist"]),
    "readme": frozenset(["Description", "Description-Content-Type"]),
    "requires-python": frozenset(["Requires-Python"]),
    "scripts": frozenset(),
    "urls": frozenset(["Project-URL"]),
    "version": frozenset(["Version"]),
}
