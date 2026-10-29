"""Estimate the token cost of a run from past results."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from statistics import median

from llm_prompts.benchmark import paths
from llm_prompts.benchmark.types import Agent, ResultRow, Scenario

VARIANTS = 2


@dataclass(frozen=True)
class TokenEstimate:
    total_tokens: int
    unknown: tuple[tuple[str, Agent], ...]
    context: int
    cost_usd: float | None
    a_cells: int = 0
    reused_cells: int = 0
    saved_usd: float | None = None


def _past(
    key: Callable[[ResultRow], float | None],
) -> dict[tuple[str, str], list[float]]:
    history: dict[tuple[str, str], list[float]] = defaultdict(list)
    for path in paths.past_results():
        for line in path.read_text().splitlines():
            try:
                row = ResultRow.from_json(json.loads(line))
            except json.JSONDecodeError:
                continue
            value = key(row)
            if (
                row.error is None
                and value is not None
                and not row.reused_from
                and not row.skipped
            ):
                history[row.scenario, row.agent].append(value)
    return history


def estimate(
    scenarios: Sequence[Scenario],
    agents: Sequence[Agent],
    repeats: int,
    reused: Mapping[tuple[str, Agent], int] | None = None,
) -> TokenEstimate:
    """Estimate run tokens from the median past tokens of each scenario and agent, leaving out the A cells in ``reused``."""
    reused = reused or {}
    tokens = _past(lambda row: row.tokens.total)
    contexts = _past(lambda row: row.context or None)
    costs = _past(lambda row: row.cost_usd or None)
    total = 0
    unknown: list[tuple[str, Agent]] = []
    context = 0
    cost: float | None = 0.0
    saved = 0.0
    a_cells = 0
    for scenario in scenarios:
        for agent in agents:
            if agent not in scenario.agents:
                continue
            pair = (scenario.id, agent)
            a_cells += repeats
            if pair not in tokens:
                unknown.append(pair)
                continue
            runs = repeats * VARIANTS - reused.get(pair, 0)
            total += int(median(tokens[pair])) * runs
            if pair in contexts and runs:
                context = max(context, int(median(contexts[pair])))
            if cost is not None and pair in costs:
                cost += median(costs[pair]) * runs
                saved += median(costs[pair]) * reused.get(pair, 0)
            else:
                cost = None
    return TokenEstimate(
        total,
        tuple(unknown),
        context,
        cost,
        a_cells,
        sum(reused.values()),
        None if cost is None else saved,
    )
