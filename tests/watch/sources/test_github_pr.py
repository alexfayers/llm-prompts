"""Tests for the watch gh-pr source."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest
from conftest import FakeSubprocess

from llm_prompts.watch.sources.github_pr import GithubPrSource


class FakeGithub:
    """Serves ``gh api -i`` reads by path, answering a matching ETag with a 304."""

    def __init__(self, fake_subprocess: FakeSubprocess) -> None:
        self.bodies: dict[str, object] = {}
        self.next_pages: dict[str, str] = {}
        self.requests: list[list[str]] = []
        fake_subprocess.on_match(
            lambda argv: argv[:3] == ["gh", "api", "-i"],
            side_effect=self._respond,
        )

    def _respond(
        self, argv: list[str], kwargs: dict[str, Any]
    ) -> subprocess.CompletedProcess[str]:
        self.requests.append(argv)
        path = argv[3]
        etag = f'"{hash(json.dumps(self.bodies[path], sort_keys=True))}"'
        headers = f"Etag: {etag}\n"
        if f"If-None-Match: {etag}" in argv:
            return subprocess.CompletedProcess(
                argv, 1, f"HTTP/2.0 304 Not Modified\n{headers}\n", "gh: HTTP 304"
            )
        if path in self.next_pages:
            headers += f'Link: <{self.next_pages[path]}>; rel="next"\n'
        body = json.dumps(self.bodies[path])
        return subprocess.CompletedProcess(
            argv, 0, f"HTTP/2.0 200 OK\n{headers}\n{body}", ""
        )

    def pr(self, runs: list[dict[str, str | None]] | None = None) -> None:
        self.bodies["repos/o/r/pulls/7"] = {
            "state": "open",
            "merged": False,
            "head": {"sha": "abc123"},
        }
        self.bodies["repos/o/r/pulls/7/reviews?per_page=100"] = []
        self.bodies["repos/o/r/commits/abc123/check-runs?per_page=100"] = {
            "check_runs": runs or []
        }
        self.bodies["repos/o/r/commits/abc123/status"] = {
            "state": "pending",
            "total_count": 0,
        }


@pytest.fixture
def github(fake_subprocess: FakeSubprocess) -> FakeGithub:
    return FakeGithub(fake_subprocess)


@pytest.mark.parametrize(("head", "ci"), [(None, "fail"), ("def456", "pending")])
def test_gh_pr_ci_fails_over_pending_until_the_head_matches(
    github: FakeGithub, head: str | None, ci: str
) -> None:
    github.pr(
        [
            {"status": "completed", "conclusion": "failure"},
            {"status": "in_progress", "conclusion": None},
        ]
    )

    assert GithubPrSource("o/r", 7, head).poll()["ci"] == ci


def test_gh_pr_ci_fails_when_a_commit_status_fails(github: FakeGithub) -> None:
    github.pr([{"status": "completed", "conclusion": "success"}])
    github.bodies["repos/o/r/commits/abc123/status"] = {
        "state": "failure",
        "total_count": 1,
    }

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "fail"


def test_gh_pr_ci_ignores_a_pending_commit_status_when_runs_passed(
    github: FakeGithub,
) -> None:
    github.pr([{"status": "completed", "conclusion": "success"}])
    github.bodies["repos/o/r/commits/abc123/status"] = {
        "state": "pending",
        "total_count": 1,
    }

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "pass"


def test_gh_pr_ci_fails_on_a_failed_run_on_a_later_page(github: FakeGithub) -> None:
    github.pr([{"status": "completed", "conclusion": "success"}])
    first = "repos/o/r/commits/abc123/check-runs?per_page=100"
    second = "https://api.github.com/repositories/1/commits/abc123/check-runs?page=2"
    github.next_pages[first] = second
    github.bodies[second] = {
        "check_runs": [{"status": "completed", "conclusion": "failure"}]
    }
    source = GithubPrSource("o/r", 7, None)

    assert source.poll()["ci"] == "fail"
    assert source.poll()["ci"] == "fail"


def test_gh_pr_sends_etags_reuses_fields_on_not_modified_and_sees_dismissals(
    github: FakeGithub,
) -> None:
    github.pr()
    reviews = "repos/o/r/pulls/7/reviews?per_page=100"
    github.bodies[reviews] = [{"id": 1, "user": {"login": "a"}, "state": "APPROVED"}]
    source = GithubPrSource("o/r", 7, None)
    first = source.poll()
    github.requests.clear()

    assert source.poll() == first
    assert all(
        any(a.startswith("If-None-Match: ") for a in argv) for argv in github.requests
    )

    github.bodies[reviews] = [{"id": 1, "user": {"login": "a"}, "state": "DISMISSED"}]

    assert source.poll()["reviews"] != first["reviews"]
