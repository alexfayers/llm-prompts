"""Save what a finished cell produced and load it again, so its checks can run again."""

from __future__ import annotations

import fnmatch
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from llm_prompts.benchmark.types import (
    MemoryEntity,
    PrefixRead,
    Tokens,
    ToolCall,
    Trace,
)

TRACE = "trace.json"
MEMORY = "memory.json"
WORKSPACE = "workspace"
SKIPPED_WORKSPACE = shutil.ignore_patterns(
    "__pycache__", "node_modules", ".venv", ".pytest_cache"
)


def _skipped(directory: str, names: list[str]) -> set[str]:
    """Return the ``names`` in ``directory`` to leave out of a saved workspace, with git's lock files."""
    git_locks = (
        fnmatch.filter(names, "*.lock") if ".git" in Path(directory).parts else []
    )
    return {*SKIPPED_WORKSPACE(directory, names), *git_locks}


@dataclass(frozen=True)
class Saved:
    trace: Trace
    workspace: Path
    memory_before: tuple[MemoryEntity, ...]
    memory_after: tuple[MemoryEntity, ...]


def _entities(items: list[dict[str, Any]]) -> tuple[MemoryEntity, ...]:
    return tuple(
        MemoryEntity(
            item["name"],
            item["entity_type"],
            tuple(item["observations"]),
            tuple((target, kind) for target, kind in item["relations"]),
            item["status"],
            item.get("location"),
        )
        for item in items
    )


def exists(cell_dir: Path) -> bool:
    """Return whether ``cell_dir`` holds everything needed to run the checks again."""
    return all((cell_dir / name).exists() for name in (TRACE, MEMORY, WORKSPACE))


def write(
    cell_dir: Path,
    workspace: Path,
    trace: Trace,
    memory_before: tuple[MemoryEntity, ...],
    memory_after: tuple[MemoryEntity, ...],
) -> None:
    """Save the trace, memory before and after, and workspace files into ``cell_dir``."""
    (cell_dir / TRACE).write_text(json.dumps(asdict(trace)))
    (cell_dir / MEMORY).write_text(
        json.dumps(
            {
                "before": [asdict(entity) for entity in memory_before],
                "after": [asdict(entity) for entity in memory_after],
            }
        )
    )
    shutil.copytree(
        workspace,
        cell_dir / WORKSPACE,
        symlinks=True,
        ignore=_skipped,
        dirs_exist_ok=True,
    )


def load(cell_dir: Path) -> Saved:
    """Load what ``write`` saved in ``cell_dir``."""
    raw = json.loads((cell_dir / TRACE).read_text())
    memory = json.loads((cell_dir / MEMORY).read_text())
    trace = Trace(
        **{
            **raw,
            "tool_calls": tuple(ToolCall(**call) for call in raw["tool_calls"]),
            "tokens": Tokens(**raw["tokens"]),
            "prefix_reads": tuple(
                PrefixRead(**read) for read in raw.get("prefix_reads", ())
            ),
            "fork_start_contexts": tuple(raw.get("fork_start_contexts", ())),
            "fork_start_s": tuple(raw.get("fork_start_s", ())),
        }
    )
    return Saved(
        trace,
        cell_dir / WORKSPACE,
        _entities(memory["before"]),
        _entities(memory["after"]),
    )
