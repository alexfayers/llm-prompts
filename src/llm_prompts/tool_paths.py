"""The shared path contract: one root folder holding one folder per tool.

llm-prompts, cline-hooks and mcp-memory each keep a copy of this module.
Every copy MUST stay identical.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT_ENV = "LLM_PROMPTS_HOME"
KINDS = ("config", "data", "state", "cache")


def root() -> Path:
    """Return ``$LLM_PROMPTS_HOME``, else ``llm-prompts`` in ``$XDG_DATA_HOME`` or ``~/.local/share`` on every platform."""
    if override := os.environ.get(ROOT_ENV):
        return Path(override).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME")
    return (
        Path(data_home) if data_home else Path.home() / ".local" / "share"
    ) / "llm-prompts"


def tool_dir(tool: str, kind: str, base: Path | None = None) -> Path:
    """Return the ``kind`` folder of ``tool`` under ``base``, or under `root` by default.

    Raises:
        ValueError: ``kind`` is not one of `KINDS`.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown path kind {kind!r}, expected one of {KINDS}")
    return (base or root()) / tool / kind
