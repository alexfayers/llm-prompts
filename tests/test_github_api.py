"""Tests for the stdlib GitHub API client used when gh is not installed."""

from __future__ import annotations

import subprocess
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeGitHub, FakeSubprocess, http_error

from llm_prompts import contribute, github_api


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test without tokens or cached lookups."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    for cached in (github_api.token, github_api.login, github_api.base_repo):
        cached.cache_clear()


class TestToken:
    def test_gh_token_wins_over_github_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "from-gh")
        monkeypatch.setenv("GITHUB_TOKEN", "from-github")

        assert github_api.token() == "from-gh"

    def test_github_token_used_without_gh_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "from-github")

        assert github_api.token() == "from-github"

    def test_falls_back_to_git_credential_helper(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on(
            "credential",
            "fill",
            stdout="protocol=https\nhost=github.com\nusername=octo\npassword=s3cret\n",
        )

        assert github_api.token() == "s3cret"

        _, kwargs = fake_subprocess.calls[0]
        assert kwargs["input"] == "protocol=https\nhost=github.com\n\n"
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"

    def test_exits_pointing_at_gh_and_token_when_none_found(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("credential", "fill", returncode=128)

        with pytest.raises(SystemExit, match=r"(?s)gh auth login.*GH_TOKEN"):
            github_api.token()


class TestBaseRepo:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/octo/widgets.git",
            "https://github.com/octo/widgets",
            "ssh://git@github.com/octo/widgets.git",
            "git@github.com:octo/widgets.git",
        ],
    )
    def test_parses_owner_and_name(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path, url: str
    ) -> None:
        fake_subprocess.on("remote", "get-url", "upstream", returncode=2)
        fake_subprocess.on("remote", "get-url", "origin", stdout=f"{url}\n")

        assert github_api.base_repo(tmp_path) == ("octo", "widgets")

    def test_prefers_upstream_over_origin(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "remote", "get-url", "upstream", stdout="git@github.com:octo/widgets.git\n"
        )
        fake_subprocess.on(
            "remote", "get-url", "origin", stdout="git@github.com:fork/widgets.git\n"
        )

        assert github_api.base_repo(tmp_path) == ("octo", "widgets")

    def test_has_upstream_reflects_the_remote(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("remote", "get-url", "upstream", returncode=2)

        assert not github_api.has_upstream(tmp_path)


class TestRequest:
    def test_sends_bearer_token_and_json_payload(self, fake_github: FakeGitHub) -> None:
        fake_github.on("POST", "/repos/octo/widgets/pulls", {"html_url": "u"})

        result = github_api.request("POST", "/repos/octo/widgets/pulls", {"a": 1})

        assert result == {"html_url": "u"}
        method, _, body, headers = fake_github.requests[0]
        assert (method, body) == ("POST", {"a": 1})
        assert headers["authorization"] == "Bearer test-token"
        assert headers["accept"] == "application/vnd.github+json"

    def test_http_error_becomes_called_process_error(
        self, fake_github: FakeGitHub
    ) -> None:
        fake_github.on("GET", "/user", http_error(401, "Bad credentials"))

        with pytest.raises(subprocess.CalledProcessError) as caught:
            github_api.request("GET", "/user")

        assert caught.value.stderr == "HTTP 401: Bad credentials"

    def test_connection_failure_matches_the_transient_pattern(
        self, fake_github: FakeGitHub
    ) -> None:
        fake_github.on("GET", "/user", urllib.error.URLError("Connection refused"))

        with pytest.raises(subprocess.CalledProcessError) as caught:
            github_api.request("GET", "/user")

        assert contribute._TRANSIENT_FAILURE.search(caught.value.stderr)

    def test_token_never_reaches_a_subprocess(
        self, fake_github: FakeGitHub, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_github.on("GET", "/user", {})

        github_api.request("GET", "/user")

        assert fake_subprocess.commands == []


class TestGraphql:
    def test_returns_data(self, fake_github: FakeGitHub) -> None:
        fake_github.on_graphql(
            "viewer { login", {"data": {"viewer": {"login": "octocat"}}}
        )

        assert github_api.login() == "octocat"

    def test_errors_become_called_process_error(self, fake_github: FakeGitHub) -> None:
        fake_github.on_graphql("viewer { login", {"errors": [{"message": "Bad query"}]})

        with pytest.raises(subprocess.CalledProcessError) as caught:
            github_api.login()

        assert caught.value.stderr == "GraphQL: Bad query"


@pytest.fixture
def octo_repo(fake_subprocess: FakeSubprocess, tmp_path: Path) -> Path:
    fake_subprocess.on("remote", "get-url", "upstream", returncode=2)
    fake_subprocess.on(
        "remote", "get-url", "origin", stdout="git@github.com:octo/widgets.git\n"
    )
    return tmp_path


def _page(numbers: list[int], end_cursor: str | None) -> dict[str, Any]:
    return {
        "data": {
            "search": {
                "pageInfo": {
                    "hasNextPage": end_cursor is not None,
                    "endCursor": end_cursor,
                },
                "nodes": [{"number": number} for number in numbers],
            }
        }
    }


class TestPrList:
    def test_pages_until_no_next_page(
        self, fake_github: FakeGitHub, octo_repo: Path
    ) -> None:
        fake_github.on_graphql(
            "viewer { login", {"data": {"viewer": {"login": "octocat"}}}
        )
        fake_github.on_graphql("search(", _page([1, 2], "c1"), _page([3], None))

        prs = github_api.pr_list(octo_repo, "is:open", ["number"])

        assert [pr["number"] for pr in prs] == [1, 2, 3]
        variables = fake_github.graphql_variables("search(")
        assert [v["cursor"] for v in variables] == [None, "c1"]
        assert variables[0]["q"] == "repo:octo/widgets is:pr author:octocat is:open"


class TestPrView:
    def test_flattens_commits(self, fake_github: FakeGitHub, octo_repo: Path) -> None:
        commit = {
            "oid": "a1",
            "messageHeadline": "h",
            "messageBody": "",
            "authoredDate": "d",
        }
        fake_github.on_graphql(
            "pullRequest(",
            {
                "data": {
                    "repository": {
                        "pullRequest": {"commits": {"nodes": [{"commit": commit}]}}
                    }
                }
            },
        )

        view = github_api.pr_view(octo_repo, 7, ["commits"])

        assert view == {"commits": [commit]}
        assert fake_github.graphql_variables("pullRequest(")[0] == {
            "owner": "octo",
            "name": "widgets",
            "number": 7,
        }

    def test_returns_plain_fields_as_is(
        self, fake_github: FakeGitHub, octo_repo: Path
    ) -> None:
        fake_github.on_graphql(
            "pullRequest(", {"data": {"repository": {"pullRequest": {"body": "text"}}}}
        )

        assert github_api.pr_view(octo_repo, 7, ["body"]) == {"body": "text"}


class TestRepositoryCalls:
    def test_viewer_permission(self, fake_github: FakeGitHub, octo_repo: Path) -> None:
        fake_github.on_graphql(
            "viewerPermission", {"data": {"repository": {"viewerPermission": "READ"}}}
        )

        assert github_api.viewer_permission(octo_repo) == "READ"

    def test_create_draft_pr_posts_a_draft(
        self, fake_github: FakeGitHub, octo_repo: Path
    ) -> None:
        fake_github.on("POST", "/repos/octo/widgets/pulls", {"html_url": "https://x/1"})

        url = github_api.create_draft_pr(octo_repo, "main", "me:topic", "t", "b")

        assert url == "https://x/1"
        assert fake_github.requests[0][2] == {
            "base": "main",
            "head": "me:topic",
            "title": "t",
            "body": "b",
            "draft": True,
        }

    def test_edit_pr_body_patches_the_body(
        self, fake_github: FakeGitHub, octo_repo: Path
    ) -> None:
        fake_github.on("PATCH", "/repos/octo/widgets/pulls/4", {})

        github_api.edit_pr_body(octo_repo, 4, "new")

        assert fake_github.requests[0][2] == {"body": "new"}

    def test_update_pr_branch_rebases_by_node_id(
        self, fake_github: FakeGitHub, octo_repo: Path
    ) -> None:
        fake_github.on_graphql(
            "pullRequest(", {"data": {"repository": {"pullRequest": {"id": "PR_1"}}}}
        )
        fake_github.on_graphql(
            "updatePullRequestBranch", {"data": {"updatePullRequestBranch": {}}}
        )

        github_api.update_pr_branch(octo_repo, 4)

        _, _, body, _ = fake_github.requests[-1]
        assert "updateMethod: REBASE" in body["query"]
        assert body["variables"] == {"id": "PR_1"}
