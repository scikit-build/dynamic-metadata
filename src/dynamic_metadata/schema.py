from __future__ import annotations

import json
from importlib import resources
from typing import Any


def get_schema() -> dict[str, Any]:
    with (
        resources.files("dynamic_metadata")
        .joinpath("resources/toml_schema.json")
        .open(encoding="utf-8")
    ) as f:
        return json.load(f)  # type: ignore[no-any-return]
