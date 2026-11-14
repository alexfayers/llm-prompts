"""Render the benchmark comparison for the console as plain text or a rich table."""

from __future__ import annotations

from collections.abc import Sequence

from rich import box
from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from llm_prompts.benchmark.report.compare import (
    Report,
    ScenarioDelta,
    change_text,
    cost_text,
    outcome_summary,
    regressed,
    size_summary,
    usage_summary,
)
from llm_prompts.benchmark.report.render import (
    COLUMNS,
    SESSION_NOTE,
    _name,
    _time,
    sections,
)

TERMINAL_HEADERS = {
    "Context": "Ctx",
    "Failed tests": "Fail",
    "Turns": "Trn",
    " change": " %",
}


def _terminal_header(header: str) -> str:
    for long, short in TERMINAL_HEADERS.items():
        header = header.replace(long, short)
    return header


def footer_text(report: Report) -> str:
    """Return the usage, prompt size and outcome lines that end the console summary."""
    return "\n".join(
        [
            usage_summary(report.usage),
            "Prompt size: not compared"
            if report.prompt_size_missing
            else size_summary(report.prompt_size),
            outcome_summary(report),
        ]
    )


def _summary_line(delta: ScenarioDelta) -> str:
    a, b = delta.a, delta.b
    line = (
        f"{_name(delta)} {delta.agent}: pass {a.passed}/{a.total} -> "
        f"{b.passed}/{b.total}, context {a.median_context:,.0f} -> "
        f"{b.median_context:,.0f} ({change_text(delta.context_change)}), cost "
        f"{cost_text(a.median_cost_usd)} -> {cost_text(b.median_cost_usd)} "
        f"({change_text(delta.cost_change)}), time {_time(a.median_wall_s)} -> "
        f"{_time(b.median_wall_s)} ({change_text(delta.time_change)})"
    )
    errors = [f", A error: {e}" for e in a.errors] + [
        f", B error: {e}" for e in b.errors
    ]
    skipped = [
        f", {side} skipped {len(repeats)}: {reason}"
        for side, summary in (("A", a), ("B", b))
        for reason, repeats in summary.skipped.items()
    ]
    return line + "".join(errors + skipped)


def summary(deltas: Sequence[ScenarioDelta], footer: str) -> str:
    """Render a plain-text summary with one line per scenario."""
    found = sections(deltas)
    breaches = (f"Gate breach: {line}" for line in found.breaches)
    notes = (f"Gate info: {line}" for line in found.notes)
    return "\n".join(
        [*map(_summary_line, deltas), *breaches, *notes, *found.retried, footer]
    )


def summary_table(deltas: Sequence[ScenarioDelta], footer: str) -> Group:
    """Render a terminal summary table."""
    table = Table(box=box.SIMPLE_HEAD, padding=0, pad_edge=False)
    rows = [
        [
            column.terminal(delta) if column.terminal else column.cell(delta)
            for column in COLUMNS
        ]
        for delta in deltas
    ]
    kept = [i for i in range(len(COLUMNS)) if any(row[i] != "0" for row in rows)]
    for index in kept:
        table.add_column(
            _terminal_header(COLUMNS[index].header),
            justify="left" if index < 2 else "right",
            no_wrap=True,
        )
    for delta, row in zip(deltas, rows, strict=True):
        table.add_row(
            *(row[i] for i in kept), style="red" if regressed([delta]) else None
        )
    reused = sorted({r for d in deltas for s in (d.a, d.b) for r in s.reused_from})
    footnote = (
        [Text(f"* reused from {', '.join(reused)}, re-judged", style="dim")]
        if reused
        else []
    )
    found = sections(deltas)
    errors = (Text(line, style="red") for line in found.errors)
    skipped = (Text(line, style="yellow") for line in found.skipped)
    breaches = (Text(f"Gate breach: {line}", style="red") for line in found.breaches)
    notes = (Text(f"Gate info: {line}", style="yellow") for line in found.notes)
    retried = (Text(line, style="yellow") for line in found.retried)
    legend = [Text(SESSION_NOTE, style="dim")] if found.follow_ups else []
    return Group(
        table,
        *footnote,
        *legend,
        *errors,
        *skipped,
        *breaches,
        *notes,
        *retried,
        Text(footer),
    )


def show(report: Report) -> None:
    """Print the console summary: a rich table on a terminal, else plain text."""
    if (console := Console()).is_terminal:
        console.print(summary_table(report.scenarios, footer_text(report)))
    else:
        print(summary(report.scenarios, footer_text(report)), flush=True)
