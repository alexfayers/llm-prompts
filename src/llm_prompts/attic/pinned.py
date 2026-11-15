"""Names the attic never hides and an ablation never drops."""

from __future__ import annotations

import json
from pathlib import Path

_PINNED: dict[str, list[str]] = json.loads(
    (Path(__file__).parent / "pinned.json").read_text("utf-8")
)

PINNED_RULES = frozenset(_PINNED["rules"])
PINNED_SKILLS = frozenset(_PINNED["skills"])
PINNED_TOOLS = frozenset(_PINNED["tools"])
