"""Tests for the watch gh-triage source."""

from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Any

import pytest
from conftest import FakeSubprocess

from llm_prompts.watch.core.runner import watch
from llm_prompts.watch.sources.github_triage import MAX_AGE, GithubTriageSource

VIEWER = "me"
LAST_PAGE = {"hasNextPage": False}


def pull_request(
    number: int, *, draft: bool = False, unresolved: bool = False, reviewer: str = "x"
) -> dict[str, Any]:
    return {
        "number": number,
        "url": f"https://github.com/o/r/pull/{number}",
        "title": f"title {number}",
        "isDraft": draft,
        "reviewThreads": {
            "pageInfo": LAST_PAGE,
            "nodes": [{"isResolved": not unresolved}],
        },
        "reviews": {
            "pageInfo": LAST_PAGE,
            "nodes": [
                {"author": {"login": reviewer}, "state": "COMMENTED", "body": "ok"}
            ],
        },
    }


class FakeGithub:
    """Serves the open-PR list over REST with an ETag, and the triage queries over GraphQL."""

    def __init__(self, fake_subprocess: FakeSubprocess) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.thread_authors: dict[int, list[str]] = {}
        self.version = 0
        self.upcoming: list[list[dict[str, Any]]] = []
        self.queries: list[str] = []
        fake_subprocess.on_match(
            lambda argv: argv[:3] == ["gh", "api", "-i"], side_effect=self._rest
        )
        fake_subprocess.on_match(
            lambda argv: argv[:3] == ["gh", "api", "graphql"],
            side_effect=self._graphql,
        )

    def change(self, *nodes: dict[str, Any]) -> None:
        self.nodes = list(nodes)
        self.version += 1

    def _rest(
        self, argv: list[str], kwargs: dict[str, Any]
    ) -> subprocess.CompletedProcess[str]:
        assert argv[3] == "repos/o/r/pulls?state=open&per_page=100"
        if self.upcoming:
            self.change(*self.upcoming.pop(0))
        etag = f'"{self.version}"'
        if f"If-None-Match: {etag}" in argv:
            return subprocess.CompletedProcess(
                argv, 1, f"HTTP/2.0 304 Not Modified\nEtag: {etag}\n\n", "gh: HTTP 304"
            )
        return subprocess.CompletedProcess(
            argv, 0, f"HTTP/2.0 200 OK\nEtag: {etag}\n\n[]", ""
        )

    def _graphql(
        self, argv: list[str], kwargs: dict[str, Any]
    ) -> subprocess.CompletedProcess[str]:
        query = next(arg for arg in argv if arg.startswith("query="))
        self.queries.append(query)
        if "comments(first: 1)" in query:
            repository = {
                f"pr{number}": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "comments": {
                                    "nodes": [{"author": {"login": a}, "body": "b"}]
                                }
                            }
                            for a in self.thread_authors.get(number, [])
                        ]
                    }
                }
                for number in map(int, re.findall(r"pr(\d+):", query))
            }
            data: dict[str, Any] = {"repository": repository}
        else:
            data = {
                "viewer": {"login": VIEWER},
                "repository": {
                    "pullRequests": {"pageInfo": LAST_PAGE, "nodes": self.nodes}
                },
            }
        return subprocess.CompletedProcess(argv, 0, json.dumps({"data": data}), "")


@pytest.fixture
def github(fake_subprocess: FakeSubprocess, isolated_home: object) -> FakeGithub:
    return FakeGithub(fake_subprocess)


def test_gh_triage_prints_the_full_list_when_a_ready_pr_appears(
    github: FakeGithub, capsys: pytest.CaptureFixture[str]
) -> None:
    ready = pull_request(1, reviewer=VIEWER)
    hidden = [pull_request(2, draft=True), pull_request(3, unresolved=True)]
    github.upcoming = [[ready, *hidden], [pull_request(4), ready, *hidden]]

    assert (
        watch([GithubTriageSource("o/r")], ["changed:list"], interval=0, timeout=5) == 0
    )
    assert capsys.readouterr().out == (
        "gh-triage o/r: changed:list\n"
        "**o/r**\n"
        "- ✅ addressed: [#1](https://github.com/o/r/pull/1) title 1\n"
        "- 👀 to review: [#4](https://github.com/o/r/pull/4) title 4\n"
    )


def test_gh_triage_marks_a_pr_addressed_when_the_viewer_opened_a_thread(
    github: FakeGithub,
) -> None:
    github.change(pull_request(1), pull_request(2))
    github.thread_authors = {1: [VIEWER], 2: ["x"]}

    assert GithubTriageSource("o/r").poll()["list"] == (
        "**o/r**\n"
        "- ✅ addressed: [#1](https://github.com/o/r/pull/1) title 1\n"
        "- 👀 to review: [#2](https://github.com/o/r/pull/2) title 2"
    )


def test_gh_triage_reads_thread_comments_only_for_ready_prs_the_viewer_has_not_reviewed(
    github: FakeGithub,
) -> None:
    github.change(
        pull_request(1, reviewer=VIEWER),
        pull_request(2),
        pull_request(3, unresolved=True),
        pull_request(4, draft=True),
    )

    GithubTriageSource("o/r").poll()

    (_, comments) = github.queries
    assert re.findall(r"pr(\d+):", comments) == ["2"]


def test_gh_triage_skips_graphql_while_the_pr_list_is_unchanged(
    github: FakeGithub,
) -> None:
    github.change(pull_request(1))
    source = GithubTriageSource("o/r")
    first = source.poll()
    github.queries.clear()

    assert source.poll() == first
    assert github.queries == []


def test_gh_triage_queries_again_when_the_pr_list_changes(github: FakeGithub) -> None:
    github.change(pull_request(1))
    source = GithubTriageSource("o/r")
    source.poll()

    github.change(pull_request(1), pull_request(2))

    assert source.poll()["count"] == "2"


def test_gh_triage_queries_again_when_the_last_result_is_old(
    github: FakeGithub, monkeypatch: pytest.MonkeyPatch
) -> None:
    github.change(pull_request(1))
    source = GithubTriageSource("o/r")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    source.poll()
    github.queries.clear()

    monkeypatch.setattr(time, "time", lambda: now + MAX_AGE)
    source.poll()

    assert github.queries


def test_gh_triage_a_later_watch_reuses_the_result_an_earlier_one_stored(
    github: FakeGithub,
) -> None:
    github.change(pull_request(1))
    watch([GithubTriageSource("o/r")], ["count=1"], interval=0, timeout=5)
    github.queries.clear()

    watch([GithubTriageSource("o/r")], ["count=1"], interval=0, timeout=5)

    assert github.queries == []


def test_gh_triage_fails_cleanly_when_the_default_repository_lookup_fails(
    fake_subprocess: FakeSubprocess, isolated_home: object
) -> None:
    fake_subprocess.on("gh", "repo", "view", returncode=1, stderr="not a repository")

    assert watch([GithubTriageSource("")], ["update"], interval=0, timeout=5) == 1
