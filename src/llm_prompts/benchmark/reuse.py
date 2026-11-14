"""Reuse the finished agent runs of side A from an earlier run when nothing that shapes them changed."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from llm_prompts.benchmark import paths, saved
from llm_prompts.benchmark.types import (
    SCHEMA_VERSION,
    Cell,
    JsonValue,
    ResultRow,
    Scenario,
)

PART_NAMES = ("schema", "build", "agent", "model", "sandbox", "repeat", "scenario")
PART_DIGEST_CHARS = 12


def _tree_digest(root: Path) -> list[str]:
    return [
        f"{path.relative_to(root)}:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def _definition(scenario: Scenario) -> dict[str, JsonValue]:
    fields = asdict(scenario)
    for judged in ("gate", "base", "checks", "headline"):
        fields.pop(judged)
    for unset in ("setup", "delegation"):
        if not fields[unset]:
            fields.pop(unset)
    return {
        **fields,
        "workspace": _tree_digest(scenario.workspace)
        if scenario.workspace.is_dir()
        else [],
        "base": _definition(scenario.base) if scenario.base else None,
    }


def _digest(value: JsonValue | list[JsonValue]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def _parts(cell: Cell, model: str, os_sandbox: bool) -> list[JsonValue] | None:
    if cell.variant.build is None:
        return None
    build = cell.variant.build[cell.agent]
    return [
        SCHEMA_VERSION,
        [build, dict(cell.variant.env)] if cell.variant.env else build,
        cell.agent,
        model,
        os_sandbox,
        cell.repeat,
        _definition(cell.scenario),
    ]


def key(cell: Cell, model: str, os_sandbox: bool) -> str | None:
    """Return a digest of everything that shapes the cell's agent run, or None if its build is not pinned.

    The checks and the judge are left out, because they run again on a reused cell.
    """
    parts = _parts(cell, model, os_sandbox)
    return None if parts is None else _digest(parts)


def parts(cell: Cell, model: str, os_sandbox: bool) -> dict[str, str] | None:
    """Return a short digest per named part of the key, for finding what differs between two runs."""
    values = _parts(cell, model, os_sandbox)
    if values is None:
        return None
    return {
        name: _digest(value)[:PART_DIGEST_CHARS]
        for name, value in zip(PART_NAMES, values, strict=True)
    }


def closest_differences(
    cell: Cell, current: Mapping[str, str], prior: Sequence[ResultRow]
) -> tuple[str, list[str]] | None:
    """Return the run id and the part names that differ for the earlier row of ``cell`` that differs least."""
    best: tuple[str, list[str]] | None = None
    for row in prior:
        earlier = row.reuse_parts
        if (
            row.variant != cell.variant.label
            or row.cell_id != cell.id
            or earlier is None
        ):
            continue
        differing = [
            name for name, value in current.items() if earlier.get(name) != value
        ]
        if best is None or len(differing) <= len(best[1]):
            best = row.run_id, differing
    return best


def load() -> list[ResultRow]:
    """Return the rows of every past run, oldest run first."""
    return [
        ResultRow.from_json(json.loads(line))
        for path in paths.past_results()
        for line in path.read_text().splitlines()
        if line
    ]


def origin(row: ResultRow) -> str:
    """Return the id of the run whose agent run ``row`` holds."""
    return row.reused_from or row.run_id


def cell_dir(row: ResultRow) -> Path:
    """Return the folder holding the saved agent run of ``row``."""
    return paths.run_dir(row.run_id) / "cells" / row.cell_id


def select(
    cells: Sequence[Cell],
    prior: Sequence[ResultRow],
    key_of: Callable[[Cell], str | None],
) -> dict[str, ResultRow]:
    """Return the earlier row by cell id for each chain that a single earlier run finished cleanly on the same side with the same keys.

    A base cell and its follow-ups are reused together or not at all, from the latest such run.
    """
    finished: dict[tuple[str, str], dict[str, ResultRow]] = {}
    for row in prior:
        if row.reuse_key and row.error is None and saved.exists(cell_dir(row)):
            finished.setdefault((row.variant, row.run_id), {})[row.reuse_key] = row
    chains: dict[tuple[str, str, int, str], list[Cell]] = defaultdict(list)
    for cell in cells:
        chain = cell.variant.label, cell.agent, cell.repeat, cell.scenario.root.id
        chains[chain].append(cell)
    reused: dict[str, ResultRow] = {}
    for (side, *_), chain_cells in chains.items():
        keys = [key_of(cell) or "" for cell in chain_cells]
        for (variant, _), rows in reversed(finished.items()):
            if variant == side and all(key in rows for key in keys):
                reused |= {
                    cell.id: rows[key]
                    for cell, key in zip(chain_cells, keys, strict=True)
                }
                break
    return reused
