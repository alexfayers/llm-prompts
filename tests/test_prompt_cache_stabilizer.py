"""Tests for the prompt-cache-stabilizer pi extension."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
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
    / "prompt-cache-stabilizer.ts"
)
_HARNESS = Path(__file__).parent / "context_total_harness.mjs"


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


def _run(tmp_path: Path, steps: list[dict[str, Any]]) -> dict[str, Any]:
    config = tmp_path / "config.json"
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir(exist_ok=True)
    config.write_text(
        json.dumps({"script": str(_SCRIPT), "agentDir": str(agent_dir), "steps": steps})
    )
    done = subprocess.run(
        ["node", str(_HARNESS), str(config)],
        check=True,
        capture_output=True,
        text=True,
    )
    output: dict[str, Any] = json.loads(done.stdout)
    assert "error" not in output, output["error"]
    results: dict[str, Any] = output["results"]
    return results


def _system(
    timestamp: int, sections: Mapping[str, str | None], content: str = ""
) -> dict[str, Any]:
    return {
        "role": "system",
        "content": content,
        "sections": sections,
        "timestamp": timestamp,
    }


def _user(timestamp: int) -> dict[str, Any]:
    return {"role": "user", "content": "hi", "timestamp": timestamp}


def _folded_sections(messages: list[dict[str, Any]]) -> dict[str, str]:
    folded: dict[str, str] = {}
    for message in messages:
        if message["role"] != "system":
            continue
        for name, text in message.get("sections", {}).items():
            if text is None:
                folded.pop(name, None)
            else:
                folded[name] = text
    return folded


def _stabilize(
    tmp_path: Path,
    messages: list[dict[str, Any]],
    *,
    triggered: bool,
    since: int = 0,
) -> list[dict[str, Any]] | None:
    steps: list[dict[str, Any]] = [
        {
            "fn": "stabilizeSystemMessages",
            "args": [messages, {"triggered": triggered, "since": since}],
            "as": "out",
        }
    ]
    out: list[dict[str, Any]] | None = _run(tmp_path, steps).get("out")
    return out


_LEAD = _system(1, {"skills": "S", "custom": "C"}, "base")


class TestStabilizeSystemMessages:
    """Tests for dropping cache-busting system section removals."""

    def test_triggered_run_drops_removal_of_custom_section(
        self, tmp_path: Path
    ) -> None:
        messages = [_LEAD, _user(2), _system(3, {"custom": None})]
        out = _stabilize(tmp_path, messages, triggered=True, since=2)
        assert out is not None
        assert _folded_sections(out) == _folded_sections([_LEAD])

    def test_removal_with_later_re_add_is_dropped_even_when_prompted(
        self, tmp_path: Path
    ) -> None:
        messages = [
            _LEAD,
            _system(3, {"custom": None}),
            _user(4),
            _system(5, {"custom": "C"}),
        ]
        out = _stabilize(tmp_path, messages, triggered=False)
        assert out is not None
        assert [m.get("sections") for m in out[1:] if m["role"] == "system"] == [
            {"custom": "C"}
        ]

    @pytest.mark.parametrize(
        ("messages", "triggered", "since"),
        [
            ([_LEAD, _user(2), _system(3, {"custom": None})], False, 0),
            ([_LEAD, _user(2), _system(3, {"skills": None})], True, 2),
            ([_LEAD, _system(1, {"custom": None}), _user(2)], True, 2),
            ([_LEAD, _user(2), _system(3, {"custom": "C2"})], True, 2),
            ([_LEAD, _user(2)], True, 0),
        ],
        ids=["prompted", "built-in", "before-prompt", "update", "no-change"],
    )
    def test_removals_that_are_legitimate_are_left_alone(
        self,
        tmp_path: Path,
        messages: list[dict[str, Any]],
        triggered: bool,
        since: int,
    ) -> None:
        assert _stabilize(tmp_path, messages, triggered=triggered, since=since) is None

    def test_leading_system_message_is_never_changed(self, tmp_path: Path) -> None:
        lead = _system(1, {"custom": None})
        assert (
            _stabilize(tmp_path, [lead, _system(2, {"custom": "C"})], triggered=True)
            is None
        )


def _handle(
    tmp_path: Path,
    model: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    prompted: bool,
    branch: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    steps: list[dict[str, Any]] = [
        {"fn": "default", "args": [{"$pi": "pi"}]},
        {
            "emit": "session_start",
            "pi": "pi",
            "ctx": {
                "sessionManager": {
                    "getBranch": {
                        "$fn": [
                            {"type": "message", "message": _user(2)},
                            {"type": "message", "message": _system(3, {})},
                        ]
                    }
                }
            },
        },
    ]
    if prompted:
        steps.append({"emit": "before_agent_start", "pi": "pi"})
    steps += [
        {"emit": "agent_start", "pi": "pi"},
        {
            "emit": "context_with_system",
            "pi": "pi",
            "payload": {"messages": messages},
            "ctx": {
                "model": model,
                "sessionManager": {
                    "getBranch": {
                        "$fn": [
                            {"type": "message", "message": message}
                            for message in branch or []
                        ]
                    }
                },
            },
            "as": "out",
        },
    ]
    out: dict[str, Any] | None = _run(tmp_path, steps).get("out")
    return out


class TestHandler:
    """Tests for the registered pi event handlers."""

    @pytest.mark.parametrize(
        ("model", "prompted", "dropped"),
        [
            ({"api": "anthropic-messages", "compat": {}}, False, True),
            ({"api": "anthropic-messages"}, False, True),
            (
                {
                    "api": "bedrock-converse-stream",
                    "compat": {"supportsMidConvoSystemMessages": True},
                },
                False,
                True,
            ),
            (
                {
                    "api": "anthropic-messages",
                    "compat": {"supportsMidConvoSystemMessages": True},
                },
                False,
                False,
            ),
            ({"api": "anthropic-messages", "compat": {}}, True, False),
        ],
        ids=["folds", "no-compat", "bedrock", "mid-convo", "prompted-run"],
    )
    def test_removals_are_dropped_only_in_triggered_runs_on_folding_models(
        self,
        tmp_path: Path,
        model: dict[str, Any],
        prompted: bool,
        dropped: bool,
    ) -> None:
        messages = [_LEAD, _user(2), _system(5, {"custom": None})]
        out = _handle(tmp_path, model, messages, prompted=prompted)
        assert (out is not None) is dropped
        if out is not None:
            assert _folded_sections(out["messages"]) == _folded_sections([_LEAD])


_FOLDING_MODEL = {"api": "anthropic-messages", "compat": {}}


def _merged_head(sections: dict[str, str]) -> dict[str, Any]:
    return _system(1, sections, "base")


class TestMergedHead:
    """Tests for restoring removals when pi merged the system messages into one head."""

    def test_dropped_removal_is_restored_in_the_merged_head(
        self, tmp_path: Path
    ) -> None:
        branch = [_LEAD, _user(2), _system(3, {"custom": None})]
        messages = [_merged_head({"skills": "S"}), _user(2)]
        out = _handle(tmp_path, _FOLDING_MODEL, messages, prompted=False, branch=branch)
        assert out is not None
        assert out["messages"][0] == _merged_head({"skills": "S", "custom": "C"})
        assert out["messages"][1:] == [_user(2)]

    @pytest.mark.parametrize(
        ("prompted", "head_sections"),
        [(True, {"skills": "S"}), (False, {"skills": "S", "other": "O"})],
        ids=["prompted-run", "head-not-from-branch"],
    )
    def test_merged_head_is_left_alone_when_it_is_legitimate(
        self,
        tmp_path: Path,
        prompted: bool,
        head_sections: dict[str, str],
    ) -> None:
        branch = [_LEAD, _user(2), _system(3, {"custom": None})]
        messages = [_merged_head(head_sections), _user(2)]
        assert (
            _handle(
                tmp_path, _FOLDING_MODEL, messages, prompted=prompted, branch=branch
            )
            is None
        )
