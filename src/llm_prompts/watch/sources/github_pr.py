"""Watch a GitHub pull request through conditional REST requests."""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Self

from ..core.source import Fields, WatchError
from .rest import conditional_get

FAILED_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "action_required", "startup_failure"}
)
ADVISORY_CHECK = "automate / rebase-queue"
ADVISORY_WORKFLOW = ".github/workflows/project-automation.yml"
PAGE = "?per_page=100"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _job(run: dict[str, Any]) -> tuple[object, ...] | None:
    """A check's identity across reruns, or None where GitHub gave no stable one."""
    attempt_key: tuple[object, ...] | None = run.get("attempt_key")
    if attempt_key:
        return attempt_key
    suite = (run.get("check_suite") or {}).get("id")
    external_id = run.get("external_id")
    return (run["name"], suite, external_id) if suite and external_id else None


def _order(run: dict[str, Any]) -> tuple[int, int]:
    return run.get("run_attempt", 0), run["id"]


def _current(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each job's latest run, plus its earlier cancelled runs unless the latest succeeded."""
    latest: dict[tuple[object, ...], dict[str, Any]] = {}
    for run in runs:
        job = _job(run)
        if job and (job not in latest or _order(run) > _order(latest[job])):
            latest[job] = run
    return [
        run
        for run in runs
        if (job := _job(run)) is None
        or run is latest[job]
        or (run["conclusion"] == "cancelled" and latest[job]["conclusion"] != "success")
    ]


def _ci(runs: list[dict[str, Any]], status: dict[str, Any]) -> str:
    state = status["state"] if status["total_count"] else None
    current = _current(runs)
    if state in {"failure", "error"} or any(
        run["conclusion"] in FAILED_CONCLUSIONS for run in current
    ):
        return "fail"
    if (state == "pending" and not runs) or any(
        run["status"] != "completed" or run["conclusion"] == "cancelled"
        for run in current
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
    """Lists the open pull requests an author has in each repo, and those closed since the last call, through conditional REST requests."""

    def __init__(self, author: str, repos: Sequence[str], head: str | None) -> None:
        """List pull requests by author (``@me`` is the signed-in user) in repos."""
        self._author = author
        self._repos = repos
        self._head = head
        self._since = _now()
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
        """Return a source for each open pull request found now and each one closed since the last call."""
        author = (
            self._get("user")[0]["login"] if self._author == "@me" else self._author
        )
        since, self._since = self._since, _now()
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
            # shortcut: only the 100 most recently updated closed PRs are read, page on if a poll gap can close more.
            closed, _ = self._get(
                f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100"
            )
            found += [
                GithubPrSource(repo, pull["number"], self._head)
                for pull in closed
                if pull["user"]["login"].lower() == author.lower()
                and pull["closed_at"] >= since
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
        "conflicts": ["conflicts=true"],
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

    def _is_advisory(self, run: dict[str, Any]) -> bool:
        """Whether run is the rebase-queue job of the project automation workflow."""
        workflow_run = re.search(r"/actions/runs/(\d+)/", run.get("details_url") or "")
        if run["name"] != ADVISORY_CHECK or not workflow_run:
            return False
        try:
            data, _ = self._get(f"repos/{self._repo}/actions/runs/{workflow_run[1]}")
        except WatchError:
            return False
        return str(data.get("path", "")).split("@")[0] == ADVISORY_WORKFLOW

    def _with_attempt(self, run: dict[str, Any]) -> dict[str, Any]:
        """Tag run with its workflow run and attempt when each attempt has one job of its name."""
        ids = re.search(r"/actions/runs/(\d+)/job/(\d+)", run.get("details_url") or "")
        if not ids:
            return run
        try:
            jobs = self._get_all(
                f"repos/{self._repo}/actions/runs/{ids[1]}/jobs?filter=all&per_page=100",
                "jobs",
            )
        except WatchError:
            return run
        named = [job for job in jobs if job.get("name") == run["name"]]
        this = [job for job in named if str(job.get("id")) == ids[2]]
        attempts = [job.get("run_attempt") for job in named]
        if (
            len(this) != 1
            or len(attempts) != len(set(attempts))
            or not all(type(attempt) is int and attempt > 0 for attempt in attempts)
        ):
            return run
        return {
            **run,
            "attempt_key": (run["name"], ids[1]),
            "run_attempt": this[0]["run_attempt"],
        }

    def _with_attempts(self, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Tag the runs that share their check name, the only ones a rerun can replace."""
        names = [run["name"] for run in runs]
        return [
            self._with_attempt(run) if names.count(run["name"]) > 1 else run
            for run in runs
        ]

    def poll(self) -> Fields:
        """Return the pull request's current fields."""
        pulls = f"repos/{self._repo}/pulls/{self._number}"
        pull, _ = self._get(pulls)
        sha = pull["head"]["sha"]
        reviews = self._get_all(f"{pulls}/reviews{PAGE}")
        if self._head and not sha.startswith(self._head):
            ci = "pending"
        else:
            runs = self._with_attempts(
                [
                    run
                    for run in self._get_all(
                        f"repos/{self._repo}/commits/{sha}/check-runs?filter=all&per_page=100",
                        "check_runs",
                    )
                    if not self._is_advisory(run)
                ]
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
            "labels": ",".join(sorted(label["name"] for label in pull["labels"])),
            "conflicts": str(pull.get("mergeable") is False).lower(),
        }
