"""Tests for the in-flight review limit guard."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cline_hooks.core.plugin import HookResult, HooksPlugin, hookimpl, plugins_override
from cline_hooks.handlers.commands import ParsedCommand

from llm_prompts.guards.review_limit import ReviewLimitGuard


@pytest.fixture(autouse=True)
def guard_loaded() -> Iterator[None]:
    """Load only this guard, with its built-in GitHub source."""
    with plugins_override([ReviewLimitGuard()]):
        yield


@pytest.fixture
def open_prs(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Turn the guards on and report 5 open PRs in acme/widgets to `gh api`."""
    monkeypatch.setenv("CLINE_HOOKS_FRONTEND", "pi")
    run = MagicMock(
        side_effect=lambda args, **_: MagicMock(
            returncode=0,
            stdout="acme/widgets\n" if args[4].startswith("repos/") else "5\n",
        )
    )
    monkeypatch.setattr("llm_prompts.guards.review_limit.subprocess.run", run)
    return run


def _guard(command: str) -> HookResult | None:
    return ReviewLimitGuard().on_hook(
        "PreShell",
        logger=logging.getLogger("test"),
        command=command,
        workspace_roots=["/work"],
    )


@pytest.mark.usefixtures("open_prs")
def test_blocks_a_new_pr_at_the_limit_of_the_repo_it_runs_in(
    open_prs: MagicMock,
) -> None:
    result = _guard("cd x && gh pr create --fill")
    assert result is not None and "acme/widgets are open, at the limit of 5" in (
        result.block or ""
    )
    assert open_prs.call_args.kwargs["cwd"] == "/work/x"
    assert "repo:acme/widgets" in open_prs.call_args.args[0][4]


@pytest.mark.parametrize("command", ["gh pr edit 5 --title x", "git push"])
def test_never_blocks_updates_or_checks_the_count(
    open_prs: MagicMock, command: str
) -> None:
    assert _guard(command) is None
    open_prs.assert_not_called()


@pytest.mark.usefixtures("open_prs")
def test_a_raised_limit_applies_to_the_next_check(isolated_config_dir: Path) -> None:
    (isolated_config_dir / "config.toml").write_text("[reviews]\nmax_in_flight = 6\n")
    assert _guard("gh pr create --fill") is None


@pytest.mark.usefixtures("open_prs")
def test_a_repo_limit_overrides_the_default(isolated_config_dir: Path) -> None:
    (isolated_config_dir / "config.toml").write_text(
        '[reviews]\nmax_in_flight = 9\n\n[reviews.repos]\n"acme/widgets" = 5\n'
    )
    assert _guard("gh pr create --fill") is not None


def test_a_registered_source_blocks_at_its_limit(
    open_prs: MagicMock, isolated_config_dir: Path
) -> None:
    class FakeSource(HooksPlugin):
        @hookimpl
        def open_reviews(
            self, command: ParsedCommand, cwd: str
        ) -> tuple[str, int] | None:
            return ("team/pkg", 2) if command.name == "review" else None

    (isolated_config_dir / "config.toml").write_text(
        '[reviews.repos]\n"team/pkg" = 2\n'
    )
    with plugins_override([ReviewLimitGuard(), FakeSource()]):
        result = _guard("review --draft")
    assert result is not None and "team/pkg are open, at the limit of 2" in (
        result.block or ""
    )
