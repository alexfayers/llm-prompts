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
from llm_prompts.watch.sources.github_pr import GithubPrDiscovery, GithubPrSource


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
        if path not in self.bodies:
            return subprocess.CompletedProcess(
                argv, 1, "HTTP/2.0 404 Not Found\n\n", "gh: HTTP 404"
            )
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

    def pr(self, runs: list[dict[str, Any]] | None = None) -> None:
        self.bodies["repos/o/r/pulls/7"] = {
            "state": "open",
            "merged": False,
            "head": {"sha": "abc123"},
        }
        self.bodies["repos/o/r/pulls/7/reviews?per_page=100"] = []
        self.bodies["repos/o/r/commits/abc123/check-runs?filter=all&per_page=100"] = {
            "check_runs": [
                {
                    "id": i,
                    "name": f"check-{i}",
                    "check_suite": {"id": 1},
                    "external_id": run.get("name", f"check-{i}"),
                    **run,
                }
                for i, run in enumerate(runs or [])
            ]
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


def advisory_pr(github: FakeGithub, workflow_path: str) -> None:
    github.pr(
        [
            {
                "name": "automate / rebase-queue",
                "details_url": "https://github.com/o/r/actions/runs/5/job/6",
                "status": "completed",
                "conclusion": "cancelled",
            },
            {"name": "test", "status": "completed", "conclusion": "success"},
        ]
    )
    github.bodies["repos/o/r/actions/runs/5"] = {"path": workflow_path}


def test_gh_pr_ci_ignores_the_cancelled_rebase_queue_job(github: FakeGithub) -> None:
    advisory_pr(github, ".github/workflows/project-automation.yml")

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "pass"


def test_gh_pr_ci_keeps_a_cancelled_job_of_the_same_name_from_another_workflow(
    github: FakeGithub,
) -> None:
    advisory_pr(github, ".github/workflows/ci.yml")

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "pending"


@pytest.mark.parametrize(
    "identity",
    [{"check_suite": {"id": None}}, {"external_id": None}, {"check_suite": None}],
)
def test_gh_pr_ci_aggregates_a_run_without_a_stable_identity(
    github: FakeGithub, identity: dict[str, Any]
) -> None:
    github.pr(
        [
            {
                "id": 1,
                "name": "test",
                "status": "completed",
                "conclusion": "cancelled",
                **identity,
            },
            {
                "id": 2,
                "name": "test",
                "status": "completed",
                "conclusion": "success",
                **identity,
            },
        ]
    )

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "pending"


@pytest.mark.parametrize("details_url", [None, "https://example.test/job/6"])
def test_gh_pr_ci_aggregates_a_rebase_queue_job_it_cannot_trace_to_a_workflow(
    github: FakeGithub, details_url: str | None
) -> None:
    github.pr(
        [
            {
                "name": "automate / rebase-queue",
                "details_url": details_url,
                "status": "completed",
                "conclusion": "cancelled",
            }
        ]
    )

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "pending"


def test_gh_pr_ci_aggregates_a_rebase_queue_job_when_the_workflow_lookup_fails(
    github: FakeGithub,
) -> None:
    advisory_pr(github, ".github/workflows/project-automation.yml")
    del github.bodies["repos/o/r/actions/runs/5"]

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "pending"


@pytest.mark.parametrize(
    ("first", "second", "ci"),
    [("success", "failure", "fail"), ("cancelled", "success", "pending")],
)
def test_gh_pr_ci_does_not_let_a_job_hide_another_job_with_the_same_name(
    github: FakeGithub, first: str, second: str, ci: str
) -> None:
    github.pr(
        [
            {
                "id": 1,
                "name": "test",
                "external_id": "a",
                "status": "completed",
                "conclusion": first,
            },
            {
                "id": 2,
                "name": "test",
                "external_id": "b",
                "status": "completed",
                "conclusion": second,
            },
        ]
    )

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == ci


def rerun_pr(
    github: FakeGithub, job_attempts: list[tuple[int, int | str | None]]
) -> None:
    """A failed then a successful run of job `test`, whose jobs are (id, run_attempt)."""
    github.pr(
        [
            {
                "id": 6,
                "name": "test",
                "external_id": "first",
                "details_url": "https://github.com/o/r/actions/runs/5/job/6",
                "status": "completed",
                "conclusion": "failure",
            },
            {
                "id": 7,
                "name": "test",
                "external_id": "second",
                "details_url": "https://github.com/o/r/actions/runs/5/job/7",
                "status": "completed",
                "conclusion": "success",
            },
        ]
    )
    github.bodies["repos/o/r/actions/runs/5/jobs?filter=all&per_page=100"] = {
        "jobs": [
            {"id": job, "name": "test"}
            | ({} if attempt == "missing" else {"run_attempt": attempt})
            for job, attempt in job_attempts
        ]
    }


def test_gh_pr_ci_matches_a_rerun_attempt_whose_external_id_changed(
    github: FakeGithub,
) -> None:
    rerun_pr(github, [(6, 1), (7, 2)])

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "pass"


def test_gh_pr_ci_does_not_match_attempts_when_two_jobs_share_a_name(
    github: FakeGithub,
) -> None:
    rerun_pr(github, [(6, 1), (7, 2), (8, 2)])

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "fail"


@pytest.mark.parametrize("attempt", ["missing", None, 0, "2"])
def test_gh_pr_ci_does_not_match_attempts_when_one_has_no_valid_attempt_number(
    github: FakeGithub, attempt: int | str | None
) -> None:
    rerun_pr(github, [(6, 1), (7, attempt), (8, "missing")])

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "fail"


def test_gh_pr_ci_does_not_match_attempts_when_the_jobs_lookup_fails(
    github: FakeGithub,
) -> None:
    rerun_pr(github, [(6, 1), (7, 2)])
    del github.bodies["repos/o/r/actions/runs/5/jobs?filter=all&per_page=100"]

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "fail"


def test_gh_pr_lists_every_check_run_attempt(github: FakeGithub) -> None:
    github.pr()

    GithubPrSource("o/r", 7, None).poll()

    assert "repos/o/r/commits/abc123/check-runs?filter=all&per_page=100" in {
        argv[3] for argv in github.requests
    }


def test_gh_pr_ci_passes_when_a_failed_run_was_rerun_successfully(
    github: FakeGithub,
) -> None:
    github.pr(
        [
            {"id": 1, "name": "test", "status": "completed", "conclusion": "failure"},
            {"id": 2, "name": "test", "status": "completed", "conclusion": "success"},
        ]
    )

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "pass"


RERUN_CONCLUSIONS = [("success", "pass"), ("skipped", "pending"), ("failure", "fail")]


@pytest.mark.parametrize(("rerun", "ci"), RERUN_CONCLUSIONS)
def test_gh_pr_ci_keeps_a_cancelled_run_until_its_rerun_succeeds(
    github: FakeGithub, rerun: str, ci: str
) -> None:
    github.pr(
        [
            {"id": 1, "name": "test", "status": "completed", "conclusion": "cancelled"},
            {"id": 2, "name": "test", "status": "completed", "conclusion": rerun},
        ]
    )

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == ci


@pytest.mark.parametrize(
    ("name", "suite"), [("test", 2), ("lint", 1)], ids=["workflow", "name"]
)
def test_gh_pr_ci_keeps_a_cancelled_run_when_another_check_succeeds(
    github: FakeGithub, name: str, suite: int
) -> None:
    github.pr(
        [
            {"id": 1, "name": "test", "status": "completed", "conclusion": "cancelled"},
            {
                "id": 2,
                "name": name,
                "check_suite": {"id": suite},
                "status": "completed",
                "conclusion": "success",
            },
        ]
    )

    assert GithubPrSource("o/r", 7, None).poll()["ci"] == "pending"


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
    first = "repos/o/r/commits/abc123/check-runs?filter=all&per_page=100"
    second = "https://api.github.com/repositories/1/commits/abc123/check-runs?page=2"
    github.next_pages[first] = second
    github.bodies[second] = {
        "check_runs": [
            {
                "id": 9,
                "name": "late",
                "check_suite": {"id": 1},
                "status": "completed",
                "conclusion": "failure",
            }
        ]
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


@pytest.mark.parametrize("merged", [True, False])
def test_gh_pr_follow_exits_on_a_merged_or_closed_pr(
    github: FakeGithub, capsys: pytest.CaptureFixture[str], merged: bool
) -> None:
    github.pr()
    github.bodies["repos/o/r/pulls/7"] = {
        "state": "closed",
        "merged": merged,
        "head": {"sha": "abc123"},
    }
    source = GithubPrSource("o/r", 7, None)

    assert watch([source], ["ci"], interval=0, timeout=5, follow=True) == 0
    assert capsys.readouterr().out.startswith("gh-pr o/r#7: ")


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


def test_gh_pr_author_watch_picks_up_a_new_pr_and_drops_a_merged_one(
    github: FakeGithub, capsys: pytest.CaptureFixture[str]
) -> None:
    github.pr()
    for path in ("pulls/9", "pulls/9/reviews?per_page=100"):
        github.bodies[f"repos/o/r/{path}"] = github.bodies[
            f"repos/o/r/{path.replace('9', '7')}"
        ]
    github.bodies["repos/o/r/pulls/7"] = {
        "state": "closed",
        "merged": True,
        "head": {"sha": "abc123"},
    }
    github.bodies["user"] = {"login": "me"}
    listings = iter(
        [
            [{"number": 7, "user": {"login": "me"}}],
            [
                {"number": 8, "user": {"login": "someone"}},
                {"number": 9, "user": {"login": "ME"}},
            ],
        ]
    )
    pulls = "repos/o/r/pulls?state=open&per_page=100"
    discovery = GithubPrDiscovery("@me", ["o/r"], None)

    def listed() -> list[GithubPrSource]:
        github.bodies[pulls] = next(listings, [])
        return discovery()

    code = watch([], ["ci"], interval=0, timeout=0.2, follow=True, discover=listed)

    assert code == 124
    out = capsys.readouterr().out
    assert out.count("gh-pr o/r#7: ") == 1
    assert "gh-pr o/r#9: " in out
    assert "o/r#8" not in out
