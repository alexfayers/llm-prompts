"""Tests for the installed agents manifest."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_prompts.install import uninstall
from llm_prompts.manifest import (
    delete_agent,
    delete_rendered_rules,
    read_manifest,
    read_rendered_rule,
    write_manifest,
    write_rendered_rules,
)


@pytest.fixture
def manifest_path(tmp_path: Path) -> Iterator[Path]:
    """Redirect the manifest to a temp file for the duration of a test."""
    path = tmp_path / "installed.json"
    with patch("llm_prompts.manifest.MANIFEST_PATH", path):
        yield path


@pytest.fixture
def rendered_rules_dir(tmp_path: Path) -> Iterator[Path]:
    """Redirect the rendered-rule cache to a temp directory for the duration of a test."""
    path = tmp_path / "rendered-rules"
    with patch("llm_prompts.manifest.RENDERED_RULES_DIR", path):
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


class TestRenderedRuleCache:
    def test_saved_rule_reads_back_unchanged(self, rendered_rules_dir: Path) -> None:
        write_rendered_rules("acme", {"greeting.md": "hello world"})

        assert read_rendered_rule("acme", "greeting.md") == "hello world"

    def test_never_saved_rule_reads_back_nothing(
        self, rendered_rules_dir: Path
    ) -> None:
        assert read_rendered_rule("acme", "missing.md") is None

    def test_replace_reads_back_new_text(self, rendered_rules_dir: Path) -> None:
        write_rendered_rules("acme", {"greeting.md": "old text"})

        write_rendered_rules("acme", {"greeting.md": "new text"})

        assert read_rendered_rule("acme", "greeting.md") == "new text"

    def test_replace_drops_rule_not_in_new_set(self, rendered_rules_dir: Path) -> None:
        write_rendered_rules("acme", {"greeting.md": "hi", "farewell.md": "bye"})

        write_rendered_rules("acme", {"greeting.md": "hi"})

        assert read_rendered_rule("acme", "farewell.md") is None

    def test_deleting_one_agent_leaves_others_readable(
        self, rendered_rules_dir: Path
    ) -> None:
        write_rendered_rules("acme", {"greeting.md": "hi"})
        write_rendered_rules("globex", {"greeting.md": "howdy"})

        delete_rendered_rules("acme")

        assert read_rendered_rule("acme", "greeting.md") is None
        assert read_rendered_rule("globex", "greeting.md") == "howdy"

    def test_uninstalling_agent_clears_its_rules(
        self, manifest_path: Path, rendered_rules_dir: Path
    ) -> None:
        write_manifest("acme", [])
        write_rendered_rules("acme", {"greeting.md": "hi"})

        uninstall(["acme"])

        assert read_rendered_rule("acme", "greeting.md") is None

    def test_redirected_config_folder_saves_cache_inside_it(
        self, rendered_rules_dir: Path
    ) -> None:
        write_rendered_rules("acme", {"greeting.md": "hi"})

        assert (rendered_rules_dir / "acme" / "greeting.md").exists()
