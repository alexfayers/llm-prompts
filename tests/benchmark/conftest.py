from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import FakeSubprocess

from benchmark.traces import make_trace
from llm_prompts.benchmark import paths
from llm_prompts.benchmark.cell import home_dirs
from llm_prompts.benchmark.cell.variants import PLACEHOLDER_MEMORY_URL
from llm_prompts.benchmark.runner.process import reset_stop
from llm_prompts.benchmark.types import MemoryEntity, MemoryHandle, ToolCall, Variant


class FakeMemory:
    def __init__(self) -> None:
        self.started: list[MemoryHandle] = []
        self.stopped: list[MemoryHandle] = []
        self.calls: list[tuple[str, Path]] = []
        self.entity_lists: dict[MemoryHandle, list[MemoryEntity]] = {}
        self.tool_call_lists: dict[MemoryHandle, list[ToolCall]] = {}
        self.copies: dict[Path, list[MemoryEntity]] = {}

    def copy_database(self, handle: MemoryHandle, target: Path) -> None:
        self.copies[target.parent] = list(self.entity_lists[handle])

    def entities(self, handle: MemoryHandle) -> tuple[MemoryEntity, ...]:
        return tuple(sorted(self.entity_lists[handle], key=lambda e: e.name))

    def tool_calls(self, handle: MemoryHandle) -> tuple[ToolCall, ...]:
        return tuple(sorted(self.tool_call_lists[handle], key=lambda c: c.at))

    def clear_tool_calls(self, handle: MemoryHandle) -> None:
        self.tool_call_lists[handle] = []

    @contextmanager
    def start(
        self,
        home: Path,
        seed: tuple[MemoryEntity, ...] | None,
        project: str,
        workspace: Path,
        env: Mapping[str, str],
    ) -> Iterator[MemoryHandle]:
        port = 41000 + len(self.started)
        handle = MemoryHandle(f"http://127.0.0.1:{port}/mcp", port, home / "m.db")
        self.entity_lists[handle] = list(
            self.copies.get(home, ()) if seed is None else seed
        )
        self.tool_call_lists[handle] = []
        self.started.append(handle)
        self.calls.append((project, workspace))
        try:
            yield handle
        finally:
            self.stopped.append(handle)


@pytest.fixture
def fake_memory(monkeypatch: pytest.MonkeyPatch) -> FakeMemory:
    from llm_prompts.benchmark.cell import memory

    fake = FakeMemory()
    monkeypatch.setattr(memory, "start", fake.start)
    monkeypatch.setattr(memory, "read_entities", fake.entities)
    monkeypatch.setattr(memory, "read_tool_calls", fake.tool_calls)
    monkeypatch.setattr(memory, "copy_database", fake.copy_database)
    monkeypatch.setattr(memory, "clear_tool_calls", fake.clear_tool_calls)
    return fake


@dataclass(frozen=True)
class BenchDirs:
    state: Path
    cache: Path


@pytest.fixture
def bench_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BenchDirs:
    dirs = BenchDirs(state=tmp_path / "state", cache=tmp_path / "cache")
    monkeypatch.setattr(paths, "state_dir", lambda: dirs.state)
    monkeypatch.setattr(paths, "cache_dir", lambda: dirs.cache)
    return dirs


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.fixture
def judge_passes(fake_subprocess: FakeSubprocess) -> None:
    fake_subprocess.on_match(
        lambda argv: argv[0] == "claude",
        stdout=json.dumps({"type": "result", "result": "PASS", "usage": {}}),
    )


UNSCRIPTED_TRACE = make_trace(model="fake")


@pytest.fixture
def fake_variant(tmp_path: Path) -> Variant:
    root = tmp_path / "variant"
    (root / "src").mkdir(parents=True)
    (root / "venv" / "bin").mkdir(parents=True)
    claude, pi = root / "templates" / "claude", root / "templates" / "pi"
    memory_url = {"memory": {"url": PLACEHOLDER_MEMORY_URL}}
    _write_json(claude / ".claude" / "settings.json", {"env": {"TEMPLATE": "1"}})
    _write_json(
        claude / ".claude" / ".claude.json",
        {"mcpServers": {"memory": {"type": "http", "url": PLACEHOLDER_MEMORY_URL}}},
    )
    _write_json(pi / ".pi" / "agent" / "mcp.json", {"mcpServers": memory_url})
    return Variant(
        "a",
        "main",
        "fake-variant-key",
        root / "src",
        root / "venv",
        {"claude": claude, "pi": pi},
        {"claude": "fake-build", "pi": "fake-build"},
    )


@pytest.fixture
def live_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "live").mkdir()
    (tmp_path / "roots").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "live")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "roots"))
    monkeypatch.setattr(paths, "work_dir", lambda: tmp_path / "roots")


def pi_settings_path() -> Path:
    return Path.home() / ".pi" / "agent" / "settings.json"


def give_pi_a_default_model(home: Path) -> None:
    """Write pi settings with a default model into ``home``, as a user's own pi has."""
    path = home / ".pi" / "agent" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"defaultModel": "test-model"}))


@pytest.fixture(autouse=True)
def _pi_default_model(isolated_home: Path) -> None:
    give_pi_a_default_model(isolated_home)


@pytest.fixture(autouse=True)
def _reset_runner_stop() -> None:
    reset_stop()


@pytest.fixture(autouse=True)
def _no_overlay_home_dirs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(home_dirs, "_discover_overlay_paths", lambda quiet: [])
    home_dirs.declared_home_dirs.cache_clear()
    yield
    home_dirs.declared_home_dirs.cache_clear()


@pytest.fixture
def declare_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[dict[str, dict[str, list[str]]]], None]:
    def declare(spec: dict[str, dict[str, list[str]]]) -> None:
        _write_json(tmp_path / "overlay" / home_dirs.HOME_DIRS_FILENAME, spec)
        monkeypatch.setattr(
            home_dirs, "_discover_overlay_paths", lambda quiet: [tmp_path / "overlay"]
        )
        home_dirs.declared_home_dirs.cache_clear()

    return declare


class FakeSandbox:
    def __init__(self) -> None:
        self._present: set[str] = set()

    def present(self, *tools: str) -> None:
        self._present.update(tools)


@pytest.fixture
def fake_sandbox(monkeypatch: pytest.MonkeyPatch) -> FakeSandbox:
    fake = FakeSandbox()
    real = shutil.which

    def which(name: str, *a: object, **k: object) -> str | None:
        if name in ("sandbox-exec", "bwrap"):
            return f"/usr/bin/{name}" if name in fake._present else None
        return real(name)

    monkeypatch.setattr(shutil, "which", which)
    return fake
