"""Share CPU cores between pytest runs that are active at the same time."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import IO, Any

from xdist.scheduler import WorkStealingScheduling  # type: ignore[import-untyped]

MIN_WORKERS = 2

_held: dict[Path, IO[str]] = {}


def available_cores() -> int:
    """The cores this process may run on."""
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def _is_running(run_file: Path) -> bool:
    """Whether a run holds the lock on ``run_file``, removing the file when none does."""
    with run_file.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        run_file.unlink(missing_ok=True)
        return False


def register_run(run_dir: Path, pid: int) -> None:
    """Hold a lock on this run's file until it is released or the process ends."""
    run_file = run_dir / str(pid)
    if run_file in _held:
        return
    run_dir.mkdir(parents=True, exist_ok=True)
    staged = run_dir / f".{pid}"
    handle = staged.open("a")
    fcntl.flock(handle, fcntl.LOCK_EX)
    staged.rename(run_file)
    _held[run_file] = handle


def release_run(run_dir: Path, pid: int) -> None:
    run_file = run_dir / str(pid)
    run_file.unlink(missing_ok=True)
    if handle := _held.pop(run_file, None):
        handle.close()


def worker_limit(run_dir: Path, cores: int) -> int:
    """The workers one run may keep busy: `cores` split between the active runs.

    ``TEST_RUNS_ALONGSIDE`` counts other test runners started with this run, such as node --test.
    """
    active = int(os.environ.get("TEST_RUNS_ALONGSIDE", "0")) + sum(
        _is_running(run_file)
        for run_file in list(run_dir.iterdir())
        if run_file.name.isdigit()
    )
    return max(MIN_WORKERS, cores // max(active, 1))


class SharedScheduling(WorkStealingScheduling):  # type: ignore[misc]
    """Gives tests only to the busiest workers, as many as the run's share allows."""

    run_dir: Path
    cores: int
    node2pending: dict[Any, list[int]]

    def check_schedule(self) -> None:
        all_nodes = self.node2pending
        busiest = sorted(all_nodes, key=lambda node: -len(all_nodes[node]))
        self.node2pending = {
            node: all_nodes[node]
            for node in busiest[: worker_limit(self.run_dir, self.cores)]
        }
        try:
            super().check_schedule()
        finally:
            self.node2pending = all_nodes


def start_workers(run_dir: Path, cores: int) -> int:
    """Register this run and return the workers ``-n auto`` starts: ``PYTEST_XDIST_AUTO_NUM_WORKERS`` when set, else the run's share."""
    register_run(run_dir, os.getpid())
    if wanted := os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS"):
        return int(wanted)
    return worker_limit(run_dir, cores)
