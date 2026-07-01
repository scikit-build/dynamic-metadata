from __future__ import annotations

import importlib.metadata
import sys

__all__ = ["entry_points"]


def __dir__() -> list[str]:
    return __all__


# The selectable ``group=`` keyword arrived in 3.10; before that ``entry_points()``
# takes no argument and returns a ``dict`` of groups. On 3.10+ the no-argument form
# warns, which this project's ``filterwarnings = error`` would turn into a test
# failure, so the two paths are split at import time.
if sys.version_info >= (3, 10):

    def entry_points(group: str) -> list[importlib.metadata.EntryPoint]:
        """Return the entry points in ``group`` across installed distributions."""
        return list(importlib.metadata.entry_points(group=group))

else:

    def entry_points(group: str) -> list[importlib.metadata.EntryPoint]:
        """Return the entry points in ``group`` across installed distributions."""
        # Pre-3.10 entry_points() returns a dict; pylint checks the 3.10+ stub.
        eps = importlib.metadata.entry_points()
        return list(eps.get(group, []))  # pylint: disable=no-member
