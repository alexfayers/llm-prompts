from __future__ import annotations

import json
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from conftest import FakeSubprocess

from benchmark.traces import make_trace
from llm_prompts.benchmark import paths, transient
from llm_prompts.benchmark.cell import home_dirs
from llm_prompts.benchmark.cell.variants import PLACEHOLDER_MEMORY_URL
from llm_prompts.benchmark.runner import process
from llm_prompts.benchmark.runner.process import reset_stop
from llm_prompts.benchmark.runner.sandbox import SandboxPolicy
from llm_prompts.benchmark.types import (
    DEFAULT_GATE,
    MemoryEntity,
    MemoryHandle,
    PreparedCell,
    Scenario,
    Session,
    ToolCall,
    Trace,
    Variant,
)


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


UNSCRIPTED_TRACE = make_trace(model="fake")
SCENARIO = Scenario(
    "s0", "light", ("claude", "pi"), Path("ws"), "demo-project", "do it", 60,
    DEFAULT_GATE, (), (),
)  # fmt: skip


@pytest.fixture
def live_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "live").mkdir()
    (tmp_path / "roots").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "live")
    give_pi_a_default_model(tmp_path / "live")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "roots"))
    monkeypatch.setattr(paths, "work_dir", lambda: tmp_path / "roots")


@dataclass
class _Script:
    memory_calls: tuple[ToolCall, ...] = ()
    trace: Trace = UNSCRIPTED_TRACE
    earlier: tuple[Trace, ...] = ()
    raises: BaseException | None = None
    reply_delay: float = 0.0
    files: Mapping[str, str] = field(default_factory=dict)
    replies: bool = True
    entities: tuple[MemoryEntity, ...] = ()


class FakeAgent:
    def __init__(self, fake_memory: FakeMemory) -> None:
        self.executed: list[PreparedCell] = []
        self.policies: list[SandboxPolicy | None] = []
        self.events: list[tuple[str, str]] = []
        self.sessions: dict[str, Session | None] = {}
        self.seen_files: dict[str, list[str]] = {}
        self._memory = fake_memory
        self._scripts: dict[str, _Script] = {}
        self._runs: Counter[str] = Counter()

    def script(self, scenario: str, **kwargs: object) -> None:
        self._scripts[scenario] = _Script(**kwargs)  # type: ignore[arg-type]

    def execute(
        self,
        prepared: PreparedCell,
        scenario: Scenario,
        model: str,
        policy: SandboxPolicy | None,
        on_reply: Callable[[], None] | None = None,
        session: Session | None = None,
    ) -> Trace:
        self.executed.append(prepared)
        self.events.append(("start", prepared.cell.id))
        self.sessions[prepared.cell.id] = session
        self.seen_files[prepared.cell.id] = sorted(
            p.name for p in prepared.workspace.iterdir()
        )
        self.policies.append(policy)
        (prepared.root / "agent.log").write_text("log")
        (prepared.home / ".cline-hooks").mkdir(exist_ok=True)
        (prepared.home / ".cline-hooks" / "cline-hooks.log").write_text("hooks")
        script = self._scripts.get(scenario.id, _Script())
        self._runs[scenario.id] += 1
        self._memory.tool_call_lists[prepared.memory].extend(script.memory_calls)
        self._memory.entity_lists[prepared.memory].extend(script.entities)
        for name, text in script.files.items():
            (prepared.workspace / name).write_text(text)
        time.sleep(script.reply_delay)
        if on_reply and script.replies:
            on_reply()
            self.events.append(("reply", prepared.cell.id))
        if script.raises is not None:
            raise script.raises
        attempt = self._runs[scenario.id] - 1
        return (
            script.earlier[attempt] if attempt < len(script.earlier) else script.trace
        )


@pytest.fixture
def fake_agent(monkeypatch: pytest.MonkeyPatch, fake_memory: FakeMemory) -> FakeAgent:
    fake = FakeAgent(fake_memory)
    monkeypatch.setattr(process, "execute", fake.execute)
    return fake


@pytest.fixture(autouse=True)
def pauses(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    waited: list[float] = []
    monkeypatch.setattr(process, "pause", waited.append)
    monkeypatch.setattr(transient, "STAGGER_S", 0.0)
    return waited


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
