"""Persisted links between commits in different repos, and the decisions drawn from them.

A commit is identified by its (tool, subject, authored date), never its sha,
because a sha changes whenever the commit is rewritten. All git/gh I/O lives
in ``contribute.py``; this module only works on data it is handed.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from .batching import SelectionError
from .setup import _CONFIG_DIR

if TYPE_CHECKING:
    from .contribute import Commit

LINKS_PATH = _CONFIG_DIR / "contribute-links.json"
HELD_STAGES = frozenset({"local only", "needs sync"})
_MERGED_STAGE = "merged"

CommitKey = tuple[str, str, str]


class LinkCycleError(SelectionError):
    """Raised when links would make a commit, or a repo, depend on itself."""

    def __init__(self, message: str) -> None:
        super().__init__([message])


class Link(NamedTuple):
    """A commit that must not go out before another commit in a different repo."""

    dependent_tool: str
    dependent_subject: str
    dependent_date: str
    dependency_tool: str
    dependency_subject: str
    dependency_date: str

    @property
    def dependent(self) -> CommitKey:
        """Return the dependent commit's identity."""
        return (self.dependent_tool, self.dependent_subject, self.dependent_date)

    @property
    def dependency(self) -> CommitKey:
        """Return the dependency commit's identity."""
        return (self.dependency_tool, self.dependency_subject, self.dependency_date)


class Status(NamedTuple):
    """A pending commit's review stage, PR url and branch."""

    stage: str
    url: str | None
    branch: str | None


class Annotation(NamedTuple):
    """One dependency of a commit, as shown next to it in a listing."""

    dependency_tool: str
    dependency_subject: str
    stage: str
    url: str | None
    satisfied: bool


class Note(NamedTuple):
    """A dependency line for a listing; `urgent` when the dependency is not yet reviewable."""

    text: str
    urgent: bool


StatusByTool = Mapping[str, Mapping[tuple[str, str], Status]]


def load_links(path: Path) -> tuple[Link, ...]:
    """Read the saved links; a missing or unreadable file holds none."""
    if not path.exists():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return tuple(Link(**entry) for entry in data.get("links", []))
    except (json.JSONDecodeError, TypeError, AttributeError):
        return ()


def save_links(path: Path, links: Sequence[Link]) -> None:
    """Write `links` to `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"links": [link._asdict() for link in links]}, indent=2) + "\n",
        encoding="utf-8",
    )


def _has_cycle(edges: Mapping[object, set[object]]) -> bool:
    done: set[object] = set()
    for root in edges:
        stack = [(root, iter(edges[root]))]
        active = {root}
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                stack.pop()
                active.discard(node)
                done.add(node)
            elif child in active:
                return True
            elif child not in done:
                active.add(child)
                stack.append((child, iter(edges.get(child, ()))))
    return False


def add_links(existing: Sequence[Link], new: Sequence[Link]) -> tuple[Link, ...]:
    """Union `new` into `existing` in order; raise `LinkCycleError` on a cycle."""
    links = tuple(dict.fromkeys([*existing, *new]))
    edges: dict[object, set[object]] = {}
    for link in links:
        edges.setdefault(link.dependent, set()).add(link.dependency)
    if _has_cycle(edges):
        raise LinkCycleError("these links would make a commit depend on itself")
    return links


def derive_links(ordered_commits: Sequence[CommitKey]) -> tuple[Link, ...]:
    """Make each commit depend on every commit in the repos that appear before its own."""
    tools = list(dict.fromkeys(tool for tool, _, _ in ordered_commits))
    return tuple(
        Link(*commit, *earlier)
        for commit in ordered_commits
        for earlier in ordered_commits
        if tools.index(earlier[0]) < tools.index(commit[0])
    )


def prune(
    links: Sequence[Link],
    pending_by_tool: Mapping[str, set[tuple[str, str]]],
    configured_tools: Collection[str],
) -> tuple[Link, ...]:
    """Drop links whose dependent is no longer pending or whose repo is not configured."""
    return tuple(
        link
        for link in links
        if link.dependent_tool in configured_tools
        and link.dependency_tool in configured_tools
        and (link.dependent_subject, link.dependent_date)
        in pending_by_tool.get(link.dependent_tool, set())
    )


def annotate(
    links: Sequence[Link], status_by_tool: StatusByTool
) -> dict[CommitKey, tuple[Annotation, ...]]:
    """List each dependent's dependencies with their stage; an absent one has merged."""
    annotations: dict[CommitKey, list[Annotation]] = {}
    for link in links:
        status = status_by_tool.get(link.dependency_tool, {}).get(
            (link.dependency_subject, link.dependency_date)
        )
        annotations.setdefault(link.dependent, []).append(
            Annotation(
                link.dependency_tool,
                link.dependency_subject,
                _MERGED_STAGE if status is None else status.stage,
                None if status is None else status.url,
                status is None,
            )
        )
    return {key: tuple(values) for key, values in annotations.items()}


def _note(annotation: Annotation, pr_body: str | None) -> Note:
    if not annotation.url:
        held = annotation.stage in HELD_STAGES
        return Note(
            f"depends on {annotation.dependency_tool}: "
            + ("unpushed" if held else "no PR yet"),
            True,
        )
    missing = pr_body is not None and annotation.url not in pr_body
    return Note(
        f"depends on {annotation.url}" + (" - missing from PR" if missing else ""),
        missing,
    )


def describe(
    annotations: Sequence[Annotation], pr_body: str | None = None
) -> tuple[Note, ...]:
    """List a note per unsatisfied dependency in `annotations` for a listing.

    A dependency PR url is flagged when `pr_body` is given and lacks it.
    """
    return tuple(_note(a, pr_body) for a in annotations if not a.satisfied)


def holds(links: Sequence[Link], status_by_tool: StatusByTool) -> frozenset[CommitKey]:
    """Return the dependents with a dependency that is not yet on a PR."""
    return frozenset(
        link.dependent
        for link in links
        if (
            status := status_by_tool.get(link.dependency_tool, {}).get(
                (link.dependency_subject, link.dependency_date)
            )
        )
        is not None
        and status.stage in HELD_STAGES
    )


def order_targets(names: Sequence[str], links: Sequence[Link]) -> list[str]:
    """Sort `names` so each dependency's repo precedes its dependent's, else keep order."""
    needs = {
        name: {
            link.dependency_tool
            for link in links
            if link.dependent_tool == name
            and link.dependency_tool in names
            and link.dependency_tool != name
        }
        for name in names
    }
    ordered: list[str] = []
    while len(ordered) < len(names):
        ready = next(
            (
                name
                for name in names
                if name not in ordered and needs[name] <= set(ordered)
            ),
            None,
        )
        if ready is None:
            raise LinkCycleError("these links make repos depend on each other")
        ordered.append(ready)
    return ordered


def resolve_commits(
    values: Sequence[str],
    commits_by_tool: Mapping[str, Sequence[Commit]],
    rewritten: Mapping[str, tuple[str, Commit]] | None = None,
) -> dict[str, list[str]]:
    """Assign each sha prefix in `values` to the one repo whose local commits it names.

    `rewritten` maps an unknown value to the repo and current commit that replaced it.
    Raises `SelectionError` listing every prefix that is unknown or ambiguous.
    """
    resolved: dict[str, list[str]] = {}
    errors: list[str] = []
    for value in dict.fromkeys(values):
        prefix = value.strip().lower()
        matches = {
            tool: [c for c in commits if c.sha.startswith(prefix)]
            for tool, commits in commits_by_tool.items()
        }
        matches = {tool: found for tool, found in matches.items() if found}
        if not prefix:
            errors.append("empty commit value")
        elif not matches and value in (rewritten or {}):
            tool, commit = (rewritten or {})[value]
            errors.append(
                f"{value}: rewritten - {tool} main now has {commit.sha[:7]} {commit.subject}"
            )
        elif not matches:
            errors.append(f"{value}: not a local commit ahead of the base branch")
        elif len(matches) > 1:
            errors.append(f"{value}: ambiguous across {', '.join(matches)}")
        else:
            ((tool, found),) = matches.items()
            if len(found) > 1:
                listed = ", ".join(f"{c.sha} {c.subject}" for c in found)
                errors.append(f"{value}: ambiguous ({listed})")
            else:
                resolved.setdefault(tool, []).append(value)
    if errors:
        raise SelectionError(errors)
    return resolved
