"""Tests for the removed-agents session-start notice."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_prompts.manifest import write_manifest
from llm_prompts.removed_agents_notice import RemovedAgentsNotice


@pytest.fixture(autouse=True)
def manifest_path(tmp_path: Path) -> Iterator[Path]:
    """Redirect the manifest to a temp file for the duration of a test."""
    path = tmp_path / "installed.json"
    with patch("llm_prompts.manifest.manifest_path", return_value=path):
        yield path


class TestRemovedAgentsNotice:
    def test_names_the_uninstall_command_for_each_managed_removed_agent(self) -> None:
        write_manifest("cline", [])
        write_manifest("copilot", [])
        write_manifest("pi", [])

        result = RemovedAgentsNotice().on_hook("TaskStart", agent_type="")

        assert result is not None
        (note,) = result.notes
        assert "llm-prompts uninstall cline" in note
        assert "llm-prompts uninstall copilot" in note
        assert "uninstall pi" not in note

    def test_is_silent_when_no_removed_agent_is_managed(self) -> None:
        write_manifest("pi", [])

        assert RemovedAgentsNotice().on_hook("TaskStart", agent_type="") is None

    def test_is_silent_inside_a_subagent(self) -> None:
        write_manifest("cline", [])

        assert RemovedAgentsNotice().on_hook("TaskStart", agent_type="worker") is None
