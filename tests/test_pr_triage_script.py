"""Tests for the pr-triage skill's listing script."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "shared"
    / "skills"
    / "pr-triage"
    / "pr_triage.py"
)

VIEWER = "me"
LAST_PAGE = {"hasNextPage": False}


@pytest.fixture
def mod() -> ModuleType:
    """Load the pr_triage script as a module."""
    spec = importlib.util.spec_from_file_location("pr_triage", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pull_request(
    number: int,
    *,
    draft: bool = False,
    threads: list[tuple[bool, str]] | None = None,
    reviewers: list[str] | None = None,
) -> dict[str, Any]:
    """Build one GraphQL pull request node."""
    return {
        "number": number,
        "url": f"https://github.com/o/r/pull/{number}",
        "title": f"title {number}",
        "isDraft": draft,
        "reviewThreads": {
            "pageInfo": LAST_PAGE,
            "nodes": [
                {
                    "isResolved": resolved,
                    "comments": {
                        "nodes": [{"author": {"login": author}, "body": "ok"}]
                    },
                }
                for resolved, author in threads or []
            ],
        },
        "reviews": {
            "pageInfo": LAST_PAGE,
            "nodes": [
                {
                    "author": {"login": name},
                    "state": "COMMENTED",
                    "body": "ok",
                }
                for name in reviewers or []
            ],
        },
    }


class TestTriage:
    """Tests for filtering and status assignment."""

    def test_excludes_drafts_and_unresolved_threads(self, mod: ModuleType) -> None:
        nodes = [
            pull_request(1, draft=True),
            pull_request(2, threads=[(False, "other")]),
            pull_request(3),
        ]
        assert [pr["number"] for pr in mod.triage(nodes, VIEWER)] == [3]

    def test_unreviewed_pr_is_to_review(self, mod: ModuleType) -> None:
        nodes = [pull_request(1, threads=[(True, "other")], reviewers=["other"])]
        assert mod.triage(nodes, VIEWER)[0]["status"] == "👀 to review:"

    def test_viewer_review_makes_it_addressed(self, mod: ModuleType) -> None:
        nodes = [pull_request(1, reviewers=[VIEWER])]
        assert mod.triage(nodes, VIEWER)[0]["status"] == "✅ addressed:"

    def test_viewer_thread_makes_it_addressed(self, mod: ModuleType) -> None:
        nodes = [pull_request(1, threads=[(True, VIEWER)])]
        assert mod.triage(nodes, VIEWER)[0]["status"] == "✅ addressed:"

    def test_addressed_sorts_first_then_by_number(self, mod: ModuleType) -> None:
        nodes = [
            pull_request(5),
            pull_request(4, reviewers=[VIEWER]),
            pull_request(2),
            pull_request(9, reviewers=[VIEWER]),
        ]
        assert [pr["number"] for pr in mod.triage(nodes, VIEWER)] == [4, 9, 2, 5]

    def test_ignores_deleted_authors(self, mod: ModuleType) -> None:
        node = pull_request(1)
        node["reviews"]["nodes"] = [
            {"author": None, "state": "COMMENTED", "body": "ok"}
        ]
        node["reviewThreads"]["nodes"] = [
            {
                "isResolved": True,
                "comments": {"nodes": [{"author": None, "body": "ok"}]},
            }
        ]
        assert mod.triage([node], VIEWER)[0]["status"] == "👀 to review:"


class TestLlmActivity:
    """Tests that [LLM]-prefixed activity under the viewer's account is ignored."""

    def test_llm_thread_is_not_a_viewer_review(self, mod: ModuleType) -> None:
        node = pull_request(1, threads=[(True, VIEWER)])
        node["reviewThreads"]["nodes"][0]["comments"]["nodes"][0]["body"] = "[LLM] done"
        assert mod.triage([node], VIEWER)[0]["status"] == "👀 to review:"

    def test_llm_review_body_is_not_a_viewer_review(self, mod: ModuleType) -> None:
        node = pull_request(1, reviewers=[VIEWER])
        node["reviews"]["nodes"][0]["body"] = "[LLM] looks fine"
        assert mod.triage([node], VIEWER)[0]["status"] == "👀 to review:"

    def test_bare_approval_counts(self, mod: ModuleType) -> None:
        node = pull_request(1, reviewers=[VIEWER])
        node["reviews"]["nodes"][0].update(body="", state="APPROVED")
        assert mod.triage([node], VIEWER)[0]["status"] == "✅ addressed:"

    def test_empty_comment_only_review_is_not_a_viewer_review(
        self, mod: ModuleType
    ) -> None:
        node = pull_request(1, reviewers=[VIEWER])
        node["reviews"]["nodes"][0]["body"] = ""
        assert mod.triage([node], VIEWER)[0]["status"] == "👀 to review:"


class TestRender:
    """Tests for the markdown output."""

    def test_groups_by_bold_repo_with_linked_bullets(self, mod: ModuleType) -> None:
        results = {
            "o/a": mod.triage(
                [pull_request(3), pull_request(1, reviewers=[VIEWER])], VIEWER
            ),
            "o/b": [],
        }
        assert mod.render(results) == (
            "**o/a**\n"
            "- ✅ addressed: [#1](https://github.com/o/r/pull/1) title 1\n"
            "- 👀 to review: [#3](https://github.com/o/r/pull/3) title 3\n"
            "\n"
            "**o/b**\n"
            "none"
        )


class FakeGh:
    """Stand-in for subprocess.run that answers gh calls and records them."""

    def __init__(self, nodes_by_repo: dict[str, list[dict[str, Any]]]) -> None:
        self.nodes_by_repo = nodes_by_repo
        self.calls: list[list[str]] = []
        self.pull_requests_page_info = LAST_PAGE

    def __call__(
        self, command: list[str], **_: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if command[:3] == ["gh", "api", "user"]:
            out = VIEWER
        elif command[:3] == ["gh", "repo", "view"]:
            out = "o/current"
        else:
            repo = next(
                arg for arg in command if arg.startswith("owner=")
            ).removeprefix("owner=")
            name = next(arg for arg in command if arg.startswith("name=")).removeprefix(
                "name="
            )
            nodes = self.nodes_by_repo[f"{repo}/{name}"]
            out = json.dumps(
                {
                    "data": {
                        "repository": {
                            "pullRequests": {
                                "pageInfo": self.pull_requests_page_info,
                                "nodes": nodes,
                            }
                        }
                    }
                }
            )
        return subprocess.CompletedProcess(command, 0, stdout=out)


class TestMain:
    """Tests for the gh-backed entry point."""

    def test_one_graphql_query_per_repo(
        self,
        mod: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        gh = FakeGh({"o/a": [pull_request(1)], "o/b": []})
        monkeypatch.setattr(mod.subprocess, "run", gh)
        mod.main(["o/a", "o/b"])
        assert len([call for call in gh.calls if "graphql" in call]) == 2
        assert capsys.readouterr().out.startswith("**o/a**\n- 👀 to review: [#1]")

    def test_defaults_to_current_repo(
        self,
        mod: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(mod.subprocess, "run", FakeGh({"o/current": []}))
        mod.main([])
        assert capsys.readouterr().out.startswith("**o/current**")

    @pytest.mark.parametrize("where", ["pullRequests", "reviewThreads", "reviews"])
    def test_fails_without_output_when_a_connection_is_truncated(
        self,
        mod: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        where: str,
    ) -> None:
        node = pull_request(1, reviewers=[VIEWER])
        truncated = {"hasNextPage": True}
        if where != "pullRequests":
            node[where]["pageInfo"] = truncated
        gh = FakeGh({"o/a": [node]})
        if where == "pullRequests":
            gh.pull_requests_page_info = truncated
        monkeypatch.setattr(mod.subprocess, "run", gh)
        with pytest.raises(SystemExit, match="o/a: too many items"):
            mod.main(["o/a"])
        assert capsys.readouterr().out == ""

    def test_gh_failure_exits_with_its_message(
        self, mod: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            raise subprocess.CalledProcessError(1, command, stderr="Could not resolve")

        monkeypatch.setattr(mod.subprocess, "run", failing)
        with pytest.raises(SystemExit, match="Could not resolve"):
            mod.main(["o/a"])
