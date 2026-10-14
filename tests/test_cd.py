"""Tests for the cd pi extension."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).parent
_SCRIPT = _HERE.parent / "src/llm_prompts/prompts/pi/extensions/cd.ts"


def _run(tmp_path: Path, request: list[dict[str, Any]], state: str) -> Any:
    mailbox = tmp_path / "agent/pi-herdsman/runtime/mailboxes-v5/w1"
    mailbox.mkdir(parents=True)
    (mailbox / "state.json").write_text(state)
    (tmp_path / "s.jsonl").write_text("{}")
    ctx = {"$ctx": "c", "sessionId": "owner", "cwd": str(tmp_path)}
    steps: list[Any] = [{"fn": "default", "args": [{"$pi": "pi"}]}]
    steps += [{**step, "ctx": ctx} for step in request]
    steps += [{"stored": "c", "as": "ctx"}, {"sent": "pi", "as": "sent"}]
    config = tmp_path / "config.json"
    agent_dir = str(tmp_path / "agent")
    config.write_text(
        json.dumps({"script": str(_SCRIPT), "agentDir": agent_dir, "steps": steps})
    )
    harness = str(_HERE / "context_total_harness.mjs")
    done = subprocess.run(
        [str(shutil.which("node")), harness, str(config)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(done.stdout)["results"]


@pytest.mark.parametrize(
    ("mailbox", "state", "refusal"),
    [
        ("m", "{}", "managed agent cannot"),
        ("", '{"ownerSessionId":"owner","agentLabel":"w1"}', "agents: w1"),
        ("", "not json", "Cannot read pi-herdsman agent state"),
    ],
)
def test_cd_refuses_to_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mailbox: str,
    state: str,
    refusal: str,
) -> None:
    monkeypatch.setenv("PI_HERDSMAN_MAILBOX", mailbox)
    results = _run(tmp_path, [{"command": "cd", "pi": "pi", "args": "/"}], state)
    assert results["ctx"]["switched"] == []
    assert refusal in results["ctx"]["ui"]["notices"][0][0]


def test_change_dir_moves_after_the_turn_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PI_HERDSMAN_MAILBOX", "")
    call = {"call": "change_dir", "pi": "pi", "params": {"path": "/"}}
    settled = {"emit": "agent_settled", "pi": "pi", "payload": {"aborted": False}}
    results = _run(
        tmp_path, [call, settled, {"command": "cd", "pi": "pi", "args": "/"}], "{}"
    )
    assert results["sent"] == [["/cd /", {"expandPromptTemplates": True}]]
    assert results["ctx"]["switched"] == ["/fork-of-s.jsonl"]
    assert results["ctx"]["continued"] == [["Directory changed. Continue the task."]]
