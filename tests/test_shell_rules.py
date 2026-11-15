"""Tests for the pi-context shell command rules."""

from __future__ import annotations

from pathlib import Path

import bashlex  # type: ignore[import-untyped]
import pytest
from cline_hooks.handlers.commands import check_rules, extract_commands

from llm_prompts.guards.shell_rules import ShellRules


@pytest.fixture
def guards_on(monkeypatch: pytest.MonkeyPatch, isolated_config_dir: Path) -> None:
    """Turn the pi-context guards on."""
    monkeypatch.setenv("CLINE_HOOKS_FRONTEND", "pi")
    (isolated_config_dir / "config.toml").write_text(
        '[pi]\nruntime = "pi-context"\n', encoding="utf-8"
    )


def blocks(command: str) -> bool:
    """Report whether the rules block the shell line."""
    commands = extract_commands(bashlex.parse(command))
    return check_rules(commands, ShellRules().command_rules()) is not None


@pytest.mark.usefixtures("guards_on")
class TestShellRules:
    @pytest.mark.parametrize(
        "command",
        [
            "set -e",
            "set -euo pipefail",
            "set -o errexit",
            "fuser -k 8080/tcp",
            "kill $(lsof -ti:8080)",
            "lsof -ti :8080 | xargs kill",
            "docker compose down -v",
            "docker-compose down --volumes",
            "docker volume rm data",
            "docker volume prune",
        ],
    )
    def test_blocks(self, command: str) -> None:
        assert blocks(command)

    @pytest.mark.parametrize(
        "command",
        [
            "set -o pipefail",
            "fuser 8080/tcp",
            "lsof -i :8080",
            "kill 123",
            "docker compose down",
            "docker volume ls",
        ],
    )
    def test_allows(self, command: str) -> None:
        assert not blocks(command)
