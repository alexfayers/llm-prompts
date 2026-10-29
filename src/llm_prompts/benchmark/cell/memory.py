"""Sandbox mcp-memory server, its DB readers and memory-use metrics."""

from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import time
import urllib.request
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_prompts.benchmark.types import (
    JsonValue,
    MemoryEntity,
    MemoryHandle,
    MemoryMetrics,
    ToolCall,
    Trace,
)

START_TIMEOUT_S = 30
STOP_TIMEOUT_S = 10
POLL_INTERVAL_S = 0.05
REQUEST_TIMEOUT_S = 30
CALLED_AT_FORMAT = "%Y-%m-%d %H:%M:%S"
MEMORY_TOOL_PREFIX = "memory."
READ_TOOLS: frozenset[str] = frozenset(
    {
        "search_nodes",
        "read_graph",
        "get_entity_with_relations",
        "search_all_projects",
        "list_metadata",
    }
)
EDIT_TOOLS: frozenset[str] = frozenset({"Edit", "Write"})
VALID_TYPES: frozenset[str] = frozenset(
    {"project", "feature", "task", "user-preferences", "pattern", "knowledge"}
)


class MemoryStartError(Exception):
    """The server did not accept connections in time, or refused the seed."""


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _check_alive(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        raise MemoryStartError(f"mcp-memory exited with code {process.returncode}")


def _wait_until_listening(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + START_TIMEOUT_S
    while True:
        _check_alive(process)
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise MemoryStartError(
                    f"mcp-memory did not listen on port {port}"
                ) from None
            time.sleep(POLL_INTERVAL_S)
    _check_alive(process)


def _call_tool(url: str, tool: str, arguments: dict[str, Any]) -> None:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        reply: dict[str, Any] = json.loads(response.read())
    result: dict[str, Any] = reply.get("result", {})
    error = reply.get("error") or result.get("structuredContent", {}).get("error")
    if error or result.get("isError"):
        raise MemoryStartError(f"mcp-memory {tool} failed: {error or result}")


def _seed(
    handle: MemoryHandle,
    seed: tuple[MemoryEntity, ...],
    project: str,
    workspace: Path,
) -> None:
    entities = [
        {
            "name": entity.name,
            "entityType": entity.entity_type,
            "observations": list(entity.observations),
            "relations": [
                {"target": target, "type": kind} for target, kind in entity.relations
            ],
            "status": entity.status,
        }
        for entity in seed
    ]
    _call_tool(
        handle.url, "create_entities", {"project": project, "entities": entities}
    )
    _call_tool(
        handle.url,
        "set_metadata",
        {"project": project, "kind": "paths", "add": [str(workspace)]},
    )


def clear_tool_calls(handle: MemoryHandle) -> None:
    """Delete the tool calls the server has recorded."""
    with closing(sqlite3.connect(handle.db)) as db:
        db.execute("DELETE FROM tool_calls")
        db.commit()


def copy_database(handle: MemoryHandle, target: Path) -> None:
    """Copy the database of a running server to ``target``."""
    with (
        closing(_open_read_only(handle)) as source,
        closing(sqlite3.connect(target)) as copy,
    ):
        source.backup(copy)


def _stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@contextmanager
def start(
    home: Path,
    seed: tuple[MemoryEntity, ...] | None,
    project: str,
    workspace: Path,
    env: Mapping[str, str],
) -> Iterator[MemoryHandle]:
    """Start a sandbox memory server and yield its handle, seeding it with ``seed`` unless it is None."""
    port = _free_port()
    handle = MemoryHandle(
        url=f"http://127.0.0.1:{port}/mcp", port=port, db=home / "memory.db"
    )
    spawn_env = {**env, **handle.env()}
    with (home / "memory.log").open("wb") as log:
        process = subprocess.Popen(
            ["mcp-memory"], env=spawn_env, stdout=log, stderr=subprocess.STDOUT
        )
    try:
        _wait_until_listening(port, process)
        if seed is not None:
            _seed(handle, seed, project, workspace)
        clear_tool_calls(handle)
        yield handle
    finally:
        _stop(process)


def _open_read_only(handle: MemoryHandle) -> sqlite3.Connection:
    return sqlite3.connect(f"{handle.db.resolve().as_uri()}?mode=ro", uri=True)


def _live(db: sqlite3.Connection, table: str, alias: str) -> str:
    """Return a condition keeping live rows, which is always true where the table has no ``deleted_at``."""
    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    return f"{alias}.deleted_at IS NULL" if "deleted_at" in columns else "1"


def read_entities(handle: MemoryHandle) -> tuple[MemoryEntity, ...]:
    """Return the entities stored by the server."""
    with closing(_open_read_only(handle)) as db:
        live_observation = _live(db, "observations", "observations")
        live_relation = _live(db, "relations", "r")
        return tuple(
            MemoryEntity(
                name=name,
                entity_type=entity_type,
                observations=tuple(
                    content
                    for (content,) in db.execute(
                        "SELECT content FROM observations"
                        f" WHERE entity_id = ? AND {live_observation} ORDER BY id",
                        (entity_id,),
                    )
                ),
                relations=tuple(
                    db.execute(
                        "SELECT target.name, kind.name FROM relations r"
                        " JOIN entities target ON target.id = r.target_id"
                        " JOIN relation_types kind ON kind.id = r.relation_type_id"
                        f" WHERE r.source_id = ? AND {live_relation} ORDER BY r.id",
                        (entity_id,),
                    )
                ),
                status=status,
            )
            for entity_id, name, entity_type, status in db.execute(
                "SELECT e.id, e.name, t.name, e.status FROM entities e"
                " JOIN entity_types t ON t.id = e.entity_type_id"
                " WHERE e.deleted_at IS NULL ORDER BY e.name"
            ).fetchall()
        )


def _parse_options(options: str) -> Mapping[str, JsonValue]:
    try:
        parsed = json.loads(options)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def read_tool_calls(handle: MemoryHandle) -> tuple[ToolCall, ...]:
    """Return the tool calls the server has received, oldest first."""
    with closing(_open_read_only(handle)) as db:
        rows = db.execute(
            "SELECT tool, called_at, options FROM tool_calls ORDER BY called_at, id"
        ).fetchall()
    return tuple(
        ToolCall(
            name=f"memory.{tool}",
            args=_parse_options(options),
            ok=True,
            at=datetime.strptime(called_at, CALLED_AT_FORMAT)
            .replace(tzinfo=UTC)
            .timestamp(),
        )
        for tool, called_at, options in rows
    )


def _read_before_first_edit(names: list[str]) -> bool:
    for name in names:
        if name in EDIT_TOOLS:
            return False
        if (
            name.startswith(MEMORY_TOOL_PREFIX)
            and name.removeprefix(MEMORY_TOOL_PREFIX) in READ_TOOLS
        ):
            return True
    return False


def _is_invalid_name(entity: MemoryEntity) -> bool:
    return (
        not entity.name.startswith(f"{entity.entity_type}/")
        or entity.entity_type not in VALID_TYPES
    )


def observation_keys(entities: tuple[MemoryEntity, ...]) -> set[tuple[str, str]]:
    """Return the (entity name, observation) pairs of ``entities``."""
    return {(e.name, text) for e in entities for text in e.observations}


def _relations(entities: tuple[MemoryEntity, ...]) -> set[tuple[str, str, str]]:
    return {(e.name, target, kind) for e in entities for target, kind in e.relations}


def metrics(
    trace: Trace,
    before: tuple[MemoryEntity, ...],
    after: tuple[MemoryEntity, ...],
) -> MemoryMetrics:
    """Compute the memory metrics of a run from its trace and the memory before and after."""
    names = [call.name for call in trace.tool_calls]
    before_names = {entity.name for entity in before}
    added = [entity for entity in after if entity.name not in before_names]
    return MemoryMetrics(
        memory_calls=sum(name.startswith(MEMORY_TOOL_PREFIX) for name in names),
        read_before_first_edit=_read_before_first_edit(names),
        entities_added=len(added),
        observations_added=len(observation_keys(after) - observation_keys(before)),
        relations_added=len(_relations(after) - _relations(before)),
        invalid_names=sum(_is_invalid_name(entity) for entity in added),
    )
