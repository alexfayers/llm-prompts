"""Load, check and save the config file, keeping its comments and layout."""

from __future__ import annotations

import fcntl
import itertools
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import tomlkit
from tomlkit import TOMLDocument

from .exit_reason import ExitReason
from .jsonfile import write_text_atomic
from .setup import config_path, read_config


class LoadedConfig(NamedTuple):
    """An editable config document and the file text it was loaded from."""

    doc: TOMLDocument
    text: str | None


def _read_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def load_doc() -> LoadedConfig:
    """Return the config file as an editable document, or an empty one if absent.

    Raises:
        ExitReason: ``config_invalid`` when the file is not valid TOML.
    """
    read_config()
    text = _read_text(config_path())
    return LoadedConfig(
        tomlkit.document() if text is None else tomlkit.parse(text), text
    )


@contextmanager
def _locked_dir(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on the directory at ``path``."""
    path.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _backup_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def _reserve_backup(path: Path) -> Path:
    """Create and return an empty owner-only backup file for ``path`` with a name no other backup has."""
    stamp = _backup_stamp()
    for index in itertools.count():
        suffix = f"-{index}" if index else ""
        backup = path.with_name(f"{path.name}.bak-{stamp}{suffix}")
        try:
            os.close(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        except FileExistsError:
            continue
        return backup
    raise AssertionError("unreachable")


def save_doc(loaded: LoadedConfig) -> bool:
    """Write the edited document to the config file, first copying an existing file to a backup.

    Returns:
        True if the file changed, False if the document matched it already.

    Raises:
        ExitReason: ``config_changed`` when the file changed since it was loaded.
    """
    path = config_path()
    text = tomlkit.dumps(loaded.doc)
    with _locked_dir(path.parent):
        current = _read_text(path)
        if current != loaded.text:
            raise ExitReason(
                "config_changed",
                f"{path} changed since it was loaded. Reload it and try again.",
            )
        if current == text:
            return False
        if current is not None:
            shutil.copy2(path, _reserve_backup(path))
        write_text_atomic(path, text)
    return True
