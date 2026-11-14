"""Runs one agent process for a prepared cell."""

from __future__ import annotations

import dataclasses
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import CancelledError
from contextlib import contextmanager, suppress
from types import FrameType

from llm_prompts.benchmark.agents import AGENTS
from llm_prompts.benchmark.runner.sandbox import SandboxPolicy, wrap
from llm_prompts.benchmark.types import (
    PreparedCell,
    Scenario,
    Session,
    Trace,
)

_live: set[subprocess.Popen[str]] = set()
_lock = threading.Lock()
_stopping = threading.Event()


def _kill_group(process: subprocess.Popen[str]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)


@contextmanager
def interrupt_on_termination() -> Iterator[None]:
    """Turn SIGTERM and SIGHUP into KeyboardInterrupt while active, so a terminated run cleans up like an interrupted one."""

    def interrupt(number: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    numbers = (signal.SIGTERM, signal.SIGHUP)
    before = [signal.signal(number, interrupt) for number in numbers]
    try:
        yield
    finally:
        for number, handler in zip(numbers, before, strict=True):
            signal.signal(number, handler)


def kill_all() -> None:
    """Stop every running agent process and refuse new ones."""
    with _lock:
        _stopping.set()
        for process in list(_live):
            _kill_group(process)


def reset_stop() -> None:
    """Allow agent processes to run again after ``kill_all``."""
    _stopping.clear()


def pause(seconds: float) -> None:
    """Wait ``seconds``, or raise ``CancelledError`` once ``kill_all`` has stopped the run."""
    if _stopping.wait(seconds):
        raise CancelledError


def execute(
    prepared: PreparedCell,
    scenario: Scenario,
    model: str,
    policy: SandboxPolicy | None,
    on_reply: Callable[[], None] | None = None,
    session: Session | None = None,
) -> Trace:
    """Run the agent for a cell, optionally inside the OS sandbox, and return its trace."""
    runner = AGENTS[prepared.cell.agent]
    argv = runner.command(prepared, scenario, model, session)
    if policy is not None:
        argv = wrap(argv, policy)
    timed_out = threading.Event()
    started = time.monotonic()
    with tempfile.TemporaryFile("w+") as stderr:
        with _lock:
            if _stopping.is_set():
                raise CancelledError
            process = subprocess.Popen(
                argv,
                cwd=prepared.workspace,
                env=prepared.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                start_new_session=True,
            )
            _live.add(process)

        def kill() -> None:
            timed_out.set()
            _kill_group(process)

        timer = threading.Timer(scenario.timeout_s, kill)
        timer.start()
        try:
            assert process.stdout is not None
            lines: list[tuple[float, str]] = []
            replied = False
            for line in process.stdout:
                lines.append((time.time(), line))
                if on_reply and not replied and runner.replied(line):
                    replied = True
                    on_reply()
            returncode = process.wait()
        finally:
            timer.cancel()
            _live.discard(process)
        wall_s = time.monotonic() - started
        stderr.seek(0)
        log = "".join(line for _, line in lines) + stderr.read()
    (prepared.root / "agent.log").write_text(log)
    if timed_out.is_set():
        raise TimeoutError(f"{prepared.cell.id} exceeded {scenario.timeout_s}s")
    trace = runner.parse(lines, wall_s)
    return dataclasses.replace(trace, exit_code=returncode or trace.exit_code)
