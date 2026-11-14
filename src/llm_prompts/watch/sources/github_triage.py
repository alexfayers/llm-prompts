"""Watch a GitHub repository's ready pull requests that have no unresolved review threads."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, ClassVar, Self

from ...network import run_with_retries
from ..core.source import Fields, WatchError
from .rest import conditional_get

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
        reviewThreads(first: 50) { pageInfo { hasNextPage } nodes { isResolved } }
        reviews(first: 20) { pageInfo { hasNextPage } nodes { author { login } state body } }
      }
    }
  }
}
"""
THREAD_COMMENTS = "reviewThreads(first: 50) { nodes { comments(first: 1) { nodes { author { login } body } } } }"
MAX_AGE = 900.0
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


def _is_viewer(authors: Sequence[dict[str, Any] | None], viewer: str) -> bool:
    return any(author and author["login"] == viewer for author in authors)


def triage(
    nodes: list[dict[str, Any]],
    viewer: str,
    comment_authors: Callable[[list[int]], Mapping[int, list[dict[str, Any] | None]]],
) -> list[str]:
    """Return a line per ready PR with every thread resolved, addressed ones first.

    comment_authors gives the authors of a PR's human thread-opening comments, and is asked only about
    ready PRs that none of the viewer's reviews already address.
    """
    ready = [
        node
        for node in nodes
        if not node["isDraft"]
        and all(thread["isResolved"] for thread in node["reviewThreads"]["nodes"])
    ]
    reviewed = {
        node["number"]
        for node in ready
        if _is_viewer(
            [r["author"] for r in node["reviews"]["nodes"] if _is_human(r)], viewer
        )
    }
    commented = comment_authors(
        [node["number"] for node in ready if node["number"] not in reviewed]
    )
    triaged: list[tuple[bool, int, str]] = []
    for node in ready:
        number = node["number"]
        addressed = number in reviewed or _is_viewer(commented[number], viewer)
        status = ADDRESSED if addressed else TO_REVIEW
        triaged.append(
            (
                not addressed,
                number,
                f"- {status} [#{number}]({node['url']}) {node['title']}",
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
        self._etag: str | None = None
        self._checked = 0.0
        self._fields: Fields | None = None

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

    @property
    def state_key(self) -> str:
        """Return the repository its stored state belongs to."""
        return self._resolve_repo()

    def load_state(self, state: Mapping[str, Any]) -> None:
        """Restore the open-PR list's ETag and the result computed under it."""
        etag, checked, fields = (
            state.get("etag"),
            state.get("checked"),
            state.get("fields"),
        )
        if (
            isinstance(etag, str)
            and isinstance(checked, int | float)
            and isinstance(fields, dict)
        ):
            self._etag, self._checked, self._fields = etag, float(checked), fields

    def dump_state(self) -> dict[str, Any]:
        """Return the open-PR list's ETag and the result computed under it."""
        if self._etag is None or self._fields is None:
            return {}
        return {"etag": self._etag, "checked": self._checked, "fields": self._fields}

    def _resolve_repo(self) -> str:
        self._repo = self._repo or _gh(
            "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"
        )
        return self._repo

    def poll(self) -> Fields:
        """Return the triaged list, markdown, and its length.

        The query runs only when the open-PR list changed or the last result is older than MAX_AGE.
        """
        response = conditional_get(
            f"repos/{self._resolve_repo()}/pulls?state=open&per_page=100", self._etag
        )
        if response.code not in {200, 304}:
            raise WatchError(f"{self._repo}: GitHub request failed.")
        if (
            response.code == 304
            and self._fields is not None
            and time.time() - self._checked < MAX_AGE
        ):
            return self._fields
        self._fields = self._query()
        self._etag = response.headers.get("etag", self._etag)
        self._checked = time.time()
        return self._fields

    def _graphql(self, query: str) -> dict[str, Any]:
        owner, _, name = self._repo.partition("/")
        data: dict[str, Any] = json.loads(
            _gh(
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
            )
        )["data"]
        return data

    def _comment_authors(
        self, numbers: list[int]
    ) -> dict[int, list[dict[str, Any] | None]]:
        if not numbers:
            return {}
        fields = " ".join(
            f"pr{number}: pullRequest(number: {number}) {{ {THREAD_COMMENTS} }}"
            for number in numbers
        )
        repository = self._graphql(
            "query($owner: String!, $name: String!) { "
            f"repository(owner: $owner, name: $name) {{ {fields} }} }}"
        )["repository"]
        return {
            number: [
                comment["author"]
                for thread in repository[f"pr{number}"]["reviewThreads"]["nodes"]
                for comment in thread["comments"]["nodes"]
                if not _is_llm(comment)
            ]
            for number in numbers
        }

    def _query(self) -> Fields:
        data = self._graphql(QUERY)
        pull_requests = data["repository"]["pullRequests"]
        nodes: list[dict[str, Any]] = pull_requests["nodes"]
        connections = [pull_requests]
        for node in nodes:
            connections += [node["reviewThreads"], node["reviews"]]
        if any(connection["pageInfo"]["hasNextPage"] for connection in connections):
            raise WatchError(f"{self._repo}: too many items for one query.")
        lines = triage(nodes, data["viewer"]["login"], self._comment_authors)
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
