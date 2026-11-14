"""The record of worktree branches that ``contribute`` manages."""

from __future__ import annotations

import fcntl
import json
import os
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

    ``base`` is the lower commit a same-repo stacked branch sits on.
    ``dropped_refs`` are refs of removed links whose Depends on line sync wrote
    and has not yet taken out of the PR body.
    ``copied`` is the author time and subject of the first commit when sync last
    copied the branch into local main.
    ``why`` is the text sync puts under Why when it opens the PR.
    ``title`` is the PR title sync last wrote, so a title edited since is kept.
    """

    repo: str
    branch: str
    path: str
    pr: int | None
    pr_state: str | None
    remote_head: str | None
    ready: bool = False
    depends_on: tuple[Link, ...] = ()
    base: str | None = None
    dropped_refs: tuple[str, ...] = ()
    copied: str | None = None
    why: str = ""
    title: str = ""


def record_path() -> Path:
    """Return the record file, overridable through ``RECORD_ENV``."""
    override = os.environ.get(RECORD_ENV)
    return (
        Path(override) if override else home.config_dir() / "contribute-worktrees.json"
    )


def _entry_from_json(data: dict[str, Any]) -> WorktreeEntry:
    return WorktreeEntry(
        **{
            **data,
            "depends_on": tuple(Link(**link) for link in data.get("depends_on", ())),
            "dropped_refs": tuple(data.get("dropped_refs", ())),
        }
    )


def load_entries(path: Path) -> list[WorktreeEntry]:
    """Read the recorded entries; a missing record holds none.

    Raises:
        CorruptRecord: The record was unreadable and has been renamed aside.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [_entry_from_json(entry) for entry in data["entries"]]
    except (OSError, ValueError, TypeError, KeyError) as error:
        aside = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%dT%H%M%S')}")
        path.replace(aside)
        raise CorruptRecord(
            f"{path} is unreadable and was renamed to {aside.name}; "
            "rebuild it with: llm-prompts contribute sync --rescan"
        ) from error


def save_entries(path: Path, entries: list[WorktreeEntry]) -> None:
    """Write ``entries`` to the record."""
    write_json_atomic(
        path,
        {
            "entries": [
                {
                    **entry._asdict(),
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
