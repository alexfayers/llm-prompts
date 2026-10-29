"""Estimate the disk a benchmark run needs and check the cell directory has it."""

from __future__ import annotations

import os
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from llm_prompts.benchmark import paths
from llm_prompts.benchmark.agents import AGENTS
from llm_prompts.benchmark.types import Cell

SAFETY_FACTOR = 2


class DiskShort(RuntimeError):
    """The cell directory cannot hold even one cell at a time."""


@dataclass(frozen=True)
class Footprint:
    bytes: int
    inodes: int

    def __add__(self, other: Footprint) -> Footprint:
        return Footprint(self.bytes + other.bytes, self.inodes + other.inodes)

    def times(self, count: float) -> Footprint:
        """Return this footprint scaled by ``count``, rounded up."""
        return Footprint(
            -int(-self.bytes * count // 1), -int(-self.inodes * count // 1)
        )


RUN_ALLOWANCE = Footprint(10_000_000, 500)


def measure(root: Path, skip: Collection[Path] = ()) -> Footprint:
    """Return the file bytes and inodes of ``root`` and everything under it, links not followed and ``skip`` left out."""
    footprint = Footprint(0, 0)
    for directory, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if Path(directory, name) not in skip]
        for name in (*dirs, *files):
            path = Path(directory, name)
            size = 0 if path.is_symlink() or path.is_dir() else path.stat().st_size
            footprint += Footprint(size, 1)
    return footprint + Footprint(0, 1)


def peak_roots(chain_sizes: Iterable[int], jobs: int) -> int:
    """Return the most cell roots that exist at once: the ``jobs`` largest chains, each holding all its cells."""
    return sum(sorted(chain_sizes, reverse=True)[:jobs])


@dataclass(frozen=True)
class Free:
    bytes: int
    inodes: float


def free_space() -> Free:
    """Return the free bytes and inodes of the filesystem holding the cell directory."""
    stat = os.statvfs(paths.work_dir())
    return Free(
        stat.f_bavail * stat.f_frsize, stat.f_favail if stat.f_files else float("inf")
    )


def fit(
    cell: Footprint, shared: Footprint, chain_sizes: Sequence[int], jobs: int
) -> int:
    """Return the largest number of jobs, at most ``jobs``, whose cells fit in the free disk with room to spare.

    Raises DiskShort when one job does not fit.
    """
    free = free_space()
    for count in range(jobs, 0, -1):
        needed = cell.times(peak_roots(chain_sizes, count) * SAFETY_FACTOR) + shared
        if needed.bytes <= free.bytes and needed.inodes <= free.inodes:
            return count
    needed = cell.times(peak_roots(chain_sizes, 1) * SAFETY_FACTOR) + shared
    raise DiskShort(
        f"Not enough disk in {paths.work_dir()} for one cell at a time:"
        f" needs about {needed.bytes / 2**20:,.0f} MB and {needed.inodes:,} inodes,"
        f" has {free.bytes / 2**20:,.0f} MB and {free.inodes:,.0f} inodes free."
        " Free some space, or set TMPDIR to a directory on a bigger disk."
    )


def estimate(cells: Sequence[Cell]) -> tuple[Footprint, Footprint]:
    """Return the footprint of the largest cell and of the folders all cells share."""
    cell, shared = Footprint(0, 0), Footprint(0, 0)
    templates: set[Path] = set()
    for one in cells:
        template = one.variant.templates[one.agent]
        folders = [template / folder for folder in AGENTS[one.agent].shared_dirs]
        own = (
            measure(template, skip=folders)
            + measure(one.scenario.workspace)
            + RUN_ALLOWANCE
        )
        cell = Footprint(max(cell.bytes, own.bytes), max(cell.inodes, own.inodes))
        if template not in templates:
            templates.add(template)
            shared += _measure_all(folders)
    packages = {AGENTS[one.agent].git_packages for one in cells} - {None}
    shared += _measure_all(paths.live_home() / folder for folder in packages if folder)
    return cell, shared


def _measure_all(folders: Iterable[Path]) -> Footprint:
    return sum((measure(f) for f in folders if f.is_dir()), Footprint(0, 0))
