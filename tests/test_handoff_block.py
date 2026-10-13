"""Tests for the HANDOFF.md startup block."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llm_prompts.handoff_block import HandoffBlock


class TestHandoffBlock:
    def test_a_present_handoff_file_tells_the_model_to_pick_it_up(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "HANDOFF.md").write_text("notes", encoding="utf-8")

        (block,) = HandoffBlock().startup_blocks([str(tmp_path)])

        assert block.title == "HANDOFF.md"
        assert block.replaces == "check for HANDOFF.md in the workspace root"
        assert block.order == 5
        assert (
            block.body(None) == f"{tmp_path}/HANDOFF.md exists - run the pickup skill."
        )

    def test_an_absent_handoff_file_is_reported_as_absent(self, tmp_path: Path) -> None:
        (block,) = HandoffBlock().startup_blocks([str(tmp_path)])

        assert block.body(None) == "No HANDOFF.md."

    def test_no_workspace_roots_gives_no_block(self) -> None:
        assert HandoffBlock().startup_blocks([]) == []

    @pytest.mark.parametrize("workspace", ["plain", "empty_git_repo", "missing"])
    def test_a_workspace_without_git_history_is_reported_as_absent(
        self, tmp_path: Path, workspace: str
    ) -> None:
        root = tmp_path / workspace
        if workspace != "missing":
            root.mkdir()
        if workspace == "empty_git_repo":
            subprocess.run(["git", "init", "-q", str(root)], check=True)

        (block,) = HandoffBlock().startup_blocks([str(root)])

        assert block.body(None) == "No HANDOFF.md."
