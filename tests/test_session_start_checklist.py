"""Tests for the session-start skill's checklist script."""

from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src/llm_prompts/prompts/shared/skills/session-start/checklist.py"
)


@pytest.fixture
def checklist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> Callable[..., list[str]]:
    """Run the script's main from an empty directory and return its printed lines."""
    main = runpy.run_path(str(_SCRIPT))["main"]
    monkeypatch.chdir(tmp_path)

    def run(*args: str) -> list[str]:
        assert main(list(args)) == 0
        return capsys.readouterr().out.splitlines()

    return run


def test_prints_nothing_when_no_step_applies(
    checklist: Callable[..., list[str]],
) -> None:
    assert checklist("--agent", "claude-code") == []


def test_handoff_in_the_git_root_replaces_all_steps_for_an_unhooked_agent_only(
    checklist: Callable[..., list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "HANDOFF.md").write_text("")
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path / "sub")

    assert checklist("--agent", "codex") == ["1. Run the `pickup` skill and stop."]
    assert "pickup" not in "".join(checklist("--agent", "pi"))


def test_handoff_above_the_git_root_is_found(
    checklist: Callable[..., list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "HANDOFF.md").write_text("")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)

    assert checklist("--agent", "codex") == ["1. Run the `pickup` skill and stop."]


def test_steps_follow_the_flags_in_order(
    checklist: Callable[..., list[str]], tmp_path: Path
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "RULES.md").write_text("")

    steps = checklist("--agent", "codex", "--outstanding", "--updates")

    markers = (
        "RULES.md",
        "read_graph",
        "projects=",
        "ONE table",
        "source updates",
        "`todos` skill",
        "--no-merged",
    )
    assert all(m in s for m, s in zip(markers, steps, strict=True))


def test_everywhere_searches_every_project(
    checklist: Callable[..., list[str]],
) -> None:
    (search, *_) = checklist("--agent", "pi", "--everywhere")

    assert "projects=" not in search
