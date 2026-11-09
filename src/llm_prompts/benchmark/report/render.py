"""Render the benchmark comparison as markdown and JSON."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

from llm_prompts.benchmark.report.compare import (
    Report,
    ScenarioDelta,
    SizeChange,
    Summary,
    b_label,
    change_text,
    cost_text,
    gate_breaches,
    gate_notes,
    interval_text,
    outcome_summary,
    usage_summary,
)

SESSION_NOTE = (
    "Cost and time are each session's own. A follow-up row counts only its own session."
    " The cost and time gates apply to each whole chain, from its base to its last follow-up, listed under Chains."
)
CHAIN_COLUMNS = ("Chain", "Agent", "Cost A", "Cost B", "Cost change") + (
    "Time A",
    "Time B",
    "Time change",
    "Runs A",
    "Runs B",
)
GATE_TEXT = {
    "all errored": "every run errored",
    "incomplete": "a side only had startup errors",
    "aborted": "aborted by a setup error",
}


@dataclass(frozen=True)
class Sections:
    errors: list[str]
    skipped: list[str]
    retried: list[str]
    breaches: tuple[str, ...]
    notes: tuple[str, ...]
    follow_ups: bool


def sections(deltas: Sequence[ScenarioDelta]) -> Sections:
    """Return the error, skip, retry and gate lines of ``deltas`` and whether any is a follow-up."""
    sides = [
        (delta, side, summary)
        for delta in deltas
        for side, summary in (("A", delta.a), ("B", delta.b))
    ]
    retried = sum(summary.retried for _, _, summary in sides)
    return Sections(
        errors=[
            f"- {delta.scenario} {delta.agent} {side}: {error}"
            for delta, side, summary in sides
            for error in summary.errors
        ],
        skipped=[
            f"- {delta.scenario} {delta.agent} {side}: "
            + ", ".join(f"#{repeat + 1}" for repeat in repeats)
            + f" skipped, {reason}"
            for delta, side, summary in sides
            for reason, repeats in summary.skipped.items()
        ],
        retried=[f"Retried runs: {retried}."] if retried else [],
        breaches=gate_breaches(deltas),
        notes=gate_notes(deltas),
        follow_ups=any(delta.follow_up_of for delta in deltas),
    )


def _time(seconds: float) -> str:
    return f"{seconds:.0f}s"


def _md_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _md_table(columns: Sequence[str], rows: Sequence[str]) -> str:
    return "\n".join([_md_row(columns), "|" + " --- |" * len(columns), *rows])


def _memory(summary: Summary) -> str:
    return (
        ", ".join(f"{name}={value:g}" for name, value in sorted(summary.memory.items()))
        or "-"
    )


def _pass(summary: Summary, interval: bool = True) -> str:
    text = f"{summary.passed}/{summary.total}"
    if interval and summary.total:
        text += f" [{interval_text(summary)}]"
    if summary.reused:
        count = "" if summary.reused == summary.total else f"{summary.reused} "
        text += f" ({count}reused from {', '.join(summary.reused_from)}, re-judged)"
    if summary.skipped_total:
        text += f" ({summary.skipped_total} skipped)"
    if summary.startup_errors:
        text += (
            f" (+{summary.startup_errors} error{'s' * (summary.startup_errors > 1)})"
        )
    return text


def _name(delta: ScenarioDelta) -> str:
    if delta.follow_up_of is None:
        return delta.scenario
    kind = "fresh follow-up" if delta.fresh else "follow-up"
    return f"{delta.scenario} -> {kind} of {delta.follow_up_of}"


@dataclass(frozen=True)
class Column:
    header: str
    cell: Callable[[ScenarioDelta], str]
    terminal: Callable[[ScenarioDelta], str] | None = None


def _pair(
    header: str,
    cell: Callable[[Summary], str],
    terminal: Callable[[Summary], str] | None = None,
) -> list[Column]:
    def column(side: str, pick: Callable[[ScenarioDelta], Summary]) -> Column:
        return Column(
            f"{header} {side}",
            lambda delta: cell(pick(delta)),
            (lambda delta: terminal(pick(delta))) if terminal else None,
        )

    return [column("A", lambda d: d.a), column("B", lambda d: d.b)]


def _terminal_name(delta: ScenarioDelta) -> str:
    if delta.follow_up_of is None:
        return delta.scenario
    return f"  ↳ {delta.scenario}" + (" (fresh)" if delta.fresh else "")


def _terminal_pass(summary: Summary) -> str:
    return (
        _pass(summary, interval=False)
        .split(" (reused")[0]
        .replace(
            f"{summary.passed}/{summary.total}",
            f"{summary.passed}/{summary.total}" + ("*" if summary.reused else ""),
            1,
        )
    )


COLUMNS = (
    Column("Scenario", lambda d: _name(d), _terminal_name),
    Column("Agent", lambda d: d.agent),
    *_pair("Pass", lambda s: _pass(s), _terminal_pass),
    *_pair(
        "Context",
        lambda s: f"{s.median_start_context:,.0f}->{s.median_context:,.0f}",
        lambda s: f"{s.median_start_context:,.0f}",
    ),
    Column("Context change", lambda d: change_text(d.context_change)),
    *_pair("Cost", lambda s: cost_text(s.median_cost_usd)),
    Column("Cost change", lambda d: change_text(d.cost_change)),
    *_pair("Time", lambda s: _time(s.median_wall_s)),
    Column("Time change", lambda d: change_text(d.time_change)),
    *_pair("Turns", lambda s: f"{s.median_turns:g}"),
    *_pair("Failed tests", lambda s: str(s.failed_test_runs)),
)
_MARKDOWN_COLUMNS = (*COLUMNS, *_pair("Memory", lambda s: _memory(s)))


def _row(delta: ScenarioDelta) -> str:
    return _md_row([column.cell(delta) for column in _MARKDOWN_COLUMNS])


def _chain_row(delta: ScenarioDelta) -> str:
    a, b = delta.a, delta.b
    return _md_row(
        [
            " > ".join(delta.chain),
            delta.agent,
            cost_text(a.chain_cost_usd),
            cost_text(b.chain_cost_usd),
            change_text(delta.chain_cost_change),
            _time(a.chain_wall_s) if a.chain_wall_s is not None else "-",
            _time(b.chain_wall_s) if b.chain_wall_s is not None else "-",
            change_text(delta.chain_time_change),
            str(a.chain_runs),
            str(b.chain_runs),
        ]
    )


def _chains(deltas: Sequence[ScenarioDelta]) -> list[str]:
    chains = [delta for delta in deltas if len(delta.chain) > 1]
    if not chains:
        return []
    return ["## Chains\n\n" + _md_table(CHAIN_COLUMNS, [*map(_chain_row, chains)])]


def _judge_reasons(report: Report) -> list[str]:
    return [
        f"- {reason.scenario} {reason.agent} {reason.variant.upper()} #{reason.repeat + 1}: "
        + " ".join(reason.detail.split())
        for reason in report.judge_reasons
    ]


def _size_line(change: SizeChange) -> str:
    return f"- {change.target}: {change.a:,} -> {change.b:,} bytes ({change.change:+,})"


def _prompt_size(report: Report) -> list[str]:
    if report.prompt_size_missing:
        return [report.prompt_size_missing]
    return [*map(_size_line, report.prompt_size)] or ["No change."]


def _problems(report: Report, found: Sections) -> list[str]:
    return [
        *(["\n".join(["Errors:", *found.errors])] if found.errors else []),
        *(["\n".join(["Skipped:", *found.skipped])] if found.skipped else []),
        *(
            ["\n".join(["## Judge reasons", "", *_judge_reasons(report)])]
            if report.judge_reasons
            else []
        ),
    ]


def render(report: Report) -> str:
    """Render a report as markdown."""
    found = sections(report.scenarios)
    table = (
        _md_table(
            [column.header for column in _MARKDOWN_COLUMNS],
            [_row(d) for d in report.scenarios],
        )
        if report.scenarios
        else "No scenarios ran."
    )
    gate = GATE_TEXT.get(report.verdict, report.verdict)
    parts = [
        f"# Benchmark {report.a} -> {b_label(report)}",
        (
            f"Run {report.run_id}, level {report.level}, agents {', '.join(report.agents)}. Gate: {gate}."
            + (
                "\n\n"
                + "\n".join(["Gate breaches:", *(f"- {b}" for b in found.breaches)])
                if found.breaches
                else ""
            )
            + (
                "\n\n" + "\n".join(["Gate info:", *(f"- {n}" for n in found.notes)])
                if found.notes
                else ""
            )
        ),
        usage_summary(report.usage),
        table,
        *([SESSION_NOTE] if found.follow_ups else []),
        *_chains(report.scenarios),
        *found.retried,
        *_problems(report, found),
        "\n".join(["## Prompt size", "", *_prompt_size(report)]),
        "\n".join(["## Overall", "", outcome_summary(report)]),
    ]
    return "\n\n".join(parts) + "\n"


def to_json(report: Report) -> str:
    """Render a report as JSON."""
    data = {
        "schema": 1,
        **asdict(report),
        "summary": outcome_summary(report).splitlines(),
        "gate_breaches": gate_breaches(report.scenarios),
        "gate_notes": gate_notes(report.scenarios),
    }
    for entry, delta in zip(data["scenarios"], report.scenarios, strict=True):
        entry["token_change"] = delta.token_change
        entry["context_change"] = delta.context_change
        entry["cost_change"] = delta.cost_change
        entry["time_change"] = delta.time_change
        entry["chain_cost_change"] = delta.chain_cost_change
        entry["chain_time_change"] = delta.chain_time_change
    return json.dumps(data, indent=2) + "\n"
