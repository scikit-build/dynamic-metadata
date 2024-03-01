from __future__ import annotations

import json
import sys
from typing import Any

if sys.version_info < (3, 9):
    import importlib_resources as resources
else:
    from importlib import resources


def get_schema() -> dict[str, Any]:
    with resources.files("dynamic_metadata").joinpath(
        "resources/toml_schema.json"
    ).open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]
