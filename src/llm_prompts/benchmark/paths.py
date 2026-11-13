"""Directories the benchmark reads and writes, always under the real home."""

from __future__ import annotations

import os
import secrets
import tempfile
from datetime import datetime
from pathlib import Path

CELL_ROOT_PREFIX = "llm-prompts-bench-"
SHARED_ROOT_PREFIX = "llm-prompts-bench-shared-"
CELL_MOUNT_NAME = "llm-prompts-bench-cell"
WORK_DIR_NAME = "llm-prompts-benchmark-cells"
MOUNT_TABLE = Path("/proc/self/mounts")
RAM_FILESYSTEMS = ("tmpfs", "ramfs")


def live_home() -> Path:
    """Return the user's real home directory, ignoring any install root."""
    return Path.home()


def state_dir() -> Path:
    """Return the directory holding benchmark run output."""
    return live_home() / ".local" / "state" / "llm-prompts" / "benchmark"


def cache_dir() -> Path:
    """Return the directory holding cached variants."""
    return live_home() / ".cache" / "llm-prompts" / "benchmark"


def runs_dir() -> Path:
    """Return the directory holding one folder per run."""
    return state_dir() / "runs"


def run_dir(run_id: str) -> Path:
    """Return the directory of the run ``run_id``."""
    return runs_dir() / run_id


def variants_dir() -> Path:
    """Return the directory holding one cache folder per variant."""
    return cache_dir() / "variants"


def variant_dir(key: str) -> Path:
    """Return the cache directory for the variant ``key``."""
    return variants_dir() / key


def past_results() -> list[Path]:
    """Return every existing results file, oldest run first."""
    return sorted(runs_dir().glob("*/results.jsonl"), key=lambda p: p.parent.name)


def new_run_id(now: datetime | None = None) -> str:
    """Return a run id of the form ``YYYYMMDD-HHMM-<4 hex chars>``."""
    return f"{(now or datetime.now()):%Y%m%d-%H%M}-{secrets.token_hex(2)}"


def _on_ram(path: Path) -> bool:
    """Return whether ``path`` is on a RAM filesystem."""
    if not MOUNT_TABLE.is_file():
        return False
    real = path.resolve()
    mounts = [line.split()[1:3] for line in MOUNT_TABLE.read_text().splitlines()]
    _, kind = max(
        (m for m in mounts if real.is_relative_to(m[0])),
        key=lambda m: len(m[0]),
        default=("/", ""),
    )
    return kind in RAM_FILESYSTEMS


def work_dir() -> Path:
    """Create and return the on-disk directory holding the cell roots.

    It is under ``$TMPDIR`` when that is set and not on a RAM filesystem, else under the cache directory.
    """
    tmp = Path(os.environ.get("TMPDIR", ""))
    on_disk = tmp.is_absolute() and tmp.is_dir() and not _on_ram(tmp)
    root = tmp / WORK_DIR_NAME if on_disk else cache_dir() / "cells"
    root.mkdir(parents=True, exist_ok=True)
    return root


def new_cell_root() -> Path:
    """Create and return a new empty directory for one cell."""
    return Path(
        tempfile.mkdtemp(prefix=f"{CELL_ROOT_PREFIX}{os.getpid()}-", dir=work_dir())
    )


def new_shared_root() -> Path:
    """Create and return a new empty directory for the folders cells share."""
    return Path(
        tempfile.mkdtemp(prefix=f"{SHARED_ROOT_PREFIX}{os.getpid()}-", dir=work_dir())
    )


def cell_mount() -> Path:
    """Create and return the fixed path at which every sandboxed cell sees its root."""
    mount = Path(tempfile.gettempdir()).resolve() / CELL_MOUNT_NAME
    mount.mkdir(exist_ok=True)
    return mount
