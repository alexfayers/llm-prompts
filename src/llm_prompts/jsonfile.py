"""Write text and JSON files atomically."""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` through a scratch file and a rename.

    A symlink is followed, so the scratch file sits beside its target and the link stays.
    An existing file keeps its mode, and stays untouched when the write fails.
    """
    path = Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        scratch.write_text(text, encoding="utf-8")
        if path.exists():
            shutil.copymode(path, scratch)
        scratch.replace(path)
    except BaseException:
        scratch.unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, data: Any) -> None:
    """Write ``data`` as indented JSON to ``path`` through a scratch file and a rename."""
    write_text_atomic(path, json.dumps(data, indent=2) + "\n")
