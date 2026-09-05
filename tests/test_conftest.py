"""Tests for the fake_subprocess fixture's side-effect handling."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest
from conftest import FakeSubprocess


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
