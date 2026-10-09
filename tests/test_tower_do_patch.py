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
