"""The record of worktree branches that ``contribute`` manages."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NamedTuple

from . import home
from .jsonfile import write_json_atomic

RECORD_ENV = "LLM_PROMPTS_CONTRIBUTE_RECORD"


class CorruptRecord(Exception):
    """The record could not be read and was set aside."""


class Link(NamedTuple):
    """A worktree branch another one depends on; ``ref`` is ``owner/repo#N`` once that branch has a PR."""

    repo: str
    branch: str
    ref: str = ""


class WorktreeEntry(NamedTuple):
    """One worktree branch that is one PR, with the state last seen for it.

    ``dropped_refs`` are refs of removed links whose Depends on line sync wrote
    and has not yet taken out of the PR body.
    ``copied`` is the author time and subject of the first commit when sync last
    copied the branch into local main, and ``copied_tip`` is the branch tip it copied.
    ``why`` is the text sync puts under Why when it opens the PR.
    ``title`` is the PR title sync gives the PR instead of the one it makes from the commits.
    ``synced_title`` is the PR title sync last wrote, so a title edited since is kept.
    ``extra`` holds the record keys this version does not know, kept so a save
    writes them back.
    """

    repo: str
    branch: str
    path: str
    pr: int | None
    pr_state: str | None
    remote_head: str | None
    ready: bool = False
    depends_on: tuple[Link, ...] = ()
    dropped_refs: tuple[str, ...] = ()
    copied: str | None = None
    copied_tip: str | None = None
    why: str = ""
    title: str = ""
    synced_title: str = ""
    extra: tuple[tuple[str, Any], ...] = ()


def record_path() -> Path:
    """Return the record file, overridable through ``RECORD_ENV``."""
    override = os.environ.get(RECORD_ENV)
    return (
        Path(override) if override else home.config_dir() / "contribute-worktrees.json"
    )


def _entry_from_json(data: dict[str, Any]) -> WorktreeEntry:
    known = set(WorktreeEntry._fields) - {"extra"}
    return WorktreeEntry(
        **{
            **{key: data[key] for key in data if key in known},
            "extra": tuple((k, v) for k, v in data.items() if k not in known),
            "depends_on": tuple(
                Link(**{k: v for k, v in link.items() if k in Link._fields})
                for link in data.get("depends_on", ())
            ),
            "dropped_refs": tuple(data.get("dropped_refs", ())),
        }
    )


def _corrupt_copy_name(path: Path) -> Path:
    return path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%dT%H%M%S')}")


def load_entries(path: Path) -> list[WorktreeEntry]:
    """Read the recorded entries; a missing record holds none.

    An entry that cannot be read is skipped with a warning, and the record is
    copied to ``.corrupt-<time>`` first.

    Raises:
        CorruptRecord: The record was unreadable and has been renamed aside.
    """
    if not path.exists():
        return []
    try:
        records = json.loads(path.read_text(encoding="utf-8"))["entries"]
        if not isinstance(records, list):
            raise TypeError("entries is not a list")
    except (OSError, ValueError, TypeError, KeyError) as error:
        aside = _corrupt_copy_name(path)
        path.replace(aside)
        raise CorruptRecord(
            f"{path} is unreadable and was renamed to {aside.name}; "
            "rebuild it with: llm-prompts contribute sync --rescan"
        ) from error
    entries: list[WorktreeEntry] = []
    skipped: list[str] = []
    for index, record in enumerate(records):
        try:
            entries.append(_entry_from_json(record))
        except (AttributeError, TypeError):
            skipped.append(f"entry {index}: {record!r}")
    if skipped:
        copy = _corrupt_copy_name(path)
        shutil.copy2(path, copy)
        print(
            f"{path}: skipped unreadable {'; '.join(skipped)} (record copied to {copy.name})",
            file=sys.stderr,
        )
    return entries


def copied_identities(repo: Path) -> set[str]:
    """Return the ``copied`` identity of each recorded entry of ``repo``, or none when the record is unreadable."""
    try:
        entries = load_entries(record_path())
    except CorruptRecord:
        return set()
    return {
        e.copied
        for e in entries
        if e.copied and e.repo == str(repo.expanduser().resolve())
    }


def save_entries(path: Path, entries: list[WorktreeEntry]) -> None:
    """Write ``entries`` to the record."""
    write_json_atomic(
        path,
        {
            "entries": [
                {
                    **dict(entry.extra),
                    **{k: v for k, v in entry._asdict().items() if k != "extra"},
                    "depends_on": [l._asdict() for l in entry.depends_on],
                }
                for entry in entries
            ]
        },
    )


class LockHeld(Exception):
    """Another contribute run holds the record lock."""


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Hold an exclusive lock beside the record; raise ``LockHeld`` when another run has it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(f"{path.name}.lock").open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LockHeld("another contribute run is in progress") from error
        yield
