"""Builds the attic manifest from the usage ledger."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .pinned import PINNED_SKILLS, PINNED_TOOLS

MS_PER_DAY = 86_400_000


class AtticError(Exception):
    """Raised when the manifest cannot be built."""


@dataclass(frozen=True)
class LedgerRow:
    """One tool call recorded in the usage ledger."""

    ts: int
    tool: str
    skill_path: str | None = None


@dataclass(frozen=True)
class AtticItem:
    """A skill or tool to hide behind a stub."""

    kind: str
    name: str
    uses: int
    stub: str


@dataclass(frozen=True)
class Manifest:
    """The items to hide, with the ledger window they were chosen from."""

    built_at: str
    window_days: float
    items: list[AtticItem]

    def to_json(self) -> dict[str, object]:
        """Return the manifest as a JSON-serialisable mapping."""
        return {
            "built_at": self.built_at,
            "window_days": self.window_days,
            "items": [vars(item) for item in self.items],
        }


def read_ledger(path: Path) -> tuple[list[LedgerRow], int]:
    """Read ledger rows, skipping lines that are not a row.

    Args:
        path: The ``usage-ledger.jsonl`` file.

    Returns:
        The rows and the number of skipped lines.
    """
    rows: list[LedgerRow] = []
    skipped = 0
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            skill = record.get("skillPath")
            rows.append(
                LedgerRow(
                    ts=int(record["ts"]),
                    tool=str(record["tool"]),
                    skill_path=skill if isinstance(skill, str) else None,
                )
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            skipped += 1
    return rows, skipped


def build_manifest(
    rows: Iterable[LedgerRow],
    installed_skills: Mapping[str, str],
    installed_tools: Mapping[str, str],
    *,
    now: datetime,
    min_days: float = 7,
    threshold: int = 1,
) -> Manifest:
    """List the installed skills and tools used fewer than ``threshold`` times.

    Args:
        rows: Every ledger row.
        installed_skills: Skill name to stub text.
        installed_tools: Tool name to stub text.
        now: The build time.
        min_days: The least ledger span to build from.
        threshold: Items with fewer uses than this are listed.

    Returns:
        The manifest, without pinned items.

    Raises:
        AtticError: The ledger spans fewer than ``min_days`` days.
    """
    rows = list(rows)
    window_days = (
        round((max(r.ts for r in rows) - min(r.ts for r in rows)) / MS_PER_DAY, 1)
        if rows
        else 0.0
    )
    if window_days < min_days:
        raise AtticError(
            f"The ledger covers {window_days} days, fewer than the {min_days} needed."
        )
    skill_uses = Counter(
        Path(row.skill_path).parent.name for row in rows if row.skill_path
    )
    tool_uses = Counter(row.tool for row in rows)
    candidates = [
        ("skill", name, stub, skill_uses[name], PINNED_SKILLS)
        for name, stub in sorted(installed_skills.items())
    ] + [
        ("tool", name, stub, tool_uses[name], PINNED_TOOLS)
        for name, stub in sorted(installed_tools.items())
    ]
    return Manifest(
        built_at=now.isoformat(),
        window_days=window_days,
        items=[
            AtticItem(kind, name, uses, stub)
            for kind, name, stub, uses, pinned in candidates
            if uses < threshold and name not in pinned
        ],
    )
