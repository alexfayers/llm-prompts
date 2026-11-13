import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from benchmark.traces import make_trace
from llm_prompts.benchmark import paths
from llm_prompts.benchmark.cell.audit import AuditHit, audit, audit_trace
from llm_prompts.benchmark.types import ToolCall


def write(path: Path, data: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    return path


@pytest.fixture
def live(tmp_path: Path, live_home: None) -> Path:
    return tmp_path / "live"


def test_audit_reports_live_paths_ports_and_symlinks(
    tmp_path: Path,
    live: Path,
    monkeypatch: pytest.MonkeyPatch,
    declare_home: Callable[[dict[str, Any]], None],
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    declare_home(
        {
            ".tools": {"empty": ["state"]},
            "a/b": {},
            "text": "x",
            "bad": {"link": "x"},
            "both": {"link": ["x"], "empty": ["x"]},
        }
    )
    write(
        live / ".config" / "systemd" / "user" / "mcp-memory.service",
        'Environment="MCP_MEMORY_PORT=41000"\n',
    )
    root = tmp_path / "root"
    text = write(root / "a.txt", f"{live}/.claude/hooks")
    blob = write(root / "b.bin", b"\x00\xff" + str(live / ".pi").encode())
    port = write(root / "port.txt", "localhost:41000")
    write(root / "other-port.txt", "localhost:410001 localhost:3000")
    write(root / "node_modules" / "pkg" / "README.md", str(live / ".pi"))
    link = root / "link"
    link.symlink_to(live / ".claude")
    tools_link = root / "tools-link"
    tools_link.symlink_to(live / ".tools")

    assert audit(root) == [
        AuditHit(text, str(live / ".claude")),
        AuditHit(blob, str(live / ".pi")),
        AuditHit(link, str(live / ".claude")),
        AuditHit(port, "localhost:41000"),
        AuditHit(tools_link, str(live / ".tools")),
    ]


def test_audit_flags_a_relative_link_into_the_live_home(
    tmp_path: Path, live: Path
) -> None:
    root = tmp_path / "root"
    link = root / "settings"
    root.mkdir()
    link.symlink_to("../live/.claude/settings.json")

    assert audit(root) == [AuditHit(link, str(live / ".claude"))]


def test_audit_trace_flags_calls_naming_the_real_home_only(
    live: Path,
) -> None:
    tool = f"{live}/.local/bin/pytest"
    ok = f"{paths.cache_dir()}/variants/v/venv/bin/pytest"
    trace = make_trace(
        tool_calls=(
            ToolCall("Bash", {"command": f"{tool} -q"}, True),
            ToolCall("Bash", {"command": f"{ok} && {live}x/bin/tool"}, True),
        )
    )

    assert audit_trace(trace) == [AuditHit(Path("Bash"), tool)]


def test_audit_trace_flags_paths_that_only_look_like_the_cache(live: Path) -> None:
    cache = paths.cache_dir()
    other = f"{cache}-other/bin/tool"
    escape = f"{cache}/../../../.claude/settings.json"
    trace = make_trace(
        tool_calls=(ToolCall("Bash", {"command": f"cat {other} {escape}"}, True),)
    )

    assert audit_trace(trace) == [
        AuditHit(Path("Bash"), other),
        AuditHit(Path("Bash"), escape),
    ]


def test_audit_allows_a_link_into_a_shared_store_only_while_it_is_read_only(
    tmp_path: Path, live: Path
) -> None:
    store = tmp_path / "store"
    shared = write(store / "pkg" / "index.js", "x")
    root = tmp_path / "root"
    link = root / "npm"
    root.mkdir()
    link.symlink_to(store)
    for path in (shared, shared.parent, store):
        path.chmod(0o555 if path.is_dir() else 0o444)

    try:
        assert audit(root, stores=[store]) == []

        shared.chmod(0o644)
        assert audit(root, stores=[store]) == [AuditHit(link, f"writable {shared}")]
    finally:
        for path in (store, shared.parent):
            path.chmod(0o755)
