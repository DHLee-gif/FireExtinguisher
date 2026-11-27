"""Latest-value exchange between independent processes (one JSON file per area)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DEFAULT_FOLDER = Path("/dev/shm/firecar")


def write_value(name: str, value: dict, captured_ns: int, folder: Path = DEFAULT_FOLDER) -> None:
    """captured_ns is when the sensor measured it, not when processing finished."""
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f"{name}.json.tmp"
    temporary.write_text(json.dumps({"captured_ns": captured_ns, "value": value}, allow_nan=False))
    os.replace(temporary, folder / f"{name}.json")


def read_value(name: str, max_age_s: float, folder: Path = DEFAULT_FOLDER) -> dict | None:
    """Return the value, or None ("no value") when missing, damaged, or too old."""
    try:
        record = json.loads((folder / f"{name}.json").read_text())
        age_s = (time.monotonic_ns() - record["captured_ns"]) / 1e9
        value = record["value"]
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return None
    return value if 0 <= age_s <= max_age_s else None
