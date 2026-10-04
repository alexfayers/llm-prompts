"""Minimal GitHub API client, used by ``contribute`` when the gh CLI is not installed."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_CREDENTIAL_QUERY = "protocol=https\nhost=github.com\n\n"
_REMOTE_REPO = re.compile(r"[/:]([^/:]+)/([^/:]+?)(?:\.git)?/?$")
_API_URL = "https://api.github.com"
_API_VERSION = "2022-11-28"
_REQUEST_TIMEOUT_SECONDS = 30
_MAX_LISTED_PRS = 1000
_PAGE_SIZE = 100
_COMMITS_SELECTION = "commits(first: 250) { nodes { commit { oid messageHeadline messageBody authoredDate } } }"
_NO_TOKEN_MESSAGE = (
    "contribute needs the GitHub CLI or a token: install gh and run `gh auth login`, "
    "or set GH_TOKEN to a token with pull request read/write access."
)


@cache
def token() -> str:
    """Return a GitHub token from GH_TOKEN, GITHUB_TOKEN, or the git credential helper."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if value := os.environ.get(name):
            return value
    completed = subprocess.run(
        ["git", "credential", "fill"],
        input=_CREDENTIAL_QUERY,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        capture_output=True,
        text=True,
        check=False,
    )
    for line in completed.stdout.splitlines():
        if line.startswith("password=") and len(line) > len("password="):
            return line.removeprefix("password=")
    raise SystemExit(_NO_TOKEN_MESSAGE)


def has_upstream(repo: Path) -> bool:
    """Return whether ``repo`` has an ``upstream`` remote."""
    return _remote_url(repo, "upstream") is not None


def _remote_url(repo: Path, remote: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(repo), "remote", "get-url", remote],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


@cache
def base_repo(repo: Path) -> tuple[str, str]:
    """Return the (owner, name) of ``repo``'s upstream remote, else origin."""
    url = _remote_url(repo, "upstream") or _remote_url(repo, "origin") or ""
    match = _REMOTE_REPO.search(url)
    if match is None:
        raise SystemExit(
            f"Cannot find the GitHub repository of {repo} from its remotes."
        )
    return match.group(1), match.group(2)


def request(method: str, path: str, payload: Any = None) -> Any:
    """Call the GitHub REST (or GraphQL) API and return the decoded JSON response."""
    api_request = Request(
        f"{_API_URL}{path}",
        data=None if payload is None else json.dumps(payload).encode(),
        method=method,
        headers={
            "Authorization": f"Bearer {token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _API_VERSION,
        },
    )
    try:
        with urlopen(api_request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except HTTPError as error:
        message = json.loads(error.read() or b"{}").get("message", error.reason)
        raise subprocess.CalledProcessError(
            1, [method, path], stderr=f"HTTP {error.code}: {message}"
        ) from error
    except URLError as error:
        raise subprocess.CalledProcessError(
            1, [method, path], stderr=f"failed to connect: {error.reason}"
        ) from error


def graphql(query: str, variables: dict[str, Any]) -> Any:
    """Run a GraphQL query and return its ``data``."""
    response = request("POST", "/graphql", {"query": query, "variables": variables})
    if response.get("errors"):
        raise subprocess.CalledProcessError(
            1,
            ["POST", "/graphql"],
            stderr=f"GraphQL: {response['errors'][0]['message']}",
        )
    return response["data"]


@cache
def login() -> str:
    """Return the authenticated user's login."""
    return str(graphql("query { viewer { login } }", {})["viewer"]["login"])


def _selection(fields: Sequence[str]) -> str:
    return " ".join(
        _COMMITS_SELECTION if field == "commits" else field for field in fields
    )


def pr_list(repo: Path, qualifier: str, fields: Sequence[str]) -> list[dict[str, Any]]:
    """List the authenticated user's PRs in ``repo`` matching the search ``qualifier``."""
    owner, name = base_repo(repo)
    query = (
        "query($q: String!, $cursor: String) { search(query: $q, type: ISSUE, "
        f"first: {_PAGE_SIZE}, after: $cursor) {{ pageInfo {{ hasNextPage endCursor }} "
        f"nodes {{ ... on PullRequest {{ {_selection(fields)} }} }} }} }}"
    )
    variables: dict[str, Any] = {
        "q": f"repo:{owner}/{name} is:pr author:{login()} {qualifier}".rstrip(),
        "cursor": None,
    }
    prs: list[dict[str, Any]] = []
    while len(prs) < _MAX_LISTED_PRS:
        search = graphql(query, variables)["search"]
        prs.extend(search["nodes"])
        if not search["pageInfo"]["hasNextPage"]:
            break
        variables["cursor"] = search["pageInfo"]["endCursor"]
    return prs


def pr_view(repo: Path, number: int, fields: Sequence[str]) -> dict[str, Any]:
    """Return ``fields`` of PR ``number``, with commits flattened to a list."""
    owner, name = base_repo(repo)
    query = (
        "query($owner: String!, $name: String!, $number: Int!) { "
        "repository(owner: $owner, name: $name) { "
        f"pullRequest(number: $number) {{ {_selection(fields)} }} }} }}"
    )
    view: dict[str, Any] = graphql(
        query, {"owner": owner, "name": name, "number": number}
    )["repository"]["pullRequest"]
    if "commits" in view:
        view["commits"] = [node["commit"] for node in view["commits"]["nodes"]]
    return view


def viewer_permission(repo: Path) -> str:
    """Return the authenticated user's permission level on ``repo``."""
    owner, name = base_repo(repo)
    query = (
        "query($owner: String!, $name: String!) { "
        "repository(owner: $owner, name: $name) { viewerPermission } }"
    )
    return str(
        graphql(query, {"owner": owner, "name": name})["repository"]["viewerPermission"]
    )


def create_draft_pr(repo: Path, base: str, head: str, title: str, body: str) -> str:
    """Open a draft PR and return its URL."""
    owner, name = base_repo(repo)
    payload = {"base": base, "head": head, "title": title, "body": body, "draft": True}
    return str(request("POST", f"/repos/{owner}/{name}/pulls", payload)["html_url"])


def edit_pr(repo: Path, number: int, title: str, body: str) -> None:
    """Replace the title and body of PR ``number``."""
    owner, name = base_repo(repo)
    payload = {"title": title, "body": body}
    request("PATCH", f"/repos/{owner}/{name}/pulls/{number}", payload)


def update_pr_branch(repo: Path, number: int) -> None:
    """Rebase PR ``number``'s branch onto its base."""
    mutation = (
        "mutation($id: ID!) { updatePullRequestBranch(input: "
        "{pullRequestId: $id, updateMethod: REBASE}) { pullRequest { number } } }"
    )
    graphql(mutation, {"id": pr_view(repo, number, ["id"])["id"]})
