"""Pure grouping of pending commits into review stages, and their rendering.

All git/gh I/O lives in ``contribute.py``; this module only decides each
commit's stage and lays the result out from data it is handed.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Literal, NamedTuple, get_args

from .batching import append_groups, batch_status
from .colors import Color, paint

if TYPE_CHECKING:
    from .batching import Batch, BatchPlan
    from .contribute import Commit, Group, Inventory, OpenPr
    from .links import Note

Stage = Literal[
    "needs sync",
    "local only",
    "needs PR",
    "changes requested",
    "draft",
    "waiting for review",
    "approved",
    "merged",
]
STAGES: tuple[Stage, ...] = get_args(Stage)

_MANUAL_TAG = "[manual PR]"
_PR_ONLY = "not on main"
_REVIEW_STAGES: dict[str, Stage] = {
    "draft": "draft",
    "changes requested": "changes requested",
    "approved": "approved",
    "needs review": "waiting for review",
}
_STAGE_COLORS: dict[Stage, Color] = {
    "needs sync": "red",
    "local only": "cyan",
    "needs PR": "yellow",
    "changes requested": "red",
    "draft": "grey",
    "waiting for review": "yellow",
    "approved": "green",
    "merged": "grey",
}


class Entry(NamedTuple):
    """One heading in a stage: its tags, branch and commit lines with suffixes."""

    stage: Stage
    tags: tuple[str, ...]
    branch: str
    lines: tuple[tuple[Commit, str], ...]


def review_state(pr: OpenPr | None) -> str:
    """Label an open PR's review state; a draft outranks its review decision."""
    if pr is None:
        return "needs review"
    if pr.is_draft:
        return "draft"
    return {"CHANGES_REQUESTED": "changes requested", "APPROVED": "approved"}.get(
        pr.review_decision, "needs review"
    )


def _pr_tag(number: int, state: str, stage: Stage) -> str:
    return f"[#{number}]" if state == stage else f"[#{number} - {state}]"


def _commit_lines(
    commits: Sequence[Commit], suffixes: dict[str, str] | None = None
) -> tuple[tuple[Commit, str], ...]:
    return tuple((commit, (suffixes or {}).get(commit.sha, "")) for commit in commits)


def _batch_entry(
    batch: Batch,
    plan: BatchPlan | None,
    open_by_number: dict[int, OpenPr],
) -> Entry:
    adds = (
        sum(len(group.commits) for group in append_groups(plan, batch))
        if plan is not None
        else 0
    )
    regressed = batch_status(batch) == "regressed"
    rebuild = plan is not None and plan.mode == "rebuild"
    tags = [f"[adds {adds}]"] if adds > 0 else []
    if regressed:
        tags.append("[regressed]")
    elif rebuild:
        tags.append("[stale]")
    review = "needs review"
    if batch.pr is not None:
        review = review_state(open_by_number.get(batch.pr.number))

    stage: Stage
    if regressed or rebuild:
        stage = "needs sync"
    elif plan is not None and plan.mode == "append":
        stage = "local only"
    elif plan is None and batch.pr is None:
        stage = "needs PR"
    else:
        stage = _REVIEW_STAGES[review]
    if batch.pr is not None:
        tags.append(_pr_tag(batch.pr.number, review, stage))

    commits = (
        [commit for group in plan.groups for commit in group.commits]
        if plan is not None
        else [batch.match.owned.get(commit.sha, commit) for commit in batch.commits]
    )
    return Entry(stage, tuple(tags), batch.branch, _commit_lines(commits))


def classify(
    commits: Sequence[Commit],
    groups: Sequence[Group],
    plans: Sequence[BatchPlan],
    inv: Inventory,
    open_prs: Sequence[OpenPr],
    pr_by_sha: dict[str, OpenPr],
    code_only: Collection[str],
    pr_only: dict[int, tuple[Commit, ...]],
) -> tuple[list[Entry], list[Group]]:
    """Sort pending commits into stage entries; also return groups with unshown commits."""
    open_by_number = {open_pr.pr.number: open_pr for open_pr in open_prs}
    plans_by_branch = {plan.branch: plan for plan in plans}
    mixed = {
        commit.sha
        for group in groups
        if "mixed-scope" in group.problems
        for commit in group.commits
    }

    entries: list[Entry] = []
    bucket_index: dict[int | None, int] = {}
    for batch in inv.batches:
        entries.append(
            _batch_entry(batch, plans_by_branch.get(batch.branch), open_by_number)
        )
        if batch.pr is not None:
            bucket_index[batch.pr.number] = len(entries) - 1
    for plan in plans:
        if plan.mode == "new":
            entries.append(
                Entry(
                    "local only",
                    ("[new]",),
                    plan.branch,
                    _commit_lines([c for g in plan.groups for c in g.commits]),
                )
            )

    shown = {commit.sha for entry in entries for commit, _ in entry.lines}

    def add(key: int | None, new: Entry, commit: Commit, manual: bool) -> None:
        if key not in bucket_index:
            bucket_index[key] = len(entries)
            entries.append(new)
        entry = entries[bucket_index[key]]
        tags = entry.tags
        if manual and _MANUAL_TAG not in tags:
            tags = (*tags[:-1], _MANUAL_TAG, *tags[-1:])
        suffix = "rule + code" if commit.sha in mixed else "code" if manual else ""
        entries[bucket_index[key]] = entry._replace(
            tags=tags, lines=(*entry.lines, (commit, suffix))
        )
        shown.add(commit.sha)

    for commit in commits:
        if commit.sha in shown:
            continue
        manual = commit.sha in code_only or commit.sha in mixed
        if commit.sha in inv.done:
            number, branch = inv.merged_prs[commit.sha]
            add(
                number,
                Entry("merged", (_pr_tag(number, "merged", "merged"),), branch, ()),
                commit,
                manual,
            )
        elif commit.sha in inv.unmanaged or (manual and commit.sha in pr_by_sha):
            number = (
                inv.unmanaged[commit.sha].number
                if commit.sha in inv.unmanaged
                else pr_by_sha[commit.sha].pr.number
            )
            open_pr = open_by_number.get(number)
            state = review_state(open_pr)
            add(
                number,
                Entry(
                    _REVIEW_STAGES[state],
                    (_pr_tag(number, state, _REVIEW_STAGES[state]),),
                    open_pr.branch if open_pr else "",
                    (),
                ),
                commit,
                manual,
            )
        elif manual:
            add(None, Entry("needs PR", (_MANUAL_TAG,), "", ()), commit, manual)

    for number, missing in pr_only.items():
        if number in bucket_index:
            entry = entries[bucket_index[number]]
            entries[bucket_index[number]] = entry._replace(
                lines=(*entry.lines, *((commit, _PR_ONLY) for commit in missing))
            )

    problems = [
        group
        for group in groups
        if group.problems
        and "mixed-scope" not in group.problems
        and any(commit.sha not in shown for commit in group.commits)
    ]
    return entries, problems


def pr_only_warning(entries: Sequence[Entry]) -> str | None:
    """Warn if open PRs hold commits local main does not have."""
    lines = [
        f"  {entry.branch}: git cherry-pick "
        + " ".join(commit.sha for commit, suffix in entry.lines if suffix == _PR_ONLY)
        for entry in entries
        if any(suffix == _PR_ONLY for _, suffix in entry.lines)
    ]
    if not lines:
        return None
    return (
        "warning: these open PRs hold commits local main does not have - "
        "cherry-pick them onto main:\n" + "\n".join(lines)
    )


def render(
    entries: Sequence[Entry],
    problems: Sequence[Group],
    color: bool,
    notes: Mapping[str, Sequence[Note]] | None = None,
) -> list[str]:
    """Lay out entries under their stage headings, then any problem commits.

    `notes` maps commit shas to dependency lines shown under the commit.
    """
    if not entries and not problems:
        return ["  no pending changes"]
    lines: list[str] = []
    for stage in STAGES:
        stage_entries = [entry for entry in entries if entry.stage == stage]
        if not stage_entries:
            continue
        heading = f"{stage}:"
        lines.append(f"  {paint(heading, _STAGE_COLORS[stage]) if color else heading}")
        for entry in stage_entries:
            tags = [
                paint(tag, "yellow") if color and tag == _MANUAL_TAG else tag
                for tag in entry.tags
            ]
            lines.append(
                "    " + " ".join([*tags, entry.branch] if entry.branch else tags)
            )
            for commit, suffix in entry.lines:
                line = f"      {commit.sha[:7]} {commit.subject}"
                lines.append(f"{line} [{suffix}]" if suffix else line)
                for note in (notes or {}).get(commit.sha, ()):
                    text = f"-> {note.text}"
                    lines.append(
                        "        "
                        + (
                            paint(text, "red" if note.urgent else "yellow")
                            if color
                            else text
                        )
                    )
    if problems:
        lines.append("  problems:")
        for group in problems:
            lines.extend(
                f"    {commit.sha[:7]} {commit.subject} [{','.join(group.problems)}]"
                for commit in group.commits
            )
    return lines
