"""Copy a tool's files from its old folders into its folder under the shared root, once."""

from __future__ import annotations

import errno
import fcntl
import os
import shutil
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .jsonfile import write_json_atomic

RECORD = "migrated.json"


def _publish_copy(old: Path, new: Path) -> None:
    """Copy the file or symlink ``old`` to ``new``, unless ``new`` exists.

    The copy is written to a scratch file first and linked into place, so ``new``
    never holds a partial copy and a file created at ``new`` meanwhile is kept.
    """
    if old.is_symlink():
        os.symlink(os.readlink(old), new)
        return
    handle, scratch = tempfile.mkstemp(prefix=f".{new.name}.", dir=new.parent)
    os.close(handle)
    try:
        shutil.copy2(old, scratch)
        os.link(scratch, new)
    finally:
        os.unlink(scratch)


def _private_dir(path: Path) -> None:
    """Make sure ``path`` is a real folder, creating it as ``0700``.

    Raises:
        OSError: ``path`` is a symlink or not a folder.
    """
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        if path.is_symlink() or not path.is_dir():
            raise NotADirectoryError(
                errno.ENOTDIR, "not a real folder", str(path)
            ) from None


def _private_dirs(tool_root: Path, path: Path) -> None:
    """Make each folder from ``tool_root`` down to ``path`` a real folder.

    Raises:
        OSError: A folder on the way is a symlink or not a folder.
    """
    relative = path.relative_to(tool_root)
    for folder in (*reversed(relative.parents), relative):
        _private_dir(tool_root / folder)


def _copy_missing(old: Path, new: Path) -> None:
    """Copy each file under ``old`` whose place under ``new`` is free.

    ``new.parent`` MUST already be a real folder.

    Raises:
        OSError: A file could not be copied. The others are still copied.
    """
    failed: OSError | None = None
    if old.is_dir() and not old.is_symlink():
        _private_dir(new)
        for child in sorted(old.iterdir()):
            try:
                _copy_missing(child, new / child.name)
            except OSError as error:
                failed = error
    elif not os.path.lexists(new):
        try:
            _publish_copy(old, new)
        except FileExistsError:
            pass
    if failed:
        raise failed


def migrate(tool_root: Path, copies: Iterable[tuple[Path, Path]]) -> None:
    """Copy each existing old path to its new path, unless ``tool_root`` records a finished run.

    Each new path MUST sit under ``tool_root``. Folders the copy creates are ``0700``,
    and a symlink on the way to a new path stops that copy.
    Old files stay in place and an existing new file is never overwritten.
    A failed copy leaves the run unrecorded, so the next run copies what is still missing.
    """
    record = tool_root / RECORD
    if record.exists():
        return
    tool_root.parent.mkdir(parents=True, exist_ok=True)
    _private_dir(tool_root)
    lock = os.open(
        tool_root / ".migrate.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(lock) as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        if record.exists():
            return
        copied: dict[str, str] = {}
        failed = False
        for old, new in copies:
            if not os.path.lexists(old):
                continue
            try:
                _private_dirs(tool_root, new.parent)
                _copy_missing(old, new)
            except OSError:
                failed = True
                continue
            copied[str(old)] = str(new)
        if not failed:
            write_json_atomic(
                record, {"date": datetime.now(UTC).isoformat(), "copied": copied}
            )
