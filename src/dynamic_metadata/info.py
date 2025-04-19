from __future__ import annotations

__all__ = ["ALL_FIELDS", "DICT_STR_FIELDS", "LIST_STR_FIELDS", "STR_FIELDS"]


# Name is not dynamically settable, so not in this list
STR_FIELDS = frozenset(
    [
        "version",
        "description",
        "requires-python",
        "license",
    ]
)

# Dynamic is not dynamically settable, so not in this list
LIST_STR_FIELDS = frozenset(
    [
        "classifiers",
        "keywords",
        "dependencies",
        "license_files",
    ]
)


DICT_STR_FIELDS = frozenset(
    [
        "urls",
        "authors",
        "maintainers",
    ]
)


# "dynamic" and "name" can't be set or requested
ALL_FIELDS = (
    STR_FIELDS
    | LIST_STR_FIELDS
    | DICT_STR_FIELDS
    | frozenset(
        [
            "optional-dependencies",
            "readme",
        ]
    )
)
