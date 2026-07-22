"""Tests for the installed agents manifest."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_prompts.manifest import delete_agent, read_manifest, write_manifest


@pytest.fixture
def manifest_path(tmp_path: Path):
    """Redirect the manifest to a temp file for the duration of a test."""
    path = tmp_path / "installed.json"
    with patch("llm_prompts.manifest.MANIFEST_PATH", path):
        yield path


class TestDeleteAgent:
    def test_delete_agent_removes_entry(self, manifest_path: Path) -> None:
        write_manifest("cline", ["a.md"])
        write_manifest("kiro", ["b.md"])

        delete_agent("cline")

        agents = read_manifest()
        assert "cline" not in agents
        assert agents["kiro"]["files"] == ["b.md"]

    def test_delete_agent_missing_is_noop(self, manifest_path: Path) -> None:
        write_manifest("kiro", ["b.md"])

        delete_agent("codex")

        assert read_manifest()["kiro"]["files"] == ["b.md"]

    def test_delete_agent_on_empty_manifest_is_noop(self, manifest_path: Path) -> None:
        delete_agent("cline")

        assert read_manifest() == {}

    def test_delete_last_agent_leaves_empty_agents_map(
        self, manifest_path: Path
    ) -> None:
        write_manifest("cline", ["a.md"])

        delete_agent("cline")

        assert read_manifest() == {}
        assert json.loads(manifest_path.read_text(encoding="utf-8")) == {"agents": {}}
