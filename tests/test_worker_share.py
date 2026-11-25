"""Tests for sharing CPU cores between concurrent pytest runs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from worker_share import (
    SharedScheduling,
    available_cores,
    register_run,
    release_run,
    start_workers,
    worker_limit,
)

CORES = 32


@pytest.fixture(autouse=True)
def _no_share_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the share settings the calling test run was started with."""
    monkeypatch.delenv("TEST_RUNS_ALONGSIDE", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_AUTO_NUM_WORKERS", raising=False)


_HOLD_LOCK = """
import fcntl, sys
handle = open(sys.argv[1], "w")
fcntl.flock(handle, fcntl.LOCK_EX)
print("locked", flush=True)
sys.stdin.read()
"""


def test_a_single_run_uses_every_core(tmp_path: Path) -> None:
    register_run(tmp_path, os.getpid())
    assert worker_limit(tmp_path, CORES) == CORES


def test_the_cores_are_split_by_the_active_runs(tmp_path: Path) -> None:
    register_run(tmp_path, os.getpid())
    register_run(tmp_path, os.getppid())
    assert worker_limit(tmp_path, CORES) == CORES // 2


def test_a_run_started_alongside_other_test_runners_counts_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_RUNS_ALONGSIDE", "1")
    register_run(tmp_path, os.getpid())
    assert worker_limit(tmp_path, CORES) == CORES // 2


def test_auto_workers_start_at_the_runs_share(tmp_path: Path) -> None:
    register_run(tmp_path, os.getppid())
    assert start_workers(tmp_path, CORES) == CORES // 2


def test_auto_workers_follow_pytest_xdist_auto_num_workers_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "3")
    assert start_workers(tmp_path, CORES) == 3


def test_the_share_never_drops_below_two(tmp_path: Path) -> None:
    register_run(tmp_path, os.getpid())
    register_run(tmp_path, os.getppid())
    assert worker_limit(tmp_path, 2) == 2


def test_a_leftover_file_with_no_lock_no_longer_counts_and_is_removed(
    tmp_path: Path,
) -> None:
    register_run(tmp_path, os.getpid())
    (tmp_path / str(os.getppid())).touch()
    assert worker_limit(tmp_path, CORES) == CORES
    assert [p.name for p in tmp_path.iterdir()] == [str(os.getpid())]


def test_a_file_that_is_not_a_run_is_skipped(tmp_path: Path) -> None:
    register_run(tmp_path, os.getpid())
    (tmp_path / "notes").touch()
    assert worker_limit(tmp_path, CORES) == CORES
    assert (tmp_path / "notes").exists()


@pytest.mark.real_io
def test_a_run_in_another_process_counts_until_it_ends(tmp_path: Path) -> None:
    register_run(tmp_path, os.getpid())
    other = tmp_path / "1"
    process = subprocess.Popen(
        [sys.executable, "-c", _HOLD_LOCK, str(other)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout and process.stdout.readline() == "locked\n"
    assert worker_limit(tmp_path, CORES) == CORES // 2
    process.communicate("")
    assert worker_limit(tmp_path, CORES) == CORES


def test_the_cores_are_those_the_process_may_run_on() -> None:
    expected = (
        len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else os.cpu_count()
    )
    assert available_cores() == expected


def test_releasing_frees_the_share(tmp_path: Path) -> None:
    register_run(tmp_path, os.getpid())
    release_run(tmp_path, os.getpid())
    assert list(tmp_path.iterdir()) == []


def test_only_as_many_workers_get_tests_as_the_share_allows(tmp_path: Path) -> None:
    config = MagicMock()
    config.getvalue.return_value = ["4*popen"]
    scheduler = SharedScheduling(config)
    scheduler.run_dir, scheduler.cores = tmp_path, 4
    register_run(tmp_path, os.getpid())
    register_run(tmp_path, os.getppid())
    nodes = [MagicMock(shutting_down=False) for _ in range(4)]
    for node in nodes:
        scheduler.add_node(node)
    scheduler.pending[:] = range(40)
    scheduler.check_schedule()
    assert [bool(scheduler.node2pending[node]) for node in nodes] == [
        True,
        True,
        False,
        False,
    ]
