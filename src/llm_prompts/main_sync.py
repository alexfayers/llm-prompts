"""Sync a local main that diverged from its upstream onto the upstream."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import suppress
from functools import cache
from itertools import takewhile
from pathlib import Path
from typing import Literal, NamedTuple

from .network import run_with_retries
from .setup import GIT_TIMEOUT
from .squash_subject import squash_pr_number

_Identity = tuple[str, str]
GIT_TIMED_OUT = 124
PRE_SYNC_REF = "refs/llm-prompts/pre-sync"
EARLIER_MAINS_REF = "refs/llm-prompts/earlier-mains"
_EARLIER_MAINS_IDENTITY = {
    f"GIT_{role}_{field}": value
    for role in ("AUTHOR", "COMMITTER")
    for field, value in (("NAME", "llm-prompts"), ("EMAIL", "llm-prompts@localhost"))
}
_OPERATION_MARKERS = (
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
    ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
)
_FIXUP_PREFIXES = ("fixup! ", "squash! ", "amend! ")
_NETWORK_COMMANDS = frozenset({"fetch", "pull", "ls-remote"})


class SkippedCopy(NamedTuple):
    """A copy of a worktree branch that could not replay, named by the branch's first commit."""

    first: str
    reason: str


class SyncResult(NamedTuple):
    """How a diverged local main was brought onto its upstream."""

    mode: Literal["reset", "rebased", "squash-synced", "rebuilt", "failed"]
    replayed: int = 0
    detail: str = ""
    skipped: tuple[SkippedCopy, ...] = ()


class _OpenPrCommit(NamedTuple):
    """A commit of an open pull request and the head it belongs to."""

    sha: str
    head: str


class Squash(NamedTuple):
    """Everything a branch changes on ``floor``, to commit as one commit with the author and message of ``first``."""

    tip: str
    floor: str
    first: str


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
    run = run_with_retries if args[0] in _NETWORK_COMMANDS else subprocess.run
    try:
        return run(
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
    try:
        _remember_main(repo, "HEAD")
    except _Bail as bail:
        return SyncResult("failed", detail=f"main left untouched: {bail}")
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


class _ReplayConflict(_Bail):
    """A local commit conflicts with the upstream it is replayed onto."""


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
    return _fetch_missing(
        repo,
        remote,
        {
            ref: sha
            for sha, ref in (
                line.split()
                for line in _read(repo, "ls-remote", remote, *refs).splitlines()
            )
        },
    )


def _fetch_missing(repo: Path, remote: str, heads: dict[str, str]) -> dict[str, str]:
    if not heads:
        return heads
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
) -> tuple[list[str], dict[_Identity, list[tuple[str, ...]]]]:
    """Return the accepted PR heads and, per commit identity, each PR's commits from that one to its head."""
    accepted: list[str] = []
    pr_commits: dict[_Identity, list[tuple[str, ...]]] = {}
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
        rows = [
            line.partition("\t")
            for line in reversed(
                _read(
                    repo,
                    "log",
                    "--no-merges",
                    "--format=%H%x09%at%x09%s",
                    f"{up}^..{head}",
                ).splitlines()
            )
        ]
        chain = tuple(sha for sha, _, _ in rows)
        for index, (_, _, rest) in enumerate(rows):
            pr_commits.setdefault(_identity(rest), []).append(chain[index:])
    return accepted, pr_commits


def _open_pr_commits(repo: Path, remote: str) -> dict[_Identity, list[_OpenPrCommit]]:
    """Map each commit of an open pull request, by identity, to its versions in each head.

    A pull request is open when its head is also the tip of a branch on the remote.
    """
    listing = [
        line.split()
        for line in _read(
            repo, "ls-remote", remote, "refs/pull/*/head", "refs/heads/*"
        ).splitlines()
    ]
    branch_tips = {sha for sha, ref in listing if ref.startswith("refs/heads/")}
    heads = _fetch_missing(
        repo,
        remote,
        {
            ref: sha
            for sha, ref in listing
            if ref.startswith("refs/pull/") and sha in branch_tips
        },
    )
    commits: dict[_Identity, list[_OpenPrCommit]] = {}
    for head in heads.values():
        for line in _read(
            repo, "log", "--no-merges", "--format=%H%x09%at%x09%s", f"@{{u}}..{head}"
        ).splitlines():
            sha, _, rest = line.partition("\t")
            commits.setdefault(_identity(rest), []).append(_OpenPrCommit(sha, head))
    return commits


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
    repo: Path, commit: LocalCommit, pr_commits: dict[_Identity, list[tuple[str, ...]]]
) -> bool:
    return any(
        _same_change(repo, commit, chain)
        for chain in pr_commits.get((commit.authored_at, commit.subject), ())
    )


def _same_change(repo: Path, commit: LocalCommit, chain: tuple[str, ...]) -> bool:
    """Return whether applying the pull request's commits from the matching one, in order, reaches the commit's tree at some step."""
    wanted = _read(repo, "rev-parse", f"{commit.sha}^{{tree}}").strip()
    ours = f"{commit.sha}^"
    for index, pr in enumerate(chain):
        try:
            tree = _merge_tree(repo, f"{pr}^", ours, pr)
        except _Conflict:
            return False
        if tree == wanted:
            return True
        if index + 1 < len(chain):
            ours = _commit_as(repo, tree, ours, pr)
    return False


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


def _reuse_resolutions(repo: Path, base: str, ours: str, theirs: str) -> str | None:
    """Merge in a throwaway worktree where git rerere records the conflicts and applies earlier hand resolutions.

    Returns:
        The merged tree, or None while any conflict has no recorded resolution.
    """
    change = _read(
        repo, "commit-tree", f"{theirs}^{{tree}}", "-p", base, "-m", "replay"
    ).strip()
    with tempfile.TemporaryDirectory() as parent:
        work = Path(parent) / "work"
        _read(repo, "worktree", "add", "--quiet", "--detach", str(work), ours)
        try:
            pick = run_git(
                work,
                "-c",
                "rerere.enabled=true",
                "-c",
                "rerere.autoUpdate=true",
                "cherry-pick",
                "--no-commit",
                change,
            )
            if (
                pick.returncode not in (0, 1)
                or run_git(work, "ls-files", "--unmerged").stdout
            ):
                return None
            return _read(work, "write-tree").strip()
        finally:
            run_git(repo, "worktree", "remove", "--force", str(work))


def replays_to(repo: Path, parent: str, squash: Squash, result: str) -> bool:
    """Return whether replaying ``squash`` on ``parent``, reusing recorded hand resolutions, gives ``result``'s tree."""
    try:
        tree: str | None
        try:
            tree = _merge_tree(repo, squash.floor, parent, squash.tip)
        except _Conflict:
            tree = _reuse_resolutions(repo, squash.floor, parent, squash.tip)
    except _Bail:
        return False
    return tree == _read(repo, "rev-parse", f"{result}^{{tree}}").strip()


def _replay(
    repo: Path, tip: str, commit: LocalCommit, squash: Squash | None = None
) -> str:
    floor, changes = (
        (squash.floor, squash.tip) if squash else (f"{commit.sha}^", commit.sha)
    )
    try:
        tree = _merge_tree(repo, floor, tip, changes)
    except _Conflict as conflict:
        resolved = _reuse_resolutions(repo, floor, tip, changes)
        if resolved is None:
            raise _ReplayConflict(
                f"local commit {commit.sha[:12]} ({commit.subject}) conflicts with upstream"
                f" in {', '.join(conflict.paths)}"
            ) from conflict
        tree = resolved
    return _commit_as(repo, tree, tip, squash.first if squash else commit.sha)


def _holds_every_change(repo: Path, commit: LocalCommit, head: str) -> bool:
    try:
        tree = _merge_tree(repo, f"{commit.sha}^", head, commit.sha)
    except _Conflict:
        return False
    return tree == _read(repo, "rev-parse", f"{head}^{{tree}}").strip()


def _replay_or_open_pr_version(
    repo: Path,
    tip: str,
    commit: LocalCommit,
    open_pr_commits: Callable[[], dict[_Identity, list[_OpenPrCommit]]],
) -> str:
    try:
        return _replay(repo, tip, commit)
    except _ReplayConflict:
        for pr_commit in open_pr_commits().get(
            (commit.authored_at, commit.subject), ()
        ):
            if _holds_every_change(repo, commit, pr_commit.head):
                with suppress(_ReplayConflict):
                    return _replay(repo, tip, commit._replace(sha=pr_commit.sha))
        raise


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
    open_pr_commits = cache(lambda: _open_pr_commits(repo, remote))
    local_shas = {commit.sha for commit in local}
    for commit in replayed:
        tip = _replay_or_open_pr_version(
            repo, tip, commit, open_pr_commits if commit.sha in local_shas else dict
        )
    reset = run_git(repo, "reset", "--keep", tip)
    if reset.returncode != 0:
        return SyncResult("failed", detail=reset.stderr.strip())
    return SyncResult("squash-synced", replayed=len(replayed))


def _squash_sync(repo: Path) -> SyncResult:
    try:
        return _build_sync(repo)
    except _Bail as bail:
        return SyncResult("failed", detail=f"squash sync stopped: {bail}")


def _remember_main(repo: Path, head: str) -> None:
    """Keep ``head`` and every earlier main reachable from ``EARLIER_MAINS_REF``."""
    earlier = run_git(repo, "rev-parse", "--verify", "--quiet", EARLIER_MAINS_REF)
    parents = [
        "-p",
        head,
        *(["-p", EARLIER_MAINS_REF] if earlier.returncode == 0 else []),
    ]
    kept = _read(
        repo,
        "commit-tree",
        f"{head}^{{tree}}",
        *parents,
        "-m",
        "llm-prompts: earlier main",
        env=_EARLIER_MAINS_IDENTITY,
    ).strip()
    _read(repo, "update-ref", EARLIER_MAINS_REF, kept)


def rebuild_local(
    repo: Path,
    base: str,
    substitutions: Mapping[str, Squash],
    drops: Collection[str],
    copies: Mapping[str, str],
    additions: Sequence[Squash],
) -> SyncResult:
    """Move local main onto ``base`` with its local commits replayed, some swapped for squashes or dropped, plus new squashes.

    Args:
        repo: The local clone, on its main branch.
        base: The ref local commits are counted from.
        substitutions: Local commit sha to the squash that replaces it.
        drops: Local commit shas to leave out.
        copies: Local commit sha of each known copy of a worktree branch to the first commit of that branch. A copy that conflicts is skipped.
        additions: Squashes to replay on top, in order. One that conflicts is skipped.

    Returns:
        ``rebuilt`` with the count of replayed commits and the skipped copies, or a failed result that leaves main untouched.
    """
    if (operation := _operation_in_progress(repo)) is not None:
        return SyncResult("failed", detail=f"a {operation} is in progress")
    try:
        branch = _read(repo, "symbolic-ref", "--short", "-q", "HEAD").strip()
        if branch != "main":
            raise _Bail(f"{repo} has {branch or 'no branch'} checked out, not main")
        merge_base = _read(repo, "merge-base", "HEAD", base).strip()
        head = _read(repo, "rev-parse", "HEAD").strip()
        tip = _read(repo, "rev-parse", base).strip()
        replayed = 0
        skipped: list[SkippedCopy] = []
        untouched = tip == merge_base
        for commit in _local_commits(repo, merge_base):
            squash = substitutions.get(commit.sha)
            dropped = commit.sha in drops
            if squash is None and not dropped and untouched:
                tip = commit.sha
                continue
            untouched = False
            if dropped:
                continue
            try:
                tip = _replay(repo, tip, commit, squash)
            except _ReplayConflict as conflict:
                if commit.sha not in copies:
                    raise
                skipped.append(SkippedCopy(copies[commit.sha], str(conflict)))
                continue
            replayed += 1
        for squash in additions:
            subject = _read(repo, "log", "-1", "--format=%s", squash.first).strip()
            try:
                tip = _replay(repo, tip, LocalCommit(squash.first, "", subject), squash)
            except _ReplayConflict as conflict:
                skipped.append(SkippedCopy(squash.first, str(conflict)))
                continue
            replayed += 1
        if tip == head:
            return SyncResult("rebuilt", skipped=tuple(skipped))
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
        _remember_main(repo, head)
        reset = run_git(repo, "reset", "--keep", tip)
    except _Bail as bail:
        return SyncResult("failed", detail=f"main left untouched: {bail}")
    if reset.returncode != 0:
        return SyncResult("failed", detail=reset.stderr.strip())
    return SyncResult("rebuilt", replayed=replayed, skipped=tuple(skipped))
