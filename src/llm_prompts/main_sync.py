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
from .setup import GIT_TIMEOUT, release_version
from .squash_subject import SQUASH_SUFFIX as _SQUASH_SUFFIX
from .squash_subject import squash_pr_number

_Identity = tuple[str, str]
GIT_TIMED_OUT = 124
PRE_SYNC_REF = "refs/llm-prompts/pre-sync"
EARLIER_MAINS_REF = "refs/llm-prompts/earlier-mains"
RESOLVE_WORKTREE = "llm-prompts-resolve"
_RESOLUTIONS_REF = "refs/llm-prompts/resolutions"
_RESOLUTION_FILE = "llm-prompts-resolution"
_RESOLVE_STEPS = "resolve the files there, git add them, then rerun"
_RERERE = ("-c", "rerere.enabled=true", "-c", "rerere.autoUpdate=true")
UPSTREAM = "refs/llm-prompts/upstream"
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


class SyncResult(NamedTuple):
    """How a diverged local main was brought onto its upstream."""

    mode: Literal["reset", "rebased", "squash-synced", "rebuilt", "stopped", "failed"]
    replayed: int = 0
    detail: str = ""
    copied: tuple[str, ...] = ()


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


def point_upstream(repo: Path, ref: str = "") -> bool:
    """Point ``UPSTREAM`` at what local main follows: ``ref`` on the remote, else the latest release tag, else the upstream branch.

    Returns:
        Whether ``UPSTREAM`` now points at a ref.
    """
    if ref:
        remote = run_git(repo, "rev-parse", "--abbrev-ref", "@{u}").stdout
        target = f"refs/remotes/{remote.strip().partition('/')[0]}/{ref}"
    elif releases := {
        version: tag
        for tag in run_git(repo, "tag", "--list", "v*").stdout.split()
        if (version := release_version(tag))
    }:
        target = f"refs/tags/{releases[max(releases)]}"
    else:
        target = run_git(
            repo, "rev-parse", "--symbolic-full-name", "@{u}"
        ).stdout.strip()
    return (
        bool(target) and run_git(repo, "symbolic-ref", UPSTREAM, target).returncode == 0
    )


def unreleased(repo: Path) -> set[str]:
    """The upstream branch commits local main holds that the release ``UPSTREAM`` follows does not, or none when it follows a branch."""
    target = run_git(repo, "symbolic-ref", UPSTREAM).stdout
    if not target.startswith("refs/tags/"):
        return set()
    ahead = set(run_git(repo, "rev-list", f"{UPSTREAM}..HEAD").stdout.split())
    return ahead & set(run_git(repo, "rev-list", f"{UPSTREAM}..@{{u}}").stdout.split())


def sync_diverged(repo: Path, upstream: str = "@{u}") -> SyncResult:
    """Bring a local main whose fast-forward pull failed onto its upstream.

    Args:
        repo: The local clone.
        upstream: The ref local main follows.

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
    identical = run_git(repo, "diff", "--quiet", "HEAD", upstream).returncode == 0
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
        reset = run_git(repo, "reset", "--soft", upstream)
        if reset.returncode != 0:
            return _failed(repo, reset.stderr.strip())
        return SyncResult("reset")
    rebase = run_git(repo, "rebase", "--quiet", upstream)
    if rebase.returncode == 0:
        return SyncResult("rebased")
    abort = run_git(repo, "rebase", "--abort")
    if rebase.returncode == GIT_TIMED_OUT:
        return _failed(repo, rebase.stderr.strip())
    if abort.returncode != 0:
        return _failed(repo, abort.stderr.strip())
    synced = _squash_sync(repo, upstream)
    return _failed(repo, synced.detail) if synced.mode == "failed" else synced


class _Bail(Exception):
    """A step could not prove the sync safe, so nothing may change; the message says why."""


class _ReplayConflict(_Bail):
    """A local commit conflicts with the upstream it is replayed onto."""


class _Stopped(_ReplayConflict):
    """A conflict waits for its hand resolution in the resolve worktree."""


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


def empty_merged_copies(repo: Path, base: str, copied: Collection[str]) -> set[str]:
    """The empty local main commits that are recorded worktree copies, by ``copied`` identity, of a pull request squash-merged into ``base``."""
    if not copied:
        return set()
    try:
        return _empty_merged_copies(repo, base, copied)
    except _Bail:
        return set()


def _empty_merged_copies(repo: Path, base: str, copied: Collection[str]) -> set[str]:
    merge_base = _read(repo, "merge-base", "HEAD", base).strip()
    empty: dict[str, str] = {}
    for line in _read(
        repo, "log", "--format=%H %T %P%x09%at%x09%s", f"{merge_base}..HEAD"
    ).splitlines():
        ids, _, identity = line.partition("\t")
        sha, tree, *parents = ids.split()
        if (
            identity in copied
            and len(parents) == 1
            and tree == _read(repo, "rev-parse", f"{parents[0]}^{{tree}}").strip()
        ):
            empty[sha] = identity.partition("\t")[2]
    if not empty:
        return set()
    merged = {
        _SQUASH_SUFFIX.sub("", subject)
        for subject in _read(repo, "log", "--format=%s", base).splitlines()
        if _SQUASH_SUFFIX.search(subject)
    }
    return {sha for sha, subject in empty.items() if subject in merged}


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


def _upstream_pr_numbers(repo: Path, upstream: str) -> dict[str, int]:
    ups = _cherry(repo, "HEAD", upstream, "+")
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
    repo: Path, remote: str, upstream: str
) -> tuple[list[str], dict[_Identity, list[tuple[str, ...]]]]:
    """Return the accepted PR heads and, per commit identity, each PR's commits from that one to its head."""
    accepted: list[str] = []
    pr_commits: dict[_Identity, list[tuple[str, ...]]] = {}
    numbers = _upstream_pr_numbers(repo, upstream)
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
            for line in _read(
                repo,
                "log",
                "--no-merges",
                "--topo-order",
                "--reverse",
                "--format=%H%x09%at%x09%s",
                f"{up}^..{head}",
            ).splitlines()
        ]
        chain = tuple(sha for sha, _, _ in rows)
        for index, (_, _, rest) in enumerate(rows):
            pr_commits.setdefault(_identity(rest), []).append(chain[index:])
    return accepted, pr_commits


def _open_pr_commits(
    repo: Path, remote: str, upstream: str
) -> dict[_Identity, list[_OpenPrCommit]]:
    """Map each commit of an open pull request, by identity, to its versions in each head.

    A pull request is open when it has a merge ref and its head is also the tip of a
    branch on the remote. A closed pull request keeps its head ref but loses its merge ref.
    """
    listing = [
        line.split()
        for line in _read(
            repo,
            "ls-remote",
            remote,
            "refs/pull/*/head",
            "refs/pull/*/merge",
            "refs/heads/*",
        ).splitlines()
    ]
    branch_tips = {sha for sha, ref in listing if ref.startswith("refs/heads/")}
    merge_refs = {ref for _, ref in listing if ref.endswith("/merge")}
    heads = _fetch_missing(
        repo,
        remote,
        {
            ref: sha
            for sha, ref in listing
            if ref.endswith("/head")
            and sha in branch_tips
            and f"{ref.removesuffix('/head')}/merge" in merge_refs
        },
    )
    commits: dict[_Identity, list[_OpenPrCommit]] = {}
    for head in heads.values():
        for line in _read(
            repo,
            "log",
            "--no-merges",
            "--format=%H%x09%at%x09%s",
            f"{upstream}..{head}",
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


def _resolution_ref(repo: Path, base: str, ours: str, theirs: str) -> str:
    """Return the ref that stores the tree staged by hand for merging ``theirs`` onto ``ours`` from ``base``."""
    trees = _read(
        repo, "rev-parse", *(f"{rev}^{{tree}}" for rev in (base, theirs, ours))
    ).split()
    return "/".join((_RESOLUTIONS_REF, *trees))


def _staged_tree(repo: Path, base: str, ours: str, theirs: str) -> str | None:
    """Return the newest tree staged by hand for merging ``theirs`` from ``base`` that replays cleanly from the main it was staged on onto ``ours``.

    A tree that keeps the main it was staged on replays only while ``ours`` leaves the files ``theirs`` changes as they were.
    """
    merge = _resolution_ref(repo, base, ours, theirs).rpartition("/")[0]
    for ref in _read(
        repo, "for-each-ref", "--sort=-creatordate", "--format=%(refname)", f"{merge}/"
    ).split():
        staged_on = ref.rpartition("/")[2]
        if _read(repo, "rev-parse", f"{ref}^{{tree}}").strip() == staged_on and set(
            _changed_paths(repo, staged_on, ours)
        ) & set(_changed_paths(repo, base, theirs)):
            continue
        with suppress(_Conflict):
            return _merge_tree(repo, staged_on, ours, ref)
    return None


def _reuse_resolutions(
    repo: Path, base: str, ours: str, theirs: str, keep: Path | None = None
) -> str | None:
    """Return a tree staged by hand for this merge, else merge in a throwaway worktree where git rerere records the conflicts and applies earlier hand resolutions.

    Args:
        repo: The local clone.
        base: The merge base.
        ours: The commit to merge onto.
        theirs: The commit whose changes on ``base`` are merged.
        keep: Where to add the worktree and leave it while any conflict has no recorded resolution. A worktree already there, whose resolution is stored for another merge, is removed first.

    Returns:
        The merged tree, or None while any conflict has no recorded resolution.

    Raises:
        _Stopped: ``keep`` holds a resolution staged for this merge that conflicts with ``ours``.
    """
    if (staged := _staged_tree(repo, base, ours, theirs)) is not None:
        return staged
    ref = _resolution_ref(repo, base, ours, theirs)
    if keep is not None and keep.exists():
        if (
            _resolution_file(keep).read_text(encoding="utf-8").rpartition("/")[0]
            == ref.rpartition("/")[0]
        ):
            raise _Stopped(
                f"the resolution staged in {keep} conflicts with main; drop it with:"
                f" git worktree remove --force {shlex.quote(str(keep))}, then rerun"
            )
        _read(repo, "worktree", "remove", "--force", str(keep))
    change = _read(
        repo, "commit-tree", f"{theirs}^{{tree}}", "-p", base, "-m", "replay"
    ).strip()
    with tempfile.TemporaryDirectory() as parent:
        work = keep or Path(parent) / "work"
        _read(repo, "worktree", "add", "--quiet", "--detach", str(work), ours)
        kept = False
        try:
            pick = run_git(work, *_RERERE, "cherry-pick", "--no-commit", change)
            if pick.returncode not in (0, 1):
                return None
            if run_git(work, "ls-files", "--unmerged").stdout:
                kept = keep is not None
                if kept:
                    _resolution_file(work).write_text(ref, encoding="utf-8")
                return None
            return _read(work, "write-tree").strip()
        finally:
            if not kept:
                run_git(repo, "worktree", "remove", "--force", str(work))


def resolve_worktree(repo: Path) -> Path:
    """Return where a rebuild leaves a conflicting copy for its hand resolution."""
    common = _read(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common.strip()) / RESOLVE_WORKTREE


def _resolution_file(work: Path) -> Path:
    """Return the file in ``work`` that names the ref its staged tree is stored under."""
    return Path(
        _read(
            work, "rev-parse", "--path-format=absolute", "--git-path", _RESOLUTION_FILE
        ).strip()
    )


def _record_resolution(repo: Path) -> None:
    """Record the hand resolution left in the resolve worktree with git rerere, and store its staged tree under the ref its merge names.

    Raises:
        _Stopped: The worktree has unresolved conflicts, changes that are not staged, or names no merge.
    """
    work = resolve_worktree(repo)
    if not work.exists():
        return
    drop = f"git worktree remove --force {shlex.quote(str(work))}"
    if run_git(work, "ls-files", "--unmerged").stdout:
        raise _Stopped(
            f"conflicts in {work} are unresolved; {_RESOLVE_STEPS}, or drop them with:"
            f" {drop}"
        )
    if any(
        line[1] != " "
        for line in _read(
            work, "status", "--porcelain", "--ignored", "--untracked-files=all"
        ).splitlines()
    ):
        raise _Stopped(f"{work} has changes that are not staged; {_RESOLVE_STEPS}")
    if not (named := _resolution_file(work)).exists():
        raise _Stopped(
            f"{work} names no merge to reuse its resolution for; save its changes,"
            f" then drop it with: {drop}"
        )
    _read(work, *_RERERE, "rerere")
    commit = _read(
        repo,
        "commit-tree",
        _read(work, "write-tree").strip(),
        "-m",
        "llm-prompts: hand resolution",
        env=_EARLIER_MAINS_IDENTITY,
    ).strip()
    _read(repo, "update-ref", named.read_text(encoding="utf-8"), commit)


def _drop_resolve_worktree(repo: Path, work: Path) -> None:
    """Remove the resolve worktree ``work``, whose resolution is stored, once main is rebuilt."""
    if work.exists():
        run_git(repo, "worktree", "remove", "--force", str(work))


def holds_changes(repo: Path, tip: str, sha: str) -> bool:
    """Return whether the changes of commit ``sha`` merge into ``tip`` cleanly and leave its tree as it is."""
    try:
        tree = _merge_tree(repo, f"{sha}^", tip, sha)
    except _Conflict:
        return False
    return tree == _read(repo, "rev-parse", f"{tip}^{{tree}}").strip()


def replays_to(
    repo: Path, parent: str, squash: Squash, result: str, reuse: bool = True
) -> bool:
    """Return whether replaying ``squash`` on ``parent``, reusing recorded hand resolutions when ``reuse``, gives ``result``'s tree."""
    try:
        tree: str | None
        try:
            tree = _merge_tree(repo, squash.floor, parent, squash.tip)
        except _Conflict:
            if not reuse:
                return False
            tree = _reuse_resolutions(repo, squash.floor, parent, squash.tip)
    except _Bail:
        return False
    return tree == _read(repo, "rev-parse", f"{result}^{{tree}}").strip()


def _replay(
    repo: Path,
    tip: str,
    commit: LocalCommit,
    squash: Squash | None = None,
    against: str = "upstream",
    keep: Path | None = None,
    reuse: bool = False,
) -> str:
    floor, changes = (
        (squash.floor, squash.tip) if squash else (f"{commit.sha}^", commit.sha)
    )
    try:
        tree = _merge_tree(repo, floor, tip, changes)
    except _Conflict as conflict:
        staged = _staged_tree(repo, floor, tip, changes) if reuse else None
        resolved = staged or (
            _reuse_resolutions(repo, floor, tip, changes, keep) if reuse else None
        )
        if resolved is None or (
            staged is None
            and resolved == _read(repo, "rev-parse", f"{tip}^{{tree}}").strip()
        ):
            message = (
                f"local commit {commit.sha[:12]} ({commit.subject}) conflicts with {against}"
                f" in {', '.join(conflict.paths)}"
            )
            if keep is not None and keep.exists():
                raise _Stopped(f"{message}; left in {keep}: {_RESOLVE_STEPS}")
            raise _ReplayConflict(message) from conflict
        tree = resolved
    tip_tree, floor_tree, changes_tree = _read(
        repo, "rev-parse", f"{tip}^{{tree}}", f"{floor}^{{tree}}", f"{changes}^{{tree}}"
    ).split()
    if tree == tip_tree and floor_tree != changes_tree:
        return tip
    return _commit_as(repo, tree, tip, squash.first if squash else commit.sha)


def _replay_or_open_pr_version(
    repo: Path,
    tip: str,
    commit: LocalCommit,
    open_pr_commits: Callable[[], dict[_Identity, list[_OpenPrCommit]]],
    merged_squashes: Mapping[str, list[str]] | None = None,
) -> str:
    reuse = commit.subject not in (merged_squashes or {})
    try:
        return _replay(repo, tip, commit, reuse=reuse)
    except _ReplayConflict:
        for pr_commit in open_pr_commits().get(
            (commit.authored_at, commit.subject), ()
        ):
            if holds_changes(repo, pr_commit.head, commit.sha):
                with suppress(_ReplayConflict):
                    return _replay(
                        repo, tip, commit._replace(sha=pr_commit.sha), reuse=reuse
                    )
        if any(
            holds_changes(repo, squash, commit.sha)
            for squash in (merged_squashes or {}).get(commit.subject, ())
        ):
            return tip
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


def _build_sync(repo: Path, upstream: str) -> SyncResult:
    remote = _read(repo, "rev-parse", "--abbrev-ref", "@{u}").strip().partition("/")[0]
    merge_base = _read(repo, "merge-base", "HEAD", upstream).strip()
    local = _local_commits(repo, merge_base)
    heads, pr_commits = _merged_pr_commits(repo, remote, upstream)
    covered = {
        *_cherry(repo, upstream, "HEAD", "-"),
        *(sha for head in heads for sha in _cherry(repo, head, "HEAD", "-")),
    }
    replayed = [
        commit
        for commit in _autosquash(
            repo, [commit for commit in local if commit.sha not in covered]
        )
        if not _equivalent(repo, commit, pr_commits)
    ]
    tip = _read(repo, "rev-parse", upstream).strip()
    open_pr_commits = cache(lambda: _open_pr_commits(repo, remote, upstream))
    local_shas = {commit.sha for commit in local}
    merged_squashes: dict[str, list[str]] = {}
    for line in _read(
        repo, "log", "--format=%H%x09%s", f"{merge_base}..{upstream}"
    ).splitlines():
        sha, _, subject = line.partition("\t")
        if squash_pr_number(subject) is not None:
            merged_squashes.setdefault(_SQUASH_SUFFIX.sub("", subject), []).append(sha)
    kept = 0
    for commit in replayed:
        new_tip = _replay_or_open_pr_version(
            repo,
            tip,
            commit,
            open_pr_commits if commit.sha in local_shas else dict,
            merged_squashes,
        )
        kept += new_tip != tip
        tip = new_tip
    reset = run_git(repo, "reset", "--keep", tip)
    if reset.returncode != 0:
        return SyncResult("failed", detail=reset.stderr.strip())
    return SyncResult("squash-synced", replayed=kept)


def _squash_sync(repo: Path, upstream: str) -> SyncResult:
    try:
        return _build_sync(repo, upstream)
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


def _changed_paths(repo: Path, old: str, new: str) -> list[str]:
    return _read(repo, "diff", "--name-only", "--no-renames", old, new).splitlines()


def _lost_paths(repo: Path, tip: str, sha: str, kept: Collection[str]) -> list[str]:
    """Return the paths where commit ``sha`` has changes that ``tip`` lacks, counting a clash in a ``kept`` path as replaced."""
    result = run_git(
        repo,
        "merge-tree",
        "--write-tree",
        "--name-only",
        f"--merge-base={sha}^",
        tip,
        sha,
    )
    if result.returncode not in (0, 1):
        raise _Bail(
            result.stderr.strip() or f"git merge-tree exited {result.returncode}"
        )
    tree, *rest = result.stdout.splitlines()
    clashes = set(takewhile(bool, rest)) if result.returncode else set()
    return sorted(
        {path for path in _changed_paths(repo, tip, tree) if path not in clashes}
        | (clashes - set(kept))
    )


def rebuild_local(
    repo: Path,
    base: str,
    substitutions: Mapping[str, Squash],
    drops: Collection[str],
    copies: Mapping[str, str],
    additions: Sequence[Squash],
    landed: Collection[str] = (),
    exact: Collection[str] = (),
    earlier: Mapping[str, Squash] | None = None,
) -> SyncResult:
    """Move local main onto ``base`` with its local commits replayed, some swapped for squashes or dropped, plus new squashes.

    A replay whose conflict has no recorded resolution stops the rebuild and leaves its merge in ``resolve_worktree``. The next rebuild records the hand resolution staged there with git rerere, and stores its whole tree for that merge, which it replays onto main. The worktree stays until main is rebuilt, and a rebuild stops while it holds changes that are not staged.

    Args:
        repo: The local clone, on its main branch.
        base: The ref local commits are counted from.
        substitutions: Local commit sha to the squash that replaces it.
        drops: Local commit shas to leave out.
        copies: Local commit sha of each known copy of a worktree branch to the first commit of that branch.
        additions: Squashes to replay on top, in order.
        landed: Local commit shas to leave out where their changes are already on the commits replayed before them.
        exact: Local commit shas that copy merged branches.
        earlier: Local commit sha of a copy that only one worktree branch claims to the squash of that branch it was copied from.

    ``landed`` and ``exact`` commits, and the squashes that replace them, replay without recorded hand resolutions, and a conflict of one fails the rebuild.
    Every change of an unpublished commit left out or replaced must be on the new main, unless it is not a ``landed`` or ``exact`` commit and clashes with a change in a file its replacement changes, or it is in a file its ``earlier`` squash, replayed on the commit's parent, changes to the content the commit holds, or main is left untouched.

    Returns:
        ``rebuilt`` with the count of replayed commits and the first commit of each squash replayed into a new commit, ``stopped`` at a conflict waiting for its hand resolution, or a failed result. Neither of the last two changes main.
    """
    if (operation := _operation_in_progress(repo)) is not None:
        return SyncResult("failed", detail=f"a {operation} is in progress")
    try:
        branch = _read(repo, "symbolic-ref", "--short", "-q", "HEAD").strip()
        if branch != "main":
            raise _Bail(f"{repo} has {branch or 'no branch'} checked out, not main")
        _record_resolution(repo)
        keep = resolve_worktree(repo)
        merge_base = _read(repo, "merge-base", "HEAD", base).strip()
        head = _read(repo, "rev-parse", "HEAD").strip()
        tip = _read(repo, "rev-parse", base).strip()
        replayed = 0
        copied: list[str] = []
        removed: dict[str, Squash | None] = {}
        placed: dict[str, Squash] = {}
        untouched = tip == merge_base
        guarded = {*landed, *exact, *(copies[sha] for sha in exact if sha in copies)}
        for commit in _local_commits(repo, merge_base):
            squash = substitutions.get(commit.sha)
            dropped = commit.sha in drops or (
                commit.sha in landed and holds_changes(repo, tip, commit.sha)
            )
            if squash is None and not dropped and untouched:
                tip = commit.sha
                continue
            untouched = False
            if dropped:
                removed[commit.sha] = None
                continue
            new_tip = _replay(
                repo,
                tip,
                commit,
                squash,
                "main" if commit.sha in copies else "upstream",
                keep,
                commit.sha not in guarded,
            )
            if squash:
                removed[commit.sha] = squash
                if new_tip != tip:
                    copied.append(squash.first)
            replayed += new_tip != tip
            tip = new_tip
        for squash in additions:
            subject = _read(repo, "log", "-1", "--format=%s", squash.first).strip()
            new_tip = _replay(
                repo,
                tip,
                LocalCommit(squash.first, "", subject),
                squash,
                "main",
                keep,
                squash.first not in guarded,
            )
            placed[squash.first] = squash
            if new_tip != tip:
                copied.append(squash.first)
            replayed += new_tip != tip
            tip = new_tip
        replacements = [s for s in removed.values() if s] + list(placed.values())
        for sha, replacement in removed.items():
            if (
                replacement is None
                and sha in copies
                and (replacement := placed.get(copies[sha])) is None
            ):
                continue
            if _read(
                repo, "for-each-ref", "--count=1", "--contains", sha, "refs/remotes"
            ):
                continue
            kept = (
                set()
                if sha in guarded
                else {
                    path
                    for squash in ([replacement] if replacement else replacements)
                    for path in _changed_paths(repo, squash.floor, squash.tip)
                }
            )
            lost = _lost_paths(repo, tip, sha, kept)
            if prior := (earlier or {}).get(sha):
                try:
                    replay = _merge_tree(repo, prior.floor, f"{sha}^", prior.tip)
                except _Conflict:
                    replay = None
                own = (
                    set(_changed_paths(repo, f"{sha}^", replay))
                    - set(_changed_paths(repo, sha, replay))
                    if replay
                    else set()
                )
                lost = [path for path in lost if path not in own]
            if lost:
                raise _Bail(
                    f"local commit {sha[:12]} has changes in {', '.join(lost)}"
                    " that its replacement drops"
                )
        if tip == head:
            _drop_resolve_worktree(repo, keep)
            return SyncResult("rebuilt", copied=tuple(copied))
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
    except _Stopped as stopped:
        return SyncResult("stopped", detail=f"main left untouched: {stopped}")
    except _Bail as bail:
        return SyncResult("failed", detail=f"main left untouched: {bail}")
    if reset.returncode != 0:
        return SyncResult("failed", detail=reset.stderr.strip())
    _drop_resolve_worktree(repo, keep)
    return SyncResult("rebuilt", replayed=replayed, copied=tuple(copied))
