"""Tests for the fake_subprocess fixture's side-effect handling."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import ContributeRemote, FakeSubprocess


def test_callable_side_effect_result_replaces_the_canned_response(
    fake_subprocess: FakeSubprocess,
) -> None:
    seen: list[tuple[list[str], dict[str, Any]]] = []

    def _effect(
        argv: list[str], kwargs: dict[str, Any]
    ) -> subprocess.CompletedProcess[str]:
        seen.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 7, "from effect", "boom")

    fake_subprocess.on("status", stdout="canned", returncode=1, side_effect=_effect)

    result = subprocess.run(["git", "status"], text=True, check=False)

    assert seen == [(["git", "status"], {"text": True, "check": False})]
    assert (result.returncode, result.stdout, result.stderr) == (
        7,
        "from effect",
        "boom",
    )


def test_callable_side_effect_returning_none_falls_through_to_canned_values(
    fake_subprocess: FakeSubprocess,
) -> None:
    seen: list[list[str]] = []

    def _effect(argv: list[str], kwargs: dict[str, Any]) -> None:
        seen.append(argv)

    fake_subprocess.on("status", stdout="canned", returncode=2, side_effect=_effect)

    result = subprocess.run(["git", "status"], text=True, check=False)

    assert seen == [["git", "status"]]
    assert (result.returncode, result.stdout) == (2, "canned")


def test_callable_class_side_effect_is_called_not_raised(
    fake_subprocess: FakeSubprocess,
) -> None:
    seen: list[list[str]] = []

    class _Effect(subprocess.CompletedProcess[str]):
        def __init__(self, argv: list[str], kwargs: dict[str, Any]) -> None:
            super().__init__(argv, 7, "from callable class", "")
            seen.append(argv)

    fake_subprocess.on("status", stdout="canned", returncode=1, side_effect=_Effect)

    result = subprocess.run(["git", "status"], text=True, check=False)

    assert seen == [["git", "status"]]
    assert (result.returncode, result.stdout) == (7, "from callable class")


def test_exception_class_side_effect_is_raised(fake_subprocess: FakeSubprocess) -> None:
    fake_subprocess.on("status", side_effect=RuntimeError)

    with pytest.raises(RuntimeError):
        subprocess.run(["git", "status"], text=True, check=False)


def test_repo_route_matches_a_call_made_with_that_cwd(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    fake_subprocess.on("gh", "pr", "list", stdout="routed", repo=tmp_path)

    result = subprocess.run(
        ["gh", "pr", "list"], cwd=tmp_path, text=True, check=False, capture_output=True
    )

    assert result.stdout == "routed"


def test_repo_route_ignores_a_call_made_with_another_cwd(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    fake_subprocess.on("gh", "pr", "list", stdout="routed", repo=tmp_path / "a")

    result = subprocess.run(
        ["gh", "pr", "list"],
        cwd=tmp_path / "b",
        text=True,
        check=False,
        capture_output=True,
    )

    assert result.stdout == ""


def test_repo_route_still_matches_the_dash_c_form(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    fake_subprocess.on("status", stdout="routed", repo=tmp_path)

    result = subprocess.run(
        ["git", "-C", str(tmp_path), "status"],
        text=True,
        check=False,
        capture_output=True,
    )

    assert result.stdout == "routed"


def _open_pr_items(contribute_remote: ContributeRemote) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--author",
            "@me",
            "--json",
            "number,state,url,headRefName,isDraft,reviewDecision,body",
        ],
        text=True,
        check=True,
        capture_output=True,
    )
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def test_open_pr_item_carries_an_empty_body_by_default(
    contribute_remote: ContributeRemote,
) -> None:
    contribute_remote.unmanaged_pr("someone/x", 3, [("c1", "feat: x")])

    assert _open_pr_items(contribute_remote)[0]["body"] == ""


def test_open_pr_item_carries_the_body_set_for_it(
    contribute_remote: ContributeRemote,
) -> None:
    contribute_remote.unmanaged_pr("someone/x", 3, [("c1", "feat: x")])
    contribute_remote.body(3, "Depends on https://x/pull/1")

    assert _open_pr_items(contribute_remote)[0]["body"] == "Depends on https://x/pull/1"
