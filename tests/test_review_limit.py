"""Tests for the in-flight review limit guard."""

from __future__ import annotations

import logging
import subprocess
import sys
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
    """Turn the guards on and report 5 of the user's open PRs in acme/widgets to `gh api`."""
    monkeypatch.setenv("CLINE_HOOKS_FRONTEND", "pi")
    replies = {
        "user": "me\n",
        "pulls": "me\nother\n" + "me\n" * 4,
        "repos": "acme/widgets\n",
    }
    run = MagicMock(
        side_effect=lambda args, **_: MagicMock(
            returncode=0,
            stdout=next(v for k, v in replies.items() if k in args[4]),
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


@pytest.mark.parametrize(
    ("command", "repo", "cwd"),
    [
        ("cd x && gh pr create --fill", "acme/widgets", "/work/x"),
        ("gh pr create --repo other/app --fill", "other/app", "/work"),
        ("gh pr create -R other/app --fill", "other/app", "/work"),
        ("gh pr create --repo=other/app --fill", "other/app", "/work"),
    ],
)
def test_blocks_a_new_pr_at_the_limit_of_the_repo_it_targets(
    open_prs: MagicMock, command: str, repo: str, cwd: str
) -> None:
    result = _guard(command)
    assert result is not None and f"{repo} are open, at the limit of 5" in (
        result.block or ""
    )
    assert open_prs.call_args.kwargs["cwd"] == cwd
    assert open_prs.call_args.args[0][4].startswith(f"repos/{repo}/pulls?state=open")
    assert "--paginate" in open_prs.call_args.args[0]


def test_counts_a_repo_named_with_its_host_on_that_host(open_prs: MagicMock) -> None:
    assert _guard("gh pr create --repo ghe.example.com/other/app --fill") is not None
    calls = [c.args[0] for c in open_prs.call_args_list]
    assert calls[-1][4].startswith("repos/other/app/pulls?")
    assert all(c[-2:] == ["--hostname", "ghe.example.com"] for c in calls)


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


@pytest.mark.usefixtures("open_prs")
def test_a_repo_limit_matches_the_repo_in_any_case(isolated_config_dir: Path) -> None:
    (isolated_config_dir / "config.toml").write_text(
        '[reviews]\nmax_in_flight = 5\n\n[reviews.repos]\n"ACME/widgets" = 9\n'
    )
    assert _guard("gh pr create --repo Acme/Widgets --fill") is None


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


@pytest.mark.real_io
def test_import_skips_the_shell_parser() -> None:
    check = (
        "import sys, llm_prompts.guards.review_limit; print('bashlex' in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", check], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "False"
