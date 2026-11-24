"""Live terminal view of the running benchmark cells."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Self, cast

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.live import Live
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
)
from rich.spinner import Spinner
from rich.text import Text

from llm_prompts.benchmark.types import ResultRow

STAT_WIDTHS = (5, 20, 6, 9)
VERDICT_WIDTH = len("skipped")
STATUS_LINES = 2


def _stats(row: ResultRow) -> list[str]:
    if not row.wall_s:
        return []
    return [
        f"{row.wall_s:.0f}s",
        f"{row.start_context:,}->{row.context:,} ctx",
        "-" if row.cost_usd is None else f"${row.cost_usd:.2f}",
        f"{row.turns} turns",
    ]


@dataclass
class _Row:
    label: str
    started: float
    tool: str = ""
    calls: int = 0
    result: Text | None = None


class _Rows:
    """One line per cell in the order the cells started: a spinner while it runs, then its result."""

    def __init__(self, width: int, lock: threading.Lock) -> None:
        self.width = width
        self._lock = lock
        self.items: dict[str, _Row] = {}
        self._spinner = Spinner("dots")

    def line(self, row: _Row, now: float) -> Text:
        """Return the line of a row: its result, or the elapsed time and tool of the running cell."""
        marker = (
            cast(Text, self._spinner.render(now)) if row.result is None else Text(" ")
        )
        detail = row.result or Text.assemble(
            " " * VERDICT_WIDTH,
            f" {f'{now - row.started:.0f}s':>{STAT_WIDTHS[0]}}",
            (f"  {row.tool}" if row.tool else ""),
        )
        return Text.assemble(
            marker,
            " ",
            row.label.ljust(self.width),
            " ",
            detail,
            no_wrap=True,
            overflow="ellipsis",
        )

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        now = time.monotonic()
        with self._lock:
            rows = list(self.items.values())
        for row in rows:
            yield self.line(row, now)


class LiveView:
    def __init__(self, labels: Sequence[str], console: Console | None = None) -> None:
        console = console or Console(stderr=True)
        self._console = console
        self._total = len(labels)
        self._lock = threading.Lock()
        self._failed = 0
        self._skipped = 0
        self._live: Live | None = None
        self._rows = _Rows(max(map(len, labels), default=0), self._lock)
        if console.is_terminal:
            self._overall = Progress(
                BarColumn(),
                MofNCompleteColumn(),
                TextColumn(
                    "done, {task.fields[failed]} fail, {task.fields[skipped]} skipped, ETA"
                ),
                TimeRemainingColumn(compact=True),
                console=console,
                speed_estimate_period=math.inf,
            )
            self._overall_id = self._overall.add_task(
                "", total=self._total, failed=0, skipped=0
            )
            self._overall.advance(self._overall_id, 0)
            self._display = Group(self._rows, self._overall)
            self._live = Live(
                self._display,
                console=console,
                redirect_stderr=True,
                refresh_per_second=10,
            )

    @property
    def display(self) -> RenderableType:
        """The live area: a row per started cell above the overall progress."""
        return self._display

    def __enter__(self) -> Self:
        if self._live:
            self._live.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._live:
            self._live.stop()

    def start(self, key: str, label: str) -> None:
        """Show the row of a cell that has started."""
        if not self._live:
            return
        with self._lock:
            self._rows.items[key] = _Row(label, time.monotonic())
        self._live.refresh()

    def tool(self, key: str, name: str) -> None:
        """Show the tool a running cell has just started."""
        if not self._live:
            return
        with self._lock:
            row = self._rows.items[key]
            row.calls += 1
            row.tool = f"{name} ({row.calls})"
        self._live.refresh()

    def _settle(self, live: Live, key: str, label: str, result: Text) -> None:
        """Turn the row of a cell into its ``result`` and count it, scrolling the oldest finished rows off when the display outgrows the terminal."""
        popped: list[_Row] = []
        with self._lock:
            row = self._rows.items.setdefault(key, _Row(label, time.monotonic()))
            row.result = result
            self._overall.update(
                self._overall_id, advance=1, failed=self._failed, skipped=self._skipped
            )
            while len(self._rows.items) > self._console.size.height - STATUS_LINES:
                oldest = next(
                    (k for k, r in self._rows.items.items() if r.result is not None),
                    None,
                )
                if oldest is None:
                    break
                popped.append(self._rows.items.pop(oldest))
        for gone in popped:
            self._console.print(self._rows.line(gone, 0.0), crop=True)
        live.refresh()

    def skip(self, key: str, label: str, reason: str) -> None:
        """Show a cell that was skipped, or cut short before it ended, and why."""
        if not self._live:
            return
        with self._lock:
            self._skipped += 1
        self._settle(
            self._live,
            key,
            label,
            Text.assemble(("skipped".ljust(VERDICT_WIDTH), "yellow"), f"  {reason}"),
        )

    def finish(self, key: str, label: str, row: ResultRow) -> None:
        """Show the result of a finished cell."""
        if not self._live:
            return
        stats = _stats(row)
        unavailable = row.startup_error
        verdict = "error" if unavailable else "pass" if row.passed else "fail"
        if not row.passed and not unavailable:
            with self._lock:
                self._failed += 1
        self._settle(
            self._live,
            key,
            label,
            Text.assemble(
                (verdict.ljust(VERDICT_WIDTH), "green" if row.passed else "red"),
                *(
                    f" {stat:>{width}}"
                    for stat, width in zip(
                        stats or [""] * len(STAT_WIDTHS), STAT_WIDTHS, strict=True
                    )
                ),
                *(((f"  {row.error}", "red"),) if row.error else ()),
            ),
        )
