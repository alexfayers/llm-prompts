"""Copy a tool's files from its old folders into its folders under the shared root."""

from __future__ import annotations

import errno
import fcntl
import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path


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


def _copy_missing(old: Path, new: Path, ancestors: tuple[Path, ...] = ()) -> None:
    """Copy each file under ``old`` to ``new``.

    ``new.parent`` MUST already be a real folder. Symlinks are copied as the file they point to,
    so a copy never leads back to ``old``.

    Raises:
        OSError: A file could not be copied, or a folder holds the other or links back to itself.
            The other files are still copied.
    """
    failed: OSError | None = None
    if old.is_dir():
        real_old, real_new = old.resolve(), new.resolve()
        if real_old in ancestors or real_old.is_relative_to(real_new):
            raise OSError(errno.ELOOP, "folder holds itself", str(old))
        if real_new.is_relative_to(real_old):
            raise OSError(errno.EINVAL, "destination is inside the source", str(old))
        _private_dir(new)
        for child in sorted(old.iterdir()):
            try:
                _copy_missing(child, new / child.name, (*ancestors, real_old))
            except OSError as error:
                failed = error
    elif old.exists():
        shutil.copy2(old, new)
    if failed:
        raise failed


def _is_free(final: Path) -> bool:
    """Return whether nothing, or only an empty folder, is at ``final``."""
    return not os.path.lexists(final) or (
        final.is_dir() and not final.is_symlink() and not any(final.iterdir())
    )


def _is_ready(final: Path) -> bool:
    """Return whether ``final`` is a real folder holding something."""
    return final.is_dir() and not final.is_symlink() and any(final.iterdir())


def _kind_of(tool_root: Path, path: Path) -> str:
    return path.relative_to(tool_root).parts[0]


def unready_kinds(tool_root: Path, copies: Iterable[tuple[Path, Path]]) -> set[str]:
    """Return the folders of ``tool_root`` that have an old path to copy and are not ready.

    A folder is ready when it is a real folder that holds something. A file, a symlink or a
    folder that cannot be read is not ready, and is not copied over.
    """
    kinds = {_kind_of(tool_root, new) for old, new in copies if os.path.lexists(old)}
    ready = set()
    for kind in kinds:
        try:
            if _is_ready(tool_root / kind):
                ready.add(kind)
        except OSError:
            pass
    return kinds - ready


def _publish_kind(
    tool_root: Path, kind: str, copies: list[tuple[Path, Path]]
) -> str | None:
    """Copy the old paths into a temporary folder, then rename it to ``tool_root / kind``.

    The temporary folder is next to its final path and only this call removes it.
    An empty folder at the final path is removed first, and a folder that is not empty is kept.

    Returns:
        Why the folder was not published, or None when it was.
    """
    final = tool_root / kind
    staging = Path(tempfile.mkdtemp(prefix=f".{kind}.{os.getpid()}-", dir=tool_root))
    try:
        for old, new in copies:
            target = staging / new.relative_to(final)
            _private_dirs(staging, target.parent)
            _copy_missing(old, target)
        if not _is_free(final):
            return f"{final} is not empty or not a real folder"
        if os.path.lexists(final):
            os.rmdir(final)
        # shortcut: Linux rename also replaces an empty folder created since the check above, nothing is lost, upgrade with renameat2 RENAME_NOREPLACE
        os.rename(staging, final)
    except OSError as error:
        return f"{error.filename or final}: {error.strerror or error}"
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return None


def migrate(tool_root: Path, copies: Iterable[tuple[Path, Path]]) -> dict[str, str]:
    """Copy the old paths of each free folder of ``tool_root`` to their new paths.

    Each new path MUST sit under a folder of ``tool_root``. A folder is copied as a whole,
    only where nothing or an empty folder is, and made ``0700`` along with the folders in it.
    Old files stay in place and nothing at a new path is overwritten or removed.
    A folder that fails keeps its old paths in use and is tried again by the next run.
    Each folder is handled on its own, so a failure never undoes another folder.

    Returns:
        The reason for each folder that was not published, keyed by folder name.

    Raises:
        OSError: ``tool_root`` or its lock file could not be set up.
    """
    copies = list(copies)
    failures: dict[str, str] = {}
    free = []
    for kind in unready_kinds(tool_root, copies):
        try:
            is_free = _is_free(tool_root / kind)
        except OSError as error:
            failures[kind] = f"{tool_root / kind}: {error.strerror or error}"
            continue
        if is_free:
            free.append(kind)
        else:
            failures[kind] = f"{tool_root / kind} is not a real folder"
    if not free:
        return failures
    tool_root.parent.mkdir(parents=True, exist_ok=True)
    _private_dir(tool_root)
    lock = os.open(
        tool_root / ".migrate.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(lock) as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        for kind in free:
            reason = _publish_kind(
                tool_root,
                kind,
                [
                    (old, new)
                    for old, new in copies
                    if os.path.lexists(old) and _kind_of(tool_root, new) == kind
                ],
            )
            if reason:
                failures[kind] = reason
    return failures
