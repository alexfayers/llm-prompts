"""Tests for the cd pi extension."""

from __future__ import annotations

import json
import os
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
    / "cd.ts"
)
_HARNESS = Path(__file__).parent / "context_total_harness.mjs"
_NODE = shutil.which("node")
_CONTINUE = "Directory changed. Continue the task."
_NOT_SAVED = "The session is not saved, so it cannot move."


def _can_strip_types() -> bool:
    if _NODE is None:
        return False
    probe = subprocess.run(
        [_NODE, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(
    not _can_strip_types(), reason="node with type stripping missing"
)


def _run(tmp_path: Path, steps: list[dict[str, Any]]) -> dict[str, Any]:
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir(exist_ok=True)
    (tmp_path / "home" / "sub").mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"script": str(_SCRIPT), "agentDir": str(agent_dir), "steps": steps})
    )
    done = subprocess.run(
        [str(_NODE), str(_HARNESS), str(config)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(tmp_path / "home")},
    )
    output: dict[str, Any] = json.loads(done.stdout)
    assert "error" not in output, output["error"]
    results: dict[str, Any] = output["results"]
    return results


def _cd(
    tmp_path: Path,
    target: str,
    *,
    session_file: Path | None = None,
    cwd: Path | None = None,
    session_dir: Path | None = None,
    cancel: bool = False,
    requested_by_tool: bool = False,
) -> dict[str, Any]:
    ctx = {
        "$ctx": "ctx",
        "cwd": str(cwd or tmp_path),
        "sessionFile": str(session_file) if session_file else None,
        "sessionDir": str(session_dir) if session_dir else None,
        "cancel": cancel,
    }
    tool_steps: list[dict[str, Any]] = [
        {"call": "change_dir", "pi": "pi", "params": {"path": target}, "ctx": ctx},
        {"emit": "agent_settled", "pi": "pi", "payload": {"aborted": False}},
    ]
    return _run(
        tmp_path,
        [
            {"fn": "default", "args": [{"$pi": "pi"}]},
            *(tool_steps if requested_by_tool else []),
            {"command": "cd", "pi": "pi", "args": target, "ctx": ctx},
            {"switched": "ctx", "as": "switched"},
            {"continued": "ctx", "as": "continued"},
            {"notices": "ctx", "as": "notices"},
        ],
    )


class TestCdCommand:
    """Tests for the /cd command."""

    def test_forks_the_session_file_into_the_target(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.mkdir()
        session = tmp_path / "session.jsonl"
        session.write_text("{}\n")
        results = _cd(tmp_path, str(target), session_file=session)
        assert results["switched"] == [str(target / "fork-of-session.jsonl")]

    def test_continues_the_task_only_when_the_tool_requested_the_switch(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        session = tmp_path / "session.jsonl"
        session.write_text("{}\n")
        typed = _cd(tmp_path, str(target), session_file=session)
        requested = _cd(
            tmp_path, str(target), session_file=session, requested_by_tool=True
        )
        assert typed["continued"] == []
        assert requested["continued"] == [[_CONTINUE]]

    def test_files_the_new_session_in_a_custom_session_directory(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        sessions = tmp_path / "sessions"
        sessions.mkdir()
        session = tmp_path / "session.jsonl"
        session.write_text("{}\n")
        forked = _cd(tmp_path, str(target), session_file=session, session_dir=sessions)
        fresh = _cd(
            tmp_path,
            str(target),
            session_file=tmp_path / "unwritten.jsonl",
            session_dir=sessions,
        )
        assert forked["switched"] == [str(sessions / "fork-of-session.jsonl")]
        assert fresh["switched"] == [str(sessions / "new.jsonl")]

    def test_writes_a_header_only_session_when_none_is_on_disk(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        results = _cd(tmp_path, str(target), session_file=tmp_path / "unwritten.jsonl")
        assert results["switched"] == [str(target / "new.jsonl")]
        assert json.loads((target / "new.jsonl").read_text()) == {
            "type": "session",
            "cwd": str(target),
        }

    def test_refuses_a_session_that_is_not_saved(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.mkdir()
        results = _cd(tmp_path, str(target))
        assert results["switched"] == []
        assert results["notices"] == [[_NOT_SAVED, "error"]]
        assert not (target / "new.jsonl").exists()

    def test_shows_usage_for_an_empty_argument(self, tmp_path: Path) -> None:
        results = _cd(tmp_path, "", session_file=tmp_path / "s.jsonl")
        assert results["switched"] == []
        assert results["notices"] == [["Usage: /cd <dir>", "error"]]

    def test_stays_put_when_the_target_is_the_current_directory(
        self, tmp_path: Path
    ) -> None:
        results = _cd(tmp_path, str(tmp_path), session_file=tmp_path / "s.jsonl")
        assert results["switched"] == []
        assert results["notices"] == [[f"Already in {tmp_path}", "info"]]

    def test_removes_the_new_session_file_when_the_switch_is_cancelled(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        results = _cd(
            tmp_path,
            str(target),
            session_file=tmp_path / "unwritten.jsonl",
            cancel=True,
        )
        assert results["switched"] == [str(target / "new.jsonl")]
        assert not (target / "new.jsonl").exists()
        assert results["notices"] == [["Directory change cancelled", "info"]]

    def test_rejects_a_target_that_is_not_a_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing"
        results = _cd(tmp_path, str(missing), session_file=tmp_path / "s.jsonl")
        assert results["switched"] == []
        assert results["notices"] == [[f"Not a directory: {missing}", "error"]]

    @pytest.mark.parametrize(
        ("target", "expected"), [("~", "home"), ("~/sub", "home/sub")]
    )
    def test_expands_a_leading_tilde_to_the_home_directory(
        self, tmp_path: Path, target: str, expected: str
    ) -> None:
        results = _cd(tmp_path, target, session_file=tmp_path / "s.jsonl")
        assert results["switched"] == [str(tmp_path / expected / "new.jsonl")]

    def test_resolves_a_relative_target_against_the_session_directory(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "sub").mkdir()
        results = _cd(tmp_path, "sub", session_file=tmp_path / "s.jsonl")
        assert results["switched"] == [str(tmp_path / "sub" / "new.jsonl")]


def _change_dir(
    tmp_path: Path,
    target: str,
    settled: list[dict[str, Any]],
    *,
    saved: bool = True,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [
        {"fn": "default", "args": [{"$pi": "pi"}]},
        {
            "call": "change_dir",
            "pi": "pi",
            "params": {"path": target},
            "ctx": {
                "$ctx": "ctx",
                "cwd": str(tmp_path),
                "sessionFile": str(tmp_path / "s.jsonl") if saved else None,
            },
            "as": "result",
            "catch": True,
        },
    ]
    steps += [{"emit": "agent_settled", "pi": "pi", "payload": s} for s in settled]
    steps.append({"sent": "pi", "as": "sent"})
    return _run(tmp_path, steps)


class TestChangeDirTool:
    """Tests for the change_dir tool."""

    def test_sends_cd_once_the_agent_has_settled(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        results = _change_dir(tmp_path, "sub", [{"aborted": False}, {"aborted": False}])
        assert results["sent"] == [
            [f"/cd {tmp_path / 'sub'}", {"expandPromptTemplates": True}]
        ]

    def test_expands_a_leading_tilde_to_the_home_directory(
        self, tmp_path: Path
    ) -> None:
        results = _change_dir(tmp_path, "~/sub", [{"aborted": False}])
        assert results["sent"] == [
            [f"/cd {tmp_path / 'home' / 'sub'}", {"expandPromptTemplates": True}]
        ]

    def test_sends_nothing_before_the_agent_has_settled(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        assert _change_dir(tmp_path, "sub", [])["sent"] == []

    def test_sends_nothing_when_the_run_was_aborted(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        assert _change_dir(tmp_path, "sub", [{"aborted": True}])["sent"] == []

    def test_rejects_a_target_that_is_not_a_directory(self, tmp_path: Path) -> None:
        results = _change_dir(tmp_path, "missing", [{"aborted": False}])
        assert results["result"] == {
            "threw": f"Not a directory: {tmp_path / 'missing'}"
        }
        assert results["sent"] == []

    def test_refuses_a_session_that_is_not_saved(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        results = _change_dir(tmp_path, "sub", [{"aborted": False}], saved=False)
        assert results["result"] == {"threw": _NOT_SAVED}
        assert results["sent"] == []
