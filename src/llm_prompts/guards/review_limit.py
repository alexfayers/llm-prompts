"""Cline-hooks plugin that blocks a new review while too many of the user's reviews in its scope are open."""

from __future__ import annotations

import os
import subprocess
import tomllib
from typing import TYPE_CHECKING, cast

import bashlex  # type: ignore[import-untyped]
import bashlex.errors  # type: ignore[import-untyped]
from cline_hooks.core.plugin import (
    HookResult,
    HooksPlugin,
    collect_contributions,
    hookimpl,
    hookspec,
)
from cline_hooks.core.vocabulary import PluginScope
from cline_hooks.handlers.commands import ParsedCommand, extract_commands
from cline_hooks.handlers.search_scope import effective_cwd

from ..telemetry_core import read_config
from .gate import guards_active

if TYPE_CHECKING:
    import logging

DEFAULT_LIMIT = 5


def _gh(cwd: str, endpoint: str, jq: str) -> str | None:
    """Return the output of a `gh api` GET in the directory, or None when it fails."""
    try:
        ran = subprocess.run(
            ["gh", "api", "-X", "GET", endpoint, "--jq", jq],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=cwd,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return ran.stdout.strip() if ran.returncode == 0 else None


class OpenReviewsSpec:
    """Extension point for commands that open reviews."""

    @hookspec
    def open_reviews(self, command: ParsedCommand, cwd: str) -> tuple[str, int] | None:
        """Return the scope key and the user's live open review count where the command opens a review, else None."""
        raise NotImplementedError


class ReviewLimitGuard(HooksPlugin):
    """Blocks a new review while the user's open reviews in its scope reach the limit under `[reviews]` in config.toml."""

    hookspecs = OpenReviewsSpec

    @hookimpl
    def open_reviews(self, command: ParsedCommand, cwd: str) -> tuple[str, int] | None:
        """Return the cwd's GitHub repo and the user's open PRs in it, for `gh pr create`."""
        if not (
            command.name == "gh"
            and "pr" in command.args
            and command.args[command.args.index("pr") + 1 :][:1] == ["create"]
        ):
            return None
        repo = _gh(cwd, "repos/{owner}/{repo}", ".full_name")
        count = repo and _gh(
            cwd, f"search/issues?q=is:pr+is:open+author:@me+repo:{repo}", ".total_count"
        )
        return (repo, int(count)) if repo and count and count.isdigit() else None

    def on_hook(
        self, hook_name: str, *, logger: logging.Logger, **kwargs: object
    ) -> HookResult | None:
        """Return a block for a new review at the limit on PreShell."""
        if not guards_active() or hook_name != PluginScope.PRE_SHELL:
            return None
        try:
            commands = extract_commands(
                bashlex.parse(cast("str", kwargs.get("command") or ""))
            )
        except (bashlex.errors.ParsingError, NotImplementedError):
            return None
        roots = cast("list[str]", kwargs.get("workspace_roots") or [])
        for index, cmd in enumerate(commands):
            cwd = effective_cwd(commands, index, roots[0] if roots else os.getcwd())
            for scope, count in collect_contributions(
                OpenReviewsSpec.open_reviews, tuple, command=cmd, cwd=cwd
            ):
                try:
                    reviews = read_config().get("reviews", {})
                    limit = int(
                        reviews.get("repos", {}).get(
                            scope, reviews.get("max_in_flight", DEFAULT_LIMIT)
                        )
                    )
                except (
                    AttributeError,
                    TypeError,
                    ValueError,
                    OSError,
                    tomllib.TOMLDecodeError,
                ):
                    limit = DEFAULT_LIMIT
                if count >= limit:
                    return HookResult(
                        block=(
                            f"{count} of your reviews in {scope} are open, at the limit of {limit}."
                            " MUST NOT open a new review until some merge or close. Updating an open review is allowed."
                            " Only the user raises the limit, with `max_in_flight` under"
                            f' `[reviews]`, or `"{scope}"` under `[reviews.repos]`, in llm-prompts\' config.toml.'
                        )
                    )
        return None
