"""The benchmark checks the disk can hold the run before it starts."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from benchmark.conftest import SCENARIO
from llm_prompts.benchmark import disk, paths
from llm_prompts.benchmark.disk import DiskShort, Footprint
from llm_prompts.benchmark.types import Cell, Variant


def fake_free(
    monkeypatch: pytest.MonkeyPatch, free_bytes: int, free_inodes: int
) -> None:
    def statvfs(path: object) -> os.statvfs_result:
        return os.statvfs_result(
            (
                4096,
                4096,
                10**9,
                free_bytes // 4096,
                free_bytes // 4096,
                10**6,
                free_inodes,
                free_inodes,
                0,
                255,
            )
        )

    monkeypatch.setattr(os, "statvfs", statvfs)


@pytest.fixture(autouse=True)
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "work_dir", lambda: tmp_path)
    return tmp_path


def test_measure_counts_inodes_and_file_bytes_without_following_links_or_skipped_folders(
    tmp_path: Path,
) -> None:
    tree = tmp_path / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / "a.txt").write_text("x" * 10)
    (tree / "sub" / "b.txt").write_text("y" * 5)
    (tree / "link").symlink_to(tmp_path)
    (tree / "skipped").mkdir()
    (tree / "skipped" / "c.txt").write_text("z" * 100)

    assert disk.measure(tree, skip=(tree / "skipped",)) == Footprint(15, 5)


def test_peak_roots_is_the_sum_of_the_largest_chains_that_run_at_once() -> None:
    assert disk.peak_roots([1, 5, 2, 3], jobs=2) == 8
    assert disk.peak_roots([1], jobs=4) == 1


def test_fit_keeps_jobs_when_the_disk_has_room(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_free(monkeypatch, 10**12, 10**9)

    assert disk.fit(Footprint(1000, 10), Footprint(0, 0), [1] * 10, jobs=4) == 4


def test_fit_lowers_jobs_to_what_the_free_bytes_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cell = Footprint(10**6, 100)
    fake_free(monkeypatch, int(10**6 * disk.SAFETY_FACTOR * 3.5), 10**9)

    assert disk.fit(cell, Footprint(0, 0), [1] * 10, jobs=8) == 3


def test_fit_lowers_jobs_to_what_the_free_inodes_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_free(monkeypatch, 10**12, int(1000 * disk.SAFETY_FACTOR * 2.5))

    assert disk.fit(Footprint(10, 1000), Footprint(0, 0), [1] * 10, jobs=8) == 2


def test_fit_refuses_with_the_numbers_when_even_one_job_does_not_fit(
    monkeypatch: pytest.MonkeyPatch, work: Path
) -> None:
    fake_free(monkeypatch, 5 * 10**6, 10**9)

    with pytest.raises(DiskShort, match=rf"{work}.*free"):
        disk.fit(Footprint(10**7, 10), Footprint(0, 0), [1], jobs=1)


def test_fit_ignores_inodes_on_filesystems_that_report_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_free(monkeypatch, 10**12, 0)
    monkeypatch.setattr(
        os,
        "statvfs",
        lambda path: os.statvfs_result(
            (4096, 4096, 10**9, 10**9, 10**9, 0, 0, 0, 0, 255)
        ),
    )

    assert disk.fit(Footprint(10, 10**9), Footprint(0, 0), [1, 1], jobs=2) == 2


def test_estimate_counts_the_cell_without_shared_folders_and_the_shared_folders_once(
    tmp_path: Path, fake_variant: Variant, live_home: None
) -> None:
    template = fake_variant.templates["pi"]
    for name in (".pi/agent/npm/pkg.js", ".npm/cache", ".pi/agent/own.json"):
        (template / name).parent.mkdir(parents=True, exist_ok=True)
        (template / name).write_text("x" * 100)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "f.py").write_text("y" * 50)
    scenario = replace(SCENARIO, workspace=workspace)
    cells = [Cell(fake_variant, "pi", scenario, repeat) for repeat in range(3)]
    own_template = disk.measure(
        template, skip=[template / ".pi/agent/npm", template / ".npm"]
    )

    cell, shared = disk.estimate(cells)

    assert cell == own_template + Footprint(50, 2) + disk.RUN_ALLOWANCE
    assert shared == disk.measure(template / ".pi/agent/npm") + disk.measure(
        template / ".npm"
    )
