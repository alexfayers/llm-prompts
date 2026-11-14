"""Tests for the watch gh-pr source."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeSubprocess

from llm_prompts.watch.core.runner import watch
from llm_prompts.watch.core.store import Persisted
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


def test_gh_pr_a_later_watch_reuses_the_etags_an_earlier_one_stored(
    github: FakeGithub,
) -> None:
    github.pr()
    watch([GithubPrSource("o/r", 7, None)], ["state=OPEN"], interval=0, timeout=5)
    github.requests.clear()

    watch([GithubPrSource("o/r", 7, None)], ["state=OPEN"], interval=0, timeout=5)

    assert all(
        any(a.startswith("If-None-Match: ") for a in argv) for argv in github.requests
    )


def test_gh_pr_watch_goes_on_when_the_cache_cannot_be_written(
    github: FakeGithub, isolated_home: Path
) -> None:
    github.pr()
    (isolated_home / ".cache").write_text("")

    assert (
        watch([GithubPrSource("o/r", 7, None)], ["state=OPEN"], interval=0, timeout=5)
        == 0
    )


@pytest.mark.parametrize("stored", ["[]", '{"repos/o/r/pulls/7": null}'])
def test_gh_pr_watch_ignores_stored_state_of_the_wrong_shape(
    github: FakeGithub, isolated_home: Path, stored: str
) -> None:
    github.pr()
    watch([GithubPrSource("o/r", 7, None)], ["state=OPEN"], interval=0, timeout=5)
    for file in (isolated_home / ".cache" / "llm-prompts" / "watch").glob("*.json"):
        file.write_text(stored)

    assert (
        watch([GithubPrSource("o/r", 7, None)], ["state=OPEN"], interval=0, timeout=5)
        == 0
    )


def test_gh_pr_cache_file_is_private_to_the_user(
    github: FakeGithub, isolated_home: Path
) -> None:
    github.pr()

    watch([GithubPrSource("o/r", 7, None)], ["state=OPEN"], interval=0, timeout=5)

    (cache,) = (isolated_home / ".cache" / "llm-prompts" / "watch").glob("*.json")
    assert cache.stat().st_mode & 0o777 == 0o600


def test_gh_pr_loose_cache_file_is_made_private(
    github: FakeGithub, isolated_home: Path
) -> None:
    github.pr()
    watch([GithubPrSource("o/r", 7, None)], ["state=OPEN"], interval=0, timeout=5)
    (cache,) = (isolated_home / ".cache" / "llm-prompts" / "watch").glob("*.json")
    cache.chmod(0o644)

    Persisted(GithubPrSource("o/r", 7, None))

    assert cache.stat().st_mode & 0o777 == 0o600


def test_gh_pr_cache_write_is_retried_after_a_failure(
    github: FakeGithub, isolated_home: Path
) -> None:
    github.pr()
    (isolated_home / ".cache").write_text("")
    source = Persisted(GithubPrSource("o/r", 7, None))
    source.poll()
    (isolated_home / ".cache").unlink()

    source.poll()

    assert list((isolated_home / ".cache" / "llm-prompts" / "watch").glob("*.json"))


def test_gh_pr_failed_cache_replace_leaves_no_temporary_file_and_is_retried(
    github: FakeGithub, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github.pr()
    source = Persisted(GithubPrSource("o/r", 7, None))
    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", _fail_replace)
        source.poll()
    directory = isolated_home / ".cache" / "llm-prompts" / "watch"
    assert list(directory.iterdir()) == []

    source.poll()

    assert len(list(directory.glob("*.json"))) == 1


def _fail_replace(self: Path, target: Path) -> Path:
    raise OSError("replace failed")
