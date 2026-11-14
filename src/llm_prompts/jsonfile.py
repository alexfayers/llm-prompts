"""Write JSON files atomically."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: Any) -> None:
    """Write ``data`` as indented JSON to ``path`` through a scratch file and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    scratch.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    scratch.replace(path)
