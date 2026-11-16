"""Tests for the attic manifest builder."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from llm_prompts.attic.manifest import (
    LedgerRow,
    build_manifest,
)
from llm_prompts.cli import main

NOW = datetime(2026, 1, 20, tzinfo=UTC)
DAY_MS = 86_400_000


def _row(days_ago: float, tool: str = "bash", skill: str | None = None) -> LedgerRow:
    return LedgerRow(
        ts=int(NOW.timestamp() * 1000 - days_ago * DAY_MS), tool=tool, skill_path=skill
    )


def _week_of_rows(*extra: LedgerRow) -> list[LedgerRow]:
    return [_row(10), _row(1), *extra]


class TestBuildManifest:
    def test_lists_unused_skills_and_tools_sorted_with_their_stubs(self) -> None:
        rows = _week_of_rows(_row(3, "read", "/x/skills/used/SKILL.md"))
        manifest = build_manifest(
            rows,
            {"used": "u", "zeta": "z stub", "alpha": "a stub"},
            {"fetch": "f", "read": "r"},
            now=NOW,
        )
        assert [(i.kind, i.name, i.uses, i.stub) for i in manifest.items] == [
            ("skill", "alpha", 0, "a stub"),
            ("skill", "zeta", 0, "z stub"),
            ("tool", "fetch", 0, "f"),
        ]

    def test_never_lists_a_pinned_skill_or_tool_even_with_no_uses(self) -> None:
        manifest = build_manifest(
            _week_of_rows(), {"git-usage": "", "other": ""}, {"read": ""}, now=NOW
        )
        assert [i.name for i in manifest.items] == ["other"]


class TestAtticBuildCommand:
    def _ledger(self, tmp_path: Path, days: float) -> Path:
        ledger = tmp_path / "usage-ledger.jsonl"
        start = datetime.now(UTC) - timedelta(days=days)
        rows = [
            {"ts": int(start.timestamp() * 1000), "tool": "bash"},
            {"ts": int(datetime.now(UTC).timestamp() * 1000), "tool": "bash"},
        ]
        ledger.write_text("\n".join(json.dumps(row) for row in rows))
        return ledger

    def _run(self, tmp_path: Path, *args: str) -> int | None:
        with (
            patch("sys.argv", ["llm-prompts", "attic", "build", *args]),
            patch("llm_prompts.attic.cli._skill_stubs", return_value={"idle": "s"}),
        ):
            return main()

    def test_writes_the_manifest_next_to_the_ledger(self, tmp_path: Path) -> None:
        ledger = self._ledger(tmp_path, 8)
        self._run(tmp_path, "--ledger", str(ledger), "--tool", "fetch")
        written = json.loads((tmp_path / "attic.json").read_text())
        assert [i["name"] for i in written["items"]] == ["idle", "fetch"]
