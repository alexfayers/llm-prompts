import io
import json

import pytest

from llm_prompts.benchmark.guard.claude import BLOCKED_EXIT_CODE, main

DENIED = [
    "pkill -f mcp-memory",
    "git push origin main",
    "git -C /repo push --force",
    "git --git-dir /x push",
    "llm-prompts update",
    "llm-prompts install claude",
    "llm-prompts install claude && ls --root",
]
ALLOWED = [
    "git status",
    "llm-prompts install claude --root /tmp/x",
]


def _verdict(monkeypatch: pytest.MonkeyPatch, stdin: str) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return main()


@pytest.mark.parametrize(
    ("commands", "code"), [(DENIED, BLOCKED_EXIT_CODE), (ALLOWED, 0)]
)
def test_bash_command_verdict(
    monkeypatch: pytest.MonkeyPatch, commands: list[str], code: int
) -> None:
    for command in commands:
        event = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert _verdict(monkeypatch, json.dumps(event)) == code, command


@pytest.mark.parametrize(
    ("stdin", "code"),
    [
        ('{"tool_name": "Read", "tool_input": {"command": "git push"}}', 0),
        ('{"tool_name": "Bash", "tool_input": "x"}', BLOCKED_EXIT_CODE),
    ],
)
def test_non_bash_is_allowed_and_bad_input_is_blocked(
    monkeypatch: pytest.MonkeyPatch, stdin: str, code: int
) -> None:
    assert _verdict(monkeypatch, stdin) == code
