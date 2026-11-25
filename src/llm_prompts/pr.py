"""`llm-prompts pr`: take a pull request through size, main sync and ready."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import size_guard
from .contribute import checkouts, first_stderr_line, run_ready, run_update
from .network import run_with_retries


def _gh(repo: Path, *args: str) -> str:
    """Run a ``gh`` command in ``repo`` and return its stdout."""
    return run_with_retries(
        ["gh", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def run_pr(repo: Path, prefix: str, number: int) -> int:
    """Check the size of PR ``number``'s prompts, rebase it onto main and mark it ready, stopping at the first failing step."""
    try:
        view = json.loads(
            _gh(
                repo,
                "pr",
                "view",
                str(number),
                "--json",
                "state,headRefName",
            )
        )
        if view["state"] != "OPEN":
            print(f"#{number} is {view['state'].lower()}")
            return 1
        checkout = next(
            (c for c in checkouts(repo) if c.branch == view["headRefName"]), None
        )
        if checkout is None:
            print(
                f"#{number}: {view['headRefName']} is not checked out in a worktree of {repo}"
            )
            return 1
        result = size_guard.check([checkout.path / prefix])
        print(result.report)
        if not result.passed:
            return 1
        if run_update(repo, True, (number,)):
            return 1
    except subprocess.CalledProcessError as error:
        print(f"gh failed: {first_stderr_line(error)}", file=sys.stderr)
        return 1
    return run_ready(repo, number)
