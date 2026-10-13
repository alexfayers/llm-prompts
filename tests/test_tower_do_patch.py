"""Tests for the tower-do-patch pi extension."""

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
    / "tower-do-patch.ts"
)
_HARNESS = Path(__file__).parent / "tower_do_patch_harness.mjs"


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
    config.write_text(json.dumps({"script": str(_SCRIPT), "steps": steps}))
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


class TestMergeTasks:
    """Tests for building the full task list from a partial change."""

    def test_upserts_lead_and_every_other_current_key_is_sent_bare(
        self, tmp_path: Path
    ) -> None:
        steps: list[dict[str, Any]] = [
            {
                "fn": "mergeTasks",
                "args": [
                    ["a", "b", "c"],
                    [
                        {"key": "b", "status": "completed"},
                        {"key": "d", "subject": "new"},
                    ],
                    [],
                ],
                "as": "merged",
            }
        ]
        assert _run(tmp_path, steps)["merged"] == [
            {"key": "b", "status": "completed"},
            {"key": "d", "subject": "new"},
            {"key": "a"},
            {"key": "c"},
        ]

    def test_removed_keys_are_left_out_of_the_list(self, tmp_path: Path) -> None:
        steps: list[dict[str, Any]] = [
            {
                "fn": "mergeTasks",
                "args": [["a", "b", "c"], [{"key": "c", "status": "pending"}], ["a"]],
                "as": "merged",
            }
        ]
        assert _run(tmp_path, steps)["merged"] == [
            {"key": "c", "status": "pending"},
            {"key": "b"},
        ]

    @pytest.mark.parametrize(
        ("current", "upserts", "removes", "message"),
        [
            (["a"], [{"key": "a"}], ["a"], "both"),
            (["a"], [{"key": "b"}, {"key": "b"}], [], "duplicate"),
            (["a"], [], ["a", "a"], "duplicate"),
            (["a"], [], ["z"], "unknown"),
            (["a"], [], [], "nothing"),
        ],
    )
    def test_conflicting_or_empty_patch_is_rejected(
        self,
        tmp_path: Path,
        current: list[str],
        upserts: list[dict[str, Any]],
        removes: list[str],
        message: str,
    ) -> None:
        steps: list[dict[str, Any]] = [
            {
                "fn": "mergeTasks",
                "args": [current, upserts, removes],
                "as": "merged",
                "catch": True,
            }
        ]
        assert message in _run(tmp_path, steps)["merged"]["threw"]


_OK: dict[str, Any] = {
    "isError": False,
    "result": {"content": [{"type": "text", "text": "ok"}]},
}


def _stale(revision: int) -> dict[str, Any]:
    text = f"stale tower-do revision: expected 1, current board revision is {revision}"
    return {"isError": True, "result": {"content": [{"type": "text", "text": text}]}}


def _deps(
    boards: list[dict[str, Any]], outcomes: list[dict[str, Any]]
) -> dict[str, Any]:
    return {"$deps": {"boards": boards, "outcomes": outcomes}, "name": "deps"}


_BOARD = {"revision": 7, "keys": ["a", "b"]}


class TestApplyPatch:
    """Tests for patching the board through the real tower_do."""

    def test_writes_the_merged_list_at_the_folded_revision_and_returns_the_outcome(
        self, tmp_path: Path
    ) -> None:
        steps: list[dict[str, Any]] = [
            {
                "fn": "applyPatch",
                "args": [
                    {
                        "tasks": [{"key": "c", "subject": "new"}],
                        "remove": ["a"],
                        "as": "me",
                    },
                    _deps([_BOARD], [_OK]),
                ],
                "as": "outcome",
            },
            {"writes": "deps", "as": "writes"},
        ]
        results = _run(tmp_path, steps)
        assert results["writes"] == [
            {
                "tasks": [{"key": "c", "subject": "new"}, {"key": "b"}],
                "baseRevision": 7,
                "as": "me",
            }
        ]
        assert results["outcome"] == _OK

    def test_a_given_revision_is_sent_as_is_and_a_stale_error_is_returned_without_retry(
        self, tmp_path: Path
    ) -> None:
        steps: list[dict[str, Any]] = [
            {
                "fn": "applyPatch",
                "args": [
                    {"remove": ["a"], "baseRevision": 3},
                    _deps([_BOARD], [_stale(7), _OK]),
                ],
                "as": "outcome",
            },
            {"writes": "deps", "as": "writes"},
        ]
        results = _run(tmp_path, steps)
        assert [w["baseRevision"] for w in results["writes"]] == [3]
        assert results["outcome"] == _stale(7)

    def test_a_stale_error_without_a_given_revision_refolds_and_retries_up_to_three_times(
        self, tmp_path: Path
    ) -> None:
        boards = [{"revision": r, "keys": ["a", "b"]} for r in (7, 8, 9, 10)]
        steps: list[dict[str, Any]] = [
            {
                "fn": "applyPatch",
                "args": [{"remove": ["a"]}, _deps(boards, [_stale(8), _stale(9), _OK])],
                "as": "recovered",
            },
            {"writes": "deps", "as": "writes"},
            {
                "fn": "applyPatch",
                "args": [
                    {"remove": ["a"]},
                    {**_deps(boards, [_stale(8)]), "name": "never"},
                ],
                "as": "exhausted",
            },
            {"writes": "never", "as": "attempts"},
        ]
        results = _run(tmp_path, steps)
        assert [w["baseRevision"] for w in results["writes"]] == [7, 8, 9]
        assert results["recovered"] == _OK
        assert len(results["attempts"]) == 4
        assert results["exhausted"] == _stale(8)


_PI = {"$pi": "pi", "board": _BOARD}
_CTX = {"$ctx": "ctx", "outcomes": [_OK]}


class TestPatchTool:
    """Tests for the registered tower_do_patch tool."""

    def test_registers_a_sequential_tool_with_guidelines_pointing_at_it(
        self, tmp_path: Path
    ) -> None:
        steps: list[dict[str, Any]] = [
            {"register": _PI},
            {"registered": "pi", "as": "tools"},
        ]
        (tool,) = _run(tmp_path, steps)["tools"]
        assert tool["name"] == "tower_do_patch"
        assert tool["executionMode"] == "sequential"
        assert any("tower_do_patch" in line for line in tool["promptGuidelines"])

    def test_execute_folds_the_board_and_calls_tower_do_with_the_merged_list(
        self, tmp_path: Path
    ) -> None:
        steps: list[dict[str, Any]] = [
            {"register": _PI},
            {
                "call": "tower_do_patch",
                "pi": "pi",
                "params": {"tasks": [{"key": "c", "subject": "new"}], "as": "me"},
                "ctx": _CTX,
                "as": "result",
            },
            {"calls": "ctx", "as": "calls"},
        ]
        results = _run(tmp_path, steps)
        assert results["calls"] == [
            ["tower_do_status", {"view": "mine"}],
            [
                "tower_do",
                {
                    "tasks": [
                        {"key": "c", "subject": "new"},
                        {"key": "a"},
                        {"key": "b"},
                    ],
                    "baseRevision": 7,
                    "as": "me",
                },
            ],
        ]
        assert results["result"]["content"] == _OK["result"]["content"]

    def test_a_failed_tower_do_call_fails_the_tool_with_its_message(
        self, tmp_path: Path
    ) -> None:
        steps: list[dict[str, Any]] = [
            {"register": _PI},
            {
                "call": "tower_do_patch",
                "pi": "pi",
                "params": {"remove": ["a"], "baseRevision": 3},
                "ctx": {"$ctx": "ctx", "outcomes": [_stale(7)]},
                "as": "result",
                "catch": True,
            },
        ]
        assert "stale tower-do revision" in _run(tmp_path, steps)["result"]["threw"]


def _task(key: str, status: str, owner: str | None = None) -> dict[str, Any]:
    return {"key": key, "status": status, **({"owner": owner} if owner else {})}


class TestBoardSummary:
    """Tests for the first-turn board summary text."""

    def _summary(self, tmp_path: Path, tasks: list[dict[str, Any]]) -> str | None:
        steps: list[dict[str, Any]] = [
            {"fn": "boardSummary", "args": [tasks], "as": "summary"}
        ]
        summary: str | None = _run(tmp_path, steps).get("summary")
        return summary

    def test_an_empty_board_gives_no_summary(self, tmp_path: Path) -> None:
        assert self._summary(tmp_path, []) is None

    def test_counts_by_status_and_lists_open_tasks_with_owner(
        self, tmp_path: Path
    ) -> None:
        tasks = [
            _task("a", "in_progress", "me"),
            _task("b", "pending"),
            _task("c", "completed", "me"),
            _task("d", "completed"),
        ]

        assert self._summary(tmp_path, tasks) == (
            "Task board: 1 in_progress, 1 pending, 2 completed.\n"
            "Open: a in_progress @me; b pending"
        )

    def test_a_board_of_only_completed_tasks_lists_no_open_tasks(
        self, tmp_path: Path
    ) -> None:
        assert self._summary(tmp_path, [_task("a", "completed")]) == (
            "Task board: 1 completed."
        )

    def test_a_long_open_list_is_cut_to_the_cap_with_a_count_of_the_rest(
        self, tmp_path: Path
    ) -> None:
        tasks = [_task(f"task-number-{n:03}", "pending", "owner") for n in range(100)]

        summary = self._summary(tmp_path, tasks)

        assert summary is not None
        assert len(summary) <= 600
        assert summary.startswith("Task board: 100 pending.\nOpen: task-number-000")
        assert summary.endswith(" more")


_MAIN_SESSION: dict[str, Any] = {"PI_SUBAGENT_CHILD": None, "PI_HERDSMAN_MAILBOX": None}
_START_CTX = {"cwd": "/proj"}
_TASKS = [_task("a", "in_progress", "me"), _task("b", "completed")]


def _first_turn(
    tmp_path: Path,
    board: dict[str, Any],
    *starts: dict[str, Any],
) -> list[Any]:
    pi = {"$pi": "pi", "board": board}
    steps: list[dict[str, Any]] = [{"register": pi}]
    steps += [
        {
            "emit": "before_agent_start",
            "pi": "pi",
            "ctx": _START_CTX,
            "as": f"s{n}",
            **env,
        }
        for n, env in enumerate(starts)
    ]
    results = _run(tmp_path, steps)
    return [results.get(f"s{n}") for n in range(len(starts))]


class TestFirstTurnBoardSummary:
    """Tests for the board summary injected at the first agent start of a main session."""

    def test_the_first_main_session_start_gets_a_hidden_board_summary_and_later_starts_do_not(
        self, tmp_path: Path
    ) -> None:
        board = {"revision": 3, "keys": ["a", "b"], "tasks": _TASKS}
        main = {"env": _MAIN_SESSION}

        first, second = _first_turn(tmp_path, board, main, main)

        assert first == {
            "message": {
                "customType": "tower-do-first-turn-board",
                "content": "Task board: 1 in_progress, 1 completed.\nOpen: a in_progress @me",
                "display": False,
            }
        }
        assert second is None

    @pytest.mark.parametrize("variable", ["PI_SUBAGENT_CHILD", "PI_HERDSMAN_MAILBOX"])
    def test_a_subagent_or_herdsman_child_gets_no_summary(
        self, tmp_path: Path, variable: str
    ) -> None:
        board = {"revision": 3, "keys": ["a", "b"], "tasks": _TASKS}

        (result,) = _first_turn(
            tmp_path, board, {"env": {**_MAIN_SESSION, variable: "1"}}
        )

        assert result is None

    @pytest.mark.parametrize(
        "board",
        [
            {"revision": 0, "keys": [], "tasks": []},
            {"revision": 1, "keys": ["a"], "fails": True},
        ],
        ids=["empty", "unreadable"],
    )
    def test_an_empty_or_unreadable_board_gives_no_summary(
        self, tmp_path: Path, board: dict[str, Any]
    ) -> None:
        (result,) = _first_turn(tmp_path, board, {"env": _MAIN_SESSION})

        assert result is None

    @pytest.mark.parametrize(
        ("reason", "summarised"),
        [
            ("startup", True),
            ("new", True),
            ("reload", False),
            ("resume", False),
            ("fork", False),
        ],
    )
    def test_only_a_fresh_session_start_re_arms_the_summary(
        self, tmp_path: Path, reason: str, summarised: bool
    ) -> None:
        board = {"revision": 3, "keys": ["a", "b"], "tasks": _TASKS}
        steps: list[dict[str, Any]] = [
            {"register": {"$pi": "pi", "board": board}},
            {
                "emit": "before_agent_start",
                "pi": "pi",
                "ctx": _START_CTX,
                "env": _MAIN_SESSION,
            },
            {
                "emit": "session_start",
                "pi": "pi",
                "ctx": _START_CTX,
                "event": {"reason": reason},
            },
            {
                "emit": "before_agent_start",
                "pi": "pi",
                "ctx": _START_CTX,
                "env": _MAIN_SESSION,
                "as": "again",
            },
        ]

        again = _run(tmp_path, steps).get("again")

        assert (again is not None) is summarised

    def test_an_unreadable_board_is_reported_to_the_ui(self, tmp_path: Path) -> None:
        board = {"revision": 1, "keys": ["a"], "fails": True}
        ctx = {"$ctx": "ui", "cwd": "/proj", "hasUI": True}
        steps: list[dict[str, Any]] = [
            {"register": {"$pi": "pi", "board": board}},
            {
                "emit": "before_agent_start",
                "pi": "pi",
                "ctx": ctx,
                "env": _MAIN_SESSION,
                "as": "result",
            },
            {"notifications": "ui", "as": "notes"},
        ]

        results = _run(tmp_path, steps)

        assert results.get("result") is None
        assert [
            (level, "unreadable board" in text) for text, level in results["notes"]
        ] == [("warning", True)]

    def test_a_cwd_whose_board_file_cannot_be_derived_gives_no_summary_and_no_crash(
        self, tmp_path: Path
    ) -> None:
        board = {"revision": 1, "keys": ["a"], "tasks": _TASKS, "fileFails": True}
        ctx = {"$ctx": "ui", "cwd": str(tmp_path / "not-a-git-repo"), "hasUI": True}
        steps: list[dict[str, Any]] = [
            {"register": {"$pi": "pi", "board": board}},
            {
                "emit": "before_agent_start",
                "pi": "pi",
                "ctx": ctx,
                "env": _MAIN_SESSION,
                "as": "result",
            },
            {"notifications": "ui", "as": "notes"},
        ]

        results = _run(tmp_path, steps)

        assert results.get("result") is None
        assert [level for _, level in results["notes"]] == ["warning"]
