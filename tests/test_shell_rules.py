"""Tests for the shell command rules of the guards."""

from __future__ import annotations

import logging

import bashlex  # type: ignore[import-untyped]
import pytest
from cline_hooks.core.plugin import HookResult
from cline_hooks.handlers.commands import check_rules, extract_commands

from llm_prompts.guards.shell_rules import ShellRules


@pytest.fixture
def guards_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the guards on."""
    monkeypatch.setenv("CLINE_HOOKS_FRONTEND", "pi")


def corrected(command: str) -> HookResult | None:
    """Return the rules' PreShell result for the shell line."""
    return ShellRules().on_hook(
        "PreShell", logger=logging.getLogger("test"), command=command
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
            "set -o errexit",
            "set -e -o errexit",
            "set -eo errexit",
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
            "set -e",
            "set -euo pipefail",
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

    @pytest.mark.parametrize(
        ("command", "fixed"),
        [
            ("set -e", "true"),
            ("set -euo pipefail", "set -uo pipefail"),
            ("set -eo pipefail && make", "set -o pipefail && make"),
            ("set -e -o pipefail; make", "set -o pipefail; make"),
            ("cd app && set -e; make", "cd app && true; make"),
            ("set -e # comment", "true # comment"),
            ("set -e >/dev/null", "true >/dev/null"),
            ('set "-e" -o pipefail', "set -o pipefail"),
            ("set -o pipefail -e", "set -o pipefail"),
            ("echo $(set -e)", "echo $(true)"),
            ("set -e\nset -ex", "true\nset -x"),
            ("set -e foo", "set foo"),
            ('set -e -x "$@"', 'set -x "$@"'),
            ('set -e "$@" foo', 'set "$@" foo'),
        ],
    )
    def test_drops_errexit_and_runs(self, command: str, fixed: str) -> None:
        result = corrected(command)
        assert result is not None and result.block is None
        assert result.updated_input == {"command": fixed}
        assert result.notes

    @pytest.mark.parametrize(
        "command", ['set -e "$@"', "set -e $args", "set -e `args`", "set -e *"]
    )
    def test_blocks_a_set_that_may_run_bare(self, command: str) -> None:
        result = corrected(command)
        assert result is not None and result.block and not result.updated_input

    @pytest.mark.parametrize(
        "command",
        [
            "set -uo pipefail",
            "set +e",
            "set -o pipefail foo -e",
            "echo set -e",
            'echo "set -e"',
            "cat <<EOF\nset -e\nEOF",
            "make",
        ],
    )
    def test_leaves_other_commands(self, command: str) -> None:
        assert corrected(command) is None

    def test_leaves_commands_when_guards_are_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLINE_HOOKS_FRONTEND")
        assert corrected("set -e") is None
