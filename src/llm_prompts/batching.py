"""Pure decisions for grouping pending commits into managed batch branches.

All git/gh I/O lives in ``contribute.py``; this module only decides branch
names, commit ownership, and batch membership from data it is handed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from .contribute import Commit, Group, Inventory, Pr

BATCH_CAP = 5


class Match(NamedTuple):
    """How one branch's commits map onto local main's commits."""

    owned: dict[str, Commit]
    amended: frozenset[str]
    unmatched: tuple[Commit, ...]


class Batch(NamedTuple):
    """One managed batch branch and its remote state."""

    branch: str
    slug: str
    pr: Pr | None
    commits: tuple[Commit, ...]
    match: Match


class BatchPlan(NamedTuple):
    """A planned batch: its target branch and how to apply it."""

    branch: str
    slug: str
    pr: Pr | None
    groups: tuple[Group, ...]
    mode: Literal["append", "rebuild", "new"]


class SelectionError(ValueError):
    """Raised when requested commits cannot be selected; carries one line per problem."""

    def __init__(self, lines: list[str]) -> None:
        super().__init__("\n".join(lines))
        self.lines = lines


def batch_branch(login: str, slug: str) -> str:
    """Build the ``<login>/contribute/<slug>`` managed batch branch name."""
    return f"{login}/contribute/{slug}"


def is_managed(branch: str, login: str) -> bool:
    """Return whether ``branch`` is a managed batch branch for ``login``."""
    return branch.startswith(f"{login}/contribute/")


def match_commits(
    branch_commits: tuple[Commit, ...], main_commits: tuple[Commit, ...]
) -> Match:
    """Match a branch's commits onto main commits by patch-id, else unique subject."""
    by_patch_id: dict[str, Commit] = {}
    subject_counts: dict[str, int] = {}
    by_subject: dict[str, Commit] = {}
    for commit in main_commits:
        if commit.patch_id:
            by_patch_id[commit.patch_id] = commit
        subject_counts[commit.subject] = subject_counts.get(commit.subject, 0) + 1
        by_subject[commit.subject] = commit

    owned: dict[str, Commit] = {}
    amended: set[str] = set()
    unmatched: list[Commit] = []
    for commit in branch_commits:
        main_commit = by_patch_id.get(commit.patch_id) if commit.patch_id else None
        if main_commit is not None:
            owned[commit.sha] = main_commit
        elif subject_counts.get(commit.subject) == 1:
            owned[commit.sha] = by_subject[commit.subject]
            amended.add(commit.sha)
        else:
            unmatched.append(commit)

    return Match(owned=owned, amended=frozenset(amended), unmatched=tuple(unmatched))


def _is_stale(batch: Batch) -> bool:
    """Return whether a batch's branch needs rebuilding rather than appending to."""
    return batch_status(batch) != "current"


def _owned_shas(batch: Batch) -> set[str]:
    """Return the main-commit shas `batch`'s branch already owns."""
    return {commit.sha for commit in batch.match.owned.values()}


def append_groups(plan: BatchPlan, batch: Batch) -> tuple[Group, ...]:
    """Return `plan`'s groups not already present on `batch`'s branch.

    An `append` plan's `groups` carries the batch's existing owned groups
    alongside newly appended ones; only the latter need cherry-picking onto
    the already-pushed branch.
    """
    owned_shas = _owned_shas(batch)
    return tuple(
        group
        for group in plan.groups
        if not ({commit.sha for commit in group.commits} & owned_shas)
    )


def _unique_slug(slug: str, used: set[str]) -> str:
    """Return `slug`, or `slug-N` if it collides with one already in `used`."""
    if slug not in used:
        return slug
    suffix = 2
    while f"{slug}-{suffix}" in used:
        suffix += 1
    return f"{slug}-{suffix}"


def plan_batches(
    groups: Sequence[Group],
    inv: Inventory,
    login: str,
    selected: frozenset[str] | None = None,
) -> list[BatchPlan]:
    """Bucket `groups` (the full pending backlog, main order) into batch plans.

    Groups already owned by an existing batch stay with it; the rest append to
    the newest open batch while it has room, else start new batches capped at
    `BATCH_CAP`. A batch with an amended or unmatched owned commit, or one
    missing a commit from an owned group, is rebuilt rather than appended to,
    even with no new groups. A current batch with no new groups gets no plan.
    """
    owned_by: dict[str, int] = {
        commit.sha: index
        for index, batch in enumerate(inv.batches)
        for commit in batch.match.owned.values()
    }

    existing: list[list[Group]] = [[] for _ in inv.batches]
    incomplete = [False for _ in inv.batches]
    pending: list[Group] = []
    for group in groups:
        indices = {
            owned_by[commit.sha] for commit in group.commits if commit.sha in owned_by
        }
        if indices:
            index = next(iter(indices))
            existing[index].append(group)
            group_shas = {commit.sha for commit in group.commits}
            if not group_shas <= _owned_shas(inv.batches[index]):
                incomplete[index] = True
        elif selected is None or selected & {commit.sha for commit in group.commits}:
            pending.append(group)

    used_slugs = {batch.slug for batch in inv.batches} | inv.past_slugs
    plans: list[BatchPlan] = []
    newest_index = len(inv.batches) - 1

    for index, batch in enumerate(inv.batches):
        batch_groups = existing[index]
        appended: list[Group] = []
        stale = _is_stale(batch) or incomplete[index]
        owns_selected = selected is None or any(
            commit.sha in selected for group in batch_groups for commit in group.commits
        )
        if index == newest_index and (owns_selected or not stale):
            room = max(0, BATCH_CAP - len(batch_groups))
            appended, pending = pending[:room], pending[room:]
        if not appended and not (stale and owns_selected):
            continue
        mode: Literal["append", "rebuild", "new"] = "rebuild" if stale else "append"
        plans.append(
            BatchPlan(
                branch=batch.branch,
                slug=batch.slug,
                pr=batch.pr,
                groups=tuple(batch_groups + appended),
                mode=mode,
            )
        )

    while pending:
        chunk, pending = pending[:BATCH_CAP], pending[BATCH_CAP:]
        slug = _unique_slug(chunk[0].slug, used_slugs)
        used_slugs.add(slug)
        plans.append(
            BatchPlan(
                branch=batch_branch(login, slug),
                slug=slug,
                pr=None,
                groups=tuple(chunk),
                mode="new",
            )
        )

    return plans


def pending_plans(
    groups: Sequence[Group],
    inv: Inventory,
    login: str,
    selected: frozenset[str] | None = None,
) -> list[BatchPlan]:
    """Plan the batches for every group still pending, skipping regressed batches."""
    pending = [
        group
        for group in groups
        if not group.problems
        and not any(
            commit.sha in inv.done or commit.sha in inv.unmanaged
            for commit in group.commits
        )
    ]
    regressed = {
        batch.branch for batch in inv.batches if batch_status(batch) == "regressed"
    }
    return [
        plan
        for plan in plan_batches(pending, inv, login, selected)
        if plan.branch not in regressed
    ]


def select_groups(
    requested: Sequence[str], groups: Sequence[Group], inv: Inventory
) -> frozenset[str]:
    """Resolve `requested` sha prefixes to the shas of their whole groups.

    Raises `SelectionError` listing every prefix that is unknown, ambiguous,
    outside any group, or in a group with problems.
    """
    group_of = {commit.sha: group for group in groups for commit in group.commits}
    selected: set[str] = set()
    errors: list[str] = []
    for value in dict.fromkeys(requested):
        prefix = value.strip().lower()
        matches = [c for c in inv.commits if c.sha.startswith(prefix)]
        if not prefix:
            errors.append("empty commit value")
        elif not matches:
            errors.append(f"{value}: not a local commit ahead of the base branch")
        elif len(matches) > 1:
            listed = ", ".join(f"{c.sha} {c.subject}" for c in matches)
            errors.append(f"{value}: ambiguous ({listed})")
        elif matches[0].sha not in group_of:
            errors.append(f"{value}: touches no prompt sources")
        elif group_of[matches[0].sha].problems:
            errors.append(f"{value}: {', '.join(group_of[matches[0].sha].problems)}")
        else:
            selected.update(c.sha for c in group_of[matches[0].sha].commits)
    if errors:
        raise SelectionError(errors)
    return frozenset(selected)


def batch_status(batch: Batch) -> Literal["current", "stale", "regressed"]:
    """Label a batch from its branch-to-main commit match."""
    if batch.match.unmatched:
        return "regressed"
    if batch.match.amended:
        return "stale"
    return "current"


def regression_warning(batches: tuple[Batch, ...]) -> str | None:
    """Warn if a managed batch holds content local main no longer has."""
    lines = [
        f"  {batch.branch}: git cherry-pick "
        + " ".join(commit.sha for commit in batch.match.unmatched)
        for batch in batches
        if batch_status(batch) == "regressed"
    ]
    if not lines:
        return None
    return (
        "warning: these batches hold content local main no longer has, so "
        "syncing would drop it - recover with the commands below, then re-run "
        "sync --apply:\n" + "\n".join(lines)
    )
