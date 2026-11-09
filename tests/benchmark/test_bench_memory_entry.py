"""Tests for pointing an agent's config at the sandbox memory server."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_prompts.benchmark.agents import AGENTS
from llm_prompts.benchmark.types import Agent


def point_memory(root: Path, agent: Agent, url: str) -> None:
    AGENTS[agent].point_memory(root, url)


URL = "http://127.0.0.1:5001/mcp"
OTHER_URL = "http://127.0.0.1:5002/mcp"


def test_claude_creates_http_entry(tmp_path: Path) -> None:
    point_memory(tmp_path, "claude", URL)
    config = json.loads((tmp_path / ".claude" / ".claude.json").read_text())
    assert config["mcpServers"]["memory"] == {"type": "http", "url": URL}
    assert not (tmp_path / ".pi").exists()


def test_pi_creates_entry_without_exposure(tmp_path: Path) -> None:
    point_memory(tmp_path, "pi", URL)
    config = json.loads((tmp_path / ".pi" / "agent" / "mcp.json").read_text())
    assert config["mcpServers"]["memory"] == {"url": URL}
    assert "exposure" not in config["mcpServers"]["memory"]
    assert not (tmp_path / ".claude").exists()


def test_claude_keeps_existing_settings(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}, "hooks": {"Stop": []}})
    )
    point_memory(tmp_path, "claude", URL)
    settings = json.loads(settings_path.read_text())
    assert settings["permissions"]["allow"] == ["Bash(ls:*)", "mcp__memory__*"]
    assert settings["hooks"] == {"Stop": []}


def test_second_call_replaces_url_and_keeps_one_rule(tmp_path: Path) -> None:
    point_memory(tmp_path, "claude", URL)
    point_memory(tmp_path, "claude", OTHER_URL)
    config = json.loads((tmp_path / ".claude" / ".claude.json").read_text())
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert config["mcpServers"]["memory"]["url"] == OTHER_URL
    assert settings["permissions"]["allow"].count("mcp__memory__*") == 1


def test_invalid_json_raises_and_leaves_file_unchanged(tmp_path: Path) -> None:
    config_path = tmp_path / ".claude" / ".claude.json"
    config_path.parent.mkdir()
    config_path.write_text("{not json")
    with pytest.raises(ValueError, match=r"\.claude\.json"):
        point_memory(tmp_path, "claude", URL)
    assert config_path.read_text() == "{not json"
