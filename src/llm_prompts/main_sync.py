"""Sync a local main that diverged from its upstream onto the upstream."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Sequence
from itertools import takewhile
from pathlib import Path
from typing import Literal, NamedTuple

from .setup import GIT_TIMEOUT
from .squash_subject import squash_pr_number

_Identity = tuple[str, str]
GIT_TIMED_OUT = 124
PRE_SYNC_REF = "refs/llm-prompts/pre-sync"
_OPERATION_MARKERS = (
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
    ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
)
_FIXUP_PREFIXES = ("fixup! ", "squash! ", "amend! ")


class SyncResult(NamedTuple):
    """How a diverged local main was brought onto its upstream."""

    mode: Literal["reset", "rebased", "squash-synced", "failed"]
    replayed: int = 0
    detail: str = ""


class LocalCommit(NamedTuple):
    """A local commit, identified across rewrites by author time and subject."""

    sha: str
    authored_at: str
    subject: str


def run_git(
    repo: Path,
    *args: str,
    input: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = ["git", "-C", str(repo), *args]
    try:
        return subprocess.run(
            argv,
            input=input,
            env={**os.environ, **env} if env else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            argv, GIT_TIMED_OUT, "", f"git {args[0]} timed out"
        )


def _operation_in_progress(repo: Path) -> str | None:
    paths = run_git(
        repo,
        "rev-parse",
        *(arg for marker, _ in _OPERATION_MARKERS for arg in ("--git-path", marker)),
    ).stdout.splitlines()
    return next(
        (
            operation
            for (_, operation), path in zip(_OPERATION_MARKERS, paths, strict=False)
            if (repo / path).exists()
        ),
        None,
    )


def _recovery(repo: Path) -> str:
    heads = run_git(repo, "rev-parse", "HEAD", PRE_SYNC_REF).stdout.split()
    operation = _operation_in_progress(repo)
    if operation is None and len(heads) == 2 and heads[0] == heads[1]:
        return "; nothing changed"
    undo = f"git reset --keep {PRE_SYNC_REF}"
    if operation == "rebase":
        undo = f"git rebase --abort && {undo}"
    return f"; recover with: cd {shlex.quote(str(repo))} && {undo}"


def _failed(repo: Path, detail: str) -> SyncResult:
    return SyncResult("failed", detail=detail + _recovery(repo))


def sync_diverged(repo: Path) -> SyncResult:
    """Bring a local main whose fast-forward pull failed onto its upstream.

    Args:
        repo: The local clone.

    Returns:
        How the clone was synced, or a failed result that leaves it untouched.
    """
    if (operation := _operation_in_progress(repo)) is not None:
        detail = f"a {operation} is in progress; finish or abort it first"
        if (
            run_git(repo, "rev-parse", "--verify", "--quiet", PRE_SYNC_REF).returncode
            == 0
        ):
            detail += f"; the state before the last sync is saved as {PRE_SYNC_REF}"
        return SyncResult("failed", detail=detail)
    identical = run_git(repo, "diff", "--quiet", "HEAD", "@{u}").returncode == 0
    saved = run_git(
        repo,
        "update-ref",
        "--create-reflog",
        "-m",
        "llm-prompts: pre-sync",
        PRE_SYNC_REF,
        "HEAD",
    )
    if saved.returncode != 0:
        return SyncResult("failed", detail=saved.stderr.strip())
    if identical:
        reset = run_git(repo, "reset", "--soft", "@{u}")
        if reset.returncode != 0:
            return _failed(repo, reset.stderr.strip())
        return SyncResult("reset")
    rebase = run_git(repo, "rebase", "--quiet", "@{u}")
    if rebase.returncode == 0:
        return SyncResult("rebased")
    abort = run_git(repo, "rebase", "--abort")
    if rebase.returncode == GIT_TIMED_OUT:
        return _failed(repo, rebase.stderr.strip())
    if abort.returncode != 0:
        return _failed(repo, abort.stderr.strip())
    synced = _squash_sync(repo)
    return _failed(repo, synced.detail) if synced.mode == "failed" else synced


class _Bail(Exception):
    """A step could not prove the sync safe, so nothing may change; the message says why."""


class _Conflict(_Bail):
    """A three-way merge left conflicts in these paths."""

    def __init__(self, paths: list[str]) -> None:
        super().__init__(f"conflicts in {', '.join(paths)}")
        self.paths = paths


def _read(
    repo: Path,
    *args: str,
    input: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    result = run_git(repo, *args, input=input, env=env)
    if result.returncode != 0:
        raise _Bail(
            result.stderr.strip() or f"git {' '.join(args)} exited {result.returncode}"
        )
    return result.stdout


def _identity(line: str) -> _Identity:
    authored_at, _, subject = line.partition("\t")
    return authored_at, subject


def _local_commits(repo: Path, merge_base: str) -> list[LocalCommit]:
    commits: list[LocalCommit] = []
    for line in _read(
        repo,
        "log",
        "--reverse",
        "--format=%H%x09%P%x09%at%x09%s",
        f"{merge_base}..HEAD",
    ).splitlines():
        sha, parents, authored_at, subject = line.split("\t", 3)
        if len(parents.split()) > 1:
            raise _Bail(f"local merge commit {sha}")
        commits.append(LocalCommit(sha, authored_at, subject))
    return commits


def _cherry(repo: Path, upstream: str, head: str, mark: str) -> list[str]:
    return [
        line[2:]
        for line in _read(repo, "cherry", upstream, head).splitlines()
        if line.startswith(f"{mark} ")
    ]


def _pull_heads(repo: Path, remote: str, refs: Sequence[str]) -> dict[str, str]:
    heads = {
        ref: sha
        for sha, ref in (
            line.split()
            for line in _read(repo, "ls-remote", remote, *refs).splitlines()
        )
    }
    checked = _read(
        repo,
        "cat-file",
        "--batch-check",
        input="".join(f"{sha}\n" for sha in heads.values()),
    ).splitlines()
    missing = [
        ref
        for ref, line in zip(heads, checked, strict=True)
        if line.endswith(" missing")
    ]
    if missing:
        _read(repo, "fetch", "--quiet", remote, *missing)
    return heads


def _record(commits: dict[_Identity, str], identity: _Identity, sha: str) -> None:
    if commits.setdefault(identity, sha) != sha:
        raise _Bail(
            f"two pull request commits share author time and subject: {identity[1]}"
        )


def _upstream_pr_numbers(repo: Path) -> dict[str, int]:
    ups = _cherry(repo, "HEAD", "@{u}", "+")
    if not ups:
        return {}
    numbers: dict[str, int] = {}
    for line in _read(
        repo, "log", "--no-walk=unsorted", "--format=%H%x09%s", *ups
    ).splitlines():
        sha, _, subject = line.partition("\t")
        if (number := squash_pr_number(subject)) is not None:
            numbers[sha] = number
    return numbers


def _merged_pr_commits(
    repo: Path, remote: str
) -> tuple[list[str], dict[_Identity, str]]:
    accepted: list[str] = []
    pr_commits: dict[_Identity, str] = {}
    numbers = _upstream_pr_numbers(repo)
    if not numbers:
        return accepted, pr_commits
    heads = _pull_heads(
        repo, remote, [f"refs/pull/{number}/head" for number in numbers.values()]
    )
    pairs = [
        (up, heads[ref])
        for up, number in numbers.items()
        if (ref := f"refs/pull/{number}/head") in heads
    ]
    if not pairs:
        return accepted, pr_commits
    trees = _read(
        repo, "rev-parse", *(f"{sha}^{{tree}}" for pair in pairs for sha in pair)
    ).split()
    for (up, head), up_tree, head_tree in zip(
        pairs, trees[0::2], trees[1::2], strict=True
    ):
        if up_tree != head_tree:
            continue
        accepted.append(head)
        for line in _read(
            repo, "log", "--no-merges", "--format=%H%x09%at%x09%s", f"{up}^..{head}"
        ).splitlines():
            sha, _, rest = line.partition("\t")
            _record(pr_commits, _identity(rest), sha)
    return accepted, pr_commits


def _merge_tree(repo: Path, base: str, ours: str, theirs: str) -> str:
    result = run_git(
        repo,
        "merge-tree",
        "--write-tree",
        "--name-only",
        f"--merge-base={base}",
        ours,
        theirs,
    )
    if result.returncode == 0:
        return result.stdout.splitlines()[0]
    if result.returncode == 1:
        raise _Conflict(list(takewhile(bool, result.stdout.splitlines()[1:])))
    raise _Bail(result.stderr.strip() or f"git merge-tree exited {result.returncode}")


def _equivalent(
    repo: Path, commit: LocalCommit, pr_commits: dict[_Identity, str]
) -> bool:
    pr = pr_commits.get((commit.authored_at, commit.subject))
    if pr is None:
        return False
    try:
        tree = _merge_tree(repo, f"{pr}^", f"{commit.sha}^", pr)
    except _Conflict:
        return False
    return tree == _read(repo, "rev-parse", f"{commit.sha}^{{tree}}").strip()


def _commit_as(repo: Path, tree: str, parent: str, source: str) -> str:
    name, email, date, message = _read(
        repo, "log", "-1", "--format=%an%x00%ae%x00%aI%x00%B", source
    ).split("\x00", 3)
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": date}
    return _read(
        repo,
        "commit-tree",
        tree,
        "-p",
        parent,
        "-F",
        "-",
        input=message.rstrip("\n") + "\n",
        env=env,
    ).strip()


def _replay(repo: Path, tip: str, commit: LocalCommit) -> str:
    try:
        tree = _merge_tree(repo, f"{commit.sha}^", tip, commit.sha)
    except _Conflict as conflict:
        raise _Bail(
            f"local commit {commit.sha[:12]} ({commit.subject}) conflicts with upstream"
            f" in {', '.join(conflict.paths)}"
        ) from conflict
    return _commit_as(repo, tree, tip, commit.sha)


def _fixup_target(subject: str) -> str | None:
    target = subject
    while target.startswith(_FIXUP_PREFIXES):
        target = target.partition("! ")[2]
    return target if target != subject else None


def _autosquash(repo: Path, commits: list[LocalCommit]) -> list[LocalCommit]:
    grouped: list[LocalCommit] = []
    for commit in commits:
        target = _fixup_target(commit.subject)
        index = next(
            (i for i in reversed(range(len(grouped))) if grouped[i].subject == target),
            None,
        )
        if index is None:
            grouped.append(commit)
            continue
        base = grouped[index]
        try:
            tree = _merge_tree(repo, f"{commit.sha}^", base.sha, commit.sha)
        except _Conflict:
            grouped.append(commit)
        else:
            grouped[index] = base._replace(
                sha=_commit_as(repo, tree, f"{base.sha}^", base.sha)
            )
    return grouped


def _build_sync(repo: Path) -> SyncResult:
    remote = _read(repo, "rev-parse", "--abbrev-ref", "@{u}").strip().partition("/")[0]
    merge_base = _read(repo, "merge-base", "HEAD", "@{u}").strip()
    local = _local_commits(repo, merge_base)
    heads, pr_commits = _merged_pr_commits(repo, remote)
    covered = {
        *_cherry(repo, "@{u}", "HEAD", "-"),
        *(sha for head in heads for sha in _cherry(repo, head, "HEAD", "-")),
    }
    replayed = [
        commit
        for commit in _autosquash(
            repo, [commit for commit in local if commit.sha not in covered]
        )
        if not _equivalent(repo, commit, pr_commits)
    ]
    tip = _read(repo, "rev-parse", "@{u}").strip()
    for commit in replayed:
        tip = _replay(repo, tip, commit)
    reset = run_git(repo, "reset", "--keep", tip)
    if reset.returncode != 0:
        return SyncResult("failed", detail=reset.stderr.strip())
    return SyncResult("squash-synced", replayed=len(replayed))


def _squash_sync(repo: Path) -> SyncResult:
    try:
        return _build_sync(repo)
    except _Bail as bail:
        return SyncResult("failed", detail=f"squash sync stopped: {bail}")
