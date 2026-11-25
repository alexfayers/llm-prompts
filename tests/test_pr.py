"""Tests for the pr module (`llm-prompts pr`)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import FakeSubprocess

from llm_prompts import pr
from llm_prompts.contribute import Checkout
from llm_prompts.size_guard import CheckResult

REPO = Path("/repo")
PREFIX = "src/pkg/prompts/"


def _view(fake: FakeSubprocess, state: str = "OPEN") -> None:
    fake.on(
        "gh",
        "pr",
        "view",
        stdout=json.dumps({"state": state, "headRefName": "feat/x"}),
    )


def _run(
    *, size_passed: bool = True, update_status: int = 0
) -> tuple[int, MagicMock, MagicMock]:
    with (
        patch(
            "llm_prompts.pr.checkouts", return_value=[Checkout(Path("/wt"), "feat/x")]
        ),
        patch(
            "llm_prompts.pr.size_guard.check",
            return_value=CheckResult(size_passed, [], [], "size report"),
        ) as size,
        patch("llm_prompts.pr.run_update", return_value=update_status) as update,
        patch("llm_prompts.pr.run_ready", return_value=0) as ready,
    ):
        status = pr.run_pr(REPO, PREFIX, 7)
    size.assert_called_once_with([Path("/wt") / PREFIX])
    return status, update, ready


def test_a_pr_is_synced_then_marked_ready(fake_subprocess: FakeSubprocess) -> None:
    _view(fake_subprocess)

    status, update, ready = _run()

    assert status == 0
    update.assert_called_once_with(REPO, True, (7,))
    ready.assert_called_once_with(REPO, 7)


def test_a_failed_size_check_stops_before_sync_and_ready(
    fake_subprocess: FakeSubprocess,
) -> None:
    _view(fake_subprocess)

    status, update, ready = _run(size_passed=False)

    assert status == 1
    update.assert_not_called()
    ready.assert_not_called()


def test_a_failed_sync_stops_before_ready(fake_subprocess: FakeSubprocess) -> None:
    _view(fake_subprocess)

    status, _, ready = _run(update_status=1)

    assert status == 1
    ready.assert_not_called()


@pytest.mark.parametrize("state", ["CLOSED", "MERGED"])
def test_a_pr_that_is_not_open_is_refused(
    fake_subprocess: FakeSubprocess, state: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _view(fake_subprocess, state)

    with patch("llm_prompts.pr.checkouts") as checkouts:
        assert pr.run_pr(REPO, PREFIX, 7) == 1
    checkouts.assert_not_called()
    assert f"#7 is {state.lower()}" in capsys.readouterr().out


def test_a_pr_branch_with_no_worktree_is_refused(
    fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
) -> None:
    _view(fake_subprocess)

    with patch("llm_prompts.pr.checkouts", return_value=[]):
        assert pr.run_pr(REPO, PREFIX, 7) == 1
    assert "feat/x" in capsys.readouterr().out
