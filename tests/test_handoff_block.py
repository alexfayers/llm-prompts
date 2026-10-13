"""Tests for the HANDOFF.md startup block."""

from __future__ import annotations

from pathlib import Path

from llm_prompts.handoff_block import HandoffBlock


class TestHandoffBlock:
    def test_a_handoff_file_in_a_later_root_is_found(self, tmp_path: Path) -> None:
        first, second = tmp_path / "first", tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (second / "HANDOFF.md").write_text("notes", encoding="utf-8")

        (block,) = HandoffBlock().startup_blocks([str(first), str(second)])

        assert block.body(None) == f"{second}/HANDOFF.md exists - run the pickup skill."

    def test_an_absent_handoff_file_is_reported_as_absent(self, tmp_path: Path) -> None:
        (block,) = HandoffBlock().startup_blocks([str(tmp_path)])

        assert block.body(None) == "No HANDOFF.md."
