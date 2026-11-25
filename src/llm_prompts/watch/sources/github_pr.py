"""Watch a GitHub pull request through conditional REST requests."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Self

from ..core.source import Fields, WatchError
from .rest import conditional_get

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


class GithubPrDiscovery:
    """Lists the open pull requests an author has in each repo, through conditional REST requests."""

    def __init__(self, author: str, repos: Sequence[str], head: str | None) -> None:
        """List pull requests by author (``@me`` is the signed-in user) in repos."""
        self._author = author
        self._repos = repos
        self._head = head
        self._cache: dict[str, tuple[str, Any, str | None]] = {}

    def _get(self, path: str) -> tuple[Any, str | None]:
        cached = self._cache.get(path)
        response = conditional_get(path, cached[0] if cached else None)
        if response.code == 304 and cached:
            return cached[1], cached[2]
        if response.code != 200:
            raise WatchError(f"GitHub request failed for {path}.")
        link = re.search(r'<([^>]+)>;\s*rel="next"', response.headers.get("link", ""))
        data = json.loads(response.body)
        self._cache[path] = (response.headers["etag"], data, link[1] if link else None)
        return data, self._cache[path][2]

    def __call__(self) -> list[GithubPrSource]:
        """Return a source for each open pull request found now."""
        author = (
            self._get("user")[0]["login"] if self._author == "@me" else self._author
        )
        found = []
        for repo in self._repos:
            next_path: str | None = f"repos/{repo}/pulls?state=open&per_page=100"
            while next_path:
                pulls, next_path = self._get(next_path)
                found += [
                    GithubPrSource(repo, pull["number"], self._head)
                    for pull in pulls
                    if pull["user"]["login"].lower() == author.lower()
                ]
        return found


class GithubPrSource:
    """Reports a pull request's state, reviews, head commit and check results."""

    name: ClassVar[str] = "gh-pr"
    default_interval: ClassVar[float] = 30.0
    aliases: ClassVar[Mapping[str, Sequence[str]]] = {
        "merged": ["merged=true"],
        "ci": ["ci=pass", "ci=fail"],
        "update": ["changed:reviews"],
    }
    terminal: ClassVar[Sequence[str]] = ["merged=true", "state=CLOSED"]

    def __init__(self, repo: str, number: int, head: str | None) -> None:
        """Watch pull request number in repo, reporting ``ci=pending`` until head is the PR's head."""
        self._repo = repo
        self._number = number
        self._head = head
        self._cache: dict[str, tuple[str, Any, str | None]] = {}
        self._used: set[str] = set()

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Add the target and head arguments."""
        parser.add_argument(
            "target",
            nargs="*",
            type=_parse_target,
            help="PR numbers, owner/repo#number or PR URLs. Any match stops the watch.",
        )
        parser.add_argument(
            "--author",
            help="With --repo and --follow, also watch every open PR this user (or @me) has, picking up new ones.",
        )
        parser.add_argument(
            "--repo",
            action="append",
            default=[],
            help="owner/repo to list --author's PRs in. Repeat for several.",
        )
        parser.add_argument(
            "--head",
            help="Report ci=pending until the PR's head commit starts with this.",
        )

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> list[Self]:
        """Build one source per target from parsed arguments."""
        if args.author and not (args.repo and args.follow):
            raise SystemExit("watch: --author needs --repo and --follow.")
        if not args.target and not args.author:
            raise SystemExit("watch: give a PR target or --author.")
        return [cls(repo, number, args.head) for repo, number in args.target]

    @classmethod
    def discoverer(cls, args: argparse.Namespace) -> GithubPrDiscovery | None:
        """Return the lister of --author's open PRs, or None without --author."""
        return (
            GithubPrDiscovery(args.author, args.repo, args.head)
            if args.author
            else None
        )

    def describe(self) -> str:
        """Return the short label printed with the result."""
        return f"gh-pr {self._repo}#{self._number}"

    @property
    def state_key(self) -> str:
        """Return the key its cached responses are stored under."""
        return f"{self._repo}#{self._number}"

    def load_state(self, state: Mapping[str, Any]) -> None:
        """Restore the cached responses a previous run stored."""
        self._cache = {
            path: (etag, data, link) for path, (etag, data, link) in state.items()
        }

    def dump_state(self) -> dict[str, Any]:
        """Return the cached responses this run used."""
        return {path: self._cache[path] for path in self._used if path in self._cache}

    def _get(self, path: str) -> tuple[Any, str | None]:
        self._used.add(path)
        cached = self._cache.get(path)
        response = conditional_get(path, cached[0] if cached else None)
        if response.code == 304 and cached:
            return cached[1], cached[2]
        if response.code != 200:
            raise WatchError(f"GitHub request failed for {self.describe()}.")
        data = json.loads(response.body)
        link = re.search(r'<([^>]+)>;\s*rel="next"', response.headers.get("link", ""))
        following = link[1] if link else None
        self._cache[path] = (response.headers["etag"], data, following)
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
