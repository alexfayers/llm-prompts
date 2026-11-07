"""Scan a tree for references to the live claude, pi, llm-prompts and memory state."""

from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
import stat
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from llm_prompts.benchmark import paths
from llm_prompts.benchmark.cell.home_dirs import declared_home_dirs
from llm_prompts.benchmark.paths import live_home
from llm_prompts.benchmark.types import Trace

DEFAULT_PORT = 3000
PORT_HOSTS = ("localhost", "127.0.0.1")
THIRD_PARTY_DIRS = frozenset({"node_modules", "_cacache"})
SESSION_DIRS = (Path(".pi/agent/sessions"), Path(".claude/projects"))
WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


@dataclass(frozen=True)
class AuditHit:
    path: Path
    marker: str


def entries(root: Path) -> Iterator[Path]:
    for directory, dirs, files in os.walk(root):
        for name in (*dirs, *files):
            path = Path(directory, name)
            if not path.is_symlink():
                yield path
    yield root


def writable_entry(root: Path) -> Path | None:
    """Return the first file or folder under ``root`` that anyone can write to."""
    return next(
        (path for path in entries(root) if path.stat().st_mode & WRITE_BITS), None
    )


def _service_env() -> dict[str, str]:
    home = live_home()
    try:
        if sys.platform == "darwin":
            plist = home / "Library" / "LaunchAgents" / "com.mcp-memory.plist"
            env = plistlib.loads(plist.read_bytes()).get("EnvironmentVariables", {})
            return {str(key): str(value) for key, value in env.items()}
        unit = home / ".config" / "systemd" / "user" / "mcp-memory.service"
        pairs = (
            pair.partition("=")
            for line in unit.read_text().splitlines()
            if line.startswith("Environment=")
            for pair in shlex.split(line.removeprefix("Environment="))
        )
        return {key: value for key, _, value in pairs}
    except (OSError, ValueError, AttributeError):
        return {}


def live_memory() -> tuple[Path, int]:
    """Return the live memory database path and port."""
    env = _service_env()
    db_path = env.get("MCP_MEMORY_DB_PATH") or str(
        live_home() / ".memory" / "memory.db"
    )
    port = env.get("MCP_MEMORY_PORT", "")
    return Path(db_path), int(port) if port.isdecimal() else DEFAULT_PORT


def live_markers() -> tuple[str, ...]:
    """Return the strings that identify the live home, memory database and port."""
    home = live_home()
    db_path, port = live_memory()
    return (
        str(home / ".claude"),
        str(home / ".claude.json"),
        str(home / ".pi"),
        str(home / ".config" / "llm-prompts"),
        str(db_path),
        *(f"{host}:{port}" for host in PORT_HOSTS),
    )


def _matcher(marker: str) -> re.Pattern[bytes]:
    pattern = re.escape(marker.encode())
    if marker.rpartition(":")[2].isdecimal():
        pattern += rb"(?![0-9])"
    return re.compile(pattern)


def audit(
    root: Path, skip: Sequence[Path] = (), stores: Sequence[Path] = ()
) -> list[AuditHit]:
    """Return every place under ``root``, except under ``skip``, that refers to the live home or memory server.

    A link into one of the shared ``stores`` is a hit while anything in that store is writable.
    """
    live, declared = live_home(), declared_home_dirs()
    whole = {live / name for name in declared}
    markers = (
        *live_markers(),
        *(
            str(live / name / sub)
            for name, spec in declared.items()
            for sub in spec.empty
        ),
    )
    matchers = [(marker, _matcher(marker)) for marker in markers]
    writable = {store: writable_entry(store) for store in stores}
    hits: list[AuditHit] = []
    for path in root.rglob("*"):
        if any(path.is_relative_to(folder) for folder in skip):
            continue
        if path.is_symlink():
            content = os.readlink(path).encode()
            target = Path(os.path.normpath(path.parent / os.readlink(path)))
            if target in whole:
                hits.append(AuditHit(path, str(target)))
            hits.extend(
                AuditHit(path, f"writable {entry}")
                for store, entry in writable.items()
                if entry and target.is_relative_to(store)
            )
        elif path.is_file() and THIRD_PARTY_DIRS.isdisjoint(
            path.relative_to(root).parts
        ):
            content = path.read_bytes()
        else:
            continue
        hits.extend(
            AuditHit(path, marker)
            for marker, matcher in matchers
            if matcher.search(content)
        )
    return sorted(hits, key=lambda hit: (hit.path, hit.marker))


def _real_home_references(text: str) -> list[str]:
    homes = {str(live_home()), str(live_home().resolve())}
    pattern = re.compile(
        rf"(?<![\w./-])(?:{'|'.join(map(re.escape, homes))})(?![\w-])[^\s\\\"'`;|&<>()]*"
    )
    allowed = str(paths.cache_dir())
    return [ref for ref in pattern.findall(text) if not ref.startswith(allowed)]


def audit_trace(trace: Trace) -> list[AuditHit]:
    """Return the tool calls in ``trace`` that name the live home."""
    return [
        AuditHit(Path(call.name), ref)
        for call in trace.tool_calls
        for ref in _real_home_references(json.dumps(call.args))
    ]
