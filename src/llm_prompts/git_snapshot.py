"""Answer questions about a repo's recent history from two git reads instead of one process per question."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import NamedTuple

_LOG_FORMAT = "%H%x00%P%x00%at%x00%s"
_REF_PATTERNS = (
    "refs/heads",
    "refs/llm-prompts",
    "refs/remotes/origin/main",
    "refs/remotes/upstream/main",
)
_FULL_SHA = re.compile(r"[0-9a-f]{40}")


class SnapshotCommit(NamedTuple):
    """A commit of the snapshot, with the author time and subject git prints for it."""

    sha: str
    parents: tuple[str, ...]
    authored_at: str
    subject: str

    @property
    def identity(self) -> str:
        """Return the author time and subject, as ``git log -1 --format=%at%x09%s`` prints them."""
        return f"{self.authored_at}\t{self.subject}".strip()


def read_refs(repo: Path) -> dict[str, str]:
    """Return the sha of every local branch, ``llm-prompts`` ref and main of origin and upstream, by full ref name."""
    rows = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "for-each-ref",
            "--format=%(objectname) %(refname)",
            *_REF_PATTERNS,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return {name: sha for sha, name in (row.split(" ", 1) for row in rows)}


def resolve_ref(refs: Mapping[str, str], name: str) -> str | None:
    """Return the sha of a full ref name, a branch or a remote branch such as ``origin/main``, if ``refs`` holds it."""
    for full in (name, f"refs/heads/{name}", f"refs/remotes/{name}"):
        if full in refs:
            return refs[full]
    return None


class Snapshot:
    """The commits of some branches that ``floor`` lacks, and every ref, as they stand when it is read.

    Every method returns None where these commits cannot settle the answer, such as a commit below the floor
    or a merge that leaves the order or the merge base open, so the caller asks git. Read a new snapshot after any ref moves.
    """

    def __init__(
        self, repo: Path, refs: Mapping[str, str], floor: str, heads: Collection[str]
    ) -> None:
        self.refs = refs
        self.floor = self._resolve(floor)
        self.commits: dict[str, SnapshotCommit] = {}
        tips = {sha for head in heads if (sha := self._resolve(head)) is not None}
        if self.floor is not None and tips:
            log = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "log",
                    "--no-show-signature",
                    f"--format={_LOG_FORMAT}",
                    *sorted(tips),
                    "--not",
                    self.floor,
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            for row in log.splitlines():
                sha, parents, authored_at, subject = row.split("\x00", 3)
                self.commits[sha] = SnapshotCommit(
                    sha, tuple(parents.split()), authored_at, subject
                )

    def _resolve(self, name: str) -> str | None:
        """Return the commit a ref name or full sha names, if the snapshot knows it."""
        return resolve_ref(self.refs, name) or (
            name if _FULL_SHA.fullmatch(name) else None
        )

    def _reach(self, tip: str) -> tuple[set[str], set[str]] | None:
        """Return the snapshot commits ``tip`` has, and the commits below them that they sit on, or None when ``tip`` is not a snapshot commit."""
        if tip not in self.commits:
            return None
        held: set[str] = set()
        below: set[str] = set()
        pending = [tip]
        while pending:
            sha = pending.pop()
            if sha in held:
                continue
            held.add(sha)
            for parent in self.commits[sha].parents:
                if parent in self.commits:
                    pending.append(parent)
                else:
                    below.add(parent)
        return held, below

    def chain(self, floor: str, ref: str) -> list[SnapshotCommit] | None:
        """Return the commits of ``floor..ref``, newest first, or None unless they form one line of history."""
        tip, base = self._resolve(ref), self._resolve(floor)
        if self.floor is None or base != self.floor or tip is None:
            return None
        start, found = tip, []
        while (commit := self.commits.get(tip)) is not None:
            found.append(commit)
            if len(commit.parents) > 1:
                return None
            if not commit.parents:
                break
            tip = commit.parents[0]
        return found if found or start == self.floor else None

    def shas(self, floor: str, ref: str) -> list[str] | None:
        """Return the commits of ``floor..ref``, oldest first, as ``git rev-list --reverse`` does."""
        found = self.chain(floor, ref)
        return None if found is None else [c.sha for c in reversed(found)]

    def is_ancestor(self, ancestor: str, sha: str) -> bool | None:
        """Return whether ``sha`` has ``ancestor`` in its history, as ``git merge-base --is-ancestor`` does."""
        a, b = self._resolve(ancestor), self._resolve(sha)
        if a is None or b is None:
            return None
        if a == b:
            return True
        if self.floor is None:
            return None
        if b in self.commits:
            held, below = self._reach(b) or (set(), set())
            if a in self.commits:
                return a in held
            return a in below if a == self.floor else None
        if b == self.floor:
            return False if a in self.commits else None
        return None

    def merge_base(self, floor: str, ref: str) -> str | None:
        """Return the merge base of the floor and ``ref``, unless a merge leaves more than one."""
        tip, base = self._resolve(ref), self._resolve(floor)
        if self.floor is None or base != self.floor or tip is None:
            return None
        if (reach := self._reach(tip)) is None:
            return None
        below = reach[1]
        return next(iter(below)) if len(below) == 1 else None

    def identity(self, sha: str) -> str | None:
        """Return the author time and subject of ``sha``, as ``git log -1 --format=%at%x09%s`` prints them."""
        commit = self.commits.get(self._resolve(sha) or "")
        return None if commit is None else commit.identity

    def commit(self, sha: str) -> SnapshotCommit | None:
        """Return ``sha``'s parents and subject."""
        return self.commits.get(self._resolve(sha) or "")

    def is_commit(self, sha: str) -> bool | None:
        """Return True when ``sha`` is the floor or a snapshot commit, else None."""
        found = self._resolve(sha)
        return True if found == self.floor or found in self.commits else None
