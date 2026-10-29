import signal
import subprocess
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import CancelledError
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from benchmark.traces import make_trace
from llm_prompts.benchmark.agents.claude import ClaudeAdapter
from llm_prompts.benchmark.agents.pi import PiAdapter
from llm_prompts.benchmark.runner import process
from llm_prompts.benchmark.types import (
    DEFAULT_GATE,
    Cell,
    MemoryHandle,
    PreparedCell,
    Scenario,
    Session,
    Variant,
)

PID = 4242
TOOL_LINE = '{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}\n'


class FakePopen:
    """Popen stand-in. A hanging process only ends once it is killed."""

    pid = PID
    stdout = property(lambda self: self)

    def __init__(self) -> None:
        self.lines, self.stderr, self.returncode, self.hang = ["out\n"], "", 0, False
        self.started: list[tuple[list[str], dict[str, Any]]] = []
        self.killed, self.reading = threading.Event(), threading.Event()

    def __call__(self, argv: list[str], **kwargs: Any) -> "FakePopen":
        self.started.append((argv, kwargs))
        kwargs["stderr"].write(self.stderr)
        return self

    def __iter__(self) -> Iterator[str]:
        if self.hang:
            self.reading.set()
            self.killed.wait(5)
            return iter(())
        return iter(self.lines)

    def wait(self) -> int:
        return self.returncode


@pytest.fixture
def popen(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakePopen]:
    fake = FakePopen()
    monkeypatch.setattr(subprocess, "Popen", fake)
    monkeypatch.setattr("os.getpgid", lambda pid: pid)
    monkeypatch.setattr("os.killpg", lambda pgid, sig: fake.killed.set())
    monkeypatch.setattr(ClaudeAdapter, "parse", lambda *_: make_trace())
    yield fake
    process.reset_stop()


@pytest.fixture
def cell(tmp_path: Path) -> tuple[PreparedCell, Scenario]:
    scenario = Scenario(
        "s", "light", ("claude",), Path("ws"), "demo", "go", 1, DEFAULT_GATE, (), ()
    )
    variant = Variant("a", "main", "k", Path("src"), Path("venv"), {})
    (tmp_path / "ws").mkdir()
    handle = MemoryHandle("http://127.0.0.1:1", 1, tmp_path / "db")
    prepared = PreparedCell(
        Cell(variant, "claude", scenario, 0), tmp_path, tmp_path / "home",
        tmp_path / "ws", {"MARK": "x"}, handle, (),
    )  # fmt: skip
    return prepared, scenario


@pytest.mark.parametrize(
    ("runner", "denied"),
    [(ClaudeAdapter(), "Agent,Task"), (PiAdapter(), "*_agent*")],
)
def test_subagent_tools_are_denied(
    cell: tuple[PreparedCell, Scenario], runner: ClaudeAdapter | PiAdapter, denied: str
) -> None:
    prepared, scenario = cell

    assert denied in runner.command(prepared, scenario, "m")


def test_a_delegation_scenario_allows_claude_subagents(
    cell: tuple[PreparedCell, Scenario],
) -> None:
    prepared, scenario = cell

    argv = ClaudeAdapter().command(prepared, replace(scenario, delegation=True), "m")

    assert "--disallowedTools" not in argv


BASE = Session("bench-base")
FORK = Session("bench-next", "bench-base")


def test_pi_argv_starts_and_forks_named_sessions(
    cell: tuple[PreparedCell, Scenario],
) -> None:
    prepared, scenario = cell
    runner = PiAdapter()

    assert "--no-session" in runner.command(prepared, scenario, "m")
    base = runner.command(prepared, scenario, "m", BASE)
    fork = runner.command(prepared, scenario, "m", FORK)

    assert "--no-session" not in base + fork
    assert base[base.index("--session-id") + 1] == "bench-base"
    assert "--fork" not in base
    assert fork[fork.index("--fork") + 1] == "bench-base"
    assert fork[fork.index("--session-id") + 1] == "bench-next"


def test_claude_argv_starts_and_resumes_forked_sessions(
    cell: tuple[PreparedCell, Scenario],
) -> None:
    prepared, scenario = cell
    runner = ClaudeAdapter()

    assert "--no-session-persistence" in runner.command(prepared, scenario, "m")
    base = runner.command(prepared, scenario, "m", BASE)
    fork = runner.command(prepared, scenario, "m", FORK)

    assert "--no-session-persistence" not in base + fork
    base_id = base[base.index("--session-id") + 1]
    assert uuid.UUID(base_id)
    assert fork[fork.index("--resume") + 1] == base_id
    assert "--fork-session" in fork
    assert "--session-id" not in fork


def test_execute_runs_agent_in_workspace_and_logs_stdout_then_stderr(
    popen: FakePopen, cell: tuple[PreparedCell, Scenario]
) -> None:
    prepared, scenario = cell
    popen.stderr, popen.returncode = "err\n", 3
    popen.lines = [TOOL_LINE, "out\n"]
    tools: list[str] = []

    result = process.execute(prepared, scenario, "m", None, tools.append)

    ((argv, kwargs),) = popen.started
    assert argv == ClaudeAdapter().command(prepared, scenario, "m")
    assert (kwargs["cwd"], kwargs["env"]) == (prepared.workspace, prepared.env)
    assert result.exit_code == 3
    assert tools == ["Bash"]
    assert (prepared.root / "agent.log").read_text() == f"{TOOL_LINE}out\nerr\n"


def test_on_reply_fires_once_at_the_first_assistant_line(
    popen: FakePopen, cell: tuple[PreparedCell, Scenario]
) -> None:
    prepared, scenario = cell
    popen.lines = ["out\n", TOOL_LINE, TOOL_LINE]
    replies: list[int] = []

    process.execute(prepared, scenario, "m", None, on_reply=lambda: replies.append(1))

    assert replies == [1]


def test_timeout_and_kill_all_stop_the_agent(
    popen: FakePopen, cell: tuple[PreparedCell, Scenario]
) -> None:
    prepared, scenario = cell
    popen.hang = True
    with pytest.raises(TimeoutError):
        process.execute(prepared, scenario, "m", None)
    assert popen.killed.is_set()

    popen.killed.clear()
    popen.reading.clear()
    worker = threading.Thread(
        target=process.execute, args=(prepared, scenario, "m", None)
    )
    worker.start()
    assert popen.reading.wait(5)
    process.kill_all()
    worker.join(5)
    assert popen.killed.is_set()
    with pytest.raises(CancelledError):
        process.execute(prepared, scenario, "m", None)


def test_sigterm_and_sighup_interrupt_the_run_so_its_cleanup_runs_and_the_handlers_come_back() -> (
    None
):
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP)

    for number in (signal.SIGTERM, signal.SIGHUP):
        with pytest.raises(KeyboardInterrupt), process.interrupt_on_termination():
            signal.raise_signal(number)

    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP)) == before
