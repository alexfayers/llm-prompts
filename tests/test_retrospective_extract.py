"""Tests for the retrospective skill's signal extraction."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "claude-code"
    / "skills"
    / "retrospective"
    / "extract_signals.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("extract_signals", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod() -> ModuleType:
    """Load the extract_signals script as a module."""
    return _load()


def _assistant(tool_id: str, name: str, command: str = "") -> dict:
    tool_use = {"type": "tool_use", "id": tool_id, "name": name}
    if name == "Bash":
        tool_use["input"] = {"command": command}
    return {"type": "assistant", "message": {"content": [tool_use]}}


def _result(tool_id: str, *, error: bool, text: str = "ok") -> dict:
    return {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "is_error": error,
                    "content": text,
                }
            ]
        },
    }


def _session(messages: list[dict]) -> dict:
    return {"session_id": "s1", "project": "p1", "title": "t", "messages": messages}


class TestBashLead:
    """Tests for the leading-command extraction."""

    def test_plain_command(self, mod: ModuleType) -> None:
        assert mod._bash_lead("docker-compose up") == "docker-compose"

    def test_skips_leading_cd(self, mod: ModuleType) -> None:
        assert mod._bash_lead("cd /some/path && python3 score.py") == "python3"

    def test_skips_cd_with_newline_separator(self, mod: ModuleType) -> None:
        assert mod._bash_lead("cd /some/path\ndocker-compose build") == "docker-compose"

    def test_skips_cd_with_semicolon(self, mod: ModuleType) -> None:
        assert mod._bash_lead("cd /x ; make test") == "make"

    def test_bare_cd_falls_back(self, mod: ModuleType) -> None:
        assert mod._bash_lead("cd /only/a/path") == "cd"

    def test_empty(self, mod: ModuleType) -> None:
        assert mod._bash_lead("") == ""


class TestResultIsError:
    """Tests for failure detection on a tool_result block."""

    def test_is_error_field(self, mod: ModuleType) -> None:
        assert mod._result_is_error({"is_error": True, "content": "x"}) is True

    def test_tool_use_error_marker(self, mod: ModuleType) -> None:
        result = {"content": "<tool_use_error>not read</tool_use_error>"}
        assert mod._result_is_error(result) is True

    def test_exit_code_one(self, mod: ModuleType) -> None:
        assert mod._result_is_error({"content": "Exit code 1\nboom"}) is True

    def test_success(self, mod: ModuleType) -> None:
        assert mod._result_is_error({"is_error": False, "content": "ok"}) is False

    def test_list_content(self, mod: ModuleType) -> None:
        result = {"content": [{"type": "text", "text": "<tool_use_error>x</tool_use_error>"}]}
        assert mod._result_is_error(result) is True


class TestExtractRetries:
    """Tests for cross-message retry detection."""

    def test_detects_consecutive_failures(self, mod: ModuleType) -> None:
        session = _session([
            _assistant("a", "Bash", "docker-compose up"),
            _result("a", error=True),
            _assistant("b", "Bash", "docker-compose up"),
            _result("b", error=True),
        ])
        retries = mod.extract_retries(session)
        assert len(retries) == 1
        assert retries[0]["command_pattern"] == "docker-compose"
        assert retries[0]["attempts"] == 2
        assert retries[0]["recovered"] is False

    def test_recovered_flag_on_trailing_success(self, mod: ModuleType) -> None:
        session = _session([
            _assistant("a", "Bash", "uv run pytest"),
            _result("a", error=True),
            _assistant("b", "Bash", "uv run pytest"),
            _result("b", error=True),
            _assistant("c", "Bash", "uv run pytest"),
            _result("c", error=False),
        ])
        retries = mod.extract_retries(session)
        assert len(retries) == 1
        assert retries[0]["recovered"] is True

    def test_single_failure_is_not_a_retry(self, mod: ModuleType) -> None:
        session = _session([
            _assistant("a", "Bash", "docker-compose up"),
            _result("a", error=True),
            _assistant("b", "Bash", "docker-compose up"),
            _result("b", error=False),
        ])
        assert mod.extract_retries(session) == []

    def test_different_commands_do_not_group(self, mod: ModuleType) -> None:
        session = _session([
            _assistant("a", "Bash", "docker-compose up"),
            _result("a", error=True),
            _assistant("b", "Bash", "uv run pytest"),
            _result("b", error=True),
        ])
        assert mod.extract_retries(session) == []

    def test_non_bash_tool_keyed_by_name(self, mod: ModuleType) -> None:
        session = _session([
            _assistant("a", "Read"),
            _result("a", error=True),
            _assistant("b", "Read"),
            _result("b", error=True),
        ])
        retries = mod.extract_retries(session)
        assert len(retries) == 1
        assert retries[0]["command_pattern"] == "Read"

    def test_result_in_separate_message_is_matched(self, mod: ModuleType) -> None:
        session = _session([
            _assistant("a", "Bash", "docker-compose up"),
            _assistant("b", "Bash", "docker-compose up"),
            _result("a", error=True),
            _result("b", error=True),
        ])
        assert len(mod.extract_retries(session)) == 1
