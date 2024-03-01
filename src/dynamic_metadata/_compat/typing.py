"""
Copyright (c) 2023 Henry Schreiner. All rights reserved.

dynamic-metadata: This project is intended to document dynamic-metadata support.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 8):
    from typing_extensions import Protocol
else:
    from typing import Protocol

__all__ = ["Protocol"]


def __dir__() -> list[str]:
    return __all__
