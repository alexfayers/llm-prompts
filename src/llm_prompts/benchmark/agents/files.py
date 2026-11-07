"""Read and write the JSON configs of agents, and copy their logins."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from llm_prompts.benchmark.types import JsonValue


def read_json(path: Path, *, strict: bool = True) -> dict[str, Any]:
    """Read a JSON object, returning ``{}`` when missing or, unless ``strict``, invalid.

    Raises:
        ValueError: If ``strict`` and the file is not valid JSON.
        TypeError: If ``strict`` and the file does not hold a JSON object.
    """
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        if strict and isinstance(error, ValueError):
            raise ValueError(f"{path} is not valid JSON: {error}") from error
        return {}
    if isinstance(data, dict):
        return data
    if strict:
        raise TypeError(f"{path} must hold a JSON object")
    return {}


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Write ``data`` to ``path`` as indented JSON, creating parent folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


EMPTY_LOGINS = (b"", b"{}")


def _write_private(target: Path, content: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)
    target.chmod(0o600)
    return target


def copy_login(source: Path, target: Path) -> Path | None:
    """Copy a login file privately and return ``target``, or None if the login is empty."""
    content = source.read_bytes()
    return None if content.strip() in EMPTY_LOGINS else _write_private(target, content)


def merge_json(
    target: Path, updates: dict[str, JsonValue], nested: tuple[str, ...] = ()
) -> Path:
    """Merge ``updates`` into the JSON object at ``target``, merging the ``nested`` keys."""
    merged = read_json(target, strict=False)
    for key, value in updates.items():
        current = merged.get(key)
        if key in nested and isinstance(current, dict) and isinstance(value, dict):
            value = {**current, **value}
        merged[key] = value
    write_json(target, merged)
    return target


def run_steps(steps: Iterable[Callable[[], Path | None]]) -> tuple[Path, ...]:
    """Run the copy steps, skipping any that fail, and return the paths they wrote."""
    written: list[Path] = []
    for step in steps:
        try:
            path = step()
        except OSError:
            continue
        if path is not None:
            written.append(path)
    return tuple(written)
