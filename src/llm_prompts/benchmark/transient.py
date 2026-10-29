"""Retry cells whose agent dies at startup on a transient error, and space out agent launches."""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass

from llm_prompts.benchmark.runner import process
from llm_prompts.benchmark.types import Trace

MAX_RETRIES = 3
BACKOFF_S = (30.0, 60.0)
STAGGER_S = 3.0
STARTUP_ERROR = "startup error: "
TRANSIENT = re.compile(r"throttl|rate exceeded|credential export", re.IGNORECASE)


def is_startup_error(error: str | None) -> bool:
    """Return whether a row error is a transient startup error, also when it is carried by a follow-up."""
    return error is not None and STARTUP_ERROR in error


def is_transient(trace: Trace, reason: str) -> bool:
    """Return whether the agent exited before its first model turn with a throttling error."""
    return bool(
        trace.exit_code
        and not trace.turns
        and not trace.tool_calls
        and TRANSIENT.search(reason)
    )


def backoff() -> float:
    """Return a random wait in seconds before the next attempt."""
    return random.uniform(*BACKOFF_S)


@dataclass(frozen=True)
class Retries:
    """The attempts of a cell that failed at startup before its last one."""

    count: int = 0
    cost_usd: float | None = None

    @property
    def exhausted(self) -> bool:
        """Return whether the cell has no retries left."""
        return self.count >= MAX_RETRIES

    def after(self, failed: Trace | None) -> Retries:
        """Return these retries plus one for the ``failed`` attempt and its cost."""
        cost = failed.cost_usd if failed else None
        spent = cost if self.cost_usd is None else self.cost_usd + (cost or 0.0)
        return Retries(self.count + 1, spent)


NO_RETRIES = Retries()


class Stagger:
    """Spaces agent launches at least ``gap_s`` apart across threads."""

    def __init__(self, gap_s: float) -> None:
        self._gap_s = gap_s
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        """Wait for this launch's turn."""
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self._gap_s
        if start > now:
            process.pause(start - now)
