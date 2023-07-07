"""
Copyright (c) 2023 Henry Schreiner. All rights reserved.

dynamic-metadata: This project is intended to document dynamic-metadata support.
"""


from __future__ import annotations

import sys

if sys.version_info < (3, 10):
    from typing_extensions import TypeAlias
else:
    from typing import TypeAlias

if sys.version_info < (3, 11):
    from typing_extensions import Self, assert_never
else:
    from typing import Self, assert_never

__all__ = ["TypeAlias", "Self", "assert_never"]


def __dir__() -> list[str]:
    return __all__
