"""Tests for the watch gh-triage source."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest
from conftest import FakeSubprocess

from llm_prompts.watch.core.runner import watch
from llm_prompts.watch.sources.github_triage import GithubTriageSource

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
            "nodes": [{"isResolved": not unresolved, "comments": {"nodes": []}}],
        },
        "reviews": {
            "pageInfo": LAST_PAGE,
            "nodes": [
                {"author": {"login": reviewer}, "state": "COMMENTED", "body": "ok"}
            ],
        },
    }


def serve(fake_subprocess: FakeSubprocess, *polls: list[dict[str, Any]]) -> None:
    answers = iter(polls)

    def respond(
        argv: list[str], kwargs: dict[str, Any]
    ) -> subprocess.CompletedProcess[str]:
        data = {
            "viewer": {"login": VIEWER},
            "repository": {
                "pullRequests": {"pageInfo": LAST_PAGE, "nodes": next(answers)}
            },
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps({"data": data}), "")

    fake_subprocess.on_match(
        lambda argv: argv[:3] == ["gh", "api", "graphql"], side_effect=respond
    )


def test_gh_triage_prints_the_full_list_when_a_ready_pr_appears(
    fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
) -> None:
    ready = pull_request(1, reviewer=VIEWER)
    hidden = [pull_request(2, draft=True), pull_request(3, unresolved=True)]
    serve(fake_subprocess, [ready, *hidden], [pull_request(4), ready, *hidden])

    source = GithubTriageSource("o/r")

    assert watch([source], ["update"], interval=0, timeout=5) == 0
    assert capsys.readouterr().out == (
        "gh-triage o/r: update\n"
        "**o/r**\n"
        "- ✅ addressed: [#1](https://github.com/o/r/pull/1) title 1\n"
        "- 👀 to review: [#4](https://github.com/o/r/pull/4) title 4\n"
    )


def test_gh_triage_fails_cleanly_when_the_default_repository_lookup_fails(
    fake_subprocess: FakeSubprocess,
) -> None:
    fake_subprocess.on("gh", "repo", "view", returncode=1, stderr="not a repository")

    assert watch([GithubTriageSource("")], ["update"], interval=0, timeout=5) == 1
