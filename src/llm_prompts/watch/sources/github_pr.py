"""Watch a GitHub pull request through conditional REST requests."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Self

from ...network import run_with_retries
from ..core.source import Fields, WatchError

FAILED_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}
)
PAGE = "?per_page=100"


def _ci(runs: list[dict[str, Any]], status: dict[str, Any]) -> str:
    state = status["state"] if status["total_count"] else None
    if state in {"failure", "error"} or any(
        run["conclusion"] in FAILED_CONCLUSIONS for run in runs
    ):
        return "fail"
    if (state == "pending" and not runs) or any(
        run["status"] != "completed" for run in runs
    ):
        return "pending"
    return "pass" if runs or state else "none"


def _approved(reviews: list[dict[str, Any]]) -> bool:
    latest = {
        review["user"]["login"]: review["state"]
        for review in reviews
        if review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
    }
    states = set(latest.values())
    return "APPROVED" in states and "CHANGES_REQUESTED" not in states


def _parse_target(text: str) -> tuple[str, int]:
    match = re.fullmatch(
        r"(?:https://github\.com/)?(?:([\w.-]+/[\w.-]+)(?:#|/pull/))?(\d+)", text
    )
    if not match:
        raise argparse.ArgumentTypeError(f"invalid PR target '{text}'")
    return match.group(1) or "{owner}/{repo}", int(match.group(2))


class GithubPrSource:
    """Reports a pull request's state, reviews, head commit and check results."""

    name: ClassVar[str] = "gh-pr"
    default_interval: ClassVar[float] = 30.0
    aliases: ClassVar[Mapping[str, Sequence[str]]] = {
        "merged": ["merged=true"],
        "ci": ["ci=pass", "ci=fail"],
        "update": ["changed:reviews"],
    }

    def __init__(self, repo: str, number: int, head: str | None) -> None:
        """Watch pull request number in repo, reporting ``ci=pending`` until head is the PR's head."""
        self._repo = repo
        self._number = number
        self._head = head
        self._cache: dict[str, tuple[str, Any, str | None]] = {}

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Add the target and head arguments."""
        parser.add_argument(
            "target",
            type=_parse_target,
            help="PR number, owner/repo#number or PR URL.",
        )
        parser.add_argument(
            "--head",
            help="Report ci=pending until the PR's head commit starts with this.",
        )

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Self:
        """Build the source from parsed arguments."""
        repo, number = args.target
        return cls(repo, number, args.head)

    def describe(self) -> str:
        """Return the short label printed with the result."""
        return f"gh-pr {self._number}"

    def _get(self, path: str) -> tuple[Any, str | None]:
        cached = self._cache.get(path)
        conditional = ["-H", f"If-None-Match: {cached[0]}"] if cached else []
        try:
            result = run_with_retries(
                ["gh", "api", "-i", path, *conditional],
                capture_output=True,
                text=True,
            )
        except OSError:
            raise WatchError("gh is not installed.") from None
        head, _, body = result.stdout.partition("\n\n")
        status_line, *header_lines = head.splitlines() or [""]
        status = re.match(r"HTTP/\S+ (\d+)", status_line)
        code = int(status[1]) if status else 0
        headers = {
            name.lower(): value.strip()
            for name, _, value in (line.partition(":") for line in header_lines)
        }
        if code == 304 and cached:
            return cached[1], cached[2]
        if code != 200:
            raise WatchError(f"GitHub request failed for {self.describe()}.")
        data = json.loads(body)
        link = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("link", ""))
        following = link[1] if link else None
        self._cache[path] = (headers["etag"], data, following)
        return data, following

    def _get_all(self, path: str, key: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_path: str | None = path
        while next_path:
            data, next_path = self._get(next_path)
            items += data[key] if key else data
        return items

    def poll(self) -> Fields:
        """Return the pull request's current fields."""
        pulls = f"repos/{self._repo}/pulls/{self._number}"
        pull, _ = self._get(pulls)
        sha = pull["head"]["sha"]
        reviews = self._get_all(f"{pulls}/reviews{PAGE}")
        if self._head and not sha.startswith(self._head):
            ci = "pending"
        else:
            runs = self._get_all(
                f"repos/{self._repo}/commits/{sha}/check-runs{PAGE}", "check_runs"
            )
            status, _ = self._get(f"repos/{self._repo}/commits/{sha}/status")
            ci = _ci(runs, status)
        return {
            "state": pull["state"].upper(),
            "merged": str(pull["merged"]).lower(),
            "head": sha,
            "approved": str(_approved(reviews)).lower(),
            "reviews": ",".join(sorted(f"{r['id']}:{r['state']}" for r in reviews)),
            "ci": ci,
        }
