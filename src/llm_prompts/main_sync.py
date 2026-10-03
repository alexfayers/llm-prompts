"""Sync a local main that diverged from its upstream onto the upstream."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Literal, NamedTuple

from .setup import GIT_TIMEOUT

_Identity = tuple[str, str]
GIT_TIMED_OUT = 124


class SyncResult(NamedTuple):
    """How a diverged local main was brought onto its upstream."""

    mode: Literal["reset", "rebased", "squash-synced", "failed"]
    replayed: int = 0
    folded: tuple[str, ...] = ()
    detail: str = ""


class LocalCommit(NamedTuple):
    """A local commit, identified across rewrites by author time and subject."""

    sha: str
    authored_at: str
    subject: str


def split_local(
    local: Sequence[LocalCommit],
    covered: Collection[str],
    pr_ids: Collection[_Identity],
) -> tuple[list[LocalCommit], list[LocalCommit]]:
    """Split local commits into those unrelated to any merged PR and those revised by one.

    Args:
        local: The local commits, oldest first.
        covered: Shas whose change already exists upstream or in a merged PR.
        pr_ids: The (author time, subject) pairs of the merged PRs' commits.

    Returns:
        The unrelated and the revised commits, each in local order.
    """
    unrelated: list[LocalCommit] = []
    revised: list[LocalCommit] = []
    for commit in local:
        if commit.sha in covered:
            continue
        in_pr = (commit.authored_at, commit.subject) in pr_ids
        (revised if in_pr else unrelated).append(commit)
    return unrelated, revised


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


def sync_diverged(repo: Path) -> SyncResult:
    """Bring a local main whose fast-forward pull failed onto its upstream.

    Args:
        repo: The local clone.

    Returns:
        How the clone was synced, or a failed result that leaves it untouched.
    """
    if run_git(repo, "diff", "--quiet", "HEAD", "@{u}").returncode == 0:
        reset = run_git(repo, "reset", "--soft", "@{u}")
        if reset.returncode != 0:
            return SyncResult("failed", detail=reset.stderr.strip())
        return SyncResult("reset")
    rebase = run_git(repo, "rebase", "--quiet", "@{u}")
    if rebase.returncode == 0:
        return SyncResult("rebased")
    run_git(repo, "rebase", "--abort")
    if rebase.returncode == GIT_TIMED_OUT:
        return SyncResult("failed", detail=rebase.stderr.strip())
    return _squash_sync(repo)


class _Bail(Exception):
    """A step could not prove the sync safe, so nothing may change; the message says why."""


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


def _pull_heads(repo: Path, remote: str) -> list[list[str]]:
    listing = _read(repo, "ls-remote", remote, "refs/pull/*/head").splitlines()
    if not listing:
        raise _Bail(f"{remote} lists no pull request heads")
    heads = [line.split() for line in listing]
    checked = _read(
        repo, "cat-file", "--batch-check", input="".join(f"{sha}\n" for sha, _ in heads)
    ).splitlines()
    missing = [
        ref
        for (_, ref), line in zip(heads, checked, strict=True)
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


def _merged_pr_heads(
    repo: Path,
    remote: str,
    ups: list[str],
    local_ids: set[_Identity],
) -> tuple[list[str], dict[_Identity, str]]:
    if not ups:
        return [], {}
    heads = [sha for sha, _ in _pull_heads(repo, remote)]
    trees = _read(
        repo, "rev-parse", *(f"{sha}^{{tree}}" for sha in [*ups, *heads])
    ).split()
    up_trees, head_trees = trees[: len(ups)], trees[len(ups) :]
    accepted: list[str] = []
    pr_commits: dict[_Identity, str] = {}
    for up, up_tree in zip(ups, up_trees, strict=True):
        foreign: list[bool] = []
        for head, head_tree in zip(heads, head_trees, strict=True):
            if head_tree != up_tree:
                continue
            ids: dict[_Identity, str] = {}
            for line in _read(
                repo,
                "log",
                "--no-merges",
                "--format=%H%x09%at%x09%s",
                f"{up}^..{head}",
            ).splitlines():
                sha, _, rest = line.partition("\t")
                _record(ids, _identity(rest), sha)
            if ids and ids.keys() <= local_ids:
                accepted.append(head)
                for identity, sha in ids.items():
                    _record(pr_commits, identity, sha)
                break
            foreign.append(bool(ids) and ids.keys().isdisjoint(local_ids))
        else:
            if not foreign or not all(foreign):
                raise _Bail(
                    f"upstream commit {up} matches no merged pull request of local commits"
                )
    return accepted, pr_commits


def _merge_tree(repo: Path, base: str, ours: str, theirs: str) -> str:
    return _read(
        repo, "merge-tree", "--write-tree", f"--merge-base={base}", ours, theirs
    ).splitlines()[0]


def _replay(repo: Path, tip: str, commit: LocalCommit) -> str:
    tree = _merge_tree(repo, f"{commit.sha}^", tip, commit.sha)
    name, email, date, message = _read(
        repo, "log", "-1", "--format=%an%x00%ae%x00%aI%x00%B", commit.sha
    ).split("\x00", 3)
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": date}
    return _read(
        repo,
        "commit-tree",
        tree,
        "-p",
        tip,
        "-F",
        "-",
        input=message.rstrip("\n") + "\n",
        env=env,
    ).strip()


def _proven_bases(
    repo: Path,
    revised: list[LocalCommit],
    pr_commits: dict[_Identity, str],
) -> dict[str, str]:
    """Find, for each revised commit, its earlier reflog version that a PR merged.

    Args:
        repo: The local clone.
        revised: The local commits revised by a merged PR, in local order.
        pr_commits: The merged PRs' commit shas by (author time, subject).

    Returns:
        The earlier version's sha for each revised commit's sha.

    Raises:
        _Bail: If a revised commit has no earlier version with the PR commit's patch-id.
    """
    wanted = {(commit.authored_at, commit.subject) for commit in revised}
    candidates: dict[_Identity, list[str]] = {}
    for line in _read(
        repo, "log", "--walk-reflogs", "--format=%H%x09%at%x09%s", "HEAD"
    ).splitlines():
        sha, _, rest = line.partition("\t")
        if _identity(rest) in wanted:
            candidates.setdefault(_identity(rest), []).append(sha)
    shas = dict.fromkeys(
        [
            *(pr_commits[identity] for identity in wanted),
            *(sha for versions in candidates.values() for sha in versions),
        ]
    )
    patch_ids = {
        sha: patch_id
        for patch_id, _, sha in (
            line.partition(" ")
            for line in _read(
                repo,
                "patch-id",
                "--stable",
                input=_read(
                    repo,
                    "show",
                    "--no-color",
                    "--no-ext-diff",
                    "--format=medium",
                    *shas,
                ),
            ).splitlines()
        )
    }
    bases: dict[str, str] = {}
    for commit in revised:
        identity = (commit.authored_at, commit.subject)
        pr_patch_id = patch_ids.get(pr_commits[identity])
        base = next(
            (
                sha
                for sha in candidates.get(identity, [])
                if patch_ids.get(sha) == pr_patch_id
            ),
            None,
        )
        if pr_patch_id is None or base is None:
            raise _Bail(
                f"no earlier local version of {commit.sha} matches its merged pull request"
            )
        bases[commit.sha] = base
    return bases


def _fold_tree(
    repo: Path,
    tip_tree: str,
    revised: list[LocalCommit],
    bases: dict[str, str],
) -> str:
    tree = tip_tree
    for commit in revised:
        base = bases[commit.sha]
        tree = _merge_tree(
            repo,
            _merge_tree(repo, f"{base}^", f"{commit.sha}^", base),
            tree,
            commit.sha,
        )
    return tree


def _fold(repo: Path, tip: str, tree: str, revised: list[LocalCommit]) -> str:
    message = "\n\n".join(
        _read(repo, "log", "-1", "--format=%B", c.sha).rstrip("\n") for c in revised
    )
    return _read(
        repo, "commit-tree", tree, "-p", tip, "-F", "-", input=f"{message}\n"
    ).strip()


def _build_sync(repo: Path) -> SyncResult:
    remote = _read(repo, "rev-parse", "--abbrev-ref", "@{u}").strip().partition("/")[0]
    merge_base = _read(repo, "merge-base", "HEAD", "@{u}").strip()
    local = _local_commits(repo, merge_base)
    heads, pr_commits = _merged_pr_heads(
        repo,
        remote,
        _cherry(repo, "HEAD", "@{u}", "+"),
        {(commit.authored_at, commit.subject) for commit in local},
    )
    covered = {
        *_cherry(repo, "@{u}", "HEAD", "-"),
        *(sha for head in heads for sha in _cherry(repo, head, "HEAD", "-")),
    }
    unrelated, revised = split_local(local, covered, pr_commits)
    tip = _read(repo, "rev-parse", "@{u}").strip()
    for commit in unrelated:
        tip = _replay(repo, tip, commit)
    tip_tree = _read(repo, "rev-parse", f"{tip}^{{tree}}").strip()
    merged = run_git(
        repo, "merge-tree", "--write-tree", f"--merge-base={merge_base}", tip, "HEAD"
    )
    folded: tuple[str, ...] = ()
    if merged.returncode != 0 or merged.stdout.split("\n", 1)[0] != tip_tree:
        if not revised:
            raise _Bail("local changes missing upstream match no merged pull request")
        tree = _fold_tree(
            repo, tip_tree, revised, _proven_bases(repo, revised, pr_commits)
        )
        if tree != tip_tree:
            tip = _fold(repo, tip, tree, revised)
            folded = tuple(commit.subject for commit in revised)
    reset = run_git(repo, "reset", "--keep", tip)
    if reset.returncode != 0:
        return SyncResult("failed", detail=reset.stderr.strip())
    return SyncResult("squash-synced", replayed=len(unrelated), folded=folded)


def _squash_sync(repo: Path) -> SyncResult:
    try:
        return _build_sync(repo)
    except _Bail as bail:
        return SyncResult("failed", detail=f"squash sync stopped: {bail}")
