"""List open, ready pull requests with no unresolved review threads."""

import argparse
import json
import subprocess
from typing import Any, TypedDict

QUERY = """
query($owner: String!, $name: String!) {
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


class TriagedPullRequest(TypedDict):
    """A pull request to show, with its triage status."""

    number: int
    url: str
    title: str
    status: str


def _is_llm(item: dict[str, Any]) -> bool:
    return bool(item["body"].startswith(LLM_PREFIX))


def _is_human(review: dict[str, Any]) -> bool:
    """A review counts when it has a non-[LLM] body or is an approval or change request."""
    body = review["body"].strip()
    return (bool(body) and not _is_llm(review)) or review["state"] in DECISIVE_STATES


def triage(nodes: list[dict[str, Any]], viewer: str) -> list[TriagedPullRequest]:
    """Keep ready PRs with every thread resolved, addressed ones first."""
    triaged: list[TriagedPullRequest] = []
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
        involved = any(author and author["login"] == viewer for author in authored)
        triaged.append(
            {
                "number": node["number"],
                "url": node["url"],
                "title": node["title"],
                "status": ADDRESSED if involved else TO_REVIEW,
            }
        )
    return sorted(triaged, key=lambda pr: (pr["status"] != ADDRESSED, pr["number"]))


def render(results: dict[str, list[TriagedPullRequest]]) -> str:
    """Render one bold repo heading and a bullet per PR, repos separated by a blank line."""
    blocks: list[str] = []
    for repo, prs in results.items():
        bullets = [
            f"- {pr['status']} [#{pr['number']}]({pr['url']}) {pr['title']}"
            for pr in prs
        ] or ["none"]
        blocks.append("\n".join([f"**{repo}**", *bullets]))
    return "\n\n".join(blocks)


def gh(*args: str) -> str:
    """Run a gh command and return its stdout."""
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def fetch_nodes(repo: str) -> list[dict[str, Any]]:
    """Fetch a repo's open pull requests with one GraphQL query."""
    owner, _, name = repo.partition("/")
    response = gh(
        "api",
        "graphql",
        "-f",
        f"query={QUERY}",
        "-F",
        f"owner={owner}",
        "-F",
        f"name={name}",
    )
    pull_requests: dict[str, Any] = json.loads(response)["data"]["repository"][
        "pullRequests"
    ]
    nodes: list[dict[str, Any]] = pull_requests["nodes"]
    connections = [pull_requests]
    for node in nodes:
        connections += [node["reviewThreads"], node["reviews"]]
    if any(connection["pageInfo"]["hasNextPage"] for connection in connections):
        raise SystemExit(f"{repo}: too many items for one query")
    return nodes


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser: optional `owner/repo` positionals."""
    parser = argparse.ArgumentParser(description="List PRs awaiting your review")
    parser.add_argument("repos", nargs="*", help="owner/repo (default: current repo)")
    return parser


def run(repos: list[str]) -> str:
    """Return the markdown listing for the repos (default: current repo)."""
    repos = repos or [
        gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    ]
    viewer = gh("api", "user", "-q", ".login")
    return render({repo: triage(fetch_nodes(repo), viewer) for repo in repos})


def main(argv: list[str] | None = None) -> None:
    """List triaged PRs for each repo as markdown."""
    args = build_parser().parse_args(argv)
    try:
        print(run(args.repos))
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.stderr.strip() or str(error)) from error


if __name__ == "__main__":
    main()
