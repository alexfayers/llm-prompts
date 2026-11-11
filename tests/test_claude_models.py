"""Tests for the shared Claude model name resolver."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_prompts.claude_models import resolve_model


@pytest.fixture(autouse=True)
def _no_bedrock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)


def _write_settings(home: Path, raw: str) -> None:
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(raw)


class TestResolveModel:
    def test_bedrock_name_maps_to_override(self, isolated_home: Path) -> None:
        _write_settings(
            isolated_home,
            json.dumps({"modelOverrides": {"model-a": "provider.model-a"}}),
        )

        assert resolve_model("model-a") == "provider.model-a"

    def test_unknown_name_returned_unchanged(self, isolated_home: Path) -> None:
        _write_settings(isolated_home, json.dumps({"availableModels": ["model-b"]}))

        assert resolve_model("model-a") == "model-a"

    @pytest.mark.parametrize("raw", ["null", "[]", "not json"])
    def test_non_object_settings_return_name_unchanged(
        self, isolated_home: Path, raw: str
    ) -> None:
        _write_settings(isolated_home, raw)

        assert resolve_model("model-a") == "model-a"

    def test_null_override_returns_name_unchanged(self, isolated_home: Path) -> None:
        _write_settings(
            isolated_home, json.dumps({"modelOverrides": {"model-a": None}})
        )

        assert resolve_model("model-a") == "model-a"
