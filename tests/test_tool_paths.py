"""Tests for the shared path contract every tool copies."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from llm_prompts import tool_paths


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_root_defaults_to_local_share_on_every_platform(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path, platform: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    assert tool_paths.root() == isolated_home / ".local" / "share" / "llm-prompts"


def test_root_follows_xdg_data_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert tool_paths.root() == tmp_path / "llm-prompts"


def test_root_env_overrides_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(tool_paths.ROOT_ENV, str(tmp_path))

    assert tool_paths.root() == tmp_path


@pytest.mark.parametrize("kind", tool_paths.KINDS)
def test_tool_dir_is_one_folder_per_tool_and_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    monkeypatch.setenv(tool_paths.ROOT_ENV, str(tmp_path))

    assert tool_paths.tool_dir("cline-hooks", kind) == tmp_path / "cline-hooks" / kind


def test_tool_dir_uses_a_given_base(tmp_path: Path) -> None:
    assert tool_paths.tool_dir("mcp-memory", "data", tmp_path) == (
        tmp_path / "mcp-memory" / "data"
    )


def test_tool_dir_rejects_an_unknown_kind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="logs"):
        tool_paths.tool_dir("llm-prompts", "logs", tmp_path)


def test_contract_names_are_fixed() -> None:
    assert tool_paths.ROOT_ENV == "LLM_PROMPTS_HOME"
    assert tool_paths.KINDS == ("config", "data", "state", "cache")
