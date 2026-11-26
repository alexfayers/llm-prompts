"""Cline-hooks plugin that blocks a new review while too many of the user's reviews in its scope are open."""

from __future__ import annotations

import itertools
import os
import subprocess
from typing import TYPE_CHECKING, cast

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


def _gh(cwd: str, endpoint: str, jq: str, host: str = "") -> str | None:
    """Return the output of a paginated `gh api` GET in the directory, or None when it fails."""
    try:
        ran = subprocess.run(
            ["gh", "api", "-X", "GET", endpoint, "--jq", jq, "--paginate"]
            + (["--hostname", host] if host else []),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=cwd,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return ran.stdout.strip() if ran.returncode == 0 else None


def open_pr_count(cwd: str, repo: str) -> int | None:
    """Return the user's open PRs in ``repo`` (``[host/]owner/name``), or None when gh cannot tell."""
    host, _, owner_repo = (
        repo.partition("/") if repo.count("/") == 2 else ("", "", repo)
    )
    login = _gh(cwd, "user", ".login", host)
    authors = login and _gh(
        cwd,
        f"repos/{owner_repo}/pulls?state=open&per_page=100",
        ".[].user.login",
        host,
    )
    return authors.split().count(login) if login and authors is not None else None


def limit_block(scope: str, count: int, brief: bool = False) -> str | None:
    """Return why a new review in ``scope`` is refused when ``count`` reviews are open, or None under the limit.

    ``brief`` gives a one-line form for CLI output instead of the agent-facing text.
    """
    try:
        reviews = read_config().get("reviews", {})
        repos = {key.lower(): value for key, value in reviews.get("repos", {}).items()}
        limit = int(
            repos.get(scope.lower(), reviews.get("max_in_flight", DEFAULT_LIMIT))
        )
    except (AttributeError, TypeError, ValueError, OSError):
        limit = DEFAULT_LIMIT
    if count < limit:
        return None
    state = f"{count} of your reviews in {scope} are open, at the limit of {limit}"
    if brief:
        return f"{state} (`max_in_flight` under `[reviews]`)"
    return (
        f"{state}."
        " MUST NOT open a new review until some merge or close. Updating an open review is allowed."
        " Only the user raises the limit, with `max_in_flight` under"
        f' `[reviews]`, or `"{scope}"` under `[reviews.repos]`, in llm-prompts\' config.toml.'
        " The limit is best effort, so parallel creates can go over it by a few."
    )


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
        """Return the `--repo` or cwd GitHub repo and the user's open PRs in it, for `gh pr create`."""
        if not (
            command.name == "gh"
            and "pr" in command.args
            and command.args[command.args.index("pr") + 1 :][:1] == ["create"]
        ):
            return None
        words = command.words
        named = [
            value
            for word, value in itertools.pairwise(words)
            if word in {"-R", "--repo"}
        ] + [
            word.removeprefix("--repo=") for word in words if word.startswith("--repo=")
        ]
        repo = named[0] if named else _gh(cwd, "repos/{owner}/{repo}", ".full_name")
        count = open_pr_count(cwd, repo) if repo else None
        return (repo, count) if repo and count is not None else None

    def on_hook(
        self, hook_name: str, *, logger: logging.Logger, **kwargs: object
    ) -> HookResult | None:
        """Return a block for a new review at the limit on PreShell."""
        if not guards_active() or hook_name != PluginScope.PRE_SHELL:
            return None
        import bashlex  # type: ignore[import-untyped]
        import bashlex.errors  # type: ignore[import-untyped]

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
                block = limit_block(scope, count)
                if block:
                    return HookResult(block=block)
        return None
