import io
import json
import socket
import sqlite3
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_prompts.benchmark.cell import memory
from llm_prompts.benchmark.types import MemoryEntity, MemoryHandle, ToolCall

SEED = (
    MemoryEntity(
        "knowledge/a", "knowledge", ("one",), (("project/demo", "part-of"),), "active"
    ),
)
SCHEMA = """
CREATE TABLE entity_types (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE relation_types (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT, entity_type_id INTEGER,
    status TEXT, deleted_at DATETIME);
CREATE TABLE relations (id INTEGER PRIMARY KEY, source_id INTEGER, target_id INTEGER,
    relation_type_id INTEGER, deleted_at DATETIME);
CREATE TABLE observations (id INTEGER PRIMARY KEY, entity_id INTEGER, content TEXT,
    deleted_at DATETIME);
CREATE TABLE tool_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, tool TEXT,
    called_at DATETIME DEFAULT CURRENT_TIMESTAMP, options TEXT DEFAULT '{}');
INSERT INTO entity_types VALUES (1, 'knowledge');
INSERT INTO relation_types VALUES (1, 'part-of');
INSERT INTO tool_calls (tool) VALUES ('seed');
"""


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    popen = MagicMock()
    popen.return_value.poll.return_value = None
    state: dict[str, Any] = {
        "listening": True,
        "reply": {},
        "requests": {},
        "popen": popen,
    }
    with sqlite3.connect(tmp_path / "memory.db") as db:
        db.executescript(SCHEMA)

    def connect(*_: Any, **__: Any) -> socket.socket:
        if not state["listening"]:
            raise OSError("refused")
        return socket.socket()

    def urlopen(request: urllib.request.Request, *_: Any, **__: Any) -> io.BytesIO:
        body = json.loads(request.data or b"{}")  # type: ignore[arg-type]
        name = body["params"]["name"]
        state["requests"][name] = body["params"]["arguments"]
        payload = {"result": {"structuredContent": state["reply"].get(name, {})}}
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(memory, "START_TIMEOUT_S", 0.2)
    return state


@pytest.mark.parametrize("failure", ["no-connection", "error-key", "exited"])
def test_start_raises_and_stops_process_when_not_ready(
    server: dict[str, Any], tmp_path: Path, failure: str
) -> None:
    server["listening"] = failure != "no-connection"
    if failure == "exited":
        server["popen"].return_value.poll.return_value = 1
    if failure == "error-key":
        server["reply"]["create_entities"] = {"error": "boom"}

    with (
        pytest.raises(memory.MemoryStartError),
        memory.start(tmp_path, SEED, "demo", tmp_path, {"PATH": "/bin"}),
    ):
        pass

    server["popen"].return_value.terminate.assert_called_once()


def test_server_seeds_then_readers_return_entities_and_tool_calls(
    server: dict[str, Any], tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    with memory.start(tmp_path, SEED, "demo", workspace, {"PATH": "/bin"}) as handle:
        assert server["popen"].call_args.kwargs["env"]["MCP_MEMORY_URL"] == handle.url
        with sqlite3.connect(handle.db) as db:
            assert db.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0] == 0
            db.executescript(
                """
                INSERT INTO entities VALUES (1, 'knowledge/a', 1, 'active', NULL);
                INSERT INTO entities VALUES (2, 'project/demo', 1, NULL, NULL);
                INSERT INTO observations VALUES (1, 1, 'one', NULL);
                INSERT INTO relations VALUES (1, 1, 2, 1, NULL);
                INSERT INTO tool_calls (tool, called_at, options)
                VALUES ('search_nodes', '2026-01-02 03:04:07', '{"project": "demo"}');
                INSERT INTO tool_calls (tool, called_at, options)
                VALUES ('read_graph', '2026-01-02 03:04:05', 'bad');
                """
            )
        entities = memory.read_entities(handle)
        calls = memory.read_tool_calls(handle)
    seeded = server["requests"]
    assert seeded["create_entities"]["entities"][0]["relations"] == [
        {"target": "project/demo", "type": "part-of"}
    ]
    assert seeded["set_metadata"]["add"] == [str(workspace)]
    assert entities[0] == SEED[0]
    epoch = datetime(2026, 1, 2, 3, 4, tzinfo=UTC).timestamp()
    assert calls == (
        ToolCall("memory.read_graph", {}, True, epoch + 5),
        ToolCall("memory.search_nodes", {"project": "demo"}, True, epoch + 7),
    )
    server["popen"].return_value.terminate.assert_called_once()


def test_read_entities_works_on_a_database_without_soft_delete_columns(
    tmp_path: Path,
) -> None:
    with sqlite3.connect(tmp_path / "memory.db") as db:
        db.executescript(
            """
            CREATE TABLE entity_types (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE relation_types (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT,
                entity_type_id INTEGER, status TEXT, deleted_at DATETIME);
            CREATE TABLE relations (id INTEGER PRIMARY KEY, source_id INTEGER,
                target_id INTEGER, relation_type_id INTEGER);
            CREATE TABLE observations (id INTEGER PRIMARY KEY, entity_id INTEGER,
                content TEXT);
            INSERT INTO entity_types VALUES (1, 'knowledge');
            INSERT INTO entities VALUES (1, 'knowledge/a', 1, NULL, NULL);
            INSERT INTO observations VALUES (1, 1, 'one');
            """
        )
    handle = MemoryHandle(url="", port=0, db=tmp_path / "memory.db")

    (entity,) = memory.read_entities(handle)

    assert entity.observations == ("one",)


def test_restarted_server_keeps_the_database_and_drops_its_tool_calls(
    server: dict[str, Any], tmp_path: Path
) -> None:
    with sqlite3.connect(tmp_path / "memory.db") as db:
        db.execute("INSERT INTO observations VALUES (1, 1, 'kept', NULL)")
    copy = tmp_path / "copy"
    copy.mkdir()
    memory.copy_database(
        MemoryHandle("", 0, tmp_path / "memory.db"), copy / "memory.db"
    )

    with (
        memory.start(copy, None, "demo", tmp_path, {"PATH": "/bin"}) as handle,
        sqlite3.connect(handle.db) as db,
    ):
        assert db.execute("SELECT content FROM observations").fetchall() == [("kept",)]
        assert db.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0] == 0
    assert "create_entities" not in server["requests"]
