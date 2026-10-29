"""Group results rows by scenario and agent and summarise each variant."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from math import sqrt
from statistics import median
from typing import Literal

from llm_prompts import size_report
from llm_prompts.benchmark.agents import AGENTS
from llm_prompts.benchmark.fail_fast import SETUP_ERROR
from llm_prompts.benchmark.types import Agent, Gate, Level, ResultRow
from llm_prompts.size_limits import COLLECTION_BYTES

BYTES_PER_KB = 1024
MIN_GATED_RUNS = 3
WILSON_Z = 1.96
Verdict = Literal["ok", "regressed", "all errored", "aborted"]


def rise(a: float | None, b: float | None) -> float | None:
    """Return the relative rise from ``a`` to ``b``, or None if either is missing or ``a`` is zero."""
    if a is None or b is None or not a:
        return None
    return (b - a) / a


@dataclass(frozen=True)
class Summary:
    passed: int = 0
    total: int = 0
    completed: int = 0
    reused: int = 0
    median_tokens: float = 0.0
    median_tool_calls: float = 0.0
    memory: Mapping[str, float] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    median_context: float = 0.0
    median_cost_usd: float | None = None
    chain_cost_usd: float | None = None
    chain_wall_s: float | None = None
    chain_runs: int = 0
    median_start_context: float = 0.0
    median_turns: float = 0.0
    median_wall_s: float = 0.0
    failed_test_runs: int = 0
    reused_from: tuple[str, ...] = ()
    skipped: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    startup_errors: int = 0
    retried: int = 0

    @property
    def skipped_total(self) -> int:
        """Number of runs skipped, left out of ``passed`` and ``total``, as are ``startup_errors``."""
        return sum(map(len, self.skipped.values()))

    @property
    def spend_usd(self) -> float | None:
        """Median cost times the runs counted, or None without a cost."""
        return (
            None if self.median_cost_usd is None else self.median_cost_usd * self.total
        )

    @property
    def time_s(self) -> float:
        """Median wall time times the runs counted."""
        return self.median_wall_s * self.total


@dataclass(frozen=True)
class ScenarioDelta:
    scenario: str
    agent: Agent
    gate: Gate
    a: Summary
    b: Summary
    follow_up_of: str | None = None
    fresh: bool = False
    headline: bool = False
    chain: tuple[str, ...] = ()

    @property
    def token_change(self) -> float | None:
        """Relative change in median tokens from A to B."""
        return rise(self.a.median_tokens, self.b.median_tokens)

    @property
    def context_change(self) -> float | None:
        """Relative change in median context from A to B."""
        return rise(self.a.median_context, self.b.median_context)

    @property
    def cost_change(self) -> float | None:
        """Relative change in this session's median cost from A to B."""
        return rise(self.a.median_cost_usd, self.b.median_cost_usd)

    @property
    def time_change(self) -> float | None:
        """Relative change in this session's median wall time from A to B."""
        return rise(self.a.median_wall_s, self.b.median_wall_s)

    @property
    def chain_cost_change(self) -> float | None:
        """Relative change in the median cost summed along the chain, from A to B."""
        return rise(self.a.chain_cost_usd, self.b.chain_cost_usd)

    @property
    def chain_time_change(self) -> float | None:
        """Relative change in the median wall time summed along the chain, from A to B."""
        return rise(self.a.chain_wall_s, self.b.chain_wall_s)


@dataclass(frozen=True)
class SizeChange:
    target: str
    a: int
    b: int
    change: int


@dataclass(frozen=True)
class PromptValue:
    agent: Agent
    bytes: int
    passes_gained: int
    extra_cost_usd: float | None

    @property
    def passes_per_kb(self) -> float | None:
        """Passing cells gained per KB of added prompt, or None without a gain."""
        if self.passes_gained <= 0 or self.bytes <= 0:
            return None
        return self.passes_gained / (self.bytes / BYTES_PER_KB)

    @property
    def cost_per_pass(self) -> float | None:
        """Extra cost per passing cell gained, or None without a gain or a cost."""
        if self.passes_gained <= 0 or self.extra_cost_usd is None:
            return None
        return self.extra_cost_usd / self.passes_gained


@dataclass(frozen=True)
class Usage:
    agent_tokens: int
    judge_tokens: int
    agent_cost_usd: float | None
    reused_runs: int = 0
    reused_cost_usd: float | None = None
    reused_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class JudgeReason:
    scenario: str
    agent: Agent
    variant: str
    repeat: int
    detail: str


@dataclass(frozen=True)
class Report:
    run_id: str
    a: str
    b: str
    level: Level
    agents: tuple[Agent, ...]
    verdict: Verdict
    scenarios: tuple[ScenarioDelta, ...]
    prompt_size: tuple[SizeChange, ...]
    prompt_size_missing: str | None
    usage: Usage
    judge_reasons: tuple[JudgeReason, ...] = ()


def _median(values: Sequence[float]) -> float:
    return median(values) if values else 0.0


def _skipped(rows: Sequence[ResultRow]) -> dict[str, tuple[int, ...]]:
    reasons: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if row.skipped:
            reasons[row.skipped].append(row.repeat)
    return {reason: tuple(sorted(repeats)) for reason, repeats in reasons.items()}


def _origins(rows: Sequence[ResultRow]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(row.reused_from for row in rows if row.reused_from))


def _summarise(all_rows: Sequence[ResultRow]) -> Summary:
    ran = [row for row in all_rows if not row.skipped]
    rows = [row for row in ran if not row.startup_error]
    completed = [row for row in rows if row.error is None]
    metrics: dict[str, list[float]] = defaultdict(list)
    for row in completed:
        for name, value in asdict(row.memory).items():
            metrics[name].append(float(value))
    costs = [row.cost_usd for row in completed if row.cost_usd is not None]
    return Summary(
        passed=sum(1 for row in rows if row.passed),
        total=len(rows),
        completed=len(completed),
        reused=sum(row.reused_from is not None for row in rows),
        reused_from=_origins(rows),
        median_tokens=_median([r.tokens.total for r in completed]),
        median_tool_calls=_median([r.tool_calls for r in completed]),
        memory={name: median(values) for name, values in metrics.items()},
        errors=tuple(dict.fromkeys(row.error for row in ran if row.error)),
        median_context=_median([r.context for r in completed]),
        median_cost_usd=median(costs) if costs else None,
        median_start_context=_median([r.start_context for r in completed]),
        median_turns=_median([r.turns for r in completed]),
        median_wall_s=_median([r.wall_s for r in completed]),
        failed_test_runs=sum(r.failed_test_runs for r in completed),
        skipped=_skipped([row for row in all_rows if row.skipped]),
        startup_errors=len(ran) - len(rows),
        retried=sum(1 for row in ran if row.retries),
    )


def _delta(scenario: str, agent: Agent, group: Sequence[ResultRow]) -> ScenarioDelta:
    first = group[0]
    return ScenarioDelta(
        scenario=scenario,
        agent=agent,
        gate=first.gate,
        a=_summarise([row for row in group if row.variant == "a"]),
        b=_summarise([row for row in group if row.variant == "b"]),
        follow_up_of=first.follow_up_of,
        fresh=first.fresh,
        headline=first.headline,
    )


def _ancestors(
    deltas: Mapping[tuple[str, Agent], ScenarioDelta], key: tuple[str, Agent]
) -> list[tuple[str, Agent]]:
    follow_up_of = deltas[key].follow_up_of
    if follow_up_of is None or (follow_up_of, key[1]) not in deltas:
        return []
    parent = (follow_up_of, key[1])
    return [parent, *_ancestors(deltas, parent)]


def _chain_totals(
    groups: Mapping[tuple[str, Agent], Sequence[ResultRow]],
    keys: Sequence[tuple[str, Agent]],
    variant: str,
) -> tuple[float | None, float | None, int]:
    """Return the median cost and wall time summed along ``keys``, and the repeats that finished every session.

    The cost is None if no such repeat has every cost.
    """
    repeats: dict[int, list[ResultRow]] = defaultdict(list)
    for key in keys:
        for row in groups[key]:
            if row.variant == variant and not row.skipped and not row.error:
                repeats[row.repeat].append(row)
    whole = [rows for rows in repeats.values() if len(rows) == len(keys)]
    costs = [
        sum(row.cost_usd or 0.0 for row in rows)
        for rows in whole
        if all(row.cost_usd is not None for row in rows)
    ]
    walls = [sum(row.wall_s for row in rows) for rows in whole]
    return (
        median(costs) if costs else None,
        median(walls) if walls else None,
        len(whole),
    )


def _gate_over_chains(
    deltas: dict[tuple[str, Agent], ScenarioDelta],
    groups: Mapping[tuple[str, Agent], Sequence[ResultRow]],
) -> None:
    """Give each last scenario of a chain the cost and time summed from the chain's base."""
    followed = {(delta.follow_up_of, delta.agent) for delta in deltas.values()}
    for key, delta in list(deltas.items()):
        if key in followed:
            continue
        path = [*reversed(_ancestors(deltas, key)), key]
        a, b = (_chain_totals(groups, path, variant) for variant in ("a", "b"))
        deltas[key] = replace(
            delta,
            chain=tuple(scenario for scenario, _ in path),
            a=replace(delta.a, chain_cost_usd=a[0], chain_wall_s=a[1], chain_runs=a[2]),
            b=replace(delta.b, chain_cost_usd=b[0], chain_wall_s=b[1], chain_runs=b[2]),
        )


def compare(rows: Sequence[ResultRow]) -> list[ScenarioDelta]:
    """Group result rows by scenario and agent and compare variant A with variant B.

    A follow-up comes right after the scenario it follows up.
    Cost and time are gated once per chain, from a base to its last follow-up. A scenario without follow-ups is a chain of one.
    """
    groups: dict[tuple[str, Agent], list[ResultRow]] = defaultdict(list)
    for row in rows:
        groups[row.scenario, row.agent].append(row)
    deltas = {key: _delta(*key, group) for key, group in sorted(groups.items())}
    _gate_over_chains(deltas, groups)
    followers: dict[tuple[str, Agent] | None, list[tuple[str, Agent]]] = defaultdict(
        list
    )
    for key, delta in deltas.items():
        parent = (delta.follow_up_of, delta.agent)
        followers[parent if parent in deltas else None].append(key)

    def chain(key: tuple[str, Agent]) -> list[ScenarioDelta]:
        return [deltas[key], *(d for child in followers[key] for d in chain(child))]

    return [delta for key in followers[None] for delta in chain(key)]


def wilson(passed: int, total: int) -> tuple[float, float]:
    """Return the Wilson score interval of a pass rate at 95% confidence."""
    if not total:
        return 0.0, 1.0
    p, z2 = passed / total, WILSON_Z**2
    centre = (p + z2 / (2 * total)) / (1 + z2 / total)
    half = WILSON_Z * sqrt(p * (1 - p) / total + z2 / (4 * total**2)) / (1 + z2 / total)
    return max(0.0, centre - half), min(1.0, centre + half)


def interval_text(summary: Summary) -> str:
    """Return the 95% interval of a summary's pass rate, such as ``44-100%``."""
    low, high = wilson(summary.passed, summary.total)
    return f"{low:.0%}-{high:.0%}"


def _intervals_apart(a: Summary, b: Summary) -> bool:
    return wilson(b.passed, b.total)[1] < wilson(a.passed, a.total)[0]


@dataclass(frozen=True)
class _Rise:
    name: str
    change: float
    max_rise: float
    a_runs: int
    b_runs: int
    chain: tuple[str, ...] = ()

    @property
    def gated(self) -> bool:
        return min(self.a_runs, self.b_runs) >= MIN_GATED_RUNS

    @property
    def runs(self) -> str:
        return "chain runs" if len(self.chain) > 1 else "runs"

    def where(self, delta: ScenarioDelta) -> str:
        return " > ".join(self.chain) if len(self.chain) > 1 else delta.scenario


def _rises(delta: ScenarioDelta) -> list[_Rise]:
    a, b, gate = delta.a, delta.b, delta.gate
    checks: list[tuple[str, float | None, float, int, int, tuple[str, ...]]] = [
        ("context", delta.context_change, gate.max_context_rise, a.completed, b.completed, ())
    ]  # fmt: skip
    if delta.chain:
        checks += [
            ("cost", delta.chain_cost_change, gate.max_cost_rise, a.chain_runs, b.chain_runs, delta.chain),
            ("time", delta.chain_time_change, gate.max_time_rise, a.chain_runs, b.chain_runs, delta.chain),
        ]  # fmt: skip
    return [
        _Rise(name, change, max_rise, a_runs, b_runs, chain)
        for name, change, max_rise, a_runs, b_runs, chain in checks
        if change is not None and change > max_rise
    ]


def _breaches(delta: ScenarioDelta) -> list[str]:
    if not delta.a.total or not delta.b.total:
        return []
    a, b, gate = delta.a, delta.b, delta.gate
    prefix = f"{delta.scenario} {delta.agent}"
    breaches: list[str] = []
    if (
        drop := a.passed / a.total - b.passed / b.total
    ) >= gate.max_pass_drop and _intervals_apart(a, b):
        breaches.append(
            f"{prefix}: pass rate {a.passed}/{a.total} -> {b.passed}/{b.total} "
            f"(drop {drop:.0%}, limit {gate.max_pass_drop:.0%}, 95% intervals "
            f"{interval_text(a)} and {interval_text(b)} do not overlap)"
        )
    breaches += [
        f"{rise_.where(delta)} {delta.agent}: {rise_.name} {rise_.change:+.0%} "
        f"(limit {rise_.max_rise:+.0%}, median of {rise_.a_runs} A and "
        f"{rise_.b_runs} B {rise_.runs})"
        for rise_ in _rises(delta)
        if rise_.gated
    ]
    return breaches


def gate_notes(deltas: Sequence[ScenarioDelta]) -> tuple[str, ...]:
    """Return one line per rule left out of the gate for want of enough runs or a clear difference."""
    return tuple(line for delta in deltas for line in _notes(delta))


def _notes(delta: ScenarioDelta) -> list[str]:
    a, b = delta.a, delta.b
    notes = [
        f"{rise_.where(delta)} {delta.agent}: {rise_.name} {rise_.change:+.0%} over limit "
        f"{rise_.max_rise:+.0%}, not gated (needs {MIN_GATED_RUNS} completed "
        f"{rise_.runs} on each side, has {rise_.a_runs} A and {rise_.b_runs} B)"
        for rise_ in _rises(delta)
        if not rise_.gated
    ]
    if (
        a.total
        and b.total
        and a.passed / a.total - b.passed / b.total >= delta.gate.max_pass_drop
        and not _intervals_apart(a, b)
    ):
        notes.append(
            f"{delta.scenario} {delta.agent}: pass rate {a.passed}/{a.total} -> "
            f"{b.passed}/{b.total} drops over limit {delta.gate.max_pass_drop:.0%}, "
            f"not gated (95% intervals {interval_text(a)} and {interval_text(b)} overlap)"
        )
    return notes


def gate_breaches(deltas: Sequence[ScenarioDelta]) -> tuple[str, ...]:
    """Return one line per gate rule a scenario breaches, naming the scenario, agent and rule."""
    return tuple(line for delta in deltas for line in _breaches(delta))


def regressed(deltas: Sequence[ScenarioDelta]) -> bool:
    """Return whether any scenario breaches its gate."""
    return any(_breaches(delta) for delta in deltas)


def verdict(rows: Sequence[ResultRow], deltas: Sequence[ScenarioDelta]) -> Verdict:
    """Return the overall gate verdict for a run."""
    if any((row.skipped or "").startswith(SETUP_ERROR) for row in rows):
        return "aborted"
    ran = [row for row in rows if not row.skipped]
    if all(row.error is not None for row in ran):
        return "all errored"
    return "regressed" if regressed(deltas) else "ok"


def _agent_cost(rows: Sequence[ResultRow]) -> float | None:
    costs = [
        cost
        for row in rows
        for cost in (row.cost_usd, row.retry_cost_usd)
        if cost is not None
    ]
    return sum(costs) if costs else None


def usage(rows: Sequence[ResultRow]) -> Usage:
    """Sum the agent tokens and cost of every row run now, errored ones included, the judge tokens of every row, and count reused rows apart."""
    fresh = [row for row in rows if row.reused_from is None]
    reused = [row for row in rows if row.reused_from is not None]
    return Usage(
        sum(row.tokens.total for row in fresh),
        sum(row.judge_tokens for row in rows),
        _agent_cost(fresh),
        len(reused),
        _agent_cost(reused),
        _origins(reused),
    )


def judge_reasons(rows: Sequence[ResultRow]) -> tuple[JudgeReason, ...]:
    """Return the full detail of every failed judge check."""
    return tuple(
        JudgeReason(row.scenario, row.agent, row.variant, row.repeat, check.detail)
        for row in rows
        for check in row.checks
        if check.kind == "judge" and not check.passed
    )


def usage_summary(used: Usage) -> str:
    """Summarise the actual token use on one line."""
    line = (
        f"Actual tokens: {used.agent_tokens + used.judge_tokens:,} "
        f"(agent {used.agent_tokens:,}, judge {used.judge_tokens:,})"
    )
    if used.agent_cost_usd is not None:
        line += f", agent cost ${used.agent_cost_usd:.2f}"
    if used.reused_runs:
        source = f" from {', '.join(used.reused_from)}" if used.reused_from else ""
        line += f". Reused runs: {used.reused_runs}{source}"
        if used.reused_cost_usd is not None:
            line += f" (agent cost ${used.reused_cost_usd:.2f}, not re-spent, judge run again)"
    return line


def size_changes(rows: Sequence[size_report.Row]) -> tuple[SizeChange, ...]:
    """Return the per-target prompt size changes in bytes."""
    return tuple(
        SizeChange(
            target, row.base or 0, row.head or 0, (row.head or 0) - (row.base or 0)
        )
        for row in rows
        if row.metric == COLLECTION_BYTES
        for target in row.targets
    )


def size_summary(changes: Sequence[SizeChange]) -> str:
    """Summarise the per-target prompt size change on one line."""
    parts = ", ".join(
        f"{change.target} {change.change:+,} bytes"
        if change.change
        else f"{change.target} 0 bytes"
        for change in changes
    )
    return f"Prompt size: {parts or 'no change'}"


def _paired_sums(
    deltas: Sequence[ScenarioDelta], measure: Callable[[Summary], float | None]
) -> tuple[float | None, float | None]:
    pairs = [(measure(delta.a), measure(delta.b)) for delta in deltas]
    priced = [(a, b) for a, b in pairs if a is not None and b is not None]
    if not priced:
        return None, None
    return sum(a for a, _ in priced), sum(b for _, b in priced)


def _overall_result(report: Report, gained: int) -> str:
    if report.verdict == "regressed" or gained < 0:
        return "regressed"
    fell = any(
        delta.b.passed * delta.a.total < delta.a.passed * delta.b.total
        for delta in report.scenarios
    )
    return "improved" if gained > 0 and not fell else "no change"


def change_text(value: float | None) -> str:
    return "-" if value is None else f"{value:+.0%}"


def cost_text(value: float | None) -> str:
    return "-" if value is None else f"${value:.2f}"


def prompt_values(report: Report) -> tuple[PromptValue, ...]:
    """Return the passing cells and cost gained for each agent whose prompt size changed."""
    values: list[PromptValue] = []
    for agent in report.agents:
        deltas = [delta for delta in report.scenarios if delta.agent == agent]
        for change in report.prompt_size:
            if change.target == AGENTS[agent].template_name and change.change:
                a_cost, b_cost = _paired_sums(deltas, lambda s: s.spend_usd)
                values.append(
                    PromptValue(
                        agent,
                        change.change,
                        sum(d.b.passed - d.a.passed for d in deltas),
                        None if a_cost is None or b_cost is None else b_cost - a_cost,
                    )
                )
    return tuple(values)


def _prompt_summary(value: PromptValue) -> str:
    line = f"Prompt: {value.agent} {value.bytes:+,} bytes"
    if value.bytes < 0:
        return f"{line}, passing cells {value.passes_gained:+d}."
    if value.passes_per_kb is None:
        return f"{line}, no passes gained."
    line += f" = {value.passes_per_kb:+.2f} passing cells per KB"
    if (cost := value.cost_per_pass) is not None:
        line += (
            ", no extra cost"
            if round(cost, 2) == 0
            else f", {'-' if cost < 0 else ''}${abs(cost):.2f} per extra pass"
        )
    return line + "."


def _headline(delta: ScenarioDelta) -> str:
    a, b = delta.a, delta.b
    return (
        f"payoff {delta.scenario} {delta.agent} pass rate {a.passed}/{a.total} to "
        f"{b.passed}/{b.total}, cost {cost_text(a.chain_cost_usd)} to {cost_text(b.chain_cost_usd)} "
        f"({change_text(delta.chain_cost_change)}), failed test runs {a.failed_test_runs} to {b.failed_test_runs}."
    )


def outcome_summary(report: Report) -> str:
    """Summarise B against A: the overall result on one line, then the value of each agent's added prompt."""
    deltas = report.scenarios
    a_passed, b_passed = (
        sum(d.a.passed for d in deltas),
        sum(d.b.passed for d in deltas),
    )
    headlines = "".join(f"{_headline(delta)} " for delta in deltas if delta.headline)
    overall = (
        f"Overall: {headlines}B {_overall_result(report, b_passed - a_passed)}. Pass rate "
        f"{a_passed}/{sum(d.a.total for d in deltas)} to "
        f"{b_passed}/{sum(d.b.total for d in deltas)} ({b_passed - a_passed:+d} cells), "
        f"cost {change_text(rise(*_paired_sums(deltas, lambda s: s.spend_usd)))}, "
        f"time {change_text(rise(*_paired_sums(deltas, lambda s: s.time_s)))}."
    )
    return "\n".join([overall, *map(_prompt_summary, prompt_values(report))])
