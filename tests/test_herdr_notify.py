"""Tests for the herdr-notify pi extension."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "extensions"
    / "herdr-notify.ts"
)
_HARNESS = Path(__file__).parent / "herdr_notify_harness.mjs"
_HERDR_STUB = """#!{node}
const fs = require("node:fs");
fs.appendFileSync(process.env.HERDR_LOG, JSON.stringify(process.argv.slice(2)) + "\\n");
if (process.env.HERDR_STUB_EXIT) process.exit(Number(process.env.HERDR_STUB_EXIT));
console.log(process.env.HERDR_STUB_OUTPUT ?? '{{"result":{{"reason":"shown","shown":true}}}}');
"""
_HERDR_ENV = {"HERDR_ENV": "1", "HERDR_PANE_ID": "w1:p1"}


def _can_strip_types() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    probe = subprocess.run(
        [node, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(
    not _can_strip_types(), reason="node with type stripping missing"
)


class _Fixture:
    """A fake herdr on PATH that logs the arguments of each call."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.log = tmp_path / "herdr.log"
        self.log.touch()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        stub = self.bin / "herdr"
        stub.write_text(_HERDR_STUB.format(node=shutil.which("node")))
        stub.chmod(0o755)

    def herdr_calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def run(
        self,
        steps: list[dict[str, Any]],
        *,
        env: dict[str, str] | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        config = self.tmp_path / "config.json"
        config.write_text(json.dumps({"script": str(_SCRIPT), "steps": steps}))
        done = subprocess.run(
            [str(shutil.which("node")), str(_HARNESS), str(config)],
            check=True,
            capture_output=True,
            text=True,
            env={
                "PATH": path or f"{self.bin}:/usr/bin:/bin",
                "HERDR_LOG": str(self.log),
                **(env or {}),
            },
        )
        output: dict[str, Any] = json.loads(done.stdout)
        assert "error" not in output, output["error"]
        results: dict[str, Any] = output["results"]
        return results

    def in_herdr(self, steps: list[dict[str, Any]], **env: str) -> dict[str, Any]:
        return self.run(steps, env={**_HERDR_ENV, **env})


@pytest.fixture
def fixture(tmp_path: Path) -> _Fixture:
    return _Fixture(tmp_path)


def test_finished_turn_raises_a_herdr_notification(fixture: _Fixture) -> None:
    fixture.in_herdr([{"emit": "agent_settled", "payload": {"aborted": False}}])
    [call] = fixture.herdr_calls()
    assert call[:2] == ["notification", "show"]


def test_outside_a_herdr_pane_nothing_is_run(fixture: _Fixture) -> None:
    fixture.run([{"emit": "agent_settled", "payload": {"aborted": False}}])
    assert fixture.herdr_calls() == []


@pytest.mark.parametrize(
    "env",
    [
        {"HERDR_STUB_EXIT": "1"},
        {"HERDR_STUB_OUTPUT": "not json"},
        {"HERDR_STUB_OUTPUT": '{"result":{"reason":"rate_limited","shown":false}}'},
    ],
    ids=["exit-code", "garbage-output", "not-shown"],
)
def test_a_failing_herdr_never_throws(fixture: _Fixture, env: dict[str, str]) -> None:
    fixture.in_herdr([{"emit": "agent_settled", "payload": {"aborted": False}}], **env)
    assert len(fixture.herdr_calls()) == 1


def test_a_missing_herdr_never_throws(fixture: _Fixture) -> None:
    fixture.run(
        [{"emit": "agent_settled", "payload": {"aborted": False}}],
        env=_HERDR_ENV,
        path="/usr/bin:/bin",
    )
    assert fixture.herdr_calls() == []


def test_finished_turn_names_the_project_and_plays_the_done_sound(
    fixture: _Fixture,
) -> None:
    fixture.in_herdr(
        [
            {
                "emit": "agent_settled",
                "payload": {"aborted": False},
                "ctx": {"cwd": "/work/widgets"},
            }
        ]
    )
    assert fixture.herdr_calls() == [
        ["notification", "show", "pi is done", "--body", "widgets", "--sound", "done"]
    ]


def test_an_aborted_run_is_not_announced(fixture: _Fixture) -> None:
    fixture.in_herdr([{"emit": "agent_settled", "payload": {"aborted": True}}])
    assert fixture.herdr_calls() == []


@pytest.mark.parametrize(
    "env",
    [
        {"PI_SUBAGENT_CHILD": "1"},
        {"PI_HERDSMAN_MAILBOX": "/mailbox"},
        {"PI_NOTIFY_AUTO": "0"},
    ],
    ids=["subagent", "herdsman-agent", "auto-disabled"],
)
def test_no_automatic_notification_for_subagents_or_when_disabled(
    fixture: _Fixture, env: dict[str, str]
) -> None:
    fixture.in_herdr([{"emit": "agent_settled", "payload": {"aborted": False}}], **env)
    assert fixture.herdr_calls() == []


def test_a_blocking_prompt_asks_for_attention_with_the_request_sound(
    fixture: _Fixture,
) -> None:
    fixture.in_herdr(
        [
            {
                "emit": "ui_prompt_start",
                "payload": {"kind": "confirm", "title": "Allow git push?"},
            }
        ]
    )
    assert fixture.herdr_calls() == [
        [
            "notification",
            "show",
            "pi needs input",
            "--body",
            "Allow git push?",
            "--sound",
            "request",
        ]
    ]


@pytest.mark.parametrize(
    "env",
    [
        {"PI_SUBAGENT_CHILD": "1"},
        {"PI_HERDSMAN_MAILBOX": "/mailbox"},
        {"PI_NOTIFY_AUTO": "0"},
    ],
    ids=["subagent", "herdsman-agent", "auto-disabled"],
)
def test_no_automatic_input_request_for_subagents_or_when_disabled(
    fixture: _Fixture, env: dict[str, str]
) -> None:
    fixture.in_herdr([{"emit": "ui_prompt_start", "payload": {"kind": "input"}}], **env)
    assert fixture.herdr_calls() == []


def test_notify_command_sends_the_message_with_an_optional_title(
    fixture: _Fixture,
) -> None:
    results = fixture.in_herdr(
        [
            {"command": "notify", "args": "Build is green", "ctx": {"$ui": True}},
            {
                "command": "notify",
                "args": "Review ready | CI | status",
                "ctx": {"$ui": True},
            },
            {"notices": True, "as": "notices"},
        ]
    )
    assert fixture.herdr_calls() == [
        ["notification", "show", "pi", "--body", "Build is green"],
        ["notification", "show", "CI | status", "--body", "Review ready"],
    ]
    assert results["notices"] == [
        ["Notification shown", "info"],
        ["Notification shown", "info"],
    ]


def test_notify_command_reports_when_nothing_was_shown(fixture: _Fixture) -> None:
    results = fixture.run(
        [
            {"command": "notify", "args": "hello", "ctx": {"$ui": True}},
            {"command": "notify", "args": "  ", "ctx": {"$ui": True}},
            {"notices": True, "as": "notices"},
        ]
    )
    assert fixture.herdr_calls() == []
    assert results["notices"] == [
        ["Notification not shown: not in a Herdr pane or Herdr declined it", "warning"],
        ["Usage: /notify <message> [| <title>]", "warning"],
    ]


def test_notify_tool_sends_title_body_and_sound(fixture: _Fixture) -> None:
    results = fixture.in_herdr(
        [
            {
                "tool": "notify",
                "params": {
                    "title": "Deploy",
                    "body": "Needs approval",
                    "sound": "request",
                },
                "as": "shown",
            },
            {"tool": "notify", "params": {"title": "Just a title"}, "as": "bare"},
        ]
    )
    assert fixture.herdr_calls() == [
        [
            "notification",
            "show",
            "Deploy",
            "--body",
            "Needs approval",
            "--sound",
            "request",
        ],
        ["notification", "show", "Just a title"],
    ]
    assert results["shown"]["content"] == [
        {"type": "text", "text": "Notification shown."}
    ]


def test_notify_tool_reports_without_throwing_when_nothing_was_shown(
    fixture: _Fixture,
) -> None:
    results = fixture.run(
        [{"tool": "notify", "params": {"title": "x"}, "as": "result"}]
    )
    assert fixture.herdr_calls() == []
    assert results["result"]["content"] == [
        {
            "type": "text",
            "text": "Notification not shown: not in a Herdr pane or Herdr declined it.",
        }
    ]


def test_notify_tool_still_works_in_a_subagent(fixture: _Fixture) -> None:
    fixture.in_herdr(
        [{"tool": "notify", "params": {"title": "x"}}], PI_SUBAGENT_CHILD="1"
    )
    assert len(fixture.herdr_calls()) == 1


def test_notify_command_stays_quiet_without_a_ui(fixture: _Fixture) -> None:
    results = fixture.in_herdr(
        [
            {
                "command": "notify",
                "args": "hello",
                "ctx": {"$ui": True, "hasUI": False},
            },
            {"notices": True, "as": "notices"},
        ]
    )
    assert len(fixture.herdr_calls()) == 1
    assert results["notices"] == []


def test_overlay_prompts_do_not_ask_for_attention(fixture: _Fixture) -> None:
    fixture.in_herdr([{"emit": "ui_prompt_start", "payload": {"kind": "custom"}}])
    assert fixture.herdr_calls() == []


def test_tool_sound_is_a_string_enum(fixture: _Fixture) -> None:
    results = fixture.in_herdr([{"registered": True, "as": "registered"}])
    [tool] = results["registered"]["tools"]
    sound = tool["parameters"]["args"][0]["sound"]
    assert sound["args"][0]["kind"] == "StringEnum"
    assert sound["args"][0]["values"] == ["none", "done", "request"]
