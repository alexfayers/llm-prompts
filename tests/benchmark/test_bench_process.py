import json
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
    ToolCall,
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
    [
        (ClaudeAdapter(), "Agent,Task"),
        (PiAdapter(), "fork,fork_resume,fork_steer,fork_cancel"),
    ],
)
def test_subagent_tools_are_denied(
    cell: tuple[PreparedCell, Scenario], runner: ClaudeAdapter | PiAdapter, denied: str
) -> None:
    prepared, scenario = cell

    assert denied in runner.command(prepared, scenario, "m")


@pytest.mark.parametrize(
    ("runner", "flag"),
    [(ClaudeAdapter(), "--disallowedTools"), (PiAdapter(), "--exclude-tools")],
)
def test_a_delegation_scenario_allows_subagents(
    cell: tuple[PreparedCell, Scenario], runner: ClaudeAdapter | PiAdapter, flag: str
) -> None:
    prepared, scenario = cell

    argv = runner.command(prepared, replace(scenario, delegation=True), "m")

    assert flag not in argv


def test_pi_leaves_out_the_tools_of_a_feature_that_is_off_and_keeps_the_rest(
    cell: tuple[PreparedCell, Scenario],
) -> None:
    prepared, scenario = cell
    off = replace(
        prepared,
        cell=replace(
            prepared.cell,
            variant=replace(
                prepared.cell.variant, features={"consult": False, "ghost": True}
            ),
        ),
    )

    argv = PiAdapter().command(off, replace(scenario, delegation=True), "m")

    assert argv[argv.index("--exclude-tools") + 1] == "consult"


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

    result = process.execute(prepared, scenario, "m", None)

    ((argv, kwargs),) = popen.started
    assert argv == ClaudeAdapter().command(prepared, scenario, "m")
    assert (kwargs["cwd"], kwargs["env"]) == (prepared.workspace, prepared.env)
    assert result.exit_code == 3
    assert (prepared.root / "agent.log").read_text() == f"{TOOL_LINE}out\nerr\n"


LATER_MS = 4102444800000


def _reply(cost: float, at: int = LATER_MS, call: str = "") -> dict[str, Any]:
    use = [{"type": "toolCall", "id": call, "name": "bash", "arguments": {}}]
    usage = {"input": 1, "output": 2, "cost": {"total": cost}}
    return {
        "role": "assistant",
        "timestamp": at,
        "usage": usage,
        "content": use if call else [],
    }


def _fork_files(
    home: Path,
    inherited: str | None,
    *entries: dict[str, Any],
    session: str = "seed.jsonl",
) -> Path:
    files = home / ".pi" / "agent" / "pi-context" / str(uuid.uuid4())
    (files / session).parent.mkdir(parents=True)
    handshake = {"inherited": inherited} if inherited else {}
    (files / "handshake.json").write_text(json.dumps(handshake))
    lines = [{"type": "session", "id": "header"}, *entries]
    (files / session).write_text("".join(json.dumps(e) + "\n" for e in lines))
    return files


def test_pi_forks_add_their_own_usage_and_calls_to_the_cell(
    popen: FakePopen, cell: tuple[PreparedCell, Scenario]
) -> None:
    prepared, scenario = cell
    prepared = replace(prepared, cell=replace(prepared.cell, agent="pi"))
    lead = {"type": "message_end", "message": _reply(0.5)}
    popen.lines = [json.dumps(e) + "\n" for e in (lead, {"type": "agent_settled"})]
    result = {"role": "toolResult", "toolCallId": "c1", "timestamp": LATER_MS}
    _fork_files(
        prepared.home,
        "seed",
        {"type": "message", "id": "seed", "message": _reply(0.5)},
        {"type": "message", "id": "f1", "message": _reply(0.25, call="c1")},
        {"type": "message", "id": "f2", "message": {**result, "content": "ok"}},
    )
    _fork_files(
        prepared.home, None, {"type": "message", "id": "old", "message": _reply(1, 0)}
    )
    _fork_files(
        prepared.home,
        None,
        {"type": "message", "id": "c1", "message": _reply(0.125)},
        session="session/--ws--/x.jsonl",
    )

    trace = process.execute(prepared, scenario, "m", None)

    assert (trace.cost_usd, trace.tokens.input, trace.tokens.output) == (0.875, 3, 6)
    assert [(c.name, c.ok, c.subagent) for c in trace.tool_calls] == [
        ("Bash", True, True)
    ]
    assert trace.turns == 1


def test_fork_calls_are_merged_into_the_lead_calls_by_time(tmp_path: Path) -> None:
    at = LATER_MS / 1000
    _fork_files(
        tmp_path,
        None,
        {"type": "message", "id": "f1", "message": _reply(0.25, call="c1")},
    )
    lead = (
        ToolCall("Read", {}, True, at - 1),
        ToolCall("Edit", {}, True, at),
        ToolCall("Write", {}, True, at + 1),
    )

    trace = PiAdapter().add_delegates(make_trace(tool_calls=lead), tmp_path, 0)

    assert [c.name for c in trace.tool_calls] == ["Read", "Edit", "Bash", "Write"]


def test_on_reply_fires_once_at_the_first_assistant_line(
    popen: FakePopen, cell: tuple[PreparedCell, Scenario]
) -> None:
    prepared, scenario = cell
    popen.lines = ["out\n", TOOL_LINE, TOOL_LINE]
    replies: list[int] = []

    process.execute(prepared, scenario, "m", None, on_reply=lambda: replies.append(1))

    assert replies == [1]


def test_on_tool_fires_at_each_tool_line(
    popen: FakePopen, cell: tuple[PreparedCell, Scenario]
) -> None:
    prepared, scenario = cell
    popen.lines = ["out\n", TOOL_LINE, TOOL_LINE]
    tools: list[str] = []

    process.execute(prepared, scenario, "m", None, on_tool=tools.append)

    assert tools == ["Bash", "Bash"]


def test_on_tool_fires_for_every_tool_in_one_line(
    popen: FakePopen, cell: tuple[PreparedCell, Scenario]
) -> None:
    prepared, scenario = cell
    popen.lines = [
        '{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}, {"type": "tool_use", "name": "Bash"}]}}\n'
    ]
    tools: list[str] = []

    process.execute(prepared, scenario, "m", None, on_tool=tools.append)

    assert tools == ["Read", "Bash"]


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
