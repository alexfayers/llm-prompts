"""Read the pull request number off a squash-merge subject."""

from __future__ import annotations

import re

SQUASH_SUFFIX = re.compile(r" \(#(\d+)\)$")


def squash_pr_number(subject: str) -> int | None:
    """Return the PR number a squash-merge subject ends with, if any."""
    match = SQUASH_SUFFIX.search(subject)
    return int(match[1]) if match else None
