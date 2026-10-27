"""Fixed reason codes for commands that exit early."""

from __future__ import annotations

from typing import Literal, get_args

Reason = Literal[
    "no_contribute_targets",
    "tool_not_configured",
    "tool_not_local",
    "no_prompts_dir",
    "gh_login_failed",
    "no_github_token",
    "no_github_remote",
    "no_push_access",
    "other",
]
REASONS: tuple[str, ...] = get_args(Reason)


class ExitReason(SystemExit):
    """A non-zero exit that names why the command stopped."""

    def __init__(self, reason: Reason, message: str | None = None) -> None:
        """Exit 1, or with `message` printed to stderr when given.

        Args:
            reason: The fixed code telemetry reports.
            message: Optional text shown to the user, never sent.
        """
        super().__init__(message or 1)
        self.reason = reason
