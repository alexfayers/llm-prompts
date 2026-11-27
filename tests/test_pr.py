"""Tests for the pr module (`llm-prompts pr`)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import FakeSubprocess

from llm_prompts import pr, telemetry_core
from llm_prompts.benchmark.scenarios.checks.judge import JudgeMissing
from llm_prompts.contribute import Checkout
from llm_prompts.size_guard import CheckResult

REPO = Path("/repo")
PREFIX = "src/pkg/prompts/"


def _view(fake: FakeSubprocess, state: str = "OPEN") -> None:
    fake.on(
        "gh",
        "pr",
        "view",
        stdout=json.dumps(
            {"state": state, "headRefName": "feat/x", "baseRefName": "main"}
        ),
    )


def _run(
    *,
    size_passed: bool = True,
    update_status: int = 0,
    clean: bool = True,
    stale: bool = False,
    rebased: bool = False,
) -> tuple[int, MagicMock, MagicMock]:
    with (
        patch(
            "llm_prompts.pr.checkouts", return_value=[Checkout(Path("/wt"), "feat/x")]
        ),
        patch(
            "llm_prompts.pr.size_guard.check",
            return_value=CheckResult(size_passed, [], [], "size report"),
        ) as size,
        patch("llm_prompts.pr.require_judge"),
        patch("llm_prompts.pr.review_and_fix", return_value=clean),
        patch(
            "llm_prompts.pr._require_pr_head",
            return_value="aaa",
            side_effect=pr.StaleCheckout("stale") if stale else None,
        ),
        patch("llm_prompts.pr._pr_head", return_value="bbb" if rebased else "aaa"),
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


def test_a_review_that_is_not_clean_stops_before_sync_and_ready(
    fake_subprocess: FakeSubprocess,
) -> None:
    _view(fake_subprocess)

    status, update, ready = _run(clean=False)

    assert status == 1
    update.assert_not_called()
    ready.assert_not_called()


def test_a_checkout_that_left_the_pr_head_stops_before_sync_and_ready(
    fake_subprocess: FakeSubprocess,
) -> None:
    _view(fake_subprocess)

    status, update, ready = _run(stale=True)

    assert status == 1
    update.assert_not_called()
    ready.assert_not_called()


def test_a_rebase_that_moves_the_pr_head_stops_before_ready(
    fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
) -> None:
    _view(fake_subprocess)

    status, update, ready = _run(rebased=True)

    assert status == 1
    update.assert_called_once()
    ready.assert_not_called()
    assert "Review it again" in capsys.readouterr().out


def test_a_missing_judge_harness_is_refused(
    fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
) -> None:
    _view(fake_subprocess)

    with (
        patch(
            "llm_prompts.pr.checkouts", return_value=[Checkout(Path("/wt"), "feat/x")]
        ),
        patch("llm_prompts.pr.require_judge", side_effect=JudgeMissing("no pi")),
        patch("llm_prompts.pr.size_guard.check") as size,
    ):
        assert pr.run_pr(REPO, PREFIX, 7) == 1
    size.assert_not_called()
    assert "no pi" in capsys.readouterr().out


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


def _review(
    replies: list[str],
    *,
    committed: bool = True,
    after_fix: bool = True,
    dirty: str = "",
) -> tuple[bool, MagicMock, MagicMock]:
    """Run the loop with the agent answering ``replies`` in turn: each review reply, then each fix reply, in call order."""
    asked = MagicMock(side_effect=replies)
    after = MagicMock(return_value=after_fix)
    with (
        patch("llm_prompts.pr.judge_harness", return_value="pi"),
        patch("llm_prompts.pr.AGENTS", {"pi": MagicMock(judge_model="m")}),
        patch("llm_prompts.pr._brief", return_value="brief"),
        patch(
            "llm_prompts.pr._gh", return_value=json.dumps({"title": "t", "body": "b"})
        ),
        patch(
            "llm_prompts.pr._git",
            side_effect=lambda _p, *a: dirty if a[0] == "status" else "local diff",
        ),
        patch("llm_prompts.pr._require_pr_head"),
        patch("llm_prompts.pr._ask", asked),
        patch("llm_prompts.pr._commit_fixes", return_value=committed),
        patch("llm_prompts.pr._push") as push,
    ):
        clean = pr.review_and_fix(Path("/wt"), 7, "feat/x", "origin/main", after)
    return clean, asked, push


def test_a_clean_first_review_fixes_and_pushes_nothing() -> None:
    clean, asked, push = _review(["OUTCOME review\nCLEAN"])

    assert clean
    asked.assert_called_once()
    assert "local diff" in asked.call_args.args[2]
    push.assert_not_called()


def test_a_clean_line_without_an_outcome_line_is_not_clean() -> None:
    clean, asked, _ = _review(
        ["CLEAN", "f1", "OUTCOME review\n\nCLEAN", "f2", "OUTCOME review\nCLEAN  "]
    )

    assert clean
    assert asked.call_count == 5


def test_an_outcome_line_after_other_text_is_not_clean() -> None:
    clean, asked, _ = _review(
        ["Looks fine.\nOUTCOME review\nCLEAN", "f1", "\n OUTCOME review\nCLEAN"]
    )

    assert clean
    assert asked.call_count == 3


def test_deferred_lines_after_clean_still_pass_the_review() -> None:
    clean, asked, _ = _review(["OUTCOME review\nCLEAN\nDEFERRED: a.py:3 (medium) x\n"])

    assert clean
    asked.assert_called_once()


def test_a_clean_line_beside_numbered_findings_is_not_clean() -> None:
    clean, asked, _ = _review(
        [
            "OUTCOME review\nCLEAN\n1. a.py:1 (high) fix it",
            "fixed",
            "OUTCOME review\nCLEAN",
        ]
    )

    assert clean
    assert asked.call_count == 3
    assert "1. a.py:1 (high) fix it" in asked.call_args_list[1].args[2]


def test_the_brief_tells_the_reviewer_the_verdict_format() -> None:
    with patch("llm_prompts.pr.render_template", return_value="loop"):
        assert pr.VERDICT_FORMAT in pr._brief(Path("/wt"))


def test_findings_are_fixed_reviewed_again_and_pushed_once_clean() -> None:
    clean, asked, push = _review(
        ["1. a.py:1 (high) fix it", "fixed", "OUTCOME review\nCLEAN"]
    )

    assert clean
    assert "Earlier findings:\n1. a.py:1" in asked.call_args_list[2].args[2]
    push.assert_called_once_with(Path("/wt"), "feat/x")


def test_findings_that_survive_every_fix_round_end_not_clean_and_unpushed() -> None:
    clean, asked, push = _review(["1. still"] * (2 * pr.MAX_FIX_ROUNDS + 1))

    assert not clean
    assert asked.call_count == 2 * pr.MAX_FIX_ROUNDS + 1
    push.assert_not_called()


def test_a_fixer_that_changes_nothing_ends_the_loop() -> None:
    clean, asked, push = _review(["1. a", "no change"], committed=False)

    assert not clean
    assert asked.call_count == 2
    push.assert_not_called()


def test_a_failed_check_after_a_fix_ends_the_loop_unpushed() -> None:
    clean, asked, push = _review(["1. a", "fixed"], after_fix=False)

    assert not clean
    assert asked.call_count == 2
    push.assert_not_called()


def test_a_checkout_that_is_not_the_pr_head_is_refused_before_any_review() -> None:
    asked = MagicMock()
    with (
        patch(
            "llm_prompts.pr._git",
            side_effect=lambda _p, *a: "" if a[0] == "status" else "aaa111\n",
        ),
        patch("llm_prompts.pr._gh", return_value=json.dumps({"headRefOid": "bbb222"})),
        patch("llm_prompts.pr._ask", asked),
        pytest.raises(pr.StaleCheckout),
    ):
        pr.review_and_fix(Path("/wt"), 7, "feat/x", "origin/main", MagicMock())
    asked.assert_not_called()


def test_a_dirty_worktree_is_refused_before_any_review() -> None:
    asked = MagicMock()
    with (
        patch("llm_prompts.pr._git", return_value=" M other.py\n"),
        patch("llm_prompts.pr._ask", asked),
        pytest.raises(pr.DirtyWorktree),
    ):
        pr.review_and_fix(Path("/wt"), 7, "feat/x", "origin/main", MagicMock())
    asked.assert_not_called()


def test_fixes_are_folded_into_the_tip_commit_without_pushing(
    fake_subprocess: FakeSubprocess,
) -> None:
    fake_subprocess.on("status", stdout=" M a.py\n")
    fake_subprocess.on("merge-base", stdout="abc\n")

    assert pr._commit_fixes(Path("/wt"), "origin/main")

    assert fake_subprocess.verbs == [
        "status --porcelain",
        "add -A",
        "commit --fixup=HEAD",
        "merge-base HEAD origin/main",
        "rebase -i --autosquash abc",
    ]


def test_a_clean_working_tree_commits_nothing(fake_subprocess: FakeSubprocess) -> None:
    assert not pr._commit_fixes(Path("/wt"), "origin/main")
    assert fake_subprocess.verbs == ["status --porcelain"]


def test_a_push_leases_the_pr_branch(fake_subprocess: FakeSubprocess) -> None:
    pr._push(Path("/wt"), "feat/x")

    assert fake_subprocess.verbs == ["push --force-with-lease origin HEAD:feat/x"]


@pytest.mark.parametrize(
    ("replies", "after_fix", "expected"),
    [
        (
            [
                "OUTCOME review\n1. a.py:1 bug",
                "fixed",
                "OUTCOME review\nCLEAN\nDEFERRED: b.py:2 (medium) x; c.py:3 (rare) y",
            ],
            True,
            {"rounds": 1, "end": "clean", "deferred": 2},
        ),
        (
            ["OUTCOME review\n1. a.py:1 bug", "fixed"],
            False,
            {"rounds": 1, "end": "escalated", "deferred": 0},
        ),
    ],
)
def test_a_finished_review_loop_sends_its_rounds_end_and_deferred_count(
    telemetry_popen: MagicMock,
    isolated_config_dir: Path,
    replies: list[str],
    after_fix: bool,
    expected: dict[str, object],
) -> None:
    record = {"install_id": "synthetic-id", "opted_out": False, "at": time.time()}
    (isolated_config_dir / "telemetry.json").write_text(json.dumps(record))

    _review(replies, after_fix=after_fix)

    [call] = telemetry_popen.call_args_list
    event = json.loads(telemetry_core.resolve_versions(call.args[0][3]))
    properties = event["properties"]
    assert event["event"] == "pr_review"
    assert {k: properties[k] for k in expected} == expected
    assert set(properties) == {
        *expected,
        *("llm_prompts", "cline_hooks", "mcp_memory"),
        *("os", "python", "schema", "$process_person_profile"),
    }
    sent = json.dumps(event)
    for private in ("feat/x", "/wt", "a.py", "origin/main", '"t"'):
        assert private not in sent
    assert not re.search(r"\b7\b", sent.replace(properties["python"], ""))
