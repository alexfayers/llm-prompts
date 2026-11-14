"""Watch a GitHub repository's ready pull requests that have no unresolved review threads."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Self

from ...network import run_with_retries
from ..core.source import Fields, WatchError

QUERY = """
query($owner: String!, $name: String!) {
  viewer { login }
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 30) {
      pageInfo { hasNextPage }
      nodes {
        number
        url
        title
        isDraft
        reviewThreads(first: 50) {
          pageInfo { hasNextPage }
          nodes { isResolved comments(first: 1) { nodes { author { login } body } } }
        }
        reviews(first: 20) { pageInfo { hasNextPage } nodes { author { login } state body } }
      }
    }
  }
}
"""
LLM_PREFIX = "[LLM]"
ADDRESSED = "✅ addressed:"
TO_REVIEW = "👀 to review:"
DECISIVE_STATES = {"APPROVED", "CHANGES_REQUESTED"}


def _is_llm(item: dict[str, Any]) -> bool:
    return bool(item["body"].startswith(LLM_PREFIX))


def _is_human(review: dict[str, Any]) -> bool:
    """A review counts when it has a non-[LLM] body or is an approval or change request."""
    body = review["body"].strip()
    return (bool(body) and not _is_llm(review)) or review["state"] in DECISIVE_STATES


def triage(nodes: list[dict[str, Any]], viewer: str) -> list[str]:
    """Return a line per ready PR with every thread resolved, addressed ones first."""
    triaged: list[tuple[bool, int, str]] = []
    for node in nodes:
        threads = node["reviewThreads"]["nodes"]
        if node["isDraft"] or any(not thread["isResolved"] for thread in threads):
            continue
        authored = [
            review["author"] for review in node["reviews"]["nodes"] if _is_human(review)
        ]
        authored += [
            comment["author"]
            for thread in threads
            for comment in thread["comments"]["nodes"]
            if not _is_llm(comment)
        ]
        addressed = any(author and author["login"] == viewer for author in authored)
        status = ADDRESSED if addressed else TO_REVIEW
        triaged.append(
            (
                not addressed,
                node["number"],
                f"- {status} [#{node['number']}]({node['url']}) {node['title']}",
            )
        )
    return [line for *_, line in sorted(triaged)]


class GithubTriageSource:
    """Reports a repository's ready pull requests that have no unresolved review threads."""

    name: ClassVar[str] = "gh-triage"
    default_interval: ClassVar[float] = 300.0
    aliases: ClassVar[Mapping[str, Sequence[str]]] = {"update": ["changed:list"]}

    def __init__(self, repo: str) -> None:
        """Watch the pull requests of repo, given as ``owner/name``, or of the current repository if empty."""
        self._repo = repo

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Add the repository argument."""
        parser.add_argument(
            "repo",
            nargs="*",
            help="owner/repo, default the current repository. Any match stops the watch.",
        )

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> list[Self]:
        """Build one source per repository from parsed arguments."""
        return [cls(repo) for repo in args.repo or [""]]

    def describe(self) -> str:
        """Return the short label printed with the result."""
        return f"gh-triage {self._repo}"

    def poll(self) -> Fields:
        """Return the triaged list, markdown, and its length."""
        self._repo = self._repo or _gh(
            "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"
        )
        owner, _, name = self._repo.partition("/")
        data = json.loads(
            _gh(
                "api",
                "graphql",
                "-f",
                f"query={QUERY}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
            )
        )["data"]
        pull_requests = data["repository"]["pullRequests"]
        nodes: list[dict[str, Any]] = pull_requests["nodes"]
        connections = [pull_requests]
        for node in nodes:
            connections += [node["reviewThreads"], node["reviews"]]
        if any(connection["pageInfo"]["hasNextPage"] for connection in connections):
            raise WatchError(f"{self._repo}: too many items for one query.")
        lines = triage(nodes, data["viewer"]["login"])
        return {
            "count": str(len(lines)),
            "list": "\n".join([f"**{self._repo}**", *(lines or ["none"])]),
        }


def _gh(*args: str) -> str:
    try:
        result = run_with_retries(["gh", *args], capture_output=True, text=True)
    except OSError:
        raise WatchError("gh is not installed.") from None
    if result.returncode:
        raise WatchError(result.stderr.strip() or "gh failed.")
    return result.stdout.strip()
